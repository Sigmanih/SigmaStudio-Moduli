import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Workflow, Save, RefreshCw } from 'lucide-react';

const RUNTIME = new Set(['prompt', 'negative_prompt', 'input_image', 'mask_image', 'width', 'height', 'steps', 'cfg_scale', 'seed', 'sampler', 'scheduler', 'batch_size', 'strength', 'mask_blur']);

export default function ModelProfiles({ inventory, onSaved, onWorkflow }) {
  const [workflows, setWorkflows] = useState([]);
  const [workflowId, setWorkflowId] = useState('');
  const [label, setLabel] = useState('');
  const [parameters, setParameters] = useState({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [verified, setVerified] = useState(false);
  const [components, setComponents] = useState([]);
  const [componentsBusy, setComponentsBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/creative/workflows');
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Impossibile leggere i workflow');
      setWorkflows(data.workflows || []);
      setNotice('');
    } catch (e) { setNotice(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const workflow = workflows.find(w => w.id === workflowId);
  useEffect(() => {
    setComponents([]);
    if (!workflowId) return;
    const controller = new AbortController();
    const timeout = setTimeout(() => { setComponentsBusy(false); setNotice('Il motore non risponde. Controlla ComfyUI e riseleziona il workflow.'); controller.abort(); }, 20000);
    setComponentsBusy(true);
    fetch(`/api/creative/models/profiles/components?id=${encodeURIComponent(workflowId)}`, { signal: controller.signal }).then(r => r.json()).then(data => {
      if (!data.success) throw new Error(data.error || 'Impossibile leggere i componenti');
      setComponents(data.fields || []);
      if (data.missing_nodes?.length) setNotice(`Nodi da installare: ${data.missing_nodes.join(', ')}`);
    }).catch(e => { if (!controller.signal.aborted) setNotice(e.message); }).finally(() => { clearTimeout(timeout); if (!controller.signal.aborted) setComponentsBusy(false); });
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [workflowId]);
  const fields = (workflow?.placeholders || []).filter(key => !RUNTIME.has(key));
  const optionsFor = key => {
    const component = components.find(field => field.key === key);
    if (component?.options) return component.options;
    if (key === 'ckpt' || /unet|diffusion/.test(key)) return [...(inventory?.checkpoints || []), ...(inventory?.unets || [])];
    if (/vae/.test(key)) return inventory?.vaes || [];
    if (/clip|encoder|t5/.test(key)) return inventory?.clips || [];
    if (/lora/.test(key)) return inventory?.loras || [];
    if (/upscale/.test(key)) return inventory?.upscale_models || [];
    return [];
  };
  const submit = async save => {
    setBusy(true); setNotice(''); setVerified(false);
    try {
      const response = await fetch('/api/creative/models/profiles/save', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, workflow_id: workflowId, parameters, validate_only: !save }) });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Profilo non valido');
      setVerified(true);
      setNotice(save ? 'Profilo salvato. Lo trovi nel selettore dei modelli.' : 'Nodi, file e parametri verificati. Non è stata avviata una generazione.');
      if (save) await onSaved?.({ ...data.profile, id: data.model_id });
    } catch (e) { setNotice(e.message); } finally { setBusy(false); }
  };
  return <section className="cs-model-profile-builder" data-agent-component="ModelProfiles" data-agent-id="creative-model-profiles">
    <header className="cs-section-heading"><h3><Workflow size={18} /> Collega un modello scaricato</h3><button className="cs-icon-button" aria-label="Aggiorna workflow" onClick={load}><RefreshCw size={15} /></button></header>
    <p className="cs-hint">Il profilo collega un workflow ai suoi file: modello base, encoder, VAE e adattatori. La provenienza Hugging Face o Civitai non cambia il modo in cui viene eseguito.</p>
    <div className="cs-profile-fields">
      <label className="cs-field"><span>Nome da mostrare nel selettore</span><input value={label} maxLength={120} disabled={busy} onChange={e => { setLabel(e.target.value); setVerified(false); }} placeholder="Per esempio: Illustrazioni · il mio modello" /></label>
      <label className="cs-field"><span>Workflow compatibile con il modello</span><select value={workflowId} disabled={busy} onChange={e => { setWorkflowId(e.target.value); setParameters({}); setVerified(false); }}><option value="">Scegli il workflow</option>{workflows.map(w => <option key={w.id} value={w.id}>{w.name} · {w.capability}</option>)}</select></label>
      {fields.map(key => { const options = optionsFor(key); const value = parameters[key] ?? workflow?.defaults?.[key] ?? ''; return <label className="cs-field" key={key}><span>{key === 'ckpt' ? 'File del modello' : key.replace(/_/g, ' ')}</span>{options.length ? <select value={value} disabled={busy} onChange={e => { setParameters(p => ({ ...p, [key]: e.target.value })); setVerified(false); }}><option value="">Scegli un file installato</option>{!options.includes(value) && value && <option value={value}>{value} · non rilevato</option>}{options.map(name => <option key={name}>{name}</option>)}</select> : <input value={value} disabled={busy} onChange={e => { setParameters(p => ({ ...p, [key]: e.target.value })); setVerified(false); }} />}</label>; })}
    </div>
    <p className="cs-hint">Una LoRA richiede un modello base e un workflow che la utilizzi. Per architetture o formati nuovi, importa il workflow appropriato e verifica i nodi richiesti.</p>
    {componentsBusy && <p role="status">Lettura dei file compatibili con questo workflow…</p>}
    <div className="cs-profile-actions"><button className="cs-secondary-button" disabled={busy || componentsBusy || !workflow || !label.trim()} onClick={() => submit(false)}><CheckCircle2 size={15} /> Verifica compatibilità</button><button className="cs-secondary-button" disabled={busy || componentsBusy || !workflow || !label.trim()} onClick={() => submit(true)}><Save size={15} /> Salva profilo</button><button className="cs-text-button" onClick={onWorkflow}>Importa un altro workflow</button></div>
    {notice && <p className={`cs-form-notice ${verified ? 'cs-profile-ok' : ''}`} role="status">{notice}</p>}
  </section>;
}
