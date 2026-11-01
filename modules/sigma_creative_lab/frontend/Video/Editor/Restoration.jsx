import React, { useCallback, useEffect, useState } from 'react';
import { Palette, Maximize2, ScanText, Mic, Music, Trash2, Skull, Sparkles, Shield, Plus, Film, Languages, FolderOpen, ChevronLeft } from 'lucide-react';

/*
 * Restauro di un film muto, elemento per elemento: colore, risoluzione, testi
 * sullo schermo letti ad alta voce da un personaggio ciascuno, colonna sonora.
 * Ogni passo e' un job dell'editor; i testi letti si correggono qui prima di
 * rifare la narrazione.
 */

const LANGUAGES = [['en', 'Inglese'], ['fr', 'Francese'], ['de', 'Tedesco'], ['es', 'Spagnolo'],
  ['pt', 'Portoghese'], ['it', 'Italiano'], ['zh', 'Cinese'], ['ar', 'Arabo']];

const REASONS = { technicolor: 'Technicolor', dipinto: 'colore dipinto', sequenza: 'stessa sequenza', buia: 'troppo buia', 'a mano': 'a mano' };

function seconds(text) {
  // Accetta "49:13", "1:02:21" o secondi semplici.
  const parts = String(text).trim().split(':').map(Number);
  if (parts.some(Number.isNaN)) return NaN;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}

