import React, { useEffect, useState } from 'react';
import { OverlayInspector } from './Overlays';
import RestorationPanel from './Restoration';
import {
  Scissors, Trash2, Copy, ArrowLeft, ArrowRight, Wand2, RefreshCw, FastForward, PlusSquare, Music,
  Volume2, CheckCircle2, Eye,
} from 'lucide-react';

/*
 * Pannello della selezione: un elemento video, un tratto della timeline o una
 * clip audio. Le operazioni manuali passano da onOp (immediate, annullabili);
 * quelle con AI da onJob (in coda, possono durare minuti).
 */

function ItemInspector({ pid, data, item, index, time, onOp, onJob }) {
  const shot = data.shots[item.shot_id] || { takes: [] };
  const [prompt, setPrompt] = useState(item.prompt || '');
  const [seconds, setSeconds] = useState(4);
  useEffect(() => { setPrompt(item.prompt || ''); }, [item.id, item.prompt]);
  const inside = time > item.start + 0.05 && time < item.end - 0.05;
  const active = shot.takes.find(t => t.id === item.take_id);
  const verdict = active?.judge;
  return (
    <>
      <h4>Elemento {index + 1} <span className="cs-prod-status">{typeof item.scene === 'string' ? item.scene : ''} · {item.duration.toFixed(2)} s</span></h4>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" disabled={!inside} title="S" onClick={() => onOp('split', { t: time })}><Scissors size={14} /> Dividi qui</button>
        <button className="cs-tool-btn" onClick={() => onOp('duplicate', { item_id: item.id })}><Copy size={14} /> Duplica</button>
        <button className="cs-tool-btn" disabled={index === 0} onClick={() => onOp('move', { item_id: item.id, index: index - 1 })}><ArrowLeft size={14} /></button>
        <button className="cs-tool-btn" disabled={index === data.items.length - 1} onClick={() => onOp('move', { item_id: item.id, index: index + 1 })}><ArrowRight size={14} /></button>
        <button className="cs-tool-btn active" title="Canc" onClick={() => onOp('delete', { item_id: item.id })}><Trash2 size={14} /> Elimina</button>
      </div>
      <label className="cs-ed-field">Transizione in entrata
        <div className="cs-prod-row">
          {['cut', 'fade', 'dip'].map(type => (
            <button key={type} className={`cs-prod-chip ${item.transition?.type === type ? 'on' : ''}`}
                    disabled={index === 0 && type === 'fade'}
                    onClick={() => onOp('transition', { item_id: item.id, type, duration: 0.6 })}>
              {{ cut: 'taglio', fade: 'dissolvenza', dip: 'al nero' }[type]}
            </button>
          ))}
        </div>
      </label>
      {shot.takes.length > 1 && (
        <label className="cs-ed-field">Versioni
          <div className="cs-ed-takes">
            {shot.takes.map(t => (
              <button key={t.id} className={`cs-prod-chip ${item.take_id === t.id ? 'on' : ''}`} title={t.prompt}
                      onClick={() => onOp('set_take', { item_id: item.id, take_id: t.id })}>
                {item.take_id === t.id && <CheckCircle2 size={11} />} {t.id} · {t.kind || 'render'}
                {t.judge?.score != null && ` · ${Math.round(t.judge.score * 100)}%`}
              </button>
            ))}
          </div>
        </label>
      )}
      {verdict && (
        <div className={`cs-ed-judge ${verdict.score >= 0.6 ? 'ok' : 'bad'}`}>
          <Eye size={13} /> Giudice: {Math.round(verdict.score * 100)}% — {verdict.seen}
          {verdict.issues?.length > 0 && <ul>{verdict.issues.map((x, k) => <li key={k}>{x}</li>)}</ul>}
        </div>
      )}
      {shot.origin !== 'title' && (
        // Ogni passo crea una versione o clip audio annullabili: l'originale resta fra le Versioni.
        <RestorationPanel pid={pid} item={item} refresh={data} onJob={onJob} />
      )}
      {shot.origin === 'scene' ? (
        <>
          <label className="cs-ed-field">Cosa mostra la scena
            <textarea className="cs-textarea" rows={3} value={prompt} onChange={e => setPrompt(e.target.value)} />
          </label>
          <button className="cs-tool-btn" disabled={!prompt.trim()}
                  title="Ricrea la scena con la stessa durata: la voce narrante resta allineata"
                  onClick={() => onJob('scene_redo', { item_id: item.id, description: prompt })}>
            <RefreshCw size={14} /> Rifai la scena
          </button>
        </>
      ) : ['import', 'title'].includes(shot.origin) ? (
        <p className="cs-hint">
          {{ title: 'Cartello di testo.', scene: 'Scena didattica.', import: 'Media importato.' }[shot.origin]} Puoi dividerlo, accorciarlo trascinando i bordi,
          spostarlo o aggiungere una transizione. Per cambiare il testo crea un nuovo cartello.
        </p>
      ) : (<>
      <label className="cs-ed-field">Descrizione
        <textarea className="cs-textarea" rows={3} value={prompt} onChange={e => setPrompt(e.target.value)} />
      </label>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" disabled={!prompt.trim()} onClick={() => onJob('redo', { item_id: item.id, prompt })}>
          <RefreshCw size={14} /> Rifai (nuova versione)
        </button>
        <label className="cs-ed-inline">s
          <input type="number" min="1" max="15" step="0.5" value={seconds} onChange={e => setSeconds(Number(e.target.value))} />
        </label>
        <button className="cs-tool-btn" disabled={!prompt.trim()} onClick={() => onJob('extend', { item_id: item.id, prompt, seconds })}>
          <FastForward size={14} /> Estendi dopo
        </button>
        <button className="cs-tool-btn" disabled={!prompt.trim()} onClick={() => onJob('insert', { index, prompt, seconds })}>
          <PlusSquare size={14} /> Inserisci prima
        </button>
      </div>
      </>)}
    </>
  );
}

