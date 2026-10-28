import React, { useState, useEffect, useCallback } from 'react';
import {
  MonitorPlay, RefreshCw, Link2, Unlink, Upload, Package, BarChart3, Loader2, CheckCircle2,
  AlertTriangle, Play, Eye, Users, Film, Languages, Subtitles, Image as ImageIcon, KeyRound
} from 'lucide-react';
import './styles/youtube-studio.css';

const API_BASE = '/api/youtube';
const DEFAULT_PACKAGE = 'E:\\SigmaRestauri\\youtube\\youtube_package.json';

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let data = null;
  try { data = await res.json(); } catch { /* risposta vuota */ }
  if (!res.ok) throw new Error((data && (data.detail || data.error)) || `Errore HTTP ${res.status}`);
  return data;
}

const fmt = (n) => (n == null ? '–' : Number(n).toLocaleString('it-IT'));
const STATUS_LABEL = {
  uploading: 'In caricamento', processing: 'Traduzioni e sottotitoli', done: 'Completato',
  error: 'Errore', interrupted: 'Interrotto',
};

function ClientSetup({ onSaved }) {
  const [json, setJson] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const save = useCallback(async () => {
    setBusy(true); setErr('');
    try {
      await api('/client', { method: 'POST', body: JSON.stringify({ client_json: json }) });
      setJson('');
      onSaved();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }, [json, onSaved]);
  return (
    <div className="yt-card">
      <h3><KeyRound size={16} /> Client OAuth</h3>
      <ol className="yt-steps">
        <li>Google Cloud Console → nuovo progetto → abilita <b>YouTube Data API v3</b> e <b>YouTube Analytics API</b>.</li>
        <li>Schermata consenso OAuth: tipo Esterno, aggiungi il tuo account come utente di test.</li>
        <li>Credenziali → ID client OAuth di tipo <b>App desktop</b> → scarica il JSON.</li>
        <li>Lascia il file <code>client_secret_*.json</code> in <code>config/</code> oppure incollane qui il contenuto.</li>
      </ol>
      <textarea className="yt-input yt-mono" rows={4} value={json} onChange={(e) => setJson(e.target.value)}
        placeholder='{"installed": {"client_id": "...", "client_secret": "..."}}' />
      {err && <div className="yt-error"><AlertTriangle size={14} /> {err}</div>}
      <button className="yt-btn primary" disabled={!json.trim() || busy} onClick={save}>
        {busy ? <Loader2 size={14} className="yt-spin" /> : <CheckCircle2 size={14} />} Salva client
      </button>
    </div>
  );
}

function Connect({ status, onConnected }) {
  const [waiting, setWaiting] = useState(false);
  const [pasted, setPasted] = useState('');
  const [err, setErr] = useState('');

  const start = useCallback(async () => {
    setErr('');
    try {
      const data = await api('/auth/start');
      window.open(data.url, '_blank', 'noopener,width=520,height=680');
      setWaiting(true);
    } catch (e) { setErr(e.message); }
  }, []);

  // La pagina di consenso torna sul backend, non qui: si guarda lo stato finche' il token arriva.
  useEffect(() => {
    if (!waiting) return undefined;
    let tries = 0;
    const id = setInterval(async () => {
      tries += 1;
      try {
        const s = await api('/status');
        if (s.connected) { setWaiting(false); onConnected(); }
      } catch { /* riprova al giro dopo */ }
      if (tries > 100) setWaiting(false);
    }, 3000);
    return () => clearInterval(id);
  }, [waiting, onConnected]);

  const paste = useCallback(async () => {
    setErr('');
    try {
      await api('/auth/paste', { method: 'POST', body: JSON.stringify({ url: pasted }) });
      setPasted('');
      onConnected();
    } catch (e) { setErr(e.message); }
  }, [pasted, onConnected]);

  return (
    <div className="yt-card">
      <h3><Link2 size={16} /> Collega il canale</h3>
      <p className="yt-muted">Client OAuth trovato{status.client_source ? ` (${status.client_source})` : ''}.
        Si apre la pagina di Google: scegli l'account del canale e concedi l'accesso.</p>
      <button className="yt-btn primary" onClick={start} disabled={waiting}>
        {waiting ? <Loader2 size={14} className="yt-spin" /> : <MonitorPlay size={14} />}
        {waiting ? 'In attesa del consenso…' : 'Collega il canale'}
      </button>
      <details className="yt-details">
        <summary>La pagina finale non si apre? (Sigma su un altro computer)</summary>
        <p className="yt-muted">Copia l'indirizzo dalla barra del browser dopo il consenso (inizia con
          http://127.0.0.1) e incollalo qui.</p>
        <div className="yt-row">
          <input className="yt-input" value={pasted} onChange={(e) => setPasted(e.target.value)}
            placeholder="http://127.0.0.1:8000/api/youtube/oauth/callback?code=…" />
          <button className="yt-btn" disabled={!pasted.trim()} onClick={paste}>Completa</button>
        </div>
      </details>
      {err && <div className="yt-error"><AlertTriangle size={14} /> {err}</div>}
    </div>
  );
}

function ChannelCard({ channel, onDisconnect }) {
  if (!channel) return null;
  return (
    <div className="yt-card yt-channel">
      {channel.thumbnail && <img src={channel.thumbnail} alt="" />}
      <div className="yt-channel-info">
        <h3>{channel.title}</h3>
        <div className="yt-stats">
          <span><Users size={13} /> {fmt(channel.subscribers)} iscritti</span>
          <span><Eye size={13} /> {fmt(channel.views)} visualizzazioni</span>
          <span><Film size={13} /> {fmt(channel.videos)} video</span>
        </div>
        {channel.long_uploads && channel.long_uploads !== 'allowed' && (
          <div className="yt-warn"><AlertTriangle size={13} /> Video oltre 15 minuti non abilitati: verifica il canale
            col telefono su youtube.com/verify.</div>
        )}
      </div>
      <button className="yt-btn ghost" onClick={onDisconnect} title="Revoca l'accesso"><Unlink size={14} /> Scollega</button>
    </div>
  );
}

function PublishPackage({ onStarted }) {
  const [path, setPath] = useState(DEFAULT_PACKAGE);
  const [pkg, setPkg] = useState(null);
  const [privacy, setPrivacy] = useState('private');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const preview = useCallback(async () => {
    setErr(''); setPkg(null);
    try {
      const data = await api(`/package?path=${encodeURIComponent(path)}`);
      setPkg(data.package);
      setPrivacy(data.package.privacy || 'private');
    } catch (e) { setErr(e.message); }
  }, [path]);

  const publish = useCallback(async () => {
    const title = pkg.localizations[pkg.default_language].title;
    if (!window.confirm(`Caricare "${title}" sul canale come ${privacy}?`)) return;
    setBusy(true); setErr('');
    try {
      await api('/publish', { method: 'POST', body: JSON.stringify({ package_path: path, privacy }) });
      onStarted();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }, [pkg, path, privacy, onStarted]);

  return (
    <div className="yt-card">
      <h3><Package size={16} /> Pubblica un pacchetto</h3>
      <div className="yt-row">
        <input className="yt-input yt-mono" value={path} onChange={(e) => setPath(e.target.value)} />
        <button className="yt-btn" onClick={preview}>Anteprima</button>
      </div>
      {pkg && (
        <div className="yt-package">
          <div className="yt-package-title">{pkg.localizations[pkg.default_language].title}</div>
          <div className="yt-chips">
            <span className="yt-chip"><Languages size={12} /> {Object.keys(pkg.localizations).join(' · ')}</span>
            <span className="yt-chip"><Subtitles size={12} /> {Object.keys(pkg.captions || {}).join(' · ') || 'nessuno'}</span>
            {pkg.thumbnail && <span className="yt-chip"><ImageIcon size={12} /> miniatura</span>}
            {pkg.contains_synthetic_media && <span className="yt-chip ai">Contenuto IA dichiarato</span>}
          </div>
          <div className="yt-muted yt-mono">{pkg.video}</div>
          {pkg.notes && <div className="yt-warn"><AlertTriangle size={13} /> {pkg.notes}</div>}
          <div className="yt-row">
            <select className="yt-input yt-select" value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
              <option value="private">Privato</option>
              <option value="unlisted">Non in elenco</option>
              <option value="public">Pubblico</option>
            </select>
            <button className="yt-btn primary" disabled={busy} onClick={publish}>
              {busy ? <Loader2 size={14} className="yt-spin" /> : <Upload size={14} />} Carica su YouTube
            </button>
          </div>
        </div>
      )}
      {err && <div className="yt-error"><AlertTriangle size={14} /> {err}</div>}
    </div>
  );
}

function Uploads({ uploads, onResume }) {
  if (!uploads.length) return null;
  return (
    <div className="yt-card">
      <h3><Upload size={16} /> Caricamenti</h3>
      {uploads.map((u) => {
        const pct = Math.round((100 * u.sent) / Math.max(1, u.size));
        return (
          <div key={u.id} className={`yt-upload ${u.status}`}>
            <div className="yt-upload-head">
              <span className="yt-mono">{u.file.split(/[\\/]/).pop()}</span>
              <span className="yt-upload-status">{STATUS_LABEL[u.status] || u.status}</span>
            </div>
            <div className="yt-bar"><div style={{ width: `${pct}%` }} /></div>
            <div className="yt-upload-foot">
              <span>{pct}% · {(u.sent / 1e9).toFixed(2)} / {(u.size / 1e9).toFixed(2)} GB</span>
              {u.video_id && <a href={`https://studio.youtube.com/video/${u.video_id}/edit`} target="_blank" rel="noreferrer">Apri in Studio</a>}
              {(u.status === 'interrupted' || u.status === 'error') && (
                <button className="yt-btn small" onClick={() => onResume(u.id)}><Play size={12} /> Riprendi</button>
              )}
            </div>
            {u.error && <div className="yt-error"><AlertTriangle size={13} /> {u.error}</div>}
            {u.steps?.length > 0 && (
              <div className="yt-chips">
                {u.steps.map((s, i) => (
                  <span key={i} className={`yt-chip ${s.ok ? 'ok' : 'ko'}`} title={s.error || ''}>{s.step}</span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Videos({ videos, onRefresh }) {
  const [report, setReport] = useState({});
  const load = useCallback(async (id) => {
    setReport((r) => ({ ...r, [id]: { loading: true } }));
    try {
      const data = await api(`/analytics?days=28&video_id=${id}`);
      setReport((r) => ({ ...r, [id]: data }));
    } catch (e) { setReport((r) => ({ ...r, [id]: { error: e.message } })); }
  }, []);
  return (
    <div className="yt-card">
      <h3><Film size={16} /> Video del canale
        <button className="yt-btn ghost small yt-right" onClick={onRefresh}><RefreshCw size={12} /></button></h3>
      {!videos.length && <p className="yt-muted">Nessun video ancora.</p>}
      {videos.map((v) => {
        const r = report[v.id];
        return (
          <div key={v.id} className="yt-video">
            {v.thumbnail && <img src={v.thumbnail} alt="" />}
            <div className="yt-video-info">
              <a href={v.url} target="_blank" rel="noreferrer">{v.title}</a>
              <div className="yt-stats">
                <span className={`yt-privacy ${v.privacy}`}>{v.privacy}</span>
                <span><Eye size={12} /> {fmt(v.views)}</span>
                <span><Languages size={12} /> {[v.default_language, ...v.localizations].filter(Boolean).join(' · ') || '–'}</span>
              </div>
              {r && !r.loading && !r.error && (
                <div className="yt-stats yt-analytics">
                  <span>28 gg: {fmt(r.views)} visualizzazioni</span>
                  <span>{fmt(Math.round(r.minutes_watched))} min guardati</span>
                  <span>permanenza {r.avg_view_percent != null ? `${Number(r.avg_view_percent).toFixed(1)}%` : '–'}</span>
                </div>
              )}
              {r?.error && <div className="yt-error"><AlertTriangle size={12} /> {r.error}</div>}
            </div>
            <button className="yt-btn ghost small" onClick={() => load(v.id)} title="Statistiche ultimi 28 giorni">
              {r?.loading ? <Loader2 size={12} className="yt-spin" /> : <BarChart3 size={12} />}
            </button>
          </div>
        );
      })}
    </div>
  );
}

const YouTubeStudio = () => {
  const [status, setStatus] = useState(null);
  const [videos, setVideos] = useState([]);
  const [uploads, setUploads] = useState([]);
  const [error, setError] = useState('');

  const loadStatus = useCallback(async () => {
    try {
      const s = await api('/status');
      setStatus(s);
      setError(s.channel_error || '');
    } catch (e) { setError(e.message); }
  }, []);
  const loadVideos = useCallback(async () => {
    try { setVideos((await api('/videos?limit=25')).videos || []); } catch (e) { setError(e.message); }
  }, []);
  const loadUploads = useCallback(async () => {
    try { setUploads((await api('/uploads')).uploads || []); } catch { /* il pannello resta usabile */ }
  }, []);

  useEffect(() => { loadStatus(); loadUploads(); }, [loadStatus, loadUploads]);
  useEffect(() => { if (status?.connected) loadVideos(); }, [status?.connected, loadVideos]);

  const active = uploads.some((u) => u.status === 'uploading' || u.status === 'processing');
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(loadUploads, 3000);
    return () => clearInterval(id);
  }, [active, loadUploads]);

  const disconnect = useCallback(async () => {
    if (!window.confirm('Scollegare il canale? Sigma non potrà più caricare né leggere le statistiche.')) return;
    await api('/disconnect', { method: 'POST' });
    setVideos([]);
    loadStatus();
  }, [loadStatus]);

  const resume = useCallback(async (id) => {
    try { await api(`/uploads/${id}/resume`, { method: 'POST' }); loadUploads(); } catch (e) { setError(e.message); }
  }, [loadUploads]);

  return (
    <div className="yt-container">
      <div className="yt-header">
        <div className="yt-header-left">
          <MonitorPlay size={20} className="yt-logo" />
          <h2>YouTube Studio</h2>
          {status && (
            <span className={`yt-badge ${status.connected ? 'on' : 'off'}`}>
              {status.connected ? 'Collegato' : 'Non collegato'}
            </span>
          )}
        </div>
        <button className="yt-btn ghost" onClick={() => { loadStatus(); loadUploads(); if (status?.connected) loadVideos(); }}>
          <RefreshCw size={14} /> Aggiorna
        </button>
      </div>
      <div className="yt-body">
        {error && <div className="yt-error"><AlertTriangle size={14} /> {error}</div>}
        {!status && <div className="yt-muted"><Loader2 size={14} className="yt-spin" /> Lettura dello stato…</div>}
        {status && !status.client_configured && <ClientSetup onSaved={loadStatus} />}
        {status && status.client_configured && !status.connected && <Connect status={status} onConnected={loadStatus} />}
        {status?.connected && (
          <>
            <ChannelCard channel={status.channel} onDisconnect={disconnect} />
            <PublishPackage onStarted={loadUploads} />
          </>
        )}
        <Uploads uploads={uploads} onResume={resume} />
        {status?.connected && <Videos videos={videos} onRefresh={loadVideos} />}
      </div>
    </div>
  );
};

export default YouTubeStudio;
