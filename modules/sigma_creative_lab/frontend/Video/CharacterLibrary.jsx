import React, { useCallback, useEffect, useRef, useState } from 'react';
import CharacterVoice from './CharacterVoice';
import { UserRound, Plus, Sparkles, Upload, Trash2, Save, Clapperboard, RefreshCw, Check, Loader2 } from 'lucide-react';

/*
 * Libreria dei personaggi: schede riutilizzabili in tutte le storie.
 *
 * Flusso: nome e aspetto -> quattro proposte del riferimento (o una foto/disegno
 * caricato) -> model sheet con profilo, retro, primi piani ed espressioni, ogni vista
 * controllata dal giudice visivo -> voce dalla libreria di Voice Studio -> "aggiungi
 * a una produzione", che copia la scheda nella bibbia della storia.
 */

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!data.success) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function CharacterEditor({ char, genres, views, voices, productions, onSaved, onDeleted }) {
  const [draft, setDraft] = useState(char);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [target, setTarget] = useState('');
  const fileRef = useRef(null);

  useEffect(() => { setDraft(char); setError(''); setMessage(''); }, [char]);

  const dirty = ['name', 'description', 'genre', 'voice_id'].some(k => (draft[k] || '') !== (char[k] || ''));

  const run = async (label, fn) => {
    setBusy(label); setError(''); setMessage('');
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(''); }
  };

  const save = () => run('save', async () => {
    const d = await post('/api/creative/characters/update', {
      id: char.id, name: draft.name, description: draft.description, genre: draft.genre, voice_id: draft.voice_id || '',
    });
    onSaved(d.character);
  });

  // Prima di generare si salva: le immagini usano la descrizione e lo stile della scheda.
  const saveThen = async () => {
    if (!dirty) return;
    const d = await post('/api/creative/characters/update', {
      id: char.id, name: draft.name, description: draft.description, genre: draft.genre, voice_id: draft.voice_id || '',
    });
    onSaved(d.character);
  };

  const candidates = () => run('candidates', async () => {
    await saveThen();
    onSaved((await post('/api/creative/characters/candidates', { id: char.id, count: 4 })).character);
  });
  const pick = (file) => run('pick', async () => {
    onSaved((await post('/api/creative/characters/pick', { id: char.id, file })).character);
  });
  const sheet = (only) => run(only ? `view:${only}` : 'sheet', async () => {
    await saveThen();
    onSaved((await post('/api/creative/characters/sheet', { id: char.id, views: only ? [only] : null })).character);
  });
  const upload = (file) => run('upload', async () => {
    const res = await fetch(`/api/creative/characters/image?id=${encodeURIComponent(char.id)}&filename=${encodeURIComponent(file.name)}`,
      { method: 'POST', body: file });
    const d = await res.json();
    if (!d.success) throw new Error(d.error || `HTTP ${res.status}`);
    onSaved(d.character);
  });
  const toProduction = () => run('production', async () => {
    await saveThen();
    await post('/api/creative/characters/to_production', { id: char.id, production: target });
    const title = productions.find(p => p.id === target)?.title || target;
    setMessage(`${char.name} aggiunto a "${title}": lo trovi fra i personaggi della produzione.`);
  });
  const remove = () => {
    if (!window.confirm(`Eliminare ${char.name} dalla libreria? Le produzioni che lo usano non cambiano.`)) return;
    run('delete', async () => { await post('/api/creative/characters/delete', { id: char.id }); onDeleted(char.id); });
  };

  const spinner = (label) => (busy === label ? <Loader2 size={14} className="cs-spin" /> : null);

  return (
    <div className="cs-char-editor">
      <div className="cs-mesh-card">
        <div className="cs-char-head">
          <input className="cs-inline-input cs-char-name" value={draft.name || ''} placeholder="Nome"
                 onChange={e => setDraft({ ...draft, name: e.target.value })} />
          <select className="cs-select" value={draft.genre || 'realistic'} onChange={e => setDraft({ ...draft, genre: e.target.value })}>
            {genres.map(g => <option key={g.id} value={g.id}>{g.label}</option>)}
          </select>
          <button className="cs-tool-btn" disabled={!dirty || !!busy} onClick={save}>{spinner('save') || <Save size={14} />} Salva</button>
          <button className="cs-icon-btn" title="Elimina dalla libreria" disabled={!!busy} onClick={remove}><Trash2 size={14} /></button>
        </div>
        <label className="cs-ed-field">Aspetto (in inglese rende meglio)
          <textarea className="cs-textarea" rows={3} value={draft.description || ''}
                    placeholder="elderly Italian man, short white beard, round glasses, flat cap, brown wool cardigan"
                    onChange={e => setDraft({ ...draft, description: e.target.value })} />
        </label>
        <label className="cs-ed-field">Voce</label>
        <CharacterVoice name={draft.name} voiceId={draft.voice_id || ''} disabled={!!busy}
                        onAssign={id => run('voice', async () => {
                          // Assegnata subito: e' una scelta, non una bozza da ricordarsi di salvare.
                          setDraft(d => ({ ...d, voice_id: id }));
                          onSaved((await post('/api/creative/characters/update', { id: char.id, voice_id: id })).character);
                        })} />
      </div>

      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><UserRound size={18} /> Riferimento</h3>
        <div className="cs-char-row">
          <div className="cs-char-front">
            {char.front_url ? <img src={char.front_url} alt={char.name} /> : <span>Nessun riferimento</span>}
          </div>
          <div className="cs-char-actions">
            <button className="cs-tool-btn" disabled={!draft.description?.trim() || !!busy} onClick={candidates}>
              {spinner('candidates') || <Sparkles size={14} />} Genera 4 proposte
            </button>
            <button className="cs-tool-btn" disabled={!!busy} onClick={() => fileRef.current?.click()}>
              {spinner('upload') || <Upload size={14} />} Carica foto o disegno
            </button>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden
                   onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) upload(f); }} />
            <p className="cs-hint">Con una foto o un disegno, se l'aspetto e' vuoto lo descrive il giudice visivo.</p>
          </div>
        </div>
        {char.candidates?.length > 0 && (
          <div className="cs-char-grid">
            {char.candidates.map(c => (
              <button key={c.file} className="cs-char-thumb" disabled={!!busy} onClick={() => pick(c.file)}
                      title="Usa come riferimento">
                <img src={c.url} alt="" loading="lazy" />
                <span><Check size={12} /> Scegli</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><Sparkles size={18} /> Model sheet</h3>
        <button className="cs-tool-btn" disabled={!char.front_url || !draft.description?.trim() || !!busy} onClick={() => sheet(null)}>
          {spinner('sheet') || <Sparkles size={14} />} {Object.keys(char.sheet || {}).length ? 'Rigenera tutto' : 'Genera model sheet'}
        </button>
        <p className="cs-hint">
          Profilo, retro, primo piano ed espressioni, ognuna confrontata col riferimento e rifatta se cambia persona.
          Il retro a volte esce con la testa girata verso la camera: rigenera solo quella vista.
        </p>
        <div className="cs-char-grid">
          {views.map(v => {
            const e = char.sheet?.[v.id];
            return (
              <div key={v.id} className="cs-char-view">
                {e ? <img src={e.url} alt={v.label} loading="lazy" /> : <div className="cs-char-empty" />}
                <div className="cs-char-view-foot">
                  <span>{v.label}</span>
                  {e?.score != null && e.score < 1 && <span className="cs-char-warn" title={(e.differences || []).join('; ')}>!</span>}
                  <button className="cs-icon-btn" title="Rigenera questa vista" disabled={!char.front_url || !!busy}
                          onClick={() => sheet(v.id)}>
                    {busy === `view:${v.id}` ? <Loader2 size={12} className="cs-spin" /> : <RefreshCw size={12} />}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="cs-mesh-card">
        <h3 className="cs-mesh-title"><Clapperboard size={18} /> Usa in una storia</h3>
        <div className="cs-char-head">
          <select className="cs-select" value={target} onChange={e => setTarget(e.target.value)}>
            <option value="">scegli una produzione…</option>
            {productions.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
          <button className="cs-tool-btn" disabled={!target || !char.front_url || !!busy} onClick={toProduction}>
            {spinner('production') || <Plus size={14} />} Aggiungi alla produzione
          </button>
        </div>
        <p className="cs-hint">La scheda viene copiata: modificare il personaggio qui non cambia i video gia' fatti.</p>
      </div>
      {error && <p className="cs-prod-error">{error}</p>}
      {message && <p className="cs-hint">{message}</p>}
    </div>
  );
}

export default function CharacterLibrary() {
  const [data, setData] = useState({ characters: [], genres: [], views: [] });
  const [voices, setVoices] = useState([]);
  const [productions, setProductions] = useState([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [newName, setNewName] = useState('');

  const load = useCallback(async () => {
    try {
      const d = await (await fetch('/api/creative/characters')).json();
      if (!d.success) throw new Error(d.error);
      setData(d);
      setSelected(s => s || d.characters[0]?.id || '');
    } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => {
    load();
    // Voci e produzioni sono accessorie: senza Voice Studio la libreria funziona lo stesso.
    fetch('/api/voices/library').then(r => r.json()).then(d => d.success && setVoices(d.voices || [])).catch(() => {});
    fetch('/api/creative/productions').then(r => r.json()).then(d => d.success && setProductions(d.productions || [])).catch(() => {});
  }, [load]);

  const create = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const d = await post('/api/creative/characters/create', { name: newName.trim() });
      setData(prev => ({ ...prev, characters: [d.character, ...prev.characters] }));
      setSelected(d.character.id);
      setNewName('');
      setError('');
    } catch (err) { setError(err.message); }
  };

  const replace = (char) => setData(prev => ({ ...prev, characters: prev.characters.map(c => (c.id === char.id ? char : c)) }));
  const removed = (id) => {
    setData(prev => ({ ...prev, characters: prev.characters.filter(c => c.id !== id) }));
    setSelected('');
  };
  const current = data.characters.find(c => c.id === selected);

  return (
    <div className="cs-char-library">
      <aside className="cs-char-list">
        <form className="cs-char-new" onSubmit={create}>
          <input className="cs-inline-input" value={newName} placeholder="Nome del nuovo personaggio"
                 onChange={e => setNewName(e.target.value)} />
          <button className="cs-tool-btn" type="submit" disabled={!newName.trim()} title="Crea"><Plus size={14} /></button>
        </form>
        {data.characters.map(c => (
          <button key={c.id} className={`cs-char-item ${c.id === selected ? 'on' : ''}`} onClick={() => setSelected(c.id)}>
            {c.front_url ? <img src={c.front_url} alt="" /> : <UserRound size={28} />}
            <span>{c.name}</span>
          </button>
        ))}
        {data.characters.length === 0 && <p className="cs-hint">Nessun personaggio: creane uno e riusalo in tutte le storie.</p>}
        {error && <p className="cs-prod-error">{error}</p>}
      </aside>
      {current
        ? <CharacterEditor char={current} genres={data.genres} views={data.views} voices={voices}
                           productions={productions} onSaved={replace} onDeleted={removed} />
        : <div className="cs-char-editor"><p className="cs-hint">Seleziona o crea un personaggio.</p></div>}
    </div>
  );
}
