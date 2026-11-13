import { useCallback, useEffect, useState } from 'react';
import { Music, Mic, Radio, Download, RefreshCw, X, RotateCcw } from 'lucide-react';
import MusicTab from '../../components/Music/MusicTab';
import TabHeader from '../../components/common/TabHeader';
import WorkspaceIcon from '../../components/common/WorkspaceIcon';
import { AUDIO_SECTIONS } from '../../services/studioNavigation';
import VoiceStudio from './VoiceStudio';
import AudioEditor from './AudioEditor';
import { useApp } from '../../contexts/AppContext';
import '../../styles/03-modules/audio-studio.css';

async function api(path, body) {
  const response = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok || value.success === false) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

const VIDEO_STATUS={rejected:'Respinto per difetti visivi',review_required:'Da verificare nei dettagli',draft:'Bozza',rendering:'Generazione in corso',assembling:'Montaggio in corso',done:'Pronto',
  failed:'Errore',partial:'Incompleto',cancelled:'Fermato',rendered:'Clip pronte'};

function MusicStudio({ onEdit }) {
  const { openTab } = useApp();
  const openVideo = id => {
    window.sessionStorage.setItem('sigmaAudioVideoProduction',id);
    openTab({name:'Video'},'video_studio');
    window.dispatchEvent(new CustomEvent('sigma_video_open_production',{detail:id}));
  };
  const [engine, setEngine] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [genre, setGenre] = useState('lofi_study');
  const [duration, setDuration] = useState(120);
  const [prompt, setPrompt] = useState('');
  const [seed, setSeed] = useState('');
  const [bpm, setBpm] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState({});
  const [treatments, setTreatments] = useState({});
  const loadJobs = useCallback(async () => {
    try { const value = await api('/api/audio-studio/music/jobs'); setJobs(value.jobs || []); }
    catch (exc) { setError(exc.message); }
  }, []);
  const loadEngine = useCallback(async () => {
    try { setEngine(await api('/api/audio-studio/music/status')); }
    catch (exc) { setError(exc.message); }
  }, []);
  useEffect(() => {
    loadEngine(); loadJobs();
    const timer = window.setInterval(loadJobs, 3000);
    return () => window.clearInterval(timer);
  }, [loadEngine, loadJobs]);
  const act = async (path, body) => {
    setPending(true); setError('');
    try { await api(path, body); await loadJobs(); }
    catch (exc) { setError(exc.message); }
    finally { setPending(false); }
  };
  const preset = engine?.presets?.find(value => value.id === genre);
  const active = jobs.filter(job => ['running', 'queued'].includes(job.status));
  const completed = jobs.filter(job => job.status === 'done' && job.result?.mp3_url);
  const problems = jobs.filter(job => ['error', 'interrupted', 'cancelled'].includes(job.status)).slice(0, 4);
  return <div className="as-music">
    <section className="as-compose" aria-label="Composizione musicale">
      <div className="as-intro"><span className="as-eyebrow">MUSICA PER STUDIARE E CREARE</span>
        <h2>Il suono del tuo prossimo progetto</h2>
        <p>Scegli un’atmosfera e genera una base strumentale. Parti da due minuti, ascolta e poi crea una sessione più lunga.</p>
      </div>
      <div className="as-genres" aria-label="Generi musicali">
        {(engine?.presets || []).map(value => <button key={value.id} className={`as-genre ${genre === value.id ? 'selected' : ''}`}
          aria-pressed={genre === value.id} onClick={() => { setGenre(value.id); setBpm(''); }}>
          <Music size={18} aria-hidden="true" /><strong>{value.name}</strong>
          <span>{value.description}</span><small>{value.bpm} BPM · {value.key}</small>
        </button>)}
      </div>
      <div className="as-form-row"><label>Durata<select value={duration} onChange={event => setDuration(Number(event.target.value))}>
        <option value={120}>Anteprima · 2 minuti</option><option value={300}>5 minuti</option>
        <option value={900}>Sessione · 15 minuti</option><option value={1800}>Sessione · 30 minuti</option>
      </select></label><span className={`as-engine ${engine?.ready ? 'ready' : ''}`}>{engine?.message || 'Verifica del motore locale…'}</span>
      <button className="as-secondary" onClick={loadEngine} aria-label="Ricontrolla motore musicale"><RefreshCw size={15} /></button></div>
      <details><summary>Personalizza la composizione</summary>
        <label>Indicazioni facoltative<textarea value={prompt} maxLength={1200} onChange={event => setPrompt(event.target.value)}
          placeholder="Per esempio: piano più presente, batteria molto discreta, atmosfera serale" /></label>
        <div className="as-form-row"><label>BPM<input type="number" min={40} max={140} value={bpm}
          placeholder={String(preset?.bpm || 72)} onChange={event => setBpm(event.target.value)} /></label>
        <label>Seed<input type="number" min={0} max={2147483647} value={seed} placeholder="Casuale"
          onChange={event => setSeed(event.target.value)} /></label></div>
      </details>
      {preset && <p className="as-scene"><strong>Tema visivo associato</strong> {preset.scene}<br />La generazione del video sarà il passaggio successivo alla scelta della base.</p>}
      {error && <p className="as-error" role="alert">{error}</p>}
      <button className="as-generate" disabled={pending || !engine?.ready} onClick={() => act('/api/audio-studio/music/generate', {
        genre, duration, prompt, ...(seed !== '' ? { seed: Number(seed) } : {}), ...(bpm !== '' ? { bpm: Number(bpm) } : {}),
      })}><Music size={17} /> {pending ? 'Avvio…' : duration === 120 ? 'Genera anteprima di 2 minuti' : 'Genera base musicale'}</button>
      <p className="as-note">Generazione locale · WAV senza perdita e MP3 · controlli su durata, silenzi e ripetizioni anomale.</p>
    </section>
    <section className="as-library" aria-label="Le tue composizioni"><h3>Le tue composizioni</h3>
      {active.map(job => <article key={job.id} className="as-track"><strong>{engine?.presets?.find(p => p.id === job.args.genre)?.name || 'Composizione'}</strong>
        <span role="status">{job.message}</span><progress max={1} value={job.progress || 0} aria-label="Avanzamento composizione" />
        <button className="as-secondary" disabled={pending} onClick={() => act('/api/audio-studio/music/action', {job_id: job.id, action: 'cancel'})}><X size={14} /> Annulla</button></article>)}
      {problems.map(job => <article key={job.id} className="as-track"><p className="as-error">{job.error || job.message || 'Composizione interrotta'}</p>
        <button className="as-secondary" disabled={pending} onClick={() => act('/api/audio-studio/music/action', {job_id: job.id, action: 'resume'})}><RotateCcw size={14} /> Riprendi</button></article>)}
      {!jobs.length && <p className="as-empty">La prima base nasce qui. Scegli un genere e crea un’anteprima.</p>}
      {completed.map(job => <article key={job.id} className="as-track"><strong>{job.result.title}{job.args.revision_of ? ' · Ricomposta' : ''}</strong>
        <span>{(job.result.duration / 60).toFixed(1)} minuti · {job.result.recipe.bpm} BPM · seed {job.result.recipe.seed}</span>
        <audio controls preload="metadata" src={job.result.mp3_url} aria-label={`Ascolta ${job.result.title}`} />
        <div className="as-form-row"><a href={job.result.wav_url} download><Download size={14} /> WAV</a>
          <a href={job.result.mp3_url} download><Download size={14} /> MP3</a></div>
        {job.video && <div className="as-linked-video">
          <strong>Video associato · {VIDEO_STATUS[job.video.status]||job.video.status}</strong>
          <span>{job.video.title}</span>
          {job.video.url && <><video controls preload="none" poster={job.video.poster_url||undefined} src={job.video.url} aria-label={`Video di ${job.result.title}`}/>
            <a href={job.video.url} download><Download size={14}/> Scarica video MP4</a></>}
          <button className="as-secondary" onClick={()=>openVideo(job.video.production_id)}>Apri in Video</button>
        </div>}
        <button className="as-secondary" onClick={()=>onEdit(job.id)}>Modifica nell’editor</button>
        <details><summary>Modifica questa base</summary>
        <label>Come vuoi cambiarla?<textarea value={feedback[job.id] || ''} maxLength={800}
          placeholder="Per esempio: piano più naturale, niente fruscio, meno batteria, melodia più semplice"
          onChange={event => setFeedback(current => ({...current, [job.id]: event.target.value}))} /></label>
        <button className="as-secondary" disabled={pending || !feedback[job.id]?.trim()} onClick={() =>
          act('/api/audio-studio/music/generate', {source_job: job.id, feedback: feedback[job.id]})}>Ricompone con queste indicazioni</button>
        <p className="as-note">Crea una nuova composizione e conserva questa versione. Il modello può cambiare melodia e arrangiamento.</p>
        <label>Modifica questa registrazione<select value={treatments[job.id] || 'soft'} onChange={event =>
          setTreatments(current => ({...current, [job.id]: event.target.value}))}>
          <option value="soft">Alti meno aggressivi</option><option value="warm">Timbro più caldo</option>
          <option value="slower">Tempo più lento del 5%</option></select></label>
        <button className="as-secondary" disabled={pending} onClick={() => act('/api/audio-studio/music/generate',
          {source_job: job.id, treatment: treatments[job.id] || 'soft'})}>Applica a una nuova copia</button>
        </details>
        {(job.args.revision_of || job.result.source_job) && <details><summary>Confronta con la versione precedente</summary>
          <audio controls preload="none" aria-label="Versione precedente" src={jobs.find(old => old.id === (job.args.revision_of || job.result.source_job))?.result?.mp3_url} />
        </details>}
      </article>)}
    </section>
  </div>;
}

