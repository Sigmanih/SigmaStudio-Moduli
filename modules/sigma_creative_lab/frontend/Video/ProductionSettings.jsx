import React, { useEffect, useState } from 'react';
import { Settings2, Music, Layers, Plus, Trash2, Upload } from 'lucide-react';

/*
 * Impostazioni di resa di una produzione: pesi del modello, cache, durata dei
 * clip, upscale, controlli automatici, LoRA e colonna sonora. I valori predefiniti
 * vengono dal benchmark (vedi tab Motori): qui si cambiano solo se serve.
 */

const KEYS = ['C major', 'D major', 'E major', 'F major', 'G major', 'A major', 'Bb major',
  'C minor', 'D minor', 'E minor', 'F minor', 'G minor', 'A minor', 'B minor'];

export function AmbientLoopCard({ draft, disabled, onChange }) {
  const s = draft.settings || {};
  const ambient = s.production_mode === 'ambient_loop';
  const set = patch => onChange({ settings: { ...s, ...patch } });
  const raw = s.scene_reference || '';
  const path = raw.replaceAll('\\', '/');
  const index = path.indexOf('/works/');
  const preview = index >= 0 ? path.slice(index) : path.startsWith('/data/') ? path : '';
  return (
    <section className="cs-mesh-card" data-agent-component="AmbientLoopSettings" data-agent-id="ambient-loop">
      <h3 className="cs-mesh-title"><Layers size={18} /> Video ambientale continuo</h3>
      <label>Tipo di produzione
        <select className="cs-select" value={s.production_mode || 'narrative'} disabled={disabled}
                onChange={e => onChange({ settings: { ...s, production_mode: e.target.value,
                  ...(e.target.value === 'ambient_loop' ? { video_model: 'ltx25', output_width: 3840, output_height: 2160 } : {}) },
                  ...(e.target.value === 'ambient_loop' ? { soundtrack: { ...draft.soundtrack, enabled: false } } : {}) })}>
          <option value="narrative">Storia e inquadrature</option>
          <option value="ambient_loop">Scena fissa in loop</option>
        </select>
      </label>
      {ambient && <>
        <p className="cs-hint">Un solo ambiente e una sola camera. Genera brevi variazioni dal medesimo riferimento,
          raccorda immagini e suono, poi estende il ciclo alla durata finale. La continuità va verificata sulle clip.</p>
        <div className="cs-inline-params">
          <label>Durata finale (ore)<input type="number" min="0.001" max="24" step="0.5" disabled={disabled}
            value={(s.loop_duration_s ?? 43200) / 3600} onChange={e => set({ loop_duration_s: Number(e.target.value) * 3600 })} /></label>
          <label>Durata del ciclo (s, massimo 20 minuti)<input type="number" min="4" max="1200" disabled={disabled}
            value={s.loop_base_seconds ?? 60} onChange={e => set({ loop_base_seconds: Number(e.target.value) })} /></label>
          <label>Raccordo audio/video (s)<input type="number" min="0.1" max="3" step="0.05" disabled={disabled}
            value={s.loop_crossfade_s ?? .75} onChange={e => set({ loop_crossfade_s: Number(e.target.value) })} /></label>
          <label>Velocità del movimento (%)<input type="number" min="25" max="100" step="5" disabled={disabled}
            value={Math.round((s.loop_motion_speed ?? 1) * 100)} onChange={e => set({ loop_motion_speed: Number(e.target.value) / 100 })} /></label>
          <label>Volume ambiente (LUFS)<input type="number" min="-30" max="-14" step="1" disabled={disabled}
            value={s.loop_audio_lufs ?? -23} onChange={e => set({ loop_audio_lufs: Number(e.target.value) })} /></label>
          <label>Formato video<select className="cs-select" disabled={disabled} value={s.loop_export_codec || 'h264'}
            onChange={e => set({ loop_export_codec: e.target.value })}>
            <option value="h264">H.264 — compatibilità ampia</option>
            <option value="hevc">HEVC/H.265 — file più compatti</option>
          </select></label>
          <label>Qualità esportazione (0 = progetto)<input type="number" min="0" max="30" step="1" disabled={disabled}
            value={s.loop_export_quality || 0} onChange={e => set({ loop_export_quality: Number(e.target.value) })} /></label>
          <label>Larghezza finale (px)<input type="number" min="0" max="7680" step="2" disabled={disabled}
            value={s.output_width || 0} onChange={e => set({ output_width: Number(e.target.value) })} /></label>
        </div>
        <p className="cs-hint">Una qualità numerica più bassa aumenta dettaglio e peso del file. Il valore 0 usa la qualità del progetto.</p>
        <label><input type="checkbox" disabled={disabled} checked={s.loop_exact_cycle === true}
          onChange={e => set({ loop_exact_cycle: e.target.checked })} /> Durata esatta del ciclo, compresi i raccordi audio/video</label>
        <label><input type="checkbox" disabled={disabled} checked={s.loop_interpolate !== false}
          onChange={e => set({ loop_interpolate: e.target.checked })} /> Interpola i fotogrammi nel rallentatore; audio con tono preservato</label>
        <label>Immagine canonica della scena
          <input className="cs-inline-input cs-prod-wide" disabled={disabled} value={raw}
            placeholder="Percorso immagine o URL locale /works/…" onChange={e => set({ scene_reference: e.target.value })} />
        </label>
        <RefImageInput productionId={draft.id} value={raw} disabled={disabled}
                       onChange={value => set({ scene_reference: value })} />
        {preview && <img className="cs-video-player" src={preview} alt="Riferimento unico della scena ambientale" />}
        <label>Elementi da mantenere e movimento consentito
          <textarea className="cs-textarea" rows={3} disabled={disabled} value={s.scene_constraints || ''}
            onChange={e => set({ scene_constraints: e.target.value })} />
        </label>
        <p className="cs-hint">Il riferimento vincola primo e ultimo fotogramma di tutte le varianti.
          La base resta nel quadro: l'uscita adatta le proporzioni senza ritagliare. Audio naturale dalle clip; musica disattivata.</p>
      </>}
    </section>
  );
}

