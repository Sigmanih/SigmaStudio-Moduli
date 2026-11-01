// =============================================================================
// PcbEditor — il laboratorio PCB, con il mouse
// =============================================================================
// Quello che sta in questa scheda non e' un visualizzatore: e' la stessa mano
// del team di agenti. Ogni gesto chiama una rotta del modulo KiCad, che esegue
// lo stesso tool che esegue l'agente — la stessa validazione, la stessa copia di
// sicurezza prima di scrivere, lo stesso undo. Se l'editor accettasse qualcosa
// che l'agente rifiuta, i due divergerebbero alla prima eccezione.
//
// Le rotte le verifica `tests/test_kicad_editor_contract.py`: ogni endpoint
// citato qui sotto dev'essere registrato dal modulo, o il clic finisce in un 404
// che nessuno vede finche' non ci si clicca sopra.
//
// **Le coordinate non si convertono.** La canvas disegna in millimetri KiCad,
// con la y verso il basso come nel file: quello che si clicca e' esattamente
// quello che finisce scritto.
//
// **Il pezzo si sposta al rilascio, non durante.** A ogni movimento si aggiorna
// solo l'anteprima: una scrittura per pixel darebbe centinaia di copie di
// sicurezza per un trascinamento solo, e la copia da cui si annulla sarebbe
// sparita sotto le altre.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  MousePointer2, Route, CircleDot, Trash2, Undo2, RotateCw, Tag,
  RefreshCw, Boxes, AlertTriangle,
} from 'lucide-react';
import { leggiScheda, postTool } from '../lib/pcbApi';
import { coloreNet, normalizzaScheda, snap, vistaScheda } from '../lib/pcbModel';
import ComponentLibrary from './ComponentLibrary';

const STRUMENTI = [
  { id: 'seleziona', nome: 'Seleziona', icona: MousePointer2,
    aiuto: 'Clicca un pezzo per selezionarlo, trascinalo per spostarlo.' },
  { id: 'pista', nome: 'Pista', icona: Route,
    aiuto: 'Clicca il punto di partenza e poi quello di arrivo.' },
  { id: 'via', nome: 'Via', icona: CircleDot,
    aiuto: 'Clicca dove vuoi il via, per cambiare layer di rame.' },
  { id: 'net', nome: 'Net del pad', icona: Tag,
    aiuto: 'Clicca un pad per assegnargli la net scritta qui sotto.' },
  { id: 'cancella', nome: 'Cancella', icona: Trash2,
    aiuto: 'Clicca una pista o un via per toglierlo. Un pezzo si toglie dal pannello.' },
];

const PASSI_GRIGLIA = [0.1, 0.25, 0.5, 1, 2.54];