function RangeInspector({ range, onOp, onJob, onClear }) {
  const [prompt, setPrompt] = useState('');
  const [tags, setTags] = useState('');
  return (
    <>
      <h4>Tratto {range.a.toFixed(2)} → {range.b.toFixed(2)} s <span className="cs-prod-status">({(range.b - range.a).toFixed(2)} s)</span></h4>
      <label className="cs-ed-field">Cosa deve succedere in questo tratto
        <textarea className="cs-textarea" rows={3} value={prompt} onChange={e => setPrompt(e.target.value)}
                  placeholder="Es. un'onda gigante travolge la barca, poi il mare si calma" />
      </label>
      <p className="cs-hint">Il tratto nuovo parte dal fotogramma in {range.a.toFixed(2)} s e arriva a quello in {range.b.toFixed(2)} s: si aggancia ai due lati senza salti.</p>
      <div className="cs-ed-actions">
        <button className="cs-tool-btn" disabled={!prompt.trim() || range.b - range.a < 0.5}
                onClick={() => { onJob('regen_range', { t_a: range.a, t_b: range.b, prompt }); onClear(); }}>
          <Wand2 size={14} /> Rigenera il tratto
        </button>
        <button className="cs-tool-btn active" onClick={() => { onOp('delete_range', { t_a: range.a, t_b: range.b }); onClear(); }}>
          <Trash2 size={14} /> Taglia via il tratto
        </button>
      </div>
      <label className="cs-ed-field">Musica per il tratto
        <input className="cs-inline-input cs-prod-wide" value={tags} onChange={e => setTags(e.target.value)}
               placeholder="Genere e strumenti (vuoto = stile della produzione)" />
      </label>
      <button className="cs-tool-btn" onClick={() => onJob('music_range', { t_a: range.a, t_b: range.b, tags })}>
        <Music size={14} /> Componi musica
      </button>
    </>
  );
}

