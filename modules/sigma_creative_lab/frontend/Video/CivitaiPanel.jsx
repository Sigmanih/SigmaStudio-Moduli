import React, { useCallback, useEffect, useState } from 'react';
import { Link2, Download, ShieldAlert, CheckCircle2, KeyRound, Loader2, AlertTriangle, Trash2, Package, RotateCw } from 'lucide-react';

/*
 * Import da Civitai: un link (video, immagine, modello o versione) diventa
 * l'elenco dei file con la cartella di ComfyUI in cui vanno. I file non sicuri
 * (pickle, scansioni non concluse) restano bloccati: non c'e' un "forza".
 */

function fmtGb(gb) { return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(gb * 1024)} MB`; }

const FAMILY_LABEL = { minimax_h3: 'MiniMax H3', ltx: 'LTX', wan21: 'Wan 2.1', wan22: 'Wan 2.2', flux: 'FLUX.1',
  flux2: 'FLUX.2', sdxl: 'SDXL', sd15: 'SD 1.5', sd3: 'SD 3', z_image: 'Z-Image', qwen_image: 'Qwen-Image' };

/*
 * Cio' che e' gia' arrivato da Civitai: dove sta, per quale motore, chi lo usa, e la rimozione.
 * Si rimuovono solo i file importati da qui (hanno la scheda .civitai.json): i modelli del
 * Video Studio e quelli copiati a mano non compaiono.
 */
function InstalledCard({ refreshKey }) {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    try {
      const d = await (await fetch('/api/creative/civitai/installed')).json();
      setItems(d.success ? d.items : []);
    } catch { setItems([]); }
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);

  const remove = async (it, force = false) => {
    const what = it.present ? `${it.model_name} (${fmtGb(it.size_gb)})` : `la scheda del download incompleto ${it.name}`;
    if (!force && !window.confirm(`Rimuovere ${what}?`)) return;
    setBusy(it.name); setNote('');
    try {
      const res = await fetch('/api/creative/civitai/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: it.folder, name: it.name, force }),
      });
      const d = await res.json();
      if (!d.success) throw new Error(d.error);
      if (!d.deleted && d.used_by?.length) {
        const titles = d.used_by.map(u => u.title).join(', ');
        if (window.confirm(`${it.model_name} e' usato da: ${titles}. Rimuoverlo comunque? Quelle produzioni lo ignoreranno.`)) {
          await remove(it, true);
        }
        return;
      }
      setNote(d.freed_gb ? `Liberati ${fmtGb(d.freed_gb)}.` : 'Rimosso.');
      load();
    } catch (e) { setNote(e.message); } finally { setBusy(''); }
  };

  const retry = async (it) => {
    setBusy(it.name); setNote('');
    try {
      const res = await fetch('/api/creative/civitai/retry', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: it.folder, name: it.name }),
      });
      const d = await res.json();
      if (!d.success) throw new Error(d.error);
      setNote(d.file?.status === 'installed' ? `${it.model_name}: gia' presente.` : `${it.model_name}: download ripreso.`);
      load();
    } catch (e) { setNote(e.message); } finally { setBusy(''); }
  };

  // Mentre qualcosa scarica, l'elenco si aggiorna da solo.
  useEffect(() => {
    if (!items?.some(it => it.state === 'downloading')) return undefined;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [items, load]);

  const stateLabel = (it) => {
    if (it.present) return fmtGb(it.size_gb);
    if (it.state === 'downloading') return `in download ${it.progress ?? 0}%`;
    return 'da completare';
  };

  if (!items) return null;
  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><Package size={18} /> Installati da Civitai</h3>
      {items.length === 0 && <p className="cs-hint">Nessun modello importato.</p>}
      <div className="cs-prod-files">
        {items.map(it => (
          <div key={`${it.folder}/${it.name}`} className={`cs-prod-file cs-civ-row ${it.present ? "" : "blocked"}`}>
            <span className="cs-prod-file-name" title={`${it.name}${it.source ? ` · ${it.source}` : ''}`}>
              {it.model_name}{it.version_name ? ` · ${it.version_name}` : ''}
            </span>
            <span>{FAMILY_LABEL[it.family] || it.base_model || 'motore ?'}</span>
            <span title={it.error || ''}>{stateLabel(it)}</span>
            <span>{it.folder}</span>
            <span title={(it.used_by || []).map(u => u.title).join(', ')}>
              {it.used_by?.length ? `usato da ${it.used_by.length}` : ''}
            </span>
            {!it.present && it.state !== 'downloading' ? (
              <button className="cs-icon-btn" title={it.error ? `Riprendi il download (ultimo errore: ${it.error})` : 'Riprendi il download'}
                      disabled={!!busy} onClick={() => retry(it)}>
                {busy === it.name ? <Loader2 size={12} className="cs-spin-icon" /> : <RotateCw size={12} />}
              </button>
            ) : <span />}
            <button className="cs-icon-btn" title={it.present ? 'Rimuovi' : 'Ripulisci la scheda'} disabled={!!busy} onClick={() => remove(it)}>
              {busy === it.name ? <Loader2 size={12} className="cs-spin-icon" /> : <Trash2 size={12} />}
            </button>
          </div>
        ))}
      </div>
      <p className="cs-hint">Le LoRA si scelgono per ogni produzione in Produzioni → Resa → LoRA: compaiono solo quelle del motore video scelto.</p>
      {note && <p className="cs-hint">{note}</p>}
    </div>
  );
}

