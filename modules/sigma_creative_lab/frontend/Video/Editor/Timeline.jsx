import React, { useRef, useState } from 'react';

/*
 * Timeline: righello, traccia video con miniature, tracce audio con forme d'onda.
 *
 * - click sul righello o sulle tracce: sposta il cursore;
 * - trascinamento sul righello: seleziona un intervallo (per rigenerare, tagliare, musica);
 * - click su un elemento o su una clip audio: lo seleziona;
 * - trascinamento dei bordi di un elemento: trim.
 * Le modifiche vere le fa il server (onOp): qui si disegna e si raccolgono i gesti.
 */

const TRACK_H = { video: 64, audio: 40, text: 26 };
const HEADER_W = 132;

function fmt(t) {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

function Waveform({ peaks, width, height, offsetS = 0, lengthS }) {
  if (!peaks?.peaks?.length || width <= 0) return null;
  const per = peaks.per_s;
  const from = Math.floor(offsetS * per);
  const to = Math.min(peaks.peaks.length, Math.ceil((offsetS + lengthS) * per));
  const slice = peaks.peaks.slice(from, to);
  if (!slice.length) return null;
  const step = Math.max(1, Math.floor(slice.length / Math.max(1, width / 2)));
  const pts = [];
  for (let i = 0; i < slice.length; i += step) {
    const x = (i / slice.length) * width;
    const h = Math.max(1, slice[i] * (height - 4));
    pts.push(`M${x.toFixed(1)},${((height - h) / 2).toFixed(1)}v${h.toFixed(1)}`);
  }
  return (
    <svg className="cs-ed-wave" width={width} height={height} aria-hidden="true">
      <path d={pts.join('')} />
    </svg>
  );
}

export default function Timeline({ data, media, time, selection, zoom, onSeek, onSelect, onOp }) {
  const ref = useRef(null);
  const [drag, setDragState] = useState(null);   // {kind: 'range'|'trim'|'move'|'resize', ...}
  // Copia sempre aggiornata: con un gesto rapido mousemove e mouseup arrivano
  // prima che React abbia ridisegnato, e leggendo lo stato si perdeva lo spostamento.
  const dragRef = useRef(null);
  const setDrag = (d) => { dragRef.current = d; setDragState(d); };
  const pxPerS = 40 * zoom;
  const duration = Math.max(data.duration, 1);
  const width = duration * pxPerS + 80;

  const tAt = (clientX) => {
    const rect = ref.current.getBoundingClientRect();
    return Math.max(0, Math.min(duration, (clientX - rect.left + ref.current.scrollLeft - HEADER_W) / pxPerS));
  };

  const onRulerDown = (e) => {
    const t = tAt(e.clientX);
    setDrag({ kind: 'range', a: t, b: t });
    onSeek(t);
  };

  const onMove = (e) => {
    const drag = dragRef.current;
    if (!drag) return;
    const t = tAt(e.clientX);
    if (drag.kind === 'range') setDrag({ ...drag, b: t });
    if (drag.kind === 'trim' || drag.kind === 'move' || drag.kind === 'resize') setDrag({ ...drag, t });
  };

  const onUp = (e) => {
    let drag = dragRef.current;
    if (!drag) return;
    // La posizione finale viene dal rilascio, non dall'ultimo mousemove visto.
    if (e?.clientX !== undefined && drag.kind !== 'range') drag = { ...drag, t: tAt(e.clientX) };
    if (e?.clientX !== undefined && drag.kind === 'range') drag = { ...drag, b: tAt(e.clientX) };
    if (drag.kind === 'range' && Math.abs(drag.b - drag.a) > 0.25) {
      onSelect({ type: 'range', a: Math.min(drag.a, drag.b), b: Math.max(drag.a, drag.b) });
    }
    // Spostamento di clip audio e testi trascinandoli; il bordo destro di un testo ne cambia la durata.
    if (drag.kind === 'move' && drag.t !== undefined && Math.abs(drag.t - drag.grab) > 0.05) {
      const start = Math.max(0, drag.start + drag.t - drag.grab);
      if (drag.target === 'audio') onOp('audio_update', { clip_id: drag.id, start });
      else onOp('overlay_update', { overlay_id: drag.id, start, end: start + drag.length });
    }
    if (drag.kind === 'resize' && drag.t !== undefined && Math.abs(drag.t - drag.end) > 0.05) {
      onOp('overlay_update', { overlay_id: drag.id, end: Math.max(drag.start + 0.3, drag.t) });
    }
    const trimDelta = drag.kind === 'trim' && drag.t !== undefined
      ? drag.t - (drag.edge === 'in' ? drag.item.start : drag.item.end) : 0;
    if (drag.kind === 'trim' && Math.abs(trimDelta) > 0.02) {
      const it = drag.item;
      const delta = trimDelta;
      const args = drag.edge === 'in' ? { src_in: it.src_in + delta } : { src_out: it.src_out + delta };
      onOp('trim', { item_id: it.id, ...args });
    }
    setDrag(null);
  };

  const ticks = [];
  const every = zoom >= 2 ? 1 : zoom >= 0.75 ? 2 : 5;
  for (let t = 0; t <= duration; t += every) ticks.push(t);
  const range = drag?.kind === 'range' ? { a: Math.min(drag.a, drag.b), b: Math.max(drag.a, drag.b) }
    : selection?.type === 'range' ? selection : null;

  return (
    <div className="cs-ed-timeline" ref={ref} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
      <div className="cs-ed-tl-inner" style={{ width: width + HEADER_W }}>
        <div className="cs-ed-ruler" onMouseDown={onRulerDown}>
          <div className="cs-ed-track-head">{fmt(time)} / {fmt(data.duration)}</div>
          {ticks.map(t => (
            <span key={t} className="cs-ed-tick" style={{ left: HEADER_W + t * pxPerS }}>{fmt(t)}</span>
          ))}
          {(data.timeline.markers || []).map(m => (
            <span key={m.id} className="cs-ed-marker" title={m.label} style={{ left: HEADER_W + m.t * pxPerS }} />
          ))}
        </div>

        <div className="cs-ed-track text" style={{ height: TRACK_H.text }}>
          <div className="cs-ed-track-head">Testi</div>
          {(data.timeline.overlays || []).map(o => {
            const moving = drag?.id === o.id && drag.t !== undefined;
            const start = moving && drag.kind === 'move' ? Math.max(0, o.start + drag.t - drag.grab) : o.start;
            const end = moving && drag.kind === 'resize' ? Math.max(o.start + 0.3, drag.t) : start + (o.end - o.start);
            const sel = selection?.type === 'overlay' && selection.id === o.id;
            return (
              <div key={o.id} className={`cs-ed-ovl-clip ${sel ? 'sel' : ''}`} title={o.text}
                   style={{ left: HEADER_W + start * pxPerS, width: Math.max(6, (end - start) * pxPerS) }}
                   onMouseDown={e => {
                     e.stopPropagation();
                     onSelect({ type: 'overlay', id: o.id });
                     setDrag({ kind: 'move', target: 'overlay', id: o.id, grab: tAt(e.clientX), start: o.start, length: o.end - o.start });
                   }}>
                <span className="cs-ed-item-label">{o.text}</span>
                <span className="cs-ed-handle out" onMouseDown={e => {
                  e.stopPropagation(); onSelect({ type: 'overlay', id: o.id });
                  setDrag({ kind: 'resize', id: o.id, start: o.start, end: o.end });
                }} />
              </div>
            );
          })}
        </div>

        <div className="cs-ed-track" style={{ height: TRACK_H.video }}>
          <div className="cs-ed-track-head">Video</div>
          {data.items.map((it, k) => {
            const m = media[it.id];
            const left = HEADER_W + it.start * pxPerS;
            const w = Math.max(4, it.duration * pxPerS - 1);
            const sel = selection?.type === 'item' && selection.id === it.id;
            const thumbs = m?.thumbs;
            return (
              <div key={it.id} className={`cs-ed-item ${sel ? 'sel' : ''}`} style={{ left, width: w }}
                   title={`${k + 1}. ${it.prompt}`}
                   onMouseDown={e => { e.stopPropagation(); onSelect({ type: 'item', id: it.id }); onSeek(tAt(e.clientX)); }}>
                {thumbs && (
                  <div className="cs-ed-thumbs" style={{
                    backgroundImage: `url(${thumbs.url})`,
                    backgroundSize: `${thumbs.width * thumbs.count}px ${thumbs.height}px`,
                    backgroundPositionX: `${-(it.src_in / thumbs.every_s) * thumbs.width}px`,
                  }} />
                )}
                {it.transition?.type !== 'cut' && <span className="cs-ed-trans">{it.transition.type}</span>}
                <span className="cs-ed-item-label">{k + 1}{it.takes > 1 ? ` · v${it.takes}` : ''}</span>
                {sel && ['in', 'out'].map(edge => (
                  <span key={edge} className={`cs-ed-handle ${edge}`}
                        onMouseDown={e => { e.stopPropagation(); setDrag({ kind: 'trim', item: it, edge }); }} />
                ))}
              </div>
            );
          })}
        </div>

        {data.timeline.audio.map(track => (
          <div key={track.id} className={`cs-ed-track audio ${track.mute ? 'muted' : ''}`} style={{ height: TRACK_H.audio }}>
            <div className="cs-ed-track-head">
              <span>{track.name}</span>
              <button className={`cs-ed-mini ${track.mute ? 'on' : ''}`} title="Muto"
                      onClick={() => onOp('track', { track_id: track.id, mute: !track.mute })}>M</button>
            </div>
            {track.kind === 'clip'
              ? data.items.map(it => (
                  <div key={it.id} className="cs-ed-aclip clip" style={{ left: HEADER_W + it.start * pxPerS, width: Math.max(2, it.duration * pxPerS - 1) }}>
                    <Waveform peaks={media[it.id]?.peaks} width={Math.max(2, it.duration * pxPerS - 1)} height={TRACK_H.audio - 4}
                              offsetS={it.src_in} lengthS={it.duration} />
                  </div>
                ))
              : track.clips.map(c => {
                  const len = c.src_out - c.src_in;
                  const sel = selection?.type === 'audio' && selection.id === c.id;
                  const moving = drag?.kind === 'move' && drag.id === c.id && drag.t !== undefined;
                  const start = moving ? Math.max(0, c.start + drag.t - drag.grab) : c.start;
                  return (
                    <div key={c.id} className={`cs-ed-aclip ${track.kind} ${sel ? 'sel' : ''}`} title={`${c.label} — trascina per spostare`}
                         style={{ left: HEADER_W + start * pxPerS, width: Math.max(4, len * pxPerS) }}
                         onMouseDown={e => {
                           e.stopPropagation();
                           onSelect({ type: 'audio', id: c.id });
                           setDrag({ kind: 'move', target: 'audio', id: c.id, grab: tAt(e.clientX), start: c.start });
                         }}>
                      <Waveform peaks={media[c.id]?.peaks} width={Math.max(4, len * pxPerS)} height={TRACK_H.audio - 4}
                                offsetS={c.src_in} lengthS={len} />
                      <span className="cs-ed-item-label">{c.label}</span>
                    </div>
                  );
                })}
          </div>
        ))}

        {range && (
          <div className="cs-ed-range" style={{ left: HEADER_W + range.a * pxPerS, width: (range.b - range.a) * pxPerS }} />
        )}
        <div className="cs-ed-playhead" style={{ left: HEADER_W + time * pxPerS }} />
      </div>
    </div>
  );
}
