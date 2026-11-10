"""Correzioni di montaggio per i video generati lunghi: clip al contrario, notti, dissolvenze, volume.

Nel video "Marte - 30 minuti" queste correzioni si facevano a mano con script esterni:
LTX-2.5 rende le albe come tramonti (si monta la clip al contrario), scurisce le notti verso
il nero (guadagno per fotogramma riferito al primo secondo) e il film voleva dissolvenze
fra le riprese e un volume da piattaforma. Qui diventano opzioni della produzione e
delle inquadrature, applicate dal montaggio.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_finishing")

#: Tetto del guadagno sulle notti: oltre, il rumore di LTX diventa piu' visibile del soggetto.
NIGHT_GAIN_CAP = 3.0
#: Una clip notturna tagliata non scende sotto questa durata: piu' corta sembra un errore di montaggio.
NIGHT_MIN_SECONDS = 7.0
#: Passo dei punti di controllo del guadagno: la curva fra due punti e' lineare.
GAIN_STEP_S = 0.5


def _tools():
    from .production import _run, ffmpeg_bin, probe
    return ffmpeg_bin, _run, probe


def luma_series(clip: Path) -> tuple[list[float], float]:
    """Luminanza media (YAVG, 0-255) di ogni fotogramma e fps della clip."""
    ffmpeg_bin, _run, probe = _tools()
    info = probe(clip)
    fps = (info["frames"] / info["duration"]) if info.get("frames") and info.get("duration") else 24.0
    out = _run([ffmpeg_bin(), "-v", "error", "-i", str(clip), "-vf",
                "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"]).stdout
    values = [float(m) for m in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", out)]
    if not values:
        raise RuntimeError(f"luminanza non misurata: {clip.name}")
    return values, fps


def night_gain_plan(luma: list[float], fps: float, cap: float = NIGHT_GAIN_CAP,
                    min_s: float = NIGHT_MIN_SECONDS) -> dict:
    """Guadagno che riporta ogni tratto alla luminanza del primo secondo.

    Si misura sopra il nero video (16): una notte che scende da 40 a 28 ha perso
    meta' della luce, non un terzo. Dove servirebbe piu' di `cap` la clip si taglia,
    ma mai sotto `min_s`: in quel caso resta intera col guadagno al tetto.
    """
    duration = len(luma) / fps
    floor = 16.0
    first = luma[:max(1, int(round(fps)))]
    ref = max(1.0, sum(first) / len(first) - floor)
    points, cut = [], None
    t = 0.0
    while t < duration:
        window = luma[int(t * fps):max(int(t * fps) + 1, int((t + GAIN_STEP_S) * fps))]
        level = max(0.5, sum(window) / len(window) - floor)
        need = ref / level
        if need > cap and cut is None and t >= min_s:
            cut = round(t, 3)
            break
        points.append((round(t, 3), round(min(cap, max(1.0, need)), 4)))
        t += GAIN_STEP_S
    return {"ref": round(ref + floor, 2), "points": points, "cut_s": cut, "cap": cap,
            "max_gain": max((g for _, g in points), default=1.0), "duration_s": round(duration, 3)}


def gain_expression(points: list[tuple[float, float]]) -> str:
    """Curva lineare a tratti in funzione di t, per il filtro eq valutato a ogni fotogramma."""
    if not points:
        return "1"
    if len(points) == 1:
        return f"{points[0][1]}"
    expr = f"{points[-1][1]}"
    for (t0, g0), (t1, g1) in reversed(list(zip(points, points[1:]))):
        slope = (g1 - g0) / (t1 - t0) if t1 > t0 else 0.0
        expr = f"if(lt(t,{t1}),{g0}+{slope:.6f}*(t-{t0}),{expr})"
    return expr


def gain_filter(points: list[tuple[float, float]]) -> str:
    """Guadagno moltiplicativo sulla luma: eq fa (y-0.5)*contrast+0.5+brightness, quindi y*g."""
    g = gain_expression(points)
    # Le virgole delle espressioni vanno protette dentro il grafo dei filtri.
    g = g.replace(",", "\\,")
    return f"eq=contrast='{g}':brightness='0.5*({g})-0.5':eval=frame"


def shot_fixes(shot: dict) -> dict:
    """Le correzioni chieste per un'inquadratura (vuoto = nessuna)."""
    out = {}
    if shot.get("reverse"):
        out["reverse"] = True
    if shot.get("night_gain"):
        out["night_gain"] = True
    if shot.get("trim_end_s"):
        out["trim_end_s"] = float(shot["trim_end_s"])
    return out


