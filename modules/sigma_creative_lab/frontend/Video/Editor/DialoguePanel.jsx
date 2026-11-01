import React, { useEffect, useState } from 'react';
import { Mic, MessageSquare, Upload, Plus, Trash2, Play, Sparkles } from 'lucide-react';

/*
 * Voci e dialoghi.
 *
 * Ogni personaggio ha una voce: una voce Kokoro predefinita, una voce creata
 * da una descrizione (Qwen3-TTS VoiceDesign) oppure un campione caricato da
 * clonare. In tutti i casi ne esce un campione che vale per ogni battuta. Le righe del copione
 * diventano:
 *   - "in campo": con H3 il personaggio dice la battuta col labiale e la voce
 *     viene poi convertita nel timbro del personaggio; con LTX-2.5 la battuta si
 *     sintetizza prima con la voce del personaggio e LTX anima il labiale su di essa;
 *   - "fuori campo": battuta TTS sulla traccia voce o dialoghi, all'istante scelto.
 */

const EMOTIONS = ['', 'calm', 'determined', 'angry', 'sad', 'whispering', 'joyful', 'afraid'];
const EMOTION_IT = { '': 'neutra', calm: 'calma', determined: 'decisa', angry: 'arrabbiata', sad: 'triste',
  whispering: 'sussurrata', joyful: 'allegra', afraid: 'impaurita' };
const EXAGGERATION = { '': 0.5, calm: 0.3, determined: 0.7, angry: 0.9, sad: 0.4, whispering: 0.25, joyful: 0.75, afraid: 0.8 };

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!data.success) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function VoiceRow({ pid, ch, engines, library, onChanged, onError }) {
  const [busy, setBusy] = useState(false);
  const fromLibrary = async (voiceId) => {
    const v = library.find(x => x.id === voiceId);
    if (!v) return;
    setBusy(true);
    try { await post('/api/creative/editor/voice', { id: pid, character: ch.name, sample_path: v.sample_path }); onChanged(); }
    catch (e) { onError(e.message); }
    setBusy(false);
  };
  const [description, setDescription] = useState(ch.voice_description || '');
  const [seed, setSeed] = useState(ch.voice_seed || 7);
  const kokoro = engines.find(e => e.id === 'kokoro');
  const canDesign = engines.some(e => e.id === 'qwen_design');
  const design = async (nextSeed) => {
    setBusy(true);
    try {
      await post('/api/creative/editor/voice', { id: pid, character: ch.name, description, seed: nextSeed });
      setSeed(nextSeed);
      onChanged();
    } catch (e) { onError(e.message); }
    setBusy(false);
  };
  const setVoice = async (voice) => {
    setBusy(true);
    try { await post('/api/creative/editor/voice', { id: pid, character: ch.name, engine: 'kokoro', voice }); onChanged(); }
    catch (e) { onError(e.message); }
    setBusy(false);
  };
  const upload = (file) => {
    if (!file) return;
    setBusy(true);
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const up = await post('/api/creative/productions/upload', { id: pid, filename: file.name, data: reader.result });
        await post('/api/creative/editor/voice', { id: pid, character: ch.name, sample_path: up.path });
        onChanged();
      } catch (e) { onError(e.message); }
      setBusy(false);
    };
    reader.readAsDataURL(file);
  };
  return (
    <div className="cs-ed-voice">
      <strong>{ch.name}</strong>
      <select className="cs-select" disabled={busy} value={ch.voice_engine === 'kokoro' ? ch.voice || '' : ''}
              onChange={e => e.target.value && setVoice(e.target.value)}>
        <option value="">{ch.voice_url ? 'campione caricato' : 'scegli una voce…'}</option>
        {(kokoro?.voices || []).map(v => <option key={v.id} value={v.id}>{v.label}</option>)}
      </select>
      <label className="cs-icon-btn cs-prod-upload" title="Carica un campione di voce da clonare (5-15 s)">
        <Upload size={13} />{busy ? '…' : ''}
        <input type="file" accept="audio/*" hidden onChange={e => upload(e.target.files?.[0])} />
      </label>
      {ch.voice_url ? <audio src={ch.voice_url} controls className="cs-ed-audio" /> : <span className="cs-prod-status">nessun campione</span>}
      {!ch.has_image && <span className="cs-prod-status">senza immagine: niente labiale</span>}
      {library.length > 0 && (
        <select className="cs-select cs-ed-voice-lib" disabled={busy} value=""
                onChange={e => e.target.value && fromLibrary(e.target.value)}
                title="Le voci create in Voice Studio: le stesse che puo' usare la chat">
          <option value="">Usa una voce della libreria…</option>
          {library.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
      )}
      {canDesign && (
        <div className="cs-ed-voice-design">
          <input className="cs-inline-input" value={description} disabled={busy}
                 placeholder="Descrivi la voce, in inglese: es. old fisherman, deep hoarse voice, slow"
                 onChange={e => setDescription(e.target.value)} />
          <button className="cs-tool-btn" disabled={busy || !description.trim()} onClick={() => design(seed)}
                  title="Crea il campione di voce da questa descrizione">
            <Sparkles size={13} /> Crea voce
          </button>
          <button className="cs-tool-btn" disabled={busy || !description.trim()} onClick={() => design(seed + 1)}
                  title="Stessa descrizione, un'altra variante di timbro">
            Altra variante
          </button>
        </div>
      )}
    </div>
  );
}

