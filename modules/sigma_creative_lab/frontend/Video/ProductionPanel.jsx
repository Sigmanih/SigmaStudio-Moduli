import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Clapperboard, Plus, Play, Square, Scissors, Trash2, Wand2, Save, RefreshCw, Cpu, AlertTriangle, CheckCircle2, Loader2, Link2, Users, Film, Eye,
  Sparkles, Image as ImageIcon, BookmarkPlus, Library, Palette, ListPlus, RotateCw, PenLine,
} from 'lucide-react';
import { SettingsCard, LoraCard, SoundtrackCard, RefImageInput } from './ProductionSettings';
import CharacterVoice from './CharacterVoice';
import PreproductionCard from './PreproductionCard';

/*
 * Produzioni video lunghe: soggetto → storyboard → render su piu' GPU → montaggio.
 * Il render dura ore e gira sul server: qui si legge lo stato dal manifest
 * (polling) e l'avanzamento per step dagli eventi.
 */

const API = '/api/creative/productions';

async function call(path, body) {
  const res = await fetch(`${API}${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* risposta non JSON */ }
  if (!res.ok || data.success === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const STATUS_LABEL = {
  draft: 'Bozza', rendering: 'In render', partial: 'Parziale', rendered: 'Clip pronti',
  assembling: 'Montaggio', done: 'Completata', failed: 'Errore', cancelled: 'Fermata',
};

/** Percorso di un file sotto data/ o works/ → URL servito dal backend (stessa regola di paths.public_url). */
function toUrl(path) {
  if (!path) return '';
  const norm = String(path).replace(/\\/g, '/');
  for (const root of ['/works/', '/data/']) {
    const parts = norm.split(root);
    if (parts.length > 1) return `${root}${parts[parts.length - 1]}`;
  }
  return '';
}

const RESOLUTIONS = [
  { id: '864x480', label: '864×480 (veloce)' },
  { id: '1024x576', label: '1024×576' },
  { id: '1280x704', label: '1280×704 (lento)' },
];

function fmtTime(s) {
  if (s == null) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${Math.round(s % 60)}s`;
}

function NewProductionForm({ native, onCreated }) {
  const [title, setTitle] = useState('');
  const [treatment, setTreatment] = useState('');
  const [style, setStyle] = useState('');
  const [genres, setGenres] = useState([]);
  const [genre, setGenre] = useState('realistic');
  useEffect(() => {
    fetch('/api/creative/genres').then(r => r.json()).then(d => setGenres(d.genres || [])).catch(() => setGenres([]));
  }, []);
  const chosen = genres.find(g => g.id === genre);
  const [backend, setBackend] = useState('comfyui');
  const [resolution, setResolution] = useState('864x480');
  const [error, setError] = useState('');

  const create = async () => {
    setError('');
    const [width, height] = resolution.split('x').map(Number);
    try {
      const { production } = await call('/create', {
        title, treatment, genre, bible: { style }, settings: { backend, width, height },
      });
      onCreated(production.id, chosen);
    } catch (e) { setError(e.message); }
  };

  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><Plus size={18} /> Nuova produzione</h3>
      <div className="cs-genre-grid">
        {genres.map(g => (
          <button key={g.id} className={`cs-genre ${genre === g.id ? 'on' : ''}`} onClick={() => setGenre(g.id)}
                  aria-label={`${g.label}: ${g.hint}`} aria-pressed={genre === g.id}>
            <strong>{g.label}</strong>
            <span>{g.hint}</span>
            {!g.image_model_ready && <em>modello d'immagine da installare in Motori</em>}
          </button>
        ))}
      </div>
      <input className="cs-inline-input cs-prod-wide" placeholder="Titolo" value={title}
             onChange={e => setTitle(e.target.value)} />
      <textarea className="cs-textarea" rows={5} value={treatment} onChange={e => setTreatment(e.target.value)}
                placeholder="Soggetto: cosa racconta il video, personaggi, ambienti, tono. L'LLM lo scompone in scene e inquadrature." />
      <input className="cs-inline-input cs-prod-wide" value={style} onChange={e => setStyle(e.target.value)}
             placeholder={chosen ? `Stile del genere: ${chosen.style}` : 'Stile visivo comune'} />
      {chosen?.keyframes && (
        <p className="cs-hint"><ImageIcon size={13} /> Ogni inquadratura parte da un fotogramma disegnato nello stile scelto:
          prima del render vedrai lo storyboard illustrato e potrai rifare le immagini che non ti convincono.</p>
      )}
      {chosen?.editor_first && (
        <p className="cs-hint">Dopo la creazione si apre l'editor: trascina i tuoi video e le schermate, aggiungi titoli e voce narrante.</p>
      )}
      <div className="cs-inline-params">
        <label>Motore
          <select className="cs-select" value={backend} onChange={e => setBackend(e.target.value)}>
            <option value="comfyui">ComfyUI su tutte le GPU (piu' veloce)</option>
            <option value="hybrid">Ibrido: ComfyUI sulla principale, nativo sulle altre</option>
            <option value="sigma_native">Nativo (sd.cpp) su tutte le GPU</option>
          </select>
        </label>
        <label>Risoluzione
          <select className="cs-select" value={resolution} onChange={e => setResolution(e.target.value)}>
            {RESOLUTIONS.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </label>
      </div>
      {native && (
        <p className="cs-hint"><Cpu size={13} />
          {native.installed
            ? `${(native.lanes || []).length} corsie: ${(native.lanes || []).map(l => `${l.label} (${l.vram_gb} GB)`).join(' + ')}`
            : `Worker nativo non pronto: ${native.detail}`}
        </p>
      )}
      {error && <p className="cs-prod-error">{error}</p>}
      <button className="cs-tool-btn" disabled={!title.trim()} onClick={create}><Plus size={15} /> Crea</button>
    </div>
  );
}

function PortraitPicker({ productionId, character, disabled, onPick }) {
  const [busy, setBusy] = useState(false);
  const [options, setOptions] = useState([]);
  const [error, setError] = useState('');
  const create = async (seed) => {
    setBusy(true); setError('');
    try {
      const d = await call('/portraits', { id: productionId, name: character.name, description: character.description, count: 4, seed });
      setOptions(d.portraits);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };
  return (
    <div className="cs-portraits">
      {character.ref_image && <img className="cs-portrait current" src={toUrl(character.ref_image)} alt={character.name} />}
      <button className="cs-tool-btn" disabled={disabled || busy || !character.description?.trim()}
              title="Quattro ritratti nello stile del genere: scegli quello giusto"
              onClick={() => create(options.length ? options[0].seed + 1 : undefined)}>
        {busy ? <Loader2 size={13} className="cs-spin-icon" /> : <Sparkles size={13} />}
        {busy ? 'Disegno…' : options.length ? 'Altri ritratti' : 'Crea ritratti'}
      </button>
      {options.map(o => (
        <img key={o.path} className={`cs-portrait ${character.ref_image === o.path ? 'on' : ''}`} src={o.url} alt=""
             title="Usa questo ritratto come riferimento" onClick={() => onPick(o.path)} />
      ))}
      {error && <span className="cs-prod-error">{error}</span>}
    </div>
  );
}

function CharactersEditor({ productionId, characters, onChange, disabled }) {
  const update = (i, patch) => onChange(characters.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  const [library, setLibrary] = useState([]);
  const [note, setNote] = useState('');

  useEffect(() => {
    // La libreria e' accessoria: se non risponde l'editor dei personaggi resta com'era.
    fetch('/api/creative/characters').then(r => r.json())
      .then(d => d.success && setLibrary(d.characters.filter(c => c.front_url))).catch(() => {});
  }, []);

  const libraryPost = async (path, body) => {
    const res = await fetch(`/api/creative/characters/${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const d = await res.json();
    if (!d.success) throw new Error(d.error || `HTTP ${res.status}`);
    return d;
  };
  const fromLibrary = async (id) => {
    if (!id) return;
    try {
      const { character } = await libraryPost('to_production', { id, production: productionId });
      onChange([...characters.filter(c => c.name !== character.name), character]);
      setNote(`${character.name} aggiunto dalla libreria, con riferimento${character.voice_sample ? ' e voce' : ''}.`);
    } catch (e) { setNote(e.message); }
  };
  const toLibrary = async (c) => {
    try {
      await libraryPost('from_production', { production: productionId, name: c.name, character: c });
      setNote(`${c.name} salvato nella libreria: lo trovi in Video Studio → Personaggi.`);
    } catch (e) { setNote(e.message); }
  };

  return (
    <div className="cs-prod-chars">
      {characters.map((c, i) => (
        <div key={i} className="cs-prod-char-block">
        <div className="cs-prod-char">
          <input className="cs-inline-input" placeholder="Nome" value={c.name || ''} disabled={disabled}
                 onChange={e => update(i, { name: e.target.value })} />
          <input className="cs-inline-input" placeholder="Aspetto (in inglese)" value={c.description || ''}
                 disabled={disabled} onChange={e => update(i, { description: e.target.value })} />
          <input className="cs-inline-input" placeholder="Chiamato anche (es. lo shogun, il difensore)"
                 title="Ruoli con cui il soggetto chiama questo personaggio: nello storyboard diventano il suo nome, cosi' non nasce un secondo personaggio uguale"
                 value={(c.aliases || []).join(', ')} disabled={disabled}
                 onChange={e => update(i, { aliases: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })} />
          <RefImageInput productionId={productionId} value={c.ref_image || ''} disabled={disabled}
                         onChange={path => update(i, { ref_image: path })} />
          <button className="cs-icon-btn" disabled={disabled || !c.name?.trim()} title="Salva nella libreria dei personaggi"
                  onClick={() => toLibrary(c)}><BookmarkPlus size={13} /></button>
          <button className="cs-icon-btn" disabled={disabled} title="Rimuovi"
                  onClick={() => onChange(characters.filter((_, k) => k !== i))}><Trash2 size={13} /></button>
        </div>
        <CharacterVoice name={c.name} voiceId={c.voice_id || ''} disabled={disabled}
                        onAssign={id => update(i, { voice_id: id })} />
        <PortraitPicker productionId={productionId} character={c} disabled={disabled}
                        onPick={path => update(i, { ref_image: path })} />
        </div>
      ))}
      <button className="cs-tool-btn" disabled={disabled}
              onClick={() => onChange([...characters, { name: '', description: '', ref_image: '' }])}>
        <Users size={14} /> Aggiungi personaggio
      </button>
      {library.length > 0 && (
        <label className="cs-prod-lib">
          <Library size={14} />
          <select className="cs-select" value="" disabled={disabled} onChange={e => fromLibrary(e.target.value)}>
            <option value="">Dalla libreria…</option>
            {library.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      )}
      {note && <p className="cs-hint">{note}</p>}
    </div>
  );
}

/** Correzioni dell'utente: cosa non va, detto a parole; diventa un vincolo per immagine e clip. */
function ShotFixes({ shot, disabled, dirty, onFix, onRemove }) {
  const [problem, setProblem] = useState('');
  const verdict = shot.judge;
  const send = (redo, text) => { onFix(text ?? problem, redo); setProblem(''); };
  return (
    <div className="cs-shot-fixes">
      {verdict && verdict.ok === false && (
        <div className="cs-shot-advice" title={verdict.seen || ''}>
          <Eye size={12} /> Il giudice consiglia: {(verdict.issues || []).slice(0, 2).join('; ') || verdict.seen}
          <button className="cs-ed-mini" disabled={disabled || dirty}
                  onClick={() => send('clip', (verdict.issues || []).join('; ') || verdict.seen)}>Applica e rifai</button>
        </div>
      )}
      {(shot.fixes || []).map((f, k) => (
        <span key={k} className="cs-prod-chip on" title={f.text}>
          {f.problem}
          <button className="cs-ed-mini" disabled={disabled} onClick={() => onRemove(k)} title="Togli questa correzione">×</button>
        </span>
      ))}
      <div className="cs-shot-fix-row">
        <input className="cs-inline-input" value={problem} disabled={disabled}
               placeholder="Cosa non va? es. il vaso ha un becco come l'annaffiatoio"
               onChange={e => setProblem(e.target.value)} />
        <button className="cs-ed-mini" disabled={disabled || dirty || !problem.trim()} onClick={() => send('keyframe')}
                title={dirty ? 'Salva prima le modifiche' : "Corregge e ridisegna l'immagine di partenza (poi rifai la clip)"}>Correggi immagine</button>
        <button className="cs-ed-mini" disabled={disabled || dirty || !problem.trim()} onClick={() => send('clip')}
                title={dirty ? 'Salva prima le modifiche' : 'Corregge e rifa la clip dalla stessa immagine'}>Correggi clip</button>
        <button className="cs-ed-mini" disabled={disabled || dirty || !problem.trim()} onClick={() => send('both')}
                title="Ridisegna l'immagine e rifa la clip">Entrambe</button>
      </div>
    </div>
  );
}

function ShotRow({ shot, index, live, disabled, onEdit, onKeyframe, characters = [], maxDur = 5.2, dirty,
                  isStyle, onStyle, onRender, onInsert, onDelete, onFix, onRemoveFix, locations = [] }) {
  const inShot = characters.filter(c => (shot.refs || []).includes(c.name));
  const refs = shot.refs || [];
  const toggleRef = (name) => onEdit({ refs: refs.includes(name) ? refs.filter(n => n !== name) : [...refs, name] });
  const progress = live && live.steps ? Math.round((100 * (live.step || 0)) / live.steps) : null;
  return (
    <div className={`cs-prod-shot status-${shot.status}`}>
      <div className="cs-prod-shot-head">
        <span className="cs-prod-shot-n">#{index + 1}</span>
        <span className="cs-prod-shot-scene">{typeof shot.scene === 'string' ? shot.scene : ''}</span>
        <select className="cs-select cs-shot-engine" value={shot.engine || ''} disabled={disabled}
                title="Motore di questa inquadratura (vuoto = quello delle impostazioni)"
                onChange={e => onEdit({ engine: e.target.value })}>
          <option value="">motore predefinito</option>
          <option value="ltx">LTX-2.5</option>
          <option value="wan_s2v">Wan S2V (battuta)</option>
          <option value="wan_i2v">Wan I2V (azione)</option>
        </select>
        <button className={`cs-prod-chip ${shot.transition === 'continue' ? 'on' : ''}`} disabled={disabled}
                title="Continua dall'ultimo fotogramma dell'inquadratura precedente"
                onClick={() => onEdit({ transition: shot.transition === 'continue' ? 'cut' : 'continue' })}>
          {shot.transition === 'continue' ? <Link2 size={12} /> : <Scissors size={12} />}
          {shot.transition === 'continue' ? 'continua' : 'taglio'}
        </button>
        <input type="number" className="cs-prod-dur" min="1" max={maxDur} step="0.5" value={shot.duration_s}
               title={`Secondi (massimo ${maxDur} con questo motore)`}
               disabled={disabled} onChange={e => onEdit({ duration_s: Math.min(maxDur, Number(e.target.value)) })} />
        <span className="cs-prod-status">
          {shot.status === 'done' && <CheckCircle2 size={13} />}
          {shot.status === 'rendering' && <Loader2 size={13} className="cs-spin-icon" />}
          {shot.status === 'reviewing' && <Eye size={13} className="cs-pulse" />}
          {shot.status === 'failed' && <AlertTriangle size={13} />}
          {shot.status === 'rendering' && progress != null ? `${progress}%` : (SHOT_STATUS[shot.status] || shot.status)}
          {shot.judge?.score != null && (
            <span title={[shot.judge.seen, ...(shot.judge.issues || [])].filter(Boolean).join('\n')}>
              {` · giudice ${Math.round(shot.judge.score * 100)}%`}
            </span>
          )}
          {shot.lane ? ` · ${shot.lane}` : ''}
          {shot.timings?.total_s ? ` · ${fmtTime(shot.timings.total_s)}` : ''}
        </span>
      </div>
      <div className="cs-prod-shot-body">
        {shot.keyframe_url && (
          <div className="cs-keyframe">
            <img src={shot.keyframe_url} alt={`Fotogramma ${index + 1}`} />
            <button className="cs-ed-mini" disabled={disabled} title="Rifai questo fotogramma" onClick={onKeyframe}><RefreshCw size={11} /></button>
            <button className={`cs-ed-mini cs-style-pick ${isStyle ? 'on' : ''}`} disabled={disabled || dirty}
                    title={isStyle ? 'Questo fotogramma fissa lo stile di tutti gli altri (clic per toglierlo)' : "Usa come riferimento di stile per tutti i fotogrammi. Attenzione: klein ne copia anche il contenuto (oggetti, ambiente), sceglilo senza personaggi in pose particolari"}
                    onClick={onStyle}><Palette size={11} /></button>
          </div>
        )}
        <textarea className="cs-textarea" rows={2} value={shot.prompt} disabled={disabled}
                  onChange={e => onEdit({ prompt: e.target.value })} />
      </div>
      {shot.keyframe_check && shot.keyframe_check.ok === false && (
        <div className="cs-shot-advice" title={shot.keyframe_check.seen || ''}>
          <Eye size={12} /> Fotogramma da controllare: {(shot.keyframe_check.issues || []).join('; ')}
          <button className="cs-ed-mini" disabled={disabled} onClick={onKeyframe}>Ridisegna</button>
        </div>
      )}
      <input className="cs-inline-input cs-prod-wide" placeholder="Audio" value={shot.audio || ''} disabled={disabled}
             onChange={e => onEdit({ audio: e.target.value })} />
      {(locations.length > 0 || inShot.length > 0) && (
        <div className="cs-shot-world" title="Luogo descritto nella pre-produzione ed espressione di ogni personaggio: entrano nell'immagine e nella clip">
          {locations.length > 0 && (
            <select className="cs-select" value={shot.location || ''} disabled={disabled}
                    onChange={e => onEdit({ location: e.target.value })}>
              <option value="">luogo della scena</option>
              {locations.map(l => <option key={l.name} value={l.name}>{l.name}</option>)}
            </select>
          )}
          {inShot.map(c => (
            <input key={c.name} className="cs-inline-input" value={(shot.expressions || {})[c.name] || ''} disabled={disabled}
                   placeholder={`Espressione di ${c.name}`}
                   onChange={e => onEdit({ expressions: { ...(shot.expressions || {}), [c.name]: e.target.value } })} />
          ))}
        </div>
      )}
      {characters.length > 0 && (
        <div className="cs-shot-dialogue" title="Battuta detta dal personaggio con la sua voce: il labiale segue l'audio">
          <select className="cs-select" value={shot.dialogue?.character || ''} disabled={disabled}
                  onChange={e => onEdit({ dialogue: e.target.value ? { character: e.target.value, text: shot.dialogue?.text || '' } : null })}>
            <option value="">nessuna battuta</option>
            {characters.map(c => <option key={c.name} value={c.name}>{c.name} dice:</option>)}
          </select>
          {shot.dialogue?.character && (
            <input className="cs-inline-input" value={shot.dialogue?.text || ''} disabled={disabled}
                   placeholder="Battuta in italiano, breve"
                   onChange={e => onEdit({ dialogue: { character: shot.dialogue.character, text: e.target.value } })} />
          )}
        </div>
      )}
      <ShotFixes shot={shot} disabled={disabled} dirty={dirty} onFix={onFix} onRemove={onRemoveFix} />
      <div className="cs-shot-tools">
        {characters.length > 0 && (
          <span className="cs-shot-chars" title="Personaggi visibili in questa inquadratura: il fotogramma chiave li ridisegna dalla loro immagine">
            <Users size={12} />
            {characters.map(c => (
              <button key={c.name} className={`cs-prod-chip ${refs.includes(c.name) ? 'on' : ''}`} disabled={disabled}
                      onClick={() => toggleRef(c.name)}>{c.name}</button>
            ))}
          </span>
        )}
        <span className="cs-shot-actions">
          <button className="cs-ed-mini" disabled={disabled || dirty} onClick={onRender}
                  title={dirty ? 'Salva prima le modifiche' : 'Rifai solo questa clip (con il prompt e i personaggi attuali)'}>
            <RotateCw size={11} /> Rifai clip
          </button>
          <button className="cs-ed-mini" disabled={disabled} onClick={onInsert} title="Nuova inquadratura subito dopo">
            <ListPlus size={11} />
          </button>
          <button className="cs-ed-mini" disabled={disabled} onClick={onDelete} title="Elimina questa inquadratura">
            <Trash2 size={11} />
          </button>
        </span>
      </div>
      {shot.error && <p className="cs-prod-error">{shot.error}</p>}
      {shot.clip_url && <video className="cs-prod-clip" src={shot.clip_url} controls preload="metadata" />}
    </div>
  );
}

/** Intestazione di scena: riscrive le inquadrature della scena seguendo le indicazioni dell'utente. */
function SceneHeader({ scene, count, disabled, dirty, onRewrite }) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState('');
  return (
    <div className="cs-scene-head">
      <strong>{scene || 'Scena'}</strong>
      <span className="cs-prod-status">{count} inquadrature</span>
      <button className="cs-ed-mini" disabled={disabled} onClick={() => setOpen(o => !o)}
              title="Riscrivi questa scena con le tue indicazioni">
        <PenLine size={11} /> Riscrivi scena
      </button>
      {open && (
        <div className="cs-scene-rewrite">
          <textarea className="cs-textarea" rows={2} value={notes} placeholder="Cosa cambiare: es. Mimoki combatte da solo contro tre samurai, inquadrature piu' lunghe, finale al tramonto"
                    onChange={e => setNotes(e.target.value)} />
          <button className="cs-tool-btn" disabled={disabled || dirty || !notes.trim()}
                  title={dirty ? 'Salva prima le modifiche' : ''}
                  onClick={() => { onRewrite(notes); setOpen(false); setNotes(''); }}>
            <Wand2 size={13} /> Riscrivi
          </button>
        </div>
      )}
    </div>
  );
}

// Lo stato "reviewing" e' il giudice visivo al lavoro: la corsia intanto rende altro.
const SHOT_STATUS = {
  pending: 'in coda', rendering: 'in render', reviewing: 'controllo del movimento', done: 'pronta',
  failed: 'fallita', skipped: 'saltata',
};

export default function ProductionPanel({ aceInstalled = false, onOpenEditor }) {
  const [list, setList] = useState([]);
  const [native, setNative] = useState(null);
  const [active, setActive] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [prod, setProd] = useState(null);
  const [draft, setDraft] = useState(null);       // copia modificabile finche' non si salva
  const [minutes, setMinutes] = useState(10);
  const [shotRange, setShotRange] = useState(null);   // [min, max] secondi per inquadratura; null = dal motore
  const [live, setLive] = useState({});           // id inquadratura -> {step, steps}
  const [error, setError] = useState('');
  const sinceRef = useRef(0);

  const refreshList = useCallback(async () => {
    try {
      const data = await call('');
      setList(data.productions);
      setNative(data.native);
      setActive(data.active);
    } catch (e) { setError(e.message); }
  }, []);

  const refreshProd = useCallback(async (id) => {
    if (!id) return;
    try {
      const data = await call(`/get?id=${encodeURIComponent(id)}`);
      setProd(data.production);
      setActive(data.active);
      setDraft(d => (d && d.id === id && d.dirty ? d : { ...data.production, dirty: false }));
    } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => { refreshList(); }, [refreshList]);
  useEffect(() => { setDraft(null); refreshProd(selectedId); }, [selectedId, refreshProd]);

  const running = !!(active && prod && active.production === prod.id);
  const planning = !!prod?.planning;

  // Polling solo mentre c'e' qualcosa che cambia lato server.
  useEffect(() => {
    if (!running && !planning) return undefined;
    const t = setInterval(async () => {
      refreshProd(selectedId);
      try {
        const { events } = await call(`/events?since=${sinceRef.current}`);
        if (events.length) {
          sinceRef.current = events[events.length - 1].t;
          setLive(prev => {
            const next = { ...prev };
            events.filter(ev => ev.type === 'shot_progress').forEach(ev => { next[ev.shot] = ev; });
            return next;
          });
        }
      } catch { /* il prossimo giro riprova */ }
    }, 3000);
    return () => clearInterval(t);
  }, [running, planning, selectedId, refreshProd]);

  const editDraft = (patch) => setDraft(d => ({ ...d, ...patch, dirty: true }));
  const editShot = (i, patch) => setDraft(d => ({
    ...d, dirty: true, shots: d.shots.map((s, k) => (k === i ? { ...s, ...patch } : s)),
  }));

  const act = async (fn) => {
    setError('');
    try { await fn(); } catch (e) { setError(e.message); }
    refreshProd(selectedId);
    refreshList();
  };

  const save = () => act(async () => {
    const { production } = await call('/update', {
      id: draft.id, title: draft.title, treatment: draft.treatment, bible: draft.bible,
      settings: draft.settings, shots: draft.shots, soundtrack: draft.soundtrack,
    });
    setDraft({ ...production, dirty: false });
  });

  const isLtx = draft?.settings?.video_model === 'ltx25';
  const maxDur = isLtx ? Math.min(10, draft?.settings?.max_clip_seconds || 10) : 5.2;
  const range = shotRange || (isLtx ? [4, Math.min(8, maxDur)] : [3, 5]);
  const chars = draft?.bible?.characters || [];
  const styleImage = prod?.bible?.style_image || '';

  const stopPlanning = () => act(() => call('/planning/cancel', { id: draft.id }));
  const insertAfter = (i) => setDraft(d => {
    const base = d.shots[i];
    const shot = { id: Math.random().toString(16).slice(2, 10), scene: base.scene, prompt: '', audio: '',
                   duration_s: range[0], transition: 'cut', refs: [], status: 'pending' };
    return { ...d, dirty: true, shots: [...d.shots.slice(0, i + 1), shot, ...d.shots.slice(i + 1)] };
  });
  const deleteShot = (i) => {
    if (!window.confirm(`Eliminare l'inquadratura #${i + 1}?`)) return;
    setDraft(d => ({ ...d, dirty: true, shots: d.shots.filter((_, k) => k !== i) }));
  };

  const done = prod?.summary?.shots_done || 0;
  const total = prod?.summary?.shots || 0;

  return (
    <div className="cs-mesh-container cs-prod">
      <div className="cs-prod-side">
        <div className="cs-mesh-card">
          <h3 className="cs-mesh-title"><Clapperboard size={18} /> Produzioni
            <button className="cs-icon-btn cs-prod-push" onClick={refreshList} title="Aggiorna"><RefreshCw size={13} /></button>
          </h3>
          <button className={`cs-tool-btn ${selectedId === null ? 'active' : ''}`} onClick={() => setSelectedId(null)}>
            <Plus size={14} /> Nuova
          </button>
          <ul className="cs-prod-list">
            {list.map(p => (
              <li key={p.id} className={p.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(p.id)}>
                <strong>{p.title}</strong>
                <span>{STATUS_LABEL[p.status] || p.status} · {p.shots_done}/{p.shots} · {fmtTime(p.duration_s)}</span>
                {p.eta_s != null && p.status === 'rendering' && <span>fine stimata fra {fmtTime(p.eta_s)}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="cs-prod-main">
        {error && <div className="cs-banner warn"><AlertTriangle size={16} /><span>{error}</span></div>}
        {!selectedId && <NewProductionForm native={native} onCreated={(id, genre) => {
          refreshList(); setSelectedId(id);
          if (genre?.editor_first && onOpenEditor) onOpenEditor(id);
        }} />}

        {selectedId && draft && (
          <>
            <div className="cs-mesh-card">
              <h3 className="cs-mesh-title"><Film size={18} /> {draft.title}
                <span className="cs-prod-push cs-prod-status">{STATUS_LABEL[prod?.status] || prod?.status}</span>
              </h3>
              <div className="cs-prod-bar"><div style={{ width: `${total ? (100 * done) / total : 0}%` }} /></div>
              <p className="cs-hint">
                {done}/{total} inquadrature · {fmtTime(prod?.summary?.duration_s)} di video
                {prod?.summary?.eta_s != null && running ? ` · fine stimata fra ${fmtTime(prod.summary.eta_s)}` : ''}
                {prod?.lanes?.length ? ` · corsie: ${prod.lanes.join(', ')}` : ''}
              </p>
              {prod?.error && <p className="cs-prod-error">{prod.error}</p>}
              {planning && (
                <div className="cs-banner">
                  <Loader2 size={16} className="cs-spin-icon" /> <span>{prod.planning}</span>
                  <button className="cs-tool-btn active" onClick={stopPlanning}><Square size={13} /> Ferma</button>
                </div>
              )}
              <div className="cs-button-grid">
                {!running && (
                  <button className="cs-tool-btn" disabled={!total || planning || draft.dirty}
                          title={draft.dirty ? 'Salva prima le modifiche' : ''}
                          onClick={() => act(() => call('/render', { id: draft.id }))}>
                    <Play size={15} /> {done ? 'Riprendi render' : 'Avvia render'}
                  </button>
                )}
                {running && (
                  <button className="cs-tool-btn active" onClick={() => act(() => call('/cancel', { id: draft.id }))}>
                    <Square size={15} /> Ferma
                  </button>
                )}
                <button className="cs-tool-btn" disabled={!onOpenEditor} onClick={() => onOpenEditor(draft.id)}>
                  <Film size={15} /> Apri nell'editor
                </button>
                <button className="cs-tool-btn" disabled={running || !done}
                        onClick={() => act(() => call('/assemble', { id: draft.id }))}>
                  <Scissors size={15} /> Monta i clip pronti
                </button>
                <button className="cs-tool-btn" disabled={running || !draft.dirty} onClick={save}>
                  <Save size={15} /> Salva modifiche
                </button>
                <button className="cs-tool-btn" disabled={running}
                        onClick={() => {
                          if (!window.confirm(`Eliminare "${draft.title}" con clip, fotogrammi e file temporanei di ComfyUI?`)) return;
                          const exports = window.confirm('Eliminare anche i video esportati? (Annulla = li conservi)');
                          act(async () => { await call('/delete', { id: draft.id, exports }); setSelectedId(null); });
                        }}>
                  <Trash2 size={15} /> Elimina
                </button>
                <button className="cs-tool-btn" disabled={running}
                        title="Toglie i tentativi scartati e le versioni vecchie di clip, fotogrammi e battute che la produzione non usa piu'"
                        onClick={() => act(async () => {
                          const r = await call('/prune', { id: draft.id });
                          setError(r.removed ? `Liberati ${r.freed_mb} MB (${r.removed} file non piu' usati)` : 'Niente da liberare');
                        })}>
                  <Scissors size={15} /> Libera spazio
                </button>
              </div>
              {prod?.output_url && (
                <video className="cs-video-player" src={prod.output_url} controls>
                  {prod.subtitles_vtt_url && <track kind="subtitles" srcLang="it" label="Italiano" src={prod.subtitles_vtt_url} />}
                </video>
              )}
              {prod?.subtitles_url && <a className="cs-hint" href={prod.subtitles_url} download>Sottotitoli (.srt)</a>}
            </div>

            <div className="cs-mesh-card">
              <h3 className="cs-mesh-title"><Wand2 size={18} /> Soggetto e storyboard</h3>
              <textarea className="cs-textarea" rows={4} value={draft.treatment || ''} disabled={running}
                        onChange={e => editDraft({ treatment: e.target.value })} />
              <input className="cs-inline-input cs-prod-wide" value={draft.bible?.style || ''} disabled={running}
                     placeholder="Stile visivo" onChange={e => editDraft({ bible: { ...draft.bible, style: e.target.value } })} />
              <input className="cs-inline-input cs-prod-wide" value={draft.bible?.audio_style || ''} disabled={running}
                     placeholder="Stile audio comune (musica, ambiente)"
                     onChange={e => editDraft({ bible: { ...draft.bible, audio_style: e.target.value } })} />
              <CharactersEditor productionId={draft.id} characters={draft.bible?.characters || []} disabled={running}
                                onChange={chars => editDraft({ bible: { ...draft.bible, characters: chars } })} />
              <div className="cs-inline-params">
                <label>Durata (minuti)
                  <input type="number" min="0.2" max="60" step="0.5" value={minutes}
                         onChange={e => setMinutes(Number(e.target.value))} />
                </label>
                <label title="Durata di ogni inquadratura scelta dallo storyboard">Inquadrature da (s)
                  <input type="number" min="1" max={maxDur} step="0.5" value={range[0]}
                         onChange={e => setShotRange([Number(e.target.value), Math.max(Number(e.target.value), range[1])])} />
                </label>
                <label>a (s)
                  <input type="number" min="1" max={maxDur} step="0.5" value={range[1]}
                         onChange={e => setShotRange([Math.min(range[0], Number(e.target.value)), Number(e.target.value)])} />
                </label>
              </div>
              <button className="cs-tool-btn" disabled={running || planning || draft.dirty || !draft.treatment?.trim()}
                      title={draft.dirty ? 'Salva prima le modifiche' : ''}
                      onClick={() => {
                        if ((draft.shots || []).length && !window.confirm('Lo storyboard nuovo sostituisce le inquadrature attuali. Continuare?')) return;
                        act(() => call('/storyboard', { id: draft.id, minutes, shot_min: range[0], shot_max: range[1] }));
                      }}>
                {planning ? <Loader2 size={15} className="cs-spin-icon" /> : <Wand2 size={15} />}
                {planning ? prod.planning : draft.bible?.pre?.scenes?.length ? 'Scrivi le inquadrature dalla storia' : 'Scrivi storia e inquadrature con l\'LLM'}
              </button>
              {(draft.shots || []).length > 0 && (
                <button className="cs-tool-btn" disabled={running || planning || draft.dirty}
                        title={draft.dirty ? 'Salva prima le modifiche' : 'Un\'immagine per inquadratura, nello stile del genere: il render parte da qui'}
                        onClick={() => act(() => call('/keyframes', { id: draft.id }))}>
                  <ImageIcon size={15} /> {draft.shots.some(x => x.keyframe) ? 'Rifai tutti i fotogrammi chiave' : 'Storyboard illustrato (fotogrammi chiave)'}
                </button>
              )}
              {(draft.shots || []).some(x => x.keyframe) && (
                <button className="cs-tool-btn" disabled={running || planning || draft.dirty}
                        title="Fotogrammi chiave con le voci e i tempi del film: guardi la storia in un minuto, prima delle ore di render"
                        onClick={() => act(() => call('/animatic', { id: draft.id }))}>
                  <Play size={15} /> Anteprima animatica
                </button>
              )}
              {prod?.animatic_url && <video className="cs-video-player" src={prod.animatic_url} controls preload="metadata" />}
            </div>

            <PreproductionCard pre={draft.bible?.pre} characters={chars} disabled={running} planning={planning} planningText={prod?.planning}
                               dirty={draft.dirty} canDevelop={!!draft.treatment?.trim()}
                               onChange={pre => editDraft({ bible: { ...draft.bible, pre } })}
                               onDevelop={() => act(() => call('/preproduction', { id: draft.id, minutes }))} />

            <SettingsCard draft={draft} disabled={running} onSettings={settings => editDraft({ settings })} />
            <LoraCard draft={draft} disabled={running} onBible={bible => editDraft({ bible })} />
            <SoundtrackCard draft={draft} disabled={running} aceInstalled={aceInstalled}
                            onSoundtrack={soundtrack => editDraft({ soundtrack })} />

            {(draft.shots || []).length > 0 && (
              <div className="cs-mesh-card">
                <h3 className="cs-mesh-title"><Clapperboard size={18} /> Inquadrature ({draft.shots.length})</h3>
                <div className="cs-prod-shots">
                  {draft.shots.map((s, i) => {
                    const shown = running || !draft.dirty ? (prod.shots.find(x => x.id === s.id) || s) : s;
                    const newScene = i === 0 || draft.shots[i - 1].scene !== s.scene;
                    return (
                      <React.Fragment key={s.id}>
                        {newScene && (
                          <SceneHeader scene={s.scene} count={draft.shots.filter(x => x.scene === s.scene).length}
                                       disabled={running || planning} dirty={draft.dirty}
                                       onRewrite={notes => act(() => call('/scene', { id: draft.id, scene: s.scene, notes }))} />
                        )}
                        <ShotRow shot={shown} index={i} live={live[s.id]} characters={chars} maxDur={maxDur}
                                 dirty={draft.dirty} isStyle={!!shown.keyframe && shown.keyframe === styleImage}
                                 locations={draft.bible?.pre?.locations || []}
                                 disabled={running || planning} onEdit={patch => editShot(i, patch)}
                                 onKeyframe={() => act(() => call('/keyframes', { id: draft.id, shot_ids: [s.id] }))}
                                 onStyle={() => act(() => call('/style_image', { id: draft.id, shot_id: shown.keyframe === styleImage ? '' : s.id }))}
                                 onRender={() => act(() => call('/render', { id: draft.id, shot_ids: [s.id] }))}
                                 onInsert={() => insertAfter(i)} onDelete={() => deleteShot(i)}
                                 onFix={(problem, redo) => act(async () => {
                                   await call('/shot_fix', { id: draft.id, shot_id: s.id, problem, redo });
                                   // La correzione vale subito: immagine e/o clip si rifanno da sole.
                                   if (redo === 'keyframe' || redo === 'both') {
                                     await call('/keyframes', { id: draft.id, shot_ids: [s.id], render_after: redo === 'both' });
                                   }
                                   if (redo === 'clip') await call('/render', { id: draft.id, shot_ids: [s.id] });
                                 })}
                                 onRemoveFix={k => act(() => call('/shot_fix', { id: draft.id, shot_id: s.id, remove: k }))} />
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
