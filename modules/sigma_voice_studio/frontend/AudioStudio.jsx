import { useCallback, useEffect, useState } from 'react';
import { Music, Mic, Download, RefreshCw, X, RotateCcw } from 'lucide-react';
import TabHeader from '../../components/common/TabHeader';
import VoiceStudio from './VoiceStudio';
import '../../styles/03-modules/audio-studio.css';

async function api(path, body) {
  const response = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok || value.success === false) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

function MusicStudio() {
  const [engine, setEngine] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [genre, setGenre] = useState('lofi_study');
  const [duration, setDuration] = useState(120);
  const [prompt, setPrompt] = useState('');
  const [seed, setSeed] = useState('');
  const [bpm, setBpm] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
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
      {completed.map(job => <article key={job.id} className="as-track"><strong>{job.result.title}</strong>
        <span>{job.result.duration / 60} minuti · {job.result.recipe.bpm} BPM · seed {job.result.recipe.seed}</span>
        <audio controls preload="metadata" src={job.result.mp3_url} aria-label={`Ascolta ${job.result.title}`} />
        <div className="as-form-row"><a href={job.result.wav_url} download><Download size={14} /> WAV</a>
          <a href={job.result.mp3_url} download><Download size={14} /> MP3</a></div>
      </article>)}
    </section>
  </div>;
}

export default function AudioStudio() {
  const [tab, setTab] = useState('music');
  return <div className="as-studio"><TabHeader icon={Music} title="AudioStudio" highlight="MUSICA & VOCI"
    description="Componi basi musicali e crea le voci dei tuoi progetti" />
    <nav className="as-tabs" aria-label="Aree di AudioStudio">
      <button aria-pressed={tab === 'music'} onClick={() => setTab('music')}><Music size={16} /> Musica</button>
      <button aria-pressed={tab === 'voice'} onClick={() => setTab('voice')}><Mic size={16} /> Voci e narrazione</button>
    </nav><div className="as-content">{tab === 'music' ? <MusicStudio /> : <VoiceStudio />}</div>
  </div>;
}
