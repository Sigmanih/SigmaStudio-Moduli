import React, { useState } from 'react';
import { Wand2, Image as ImageIcon, Smartphone, Monitor, SlidersHorizontal, RefreshCw, Cpu, Dices } from 'lucide-react';
import ModelPicker from '../shared/ModelPicker';
import CreativeEngineButton from '../shared/CreativeEngineButton';
import { imageRequest, selectImageModel, selectionIssue } from './imageCreation';

const FORMATS = [
  ['Quadrato', 1024, 1024, ImageIcon], ['Orizzontale', 1280, 720, Monitor], ['Verticale', 720, 1280, Smartphone],
];
const STYLES = [['Fotografico', 'photorealistic'], ['Cinema', 'cinematic lighting'], ['Illustrazione', 'digital illustration'], ['Anime', 'anime style']];

export default function CreationForm({ draft, onChange, onGenerate, busy, models, inventory, loading, error, onRefresh, onManageModels, backends }) {
  const [advanced, setAdvanced] = useState(false);
  const [validation, setValidation] = useState('');
  const change = patch => { onChange(previous => ({ ...previous, ...patch })); setValidation(''); };
  const issue = loading ? '' : selectionIssue(draft, models, inventory);
  const submit = event => {
    event.preventDefault();
    if (busy || loading || issue || error) return;
    try {
      const request = imageRequest(draft);
      setValidation('');
      onGenerate(request.params, request.backend);
    } catch (e) { setValidation(e.message); }
  };
  return (
    <form className="cs-creation-form" onSubmit={submit} data-agent-component="CreationForm" data-agent-id="image-creation-form">
      <div className="cs-creation-scroll">
      <header><span className="cs-eyebrow">IL TUO PROSSIMO PROGETTO</span><h2>Crea un’immagine</h2><p>Parti da un’idea. Scegli come darle forma.</p></header>
      <label className="cs-field" htmlFor="cs-image-prompt"><span>Che cosa vuoi creare?</span>
        <textarea id="cs-image-prompt" value={draft.prompt} rows={5} maxLength={8000} disabled={busy}
          placeholder="Una piccola libreria sul mare, luce del tramonto, acquerello dai colori caldi…"
          onChange={e => change({ prompt: e.target.value })}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e); }} />
      </label>
      <div className="cs-style-choices" aria-label="Aggiungi uno stile">
        {STYLES.map(([label, value]) => <button key={value} type="button" className="cs-choice" disabled={busy}
          onClick={() => { if (!draft.prompt.toLowerCase().includes(value)) change({ prompt: [draft.prompt.trim(), value].filter(Boolean).join(', ') }); }}>{label}</button>)}
      </div>
      <section className="cs-model-section" aria-label="Scelta del modello" data-agent-part="image-model-selection">
        <div className="cs-section-heading"><h3><Cpu size={15} /> Modello</h3><button type="button" className="cs-icon-button" onClick={onRefresh} disabled={loading || busy} aria-label="Aggiorna i modelli"><RefreshCw size={15} /></button></div>
        <ModelPicker task="text_to_image" models={models} inventory={inventory} value={draft.model}
          onChange={value => onChange(previous => value.model_id !== previous.model.model_id ? selectImageModel(previous, value, models.find(m => m.id === value.model_id)) : { ...previous, model: value })}
          disabled={busy || loading} showCheckpoint={advanced} />
        {!inventory?.enabled && <CreativeEngineButton onReady={onRefresh} />}
        {(loading || error || issue) && <p className="cs-form-notice" role={error ? 'alert' : 'status'}>{loading ? 'Cerco i modelli disponibili…' : error || issue}</p>}
        <button type="button" className="cs-text-button" onClick={onManageModels}>Modelli e motori <span aria-hidden="true">→</span></button>
      </section>
      <fieldset className="cs-format-field"><legend>Formato</legend><div className="cs-format-choices">
        {FORMATS.map(([label, w, h, Icon]) => <button key={label} type="button" className="cs-choice" aria-pressed={Number(draft.width) === w && Number(draft.height) === h}
          disabled={busy} onClick={() => change({ width: w, height: h })}><Icon size={17} /><span>{label}</span><small>{w} × {h}</small></button>)}
      </div></fieldset>
      <label className="cs-field" htmlFor="cs-image-priority"><span>Che cosa conta di più?</span>
        <select id="cs-image-priority" value={draft.priority} disabled={busy} onChange={e => change({ priority: e.target.value })}>
          <option value="balanced">Un buon equilibrio</option><option value="quality">La qualità del risultato</option><option value="speed">Creare più velocemente</option>
        </select>
      </label>
      <button type="button" className="cs-advanced-toggle" aria-expanded={advanced} aria-controls="cs-image-advanced" onClick={() => setAdvanced(v => !v)}>
        <SlidersHorizontal size={15} /> Impostazioni avanzate <span>{advanced ? '−' : '+'}</span>
      </button>
      {advanced && <div id="cs-image-advanced" className="cs-advanced-fields">
        <label className="cs-field"><span>Elementi da evitare</span><textarea rows={2} value={draft.negative_prompt} disabled={busy} onChange={e => change({ negative_prompt: e.target.value })} placeholder="Per esempio: scritte, sfocatura, sfondo affollato" /></label>
        <div className="cs-field-pair">
          {[['width', 'Larghezza', 64, 4096, 8], ['height', 'Altezza', 64, 4096, 8], ['steps', 'Passaggi', 1, 150, 1], ['cfg_scale', 'Aderenza al testo', 0, 30, 0.5]].map(([key, label, min, max, step]) =>
            <label key={key} className="cs-field"><span>{label}</span><input type="number" value={draft[key]} min={min} max={max} step={step} disabled={busy} onChange={e => change({ [key]: e.target.value })} /></label>)}
        </div>
        <label className="cs-field"><span>Seed · −1 per un risultato nuovo</span><div className="cs-seed-field"><input type="number" min={-1} step={1} value={draft.seed} disabled={busy} onChange={e => change({ seed: e.target.value })} /><button type="button" className="cs-icon-button" disabled={busy} onClick={() => change({ seed: -1 })} aria-label="Usa un seed casuale"><Dices size={16} /></button></div></label>
        <label className="cs-field"><span>Motore di esecuzione</span><select value={draft.backend} disabled={busy} onChange={e => change({ backend: e.target.value })}><option value="">Automatico</option>{backends.filter(b => b.available && b.capabilities?.includes('text_to_image')).map(b => <option key={b.name} value={b.name}>{b.name}</option>)}</select></label>
        {[['sampler', 'Campionatore', inventory?.samplers], ['scheduler', 'Scheduler', inventory?.schedulers]].map(([key, label, options]) => options?.length > 0 && <label className="cs-field" key={key}><span>{label}</span><select value={draft[key]} disabled={busy} onChange={e => change({ [key]: e.target.value })}><option value="">Predefinito del modello</option>{options.map(name => <option key={name}>{name}</option>)}</select></label>)}
      </div>}
      {validation && <p className="cs-form-notice" role="alert">{validation}</p>}
      </div>
      <footer className="cs-creation-submit">
      <button className="cs-create-button" type="submit" disabled={busy || loading || !!error || !!issue || !draft.prompt.trim()} data-agent-action="generate-image"><Wand2 size={19} />{busy ? 'Creazione in corso…' : 'Crea immagine'}</button>
      <p className="cs-shortcut">Puoi anche premere Ctrl / ⌘ + Invio.</p>
      </footer>
    </form>
  );
}
