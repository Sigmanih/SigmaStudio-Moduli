// =============================================================================
// ActivityBar.jsx — Cosa sta girando adesso, chiunque lo abbia lanciato
// Sigma Studio v8 — Developer Studio
// =============================================================================
//
// Un ventaglio lanciato da riga di comando non compariva da nessuna parte qui
// dentro: la pagina mostrava un sistema fermo mentre due agenti stavano
// riscrivendo il progetto. Lo stream degli eventi è visibile solo a chi è
// attaccato a quello stream, e non è quasi mai chi apre la scheda.
//
// Questa barra legge il registro delle attività, che sta su disco proprio per
// questo: la domanda «cosa sta girando» arriva da una richiesta diversa da
// quella che sta lavorando.

import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Users, Layers, MessageSquare, Clock } from 'lucide-react';

// Un secondo e mezzo: abbastanza per sembrare vivo, abbastanza poco da non
// pesare. Il registro è un file piccolo, la lettura costa quanto un ls.
const INTERVALLO_MS = 1500;

const ICONA = {
  ventaglio: Layers,
  obiettivo: Users,
  agente: MessageSquare,
};

const COLORE = {
  ventaglio: '#a371f7',
  obiettivo: '#00f2fe',
  agente: '#3fb950',
};

function durata(secondiDa) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - secondiDa));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, '0')}s`;
}

export default function ActivityBar({ isLight = false }) {
  const [stato, setStato] = useState({ busy: false, running: [], recent: [] });
  const [aperto, setAperto] = useState(false);

  const leggi = useCallback(() => {
    fetch('/api/harness/activity')
      .then((r) => r.json())
      .then((d) => { if (d && d.success) setStato(d); })
      .catch(() => { /* il registro non deve poter rompere la pagina */ });
  }, []);

  useEffect(() => {
    leggi();
    const t = setInterval(leggi, INTERVALLO_MS);
    return () => clearInterval(t);
  }, [leggi]);

  const bordo = isLight ? 'rgba(0,0,0,0.12)' : 'rgba(255,255,255,0.10)';
  const testo = isLight ? '#1f2328' : '#e6edf3';
  const sfondo = isLight ? 'rgba(0,0,0,0.02)' : 'rgba(255,255,255,0.03)';

  // A riposo la barra resta, piccola: sparire del tutto renderebbe impossibile
  // distinguere «non sta girando niente» da «la barra non funziona».
  const attivi = stato.running || [];

  return (
    <div style={{
      border: `1px solid ${attivi.length ? 'rgba(0, 242, 254, 0.45)' : bordo}`,
      borderRadius: 10,
      background: sfondo,
      marginBottom: 10,
      overflow: 'hidden',
    }}>
      <button
        type="button"
        onClick={() => setAperto((v) => !v)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '7px 10px', background: 'none', border: 'none',
          cursor: 'pointer', textAlign: 'left', color: testo,
        }}
      >
        <Activity size={13} color={attivi.length ? '#00f2fe' : '#8b949e'} />
        <span style={{ fontSize: '0.66rem', fontWeight: 800 }}>
          {attivi.length
            ? `${attivi.length} in esecuzione`
            : 'Nessun agente in esecuzione'}
        </span>
        {attivi.length > 0 && (
          <span style={{
            width: 7, height: 7, borderRadius: '50%', background: '#00f2fe',
            boxShadow: '0 0 6px #00f2fe',
          }} />
        )}
      </button>

      {attivi.map((voce) => {
        const Icona = ICONA[voce.tipo] || Activity;
        const colore = COLORE[voce.tipo] || '#8b949e';
        const coda = voce.queue || null;
        const piano = voce.pipeline || null;
        return (
          <div key={voce.id} style={{
            padding: '6px 10px 8px', borderTop: `1px solid ${bordo}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Icona size={12} color={colore} />
              <span style={{
                fontSize: '0.63rem', fontWeight: 700, color: colore,
                textTransform: 'uppercase', letterSpacing: '0.04em',
              }}>
                {voce.tipo}
              </span>
              <Clock size={10} color="#8b949e" />
              <span style={{ fontSize: '0.6rem', color: '#8b949e' }}>
                {durata(voce.iniziato)}
              </span>
            </div>

            <div style={{
              fontSize: '0.64rem', color: testo, marginTop: 3,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }} title={voce.titolo}>
              {voce.titolo || '(senza titolo)'}
            </div>

            {voce.progress && (
              <div style={{ fontSize: '0.6rem', color: '#8b949e', marginTop: 2 }}>
                {voce.progress}
              </div>
            )}

            {/* La coda del ventaglio: è la domanda «a che punto siamo». */}
            {coda && (
              <div style={{
                display: 'flex', gap: 8, marginTop: 4,
                fontSize: '0.58rem', fontWeight: 700,
              }}>
                <span style={{ color: '#3fb950' }}>{coda.done} fatte</span>
                <span style={{ color: '#00f2fe' }}>{coda.doing} in corso</span>
                <span style={{ color: '#8b949e' }}>{coda.todo} da fare</span>
                {coda.blocked > 0 && (
                  <span style={{ color: '#d29922' }}>{coda.blocked} bloccate</span>
                )}
                {coda.failed > 0 && (
                  <span style={{ color: '#f85149' }}>{coda.failed} ferme</span>
                )}
              </div>
            )}

            {/* Il piano della squadra, quando c'è: senza, si sa che qualcosa
                gira ma non quale task. */}
            {piano && (
              <div style={{ fontSize: '0.58rem', color: '#8b949e', marginTop: 4 }}>
                piano: {piano.done ?? 0}/{piano.total ?? 0} task
                {typeof piano.progress_percent === 'number' &&
                  ` (${Math.round(piano.progress_percent)}%)`}
              </div>
            )}

            {voce.workspace_root && (
              <div style={{
                fontSize: '0.56rem', color: '#6e7681', marginTop: 3,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }} title={voce.workspace_root}>
                {voce.workspace_root}
              </div>
            )}
          </div>
        );
      })}

      {aperto && (stato.recent || []).length > 0 && (
        <div style={{ borderTop: `1px solid ${bordo}`, padding: '6px 10px' }}>
          <div style={{
            fontSize: '0.58rem', fontWeight: 800, color: '#8b949e',
            marginBottom: 4, letterSpacing: '0.04em',
          }}>
            APPENA FINITI
          </div>
          {(stato.recent || []).slice(0, 6).map((voce, i) => (
            <div key={`${voce.id}-${i}`} style={{
              fontSize: '0.6rem', color: '#8b949e', padding: '1px 0',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              <span style={{
                color: voce.esito === 'obiettivo raggiunto' ? '#3fb950' : '#8b949e',
              }}>
                ●
              </span>{' '}
              {voce.titolo || voce.tipo} — {voce.esito}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
