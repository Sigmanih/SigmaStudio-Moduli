import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Play, Pause, Undo2, Redo2, Download, Subtitles, ZoomIn, ZoomOut, SkipBack, RotateCcw, Loader2,
  AlertTriangle, CheckCircle2, X, MessageSquare, SlidersHorizontal, Upload, Heading, Type, FilePlus2, GraduationCap,
} from 'lucide-react';
import Player from './Player';
import Timeline from './Timeline';
import Inspector from './Inspector';
import DialoguePanel from './DialoguePanel';
import { OverlayLayer } from './Overlays';

/*
 * Editor video: anteprima, timeline multitraccia, modifiche manuali e con AI.
 * Lo stato vero sta sul server (timeline.json): ogni operazione risponde con
 * la timeline aggiornata, e la UI si limita a mostrarla.
 */

const JOB_LABEL = {
  regen_range: 'Rigenera tratto', redo: 'Rifai elemento', recolor: 'Ricolora', upscale: 'Ingrandisci',
  restore_read: 'Leggi i testi', restore_narrate: 'Narrazione', restore_score: 'Colonna sonora',
  restore_fetch: 'Scarica film', extend: 'Estendi', insert: 'Inserisci',
  dialogue: 'Dialogo', voice_line: 'Battuta', music_range: 'Musica', export: 'Export', subtitles: 'Sottotitoli',
  import: 'Importa', title: 'Titolo', scene: 'Scena didattica', lesson: 'Lezione animata', scene_redo: 'Rifai scena',
};

function LessonForm({ onCreate, onClose }) {
  const [topic, setTopic] = useState('');
  const [minutes, setMinutes] = useState(1);
  const [audience, setAudience] = useState('studenti delle superiori');
  const [voices, setVoices] = useState([]);
  const [voiceId, setVoiceId] = useState('');
  useEffect(() => {
    fetch('/api/voices/library').then(r => r.json()).then(d => setVoices(d.voices || [])).catch(() => setVoices([]));
  }, []);
  return (
    <div className="cs-ed-popover">
      <h4><GraduationCap size={14} /> Lezione animata</h4>
      <textarea className="cs-textarea" rows={3} autoFocus value={topic} onChange={e => setTopic(e.target.value)}
                placeholder="Argomento: es. 'la legge di Ohm con un esempio numerico' o 'derivata di una funzione: significato geometrico'" />
      <div className="cs-prod-row">
        <label className="cs-ed-inline">minuti
          <input type="number" min="0.5" max="10" step="0.5" value={minutes} onChange={e => setMinutes(Number(e.target.value))} />
        </label>
        <select className="cs-select" value={audience} onChange={e => setAudience(e.target.value)}>
          <option value="studenti delle medie">Scuola media</option>
          <option value="studenti delle superiori">Superiori</option>
          <option value="studenti universitari">Università</option>
          <option value="pubblico generale, senza prerequisiti">Pubblico generale</option>
        </select>
        <select className="cs-select" value={voiceId} onChange={e => setVoiceId(e.target.value)}>
          <option value="">Voce: Sara (predefinita)</option>
          {voices.map(v => <option key={v.id} value={v.id}>Voce: {v.name}</option>)}
        </select>
      </div>
      <p className="cs-hint">Copione, una scena con formule o grafici per capitolo, voce narrante allineata: tutto in coda alla timeline.
        Poi puoi aggiungere i sottotitoli e la musica.</p>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" disabled={!topic.trim()}
                onClick={() => onCreate({ topic, minutes, audience, voice_id: voiceId || undefined })}>Crea la lezione</button>
        <button className="cs-tool-btn" onClick={onClose}>Annulla</button>
      </div>
    </div>
  );
}

