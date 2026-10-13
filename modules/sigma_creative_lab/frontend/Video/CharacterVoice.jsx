import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Play, Plus, Loader2, SlidersHorizontal } from 'lucide-react';

/*
 * Voce di un personaggio, scelta o creata li' dove si crea il personaggio.
 *
 * Il motore si sceglie per personaggio. Qwen3-TTS e VoxCPM2 creano la voce da una descrizione e la
 * ripetono clonando il campione: italiano nativo e voci da bambino vere (prova delle voci: l'utente ha
 * scelto Qwen3-TTS per Lia). Kokoro con tono resta per chi vuole regolarla a mano: alzare il tono di una
 * voce adulta la fa suonare finta, quindi non e' piu' la scelta di partenza.
 */

const TYPES = [
  ['bambina', 'Bambina'], ['bambino', 'Bambino'], ['donna', 'Donna'], ['uomo', 'Uomo'],
  ['nonna', 'Nonna'], ['nonno', 'Nonno'], ['animaletto', 'Animaletto buffo'], ['saggio', 'Vecchio saggio'],
  ['narratrice', 'Narratrice'], ['gigante', 'Gigante / orco'],
];
const ENGINES = [
  ['qwen', 'Qwen3-TTS (consigliato)'], ['voxcpm', 'VoxCPM2'], ['kokoro', 'Kokoro con tono regolabile'],
];
const ENGINE_LABEL = { qwen: 'Qwen3-TTS', voxcpm: 'VoxCPM2' };
// Tipi che esistono solo per Kokoro (tono molto basso) o solo per i motori da descrizione.
const KOKORO_ONLY = new Set(['gigante']);
const DESIGN_ONLY = new Set(['saggio', 'narratrice']);
const DEFAULTS = {
  bambina: [3.5, 1.05], bambino: [5, 1.05], donna: [0, 1], uomo: [0, 1], nonna: [-2, 0.92], nonno: [-2.5, 0.92],
  animaletto: [7, 1.1], gigante: [-5, 0.88], saggio: [-5, 0.86], narratrice: [0, 1],
};

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!data.success) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export default function CharacterVoice({ name, voiceId, onAssign, disabled }) {
  const [voices, setVoices] = useState([]);
  const [engines, setEngines] = useState({});
  const [engine, setEngine] = useState('qwen');
  const [description, setDescription] = useState('');
  const [open, setOpen] = useState(false);
  const [type, setType] = useState('bambina');
  const [tone, setTone] = useState(3.5);
  const [speed, setSpeed] = useState(1.05);
  const [line, setLine] = useState('Ciao! Che bella giornata, andiamo a giocare in giardino?');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const audioRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const d = await (await fetch('/api/voices/library')).json();
      if (d.success) { setVoices(d.voices || []); setEngines(d.engines || {}); }
    } catch { setVoices([]); }   // senza Voice Studio il personaggio resta senza voce
  }, []);
  useEffect(() => { load(); }, [load]);

  const current = voices.find(v => v.id === voiceId);
  useEffect(() => {
    // Una voce italiana gia' assegnata si ritocca dai suoi valori.
    if (current?.kind === 'preset') {
      if (current.semitones != null) setTone(Number(current.semitones));
      if (current.speed != null) setSpeed(Number(current.speed));
    }
  }, [current?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (label, fn) => {
    setBusy(label); setError('');
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(''); }
  };
  const play = (id) => run(`play:${id}`, async () => {
    const d = await post('/api/voices/library/speak', { id, text: line });
    if (audioRef.current) audioRef.current.pause();
    audioRef.current = new Audio(`data:audio/wav;base64,${d.audio}`);
    audioRef.current.play();
  });
  const create = () => run('create', async () => {
    const body = engine === 'kokoro'
      ? { name: name || 'Voce', mode: 'preset', preset: type, semitones: tone, speed }
      : { name: name || 'Voce', mode: 'type', type, engine, description: description.trim() };
    const d = await post('/api/voices/library/create', body);
    await load();
    onAssign(d.voice.id);
    setOpen(false);
  });
  const retune = () => run('tone', async () => {
    await post('/api/voices/library/update', { id: voiceId, semitones: tone, speed });
    await load();
    await play(voiceId);
  });
  const pickType = (t) => { setType(t); const [st, sp] = DEFAULTS[t]; setTone(st); setSpeed(sp); };

  return (
    <div className="cs-char-voice">
      <div className="cs-char-head">
        <Mic size={14} />
        <select className="cs-select" value={voiceId || ''} disabled={disabled} onChange={e => onAssign(e.target.value)}>
          <option value="">nessuna voce</option>
          {voices.map(v => (
            <option key={v.id} value={v.id}>
              {v.name}{v.kind === 'preset' ? ' · Kokoro' : v.kind === 'design' ? ` · ${ENGINE_LABEL[v.engine] || 'Qwen3-TTS'}` : ' · campione'}
            </option>
          ))}
        </select>
        {voiceId && (
          <button className="cs-icon-btn" title="Ascolta" disabled={!!busy} onClick={() => play(voiceId)}>
            {busy === `play:${voiceId}` ? <Loader2 size={13} className="cs-spin-icon" /> : <Play size={13} />}
          </button>
        )}
        <button className="cs-tool-btn" disabled={disabled} onClick={() => setOpen(o => !o)}>
          {current?.kind === 'preset' ? <SlidersHorizontal size={13} /> : <Plus size={13} />}
          {current?.kind === 'preset' ? ' Tono' : ' Crea voce'}
        </button>
      </div>
      {open && (
        <div className="cs-char-voice-editor">
          {current?.kind !== 'preset' && (
            <>
              <label>Motore
                <select className="cs-select" value={engine} onChange={e => {
                  const next = e.target.value;
                  setEngine(next);
                  if (next === 'kokoro' && DESIGN_ONLY.has(type)) pickType('nonno');
                  if (next !== 'kokoro' && KOKORO_ONLY.has(type)) pickType('saggio');
                }}>
                  {ENGINES.map(([id, label]) => (
                    <option key={id} value={id} disabled={id !== 'kokoro' && engines[id] === false}>
                      {label}{id !== 'kokoro' && engines[id] === false ? ' (da installare in Motori)' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <div className="cs-char-voice-types">
                {TYPES.filter(([id]) => (engine === 'kokoro' ? !DESIGN_ONLY.has(id) : !KOKORO_ONLY.has(id))).map(([id, label]) => (
                  <button key={id} className={`cs-prod-chip ${type === id ? 'on' : ''}`} onClick={() => pickType(id)}>{label}</button>
                ))}
              </div>
            </>
          )}
          {current?.kind !== 'preset' && engine !== 'kokoro' ? (
            <textarea className="cs-textarea" rows={2} value={description} onChange={e => setDescription(e.target.value)}
                      placeholder="Descrizione facoltativa, in italiano o inglese: età, timbro, carattere (es. una bambina di 6 anni, voce squillante e timida)" />
          ) : (
            <>
              <label>Tono {tone > 0 ? '+' : ''}{tone} semitoni
                <input type="range" min="-8" max="10" step="0.5" value={tone} onChange={e => setTone(Number(e.target.value))} />
              </label>
              <label>Velocità {speed.toFixed(2)}×
                <input type="range" min="0.8" max="1.3" step="0.01" value={speed} onChange={e => setSpeed(Number(e.target.value))} />
              </label>
            </>
          )}
          <input className="cs-inline-input" value={line} onChange={e => setLine(e.target.value)} placeholder="Frase di prova" />
          {current?.kind === 'preset'
            ? <button className="cs-tool-btn" disabled={!!busy} onClick={retune}>
                {busy === 'tone' ? <Loader2 size={13} className="cs-spin-icon" /> : <Play size={13} />} Applica e ascolta
              </button>
            : <button className="cs-tool-btn" disabled={!!busy} onClick={create}>
                {busy === 'create' ? <Loader2 size={13} className="cs-spin-icon" /> : <Plus size={13} />}
                {busy === 'create' && engine !== 'kokoro' ? ' Creo la voce (circa un minuto)…' : ' Crea la voce e assegnala'}
              </button>}
          <p className="cs-hint">
            {engine === 'kokoro' || current?.kind === 'preset'
              ? `Ascolta e ritocca il tono finché è quella giusta per ${name || 'il personaggio'}.`
              : "La voce nasce dalla descrizione e resta la stessa in ogni battuta. Non ti convince? Creane un'altra: ogni tentativo è diverso."}
          </p>
        </div>
      )}
      {error && <p className="cs-prod-error">{error}</p>}
    </div>
  );
}
