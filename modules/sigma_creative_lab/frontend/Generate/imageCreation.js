export const IMAGE_DRAFT = {
  prompt: '', negative_prompt: '', width: 1024, height: 1024, steps: 30,
  cfg_scale: 7, seed: -1, model: {}, backend: '', sampler: '', scheduler: '', priority: 'balanced',
};

export function imageModels(models = []) {
  return models.filter(m => Array.isArray(m.tasks) && m.tasks.includes('text_to_image'));
}

export function selectImageModel(draft, model, profile = {}) {
  const defaults = {
    'flux.1-schnell': [4, 1], 'flux.1-dev': [28, 1], 'qwen-image': [20, 2],
    sdxl: [30, 7], 'sd3.5-large': [28, 4],
  };
  const [steps, cfg_scale] = defaults[model.model_id] || [profile.defaults?.steps ?? 30, profile.defaults?.cfg_scale ?? 7];
  return { ...draft, model, steps, cfg_scale, sampler: profile.defaults?.sampler || '', scheduler: profile.defaults?.scheduler || '' };
}

export function selectionIssue(draft, models, inventory) {
  const candidates = imageModels(models);
  const selected = candidates.find(m => m.id === draft.model?.model_id);
  const ckpt = draft.model?.ckpt;
  if (draft.model?.model_id && !selected) return 'Il modello selezionato non è più nel catalogo. Scegline un altro.';
  if (ckpt) {
    if (!selected) return 'Scegli un modello prima di indicare un file personalizzato.';
    if (draft.backend && draft.backend !== 'comfyui') return 'I file installati si usano con il motore locale ComfyUI.';
    if (!inventory?.reachable || !inventory?.enabled) return 'Collega ComfyUI per usare il file selezionato.';
    if (![...(inventory.checkpoints || []), ...(inventory.unets || [])].includes(ckpt)) return 'Il file selezionato non è più disponibile. Aggiorna i modelli.';
    if (!selected.workflow_available) return 'Questo modello richiede un workflow: puoi configurarlo in Modelli e motori.';
    return '';
  }
  if (selected) {
    if (!selected.available) return 'Questo modello non è ancora configurato. Apri Modelli e motori per prepararlo.';
    if (draft.backend && !(selected.available_via || []).includes(draft.backend)) return 'Il modello non è disponibile sul motore scelto. Imposta il motore su Automatico.';
  } else if (!candidates.some(m => m.available && (!draft.backend || (m.available_via || []).includes(draft.backend)))) {
    return 'Nessun modello immagine disponibile. Collega un motore o installa un modello.';
  }
  return '';
}

export function imageRequest(draft) {
  const params = {};
  for (const [key, min, max, integer] of [
    ['width', 64, 4096, true], ['height', 64, 4096, true], ['steps', 1, 150, true],
    ['cfg_scale', 0, 30, false], ['seed', -1, Number.MAX_SAFE_INTEGER, true],
  ]) {
    if (draft[key] === '') throw new Error('Completa i parametri numerici prima di creare.');
    const value = Number(draft[key]);
    if (!Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) {
      throw new Error('Controlla dimensioni, passaggi, aderenza e seed nelle impostazioni avanzate.');
    }
    params[key] = value;
  }
  if (params.width % 8 || params.height % 8) throw new Error('Larghezza e altezza devono essere multipli di 8.');
  params.prompt = draft.prompt.trim();
  if (!params.prompt) throw new Error('Descrivi prima l’immagine che vuoi creare.');
  params.negative_prompt = draft.negative_prompt.trim();
  params.priority = draft.priority;
  for (const key of ['model_id', 'ckpt']) if (draft.model?.[key]) params[key] = draft.model[key];
  for (const key of ['sampler', 'scheduler']) if (draft[key]) params[key] = draft[key];
  return { params, backend: draft.backend || undefined };
}

export function draftFromAsset(asset, previous = IMAGE_DRAFT) {
  const params = asset?.metadata?.params || {};
  const draft = { ...previous };
  for (const key of Object.keys(IMAGE_DRAFT)) if (key !== 'model' && key !== 'backend' && params[key] !== undefined) draft[key] = params[key];
  draft.model = { ...(params.model_id ? { model_id: params.model_id } : {}), ...(params.ckpt ? { ckpt: params.ckpt } : {}) };
  draft.backend = '';
  return draft;
}
