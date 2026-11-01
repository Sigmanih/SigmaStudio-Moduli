import React, { useEffect, useState } from 'react';
import { Trash2, Type } from 'lucide-react';

/*
 * Testi sovrapposti al video: titolo centrale, sottopancia, didascalia.
 *
 * L'anteprima e' HTML sopra il player; l'export imprime nel video PNG disegnati
 * con le stesse proporzioni (media_import.render_text), cosi' quello che si
 * vede qui e' quello che esce nel file.
 */

export const STYLE_LABEL = { lower: 'Sottopancia', caption: 'Didascalia', title: 'Titolo al centro' };

export function OverlayLayer({ overlays, time }) {
  const visible = (overlays || []).filter(o => time >= o.start && time < o.end);
  if (!visible.length) return null;
  return (
    <div className="cs-ed-ovl-layer" aria-hidden="true">
      {visible.map(o => {
        const fade = Math.min(0.3, (o.end - o.start) / 3);
        const opacity = Math.min(1, (time - o.start) / fade, (o.end - time) / fade);
        return (
          <div key={o.id} className={`cs-ed-ovl ${o.style}`} style={{ opacity }}>
            <div className="cs-ed-ovl-box">
              <span className="cs-ed-ovl-text">{o.text}</span>
              {o.sub && <span className="cs-ed-ovl-sub">{o.sub}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function OverlayInspector({ overlay, onOp }) {
  const [text, setText] = useState(overlay.text);
  const [sub, setSub] = useState(overlay.sub || '');
  useEffect(() => { setText(overlay.text); setSub(overlay.sub || ''); }, [overlay.id, overlay.text, overlay.sub]);
  const save = (fields) => onOp('overlay_update', { overlay_id: overlay.id, ...fields });
  return (
    <>
      <h4><Type size={14} /> Testo sovrapposto <span className="cs-prod-status">{(overlay.end - overlay.start).toFixed(1)} s</span></h4>
      <div className="cs-prod-row">
        {Object.entries(STYLE_LABEL).map(([style, label]) => (
          <button key={style} className={`cs-prod-chip ${overlay.style === style ? 'on' : ''}`}
                  onClick={() => save({ style })}>{label}</button>
        ))}
      </div>
      <label className="cs-ed-field">Testo
        <textarea className="cs-textarea" rows={2} value={text} onChange={e => setText(e.target.value)}
                  onBlur={() => text.trim() && text !== overlay.text && save({ text })} />
      </label>
      {overlay.style !== 'caption' && (
        <label className="cs-ed-field">Seconda riga
          <input className="cs-inline-input cs-prod-wide" value={sub} placeholder="Es. ruolo, luogo, data"
                 onChange={e => setSub(e.target.value)} onBlur={() => sub !== (overlay.sub || '') && save({ sub })} />
        </label>
      )}
      <div className="cs-inline-params">
        <label>Da (s)
          <input type="number" step="0.1" min="0" defaultValue={overlay.start.toFixed(2)} key={`a${overlay.id}${overlay.start}`}
                 onBlur={e => save({ start: Number(e.target.value) })} />
        </label>
        <label>A (s)
          <input type="number" step="0.1" min="0" defaultValue={overlay.end.toFixed(2)} key={`b${overlay.id}${overlay.end}`}
                 onBlur={e => save({ end: Number(e.target.value) })} />
        </label>
      </div>
      <p className="cs-hint">Trascina il testo sulla traccia "Testi" per spostarlo, il bordo destro per allungarlo.</p>
      <button className="cs-tool-btn active" onClick={() => onOp('overlay_delete', { overlay_id: overlay.id })}>
        <Trash2 size={14} /> Elimina testo
      </button>
    </>
  );
}
