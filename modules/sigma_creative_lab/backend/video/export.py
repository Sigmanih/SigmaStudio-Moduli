"""Export della timeline in un unico MP4.

Tre passaggi, ognuno riprendibile e con pochi ingressi per comando ffmpeg:

1. **segmenti**: ogni gruppo di elementi uniti da dissolvenza diventa un
   segmento (xfade + acrossfade fra i membri); un elemento isolato e' un
   segmento da solo. Il passaggio al nero e' un fade-out/fade-in ai due lati.
2. **concatenazione** dei segmenti senza ricodifica.
3. **mix** delle tracce audio sopra l'audio dei clip: ogni clip con il suo
   ritardo e volume, la musica abbassata sotto dialoghi e voce fuori campo.

Un unico grafo con cento ingressi sarebbe fragile da eseguire e impossibile da
riprendere; cosi' un errore costa al massimo il segmento in cui avviene.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger("creative_export")

FPS = 24
SAMPLE_RATE = 48000


def _ff():
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe, _video_codec_args
    return ffmpeg_bin, _run, probe, _video_codec_args


def _groups(items: list[dict]) -> list[list[dict]]:
    """Elementi consecutivi uniti da dissolvenza finiscono nello stesso gruppo."""
    groups: list[list[dict]] = []
    for it in items:
        if groups and it["transition"]["type"] == "fade":
            groups[-1].append(it)
        else:
            groups.append([it])
    return groups


def _render_group(group: list[dict], next_item: dict | None, out: Path, size: tuple[int, int],
                  clip_gain_db: float, clip_mute: bool, codec: str, quality: int,
                  settings: dict | None = None) -> None:
    from core.modules.sigma_creative_lab.video.postprocess import upscaled_source
    ffmpeg_bin, _run, probe, codec_args = _ff()
    w, h = size
    cmd = [ffmpeg_bin(), "-v", "error", "-y"]
    chains, vlabels, alabels = [], [], []
    for k, it in enumerate(group):
        # La copia Real-ESRGAN ha gli stessi frame e gli stessi tempi: src_in/src_out valgono uguale.
        src = upscaled_source(Path(it["clip_path"]), size[1], settings or {})
        cmd += ["-i", str(src)]
        dur = it["duration"]
        vf = (f"[{k}:v]trim=start={it['src_in']:.6f}:end={it['src_out']:.6f},setpts=PTS-STARTPTS,"
              f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
        # Passaggio al nero: questo elemento entra dal nero, il precedente ci esce.
        if k == 0 and it["transition"]["type"] == "dip":
            vf += f",fade=t=in:st=0:d={it['transition']['duration'] / 2:.3f}"
        if k == len(group) - 1 and next_item and next_item["transition"]["type"] == "dip":
            d = next_item["transition"]["duration"] / 2
            vf += f",fade=t=out:st={max(0.0, dur - d):.3f}:d={d:.3f}"
        chains.append(vf + f",format=yuv420p[v{k}]")
        has_audio = probe(src)["has_audio"] and not clip_mute
        if has_audio:
            af = (f"[{k}:a]atrim=start={it['src_in']:.6f}:end={it['src_out']:.6f},asetpts=PTS-STARTPTS,"
                  f"aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,volume={clip_gain_db}dB,"
                  f"afade=t=in:d=0.012,afade=t=out:st={max(0.0, dur - 0.012):.4f}:d=0.012[a{k}]")
        else:
            # Silenzio della stessa durata: xfade e concat pretendono tracce omogenee.
            af = f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={dur:.6f}[a{k}]"
        chains.append(af)
        vlabels.append(f"[v{k}]")
        alabels.append(f"[a{k}]")
    v, a, acc = vlabels[0], alabels[0], group[0]["duration"]
    for k in range(1, len(group)):
        d = group[k]["transition"]["duration"]
        offset = max(0.0, acc - d)
        chains.append(f"{v}{vlabels[k]}xfade=transition=fade:duration={d:.3f}:offset={offset:.6f}[xv{k}]")
        chains.append(f"{a}{alabels[k]}acrossfade=d={d:.3f}:c1=tri:c2=tri[xa{k}]")
        v, a = f"[xv{k}]", f"[xa{k}]"
        acc = offset + group[k]["duration"]
    cmd += ["-filter_complex", ";".join(chains), "-map", v, "-map", a]
    cmd += codec_args(codec, quality) + ["-r", str(FPS), "-c:a", "aac", "-b:a", "256k", "-ar", str(SAMPLE_RATE),
                                         "-ac", "2", str(out)]
    _run(cmd, timeout=3600)


def _mix_tracks(base: Path, tracks: list[dict], out: Path) -> None:
    """Aggiunge dialoghi, voce, effetti e musica sopra l'audio dei clip."""
    ffmpeg_bin, _run, _probe, _codec = _ff()
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-i", str(base)]
    chains, by_kind = [], {}
    n = 1
    for track in tracks:
        if track.get("mute") or track["kind"] == "clip":
            continue
        for clip in track["clips"]:
            src = Path(clip["src"])
            if not src.is_file():
                log.warning(f"clip audio mancante, saltata: {src}")
                continue
            cmd += ["-i", str(src)]
            dur = max(0.0, clip["src_out"] - clip["src_in"])
            delay_ms = int(round(clip["start"] * 1000))
            gain = float(track.get("gain_db", 0.0)) + float(clip.get("gain_db", 0.0))
            label = f"c{n}"
            # Le micro-dissolvenze da 20 ms restano: evitano i click anche senza dissolvenze scelte.
            f_in = max(0.02, float(clip.get("fade_in") or 0.0))
            f_out = max(0.02, float(clip.get("fade_out") or 0.0))
            chains.append(f"[{n}:a]atrim=start={clip['src_in']:.4f}:duration={dur:.4f},asetpts=PTS-STARTPTS,"
                          f"aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,volume={gain}dB,"
                          f"afade=t=in:d={f_in:.3f},afade=t=out:st={max(0.0, dur - f_out):.4f}:d={f_out:.3f},"
                          f"adelay={delay_ms}|{delay_ms}[{label}]")
            by_kind.setdefault(track["kind"], []).append(f"[{label}]")
            n += 1
    if n == 1:
        shutil.copy2(base, out)
        return

    def bus(name: str, labels: list[str]) -> str:
        if len(labels) == 1:
            chains.append(f"{labels[0]}anull[{name}]")
        else:
            chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[{name}]")
        return f"[{name}]"

    final = ["[0:a]"]
    speech = by_kind.get("dialogue", []) + by_kind.get("voice", [])
    speech_bus = bus("speech", speech) if speech else None
    if by_kind.get("music"):
        music_bus = bus("music", by_kind["music"])
        if speech_bus:
            # La musica si abbassa quando si parla: senza, i dialoghi si perdono.
            chains.append(f"{speech_bus}asplit=2[speech_out][speech_key]")
            chains.append(f"{music_bus}[speech_key]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[ducked]")
            final += ["[speech_out]", "[ducked]"]
        else:
            final.append(music_bus)
    elif speech_bus:
        final.append(speech_bus)
    if by_kind.get("sfx"):
        final.append(bus("sfx", by_kind["sfx"]))
    chains.append(f"{''.join(final)}amix=inputs={len(final)}:duration=first:normalize=0,alimiter=limit=0.95[mix]")
    cmd += ["-filter_complex", ";".join(chains), "-map", "0:v", "-map", "[mix]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out)]
    _run(cmd, timeout=7200)


def _burn_overlays(video: Path, overlays: list[dict], size: tuple[int, int], out: Path, codec: str, quality: int,
                   work: Path) -> None:
    """Testi sovrapposti impressi nel video, ognuno con una breve dissolvenza.

    Ogni testo e' un PNG trasparente (stesso disegno dell'anteprima) sovrapposto
    solo nel suo intervallo: niente drawtext, che dipende dai font di sistema e
    impagina male le righe lunghe.
    """
    from core.modules.sigma_creative_lab.video.media_import import overlay_png
    ffmpeg_bin, _run, _probe, codec_args = _ff()
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-i", str(video)]
    chains, last = [], "[0:v]"
    for k, ov in enumerate(overlays, 1):
        png = overlay_png(work / f"overlay_{k:03d}.png", size, ov["text"], ov.get("sub", ""), ov.get("style", "lower"))
        cmd += ["-loop", "1", "-t", f"{ov['end'] + 0.5:.3f}", "-i", str(png)]
        d = min(0.3, (ov["end"] - ov["start"]) / 3)
        chains.append(f"[{k}:v]format=rgba,fade=t=in:st={ov['start']:.3f}:d={d:.3f}:alpha=1,"
                      f"fade=t=out:st={ov['end'] - d:.3f}:d={d:.3f}:alpha=1[t{k}]")
        chains.append(f"{last}[t{k}]overlay=0:0:enable='between(t,{ov['start']:.3f},{ov['end']:.3f})'[v{k}]")
        last = f"[v{k}]"
    cmd += ["-filter_complex", ";".join(chains), "-map", last, "-map", "0:a", *codec_args(codec, quality),
            "-c:a", "copy", str(out)]
    _run(cmd, timeout=7200)


def export_timeline(tl: dict, prod: dict, out: Path, size: tuple[int, int] | None = None, codec: str = "libx264",
                    quality: int = 18, progress: Callable[[str, float], None] | None = None) -> Path:
    from core.modules.sigma_creative_lab.video.timeline import layout
    items = layout(tl, prod)["items"]
    if not items:
        raise RuntimeError("la timeline e' vuota")
    for it in items:
        if not Path(it["clip_path"]).is_file():
            raise RuntimeError(f"clip mancante per l'elemento {it['id']}: {it['clip_path']}")
    s = prod.get("settings") or {}
    if size is None:
        h = int(s.get("output_height") or 0)
        if not h:
            # Senza un'uscita scelta vale il materiale piu' definito in timeline (fino a
            # 1080p): una registrazione dello schermo importata non va ridotta ai 480p
            # con cui H3 genera, il testo diventerebbe illeggibile.
            ffmpeg_bin, _run, probe, _codec = _ff()
            heights = []
            for it in items:
                try:
                    heights.append(int(probe(Path(it["clip_path"]))["height"] or 0))
                except Exception:
                    continue
            h = min(1080, max([int(s.get("height", 480))] + heights))
        w = int(round(h * int(s.get("width", 864)) / int(s.get("height", 480)) / 2) * 2)
        size = (w, h)
    clip_track = next((t for t in tl["audio"] if t["kind"] == "clip"), {"gain_db": 0.0, "mute": False})
    work = out.parent / f".{out.stem}_export"
    work.mkdir(parents=True, exist_ok=True)
    groups = _groups(items)
    seg_list = []
    for gi, group in enumerate(groups):
        nxt = groups[gi + 1][0] if gi + 1 < len(groups) else None
        seg = work / f"seg_{gi:05d}.mp4"
        if progress:
            progress(f"Segmento {gi + 1}/{len(groups)}", (gi + 1) / (len(groups) + 1))
        _render_group(group, nxt, seg, size, float(clip_track.get("gain_db", 0.0)), bool(clip_track.get("mute")),
                      codec, quality, s)
        seg_list.append(f"file '{seg.resolve().as_posix()}'")
    ffmpeg_bin, _run, _probe, _codec = _ff()
    (work / "concat.txt").write_text("\n".join(seg_list) + "\n", encoding="utf-8")
    joined = work / "joined.mp4"
    _run([ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"),
          "-c", "copy", str(joined)], timeout=3600)
    overlays = [o for o in tl.get("overlays") or [] if o.get("text")]
    if overlays:
        if progress:
            progress("Testi sovrapposti", 0.96)
        titled = work / "titled.mp4"
        _burn_overlays(joined, overlays, size, titled, codec, quality, work)
        joined = titled
    if progress:
        progress("Mix delle tracce audio", 0.98)
    out.parent.mkdir(parents=True, exist_ok=True)
    _mix_tracks(joined, tl["audio"], out)
    shutil.rmtree(work, ignore_errors=True)
    return out