export function SettingsCard({ draft, disabled, onSettings }) {
  const s = draft.settings || {};
  const set = (patch) => onSettings({ ...s, ...patch });
  const ltx = s.video_model === 'ltx25';
  const [customModels, setCustomModels] = useState([]);
  const [writers, setWriters] = useState([]);

  useEffect(() => {
    fetch('/api/creative/video/diffusion_models')
      .then(r => r.json())
      .then(d => setCustomModels(d.models || []))
      .catch(() => setCustomModels([]));
    // Modelli di testo installati: chi scrive la storia puo' essere diverso dal modello della chat.
    fetch('/api/models/local/list')
      .then(r => r.json())
      .then(d => setWriters((d.models || []).filter(m => m.category === 'llm' && m.format === 'GGUF' && m.is_complete !== false)))
      .catch(() => setWriters([]));
  }, []);

  const OFFICIAL_DIT = new Set([
    'minimax_h3_fl2va_pruned_int8_convrot.safetensors',
    'minimax_h3_fl2va_pruned_fp8_scaled.safetensors',
    'minimax_h3_fl2va_pruned_w6a8.safetensors',
    'minimax_h3_ref2va_pruned_int8_convrot.safetensors',
    'minimax_h3_ref2va_pruned_fp8_scaled.safetensors',
    'minimax_h3_ref2va_pruned_w6a8.safetensors',
    'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
  ]);
  const userModels = customModels.filter(m => !OFFICIAL_DIT.has(m.filename));

  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><Settings2 size={18} /> Resa</h3>
      <div className="cs-inline-params">
        <label>Modello video
          <select className="cs-select" value={s.video_model || 'h3'} disabled={disabled}
                  onChange={e => set({ video_model: e.target.value,
                                       max_clip_seconds: e.target.value === 'ltx25' ? 10 : 5.2 })}>
            <option value="h3">MiniMax H3 (licenza esclude l'UE)</option>
            <option value="ltx25">LTX-2.5 (licenza valida in UE, 1280x704)</option>
          </select>
        </label>
        <label>Pesi DiT
          <select className="cs-select" value={s.weights || 'int8'} disabled={disabled || ltx}
                  onChange={e => set({ weights: e.target.value })}>
            <optgroup label="DiT Ufficiali Comfy-Org">
              <option value="int8">int8 convrot (riferimento)</option>
              <option value="fp8">fp8 scaled (tensor core FP8)</option>
              <option value="w6a8" disabled>w6a8 (non supportato)</option>
            </optgroup>
            {userModels.length > 0 && (
              <optgroup label="Modelli Installati (Civitai / diffusion_models)">
                {userModels.map(m => {
                  const isH3 = !m.base_model || m.base_model.toLowerCase().includes('minimax') || m.base_model.toLowerCase().includes('h3');
                  const label = `${m.model_name || m.filename}${m.version_name ? ` · ${m.version_name}` : ''} [${m.format}] (${m.size_gb} GB)${!isH3 ? ` (⚠️ ${m.base_model} - modello immagini)` : ''}`;
                  return (
                    <option key={m.filename} value={m.filename} disabled={!isH3}>
                      {label}
                    </option>
                  );
                })}
              </optgroup>
            )}
          </select>
        </label>
        <label>Cache fra gli step
          <select className="cs-select" value={s.cache_mode || ''} disabled={disabled || ltx}
                  onChange={e => set({ cache_mode: e.target.value })}>
            <option value="">nessuna (qualita' piena)</option>
            <option value="easycache">EasyCache (~2x piu' veloce)</option>
          </select>
        </label>
        <label>Clip max (s)
          <select className="cs-select" value={s.max_clip_seconds || (ltx ? 10 : 5.2)} disabled={disabled}
                  onChange={e => set({ max_clip_seconds: Number(e.target.value) })}>
            <option value={5.2}>5 ({ltx ? '121' : '124'} frame)</option>
            <option value={10}>10</option>
            <option value={15}>15 ({ltx ? '361' : '362'} frame, molto piu' lento)</option>
          </select>
        </label>
        <label>Uscita
          <select className="cs-select" value={s.output_height || 0} disabled={disabled}
                  onChange={e => set({ output_height: Number(e.target.value) })}>
            <option value={0}>risoluzione di generazione</option>
            <option value={720}>upscale 720p</option>
            <option value={1080}>upscale 1080p</option>
            <option value={1440}>upscale 1440p</option>
            <option value={2160}>upscale 2160p / UHD</option>
          </select>
        </label>
        <label>Upscale con
          <select className="cs-select" value={s.upscaler || 'esrgan'} disabled={disabled || !s.output_height}
                  onChange={e => set({ upscaler: e.target.value })}>
            <option value="seedvr2">SeedVR2 (ricostruisce il dettaglio, coerente fra i fotogrammi)</option>
            <option value="esrgan">Real-ESRGAN (ricostruisce il dettaglio)</option>
            <option value="lanczos">Lanczos (veloce)</option>
          </select>
        </label>
        <label>Step
          <input type="number" min="4" max="50" value={s.steps || 20} disabled={disabled || ltx}
                 title={ltx ? 'LTX distillato usa passi fissi (8 + 3)' : ''}
                 onChange={e => set({ steps: Number(e.target.value) })} />
        </label>
      </div>
      <div className="cs-prod-toggles">
        <p className="cs-hint">Controllo tecnico obbligatorio · anatomia, mani e oggetti richiedono anche una revisione di dettaglio prima del montaggio.</p>
        <label><input type="checkbox" checked={!!s.continuous_journey} disabled={disabled || !ltx}
          onChange={e => set({ continuous_journey: e.target.checked,
            ...(e.target.checked ? { pov: true, crossfade_s: 0, color_match: false } : {}) })} /> Viaggio continuo in prima persona: raccordi e riferimenti finali puliti obbligatori</label>
        <label><input type="checkbox" checked={s.color_match !== false} disabled={disabled}
                      onChange={e => set({ color_match: e.target.checked })} /> Correzione colore nelle riprese continue</label>
        <label><input type="checkbox" checked={s.judge !== false} disabled={disabled}
                      onChange={e => set({ judge: e.target.checked })} /> Giudice visivo: rifa le clip con azione sbagliata o movimento innaturale</label>
        <label><input type="checkbox" checked={s.motion_guard !== false} disabled={disabled}
                      onChange={e => set({ motion_guard: e.target.checked })} /> Chiedi nel prompt un movimento fisicamente plausibile</label>
        {ltx && (
          <>
            <label title="Wan 2.2 S2V anima il personaggio dalla voce: piu' realistico sugli umani, sui cartoni LTX articola di piu' la bocca">Battute con
              <select className="cs-select" value={s.dialogue_engine || ''} disabled={disabled}
                      onChange={e => set({ dialogue_engine: e.target.value })}>
                <option value="">LTX-2.5 (consigliato per i cartoni)</option>
                <option value="wan_s2v">Wan 2.2 S2V (dalla voce)</option>
              </select>
            </label>
            <label title="Wan 2.2 I2V 14B: movimento piu' fisico su alcune azioni, a 832x480 e 16 fps (il montaggio adegua)">Azioni con
              <select className="cs-select" value={s.motion_engine || ''} disabled={disabled}
                      onChange={e => set({ motion_engine: e.target.value })}>
                <option value="">LTX-2.5</option>
                <option value="wan_i2v">Wan 2.2 I2V 14B</option>
              </select>
            </label>
            <label title="Sotto le battute il suono del luogo (prato, stagno...), generato una volta per luogo">
              <input type="checkbox" checked={s.ambience !== false} disabled={disabled}
                     onChange={e => set({ ambience: e.target.checked })} /> Ambiente sonoro sotto le battute
            </label>
          </>
        )}
        <label title="Scrive storia, luoghi, inquadrature e correzioni. Piu' bit = storie migliori: il 27B a 2 bit inventa parole, a Q4_K_M no">Chi scrive la storia
          <select className="cs-select" value={s.writer_model || ''} disabled={disabled}
                  onChange={e => set({ writer_model: e.target.value })}>
            <option value="">il modello della chat</option>
            {writers.map(m => (
              <option key={m.model_id} value={m.model_id}>{m.clean_name || m.model_id}{m.params_label ? ` (${m.params_label})` : ''}</option>
            ))}
          </select>
        </label>
        <label title="La scelta finale e' tua: il giudice segnala, e rifa' da solo solo quello che e' da buttare">Il giudice
          <select className="cs-select" value={s.judge_mode || 'severe'} disabled={disabled || s.judge === false}
                  onChange={e => set({ judge_mode: e.target.value })}>
            <option value="severe">consiglia, rifà solo gli errori gravi (deformi, fisica impossibile)</option>
            <option value="advise">consiglia soltanto</option>
            <option value="strict">rifà ogni clip bocciata (più lento)</option>
          </select>
        </label>
        <label>Giudice su
          <select className="cs-select" value={s.judge_device || 'auto'} disabled={disabled || s.judge === false}
                  onChange={e => set({ judge_device: e.target.value })}>
            <option value="auto">Automatico (GPU piu' piccola dedicata, ~8 s a clip)</option>
            <option value="cpu">CPU (30B, ~85 s a clip, nessuna GPU tolta ai render)</option>
            <option value="gpu:1">GPU 1</option>
            <option value="gpu:0">GPU 0</option>
          </select>
        </label>
      </div>
    </div>
  );
}

export function LoraCard({ draft, disabled, onBible }) {
  const [available, setAvailable] = useState([]);
  const [pick, setPick] = useState('');
  const loras = draft.bible?.loras || [];

  // Solo le LoRA della famiglia del modello video: una LoRA di H3 su LTX non si carica (e viceversa).
  const family = draft.settings?.video_model === 'ltx25' ? 'ltx' : 'minimax_h3';
  useEffect(() => {
    fetch(`/api/creative/loras?family=${family}`).then(r => r.json())
      .then(d => setAvailable(d.loras || [])).catch(() => setAvailable([]));
  }, [family]);

  const add = () => {
    const l = available.find(x => x.path === pick);
    if (!l || loras.some(x => x.path === l.path)) return;
    onBible({ ...draft.bible, loras: [...loras, { path: l.path, name: l.model_name || l.name, multiplier: 1.0,
      trained_words: l.trained_words || [] }] });
  };
  const update = (i, patch) => onBible({ ...draft.bible, loras: loras.map((l, k) => (k === i ? { ...l, ...patch } : l)) });

  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><Layers size={18} /> LoRA di stile</h3>
      {loras.map((l, i) => (
        <div key={l.path} className="cs-prod-lora">
          <span title={l.path}>{l.name}</span>
          {(l.trained_words || []).length > 0 && <code>{l.trained_words.join(' ')}</code>}
          <input type="number" min="0" max="2" step="0.05" value={l.multiplier} disabled={disabled}
                 onChange={e => update(i, { multiplier: Number(e.target.value) })} />
          <button className="cs-icon-btn" disabled={disabled} title="Rimuovi"
                  onClick={() => onBible({ ...draft.bible, loras: loras.filter((_, k) => k !== i) })}>
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <div className="cs-prod-row">
        <select className="cs-select" value={pick} disabled={disabled} onChange={e => setPick(e.target.value)}>
          <option value="">{available.length ? 'Scegli una LoRA H3…' : 'Nessuna LoRA H3: importala da Modelli & Civitai'}</option>
          {available.map(l => <option key={l.path} value={l.path}>{l.model_name || l.name}</option>)}
        </select>
        <button className="cs-tool-btn" disabled={disabled || !pick} onClick={add}><Plus size={14} /> Aggiungi</button>
      </div>
      <p className="cs-hint">Le parole chiave della LoRA vengono aggiunte da sole a ogni inquadratura.</p>
      {loras.length > 0 && (
        <p className="cs-prod-error">
          Attenzione: con una LoRA H3 rende circa 8 volte piu' lento su una GPU da 16 GB (prova del 2026-10-11:
          559 s invece di 69 per clip), perche' il modello non entra in memoria e la LoRA viene riapplicata a ogni passo.
          Per uno stile preciso conviene il genere con fotogrammi chiave.
        </p>
      )}
    </div>
  );
}

export function SoundtrackCard({ draft, disabled, aceInstalled, onSoundtrack }) {
  const st = draft.soundtrack || {};
  const set = (patch) => onSoundtrack({ ...st, ...patch });
  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><Music size={18} /> Colonna sonora</h3>
      <label className="cs-prod-toggles">
        <span><input type="checkbox" checked={!!st.enabled} disabled={disabled || !aceInstalled}
                     onChange={e => set({ enabled: e.target.checked })} /> Musica continua generata con ACE-Step</span>
      </label>
      {!aceInstalled && <p className="cs-hint">ACE-Step non e' installato: installalo dalla sezione Motori.</p>}
      {st.enabled && (
        <>
          <input className="cs-inline-input cs-prod-wide" placeholder="Genere e strumenti (vuoto = stile audio della produzione)"
                 value={st.tags || ''} disabled={disabled} onChange={e => set({ tags: e.target.value })} />
          <div className="cs-inline-params">
            <label>BPM
              <input type="number" min="40" max="200" value={st.bpm || 90} disabled={disabled}
                     onChange={e => set({ bpm: Number(e.target.value) })} />
            </label>
            <label>Tonalita'
              <select className="cs-select" value={st.keyscale || 'D minor'} disabled={disabled}
                      onChange={e => set({ keyscale: e.target.value })}>
                {KEYS.map(k => <option key={k} value={k}>{k}</option>)}
              </select>
            </label>
            <label>Volume musica (dB)
              <input type="number" min="-40" max="0" step="1" value={st.music_db ?? -14} disabled={disabled}
                     onChange={e => set({ music_db: Number(e.target.value) })} />
            </label>
          </div>
          <p className="cs-hint">
            Un brano per scena con tonalita' e tempo comuni, uniti con dissolvenze. Ai clip si chiede solo
            l'audio diegetico (suoni e voci) e la musica si abbassa quando parlano.
          </p>
        </>
      )}
    </div>
  );
}

export function RefImageInput({ productionId, value, disabled, onChange }) {
  const [busy, setBusy] = useState(false);
  const upload = (file) => {
    if (!file) return;
    setBusy(true);
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const res = await fetch('/api/creative/productions/upload', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: productionId, filename: file.name, data: reader.result }),
        });
        const data = await res.json();
        if (data.success) onChange(data.path);
      } finally { setBusy(false); }
    };
    reader.readAsDataURL(file);
  };
  return (
    <label className={`cs-icon-btn cs-prod-upload ${value ? 'has' : ''}`} title={value || 'Carica immagine di riferimento'}>
      <Upload size={13} />{busy ? '…' : value ? 'rif.' : ''}
      <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={disabled || busy}
             onChange={e => upload(e.target.files?.[0])} />
    </label>
  );
}
