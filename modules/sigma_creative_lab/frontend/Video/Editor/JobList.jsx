import { AlertTriangle, CheckCircle2, Loader2, RotateCcw, X } from 'lucide-react';
import PublicationResult from './PublicationResult';
import '../../../../styles/03-modules/editor-jobs.css';

const LABELS = {
  regen_range: 'Rigenera tratto', redo: 'Rifai elemento', recolor: 'Ricolora', upscale: 'Ingrandisci',
  restore_clean: 'Pulisci pellicola', remaster: 'Restauro completo', restore_read: 'Leggi i testi',
  restore_narrate: 'Narrazione', restore_score: 'Colonna sonora', restore_pipeline: 'Pipeline di restauro',
  restore_translate: 'Traduzione',
  restore_fetch: 'Scarica film', extend: 'Estendi', insert: 'Inserisci', dialogue: 'Dialogo',
  voice_line: 'Battuta', music_range: 'Musica', export: 'Export', subtitles: 'Sottotitoli',
  import: 'Importa', title: 'Titolo', scene: 'Scena didattica', lesson: 'Lezione animata', scene_redo: 'Rifai scena',
  manga_read: 'Leggi fumetto', manga_direct: 'Regia del fumetto', manga_speakers: 'Voci del fumetto',
};

export default function JobList({ jobs, error, pending, onAction }) {
  const active = jobs.filter(job => ['queued', 'running'].includes(job.status));
  const recent = jobs.filter(job => ['done', 'error', 'cancelled', 'interrupted'].includes(job.status)).slice(0, 4);
  if (!active.length && !recent.length && !error) return null;
  return <section className="cs-ed-jobs" data-agent-component="EditorJobs" aria-label="Lavori dell’editor">
    {error && <p className="cs-prod-error" role="status">Impossibile aggiornare i lavori: {error}</p>}
    {[...active, ...recent].map(job => <div key={job.id} className={`cs-ed-job ${job.status}`}>
      {['queued', 'running'].includes(job.status) ? <Loader2 size={12} className="cs-spin-icon" aria-hidden="true" />
        : job.status === 'done' ? <CheckCircle2 size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
      <span>{LABELS[job.kind] || 'Operazione'}</span>
      <span className="cs-prod-status" title={job.error || job.message}>{job.status === 'error' ? job.error : job.message}</span>
      {job.status === 'done' && <PublicationResult publication={job.result} jobId={job.id} />}
      {['queued', 'running'].includes(job.status) && <button className="cs-ed-mini" disabled={pending}
        aria-label="Annulla lavoro" data-agent-action="cancel-job" onClick={() => onAction(job.id, 'cancel')}>
        <X size={11} aria-hidden="true" />
      </button>}
      {job.can_resume && <button className="cs-ed-mini" disabled={pending} data-agent-action="resume-job"
        onClick={() => onAction(job.id, 'resume')}><RotateCcw size={11} aria-hidden="true" /> Riprendi dai checkpoint</button>}
      {job.status === 'running' && <progress className="cs-ed-job-progress" max={1}
        value={Math.max(0, Math.min(1, job.progress || 0))} aria-label="Avanzamento del lavoro" />}
    </div>)}
  </section>;
}
