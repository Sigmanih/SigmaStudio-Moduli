import React, { useState } from 'react';
import { Cpu, Gauge, Download, CheckCircle2, Loader2, Play, Server, RotateCcw } from 'lucide-react';

/*
 * Motori video: GPU e corsie, istanze ComfyUI, componenti installabili e
 * risultati del benchmark. I numeri del benchmark sono quelli che hanno deciso
 * i valori predefiniti delle produzioni.
 */

const BENCH_SETS = [
  { id: 'comfy_sage,comfy_sage_easycache', label: 'ComfyUI: Sage e EasyCache' },
  { id: 'comfy_sage_gpu1', label: 'ComfyUI sulla seconda GPU' },
  { id: 'native_q4_sage,native_int8_sage', label: 'Motore nativo (sd.cpp)' },
];

/**
 * Token Hugging Face per i modelli "gated" (es. LTX-2.5): la licenza la accetti tu
 * sul sito con il tuo account, il token serve solo a scaricare. Salvato sul server,
 * non viene mai rimandato all'interfaccia.
 */
function HfTokenField({ has, onSaved }) {
  const [value, setValue] = useState('');
  const [message, setMessage] = useState('');
  const save = async () => {
    const d = await (await fetch('/api/creative/video/token', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hf_token: value.trim() }),
    })).json().catch(() => ({}));
    setMessage(d.success ? (d.has_token ? 'Token salvato.' : 'Token rimosso.') : (d.error || 'Errore'));
    setValue('');
    onSaved();
  };
  return (
    <div className="cs-prod-row">
      <span className="cs-prod-status">Token Hugging Face: {has ? 'configurato' : 'assente'}</span>
      <input className="cs-inline-input" type="password" autoComplete="off" placeholder="hf_… (tipo Read)"
             value={value} onChange={e => setValue(e.target.value)} />
      <button className="cs-tool-btn" onClick={save} disabled={!value.trim() && !has}>{value.trim() ? 'Salva' : 'Rimuovi'}</button>
      {message && <span className="cs-hint">{message}</span>}
    </div>
  );
}

export default function EnginesPanel({ engines, onRefresh }) {
  const [restart, setRestart] = useState({ busy: false, message: '' });
  if (!engines) return <div className="cs-prod-main"><p className="cs-hint">Caricamento…</p></div>;
  const restartServices = async () => {
    setRestart({ busy: true, message: '' });
    try {
      const d = await (await fetch('/api/creative/video/restart', { method: 'POST' })).json();
      const ports = d.stopped?.comfyui || [];
      setRestart({ busy: false, message: d.success
        ? `Servizi chiusi${ports.length ? ` (ComfyUI :${ports.join(', :')})` : ''}: ripartono alla prossima richiesta.`
        : d.error });
    } catch (e) {
      setRestart({ busy: false, message: String(e) });
    }
    onRefresh();
  };
  const post = async (url, body) => {
    await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    onRefresh();
  };
  const bench = engines.benchmark_state || {};
  return (
    <div className="cs-prod-main">
      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><Cpu size={18} /> GPU e corsie
          <button className="cs-tool-btn" style={{ marginLeft: 'auto' }} disabled={restart.busy}
                  title="Chiude le istanze ComfyUI avviate da Sigma, il worker voci e il giudice visivo"
                  onClick={restartServices}>
            {restart.busy ? <Loader2 size={14} className="cs-spin-icon" /> : <RotateCcw size={14} />} Riavvia servizi
          </button>
        </h3>
        {restart.message && <p className="cs-hint">{restart.message}</p>}
        <div className="cs-prod-files">
          {(engines.gpus || []).map(g => {
            const inst = (engines.comfy?.instances || []).find(i => i.gpu === g.index);
            const lease = (engines.leases || []).find(l => (l.devices || []).includes(g.index));
            return (
              <div key={g.index} className="cs-prod-file">
                <span className="cs-prod-file-name">GPU {g.index} · {g.name}</span>
                <span>{g.vram_gb} GB</span>
                <span><Server size={12} /> ComfyUI :{inst?.port} {inst?.alive ? `attivo ${inst.flags.join(' ')}` : 'spento'}</span>
                <span>{lease ? `riservata a ${lease.owner}` : 'libera'}</span>
              </div>
            );
          })}
        </div>
        <p className="cs-hint">
          ComfyUI: {engines.comfy?.installed ? engines.comfy.path : 'non trovato'} · ottimizzazioni predefinite:
          {' '}{(engines.comfy?.default_flags || []).join(' ') || 'nessuna'} · motore nativo:
          {' '}{engines.native?.installed ? 'pronto' : engines.native?.detail}
        </p>
      </div>

      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><Gauge size={18} /> Benchmark (MiniMax H3, 864×480)</h3>
        <table className="cs-prod-table">
          <thead><tr><th>Configurazione</th><th>Frame</th><th>Clip</th><th>s/step</th><th>VRAM picco</th></tr></thead>
          <tbody>
            {(engines.benchmark || []).map(b => (
              <tr key={b.config}>
                <td title={b.config}>{b.label}{b.cold ? ' (a freddo)' : ''}</td>
                <td>{b.frames}</td>
                <td>{b.wall_s} s</td>
                <td>{b.s_per_step ?? '—'}</td>
                <td>{Object.entries(b.peak_vram_mib || {}).map(([k, v]) => `GPU${k} ${(v / 1024).toFixed(1)}G`).join(' · ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="cs-button-grid">
          {BENCH_SETS.map(b => (
            <button key={b.id} className="cs-tool-btn" disabled={bench.running}
                    onClick={() => post('/api/creative/video/benchmark', { configs: b.id, runs: 2 })}>
              {bench.running ? <Loader2 size={14} className="cs-spin-icon" /> : <Play size={14} />} {b.label}
            </button>
          ))}
        </div>
        {bench.running && <p className="cs-hint">Benchmark in corso: {bench.configs}. Non avviare produzioni nel frattempo.</p>}
      </div>

      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><Download size={18} /> Componenti</h3>
        <HfTokenField has={engines.has_hf_token} onSaved={onRefresh} />
        <div className="cs-prod-files">
          {(engines.components || []).map(c => (
            <div key={c.id} className="cs-prod-file">
              <span className="cs-prod-file-name">{c.label}</span>
              <span>{c.size_gb >= 1 ? `${c.size_gb} GB` : `${Math.round(c.size_gb * 1024)} MB`}</span>
              {c.installed
                ? <span className="ok"><CheckCircle2 size={12} /> installato</span>
                : c.job?.status === 'running'
                  ? <span><Loader2 size={12} className="cs-spin-icon" /> {c.job.message} {c.job.progress != null ? `${c.job.progress}%` : ''}</span>
                  : <button className="cs-tool-btn" onClick={() => post('/api/creative/video/install', { component: c.id })}>
                      <Download size={13} /> Installa
                    </button>}
              {c.job?.status === 'error' && <span className="bad">{c.job.message}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
