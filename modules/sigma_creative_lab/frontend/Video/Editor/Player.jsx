import React, { useEffect, useImperativeHandle, useRef, forwardRef } from 'react';

/*
 * Anteprima della timeline senza ricodifica.
 *
 * Due <video> si alternano: mentre uno riproduce l'elemento corrente, l'altro
 * ha gia' caricato il successivo, cosi' il passaggio fra clip non ha pause.
 * Le tracce audio (dialoghi, voce, musica, effetti) sono AudioBuffer di
 * WebAudio programmati all'istante giusto. Le dissolvenze si vedono solo
 * nell'export: qui ogni passaggio e' un taglio.
 */

const EPS = 1 / 48;

function itemAt(items, t) {
  for (let i = 0; i < items.length; i += 1) {
    if (t >= items[i].start - EPS && t < items[i].end - EPS) return i;
  }
  return items.length ? items.length - 1 : -1;
}

const Player = forwardRef(function Player({ items, audioTracks, mediaFor, clipTrack, onTime, onEnded }, ref) {
  const videos = [useRef(null), useRef(null)];
  const state = useRef({ active: 0, index: -1, playing: false, raf: 0, t: 0 });
  const audio = useRef({ ctx: null, buffers: {}, sources: [] });

  const srcFor = (it) => (mediaFor(it.id)?.scrub_url) || it.clip_url;

  const load = (slot, index, srcTime) => {
    const v = videos[slot].current;
    const it = items[index];
    if (!v || !it) return;
    const src = srcFor(it);
    if (v.dataset.src !== src) {
      v.dataset.src = src;
      v.src = src;
    }
    v.dataset.index = String(index);
    const go = () => { v.currentTime = srcTime; };
    if (v.readyState >= 1) go(); else v.addEventListener('loadedmetadata', go, { once: true });
  };

  // La visibilita' si imposta qui e non con gli eventi play/seeked: dopo un
  // salto a video fermo quegli eventi possono non arrivare e restava visibile
  // il video sbagliato (o nessuno).
  const show = (slot) => {
    videos.forEach((r, j) => { if (r.current) r.current.style.visibility = j === slot ? 'visible' : 'hidden'; });
  };

  const applyClipVolume = () => {
    const gain = clipTrack?.mute ? 0 : Math.min(1, Math.pow(10, (clipTrack?.gain_db || 0) / 20));
    videos.forEach(r => { if (r.current) r.current.volume = gain; });
  };

  // --- audio delle tracce ---------------------------------------------------
  const ensureAudio = async () => {
    const a = audio.current;
    if (!a.ctx) a.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const wanted = [];
    (audioTracks || []).forEach(tr => (tr.kind !== 'clip' ? tr.clips : []).forEach(c => wanted.push(c)));
    await Promise.all(wanted.map(async c => {
      if (a.buffers[c.url]) return;
      try {
        const data = await (await fetch(c.url)).arrayBuffer();
        a.buffers[c.url] = await a.ctx.decodeAudioData(data);
      } catch { a.buffers[c.url] = null; }
    }));
  };

  const stopAudio = () => {
    audio.current.sources.forEach(s => { try { s.stop(); } catch { /* gia' fermo */ } });
    audio.current.sources = [];
  };

  const startAudio = (t0) => {
    const a = audio.current;
    if (!a.ctx) return;
    stopAudio();
    const now = a.ctx.currentTime + 0.05;
    (audioTracks || []).forEach(tr => {
      if (tr.kind === 'clip' || tr.mute) return;
      tr.clips.forEach(c => {
        const buf = a.buffers[c.url];
        if (!buf) return;
        const len = c.src_out - c.src_in;
        const clipEnd = c.start + len;
        if (clipEnd <= t0) return;
        const offsetInClip = Math.max(0, t0 - c.start);
        const src = a.ctx.createBufferSource();
        src.buffer = buf;
        const g = a.ctx.createGain();
        const level = Math.pow(10, ((tr.gain_db || 0) + (c.gain_db || 0)) / 20);
        const at = now + Math.max(0, c.start - t0);
        const playLen = len - offsetInClip;
        // Dissolvenze della clip: stesse durate che l'export applica con afade.
        const fi = Math.max(0, c.fade_in || 0);
        const fo = Math.max(0, c.fade_out || 0);
        g.gain.setValueAtTime(fi > offsetInClip ? level * (offsetInClip / fi) : level, at);
        if (fi > offsetInClip) g.gain.linearRampToValueAtTime(level, at + (fi - offsetInClip));
        if (fo > 0 && playLen > fo) {
          g.gain.setValueAtTime(level, at + playLen - fo);
          g.gain.linearRampToValueAtTime(0.0001, at + playLen);
        }
        src.connect(g).connect(a.ctx.destination);
        src.start(at, c.src_in + offsetInClip, playLen);
        a.sources.push(src);
      });
    });
  };

  // --- riproduzione -------------------------------------------------------
  const tick = () => {
    const s = state.current;
    const v = videos[s.active].current;
    const it = items[s.index];
    if (!v || !it) return;
    const t = it.start + (v.currentTime - it.src_in);
    s.t = t;
    onTime?.(t);
    // Un file piu' corto della fine dichiarata (es. audio rimontato) finisce
    // prima di src_out: senza `ended` il player aspettava per sempre.
    const end = Math.min(it.src_out, Number.isFinite(v.duration) ? v.duration : it.src_out);
    if (v.ended || v.currentTime >= end - EPS) {
      const next = s.index + 1;
      if (next >= items.length) {
        pause();
        onEnded?.();
        return;
      }
      const other = 1 - s.active;
      const nv = videos[other].current;
      if (Number(nv.dataset.index) !== next) load(other, next, items[next].src_in);
      v.pause();
      s.active = other;
      s.index = next;
      show(other);
      nv.play().catch(() => {});
      preload(next + 1);
    } else if (v.paused && v.readyState >= 2) {
      // In riproduzione ma fermo (salto, buffer esaurito): si riprende.
      v.play().catch(() => {});
    }
  };

  const preload = (index) => {
    if (index < items.length) load(1 - state.current.active, index, items[index].src_in);
  };

  const seek = (t) => {
    const s = state.current;
    const index = itemAt(items, t);
    if (index < 0) return;
    const it = items[index];
    const srcTime = it.src_in + Math.max(0, Math.min(t - it.start, it.duration - EPS));
    s.index = index;
    videos[1 - s.active].current?.pause();
    load(s.active, index, srcTime);
    show(s.active);
    s.t = t;
    onTime?.(t);
    preload(index + 1);
    if (s.playing) {
      const v = videos[s.active].current;
      const resume = () => v.play().catch(() => {});
      if (v.readyState >= 2) resume(); else v.addEventListener('canplay', resume, { once: true });
      startAudio(t);
    }
  };

  const play = async () => {
    const s = state.current;
    if (!items.length) return;
    await ensureAudio();
    if (audio.current.ctx?.state === 'suspended') await audio.current.ctx.resume();
    if (s.index < 0) seek(s.t || 0);
    applyClipVolume();
    s.playing = true;
    await videos[s.active].current.play().catch(() => {});
    startAudio(s.t);
    // Un timer e non requestAnimationFrame: con la finestra in secondo piano
    // rAF si ferma mentre il video continua, e il passaggio al clip successivo
    // non avverrebbe piu'. Il timer in background rallenta ma non si ferma.
    clearInterval(s.raf);
    s.raf = setInterval(tick, 33);
  };

  const pause = () => {
    const s = state.current;
    s.playing = false;
    clearInterval(s.raf);
    videos.forEach(r => r.current?.pause());
    stopAudio();
  };

  useImperativeHandle(ref, () => ({
    play, pause, seek,
    toggle: () => (state.current.playing ? pause() : play()),
    isPlaying: () => state.current.playing,
    time: () => state.current.t,
  }));

  // Timeline cambiata (taglio, nuova versione): si riposiziona dove si era.
  useEffect(() => {
    const s = state.current;
    const wasPlaying = s.playing;
    pause();
    s.index = -1;
    if (items.length) seek(Math.min(s.t, items[items.length - 1].end - EPS));
    if (wasPlaying) play();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, audioTracks]);

  useEffect(applyClipVolume);
  useEffect(() => () => { pause(); audio.current.ctx?.close?.(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="cs-ed-player">
      {[0, 1].map(k => (
        <video key={k} ref={videos[k]} playsInline preload="auto"
               style={{ visibility: state.current.active === k ? 'visible' : 'hidden' }}
               onPlay={() => show(state.current.active)}
               onSeeked={() => show(state.current.active)} />
      ))}
      {!items.length && <div className="cs-ed-empty">Timeline vuota: genera le inquadrature dalla scheda Produzioni.</div>}
    </div>
  );
});

export default Player;