export default function DialoguePanel({ pid, data, time, onJob, onReload }) {
  const [engines, setEngines] = useState([]);
  const [installed, setInstalled] = useState(true);
  const [lines, setLines] = useState([{ character: '', text: '', emotion: '', mode: 'in_campo' }]);
  const [error, setError] = useState('');
  const [library, setLibrary] = useState([]);
  useEffect(() => {
    // La libreria sta in Voice Studio: se il modulo non c'e' la scelta semplicemente non compare.
    fetch('/api/voices/library').then(r => r.json()).then(d => setLibrary(d.voices || [])).catch(() => setLibrary([]));
  }, []);

  useEffect(() => {
    fetch('/api/creative/editor/voices').then(r => r.json())
      .then(d => { setEngines(d.engines || []); setInstalled(d.installed !== false); }).catch(() => {});
  }, []);

  const characters = data.characters || [];
  const update = (i, patch) => setLines(ls => ls.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  const itemIndexAt = (t) => {
    const k = data.items.findIndex(it => t < it.end);
    return k < 0 ? data.items.length : k + (t > data.items[k].start + 0.05 ? 1 : 0);
  };

  const generate = (l) => {
    if (!l.text.trim()) return;
    if (l.mode === 'in_campo') {
      onJob('dialogue', { character: l.character, text: l.text, emotion: l.emotion, index: itemIndexAt(time) });
    } else {
      onJob('voice_line', {
        text: l.text, start: time, character: l.character || undefined, track: l.character ? 'dialogue' : 'voice',
        exaggeration: EXAGGERATION[l.emotion] ?? 0.5,
      });
    }
  };

  return (
    <div className="cs-ed-dialogue">
      {!installed && <div className="cs-banner warn"><Mic size={16} /><span>Motori voce non installati: Video Studio → Motori.</span></div>}
      <h4><Mic size={14} /> Voci dei personaggi</h4>
      {characters.length === 0 && <p className="cs-hint">Aggiungi i personaggi (con immagine) nella scheda Produzioni.</p>}
      {characters.map(ch => (
        <VoiceRow key={ch.name} pid={pid} ch={ch} engines={engines} library={library} onChanged={onReload} onError={setError} />
      ))}
      <h4><MessageSquare size={14} /> Copione <span className="cs-prod-status">le battute partono dal cursore ({time.toFixed(2)} s)</span></h4>
      {lines.map((l, i) => (
        <div key={i} className="cs-ed-line">
          <select className="cs-select" value={l.character} onChange={e => update(i, { character: e.target.value })}>
            <option value="">Narratore (fuori campo)</option>
            {characters.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <input className="cs-inline-input" value={l.text} placeholder="Battuta" onChange={e => update(i, { text: e.target.value })} />
          <select className="cs-select" value={l.emotion} onChange={e => update(i, { emotion: e.target.value })}>
            {EMOTIONS.map(em => <option key={em} value={em}>{EMOTION_IT[em]}</option>)}
          </select>
          <select className="cs-select" value={l.character ? l.mode : 'fuori_campo'} disabled={!l.character}
                  onChange={e => update(i, { mode: e.target.value })}>
            <option value="in_campo">in campo (labiale)</option>
            <option value="fuori_campo">solo voce</option>
          </select>
          <button className="cs-tool-btn" disabled={!l.text.trim()} onClick={() => generate({ ...l, mode: l.character ? l.mode : 'fuori_campo' })}>
            <Play size={13} /> Genera
          </button>
          <button className="cs-icon-btn" onClick={() => setLines(ls => ls.filter((_, k) => k !== i))}><Trash2 size={13} /></button>
        </div>
      ))}
      <button className="cs-tool-btn" onClick={() => setLines(ls => [...ls, { character: '', text: '', emotion: '', mode: 'in_campo' }])}>
        <Plus size={14} /> Riga
      </button>
      {error && <p className="cs-prod-error">{error}</p>}
      <p className="cs-hint">
        {data.video_model === 'ltx25'
          ? "In campo (LTX-2.5): la battuta viene detta con la voce del personaggio, poi LTX genera l'inquadratura con il labiale sincronizzato su quell'audio. Whisper verifica che la battuta sia quella del copione."
          : "In campo: H3 genera l'inquadratura con il personaggio che pronuncia la battuta (labiale sincronizzato), poi la voce viene portata al timbro del personaggio e Whisper verifica che la battuta sia quella del copione."}
      </p>
    </div>
  );
}