export default function PcbEditor({ progetto, isLight, onChanged }) {
  const pcbPath = (progetto && progetto.pcb_path) || '';

  const [scheda, setScheda] = useState(null);
  const [caricamento, setCaricamento] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errore, setErrore] = useState(null);
  const [esito, setEsito] = useState(null);

  const [strumento, setStrumento] = useState('seleziona');
  const [selezionato, setSelezionato] = useState(null);
  const [layer, setLayer] = useState('F.Cu');
  const [larghezzaPista, setLarghezzaPista] = useState(0.25);
  const [diametroVia, setDiametroVia] = useState(0.8);
  const [net, setNet] = useState('');
  const [passo, setPasso] = useState(0.5);
  const [snapAttivo, setSnapAttivo] = useState(true);

  const [cursore, setCursore] = useState(null);
  const [inizioPista, setInizioPista] = useState(null);
  const [trascinamento, setTrascinamento] = useState(null);
  //: Le misure del contorno da applicare. Vuote significano "quelle della
  //: scheda": cosi' il campo mostra il vero e non costringe a riscriverlo.
  const [contorno, setContorno] = useState({ larghezza: '', altezza: '' });
  //: I campi del pezzo **gia' in scheda**: si riempiono quando se ne seleziona
  //: uno, e servono a rinominarlo o a cambiarne il valore. Il pezzo nuovo non
  //: passa di qui — lo inserisce `ComponentLibrary`, che ha i suoi campi e un
  //: elenco da cui scegliere invece di un nome da ricordare.
  const [nuovoPezzo, setNuovoPezzo] = useState({ reference: '', valore: '' });

  //: Le violazioni DRC da sovrapporre alla canvas. Ogni voce ha x, y, messaggio.
  const [violazioni, setViolazioni] = useState([]);
  const [tooltipDrc, setTooltipDrc] = useState(null); // {x, y, testo}

  const svgRef = useRef(null);
  const trascinamentoRef = useRef(null);

  const vista = useMemo(() => vistaScheda(scheda), [scheda]);

  // --- caricamento ----------------------------------------------------------

  const ricarica = useCallback(async () => {
    if (!pcbPath) {
      setScheda(null);
      return;
    }
    setCaricamento(true);
    try {
      const grezza = await leggiScheda(pcbPath);
      setScheda(grezza ? normalizzaScheda(grezza) : null);
      setErrore(grezza ? null : 'Il file non contiene una scheda leggibile.');
    } catch (err) {
      setErrore(err.message || String(err));
      setScheda(null);
    } finally {
      setCaricamento(false);
    }
  }, [pcbPath]);

  useEffect(() => {
    setSelezionato(null);
    setInizioPista(null);
    setTrascinamento(null);
    void ricarica();
  }, [ricarica]);

  /**
   * Esegue un'operazione sul file, poi rilegge la scheda dal disco.
   *
   * Si rilegge invece di aggiornare lo stato locale perche' la verita' e' il
   * file: il tool puo' aver normalizzato o rifiutato una parte della richiesta,
   * e indovinare il risultato e' il modo di mostrare una scheda che non esiste.
   */
  const esegui = useCallback(async (etichetta, rotta, corpo) => {
    if (!pcbPath) return null;
    setBusy(true);
    setErrore(null);
    setEsito(null);
    try {
      const dati = await postTool(rotta, { project: pcbPath, ...corpo });
      setEsito(etichetta);
      await ricarica();
      if (onChanged) onChanged();
      return dati;
    } catch (err) {
      setErrore(err.message || String(err));
      return null;
    } finally {
      setBusy(false);
    }
  }, [pcbPath, ricarica, onChanged]);

  // --- coordinate e spostamenti ---------------------------------------------

  /** Il punto in millimetri sotto il puntatore, arrotondato alla griglia. */
  const puntoMm = useCallback((evento) => {
    const svg = svgRef.current;
    if (!svg || !svg.getScreenCTM) return null;
    const pt = svg.createSVGPoint();
    pt.x = evento.clientX;
    pt.y = evento.clientY;
    const locale = pt.matrixTransform(svg.getScreenCTM().inverse());
    const arrotonda = (v) => (snapAttivo ? snap(v, passo) : Math.round(v * 1000) / 1000);
    return { x: arrotonda(locale.x), y: arrotonda(locale.y) };
  }, [passo, snapAttivo]);

  const pezzoDi = useCallback(
    (reference) => (scheda
      ? scheda.componenti.find((c) => c.reference === reference)
      : null),
    [scheda],
  );

  const sposta = useCallback(async (reference, x, y, rotazione) => {
    const corpo = { reference, x_mm: x, y_mm: y };
    if (typeof rotazione === 'number') corpo.rotation = rotazione;
    return esegui(
      `${reference} a (${x.toFixed(2)}, ${y.toFixed(2)})`,
      '/api/kicad/footprint/move',
      corpo,
    );
  }, [esegui]);

  const ruotaSelezionato = useCallback((gradi) => {
    const pezzo = pezzoDi(selezionato);
    if (!pezzo) return;
    const nuovo = ((((pezzo.rotazione || 0) + gradi) % 360) + 360) % 360;
    void sposta(pezzo.reference, pezzo.x, pezzo.y, nuovo);
  }, [pezzoDi, selezionato, sposta]);

  const suPointerDown = useCallback((evento, reference) => {
    if (strumento !== 'seleziona' || !scheda) return;
    evento.stopPropagation();
    const punto = puntoMm(evento);
    const pezzo = pezzoDi(reference);
    if (!punto || !pezzo) return;
    setSelezionato(reference);
    trascinamentoRef.current = {
      reference,
      x: pezzo.x,
      y: pezzo.y,
      // L'offset fra il puntatore e il centro del pezzo: senza, il pezzo salta
      // sotto il cursore al primo movimento.
      offset: { x: pezzo.x - punto.x, y: pezzo.y - punto.y },
    };
    setTrascinamento({ reference, x: pezzo.x, y: pezzo.y });
  }, [pezzoDi, puntoMm, scheda, strumento]);

  const suPointerMove = useCallback((evento) => {
    const punto = puntoMm(evento);
    setCursore(punto);
    const attivo = trascinamentoRef.current;
    if (!attivo || !punto) return;
    const grezzoX = punto.x + attivo.offset.x;
    const grezzoY = punto.y + attivo.offset.y;
    attivo.x = snapAttivo ? snap(grezzoX, passo) : grezzoX;
    attivo.y = snapAttivo ? snap(grezzoY, passo) : grezzoY;
    setTrascinamento({ reference: attivo.reference, x: attivo.x, y: attivo.y });
  }, [passo, puntoMm, snapAttivo]);

  const suPointerUp = useCallback(() => {
    const attivo = trascinamentoRef.current;
    trascinamentoRef.current = null;
    setTrascinamento(null);
    if (!attivo) return;
    const pezzo = pezzoDi(attivo.reference);
    const mosso = pezzo
      && (Math.abs(pezzo.x - attivo.x) > 0.001 || Math.abs(pezzo.y - attivo.y) > 0.001);
    if (mosso) void sposta(attivo.reference, attivo.x, attivo.y);
  }, [pezzoDi, sposta]);

  // --- gesti sulla scheda ---------------------------------------------------

  const suClicScheda = useCallback((evento) => {
    const punto = puntoMm(evento);
    if (!punto || !scheda) return;

    if (strumento === 'pista') {
      // Il capo si aggancia al pad piu' vicino quando ce n'e' uno: una pista che
      // parte a un decimo di millimetro dal pad non lo tocca, e il DRC la
      // segnala come non connessa — un errore che a occhio non si vede.
      if (!inizioPista) {
        setInizioPista(agganciaPad(scheda, punto));
        return;
      }
      const a = inizioPista;
      const b = agganciaPad(scheda, punto);
      setInizioPista(null);
      if (Math.abs(a.x - b.x) < 0.001 && Math.abs(a.y - b.y) < 0.001) return;
      void esegui(
        `Pista ${layer} da (${a.x}, ${a.y}) a (${b.x}, ${b.y})`,
        '/api/kicad/track/add',
        {
          start: [a.x, a.y], end: [b.x, b.y],
          width_mm: larghezzaPista, layer, net,
        },
      );
      return;
    }

    if (strumento === 'via') {
      const dove = agganciaPad(scheda, punto);
      void esegui(
        `Via a (${dove.x}, ${dove.y})`,
        '/api/kicad/via/add',
        { at: [dove.x, dove.y], size_mm: diametroVia, drill_mm: diametroVia / 2, net },
      );
      return;
    }

    if (strumento === 'seleziona' && !evento.target.closest('[data-pezzo]')) {
      setSelezionato(null);
    }
  }, [diametroVia, esegui, inizioPista, layer, larghezzaPista, net, puntoMm, scheda, strumento]);

  const cancellaPista = useCallback((pista) => {
    void esegui('Pista tolta', '/api/kicad/track/delete', {
      start: [pista.da.x, pista.da.y],
      end: [pista.a.x, pista.a.y],
      layer: pista.layer,
    });
  }, [esegui]);

  const cancellaVia = useCallback((via) => {
    void esegui('Via tolta', '/api/kicad/via/delete', { at: [via.x, via.y] });
  }, [esegui]);

  const assegnaNet = useCallback((reference, pad) => {
    if (!net.trim()) {
      setErrore('Scrivi il nome della net prima di cliccare il pad.');
      return;
    }
    void esegui(`Pad ${reference}.${pad} sulla net ${net}`, '/api/kicad/pad/net', {
      reference, pad, net,
    });
  }, [esegui, net]);

  const cancellaSelezionato = useCallback(async () => {
    const pezzo = pezzoDi(selezionato);
    if (!pezzo) return;
    const dati = await esegui(
      `${pezzo.reference} tolto dalla scheda`,
      '/api/kicad/footprint/remove',
      { reference: pezzo.reference },
    );
    if (dati) setSelezionato(null);
  }, [esegui, pezzoDi, selezionato]);

  const salvaProprieta = useCallback(async (reference, nuovoRif, valore) => {
    const dati = await esegui(
      `${reference} aggiornato`,
      '/api/kicad/footprint/rename',
      { reference, new_reference: nuovoRif, value: valore },
    );
    if (dati && nuovoRif && dati.reference_new) setSelezionato(dati.reference_new);
  }, [esegui]);

  const annulla = useCallback(() => {
    setInizioPista(null);
    void esegui('Ultima scrittura annullata', '/api/kicad/undo', {});
  }, [esegui]);

  // --- DRC: esecuzione e sovrapposizione violazioni --------------------------

  const eseguiDrc = useCallback(async () => {
    if (!pcbPath) return;
    setBusy(true);
    setErrore(null);
    try {
      const dati = await postTool('/api/kicad/drc', { project: pcbPath });
      const viol = Array.isArray(dati.violations) ? dati.violations : [];
      // Filtra solo quelle con coordinate valide per il rendering SVG.
      setViolazioni(viol.filter((v) => typeof v.x === 'number' && typeof v.y === 'number'));
      setEsito(`DRC: ${viol.length} violazioni`);
    } catch (err) {
      setErrore(err.message || String(err));
      setViolazioni([]);
    } finally {
      setBusy(false);
    }
  }, [pcbPath]);

  const suClicViolazione = useCallback((evento, v) => {
    evento.stopPropagation();
    setTooltipDrc({ x: v.x, y: v.y, testo: v.messaggio || v.rule || 'Violazione DRC' });
  }, []);

  const chiudiTooltip = useCallback(() => setTooltipDrc(null), []);

  const cambiaContorno = useCallback((larghezza, altezza) => {
    void esegui(
      `Contorno ${larghezza}×${altezza} mm`,
      '/api/kicad/outline/set',
      { width_mm: larghezza, height_mm: altezza },
    );
  }, [esegui]);

  // --- inserire un pezzo nuovo ----------------------------------------------

  const inserisciPezzo = useCallback(async (dati) => {
    // I nomi dei campi sono quelli del tool (`x_mm`), non quelli comodi del
    // pannello: la rotta passa gli argomenti all'esecutore così come sono, e un
    // `x` al posto di `x_mm` finirebbe in un errore di parametro.
    const datiOp = await esegui(
      `${dati.riferimento} aggiunto (${dati.footprint})`,
      '/api/kicad/part/add',
      {
        libreria: dati.libreria,
        footprint: dati.footprint,
        riferimento: dati.riferimento,
        valore: dati.valore,
        x_mm: Number(dati.x_mm),
        y_mm: Number(dati.y_mm),
        rotazione: Number(dati.rotazione),
        lato: dati.lato,
      },
    );
    if (datiOp && datiOp.riferimento) setSelezionato(datiOp.riferimento);
    return datiOp;
  }, [esegui]);

  const posizioneMostrata = useCallback((pezzo) => {
    if (trascinamento && trascinamento.reference === pezzo.reference) {
      return { x: trascinamento.x, y: trascinamento.y };
    }
    return { x: pezzo.x, y: pezzo.y };
  }, [trascinamento]);

  const testo = (chiaro, scuro) => (isLight ? chiaro : scuro);
  const pezzoSelezionato = pezzoDi(selezionato);

  // --- disegno --------------------------------------------------------------

  if (!pcbPath) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center', gap: '10px',
                    color: testo('#64748b', '#64748b') }}>
        <Boxes size={30} />
        <div style={{ fontSize: '0.85rem' }}>
          Scegli un progetto KiCad dal selettore qui sopra per disegnare la scheda.
        </div>
      </div>
    );
  }

  if (!scheda) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center', gap: '10px',
                    color: testo('#475569', '#94a3b8') }}>
        {caricamento ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <RefreshCw size={16} className="spin" /> Lettura della scheda…
          </div>
        ) : (
          <>
            <div style={{ fontSize: '0.85rem' }}>{errore || 'Nessuna scheda.'}</div>
            <button type="button" onClick={() => void ricarica()} style={pulsante(isLight)}>
              <RefreshCw size={13} /> Riprova
            </button>
          </>
        )}
      </div>
    );
  }

  const coloreBordo = testo('#334155', '#475569');
  const coloreTesto = testo('#0f172a', '#e2e8f0');
  const colorePannello = testo('#f8fafc', 'rgba(255,255,255,0.03)');
  const cursoreSvg = strumento === 'seleziona' ? 'default' : 'crosshair';
  const larghezzaContorno = contorno.larghezza === '' ? scheda.larghezza : contorno.larghezza;
  const altezzaContorno = contorno.altezza === '' ? scheda.altezza : contorno.altezza;

  const etichetta = (nome, nodo) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '3px',
                    fontSize: '0.7rem', color: testo('#64748b', '#94a3b8') }}>
      <span>{nome}</span>
      {nodo}
    </label>
  );

  const inputStile = {
    background: testo('#fff', 'rgba(15,23,42,0.8)'),
    border: `1px solid ${coloreBordo}`,
    borderRadius: '4px',
    color: coloreTesto,
    fontSize: '0.75rem',
    padding: '4px 6px',
    outline: 'none',
    width: '100%',
  };

  return (
    <div className="pcb-lab__editor" style={{ minHeight: 0 }}>
      {/* ---- pannello dei comandi ---- */}
      <aside className="pcb-lab__aside" style={{
        background: colorePannello,
        borderLeft: `3px solid ${busy ? '#0d6efd' : 'transparent'}`,
      }}>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          {STRUMENTI.map((s) => {
            const Icona = s.icona;
            const attivo = strumento === s.id;
            return (
              <button
                key={s.id}
                type="button"
                title={s.aiuto}
                onClick={() => {
                  setStrumento(s.id);
                  setInizioPista(null);
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '5px',
                  padding: '5px 8px', borderRadius: '5px', cursor: 'pointer',
                  fontSize: '0.72rem', fontWeight: 600,
                  background: attivo ? 'rgba(13,110,253,0.18)' : 'transparent',
                  border: `1px solid ${attivo ? 'rgba(13,110,253,0.45)' : coloreBordo}`,
                  color: attivo ? '#38bdf8' : testo('#475569', '#94a3b8'),
                }}
              >
                <Icona size={13} /> {s.nome}
              </button>
            );
          })}
        </div>

        <div style={{ fontSize: '0.7rem', color: testo('#64748b', '#94a3b8'),
                      lineHeight: 1.35 }}>
          {(STRUMENTI.find((s) => s.id === strumento) || {}).aiuto}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          {etichetta('Layer di rame', (
            <select value={layer} onChange={(e) => setLayer(e.target.value)} style={inputStile}>
              <option value="F.Cu">F.Cu (sopra)</option>
              <option value="B.Cu">B.Cu (sotto)</option>
            </select>
          ))}
          {etichetta('Net', (
            <select value={net} onChange={(e) => setNet(e.target.value)} style={inputStile}>
              <option value="">— nessuna —</option>
              {(scheda.nets || []).map((n) => (
                <option key={n.nome} value={n.nome}>{n.nome}</option>
              ))}
            </select>
          ))}
          {etichetta('Larghezza pista (mm)', (
            <input type="number" step="0.05" min="0.05" value={larghezzaPista}
                   onChange={(e) => setLarghezzaPista(Number(e.target.value))}
                   style={inputStile} />
          ))}
          {etichetta('Diametro via (mm)', (
            <input type="number" step="0.05" min="0.3" value={diametroVia}
                   onChange={(e) => setDiametroVia(Number(e.target.value))}
                   style={inputStile} />
          ))}
          {etichetta('Griglia (mm)', (
            <select value={passo} onChange={(e) => setPasso(Number(e.target.value))}
                    style={inputStile}>
              {PASSI_GRIGLIA.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          ))}
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px',
                          fontSize: '0.72rem', color: testo('#475569', '#94a3b8'),
                          marginTop: '16px' }}>
            <input type="checkbox" checked={snapAttivo}
                   onChange={(e) => setSnapAttivo(e.target.checked)} />
            Aggancia
          </label>
        </div>

        <div style={{ display: 'flex', gap: '6px' }}>
          <button type="button" onClick={() => ruotaSelezionato(90)}
                  disabled={!pezzoSelezionato || busy} style={pulsante(isLight)}>
            <RotateCw size={13} /> +90°
          </button>
          <button type="button" onClick={() => ruotaSelezionato(-90)}
                  disabled={!pezzoSelezionato || busy} style={pulsante(isLight)}>
            <RotateCw size={13} style={{ transform: 'scaleX(-1)' }} /> −90°
          </button>
          <button type="button" onClick={() => void cancellaSelezionato()}
                  disabled={!pezzoSelezionato || busy} style={pulsante(isLight, true)}>
            <Trash2 size={13} /> Pezzo
          </button>
        </div>

        {/* ---- scegliere e inserire un componente ---- */}
        <div style={{ borderTop: `1px solid ${coloreBordo}`, paddingTop: '10px' }}>
          <ComponentLibrary
            isLight={isLight}
            scheda={scheda}
            busy={busy}
            inserisci={inserisciPezzo}
          />
        </div>

        {/* ---- proprietà del pezzo selezionato ---- */}
        {pezzoSelezionato && (
          <div style={{ borderTop: `1px solid ${coloreBordo}`, paddingTop: '10px',
                        display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: coloreTesto }}>
              {pezzoSelezionato.reference}
              <span style={{ fontWeight: 400, marginLeft: '6px',
                             color: testo('#64748b', '#94a3b8') }}>
                {pezzoSelezionato.libreria}
              </span>
            </div>
            <div style={{ fontSize: '0.68rem', color: testo('#64748b', '#94a3b8') }}>
              ({pezzoSelezionato.x.toFixed(2)}, {pezzoSelezionato.y.toFixed(2)}) mm
              · {pezzoSelezionato.rotazione}°
              · {pezzoSelezionato.pads.length} pad
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              {etichetta('Riferimento', (
                <input value={nuovoPezzo.reference} style={inputStile}
                       placeholder={pezzoSelezionato.reference}
                       onChange={(e) => setNuovoPezzo((p) => ({ ...p, reference: e.target.value }))} />
              ))}
              {etichetta('Valore', (
                <input value={nuovoPezzo.valore} style={inputStile}
                       placeholder={pezzoSelezionato.valore}
                       onChange={(e) => setNuovoPezzo((p) => ({ ...p, valore: e.target.value }))} />
              ))}
            </div>
            <button type="button" disabled={busy}
                    onClick={() => void salvaProprieta(
                      pezzoSelezionato.reference,
                      nuovoPezzo.reference && nuovoPezzo.reference !== pezzoSelezionato.reference
                        ? nuovoPezzo.reference : '',
                      nuovoPezzo.valore !== pezzoSelezionato.valore ? nuovoPezzo.valore : '',
                    )}
                    style={pulsante(isLight, true)}>
              Salva riferimento e valore
            </button>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px' }}>
              {pezzoSelezionato.pads.map((p) => (
                <span key={p.numero}
                      title={`Pad ${p.numero}${p.net ? ` — ${p.net}` : ' — nessuna net'}`}
                      style={{
                        fontSize: '0.62rem', padding: '1px 5px', borderRadius: '8px',
                        border: `1px solid ${p.net ? coloreNet(p.net) : coloreBordo}`,
                        color: p.net ? coloreNet(p.net) : testo('#94a3b8', '#64748b'),
                      }}>
                  {p.numero}{p.net ? ` ${p.net}` : ''}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* ---- contorno e annulla ---- */}
        <div style={{ borderTop: `1px solid ${coloreBordo}`, paddingTop: '10px',
                      display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
            {etichetta('Scheda larghezza (mm)', (
              <input type="number" step="1" min="5" value={larghezzaContorno}
                     onChange={(e) => setContorno((c) => ({ ...c, larghezza: e.target.value }))}
                     style={inputStile} />
            ))}
            {etichetta('Scheda altezza (mm)', (
              <input type="number" step="1" min="5" value={altezzaContorno}
                     onChange={(e) => setContorno((c) => ({ ...c, altezza: e.target.value }))}
                     style={inputStile} />
            ))}
          </div>
          <button type="button" disabled={busy}
                  onClick={() => {
                    cambiaContorno(Number(larghezzaContorno), Number(altezzaContorno));
                    setContorno({ larghezza: '', altezza: '' });
                  }}
                  style={pulsante(isLight)}>
            Applica contorno {scheda.larghezza}×{scheda.altezza} → {larghezzaContorno}×{altezzaContorno}
          </button>
          <button type="button" onClick={annulla} disabled={busy} style={pulsante(isLight)}>
            <Undo2 size={13} /> Annulla l&apos;ultima scrittura
          </button>
          <button type="button" onClick={() => void eseguiDrc()} disabled={busy}
                  style={{ ...pulsante(isLight), borderColor: 'rgba(239,68,68,0.5)', color: '#ef4444' }}>
            <AlertTriangle size={13} /> Esegui DRC
          </button>
          {violazioni.length > 0 && (
            <div style={{ fontSize: '0.68rem', color: '#f87171' }}>
              {violazioni.length} violazioni — clicca un marker per il dettaglio
            </div>
          )}
        </div>

        {errore && (
          <div style={{ fontSize: '0.7rem', color: '#f87171', lineHeight: 1.35 }}>
            {errore}
          </div>
        )}
        {esito && !busy && (
          <div style={{ fontSize: '0.7rem', color: '#10b981', lineHeight: 1.35 }}>
            {esito}
          </div>
        )}
      </aside>

      {/* ---- canvas ---- */}
      <div className="pcb-lab__area" style={{ position: 'relative' }}>
        <svg
          ref={svgRef}
          viewBox={`${vista.x} ${vista.y} ${vista.w} ${vista.h}`}
          preserveAspectRatio="xMidYMid meet"
          style={{
            width: '100%', flex: 1, minHeight: 0, touchAction: 'none',
            background: testo('#ffffff', '#0b1220'), cursor: cursoreSvg,
          }}
          onPointerMove={suPointerMove}
          onPointerUp={suPointerUp}
          onPointerLeave={suPointerUp}
          onClick={suClicScheda}
        >
          <rect x={0} y={0} width={scheda.larghezza} height={scheda.altezza}
                fill={testo('#f8fafc', '#0f1a2e')} stroke="#0d6efd" strokeWidth={0.3} />

          {scheda.piste.map((p, i) => (
            <line
              key={`pista-${i}`}
              x1={p.da.x} y1={p.da.y} x2={p.a.x} y2={p.a.y}
              stroke={p.layer === 'B.Cu' ? '#3b82f6' : coloreNet(p.net)}
              strokeWidth={Math.max(p.larghezza, 0.1)}
              strokeLinecap="round"
              opacity={0.85}
              style={{ cursor: strumento === 'cancella' ? 'pointer' : 'inherit' }}
              onClick={(e) => {
                if (strumento === 'cancella') {
                  e.stopPropagation();
                  cancellaPista(p);
                }
              }}
            />
          ))}

          {scheda.vie.map((v, i) => (
            <g
              key={`via-${i}`}
              style={{ cursor: strumento === 'cancella' ? 'pointer' : 'inherit' }}
              onClick={(e) => {
                if (strumento === 'cancella') {
                  e.stopPropagation();
                  cancellaVia(v);
                }
              }}
            >
              <circle cx={v.x} cy={v.y} r={Math.max(v.diametro / 2, 0.2)}
                      fill="#0f172a" stroke={coloreNet(v.net)} strokeWidth={0.12} />
              <circle cx={v.x} cy={v.y} r={Math.max(v.foro / 2, 0.08)}
                      fill={testo('#e2e8f0', '#0b1220')} />
            </g>
          ))}

          {scheda.componenti.map((c) => {
            const pos = posizioneMostrata(c);
            const attivo = c.reference === selezionato;
            return (
              <g
                key={c.reference}
                data-pezzo={c.reference}
                onPointerDown={(e) => suPointerDown(e, c.reference)}
                style={{ cursor: strumento === 'seleziona' ? 'move' : 'inherit' }}
              >
                <g transform={`translate(${pos.x} ${pos.y}) rotate(${c.rotazione})`}>
                  <rect
                    x={-c.larghezza / 2} y={-c.altezza / 2}
                    width={c.larghezza} height={c.altezza}
                    fill={testo('#dbeafe', '#1e3a8a')}
                    fillOpacity={attivo ? 0.9 : 0.45}
                    stroke={attivo ? '#0d6efd' : '#64748b'}
                    strokeWidth={attivo ? 0.2 : 0.08}
                  />
                  {c.pads.map((p) => (
                    <rect
                      key={p.numero}
                      x={p.x - pos.x - 0.4} y={p.y - pos.y - 0.3}
                      width={0.8} height={0.6}
                      fill={p.net ? coloreNet(p.net) : '#94a3b8'}
                      stroke="#0f172a" strokeWidth={0.04}
                      style={{ cursor: strumento === 'net' ? 'crosshair' : 'inherit' }}
                      onClick={(e) => {
                        if (strumento === 'net') {
                          e.stopPropagation();
                          assegnaNet(c.reference, p.numero);
                        }
                      }}
                    />
                  ))}
                </g>
                <text
                  x={pos.x} y={pos.y - c.altezza / 2 - 0.6}
                  textAnchor="middle" fontSize={1.1}
                  fill={attivo ? '#38bdf8' : testo('#334155', '#cbd5e1')}
                  style={{ pointerEvents: 'none', fontWeight: attivo ? 700 : 400 }}
                >
                  {c.reference}{c.valore ? ` ${c.valore}` : ''}
                </text>
              </g>
            );
          })}

          {inizioPista && cursore && (
            <line
              x1={inizioPista.x} y1={inizioPista.y} x2={cursore.x} y2={cursore.y}
              stroke="#38bdf8" strokeWidth={larghezzaPista}
              strokeDasharray="0.6 0.4" pointerEvents="none"
            />
          )}
          {inizioPista && (
            <circle cx={inizioPista.x} cy={inizioPista.y} r={0.35}
                    fill="#38bdf8" pointerEvents="none" />
          )}

          {/* --- marker DRC: cerchi rossi pulsanti con tooltip al click --- */}
          {violazioni.map((v, i) => (
            <g key={`drc-${i}`} onClick={(e) => suClicViolazione(e, v)}
               style={{ cursor: 'pointer' }}>
              <circle cx={v.x} cy={v.y} r={0.8}
                      fill="rgba(239,68,68,0.25)" stroke="#ef4444" strokeWidth={0.15}
                      className="drc-marker-pulse" />
              <circle cx={v.x} cy={v.y} r={0.35}
                      fill="#ef4444" stroke="#fff" strokeWidth={0.08} />
            </g>
          ))}

          {tooltipDrc && (
            <g pointerEvents="none">
              <rect x={tooltipDrc.x + 1} y={tooltipDrc.y - 3}
                    width={Math.min(tooltipDrc.testo.length * 0.65, 28)} height={2.5}
                    rx={0.3}
                    fill="rgba(15,23,42,0.92)" stroke="#ef4444" strokeWidth={0.08} />
              <text x={tooltipDrc.x + 1.3} y={tooltipDrc.y - 1.2}
                    fontSize={0.75} fill="#fecaca">
                {tooltipDrc.testo.length > 40 ? tooltipDrc.testo.slice(0, 38) + '…' : tooltipDrc.testo}
              </text>
            </g>
          )}
        </svg>

        <div style={{
          display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap',
          padding: '5px 10px', borderTop: `1px solid ${coloreBordo}`,
          fontSize: '0.68rem', color: testo('#64748b', '#94a3b8'),
        }}>
          <span>{(progetto && progetto.name) || '—'}</span>
          <span>{pcbPath.split(/[\\/]/).pop() || '—'}</span>
          <span>{scheda.larghezza}×{scheda.altezza} mm</span>
          <span>{scheda.componenti.length} pezzi</span>
          <span>{scheda.piste.length} piste</span>
          <span>{scheda.vie.length} via</span>
          <span>
            {cursore ? `x ${cursore.x.toFixed(2)}  y ${cursore.y.toFixed(2)} mm` : '—'}
          </span>
          {busy && <span style={{ color: '#38bdf8' }}>scrittura…</span>}
        </div>
      </div>
    </div>
  );
}

/** Un pulsante del pannello: stessa forma per tutti, colore diverso se distrugge. */
function pulsante(isLight, distruttivo = false) {
  return {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px',
    padding: '5px 9px', borderRadius: '5px', cursor: 'pointer',
    fontSize: '0.72rem', fontWeight: 600,
    background: isLight ? '#fff' : 'rgba(255,255,255,0.05)',
    border: `1px solid ${distruttivo
      ? 'rgba(239,68,68,0.45)'
      : (isLight ? '#cbd5e1' : 'rgba(255,255,255,0.14)')}`,
    color: distruttivo ? '#ef4444' : (isLight ? '#334155' : '#e2e8f0'),
  };
}

/**
 * Il pad piu' vicino al punto, entro la tolleranza. Serve a collegare davvero:
 * una pista che parte a un decimo di millimetro dal pad non lo tocca, e il DRC
 * la segnala come non connessa — un errore che a occhio non si vede.
 */
function agganciaPad(scheda, punto, tolleranza = 1) {
  if (!scheda || !punto) return punto;
  let migliore = null;
  let distanza = tolleranza;
  for (const componente of scheda.componenti) {
    for (const pad of componente.pads) {
      const d = Math.hypot(pad.x - punto.x, pad.y - punto.y);
      if (d <= distanza) {
        distanza = d;
        migliore = { x: pad.x, y: pad.y, pad: `${componente.reference}.${pad.numero}` };
      }
    }
  }
  return migliore || punto;
}
