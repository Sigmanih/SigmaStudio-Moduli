import { useState } from 'react';
import '../../../../styles/03-modules/editor-jobs.css';

export default function PublicationResult({ publication, projectId, jobId }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  if (!publication?.publication_ready) return null;
  const show = async () => {
    try {
      const query = jobId ? `job_id=${encodeURIComponent(jobId)}` : `id=${encodeURIComponent(projectId)}`;
      const response = await fetch(`/api/creative/editor/publication/preview?${query}`);
      const value = await response.json();
      if (!response.ok || !value.success) throw new Error(value.error || 'Anteprima non disponibile');
      setPreview(value); setError('');
    } catch (exc) { setError(exc.message); }
  };
  return <div className="cs-ed-publication">
    <strong>Pacchetto YouTube · materiali generati</strong>
    <input className="cs-inline-input" aria-label="Cartella del pacchetto YouTube" readOnly
      value={publication.package_dir} onFocus={event => event.target.select()} />
    <button className="cs-tool-btn" onClick={show}>Anteprima e verifiche del pacchetto</button>
    {error && <p className="cs-prod-error" role="status">{error}</p>}
    {preview && <>
      <img className="cs-ed-publication-thumbnail" src={preview.thumbnail} alt={`Miniatura di ${preview.identity.title}`} />
      {preview.intro && <details><summary>Fotogramma dell’intro verificata</summary>
        <img className="cs-ed-publication-thumbnail" src={preview.intro} alt={`Intro di ${preview.identity.title} ${preview.identity.year}`} />
      </details>}
      <span>Durata master esportato: {Math.floor(preview.validation.duration / 3600)}:{String(Math.floor(preview.validation.duration / 60) % 60).padStart(2, '0')}:{(preview.validation.duration % 60).toFixed(3).padStart(6, '0')}. Audio separati verificati sulla stessa durata.</span>
      <span>{preview.identity.title} {preview.identity.year} · Controlli tecnici superati. Rivedi intro, testi e resa audiovisiva prima della pubblicazione.</span>
    </>}
  </div>;
}