export default function CivitaiPanel() {
  const [url, setUrl] = useState('');
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState({});        // version_id -> Set di file id
  const [jobs, setJobs] = useState([]);
  const [token, setToken] = useState('');
  const [tokenSaved, setTokenSaved] = useState(null);

  const refreshJobs = useCallback(async () => {
    try {
      const d = await (await fetch('/api/creative/video/downloads')).json();
      setJobs(d.jobs || []);
    } catch { /* il prossimo giro riprova */ }
  }, []);

  useEffect(() => {
    refreshJobs();
    const t = setInterval(refreshJobs, 3000);
    return () => clearInterval(t);
  }, [refreshJobs]);

  const resolve = async () => {
    setBusy(true); setError(''); setInfo(null);
    try {
      const d = await (await fetch(`/api/creative/civitai/resolve?url=${encodeURIComponent(url)}`)).json();
      if (!d.success) throw new Error(d.error);
      setInfo(d);
      setTokenSaved(d.has_token);
      // Preselezione: i file importabili non ancora presenti. Le varianti alternative
      // (stesso ruolo, altra precisione) le sceglie l'utente.
      const pre = {};
      d.versions.forEach(v => {
        const primary = (v.files || []).filter(f => f.importable && !f.installed && (f.primary || v.files.length === 1));
        pre[v.version_id] = new Set(primary.map(f => f.id));
      });
      setSelected(pre);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const toggle = (vid, fid) => setSelected(prev => {
    const next = new Set(prev[vid] || []);
    if (next.has(fid)) next.delete(fid); else next.add(fid);
    return { ...prev, [vid]: next };
  });

  const doImport = async (vid) => {
    setError('');
    try {
      const res = await fetch('/api/creative/civitai/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version_id: vid, file_ids: [...(selected[vid] || [])] }),
      });
      const d = await res.json();
      if (!d.success) throw new Error(d.error);
      const blocked = d.files.filter(f => f.status === 'blocked');
      if (blocked.length) setError(`Bloccati: ${blocked.map(f => f.file).join(', ')}`);
      refreshJobs();
    } catch (e) { setError(e.message); }
  };

  const saveToken = async () => {
    const d = await (await fetch('/api/creative/video/token', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ civitai_token: token }),
    })).json();
    if (d.success) { setTokenSaved(d.has_token); setToken(''); } else setError(d.error);
  };

  const active = jobs.filter(j => j.asset_id?.startsWith('civitai:'));

  return (
    <div className="cs-prod-main">
      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><Link2 size={18} /> Importa da Civitai</h3>
        <div className="cs-prod-row">
          <input className="cs-inline-input cs-prod-wide" value={url} onChange={e => setUrl(e.target.value)}
                 placeholder="https://civitai.com/... o https://civitai.red/models/... (o /images/...)"
                 onKeyDown={e => e.key === 'Enter' && url.trim() && resolve()} />
          <button className="cs-tool-btn" disabled={busy || !url.trim()} onClick={resolve}>
            {busy ? <Loader2 size={14} className="cs-spin-icon" /> : <Link2 size={14} />} Analizza
          </button>
        </div>
        {tokenSaved === false && (
          <div className="cs-banner warn">
            <KeyRound size={16} />
            <span>Civitai (.com / .red) richiede un token API per scaricare (Account → API Keys).</span>
          </div>
        )}
        <div className="cs-prod-row">
          <input className="cs-inline-input cs-prod-wide" type="password" value={token} autoComplete="off"
                 placeholder={tokenSaved ? 'Token Civitai salvato (scrivi per sostituirlo)' : 'Token API Civitai'}
                 onChange={e => setToken(e.target.value)} />
          <button className="cs-tool-btn" disabled={!token.trim()} onClick={saveToken}><KeyRound size={14} /> Salva</button>
        </div>
        {error && <p className="cs-prod-error">{error}</p>}
      </div>

      {info?.image && (
        <div className="cs-mesh-card">
          <h3 className="cs-mesh-title">Media di partenza</h3>
          {info.image.type === 'video'
            ? <video className="cs-prod-clip" src={info.image.url} controls muted />
            : <img className="cs-prod-clip" src={info.image.url} alt="" />}
          <p className="cs-hint">
            {info.image.width}×{info.image.height} · {info.image.base_model}
            {info.image.meta ? '' : ' · prompt e workflow non pubblicati'}
          </p>
        </div>
      )}

      {(info?.versions || []).map(v => (
        <div key={v.version_id} className="cs-mesh-card">
          <h3 className="cs-mesh-title">
            {v.model_name} <span className="cs-prod-status">· {v.version_name} · {v.model_type} · {v.base_model}</span>
          </h3>
          {v.error && <p className="cs-prod-error">{v.error}</p>}
          <p className="cs-hint">
            Motori: {(v.engines || []).join(', ') || 'nessuno noto'}
            {v.trained_words?.length ? ` · parole chiave: ${v.trained_words.join(' ')}` : ''}
            {v.license && !(v.license.commercial_use || []).includes('Sell') ? ' · uso commerciale limitato' : ''}
            {v.early_access ? ' · accesso anticipato o a pagamento' : ''}
          </p>
          <div className="cs-prod-files">
            {(v.files || []).map(f => (
              <label key={f.id} className={`cs-prod-file ${f.importable ? '' : 'blocked'}`}>
                <input type="checkbox" disabled={!f.importable || f.installed}
                       checked={f.installed || (selected[v.version_id]?.has(f.id) ?? false)}
                       onChange={() => toggle(v.version_id, f.id)} />
                <span className="cs-prod-file-name" title={f.name}>{f.name}</span>
                <span>{f.type}{f.precision ? ` · ${f.precision}` : ''}</span>
                <span>{fmtGb(f.size_gb)}</span>
                <span>{f.folder ? `→ ${f.folder}` : ''}</span>
                {f.installed && <span className="ok"><CheckCircle2 size={12} /> presente</span>}
                {!f.importable && <span className="bad" title={f.blocked_reasons.join('\n')}><ShieldAlert size={12} /> {f.blocked_reasons[0]}</span>}
              </label>
            ))}
          </div>
          <button className="cs-tool-btn" disabled={!(selected[v.version_id]?.size)} onClick={() => doImport(v.version_id)}>
            <Download size={14} /> Importa {selected[v.version_id]?.size || 0} file
          </button>
        </div>
      ))}

      <InstalledCard refreshKey={jobs.filter(j => j.status === 'done').length} />

      {active.length > 0 && (
        <div className="cs-mesh-card">
          <h3 className="cs-mesh-title"><Download size={18} /> Download</h3>
          {active.map(j => (
            <div key={j.job_id} className="cs-prod-dl">
              <span title={j.target}>{j.label}</span>
              <div className="cs-prod-bar"><div style={{ width: `${j.progress || 0}%` }} /></div>
              <span>
                {j.status === 'error' ? <><AlertTriangle size={12} /> {j.error}</> : `${j.status} ${j.progress || 0}%`}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