function SceneForm({ onCreate, onClose }) {
  const [description, setDescription] = useState('');
  const [seconds, setSeconds] = useState(10);
  const [mode, setMode] = useState('kit');
  return (
    <div className="cs-ed-popover">
      <h4><GraduationCap size={14} /> Scena didattica</h4>
      <textarea className="cs-textarea" rows={4} autoFocus value={description} onChange={e => setDescription(e.target.value)}
                placeholder="Cosa deve spiegare: es. 'il moto di un proiettile: formula della traiettoria, poi la parabola con i vettori velocita'' oppure 'il teorema di Pitagora passo per passo'" />
      <div className="cs-prod-row">
        <button className={`cs-prod-chip ${mode === 'kit' ? 'on' : ''}`} onClick={() => setMode('kit')}
                title="Formule, grafici, traiettorie ed elenchi disegnati in modo esatto">A blocchi (consigliato)</button>
        <button className={`cs-prod-chip ${mode === 'html' ? 'on' : ''}`} onClick={() => setMode('html')}
                title="Il modello scrive HTML/CSS/JS libero: piu' vario, meno affidabile">HTML libero</button>
        <label className="cs-ed-inline">s
          <input type="number" min="4" max="40" step="1" value={seconds} onChange={e => setSeconds(Number(e.target.value))} />
        </label>
      </div>
      <p className="cs-hint">Il modello della chat progetta la scena, il browser la rende fotogramma per fotogramma: formule e curve sono esatte.</p>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" disabled={!description.trim()} onClick={() => onCreate({ description, seconds, mode })}>Crea al cursore</button>
        <button className="cs-tool-btn" onClick={onClose}>Annulla</button>
      </div>
    </div>
  );
}

const CHUNK = 8 * 1024 * 1024;
const ACCEPT = 'video/*,image/*,audio/*';

/** Carica un file a pezzi da 8 MB: una registrazione di centinaia di MB non passa da un unico JSON. */
async function uploadFile(pid, file, onProgress) {
  const upload = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
  let offset = 0;
  while (offset < file.size) {
    const chunk = file.slice(offset, offset + CHUNK);
    const res = await fetch(`/api/creative/editor/import_chunk?id=${encodeURIComponent(pid)}&upload=${upload}&offset=${offset}`,
      { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: chunk });
    const d = await res.json().catch(() => ({}));
    if (!res.ok || d.success === false) throw new Error(d.error || `HTTP ${res.status}`);
    offset = d.size;
    onProgress(offset / file.size);
  }
  return upload;
}