def _fingerprint(clip: Path, fixes: dict) -> str:
    st = clip.stat()
    raw = json.dumps({"clip": str(clip.resolve()), "size": st.st_size, "mtime": st.st_mtime_ns, **fixes},
                     sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def plan_for(shot: dict) -> dict | None:
    """Piano del guadagno notturno della clip attuale, misurato una volta e tenuto nell'inquadratura."""
    if not shot.get("night_gain") or not shot.get("clip_path"):
        return None
    clip = Path(shot["clip_path"])
    if not clip.is_file():
        return None
    key = _fingerprint(clip, {"night": NIGHT_GAIN_CAP, "min": NIGHT_MIN_SECONDS})
    cached = shot.get("night_plan") or {}
    if cached.get("key") == key:
        return cached
    luma, fps = luma_series(clip)
    plan = {**night_gain_plan(luma, fps), "key": key}
    shot["night_plan"] = plan
    return plan


def corrected_source(shot: dict, quality: int = 12) -> Path:
    """La clip con le correzioni dell'inquadratura, alla risoluzione di generazione.

    Si corregge prima dell'upscale: `reverse` tiene in memoria tutti i fotogrammi, e
    a 2160 righe una clip da dieci secondi sono tre gigabyte. Il file sta in cache
    accanto alla clip e si rifa' solo se cambiano clip o correzioni.
    """
    clip = Path(shot["clip_path"])
    fixes = shot_fixes(shot)
    if not fixes:
        return clip
    ffmpeg_bin, _run, probe = _tools()
    out = clip.with_name(f"{clip.stem}.fix{_fingerprint(clip, fixes)}.mp4")
    if out.is_file():
        return out
    info = probe(clip)
    vf, af = [], []
    end = None
    if fixes.get("night_gain"):
        plan = plan_for(shot)
        if plan:
            if plan.get("cut_s"):
                end = float(plan["cut_s"])
            vf.append(gain_filter([tuple(p) for p in plan["points"]]))
    if fixes.get("trim_end_s"):
        end = min(end or 1e9, max(1.0, float(info["duration"] or 0) - float(fixes["trim_end_s"])))
    if end:
        vf.insert(0, f"trim=end={end:.4f},setpts=PTS-STARTPTS")
        af.insert(0, f"atrim=end={end:.4f},asetpts=PTS-STARTPTS")
    if fixes.get("reverse"):
        # Al contrario anche l'audio: il vento o un rombo letti in avanti tradirebbero il trucco.
        vf.append("reverse")
        af.append("areverse")
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-vf", ",".join(vf + ["format=yuv420p"])]
    if info.get("has_audio"):
        cmd += ["-af", ",".join(af) if af else "anull", "-c:a", "aac", "-b:a", "320k"]
    else:
        cmd += ["-an"]
    tmp = out.with_name(out.stem + ".part.mp4")
    _run(cmd + ["-c:v", "libx264", "-preset", "medium", "-crf", str(int(quality)), "-pix_fmt", "yuv420p",
                str(tmp)], timeout=3600)
    tmp.replace(out)
    return out


# ---------------------------------------------------------------------------
# Dissolvenze fra le riprese
# ---------------------------------------------------------------------------

def fade_boundaries(shots: list, crossfade_s: float, durations: list[float]) -> list[float]:
    """Durata della dissolvenza dopo ogni inquadratura (0 = taglio netto).

    Mai dentro una catena di `continue`: e' la stessa ripresa che prosegue, una
    dissolvenza a meta' farebbe vedere il punto di giunzione.
    """
    out = []
    for i in range(len(shots)):
        if i + 1 >= len(shots) or crossfade_s <= 0:
            out.append(0.0)
            continue
        nxt = shots[i + 1]
        joined = nxt.get("transition") == "continue" and nxt.get("continued", True)
        # Ogni lato deve restare visibile almeno per mezzo secondo fuori dalle dissolvenze.
        room = min(durations[i], durations[i + 1]) / 2 - 0.25
        out.append(0.0 if joined or room <= 0.1 else round(min(crossfade_s, room), 3))
    return out


def crossfade_pieces(segments: list[Path], durations: list[float], fades: list[float], work: Path,
                     video_args: list, fps: int) -> list[Path]:
    """Pezzi da concatenare: corpo di ogni segmento senza le code e una clip per ogni dissolvenza.

    Un unico grafo con xfade su centinaia di ingressi sarebbe fragile e non riprendibile
    (vedi assemble); qui si ricodificano solo i tratti toccati dalle dissolvenze.
    """
    ffmpeg_bin, _run, _probe = _tools()
    pieces = []
    for i, seg in enumerate(segments):
        head = fades[i - 1] if i > 0 else 0.0
        tail = fades[i]
        if head or tail:
            body = work / f"{seg.stem}.body.mkv"
            end = durations[i] - tail
            _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(seg), "-filter_complex",
                  f"[0:v]trim=start={head:.5f}:end={end:.5f},setpts=PTS-STARTPTS,fps={fps}[v];"
                  f"[0:a]atrim=start={head:.5f}:end={end:.5f},asetpts=PTS-STARTPTS[a]",
                  "-map", "[v]", "-map", "[a]", *video_args, "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
                  str(body)])
            pieces.append(body)
        else:
            pieces.append(seg)
        if tail:
            nxt = segments[i + 1]
            joint = work / f"{seg.stem}.xfade.mkv"
            d = tail
            start = durations[i] - d
            _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(seg), "-i", str(nxt), "-filter_complex",
                  f"[0:v]trim=start={start:.5f},setpts=PTS-STARTPTS,fps={fps}[a0];"
                  f"[1:v]trim=end={d:.5f},setpts=PTS-STARTPTS,fps={fps}[b0];"
                  f"[a0][b0]xfade=transition=fade:duration={d:.5f}:offset=0[v];"
                  f"[0:a]atrim=start={start:.5f},asetpts=PTS-STARTPTS[a1];"
                  f"[1:a]atrim=end={d:.5f},asetpts=PTS-STARTPTS[b1];"
                  f"[a1][b1]acrossfade=d={d:.5f}:c1=tri:c2=tri[a]",
                  "-map", "[v]", "-map", "[a]", *video_args, "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
                  str(joint)])
            pieces.append(joint)
    return pieces


