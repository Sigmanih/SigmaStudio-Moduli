import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Sparkles, Upload, Trash2, Play, Loader2, Check, Library } from 'lucide-react';

/*
 * Le mie voci: create da una descrizione, clonate da un campione o prese fra le
 * predefinite. La stessa voce serve alla chat (motore "Le mie voci") e ai
 * personaggi dei video in Video Studio.
 */

async function call(path, body) {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const MODES = [
  { id: 'design', label: 'Da descrizione' },
  { id: 'clone', label: 'Da un campione' },
  { id: 'preset', label: 'Predefinita' },
];

export default function VoiceLibrary({ onUse, activeVoice }) {
  const [voices, setVoices] = useState([]);
  const [engines, setEngines] = useState({});
  const [mode, setMode] = useState('design');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [preset, setPreset] = useState('if_sara');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [testText, setTestText] = useState('Ciao! Questa e\' la mia voce, la sentirai nei video e in chat.');
  const audio = useRef(null);

  const load = useCallback(async () => {
    try {
      const d = await call('/api/voices/library');
      setVoices(d.voices || []);
      setEngines(d.engines || {});
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    setError(''); setBusy('create');
    try {
      const body = { name: name || 'Nuova voce', mode };
      if (mode === 'design') body.description = description;
      if (mode === 'preset') body.preset = preset;
      if (mode === 'clone') {
        body.filename = file.name;
        body.data = await new Promise((ok, ko) => {
          const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = ko; r.readAsDataURL(file);
        });
      }
      await call('/api/voices/library/create', body);
      setName(''); setDescription(''); setFile(null);
      await load();
    } catch (e) { setError(e.message); }
    setBusy('');
  };

  const test = async (v) => {
    setError(''); setBusy(v.id);
    try {
      const d = await call('/api/voices/library/speak', { id: v.id, text: testText });
      if (audio.current) { audio.current.src = `data:audio/wav;base64,${d.audio}`; audio.current.play(); }
    } catch (e) { setError(e.message); }
    setBusy('');
  };

  const remove = async (v) => {
    if (!window.confirm(`Eliminare la voce "${v.name}"?`)) return;
    await call('/api/voices/library/update', { id: v.id, delete: true }).catch(e => setError(e.message));
    load();
  };

  const canCreate = mode === 'design' ? description.trim() && engines.design
    : mode === 'clone' ? file && engines.clone : engines.preset;

  return (
    <div className="vs-card vs-library">
      <h3><Library size={16} /> Le mie voci</h3>
      <p className="vs-hint">Usale in chat (motore "Le mie voci") e per i personaggi dei video. Un campione clonato deve essere la tua voce o di chi ti ha dato il permesso.</p>
      {engines.reason && <p className="vs-error">{engines.reason}</p>}

      <div className="vs-lib-modes">
        {MODES.map(m => (
          <button key={m.id} className={`vs-chip ${mode === m.id ? 'on' : ''}`} onClick={() => setMode(m.id)}>{m.label}</button>
        ))}
      </div>
      <div className="vs-lib-form">
        <input placeholder="Nome della voce" value={name} onChange={e => setName(e.target.value)} />
        {mode === 'design' && (
          <textarea rows={2} value={description} onChange={e => setDescription(e.target.value)}
                    placeholder="Descrivila in inglese: eta', timbro, ritmo, carattere. Es. 'calm Italian male narrator in his sixties, deep warm voice, slow pace'" />
        )}
        {mode === 'clone' && (
          <label className="vs-file">
            <Upload size={14} /> {file ? file.name : 'Scegli 5-15 secondi di parlato pulito (WAV, MP3, M4A)'}
            <input type="file" accept="audio/*" hidden onChange={e => setFile(e.target.files?.[0] || null)} />
          </label>
        )}
        {mode === 'preset' && (
          <select value={preset} onChange={e => setPreset(e.target.value)}>
            <option value="if_sara">Sara (donna)</option>
            <option value="im_nicola">Nicola (uomo)</option>
          </select>
        )}
        <button className="vs-primary" disabled={!canCreate || !!busy} onClick={create}>
          {busy === 'create' ? <Loader2 size={14} className="vs-spin" /> : <Sparkles size={14} />}
          {busy === 'create' ? 'Creo la voce… (fino a un minuto)' : 'Crea voce'}
        </button>
      </div>

      <input className="vs-test" value={testText} onChange={e => setTestText(e.target.value)} title="Frase di prova" />
      <ul className="vs-lib-list">
        {voices.map(v => (
          <li key={v.id} className={activeVoice === v.id ? 'active' : ''}>
            <div>
              <strong>{v.name}</strong>
              <span>{{ design: 'da descrizione', clone: 'clonata', preset: 'predefinita' }[v.kind] || v.kind}
                {v.description ? ` · ${v.description}` : ''}</span>
            </div>
            <audio src={v.sample_url} controls preload="none" />
            <button title="Prova con la frase sopra" disabled={!!busy} onClick={() => test(v)}>
              {busy === v.id ? <Loader2 size={14} className="vs-spin" /> : <Play size={14} />}
            </button>
            <button title="Usala come voce della chat" onClick={() => onUse(v)}><Check size={14} /></button>
            <button title="Elimina" onClick={() => remove(v)}><Trash2 size={14} /></button>
          </li>
        ))}
        {!voices.length && <li className="vs-empty">Nessuna voce ancora: creane una qui sopra.</li>}
      </ul>
      <audio ref={audio} hidden />
      {error && <p className="vs-error">{error}</p>}
    </div>
  );
}