function AudioInspector({ clip, track, onOp }) {
  return (
    <>
      <h4>{clip.label || 'Clip audio'} <span className="cs-prod-status">{track.name}</span></h4>
      {clip.meta?.text && (
        <p className="cs-hint">
          «{clip.meta.text}»{clip.meta.heard ? ` · sentito: «${clip.meta.heard}»` : ''}
          {clip.meta.match != null ? ` · corrispondenza ${(clip.meta.match * 100).toFixed(0)}%` : ''}
        </p>
      )}
      {(clip.meta?.damaged?.length > 0 || clip.meta?.audio_issues?.length > 0) && (
        <p className="cs-prod-error">
          Difetti rimasti dopo i tentativi: {[...(clip.meta.damaged || []).map(w => `«${w}» poco chiara`),
            ...(clip.meta.audio_issues || [])].join(' · ')}. Rigenera la battuta o cambia la voce.
        </p>
      )}
      <div className="cs-inline-params">
        <label>Inizio (s)
          <input type="number" step="0.1" min="0" defaultValue={clip.start.toFixed(2)} key={`s${clip.id}${clip.start}`}
                 onBlur={e => onOp('audio_update', { clip_id: clip.id, start: Number(e.target.value) })} />
        </label>
        <label>Volume (dB)
          <input type="number" step="1" min="-40" max="12" defaultValue={clip.gain_db} key={`g${clip.id}${clip.gain_db}`}
                 onBlur={e => onOp('audio_update', { clip_id: clip.id, gain_db: Number(e.target.value) })} />
        </label>
      </div>
      <div className="cs-inline-params">
        <label>Entra in (s)
          <input type="number" step="0.1" min="0" defaultValue={clip.fade_in || 0} key={`fi${clip.id}${clip.fade_in}`}
                 onBlur={e => onOp('audio_update', { clip_id: clip.id, fade_in: Number(e.target.value) })} />
        </label>
        <label>Esce in (s)
          <input type="number" step="0.1" min="0" defaultValue={clip.fade_out || 0} key={`fo${clip.id}${clip.fade_out}`}
                 onBlur={e => onOp('audio_update', { clip_id: clip.id, fade_out: Number(e.target.value) })} />
        </label>
      </div>
      <div className="cs-prod-row">
        {[['Dissolvenza morbida', 1.5, 2.5], ['Breve', 0.3, 0.5], ['Nessuna', 0, 0]].map(([label, a, b]) => (
          <button key={label} className="cs-prod-chip" onClick={() => onOp('audio_update', { clip_id: clip.id, fade_in: a, fade_out: b })}>{label}</button>
        ))}
      </div>
      <audio className="cs-ed-audio" src={clip.url} controls />
      <button className="cs-tool-btn active" onClick={() => onOp('audio_delete', { clip_id: clip.id })}><Trash2 size={14} /> Elimina clip</button>
    </>
  );
}

export default function Inspector({ pid, data, selection, time, onOp, onJob, onClear }) {
  if (!selection) {
    return (
      <div className="cs-ed-inspector">
        <p className="cs-hint"><Volume2 size={13} /> Seleziona un elemento, una clip audio, oppure trascina sul righello per scegliere un tratto.</p>
        <p className="cs-hint">Scorciatoie: Spazio riproduci · S dividi · Canc elimina · Ctrl+Z / Ctrl+Y</p>
      </div>
    );
  }
  let body = null;
  if (selection.type === 'item') {
    const index = data.items.findIndex(it => it.id === selection.id);
    if (index >= 0) body = <ItemInspector pid={pid} data={data} item={data.items[index]} index={index} time={time} onOp={onOp} onJob={onJob} />;
  } else if (selection.type === 'range') {
    body = <RangeInspector range={selection} onOp={onOp} onJob={onJob} onClear={onClear} />;
  } else if (selection.type === 'overlay') {
    const overlay = (data.timeline.overlays || []).find(o => o.id === selection.id);
    if (overlay) body = <OverlayInspector overlay={overlay} onOp={onOp} />;
  } else if (selection.type === 'audio') {
    for (const track of data.timeline.audio) {
      const clip = track.clips.find(c => c.id === selection.id);
      if (clip) body = <AudioInspector clip={clip} track={track} onOp={onOp} />;
    }
  }
  return <div className="cs-ed-inspector">{body || <p className="cs-hint">Selezione non piu' presente.</p>}</div>;
}