def montage_durations(prod: dict, fps: int = 24) -> list[tuple[dict, float]]:
    """Quanto dura ogni inquadratura nel film montato: fotogramma doppio, tagli e dissolvenze compresi.

    La musica si compone prima del montaggio: con le durate dello storyboard un film
    di 30 minuti con 180 dissolvenze da 1 s finiva con tre minuti di musica in piu',
    e i cambi di brano cadevano a meta' delle scene.
    """
    done = [s for s in prod.get("shots") or [] if s.get("status") == "done"]
    lengths = []
    for i, shot in enumerate(done):
        frames = int(shot.get("frames") or 0)
        seconds = frames / fps if frames else float(shot.get("duration_s") or 0)
        if shot.get("transition") == "continue" and i > 0 and shot.get("continued", True) and not shot.get("reverse"):
            seconds -= 1.0 / fps
        if shot.get("night_gain"):
            try:
                plan = plan_for(shot)
            except Exception as exc:
                log.warning(f"guadagno notturno non misurato per {shot.get('id')}: {exc}")
                plan = None
            if plan and plan.get("cut_s"):
                seconds = min(seconds, float(plan["cut_s"]))
        if shot.get("trim_end_s"):
            seconds = max(1.0, seconds - float(shot["trim_end_s"]))
        lengths.append(max(0.0, seconds))
    fades = fade_boundaries(done, float((prod.get("settings") or {}).get("crossfade_s") or 0), lengths)
    # Meta' di ogni sovrapposizione a ciascun lato: la somma e' la durata esatta del film.
    return [(sh, lengths[i] - (fades[i - 1] / 2 if i else 0.0) - fades[i] / 2) for i, sh in enumerate(done)]