function TitleForm({ onCreate, onClose }) {
  const [title, setTitle] = useState('');
  const [sub, setSub] = useState('');
  const [seconds, setSeconds] = useState(3.5);
  const [background, setBackground] = useState('scene');
  return (
    <div className="cs-ed-popover">
      <h4><Heading size={14} /> Nuovo cartello</h4>
      <input className="cs-inline-input cs-prod-wide" autoFocus placeholder="Titolo" value={title} onChange={e => setTitle(e.target.value)} />
      <input className="cs-inline-input cs-prod-wide" placeholder="Sottotitolo (facoltativo)" value={sub} onChange={e => setSub(e.target.value)} />
      <div className="cs-prod-row">
        <button className={`cs-prod-chip ${background === 'scene' ? 'on' : ''}`} onClick={() => setBackground('scene')}>Scena sfocata</button>
        <button className={`cs-prod-chip ${background === 'color' ? 'on' : ''}`} onClick={() => setBackground('color')}>Sfondo scuro</button>
        <label className="cs-ed-inline">s
          <input type="number" min="1" max="15" step="0.5" value={seconds} onChange={e => setSeconds(Number(e.target.value))} />
        </label>
      </div>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" disabled={!title.trim()} onClick={() => onCreate({ title, sub, seconds, background })}>Inserisci al cursore</button>
        <button className="cs-tool-btn" onClick={onClose}>Annulla</button>
      </div>
    </div>
  );
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* risposta non JSON */ }
  if (!res.ok || data.success === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export default function EditorView({ productionId, onPickProduction }) {
  const [productions, setProductions] = useState([]);
  const [data, setData] = useState(null);
  const [media, setMedia] = useState({});
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selection, setSelection] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [side, setSide] = useState('inspector');
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState('');
  const [uploads, setUploads] = useState([]);
  const [titleForm, setTitleForm] = useState(false);
  const [sceneForm, setSceneForm] = useState(false);
  const [lessonForm, setLessonForm] = useState(false);
  const [dropping, setDropping] = useState(false);
  const fileInput = useRef(null);
  const player = useRef(null);
  const pid = productionId;

  useEffect(() => {
    api('/api/creative/productions').then(d => setProductions(d.productions || [])).catch(e => setError(e.message));
  }, []);

  const load = useCallback(async () => {
    if (!pid) return;
    try { setData(await api(`/api/creative/editor/timeline?id=${encodeURIComponent(pid)}`)); }
    catch (e) { setError(e.message); }
  }, [pid]);

  useEffect(() => { setData(null); setMedia({}); setSelection(null); load(); }, [load]);

  // Miniature, copie per lo scrubbing e forme d'onda: si chiedono una volta per elemento.
  useEffect(() => {
    if (!data) return;
    const missing = [
      ...data.items.filter(it => !media[it.id]).map(it => ['item', it.id]),
      ...data.timeline.audio.filter(t => t.kind !== 'clip').flatMap(t => t.clips)
        .filter(c => !media[c.id]).map(c => ['clip', c.id]),
    ];
    missing.slice(0, 8).forEach(([kind, id]) => {
      setMedia(m => ({ ...m, [id]: m[id] || { pending: true } }));
      api(`/api/creative/editor/media?id=${encodeURIComponent(pid)}&${kind}=${id}`)
        .then(d => setMedia(m => ({ ...m, [id]: d })))
        .catch(() => setMedia(m => ({ ...m, [id]: { failed: true } })));
    });
  }, [data, media, pid]);

  // Coda dei job: si aggiorna spesso solo quando c'e' qualcosa in corso.
  useEffect(() => {
    if (!pid) return undefined;
    let stop = false;
    let lastDone = 0;
    const poll = async () => {
      try {
        const d = await api(`/api/creative/editor/jobs?id=${encodeURIComponent(pid)}`);
        if (stop) return;
        setJobs(d.jobs || []);
        const done = (d.jobs || []).filter(j => j.status === 'done').length;
        if (done !== lastDone) { lastDone = done; load(); }
      } catch { /* il prossimo giro riprova */ }
    };
    poll();
    const t = setInterval(poll, 2500);
    return () => { stop = true; clearInterval(t); };
  }, [pid, load]);

  const op = useCallback(async (name, args) => {
    setError('');
    try {
      const d = await api('/api/creative/editor/op', { id: pid, op: name, args });
      setData(d);
      if (['delete', 'audio_delete', 'overlay_delete'].includes(name)) setSelection(null);
      // Un testo appena aggiunto si seleziona subito: lo si vuole scrivere.
      if (name === 'overlay_add' && d.result?.overlay) setSelection({ type: 'overlay', id: d.result.overlay });
    } catch (e) { setError(e.message); }
  }, [pid]);

  const undo = useCallback(async (redo = false) => {
    setError('');
    try { setData(await api('/api/creative/editor/undo', { id: pid, redo })); } catch (e) { setError(e.message); }
  }, [pid]);

  const job = useCallback(async (kind, args = {}) => {
    setError('');
    try {
      const d = await api('/api/creative/editor/job', { id: pid, kind, args });
      setJobs(j => [d.job, ...j]);
    } catch (e) { setError(e.message); }
  }, [pid]);

  const importFiles = useCallback(async (files) => {
    const at = player.current?.time() ?? time;
    for (const file of Array.from(files || [])) {
      const key = `${file.name}-${Date.now()}`;
      setUploads(u => [...u, { key, name: file.name, progress: 0 }]);
      try {
        const upload = await uploadFile(pid, file, p => setUploads(u => u.map(x => (x.key === key ? { ...x, progress: p } : x))));
        const d = await api('/api/creative/editor/import', { id: pid, upload, filename: file.name, t: at });
        setJobs(j => [d.job, ...j]);
      } catch (e) { setError(`${file.name}: ${e.message}`); }
      setUploads(u => u.filter(x => x.key !== key));
    }
  }, [pid, time]);

  const addText = () => {
    const t = player.current?.time() ?? time;
    op('overlay_add', { text: 'Nuovo testo', sub: '', style: 'lower', start: t, end: t + 3 })
      .then(() => setSide('inspector'));
  };

  const seek = (t) => { setTime(t); player.current?.seek(t); };
  const toggle = () => { player.current?.toggle(); setPlaying(p => !p); };

  useEffect(() => {
    const onKey = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      if (e.code === 'Space') { e.preventDefault(); toggle(); }
      else if (e.key === 's' || e.key === 'S') op('split', { t: player.current?.time() ?? time });
      else if (e.key === 'Delete' && selection?.type === 'item') op('delete', { item_id: selection.id });
      else if (e.key === 'Delete' && selection?.type === 'audio') op('audio_delete', { clip_id: selection.id });
      else if (e.key === 'Delete' && selection?.type === 'overlay') op('overlay_delete', { overlay_id: selection.id });
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(e.shiftKey); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); undo(true); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  if (!pid) {
    const createEmpty = async () => {
      const title = window.prompt('Titolo del nuovo montaggio', 'Presentazione');
      if (!title) return;
      try {
        const d = await api('/api/creative/productions/create', { title });
        onPickProduction(d.production.id);
      } catch (e) { setError(e.message); }
    };
    return (
      <div className="cs-prod-main">
        <div className="cs-mesh-card">
          <h3 className="cs-mesh-title">Scegli cosa montare</h3>
          <button className="cs-tool-btn" onClick={createEmpty}><FilePlus2 size={14} /> Nuovo montaggio vuoto</button>
          <p className="cs-hint">Un montaggio vuoto parte dai tuoi video, immagini e audio: per presentazioni, demo e tutorial.</p>
          <ul className="cs-prod-list">
            {productions.map(p => (
              <li key={p.id} onClick={() => onPickProduction(p.id)}>
                <strong>{p.title}</strong><span>{p.shots_done} clip · {p.status}</span>
              </li>
            ))}
          </ul>
          {error && <p className="cs-prod-error">{error}</p>}
        </div>
      </div>
    );
  }
  if (!data) return <div className="cs-prod-main"><p className="cs-hint"><Loader2 size={14} className="cs-spin-icon" /> Caricamento della timeline…</p></div>;

  const clipTrack = data.timeline.audio.find(t => t.kind === 'clip');
  const active = jobs.filter(j => j.status === 'queued' || j.status === 'running');
  const recent = jobs.filter(j => j.status === 'done' || j.status === 'error').slice(0, 4);

  return (
    <div className={`cs-ed ${dropping ? 'dropping' : ''}`}
         onDragOver={e => { if (e.dataTransfer?.types?.includes('Files')) { e.preventDefault(); setDropping(true); } }}
         onDragLeave={e => { if (e.currentTarget === e.target) setDropping(false); }}
         onDrop={e => { e.preventDefault(); setDropping(false); importFiles(e.dataTransfer.files); }}>
      {dropping && <div className="cs-ed-dropzone"><Upload size={28} /> Rilascia per inserire al cursore</div>}
      <div className="cs-ed-top">
        <div className="cs-ed-stage">
          <div className="cs-ed-screen">
            <Player ref={player} items={data.items} audioTracks={data.timeline.audio} clipTrack={clipTrack}
                    mediaFor={id => media[id]} onTime={setTime} onEnded={() => setPlaying(false)} />
            <OverlayLayer overlays={data.timeline.overlays} time={time} />
          </div>
          <div className="cs-ed-toolbar">
            <button className="cs-icon-btn" title="Inizio" onClick={() => seek(0)}><SkipBack size={15} /></button>
            <button className="cs-icon-btn" title={playing ? 'Pausa (Spazio)' : 'Riproduci (Spazio)'} onClick={toggle}>{playing ? <Pause size={15} /> : <Play size={15} />}</button>
            <span className="cs-ed-time">{time.toFixed(2)} / {data.duration.toFixed(2)} s</span>
            <button className="cs-icon-btn" title="Annulla (Ctrl+Z)" disabled={!data.history.undo} onClick={() => undo(false)}><Undo2 size={15} /></button>
            <button className="cs-icon-btn" title="Ripeti (Ctrl+Y)" disabled={!data.history.redo} onClick={() => undo(true)}><Redo2 size={15} /></button>
            <button className="cs-icon-btn" title="Zoom -" onClick={() => setZoom(z => Math.max(0.25, z / 1.5))}><ZoomOut size={15} /></button>
            <button className="cs-icon-btn" title="Zoom +" onClick={() => setZoom(z => Math.min(8, z * 1.5))}><ZoomIn size={15} /></button>
            <span className="cs-ed-spacer" />
            <input ref={fileInput} type="file" accept={ACCEPT} multiple hidden
                   onChange={e => { importFiles(e.target.files); e.target.value = ''; }} />
            <button className="cs-tool-btn" title="Video, immagini o audio: entrano al cursore (anche trascinandoli qui)"
                    onClick={() => fileInput.current?.click()}><Upload size={14} /> Importa</button>
            <button className="cs-tool-btn" title="Cartello a tutto schermo con titolo e sottotitolo"
                    onClick={() => setTitleForm(v => !v)}><Heading size={14} /> Titolo</button>
            <button className="cs-tool-btn" title="Spiegazione animata: formule, grafici, traiettorie, elenchi"
                    onClick={() => setSceneForm(v => !v)}><GraduationCap size={14} /> Scena didattica</button>
            <button className="cs-tool-btn" title="Una lezione intera da un argomento: copione, scene, voce narrante"
                    onClick={() => setLessonForm(v => !v)}><GraduationCap size={14} /> Lezione animata</button>
            <button className="cs-tool-btn" title="Testo sovrapposto al video (sottopancia, didascalia)"
                    onClick={addText}><Type size={14} /> Testo</button>
            <button className="cs-tool-btn" title="Riparti dallo storyboard (annullabile)"
                    onClick={() => window.confirm('Ricostruire la timeline dallo storyboard? Si puo\' annullare.') &&
                      api('/api/creative/editor/rebuild', { id: pid }).then(setData).catch(e => setError(e.message))}>
              <RotateCcw size={14} /> Ricostruisci
            </button>
            <button className="cs-tool-btn" onClick={() => job('subtitles')}><Subtitles size={14} /> Sottotitoli</button>
            <button className="cs-tool-btn" onClick={() => job('export')}><Download size={14} /> Esporta</button>
          </div>
          {titleForm && (
            <TitleForm onClose={() => setTitleForm(false)}
                       onCreate={args => { job('title', { ...args, t: player.current?.time() ?? time }); setTitleForm(false); }} />
          )}
          {lessonForm && (
            <LessonForm onClose={() => setLessonForm(false)}
                        onCreate={args => { job('lesson', args); setLessonForm(false); }} />
          )}
          {sceneForm && (
            <SceneForm onClose={() => setSceneForm(false)}
                       onCreate={args => { job('scene', { ...args, t: player.current?.time() ?? time }); setSceneForm(false); }} />
          )}
          {uploads.map(u => (
            <div key={u.key} className="cs-ed-job running">
              <Loader2 size={12} className="cs-spin-icon" /><span>Caricamento</span>
              <span className="cs-prod-status">{u.name}</span>
              <div className="cs-prod-bar"><div style={{ width: `${u.progress * 100}%` }} /></div>
            </div>
          ))}
          {!data.items.length && (
            <p className="cs-hint">Timeline vuota: trascina qui video, immagini o audio, oppure usa Importa e Titolo.</p>
          )}
          {data.output_url && <p className="cs-hint">Ultimo export: <a href={data.output_url} target="_blank" rel="noreferrer">{data.output_url.split('/').pop()}</a></p>}
        </div>
        <div className="cs-ed-side">
          <div className="cs-prod-row">
            <button className={`cs-prod-chip ${side === 'inspector' ? 'on' : ''}`} onClick={() => setSide('inspector')}>
              <SlidersHorizontal size={12} /> Selezione
            </button>
            <button className={`cs-prod-chip ${side === 'dialogue' ? 'on' : ''}`} onClick={() => setSide('dialogue')}>
              <MessageSquare size={12} /> Voci e dialoghi
            </button>
          </div>
          {side === 'inspector'
            ? <Inspector pid={pid} data={data} selection={selection} time={time} onOp={op} onJob={job} onClear={() => setSelection(null)} />
            : <DialoguePanel pid={pid} data={data} time={time} onJob={job} onReload={load} />}
          {(active.length > 0 || recent.length > 0) && (
            <div className="cs-ed-jobs">
              {[...active, ...recent].map(j => (
                <div key={j.id} className={`cs-ed-job ${j.status}`}>
                  {j.status === 'running' || j.status === 'queued' ? <Loader2 size={12} className="cs-spin-icon" />
                    : j.status === 'done' ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                  <span>{JOB_LABEL[j.kind] || j.kind}</span>
                  <span className="cs-prod-status" title={j.error}>{j.status === 'error' ? j.error : j.message}</span>
                  {j.status === 'running' && <div className="cs-prod-bar"><div style={{ width: `${(j.progress || 0) * 100}%` }} /></div>}
                  {j.status === 'queued' && (
                    <button className="cs-ed-mini" onClick={() => api('/api/creative/editor/job/cancel', { job_id: j.id })}><X size={11} /></button>
                  )}
                </div>
              ))}
            </div>
          )}
          {error && <p className="cs-prod-error">{error}</p>}
        </div>
      </div>
      <Timeline data={data} media={media} time={time} selection={selection} zoom={zoom}
                onSeek={seek} onSelect={setSelection} onOp={op} />
    </div>
  );
}
