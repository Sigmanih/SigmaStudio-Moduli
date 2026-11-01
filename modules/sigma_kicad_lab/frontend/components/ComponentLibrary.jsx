// =============================================================================
// ComponentLibrary — scegliere un componente e metterlo in scheda
// =============================================================================
// Il pannello che c'era prima chiedeva di **scrivere a mano** il nome della
// libreria e quello del footprint, poi premeva «Cerca», e i risultati non li
// mostrava nemmeno: la rotta risponde `risultati` e il codice leggeva
// `footprints`/`results`, due chiavi che non esistono. Chi lo usava doveva
// ricordarsi a memoria che `R_0805_2012Metric` sta in `Resistor_SMD`.
//
// Qui si fa il contrario: si cerca, si sceglie da un elenco, il riferimento
// libero viene proposto da solo e la posizione si puo' ripetere con un passo.
// La ricerca passa dall'indice del server (`var/cache/kicad`), quindi la prima
// volta costa la costruzione e tutte le successive un millisecondo.
//
// **Il pannello non scrive da solo.** Ogni inserimento chiama `inserisci`, che
// e' lo stesso gesto del trascinamento sulla canvas: la rotta del modulo apre
// il progetto, esegue il tool dell'agente e rifa' la copia di sicurezza. Due
// strade per la stessa modifica divergono, e divergono sulle validazioni.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Search, X, Plus, Repeat, MapPin, Boxes, Loader2,
} from 'lucide-react';
import { getJson, postTool } from '../lib/pcbApi';

const CHIAVE_RECENTI = 'sigma.pcb.componenti_recenti';
const LIMITE_RISULTATI = 40;
const ATTESA_RICERCA = 220;
const MAX_RECENTI = 6;

//: Che prefisso tocca a un pezzo. Si guarda prima la libreria e poi il nome del
//: footprint: `Resistor_SMD:R_0805_2012Metric` e `Device:R` devono dare `R`
//: entrambi, o la numerazione riparte da R1 sopra un R1 che c'e' gia'.
const PREFISSI = [
  [/resistor|resistenza|^R[_0-9]/i, 'R'],
  [/capacitor|condensator|^C[_0-9]/i, 'C'],
  [/inductor|inductor|^L[_0-9]/i, 'L'],
  [/led/i, 'LED'],
  [/diode|^D[_0-9]/i, 'D'],
  [/transistor|mosfet|^Q[_0-9]/i, 'Q'],
  [/crystal|oscillator|^Y[_0-9]/i, 'Y'],
  [/connector|conn_|^J[_0-9]/i, 'J'],
  [/pin_header|header|^P[_0-9]/i, 'P'],
  [/switch|button|tact|^SW/i, 'SW'],
  [/fuse|^F[_0-9]/i, 'F'],
  [/relay|^K[_0-9]/i, 'K'],
  [/test_point|fiducial|^TP/i, 'TP'],
  [/mounting|hole/i, 'H'],
  [/battery/i, 'BT'],
  [/sensor|ic|micro|^U[_0-9]/i, 'U'],
];

/** Le voci usate di recente, dal browser. Un localStorage illeggibile non deve
 *  rompere il pannello: si riparte da un elenco vuoto. */
function leggiRecenti() {
  try {
    const grezzo = window.localStorage.getItem(CHIAVE_RECENTI);
    const voci = grezzo ? JSON.parse(grezzo) : [];
    return Array.isArray(voci) ? voci.filter((v) => v && v.footprint) : [];
  } catch {
    return [];
  }
}

function salvaRecenti(voci) {
  try {
    window.localStorage.setItem(CHIAVE_RECENTI, JSON.stringify(voci));
  } catch {
    // Spazio pieno o localStorage spento: i recenti sono comodita', non stato.
  }
}

/** Il prefisso giusto per una voce della libreria. */
function prefissoPer(libreria, footprint) {
  const testo = `${libreria || ''}:${footprint || ''}`;
  for (const [prova, prefisso] of PREFISSI) {
    if (prova.test(testo)) return prefisso;
  }
  return 'U';
}

/**
 * Il primo riferimento libero per quel prefisso.
 *
 * I numeri si leggono dai pezzi che stanno in scheda: proporre `R1` quando `R1`
 * c'e' gia' fa fallire l'inserimento con un errore che l'utente non ha modo di
 * prevenire.
 */
function prossimoRiferimento(componenti, prefisso) {
  let massimo = 0;
  const modello = new RegExp(`^${prefisso}(\\d+)$`, 'i');
  for (const pezzo of componenti || []) {
    const trovato = modello.exec(String(pezzo.reference || '').trim());
    if (trovato) massimo = Math.max(massimo, Number(trovato[1]));
  }
  return `${prefisso}${massimo + 1}`;
}