def clip_contact_sheet(clip: Path, out: Path, columns: int = 4, rows: int = 3, width: int = 400) -> Path:
    """Provino di una clip: fotogrammi equidistanti dal primo all'ultimo, da guardare con view_image.

    L'ultimo fotogramma e' sempre nel foglio: e' li' che si vede se un'alba e' diventata
    un tramonto o se una notte e' finita nel nero.
    """
    ffmpeg_bin, _run, probe = _tools()
    if out.is_file() and out.stat().st_mtime >= clip.stat().st_mtime:
        return out
    info = probe(clip)
    count = columns * rows
    frames = int(info.get("frames") or 0) or int(round(float(info.get("duration") or 1) * 24))
    # Indici equidistanti con primo e ultimo inclusi (fps=1/passo perdeva la coda).
    picks = sorted({round(k * (frames - 1) / (count - 1)) for k in range(count)}) if frames > 1 else [0]
    select = "+".join(f"eq(n\\,{n})" for n in picks)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-vf",
          f"select='{select}',scale={width}:-2,tile={columns}x{rows}", "-fps_mode", "passthrough",
          "-frames:v", "1", "-q:v", "3", str(out)], timeout=600)
    return out


# ---------------------------------------------------------------------------
# Volume finale
# ---------------------------------------------------------------------------

def loudnorm(video: Path, target_lufs: float = -16.0, true_peak: float = -1.5) -> dict:
    """Porta il film al volume integrato richiesto, in due passaggi (misura, poi correzione lineare).

    Il video si copia: la sola traccia audio si ricodifica. Il file viene sostituito
    solo quando la nuova versione e' completa.
    """
    ffmpeg_bin, _run, _probe = _tools()
    flt = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
    err = _run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
                flt + ":print_format=json", "-f", "null", "-"], timeout=7200).stderr
    found = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err, flags=re.S)
    if not found:
        raise RuntimeError("misura del volume non riuscita")
    m = json.loads(found[-1])
    # La correzione lineare non supera il tetto dei picchi: prova della sonda (9/11/2026), -19,5 LUFS con
    # picchi a ridosso del tetto, e il film usciva a -18,8 invece di -16. Se il guadagno porterebbe i picchi
    # oltre il tetto si usa la modalita' dinamica, che comprime appena e arriva al volume chiesto.
    gain = target_lufs - float(m["input_i"])
    linear = float(m["input_tp"]) + gain <= true_peak
    second = (f"{flt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
              f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
              f":linear={'true' if linear else 'false'}")
    tmp = video.with_name(video.stem + ".loud" + video.suffix)
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(video), "-map", "0", "-c:v", "copy", "-c:s", "copy",
          "-af", second, "-ar", "48000", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(tmp)],
         timeout=7200)
    tmp.replace(video)
    out = {"target_lufs": target_lufs, "measured_lufs": float(m["input_i"]), "mode": "linear" if linear else "dynamic"}
    check = _run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
                  flt + ":print_format=json", "-f", "null", "-"], timeout=7200).stderr
    after = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", check, flags=re.S)
    if after:
        out["output_lufs"] = float(json.loads(after[-1])["input_i"])
    return out
