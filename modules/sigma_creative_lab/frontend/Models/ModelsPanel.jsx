import React, { useMemo, useState } from 'react';
import { Cpu, CheckCircle2, XCircle, AlertTriangle, HardDrive, Zap, Star, Copy } from 'lucide-react';
import ModelDownloads from './ModelDownloads';
import ModelBrowser from './ModelBrowser';
import ModelInventory from './ModelInventory';
import WorkflowPanel from './WorkflowPanel';
import ModelProfiles from './ModelProfiles';
import CreativeSkills from './CreativeSkills';
import CreativeEngineButton from '../shared/CreativeEngineButton';

const TASK_LABELS = {
  text_to_image: 'Text→Image', img_to_img: 'Image→Image', inpaint: 'Inpaint', outpaint: 'Outpaint',
  instruct_edit: 'Instruct Edit', upscale: 'Upscale', restore: 'Restauro',
  vision_describe: 'Vision', vision_qa: 'Vision QA', quality_score: 'Quality', ocr: 'OCR',
  segment: 'Segmentazione', remove_background: 'Scontorno',
  image_to_3d: 'Image→3D', multiview_to_3d: 'Multi-view→3D', texture_3d: 'Texture 3D',
  texture_pbr: 'PBR', text_to_video: 'Text→Video', image_to_video: 'Image→Video',
};

function Meter({ value, icon: Icon, title }) {
  return (
    <span className="cs-meter" title={`${title}: ${value}/5`}>
      <Icon size={11} />
      {[1, 2, 3, 4, 5].map(i => <i key={i} className={i <= value ? 'on' : ''} />)}
    </span>
  );
}