/**
 * @param {boolean} isLight  il tema dell'applicazione, per le classi CSS
 * @param {object}  scheda   la scheda aperta: serve per i riferimenti liberi
 * @param {boolean} busy     una scrittura e' in corso sulla scheda
 * @param {Function} inserisci  async (dati) => esito | null — la stessa mano
 *                              dell'agente, via `/api/kicad/part/add`
 */
export default function ComponentLibrary({ isLight, scheda, busy, inserisci }) {
  const [librerie, setLibrerie] = useState([]);
  const [libreriaScelta, setLibreriaScelta] = useState('');
  const [query, setQuery] = useState('');
  const [risultati, setRisultati] = useState(null);
  const [totaleTrovati, setTotaleTrovati] = useState(0);
  const [troncato, setTroncato] = useState(false);
  const [daIndice, setDaIndice] = useState(null);
  const [inRicerca, setInRicerca] = useState(false);
  const [erroreRicerca, setErroreRicerca] = useState(null);
  const [scelto, setScelto] = useState(null);
  const [recenti, setRecenti] = useState(() => leggiRecenti());

  const [riferimento, setRiferimento] = useState('');
  const [valore, setValore] = useState('');
  const [x, setX] = useState('10');
  const [y, setY] = useState('10');
  const [rotazione, setRotazione] = useState(0);
  const [lato, setLato] = useState('top');
  const [passo, setPasso] = useState('5');

  const [inCorso, setInCorso] = useState(false);
  const [esito, setEsito] = useState(null);
  const [errore, setErrore] = useState(null);

  //: L'ultima richiesta partita: una risposta vecchia che arriva dopo una nuova
  //: non deve sovrascrivere quella giusta.
  const richiesta = useRef(0);
  const campoRicerca = useRef(null);

  // --- librerie -------------------------------------------------------------

  useEffect(() => {
    let vivo = true;
    getJson('/api/kicad/libraries')
      .then((dati) => {
        if (!vivo) return;
        const elenco = dati.librerie || dati.libraries || [];
        setLibrerie(Array.isArray(elenco) ? elenco : []);
      })
      .catch(() => {
        // Senza elenco si cerca comunque fra tutte: il filtro per libreria e'
        // una comodita', non un requisito.
        if (vivo) setLibrerie([]);
      });
    return () => { vivo = false; };
  }, []);

  // --- posizione iniziale al centro della scheda ----------------------------

  useEffect(() => {
    if (!scheda) return;
    setX((precedente) => (precedente === '10' ? String(Math.round(scheda.larghezza / 2)) : precedente));
    setY((precedente) => (precedente === '10' ? String(Math.round(scheda.altezza / 2)) : precedente));
  }, [scheda]);

  // --- ricerca, con un'attesa breve fra un tasto e l'altro ------------------

  useEffect(() => {
    const cercato = query.trim();
    if (!cercato && !libreriaScelta) {
      setRisultati(null);
      setTotaleTrovati(0);
      setTroncato(false);
      setErroreRicerca(null);
      return undefined;
    }
    const mia = richiesta.current + 1;
    richiesta.current = mia;
    setInRicerca(true);
    const timer = window.setTimeout(async () => {
      try {
        const dati = await postTool('/api/kicad/footprint/search', {
          query: cercato,
          libreria: libreriaScelta,
          limite: LIMITE_RISULTATI,
        });
        if (richiesta.current !== mia) return;      // superata da una piu' nuova
        const trovati = Array.isArray(dati.risultati) ? dati.risultati : [];
        setRisultati(trovati);
        setTotaleTrovati(Number(dati.totale) || trovati.length);
        setTroncato(Boolean(dati.troncato));
        setDaIndice(dati.da_indice === undefined ? null : Boolean(dati.da_indice));
        setErroreRicerca(null);
      } catch (err) {
        if (richiesta.current !== mia) return;
        setRisultati([]);
        setTotaleTrovati(0);
        setErroreRicerca(err.message || String(err));
      } finally {
        if (richiesta.current === mia) setInRicerca(false);
      }
    }, ATTESA_RICERCA);
    return () => window.clearTimeout(timer);
  }, [query, libreriaScelta]);


  // --- scelta e inserimento -------------------------------------------------

  const scegli = useCallback((voce) => {
    setScelto({ libreria: voce.libreria, footprint: voce.footprint });
    setErrore(null);
    setEsito(null);
    setRiferimento((precedente) => {
      if (precedente.trim()) return precedente;
      const prefisso = prefissoPer(voce.libreria, voce.footprint);
      return prossimoRiferimento(scheda ? scheda.componenti : [], prefisso);
    });
  }, [scheda]);

  const ricorda = useCallback((voce) => {
    const altre = recenti.filter(
      (v) => !(v.libreria === voce.libreria && v.footprint === voce.footprint),
    );
    const aggiornati = [voce, ...altre].slice(0, MAX_RECENTI);
    setRecenti(aggiornati);
    salvaRecenti(aggiornati);
  }, [recenti]);

  /**
   * Inserisce il pezzo scelto. `ripeti` serve a popolare: dopo un inserimento
   * il riferimento avanza e la posizione si sposta del passo, cosi' venti
   * resistenze non finiscono una sopra l'altra.
   */
  const conferma = useCallback(async (ripeti) => {
    if (!scelto) {
      setErrore('Scegli prima un componente dall\'elenco.');
      return;
    }
    if (!riferimento.trim()) {
      setErrore('Serve un riferimento (es. R1): e\' il nome con cui la scheda lo conosce.');
      return;
    }
    setInCorso(true);
    setErrore(null);
    setEsito(null);
    try {
      const dati = await inserisci({
        libreria: scelto.libreria,
        footprint: scelto.footprint,
        riferimento: riferimento.trim(),
        valore,
        x_mm: Number(x) || 0,
        y_mm: Number(y) || 0,
        rotazione: Number(rotazione) || 0,
        lato,
      });
      if (!dati) return;                       // l'errore lo mostra la scheda
      const messo = `${dati.riferimento || riferimento} in scheda`;
      setEsito(messo);
      ricorda(scelto);
      if (!ripeti) return;
      const prefisso = prefissoPer(scelto.libreria, scelto.footprint);
      setRiferimento(prossimoRiferimento(scheda ? scheda.componenti : [], prefisso));
      const scarto = Number(passo) || 0;
      setX((precedente) => String(Math.round((Number(precedente) + scarto) * 100) / 100));
    } catch (err) {
      setErrore(err.message || String(err));
    } finally {
      setInCorso(false);
    }
  }, [inserisci, lato, passo, riferimento, ricorda, rotazione, scheda, scelto, valore, x, y]);

  const alTastoRicerca = useCallback((evento) => {
    if (evento.key === 'Enter' && risultati && risultati.length) {
      evento.preventDefault();
      scegli(risultati[0]);
    }
    if (evento.key === 'Escape') {
      setQuery('');
      setRisultati(null);
    }
  }, [risultati, scegli]);

  // --- cosa mostrare nell'elenco --------------------------------------------

  const voci = useMemo(() => {
    if (risultati) return risultati.map((v) => ({ ...v, recente: false }));
    return recenti.map((v) => ({ ...v, recente: true }));
  }, [risultati, recenti]);

  const occupato = Boolean(busy || inCorso);
  const nulla = !query.trim() && !libreriaScelta;


  return (
    <section className={`pcblib ${isLight ? '' : 'pcblib--scuro'}`}>
      <div className="pcblib__testa">
        <span className="pcblib__titolo">
          <Boxes size={14} /> Componenti
        </span>
        <span className="pcblib__conta">
          {risultati
            ? `${totaleTrovati}${troncato ? ` (primi ${risultati.length})` : ''}`
            : `${librerie.length || '—'} librerie`}
        </span>
      </div>

      <div className="pcblib__cerca">
        <Search size={13} />
        <input
          ref={campoRicerca}
          className="pcblib__input"
          type="search"
          value={query}
          placeholder="Cerca un componente: R_0805, SOT-23, ESP32…"
          aria-label="Cerca un footprint nelle librerie KiCad"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={alTastoRicerca}
        />
        {query && (
          <button
            type="button"
            className="pcblib__pulisci"
            title="Pulisci la ricerca"
            onClick={() => { setQuery(''); setRisultati(null); }}
          >
            <X size={12} />
          </button>
        )}
      </div>

      {librerie.length > 0 && (
        <div className="pcblib__librerie" role="group" aria-label="Filtra per libreria">
          <button
            type="button"
            className={`pcblib__chip ${libreriaScelta ? '' : 'pcblib__chip--attivo'}`}
            aria-pressed={!libreriaScelta}
            onClick={() => setLibreriaScelta('')}
          >
            tutte
          </button>
          {librerie.map((nome) => (
            <button
              key={nome}
              type="button"
              className={`pcblib__chip ${libreriaScelta === nome ? 'pcblib__chip--attivo' : ''}`}
              aria-pressed={libreriaScelta === nome}
              onClick={() => setLibreriaScelta(libreriaScelta === nome ? '' : nome)}
            >
              {nome}
            </button>
          ))}
        </div>
      )}

      <div className="pcblib__elenco" role="listbox" aria-label="Componenti disponibili">
        {inRicerca && (
          <>
            <div className="pcblib__scheletro" />
            <div className="pcblib__scheletro" />
            <div className="pcblib__scheletro" />
          </>
        )}

        {!inRicerca && erroreRicerca && (
          <div className="pcblib__errore">{erroreRicerca}</div>
        )}

        {!inRicerca && !erroreRicerca && nulla && (
          <div className="pcblib__vuoto">
            {voci.length
              ? 'Usati di recente:'
              : 'Scrivi qualcosa per cercare fra le librerie KiCad installate.'}
          </div>
        )}

        {!inRicerca && risultati && risultati.length === 0 && (
          <div className="pcblib__vuoto">
            Nessun footprint con questo nome
            {libreriaScelta ? ` in ${libreriaScelta}` : ''}. Prova con meno
            lettere: la ricerca guarda dentro il nome.
          </div>
        )}

        {!inRicerca && voci.map((voce) => {
          const attiva = scelto
            && scelto.libreria === voce.libreria
            && scelto.footprint === voce.footprint;
          return (
            <button
              key={`${voce.libreria}:${voce.footprint}`}
              type="button"
              role="option"
              aria-selected={attiva}
              className={`pcblib__voce ${attiva ? 'pcblib__voce--scelto' : ''}`}
              title={`${voce.libreria}:${voce.footprint}`}
              onClick={() => scegli(voce)}
            >
              <span className="pcblib__nome">{voce.footprint}</span>
              <span className="pcblib__luogo">
                {voce.recente ? 'recente' : voce.libreria}
              </span>
            </button>
          );
        })}
      </div>

      <div className="pcblib__librerie" style={{ justifyContent: 'space-between' }}>
        <span className="pcblib__pillola" title="La ricerca passa dall'indice dei footprint">
          {daIndice === null
            ? 'ricerca diretta'
            : (daIndice ? 'ricerca dall\'indice' : 'ricerca diretta')}
        </span>
        {scelto && (
          <span className="pcblib__pillola pcblib__pillola--ok" title="Componente scelto">
            {scelto.libreria}:{scelto.footprint}
          </span>
        )}
      </div>


      <div className="pcblib__campi">
        <label className="pcblib__campo">
          <span>Riferimento</span>
          <input value={riferimento} placeholder="R1"
                 onChange={(e) => setRiferimento(e.target.value)} />
        </label>
        <label className="pcblib__campo">
          <span>Valore</span>
          <input value={valore} placeholder="10k"
                 onChange={(e) => setValore(e.target.value)} />
        </label>
        <label className="pcblib__campo">
          <span>X (mm)</span>
          <input type="number" step="0.5" value={x} onChange={(e) => setX(e.target.value)} />
        </label>
        <label className="pcblib__campo">
          <span>Y (mm)</span>
          <input type="number" step="0.5" value={y} onChange={(e) => setY(e.target.value)} />
        </label>
        <label className="pcblib__campo">
          <span>Passo ripetizione (mm)</span>
          <input type="number" step="0.5" value={passo} onChange={(e) => setPasso(e.target.value)} />
        </label>
        <label className="pcblib__campo">
          <span>Lato</span>
          <select value={lato} onChange={(e) => setLato(e.target.value)}>
            <option value="top">sopra (F.Cu)</option>
            <option value="bottom">sotto (B.Cu)</option>
          </select>
        </label>
        <div className="pcblib__campo pcblib__campo--largo">
          <span>Rotazione</span>
          <div className="pcblib__rotazioni">
            {[0, 90, 180, 270].map((gradi) => (
              <button
                key={gradi}
                type="button"
                aria-pressed={Number(rotazione) === gradi}
                onClick={() => setRotazione(gradi)}
              >
                {gradi}°
              </button>
            ))}
          </div>
        </div>
      </div>

      <button
        type="button"
        className="pcblib__bottone"
        title="Porta le coordinate al centro della scheda"
        onClick={() => {
          if (!scheda) return;
          setX(String(Math.round(scheda.larghezza / 2)));
          setY(String(Math.round(scheda.altezza / 2)));
        }}
      >
        <MapPin size={12} /> Centro scheda
      </button>

      <div className="pcblib__azioni">
        <button
          type="button"
          className="pcblib__bottone pcblib__bottone--forte"
          disabled={!scelto || occupato}
          onClick={() => void conferma(false)}
        >
          {inCorso ? <Loader2 size={12} /> : <Plus size={12} />} Inserisci
        </button>
        <button
          type="button"
          className="pcblib__bottone"
          disabled={!scelto || occupato}
          title="Inserisce e prepara il prossimo riferimento, spostato del passo"
          onClick={() => void conferma(true)}
        >
          <Repeat size={12} /> e ripeti
        </button>
      </div>

      {errore && <div className="pcblib__errore">{errore}</div>}
      {esito && !errore && <div className="pcblib__nota">{esito}</div>}

      <div className="pcblib__nota">
        Il pezzo arriva dalla libreria KiCad installata: pad, maschera e
        serigrafia sono quelli veri, non un rettangolo approssimato.
      </div>
    </section>
  );
}