export default function AudioStudio() {
  const [sourceJob,setSourceJob] = useState(null);
  const [tab, setTab] = useState(() => {
    try { const value = window.sessionStorage.getItem('sigmaAudioStudioSection'); return AUDIO_SECTIONS.some(s => s.id === value) ? value : 'music'; }
    catch { return 'music'; }
  });
  const selectTab = useCallback(value => {
    if (!AUDIO_SECTIONS.some(s => s.id === value)) return;
    setTab(value);
    try { window.sessionStorage.setItem('sigmaAudioStudioSection', value); } catch { /* La sezione resta selezionata in memoria. */ }
  }, []);
  useEffect(() => {
    const select = event => selectTab(event.detail);
    window.addEventListener('sigma_audio_studio_section', select);
    return () => window.removeEventListener('sigma_audio_studio_section', select);
  }, [selectTab]);
  const section = AUDIO_SECTIONS.find(s => s.id === tab);
  return <div className="as-studio" data-agent-component="AudioStudio"><TabHeader icon={Music} title="Audio" highlight={section.name.toUpperCase()}
    description={section.description} />
    <nav className="as-tabs" aria-label="Sezioni Audio" role="tablist">
      {AUDIO_SECTIONS.map(s => <button type="button" role="tab" key={s.id} id={`audio-tab-${s.id}`}
        aria-selected={tab === s.id} aria-controls="audio-section-panel" tabIndex={tab === s.id ? 0 : -1}
        onKeyDown={event => {
          const index = AUDIO_SECTIONS.findIndex(item => item.id === tab);
          const next = event.key === 'ArrowRight' ? (index + 1) % AUDIO_SECTIONS.length
            : event.key === 'ArrowLeft' ? (index + AUDIO_SECTIONS.length - 1) % AUDIO_SECTIONS.length : -1;
          if (next >= 0) { event.preventDefault(); selectTab(AUDIO_SECTIONS[next].id); document.getElementById(`audio-tab-${AUDIO_SECTIONS[next].id}`)?.focus(); }
        }}
        onClick={() => selectTab(s.id)}><WorkspaceIcon name={s.icon} size={16} /><span>{s.name}</span></button>)}
    </nav><div className="as-content" id="audio-section-panel" role="tabpanel" aria-labelledby={`audio-tab-${tab}`}>{tab === 'music' ? <MusicStudio onEdit={id=>{setSourceJob(id);selectTab('editor');}} /> : tab === 'editor' ? <AudioEditor sourceJob={sourceJob} onOpened={()=>setSourceJob(null)}/> : tab === 'radio' ? <MusicTab /> : <VoiceStudio />}</div>
  </div>;
}
