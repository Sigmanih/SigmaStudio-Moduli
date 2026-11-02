import React, { useState } from 'react';
import { Power, LoaderCircle } from 'lucide-react';

export default function CreativeEngineButton({ onReady }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const start = async () => {
    setBusy(true); setError('');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch('/api/creative/engine/start', { method: 'POST', signal: controller.signal });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Avvio del motore non riuscito');
      await onReady?.();
    } catch (e) { setError(e.name === 'AbortError' ? 'Il motore sta ancora avviandosi. Aggiorna tra qualche secondo.' : e.message); }
    finally { clearTimeout(timer); setBusy(false); }
  };
  return <div className="cs-engine-start" data-agent-component="CreativeEngineButton" data-agent-id="creative-engine-start">
    <button type="button" className="cs-secondary-button" onClick={start} disabled={busy}>
      {busy ? <LoaderCircle size={15} className="cs-spin" /> : <Power size={15} />}
      {busy ? 'Avvio e collegamento…' : 'Avvia motore locale'}
    </button>
    {error && <p className="cs-form-notice" role="alert">{error}</p>}
  </div>;
}
