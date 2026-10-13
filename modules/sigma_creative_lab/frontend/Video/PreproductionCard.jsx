import React from 'react';
import { BookOpen, MapPin, Package, Plus, Trash2, Wand2, Loader2 } from 'lucide-react';

/*
 * Pre-produzione: la storia sviluppata dall'agente, i luoghi e gli oggetti descritti per filo
 * e per segno. Si rilegge e si corregge qui, prima di scrivere le inquadrature: le descrizioni
 * entrano in ogni immagine e in ogni clip, cosi' il vaso resta lo stesso vaso in tutto il film.
 * Si puo' scrivere in qualsiasi lingua: al salvataggio le descrizioni passano in inglese per i modelli.
 */

// L'ossatura della storia: se una voce e' vuota o debole, la storia lo e'.
const ARC = [
  ['want', 'Cosa vuole il protagonista'], ['obstacle', "L'ostacolo"], ['failed_attempt', 'Il tentativo che fallisce'],
  ['turning_point', 'La svolta'], ['resolution', 'Come si risolve'],
];
const EMPTY_SCENE ={ title: '', location: '', time: '', mood: '', summary: '', seconds: 20 };

export default function PreproductionCard({ pre, characters = [], disabled, planning, planningText, canDevelop, dirty, onChange, onDevelop }) {
  const scenes = pre?.scenes || [];
  const locations = pre?.locations || [];
  const props = pre?.props || [];
  const set = (patch) => onChange({ ...(pre || {}), ...patch });
  const setItem = (key, list, i, patch) => set({ [key]: list.map((x, k) => (k === i ? { ...x, ...patch } : x)) });
  const dropItem = (key, list, i) => set({ [key]: list.filter((_, k) => k !== i) });
  const total = scenes.reduce((a, s) => a + Number(s.seconds || 0), 0);

  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><BookOpen size={18} /> Storia, luoghi e oggetti</h3>
      <p className="cs-hint">
        Prima di generare, l'agente sviluppa il soggetto in una storia completa e descrive ogni luogo e ogni oggetto.
        Rileggi e correggi: puoi scrivere in italiano o in inglese, le descrizioni arrivano ai modelli in inglese.
      </p>
      <button className="cs-tool-btn" disabled={disabled || planning || dirty || !canDevelop}
              title={dirty ? 'Salva prima le modifiche' : ''}
              onClick={() => {
                if (scenes.length && !window.confirm('La storia nuova sostituisce quella attuale. Continuare?')) return;
                onDevelop();
              }}>
        {planning ? <Loader2 size={15} className="cs-spin-icon" /> : <Wand2 size={15} />}
        {planning ? planningText : scenes.length ? 'Risviluppa la storia' : 'Sviluppa storia, luoghi e oggetti'}
      </button>

      {scenes.length > 0 && (
        <>
          <div className="cs-pre-head">
            <label>Titolo
              <input className="cs-inline-input" value={pre.title || ''} disabled={disabled}
                     onChange={e => set({ title: e.target.value })} />
            </label>
            <label>La storia in una frase
              <textarea className="cs-textarea" rows={2} value={pre.logline || ''} disabled={disabled}
                        onChange={e => set({ logline: e.target.value })} />
            </label>
            <label>Messaggio
              <input className="cs-inline-input" value={pre.message || ''} disabled={disabled}
                     onChange={e => set({ message: e.target.value })} />
            </label>
            {ARC.map(([key, label]) => (
              <label key={key}>{label}
                <input className="cs-inline-input" value={pre.arc?.[key] || ''} disabled={disabled}
                       onChange={e => set({ arc: { ...(pre.arc || {}), [key]: e.target.value } })} />
              </label>
            ))}
          </div>

          <h4 className="cs-pre-sub">Scene ({scenes.length} · {Math.round(total)} s)</h4>
          {scenes.map((s, i) => (
            <div key={i} className="cs-pre-item">
              <div className="cs-pre-row">
                <span className="cs-prod-shot-n">{i + 1}</span>
                <input className="cs-inline-input" value={s.title} disabled={disabled} placeholder="Titolo"
                       onChange={e => setItem('scenes', scenes, i, { title: e.target.value })} />
                <select className="cs-select" value={s.location || ''} disabled={disabled} title="Luogo"
                        onChange={e => setItem('scenes', scenes, i, { location: e.target.value })}>
                  <option value="">luogo?</option>
                  {locations.map(l => <option key={l.name} value={l.name}>{l.name}</option>)}
                </select>
                <input type="number" className="cs-prod-dur" min="3" step="1" value={s.seconds} disabled={disabled}
                       title="Secondi" onChange={e => setItem('scenes', scenes, i, { seconds: Number(e.target.value) })} />
                <button className="cs-ed-mini" disabled={disabled} title="Elimina la scena"
                        onClick={() => dropItem('scenes', scenes, i)}><Trash2 size={11} /></button>
              </div>
              <div className="cs-pre-row">
                <input className="cs-inline-input" value={s.time || ''} disabled={disabled} placeholder="Momento e luce"
                       onChange={e => setItem('scenes', scenes, i, { time: e.target.value })} />
                <input className="cs-inline-input" value={s.mood || ''} disabled={disabled} placeholder="Emozione"
                       onChange={e => setItem('scenes', scenes, i, { mood: e.target.value })} />
              </div>
              <textarea className="cs-textarea" rows={3} value={s.summary} disabled={disabled}
                        placeholder="Cosa succede, chi vuole cosa, gesti, espressioni, battute"
                        onChange={e => setItem('scenes', scenes, i, { summary: e.target.value })} />
              {(s.lines || []).map((ln, k) => (
                <div key={k} className="cs-pre-row" title="Battuta della scena: finisce nell'inquadratura giusta, con la voce del personaggio">
                  <select className="cs-select" value={ln.character} disabled={disabled}
                          onChange={e => setItem('scenes', scenes, i, { lines: s.lines.map((x, j) => (j === k ? { ...x, character: e.target.value } : x)) })}>
                    {characters.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                  <input className="cs-inline-input" value={ln.line} disabled={disabled}
                         onChange={e => setItem('scenes', scenes, i, { lines: s.lines.map((x, j) => (j === k ? { ...x, line: e.target.value } : x)) })} />
                  <button className="cs-ed-mini" disabled={disabled} title="Togli la battuta"
                          onClick={() => setItem('scenes', scenes, i, { lines: s.lines.filter((_, j) => j !== k) })}><Trash2 size={11} /></button>
                </div>
              ))}
              {characters.length > 0 && (
                <button className="cs-ed-mini" disabled={disabled}
                        onClick={() => setItem('scenes', scenes, i, { lines: [...(s.lines || []), { character: characters[0].name, line: '' }] })}>
                  <Plus size={11} /> Battuta
                </button>
              )}
            </div>
          ))}
          <button className="cs-ed-mini" disabled={disabled} onClick={() => set({ scenes: [...scenes, { ...EMPTY_SCENE }] })}>
            <Plus size={11} /> Scena
          </button>

          <h4 className="cs-pre-sub"><MapPin size={14} /> Luoghi</h4>
          {locations.map((l, i) => (
            <div key={i} className="cs-pre-item">
              <div className="cs-pre-row">
                <input className="cs-inline-input" value={l.name} disabled={disabled} placeholder="Nome del luogo"
                       onChange={e => {
                         // Il nome e' anche il legame con le scene: si rinomina dappertutto.
                         const old = l.name;
                         set({
                           locations: locations.map((x, k) => (k === i ? { ...x, name: e.target.value } : x)),
                           scenes: scenes.map(sc => (sc.location === old ? { ...sc, location: e.target.value } : sc)),
                         });
                       }} />
                <button className="cs-ed-mini" disabled={disabled} title="Elimina il luogo"
                        onClick={() => dropItem('locations', locations, i)}><Trash2 size={11} /></button>
              </div>
              <textarea className={`cs-textarea ${l.description ? '' : 'cs-pre-missing'}`} rows={3} value={l.description}
                        disabled={disabled} placeholder="Com'e' fatto: pianta, materiali, colori, da dove viene la luce, un dettaglio riconoscibile"
                        onChange={e => setItem('locations', locations, i, { description: e.target.value })} />
            </div>
          ))}
          <button className="cs-ed-mini" disabled={disabled}
                  onClick={() => set({ locations: [...locations, { name: '', description: '' }] })}>
            <Plus size={11} /> Luogo
          </button>

          <h4 className="cs-pre-sub"><Package size={14} /> Oggetti</h4>
          {props.map((p, i) => (
            <div key={i} className="cs-pre-item">
              <div className="cs-pre-row">
                <input className="cs-inline-input" value={p.name} disabled={disabled} placeholder="Nome (come nelle inquadrature)"
                       onChange={e => setItem('props', props, i, { name: e.target.value })} />
                <button className="cs-ed-mini" disabled={disabled} title="Elimina l'oggetto"
                        onClick={() => dropItem('props', props, i)}><Trash2 size={11} /></button>
              </div>
              <textarea className="cs-textarea" rows={2} value={p.description} disabled={disabled}
                        placeholder="Forma, grandezza, materiale, colore, e cosa NON ha (es. un vaso tondo senza becco)"
                        onChange={e => setItem('props', props, i, { description: e.target.value })} />
              <input className="cs-inline-input cs-prod-wide" value={p.states || ''} disabled={disabled}
                     placeholder="Come cambia nella storia (es. solo terra → germoglio → piantina)"
                     onChange={e => setItem('props', props, i, { states: e.target.value })} />
            </div>
          ))}
          <button className="cs-ed-mini" disabled={disabled}
                  onClick={() => set({ props: [...props, { name: '', description: '', states: '' }] })}>
            <Plus size={11} /> Oggetto
          </button>
        </>
      )}
    </div>
  );
}