// Tratti lasciati come nel film (gia' a colori): la mappa automatica si corregge qui, vale alla prossima ricolorazione.
function ProtectSection({ color, onSave }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  if (!color) return null;
  const add = () => {
    const a = seconds(from), b = seconds(to);
    if (Number.isFinite(a) && Number.isFinite(b) && b > a) {
      onSave({ start_s: a, end_s: b, protect: true });
      setFrom(''); setTo('');
    }
  };
  return (
    <>
      <p className="cs-hint">
        <Shield size={12} /> Scene lasciate originali (gia' a colori nel film): {color.protected.length} tratti,
        {' '}{Math.round(color.night_s)} s di notte virata tenuta blu. Correggi qui, poi "Ricolora".
      </p>
      <div className="cs-ed-cards">
        {color.protected.map(r => (
          <div className="cs-ed-card" key={`${r.start_s}-${r.end_s}`}>
            <span className="cs-prod-status">{clock(r.start_s)}–{clock(r.end_s)} · {REASONS[r.reason] || r.reason}</span>
            <span className="cs-ed-card-tools">
              <button className="cs-ed-mini" title="Ricolora anche questo tratto"
                      onClick={() => onSave({ start_s: r.start_s, end_s: r.end_s, protect: false })}>
                <Trash2 size={11} />
              </button>
            </span>
          </div>
        ))}
        <div className="cs-ed-actions">
          <input className="cs-inline-input" value={from} onChange={e => setFrom(e.target.value)} placeholder="da 49:13" />
          <input className="cs-inline-input" value={to} onChange={e => setTo(e.target.value)} placeholder="a 52:33" />
          <button className="cs-ed-mini" title="Lascia originale questo tratto" onClick={add}><Plus size={11} /></button>
        </div>
      </div>
    </>
  );
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* risposta non JSON */ }
  if (!res.ok || data.success === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function clock(t) {
  const m = Math.floor(t / 60);
  return `${m}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
}

function CardRow({ card, index, onSave }) {
  const [text, setText] = useState(card.text);
  const [speaker, setSpeaker] = useState(card.speaker);
  useEffect(() => { setText(card.text); setSpeaker(card.speaker); }, [card.text, card.speaker]);
  if (card.deleted) return null;
  return (
    <div className={`cs-ed-card ${card.needs_review ? 'review' : ''}`}
         title={card.seen ? `In scena: ${card.seen}` : undefined}>
      <span className="cs-prod-status">
        {clock(card.start)} · {card.kind === 'page' ? 'pagina' : 'didascalia'}{card.needs_review ? ' · da rivedere' : ''}
      </span>
      <input className="cs-inline-input" value={speaker} onChange={e => setSpeaker(e.target.value)}
             onBlur={() => speaker !== card.speaker && onSave({ index, speaker })} title="Chi legge" />
      <span className="cs-ed-card-tools">
        <button className={`cs-ed-mini ${card.menacing ? 'active' : ''}`}
                title={card.menacing ? 'Voce da cattivo (clic per toglierla)' : 'Dai al personaggio la voce da cattivo'}
                onClick={() => onSave({ index, menacing: !card.menacing })}>
          <Skull size={11} />
        </button>
        <button className="cs-ed-mini" title="Non leggere questo testo" onClick={() => onSave({ index, delete: true })}>
          <Trash2 size={11} />
        </button>
      </span>
      <textarea className="cs-textarea" rows={2} value={text} onChange={e => setText(e.target.value)}
                onBlur={() => text !== card.text && onSave({ index, text })} />
    </div>
  );
}

function MoodRow({ mood, index, onSave }) {
  const [tags, setTags] = useState(mood.tags);
  useEffect(() => { setTags(mood.tags); }, [mood.tags]);
  return (
    <div className={`cs-ed-card ${mood.edited ? 'edited' : ''}`}>
      <span className="cs-prod-status">{clock(mood.start)}–{clock(mood.end)}{mood.edited ? ' · corretta' : ''}</span>
      <textarea className="cs-textarea" rows={2} value={tags} onChange={e => setTags(e.target.value)}
                onBlur={() => tags !== mood.tags && onSave({ index, tags })} />
    </div>
  );
}

export default function RestorationPanel({ pid, item, sourceOrigin, refresh, onJob }) {
  const [height, setHeight] = useState(1440);
  const [language, setLanguage] = useState('en');
  const [pipelineLanguages, setPipelineLanguages] = useState(LANGUAGES.map(([id]) => id));
  const [makeMusic, setMakeMusic] = useState(true);
  const [preserveSourceAudio, setPreserveSourceAudio] = useState(false);
  const [outputDir, setOutputDir] = useState('');
  const [includeSigla, setIncludeSigla] = useState(() => typeof window !== 'undefined'
    && window.localStorage.getItem('sigmaCreativeIncludeSigla') === 'true');
  const [siglaAssetsDir, setSiglaAssetsDir] = useState(() => typeof window !== 'undefined'
    ? window.localStorage.getItem(`sigmaCreativeSiglaDir:${pid}`) || window.localStorage.getItem('sigmaCreativeSiglaDefaultDir') || '' : '');
  const [siglaPicker, setSiglaPicker] = useState(false);
  const [pickerTarget, setPickerTarget] = useState('sigla');
  const [siglaFolders, setSiglaFolders] = useState([]);
  const [siglaBrowsePath, setSiglaBrowsePath] = useState('');
  const [siglaHasIntro, setSiglaHasIntro] = useState(false);
  const [siglaDefault, setSiglaDefault] = useState(() => typeof window !== 'undefined'
    && Boolean(window.localStorage.getItem('sigmaCreativeSiglaDefaultDir'))
    && window.localStorage.getItem('sigmaCreativeSiglaDefaultDir') === (window.localStorage.getItem(`sigmaCreativeSiglaDir:${pid}`)
      || window.localStorage.getItem('sigmaCreativeSiglaDefaultDir')));
  const [ctaLanguage, setCtaLanguage] = useState('en');
  const [style, setStyle] = useState('');
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const shot = item.shot_id;

  const load = useCallback(() => {
    api(`/api/creative/editor/restoration?id=${encodeURIComponent(pid)}&shot=${encodeURIComponent(shot)}`)
      .then(setState).catch(e => setError(e.message));
  }, [pid, shot]);
  // L'editor ricarica i dati quando un job finisce: e' il momento di rileggere i testi.
  useEffect(() => { load(); }, [load, refresh]);

  const save = useCallback(edit => {
    api('/api/creative/editor/restoration/cards', { id: pid, shot, edits: [edit] })
      .then(setState).catch(e => setError(e.message));
  }, [pid, shot]);
  const saveMood = useCallback(edit => {
    api('/api/creative/editor/restoration/moods', { id: pid, shot, edits: [edit] })
      .then(setState).catch(e => setError(e.message));
  }, [pid, shot]);
  const saveProtect = useCallback(range => {
    api('/api/creative/editor/restoration/protect', { id: pid, shot, ranges: [range] })
      .then(setState).catch(e => setError(e.message));
  }, [pid, shot]);
  const [redescribe, setRedescribe] = useState(false);

  const browseSigla = useCallback(async path => {
    try {
      const d = await api(`/api/creative/editor/sigla-folders${path ? `?path=${encodeURIComponent(path)}` : ''}`);
      setSiglaBrowsePath(d.current);
      setSiglaFolders(d.folders || []);
      setSiglaHasIntro(Boolean(d.has_intro && d.has_outro));
    } catch (e) { setError(e.message); }
  }, []);

  const cards = state?.cards || [];
  const voices = Object.entries(state?.voices || {});
  return (
    <div className="cs-ed-restore">
      <h4>Restauro</h4>
      {sourceOrigin === 'import' && (
        <div className="cs-ed-actions">
          <select className="cs-inline-input" value={height} onChange={e => setHeight(Number(e.target.value))}
                  aria-label="Risoluzione del restauro">
            <option value={1080}>1080 linee · 1440×1080 (4:3), file più leggero</option>
            <option value={1440}>1440p · 1920×1440 (4:3), consigliato</option>
            <option value={2160}>2160 linee · 2880×2160 (4:3), 4K</option>
          </select>
          <p className="cs-hint">Il rapporto del film resta intatto. Il 4K ingrandisce il raster senza recuperare dettagli assenti nella pellicola; scegli 1080 per un file più leggero.</p>
          <button className="cs-tool-btn" title="Analisi cadenza, pulizia forense, SeedVR2, RIFE 24 fps, colore coerente e rapporto originale"
                  onClick={() => onJob('remaster', { item_id: item.id, output_height: height,
                    preserve_source_audio: preserveSourceAudio })}>
            <Film size={14} /> Restauro video
          </button>
        </div>
      )}
      {sourceOrigin === 'import' && (
        <div className="cs-ed-restore-pipeline">
          <p className="cs-hint">Mantiene sigla, cartelli e chiusura originali. Pipeline guidata: restauro video, testi, musica, voci e master multilingua; nessun taglio automatico.</p>
          <div className="cs-ed-restore-languages">
            {LANGUAGES.map(([id, label]) => (
              <label key={id} className="cs-ed-inline">
                <input type="checkbox" checked={pipelineLanguages.includes(id)}
                       onChange={e => setPipelineLanguages(current => e.target.checked
                         ? [...current, id] : current.filter(x => x !== id))} />
                {label}
              </label>
            ))}
          </div>
          <label className="cs-ed-inline">
            <input type="checkbox" checked={makeMusic} onChange={e => setMakeMusic(e.target.checked)} />
            Crea una colonna sonora originale a tema, adattata alle scene
          </label>
          <input className="cs-inline-input cs-prod-wide" value={style} onChange={e => setStyle(e.target.value)}
                 placeholder="Tema musicale facoltativo (es. sinfonico, jazz d'epoca, gotico, senza canto)" />
          <label className="cs-ed-inline">
            <input type="checkbox" checked={preserveSourceAudio}
                   onChange={e => setPreserveSourceAudio(e.target.checked)} />
            Mantieni l'audio originale sotto musica e voci
          </label>
          <div className="cs-ed-actions">
            <span className="cs-inline-input cs-prod-wide" title={outputDir}>{outputDir || 'Cartella del file finale (predefinita del modulo)'}</span>
            <button className="cs-tool-btn" onClick={() => { setPickerTarget('output'); setSiglaPicker(true); browseSigla(''); }}>
              <FolderOpen size={14} /> Scegli destinazione
            </button>
          </div>
          <label className="cs-ed-inline">
            <input type="checkbox" checked={includeSigla} onChange={e => {
              setIncludeSigla(e.target.checked);
              window.localStorage.setItem('sigmaCreativeIncludeSigla', String(e.target.checked));
            }} />
            Inserisci la sigla animata con countdown, voce narrante, logo e invito a iscriversi
          </label>
          {includeSigla && <>
            <div className="cs-ed-actions">
              <span className="cs-inline-input cs-prod-wide" title={siglaAssetsDir}>{siglaAssetsDir || 'Seleziona una cartella con intro, outro e voci'}</span>
              <button className="cs-tool-btn" onClick={() => { setPickerTarget('sigla'); setSiglaPicker(true); browseSigla(''); }}>
                <FolderOpen size={14} /> Scegli cartella
              </button>
            </div>
            <label className="cs-ed-inline">
              <input type="checkbox" checked={siglaDefault} onChange={e => {
                const enabled = e.target.checked;
                setSiglaDefault(enabled);
                if (enabled && siglaAssetsDir) window.localStorage.setItem('sigmaCreativeSiglaDefaultDir', siglaAssetsDir);
                else window.localStorage.removeItem('sigmaCreativeSiglaDefaultDir');
              }} />
              Usa questa cartella come sigla predefinita per i prossimi film
            </label>
            {siglaPicker && <div className="cs-ed-popover">
              <div className="cs-ed-actions">
                <button className="cs-ed-mini" disabled={!siglaBrowsePath} title="Cartella precedente"
                        onClick={() => browseSigla(/^[A-Za-z]:[\\/]SigmaRestauri$/i.test(siglaBrowsePath)
                          || /[\\/]works$/i.test(siglaBrowsePath) ? '' : siglaBrowsePath.replace(/[\\/][^\\/]+$/, ''))}><ChevronLeft size={14} /></button>
                <strong>{siglaBrowsePath || 'Cartelle disponibili'}</strong>
              </div>
              {siglaBrowsePath && <button className="cs-tool-btn" disabled={pickerTarget === 'sigla' && !siglaHasIntro}
                onClick={() => {
                  if (pickerTarget === 'sigla') {
                    setSiglaAssetsDir(siglaBrowsePath);
                    window.localStorage.setItem(`sigmaCreativeSiglaDir:${pid}`, siglaBrowsePath);
                    if (siglaDefault) window.localStorage.setItem('sigmaCreativeSiglaDefaultDir', siglaBrowsePath);
                  } else setOutputDir(siglaBrowsePath);
                  setSiglaPicker(false);
                }}>{pickerTarget === 'sigla' ? `Seleziona cartella sigla${siglaHasIntro ? ' · intro e outro trovati' : ' · intro/outro mancanti'}` : 'Seleziona cartella di destinazione'}</button>}
              <div className="cs-ed-cards">{siglaFolders.map(folder => (
                <button className="cs-tool-btn" key={folder.path} onClick={() => browseSigla(folder.path)}>
                  <FolderOpen size={13} /> {folder.name}
                </button>))}</div>
              <button className="cs-tool-btn" onClick={() => setSiglaPicker(false)}>Chiudi</button>
            </div>}
            <div className="cs-ed-actions">
              <select className="cs-inline-input" value={ctaLanguage} onChange={e => setCtaLanguage(e.target.value)}
                      aria-label="Lingua dell'invito a iscriversi">
                {LANGUAGES.map(([id, label]) => <option key={id} value={id}>Invito: {label}</option>)}
              </select>
            </div>
            <p className="cs-hint">Conserva animazione, countdown e voce originale; aggiunge una maschera neon al logo e una call to action animata. La cartella deve avere le voci per ogni lingua selezionata.</p>
          </>}
          <button className="cs-tool-btn" disabled={!pipelineLanguages.length || (includeSigla && !siglaAssetsDir.trim())}
                  title="Avvia tutti i passaggi e crea un MP4 con tracce audio e sottotitoli selezionabili"
                  onClick={() => onJob('restore_pipeline', { item_id: item.id, output_height: height,
                    languages: pipelineLanguages, make_music: makeMusic, preserve_source_audio: preserveSourceAudio,
                    music_style: style.trim() || undefined, output_dir: outputDir.trim() || undefined,
                    include_sigla: includeSigla, sigla_assets_dir: includeSigla ? siglaAssetsDir.trim() : undefined,
                    sigla_cta_language: ctaLanguage })}>
            <Languages size={14} /> Avvia pipeline completa
          </button>
        </div>
      )}
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" title="Polvere, sfarfallio e tremolio del proiettore: da fare sul bianco e nero, prima del colore"
                onClick={() => onJob('restore_clean', { item_id: item.id })}>
          <Sparkles size={14} /> Pulisci pellicola
        </button>
        <button className="cs-tool-btn" title="Toglie la tinta e colora con DDColor; lascia originali le scene gia' a colori, tiene blu le notti virate, cartelli in grigio (leggi prima i testi)"
                onClick={() => onJob('recolor', { item_id: item.id })}>
          <Palette size={14} /> Ricolora
        </button>
        <select className="cs-inline-input" value={height} onChange={e => setHeight(Number(e.target.value))}>
        {[1080, 1440, 2160].map(h => <option key={h} value={h}>{h} linee</option>)}
        </select>
        <button className="cs-tool-btn" title="Real-ESRGAN: nuova versione ingrandita"
                onClick={() => onJob('upscale', { item_id: item.id, height })}>
          <Maximize2 size={14} /> Ingrandisci
        </button>
      </div>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" title="Trova didascalie e pagine scritte, le legge e decide chi le pronuncia"
                onClick={() => onJob('restore_read', { item_id: item.id })}>
          <ScanText size={14} /> Leggi i testi
        </button>
        <select className="cs-inline-input" value={language} onChange={e => setLanguage(e.target.value)}>
          {LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
        <button className="cs-tool-btn" disabled={!cards.length} title="Una voce per personaggio, sulla traccia voce"
                onClick={() => onJob('restore_narrate', { item_id: item.id, language })}>
          <Mic size={14} /> Narra
        </button>
      </div>
      <div className="cs-ed-actions">
        <span className="cs-hint">Usa il tema musicale impostato sopra; l'atmosfera viene analizzata scena per scena.</span>
        <button className="cs-tool-btn"
                title="Un brano per sequenza; con atmosfere gia' salvate rifa' solo i brani delle sequenze corrette"
                onClick={() => onJob('restore_score', { item_id: item.id, style, redescribe })}>
          <Music size={14} /> Colonna sonora
        </button>
      </div>
      {(state?.moods || []).length > 0 && (
        <>
          <label className="cs-ed-inline">
            <input type="checkbox" checked={redescribe} onChange={e => setRedescribe(e.target.checked)} />
            Rifai da capo le atmosfere (perde le correzioni)
          </label>
          <p className="cs-hint">Atmosfera di ogni sequenza: correggi quelle sbagliate, poi "Colonna sonora" rifa' solo quei brani.</p>
          <div className="cs-ed-cards">
            {state.moods.map((m, i) => <MoodRow key={`${i}-${m.start}`} mood={m} index={i} onSave={saveMood} />)}
          </div>
        </>
      )}
      <ProtectSection color={state?.color} onSave={saveProtect} />
      {error && <p className="cs-prod-error">{error}</p>}
      {cards.length > 0 && (
        <>
          <p className="cs-hint">
            {state.titles} didascalie e {state.pages} pagine trovate, {cards.filter(c => !c.deleted).length} testi da leggere,
            {' '}{cards.filter(c => c.needs_review && !c.deleted).length} da rivedere. Il cast automatico sbaglia spesso
            chi dice una battuta: correggi testo o personaggio, poi rifai la narrazione.
          </p>
          {voices.length > 0 && (
            <p className="cs-hint">Voci: {voices.map(([sp, v]) => `${sp} → ${v.voice}`).join(' · ')}</p>
          )}
          <div className="cs-ed-cards">
            {cards.map((c, i) => <CardRow key={`${i}-${c.start}`} card={c} index={i} onSave={save} />)}
          </div>
        </>
      )}
    </div>
  );
}