export default function ModelsPanel({ models = [], inventory = null, meta = null, loading = false, error = '', onRefresh, onUseModel, onOpenPipeline, onOpenSkill }) {
  const [showCatalog, setShowCatalog] = useState(false);
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('');
  const [enabling, setEnabling] = useState(false);
  const [section, setSection] = useState('catalog');
  const [actionError, setActionError] = useState('');

  const matches = item => (!tag || (item.tags || []).includes(tag)) &&
    [item.label, item.filename, ...(item.tags || [])].filter(Boolean).join(' ').toLowerCase().includes(query.toLowerCase());
  const grouped = useMemo(() => [{ id: 'models', label: showCatalog ? 'Catalogo modelli' : 'I tuoi modelli', models: models
    .filter(m => (showCatalog || m.installed || (m.available && m.available_via?.some(backend => backend !== 'comfyui'))) && (!tag || (m.tags || []).includes(tag)))
    .filter(m => [m.label, m.filename, ...(m.tags || [])].filter(Boolean).join(' ').toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => Number(Boolean(b.installed)) - Number(Boolean(a.installed)) || Number(b.available) - Number(a.available)),
  }].filter(g => g.models.length), [models, showCatalog, query, tag]);
  const components = (meta?.installed_files || []).filter(item => !item.workflow && matches(item));
  const availableTags = new Set([...models.filter(m => showCatalog || m.installed || m.available), ...(meta?.installed_files || [])].flatMap(m => m.tags || []));
  const tags = ['Immagini', 'Ritocco', 'Video', 'Musica', '3D', 'Materiali', 'Ingrandimento', 'Scontorno', 'Analisi', 'Testi', 'Componente'].filter(t => availableTags.has(t));

  /** ComfyUI è in esecuzione ma spento in config: un click lo collega. */
  const enableComfy = () => {
    setEnabling(true);
    fetch('/api/creative/backends/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backends: { comfyui: { enabled: true, url: inventory.url } } }),
    })
      .then(async r => { const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.error || 'Collegamento non riuscito'); return onRefresh?.(); })
      .catch(e => setActionError(e.message))
      .finally(() => setEnabling(false));
  };

  const data = meta || { models, available_backends: [], workflows: {} };

  return (
    <div className="cs-models-container" data-agent-component="ModelsPanel" data-agent-id="creative-models">
      <div className="cs-models-header">
        <div>
          <h2><Cpu size={20} /> Modelli e motori</h2>
          <p className="cs-hint">
            Scegli i modelli da usare, aggiungine altri o controlla i file locali.
            Per creare un’immagine puoi scegliere direttamente in 2D Generator.
          </p>
        </div>
        <div className="cs-models-stats">
          <span><HardDrive size={13} /> {data.vram_free_gb ? `${data.vram_free_gb} GB VRAM` : 'VRAM n/d'}</span>
          <span>{(data.available_backends || []).join(' · ') || 'nessun backend'}</span>
          <label className="cs-check">
            <input type="checkbox" checked={showCatalog} onChange={e => setShowCatalog(e.target.checked)} />
            Mostra anche modelli da installare
          </label>
          <button className="cs-copy-btn" onClick={() => onRefresh?.()}>Aggiorna</button>
        </div>
      </div>

      <nav className="cs-model-sections" aria-label="Gestione modelli">{[['catalog', 'Modelli disponibili'], ['install', 'Aggiungi modelli'], ['profiles', 'Profili e skill']].map(([id, label]) => <button type="button" key={id} className="cs-choice" aria-pressed={section === id} onClick={() => setSection(id)}>{label}</button>)}</nav>
      {section === 'profiles' && <><ModelProfiles inventory={inventory} onWorkflow={() => setSection('workflows')} onSaved={async profile => { await onRefresh?.(); if (profile.capability === 'text_to_image') onUseModel?.(profile); }} /><div className="cs-profile-actions"><button className="cs-secondary-button" onClick={onOpenPipeline}><Cpu size={15} /> Editor delle automazioni creative</button><button className="cs-secondary-button" onClick={() => setSection('inventory')}>Inventario dei file locali</button></div></>}
      {['inventory', 'workflows'].includes(section) && <button className="cs-text-button" onClick={() => setSection('profiles')}>← Torna ai profili</button>}
      {section === 'profiles' && <CreativeSkills onOpen={onOpenSkill} />}
      {(error || actionError) && <p className="cs-form-notice" role="alert">{error || actionError}</p>}
      {section === 'catalog' && loading && <p role="status">Aggiornamento dei modelli…</p>}
      {section === 'catalog' && <div className="cs-model-filters"><label className="cs-field"><span>Cerca tra modelli e componenti</span><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Nome, utilizzo o formato…" /></label><div className="cs-usage-filter" aria-label="Filtra per utilizzo"><button type="button" className="cs-choice" aria-pressed={!tag} onClick={() => setTag('')}>Tutti</button>{tags.map(t => <button type="button" className="cs-choice" aria-pressed={tag === t} key={t} onClick={() => setTag(t)}>{t}</button>)}</div></div>}
      {section === 'catalog' && !loading && !grouped.length && !components.length && <p className="cs-hint">Nessun modello corrisponde al filtro. Puoi aggiungerne uno da Hugging Face o Civitai.</p>}
      {section === 'install' && <><ModelDownloads onInstalled={onRefresh} /><ModelBrowser onInstalled={onRefresh} /></>}
      {!inventory?.enabled && <div className="cs-engine-notice"><p>Il motore locale è spento o non collegato. I modelli installati restano pronti sul disco.</p><CreativeEngineButton onReady={onRefresh} /></div>}

      {inventory?.reachable && !inventory.enabled && (
        <div className="cs-banner ok">
          <CheckCircle2 size={16} />
          <span>ComfyUI è in esecuzione su <code>{inventory.url}</code> ma non è collegato a Sigma.</span>
          <button className="cs-tool-btn" disabled={enabling} onClick={enableComfy}>
            {enabling ? 'Collegamento...' : 'Collega ComfyUI'}
          </button>
        </div>
      )}

      {section === 'inventory' && <div className="cs-mesh-card">
        <ModelInventory onRefresh={onRefresh} />
      </div>}

      {section === 'workflows' && <div className="cs-mesh-card">
        <WorkflowPanel onChanged={onRefresh} />
      </div>}

      {section === 'catalog' && grouped.map(group => (
        <section key={group.id} className="cs-model-group">
          <h3>{group.label}</h3>
          <div className="cs-model-grid">
            {group.models.map(m => (
              <article key={m.id} className={`cs-model-card ${m.available ? '' : 'off'}`}>
                <header>
                  <span className="cs-model-name">{m.label}</span>
                  {m.available
                    ? <CheckCircle2 size={14} className="ok" />
                    : <XCircle size={14} className="off" />}
                </header>

                <div className="cs-model-meters">
                  {!m.installed && <><Meter value={m.quality} icon={Star} title="Qualità" /><Meter value={m.speed} icon={Zap} title="Velocità" /></>}
                  {m.vram_gb > 0 && (
                    <span className={`cs-vram ${m.fits_vram ? '' : 'over'}`} title="VRAM consigliata">
                      <HardDrive size={11} /> {m.vram_gb} GB
                    </span>
                  )}
                </div>

                <div className="cs-model-tasks">
                  {(m.tags?.length ? m.tags : m.tasks.map(t => TASK_LABELS[t] || t)).map(t => <span key={t}>{t}</span>)}
                </div>
                {m.installed && <p className="cs-model-status">{m.available ? 'Pronto per creare' : m.setup_message || 'Controllo del motore necessario'}</p>}

                {m.strengths.length > 0 && (
                  <p className="cs-model-strengths">{m.strengths.map(s => s.replace(/_/g, ' ')).join(' · ')}</p>
                )}
                {m.notes && <p className="cs-model-notes">{m.notes}</p>}

                <footer>
                  {m.tasks.includes('text_to_image') && onUseModel && (m.installed || m.available ? <button className="cs-secondary-button" onClick={() => onUseModel(m)}>Usa in 2D Generator</button> : <button className="cs-secondary-button" onClick={() => setSection('install')}>Trova e installa</button>)}
                  <span>{m.available_via.length ? `via ${m.available_via.join(', ')}` : `richiede ${m.backends.join(' o ')}`}</span>
                  {m.workflow && !m.installed && m.family === 'custom' && (
                    <button
                      className="cs-copy-btn"
                      title="Copia il nome del file workflow da creare"
                      onClick={() => navigator.clipboard?.writeText(`${m.workflow}.json`)}
                    >
                      <Copy size={11} /> {m.workflow}
                    </button>
                  )}
                </footer>
              </article>
            ))}
          </div>
        </section>
      ))}
      {section === 'catalog' && components.length > 0 && <details className="cs-model-components" open={query || tag ? true : undefined}><summary>Componenti e modelli con workflow dedicato · {components.length}</summary><div className="cs-model-grid">{components.map(item => <article key={item.id} className="cs-model-card"><header><span className="cs-model-name">{item.label}</span><CheckCircle2 size={14} className="ok" /></header><div className="cs-usage-tags">{item.tags.map(t => <span key={t}>{t}</span>)}</div><p className="cs-model-notes">{item.issues?.join(' · ') || 'Installato. Viene utilizzato dai workflow che richiedono questo componente.'}</p>{item.issues?.length > 0 && <button className="cs-secondary-button" onClick={() => setSection('profiles')}>Associa workflow</button>}</article>)}</div></details>}
    </div>
  );
}
