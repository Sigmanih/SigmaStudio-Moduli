// =============================================================================
// FanoutPanel.jsx — Il lavoro grande, spezzato e dato a più agenti
// Sigma Studio v8 — Developer Studio
// =============================================================================
//
// Un lavoro da duecento file non si fa con un run: il contesto non ci sta, e a
// metà strada l'agente non ricorda più cosa aveva già sistemato. Si spezza
// prima — una voce per file, per cartella, per modulo — e si fa consumare la
// coda da più run in parallelo, ognuno nel proprio worktree.
//
// Questo pannello è la faccia di quella macchina. Serve a tre cose che senza
// interfaccia non si possono fare: riempire la coda, farla partire, e vedere a
// che punto è mentre gira — perché un lavoro che dura ore senza notizie è
// indistinguibile da uno bloccato.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Layers, Play, Square, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react';

const COLORE = {
  todo: '#8b949e',
  doing: '#00f2fe',
  done: '#3fb950',
  failed: '#f85149',
  // Bloccata non è ferma: è una voce che aspetta qualcosa che non è stato
  // fatto. Con lo stesso colore di «ferma» si cercherebbe il difetto nella
  // voce sbagliata.
  blocked: '#d29922'
};

// Il modello non si sceglie qui: lo risolve il ciclo dal ruolo configurato,
// che è l'unico posto in cui quella scelta vive. Un secondo selettore qui
// sarebbe una seconda verità, e le due divergerebbero.
export default function FanoutPanel({ workspaceRoot, isLight }) {
  const [aperto, setAperto] = useState(false);
  const [code, setCode] = useState([]);
  const [codaAttiva, setCodaAttiva] = useState('');
  const [progresso, setProgresso] = useState(null);
  const [inCorso, setInCorso] = useState(false);
  const [lavoratori, setLavoratori] = useState(2);
  const [voci, setVoci] = useState('');
  const [obiettivo, setObiettivo] = useState('');
  const [eventi, setEventi] = useState([]);
  const [errore, setErrore] = useState('');
  const abortRef = useRef(null);

  const caricaCode = useCallback(async () => {
    try {
      const res = await fetch('/api/harness/queues');
      const dati = await res.json();
      setCode(dati.queues || []);
      if (!codaAttiva && (dati.queues || []).length > 0) {
        setCodaAttiva(dati.queues[0].queue_id);
        setProgresso(dati.queues[0]);
      }
    } catch (e) {
      setErrore(e.message);
    }
  }, [codaAttiva]);

  useEffect(() => {
    if (aperto) caricaCode();
  }, [aperto, caricaCode]);

  // Fermare il lavoro quando il pannello sparisce: un ventaglio che continua a
  // girare dopo che nessuno lo guarda è un ventaglio che nessuno può fermare.
  useEffect(() => () => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch (e) { /* già chiuso */ }
    }
  }, []);

  const creaCoda = async () => {
    const titoli = voci.split('\n').map(r => r.trim()).filter(Boolean);
    if (titoli.length === 0) {
      setErrore('Servono delle voci: una per riga.');
      return;
    }
    const id = codaAttiva || `q_${Date.now().toString(36)}`;
    setErrore('');
    try {
      const res = await fetch('/api/harness/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queue_id: id, goal: obiettivo, items: titoli })
      });
      const dati = await res.json();
      if (!dati.success) {
        setErrore(dati.error || 'Coda non creata.');
        return;
      }
      setCodaAttiva(id);
      setProgresso(dati);
      setVoci('');
      caricaCode();
    } catch (e) {
      setErrore(e.message);
    }
  };

  const avvia = async () => {
    if (!codaAttiva) {
      setErrore('Scegli o crea una coda.');
      return;
    }
    setErrore('');
    setEventi([]);
    setInCorso(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch('/api/harness/fanout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          queue_id: codaAttiva,
          workspace_root: workspaceRoot,
          workers: lavoratori
        })
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const righe = buffer.split('\n\n');
        buffer = righe.pop() || '';

        for (const riga of righe) {
          if (!riga.startsWith('data: ')) continue;
          let evento;
          try {
            evento = JSON.parse(riga.slice(6).trim());
          } catch (e) {
            continue;
          }

          if (evento.type === 'fanout_progress' || evento.type === 'fanout_started'
              || evento.type === 'fanout_finished') {
            setProgresso(evento);
          }
          if (evento.type === 'item_started' || evento.type === 'item_finished') {
            setEventi(prec => [...prec.slice(-40), evento]);
          }
          if (evento.type === 'error') setErrore(evento.error || 'errore');
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setErrore(e.message);
    } finally {
      setInCorso(false);
      abortRef.current = null;
      caricaCode();
    }
  };

  const ferma = () => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch (e) { /* già chiuso */ }
    }
  };

  const bordo = isLight ? '1px solid #d0d7de' : '1px solid rgba(255,255,255,0.08)';
  const totale = progresso?.total || 0;
  const fatte = progresso?.done || 0;
  const percentuale = totale > 0 ? Math.round((fatte / totale) * 100) : 0;

  return (
    <div style={{
      borderTop: bordo,
      background: isLight ? '#ffffff' : '#0d1117',
      fontSize: '0.7rem',
      flexShrink: 0
    }}>
      <div
        onClick={() => setAperto(!aperto)}
        style={{
          padding: '7px 10px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          cursor: 'pointer',
          fontWeight: 700,
          letterSpacing: '0.4px',
          color: isLight ? '#24292e' : '#c9d1d9'
        }}
      >
        {aperto ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Layers size={13} color="#00f2fe" />
        <span>LAVORO IN PARALLELO</span>
        {totale > 0 && (
          <span style={{
            marginLeft: 'auto',
            fontSize: '0.62rem',
            fontWeight: 800,
            color: inCorso ? '#00f2fe' : COLORE.done
          }}>
            {fatte}/{totale}
          </span>
        )}
      </div>

      {aperto && (
        <div style={{ padding: '0 10px 9px' }}>
          <div style={{
            fontSize: '0.62rem', color: '#8b949e',
            lineHeight: 1.5, marginBottom: '7px'
          }}>
            Una voce per riga. Ogni voce diventa un run dell&apos;agente, isolato
            nel proprio worktree: più agenti lavorano insieme senza scriversi
            addosso.
          </div>

          {code.length > 0 && (
            <select
              value={codaAttiva}
              onChange={e => {
                setCodaAttiva(e.target.value);
                setProgresso(code.find(c => c.queue_id === e.target.value) || null);
              }}
              disabled={inCorso}
              style={{
                width: '100%', marginBottom: '6px', padding: '4px',
                fontSize: '0.64rem', borderRadius: '4px',
                background: isLight ? '#ffffff' : '#161b22',
                color: isLight ? '#24292e' : '#c9d1d9',
                border: bordo
              }}
            >
              {code.map(c => (
                <option key={c.queue_id} value={c.queue_id}>
                  {c.queue_id} — {c.done}/{c.total}
                </option>
              ))}
            </select>
          )}

          {!inCorso && (
            <>
              <input
                value={obiettivo}
                onChange={e => setObiettivo(e.target.value)}
                placeholder="Obiettivo generale (a cosa serve tutto questo)"
                style={{
                  width: '100%', marginBottom: '5px', padding: '4px 6px',
                  fontSize: '0.64rem', borderRadius: '4px',
                  background: isLight ? '#ffffff' : '#161b22',
                  color: isLight ? '#24292e' : '#c9d1d9', border: bordo
                }}
              />
              <textarea
                value={voci}
                onChange={e => setVoci(e.target.value)}
                placeholder={'Una voce per riga, per esempio:\ntraduci sigma_network/index.jsx\ntraduci sigma_roadmap/index.jsx'}
                rows={4}
                style={{
                  width: '100%', marginBottom: '5px', padding: '4px 6px',
                  fontSize: '0.63rem', fontFamily: 'monospace',
                  borderRadius: '4px', resize: 'vertical',
                  background: isLight ? '#ffffff' : '#161b22',
                  color: isLight ? '#24292e' : '#c9d1d9', border: bordo
                }}
              />
              <button
                onClick={creaCoda}
                style={{
                  width: '100%', marginBottom: '7px', padding: '4px',
                  borderRadius: '4px', border: bordo, background: 'transparent',
                  color: '#8b949e', fontSize: '0.63rem', cursor: 'pointer'
                }}
              >
                Aggiungi alla coda
              </button>
            </>
          )}

          {totale > 0 && (
            <div style={{ marginBottom: '7px' }}>
              <div style={{
                height: '5px', borderRadius: '3px', overflow: 'hidden',
                background: isLight ? '#e1e4e8' : '#21262d', display: 'flex'
              }}>
                <div style={{ width: `${percentuale}%`, background: COLORE.done }} />
                <div style={{
                  width: `${totale ? Math.round((progresso.doing / totale) * 100) : 0}%`,
                  background: COLORE.doing
                }} />
                <div style={{
                  width: `${totale ? Math.round((progresso.failed / totale) * 100) : 0}%`,
                  background: COLORE.failed
                }} />
              </div>
              <div style={{
                display: 'flex', gap: '8px', marginTop: '4px',
                fontSize: '0.6rem', fontWeight: 700
              }}>
                <span style={{ color: COLORE.done }}>{progresso.done} fatte</span>
                <span style={{ color: COLORE.doing }}>{progresso.doing} in corso</span>
                <span style={{ color: COLORE.todo }}>
                  {progresso.todo} da fare
                  {/* Quante possono partire adesso. Senza questo numero,
                      «10 da fare, 0 in corso» non distingue una coda ferma da
                      una che sta aspettando una dipendenza. */}
                  {typeof progresso.ready === 'number' && progresso.ready < progresso.todo
                    && ` (${progresso.ready} pronte)`}
                </span>
                {progresso.blocked > 0 && (
                  <span style={{ color: COLORE.blocked }} title="Dipendono da voci non riuscite">
                    {progresso.blocked} bloccate
                  </span>
                )}
                {progresso.failed > 0 && (
                  <span style={{ color: COLORE.failed }}>{progresso.failed} ferme</span>
                )}
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '6px' }}>
            {!inCorso ? (
              <>
                <button
                  onClick={avvia}
                  disabled={!codaAttiva || totale === 0}
                  style={{
                    flex: 1, padding: '5px', borderRadius: '5px',
                    border: '1px solid rgba(0, 242, 254, 0.5)',
                    background: totale > 0 ? 'rgba(0, 242, 254, 0.15)' : 'transparent',
                    color: totale > 0 ? '#00f2fe' : '#6e7681',
                    fontWeight: 800, fontSize: '0.64rem',
                    cursor: totale > 0 ? 'pointer' : 'default',
                    display: 'flex', alignItems: 'center',
                    justifyContent: 'center', gap: '4px'
                  }}
                >
                  <Play size={11} /> Avvia
                </button>
                <select
                  value={lavoratori}
                  onChange={e => setLavoratori(Number(e.target.value))}
                  title="Quanti agenti in parallelo. Oltre un certo punto non è parallelismo, è contesa: la banda verso i pesi del modello è condivisa"
                  style={{
                    padding: '5px', fontSize: '0.63rem', borderRadius: '4px',
                    background: isLight ? '#ffffff' : '#161b22',
                    color: isLight ? '#24292e' : '#c9d1d9', border: bordo
                  }}
                >
                  {[1, 2, 3, 4, 6, 8].map(n => (
                    <option key={n} value={n}>{n}×</option>
                  ))}
                </select>
              </>
            ) : (
              <button
                onClick={ferma}
                style={{
                  flex: 1, padding: '5px', borderRadius: '5px',
                  border: '1px solid rgba(248, 81, 73, 0.5)',
                  background: 'rgba(248, 81, 73, 0.15)', color: '#f85149',
                  fontWeight: 800, fontSize: '0.64rem', cursor: 'pointer',
                  display: 'flex', alignItems: 'center',
                  justifyContent: 'center', gap: '4px'
                }}
              >
                <Square size={11} /> Ferma
              </button>
            )}
            <button
              onClick={caricaCode}
              disabled={inCorso}
              title="Ricarica lo stato delle code"
              style={{
                padding: '5px 7px', borderRadius: '4px', border: bordo,
                background: 'transparent', color: '#8b949e',
                cursor: inCorso ? 'default' : 'pointer'
              }}
            >
              <RefreshCw size={11} />
            </button>
          </div>

          {eventi.length > 0 && (
            <div style={{
              maxHeight: '150px', overflowY: 'auto',
              fontSize: '0.61rem', fontFamily: 'monospace', lineHeight: 1.6
            }}>
              {[...eventi].reverse().map((e, i) => (
                <div key={i} style={{
                  display: 'flex', gap: '5px',
                  color: e.type === 'item_started'
                    ? COLORE.doing
                    : (e.ok ? COLORE.done : COLORE.failed)
                }}>
                  <span>{e.type === 'item_started' ? '▸' : (e.ok ? '✓' : '✕')}</span>
                  <span style={{
                    flex: 1, overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap'
                  }}>
                    {e.title}
                  </span>
                  <span style={{ color: '#6e7681' }}>{e.worker}</span>
                </div>
              ))}
            </div>
          )}

          {errore && (
            <div style={{ marginTop: '6px', fontSize: '0.62rem', color: '#f85149' }}>
              {errore}
            </div>
          )}

          {progresso?.failed > 0 && !inCorso && (
            <div style={{ marginTop: '6px', fontSize: '0.61rem', color: '#8b949e', lineHeight: 1.5 }}>
              Le voci ferme hanno esaurito i tentativi. Il loro lavoro non è
              perduto: guarda i branch delle sessioni, o rimettile in coda
              cambiando ciò che le faceva fallire.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
