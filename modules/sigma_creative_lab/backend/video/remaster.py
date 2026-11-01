"""Pipeline ripetibile per restaurare un film d'archivio senza ridisegnarne le scene."""
from __future__ import annotations

import json
import math
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import requests
from PIL import Image

from core.logger import get_logger

log = get_logger("creative_remaster")
Progress = Callable[[str, float], None]


def _nop(_message: str, _fraction: float) -> None:
    return None


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _ff():
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, probe
    return ffmpeg_bin, probe


def _run(cmd: list[str], timeout: int = 3600) -> None:
    ffmpeg_bin, _probe = _ff()
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout, creationflags=_flags())
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace")[-1200:] if exc.stderr else str(exc)
        raise RuntimeError(f"ffmpeg non è riuscito: {detail}") from exc


def _count(path: Path) -> int:
    _ffmpeg_bin, probe = _ff()
    return int(probe(path).get("frames") or 0)


def _rate(path: Path) -> float:
    from core.modules.sigma_creative_lab.video.postprocess import _rate_and_frames
    ffmpeg_bin, probe = _ff()
    return float(_rate_and_frames(path, probe(path))[0])


def cadence_profile(source: Path, width: int = 96, height: int = 72) -> dict:
    """Rimuove il telecine 3:2 quando c'e', preserva invece la cadenza nativa."""
    ffmpeg_bin, probe = _ff()
    info = probe(source)
    fps = _rate(source)
    if fps < 12 or fps > 70:
        raise ValueError(f"cadenza non supportata per il profilo 3:2: {fps:.3f} fps")
    # Un flusso sotto i 28 fps non contiene il telecine cinematografico 29,97/30
    # fps: analizzare ogni frame a bassa risoluzione sarebbe solo un passaggio costoso.
    if fps < 28:
        return {"source_fps": fps, "cycle": 1, "drop_phases": [],
                "phase_median_diff": [], "fps": fps, "mode": "native"}
    frame_size = width * height
    decoded = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(source), "-vf", f"scale={width}:{height}",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True,
                             timeout=max(1800, int(info.get("duration") or 0) * 3), creationflags=_flags(), check=True)
    raw = np.frombuffer(decoded.stdout, dtype=np.uint8)
    if raw.size % frame_size:
        raise RuntimeError("lettura sorgente incompleta durante l'analisi della cadenza")
    frames = raw.reshape(-1, height, width).astype(np.int16)
    differences = np.abs(frames[1:] - frames[:-1]).mean(axis=(1, 2))
    del frames, raw, decoded
    phases = np.arange(1, len(differences) + 1, dtype=np.int64) % 5
    means = np.array([float(np.median(differences[phases == p])) for p in range(5)])
    dropped_phases = sorted(np.argsort(means)[:2].tolist())
    remaining = sorted(means[p] for p in range(5) if p not in dropped_phases)
    if not remaining or remaining[0] < max(0.35, float(np.mean(means[dropped_phases])) * 1.08):
        return {"source_fps": fps, "cycle": 1, "drop_phases": [],
                "phase_median_diff": [round(float(x), 4) for x in means], "fps": fps, "mode": "native"}
    return {"source_fps": fps, "cycle": 5, "drop_phases": dropped_phases,
            "phase_median_diff": [round(float(x), 4) for x in means], "fps": fps * 3 / 5, "mode": "telecine"}


def _select_expr(profile: dict) -> str:
    phases = profile["drop_phases"]
    if not phases:
        return "all"
    return "not(" + "+".join(f"eq(mod(n\\,5)\\,{p})" for p in phases) + ")"


def normalize_cadence(source: Path, out: Path, profile: dict) -> dict:
    """Scarta solo i doppioni della fase rilevata e assegna il frame rate reale."""
    ffmpeg_bin, probe = _ff()
    fps = float(profile["fps"])
    out.parent.mkdir(parents=True, exist_ok=True)
    expr = _select_expr(profile)
    video_filter = (f"select='{expr}'," if profile.get("drop_phases") else "") + f"setpts=N/({fps:.9f}*TB)"
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(source), "-an", "-vf",
          video_filter, "-fps_mode", "cfr", "-r", f"{fps:.9f}",
          "-c:v", "libx264", "-preset", "medium", "-crf", "10", "-pix_fmt", "yuv420p", str(out)],
         timeout=7200)
    info = probe(out)
    return {"path": str(out), "fps": _rate(out), "frames": int(info.get("frames") or 0),
            "duration": float(info.get("duration") or 0.0)}


def _scene_boundaries(source: Path, fps: float, total: int, analysis: dict | None = None) -> list[int]:
    from core.modules.sigma_creative_lab.video import restoration as R
    analysis = analysis or R.analyze(source)
    cuts = [0]
    for seconds in analysis.get("cuts", []):
        frame = int(round(float(seconds) * fps))
        if 12 <= frame < total - 12 and frame - cuts[-1] >= 12:
            cuts.append(frame)
    cuts.append(total)
    return cuts


def _segments(boundaries: list[int], max_frames: int) -> list[tuple[int, int]]:
    if len(boundaries) == 1:
        boundaries = [0, boundaries[0]]
    result = []
    for start, end in zip(boundaries, boundaries[1:]):
        cursor = start
        while end - cursor > max_frames:
            stop = cursor + max_frames
            result.append((cursor, stop))
            cursor = stop
        if end - cursor:
            result.append((cursor, end))
    return result


def _extract(source: Path, start: int, end: int, fps: float, out: Path, pad_one: bool = False) -> None:
    ffmpeg_bin, _probe = _ff()
    count = end - start
    vf = f"select='between(n\\,{start}\\,{end - 1})',setpts=N/({fps:.9f}*TB)"
    if pad_one:
        vf += f",tpad=stop_mode=clone:stop_duration={1.0 / fps:.9f},trim=end_frame={count + 1}"
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(source), "-vf", vf, "-an", "-fps_mode", "cfr",
          "-r", f"{fps:.9f}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "8", "-pix_fmt", "yuv420p",
          str(out)], timeout=1800)
    expected = count + (1 if pad_one else 0)
    got = _count(out)
    if abs(got - expected) > 1:
        raise RuntimeError(f"segmento estratto con {got} frame invece di {expected}")


def _concat(parts: list[Path], out: Path, fps: float, gpu: int) -> None:
    from core.modules.sigma_creative_lab.video.postprocess import video_encoder_args
    ffmpeg_bin, _probe = _ff()
    listing = out.with_suffix(".concat.txt")
    partial = out.with_name(f"{out.stem}.part{out.suffix}")
    listing.write_text("".join(f"file '{p.as_posix().replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n"
                                 for p in parts), encoding="utf-8")
    try:
        _run([ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-an",
              "-r", f"{fps:.9f}", *video_encoder_args(14, gpu), str(partial)], timeout=7200)
        partial.replace(out)
    finally:
        listing.unlink(missing_ok=True)


def upscale_temporal(source: Path, out: Path, fps: float, total: int, boundaries: list[int], gpu: int,
                     progress: Progress, multiplier: float = 3.0) -> dict:
    from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
    from core.modules.sigma_creative_lab.generators.adapters.comfy_seedvr import upscale_clip
    ffmpeg_bin, probe = _ff()
    cuts = _segments(boundaries, max_frames=max(18, round(fps * 5)))
    parts = []
    base = None
    src_info = probe(source)
    expected_size = (int(round(int(src_info["width"]) * multiplier / 2) * 2),
                     int(round(int(src_info["height"]) * multiplier / 2) * 2))
    scale_tag = f"{multiplier:.3f}".replace(".", "p")
    for index, (start, end) in enumerate(cuts):
        segment = out.parent / f"seedvr_{scale_tag}_input_{index:04d}.mp4"
        restored = out.parent / f"seedvr_{scale_tag}_output_{index:04d}.mp4"
        expected = end - start
        cached = False
        if restored.is_file():
            try:
                cached_info = probe(restored)
                cached = abs(int(cached_info.get("frames") or 0) - expected) <= 1 and \
                    (int(cached_info["width"]), int(cached_info["height"])) == expected_size
            except (OSError, KeyError, TypeError, ValueError, RuntimeError):
                cached = False
        if not cached:
            _extract(source, start, end, fps, segment)
            partial = restored.with_name(f"{restored.stem}.part{restored.suffix}")
            partial.unlink(missing_ok=True)
            base = base or instances.ensure(gpu)
            upscale_clip(base, segment, partial, multiplier, timeout_s=2400)
            actual_info = probe(partial)
            if abs(int(actual_info.get("frames") or 0) - expected) > 1 or \
                    (int(actual_info["width"]), int(actual_info["height"])) != expected_size:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"SeedVR2 ha restituito un segmento non valido ({index + 1}/{len(cuts)})")
            partial.replace(restored)
        parts.append(restored)
        segment.unlink(missing_ok=True)
        progress(f"SeedVR2 · segmento {index + 1}/{len(cuts)}" + (" · recuperato" if cached else ""),
                 (index + 1) / max(1, len(cuts)))
    _concat(parts, out, fps, gpu)
    if abs(_count(out) - total) > 1:
        raise RuntimeError("SeedVR2 ha cambiato la durata del film")
    for p in parts:
        p.unlink(missing_ok=True)
    return probe(out)


def _comfy_rife(base: str, segment: Path, out: Path, fps: float, timeout_s: float = 900) -> Path:
    name = f"sigma_rife_{uuid.uuid4().hex[:12]}.mp4"
    with segment.open("rb") as fh:
        response = requests.post(f"{base.rstrip('/')}/upload/image", files={"image": (name, fh, "video/mp4")},
                                 data={"overwrite": "true"}, timeout=120)
    response.raise_for_status()
    uploaded = response.json().get("name", name)
    graph = {
        "load": {"class_type": "LoadVideo", "inputs": {"file": uploaded}},
        "parts": {"class_type": "GetVideoComponents", "inputs": {"video": ["load", 0]}},
        "model": {"class_type": "FrameInterpolationModelLoader", "inputs": {"model_name": "rife_v4.26.safetensors"}},
        "rife": {"class_type": "FrameInterpolate", "inputs": {
            "interp_model": ["model", 0], "images": ["parts", 0], "multiplier": 4}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["rife", 0], "fps": fps * 4}},
        "save": {"class_type": "SaveVideo", "inputs": {
            "video": ["video", 0], "filename_prefix": f"sigma/remaster/rife_{uuid.uuid4().hex[:8]}",
            "format": "mp4", "format.codec": "h264"}},
    }
    response = requests.post(f"{base.rstrip('/')}/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex},
                             timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI ha rifiutato RIFE: {response.text[:600]}")
    prompt_id = response.json()["prompt_id"]
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        history = requests.get(f"{base.rstrip('/')}/history/{prompt_id}", timeout=30).json().get(prompt_id)
        if history:
            status = history.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"RIFE/ComfyUI fallito: {str(status.get('messages'))[-800:]}")
            if status.get("completed"):
                for node in (history.get("outputs") or {}).values():
                    for item in node.get("images") or node.get("videos") or node.get("gifs") or []:
                        if item.get("type", "output") != "output":
                            continue
                        response = requests.get(f"{base.rstrip('/')}/view", params={
                            "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output")}, timeout=300)
                        response.raise_for_status()
                        out.write_bytes(response.content)
                        return out
                raise RuntimeError("RIFE completato senza produrre un video")
        time.sleep(1.5)
    raise TimeoutError("RIFE su ComfyUI ha superato il timeout del segmento")


def interpolate_temporal(source: Path, out: Path, fps: float, total: int, boundaries: list[int], gpu: int,
                         progress: Progress) -> dict:
    from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
    from core.modules.sigma_creative_lab.video.postprocess import video_encoder_args
    ffmpeg_bin, probe = _ff()
    chunks = _segments(boundaries, max_frames=max(18, round(fps * 2)))
    base = None
    parts = []
    target_fps = 24.0
    for index, (start, end) in enumerate(chunks):
        n = end - start
        prefix = out.stem
        inp = out.parent / f"{prefix}_input_{index:04d}.mp4"
        generated = out.parent / f"{prefix}_72fps_{index:04d}.mp4"
        part = out.parent / f"{prefix}_24fps_{index:04d}.mp4"
        # L'arrotondamento cumulativo evita che gli scarti per shot accorcino tutto il film.
        target = max(2, int(round(end * target_fps / fps) - round(start * target_fps / fps)))
        cached_part = False
        if part.is_file():
            try:
                cached_part = abs(int(probe(part).get("frames") or 0) - target) <= 1
            except (OSError, ValueError, RuntimeError):
                cached_part = False
        if not cached_part:
            expected_input = end - start + 1
            input_valid = False
            if inp.is_file():
                try:
                    input_valid = abs(int(probe(inp).get("frames") or 0) - expected_input) <= 1
                except (OSError, ValueError, RuntimeError):
                    input_valid = False
            if not input_valid:
                _extract(source, start, end, fps, inp, pad_one=True)
            generated_valid = False
            if generated.is_file():
                try:
                    generated_valid = abs(int(probe(generated).get("frames") or 0) - expected_input * 4) <= 4
                except (OSError, ValueError, RuntimeError):
                    generated_valid = False
            if not generated_valid:
                base = base or instances.ensure(gpu)
                _comfy_rife(base, inp, generated, fps)
            partial = part.with_name(f"{part.stem}.part{part.suffix}")
            _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(generated), "-vf",
                  f"fps={target_fps:.6f},trim=end_frame={target}", "-an", "-frames:v", str(target), "-r", "24",
                  *video_encoder_args(14, gpu), str(partial)], timeout=1800)
            actual = int(probe(partial).get("frames") or 0)
            if actual != target:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"RIFE ha prodotto {actual} frame invece di {target} nel segmento {index + 1}")
            partial.replace(part)
        parts.append(part)
        inp.unlink(missing_ok=True)
        generated.unlink(missing_ok=True)
        progress("RIFE · interpolazione per inquadratura", (index + 1) / max(1, len(chunks)))
    _concat(parts, out, target_fps, gpu)
    expected_total = int(round(total * target_fps / fps))
    if abs(_count(out) - expected_total) > 1:
        raise RuntimeError("RIFE ha cambiato la durata complessiva oltre la tolleranza dei segmenti")
    for p in parts:
        p.unlink(missing_ok=True)
    return probe(out)


def anchor_chroma(source: Path, out: Path, cmap: dict, gpu: int = 0, strength: float = 0.7) -> dict:
    """Stabilizza la dominante cromatica di ogni inquadratura senza trascinare i pixel in movimento."""
    from core.modules.sigma_creative_lab.video.postprocess import video_encoder_args
    ffmpeg_bin, probe = _ff()
    info = probe(source)
    width, height = int(info["width"]), int(info["height"])
    fps, total = _rate(source), int(info["frames"])
    small_w, small_h = 160, 120
    decode_small = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(source), "-vf",
                                   f"scale={small_w}:{small_h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                                  capture_output=True, timeout=max(1800, int(info["duration"] * 3)),
                                  creationflags=_flags(), check=True).stdout
    frame_size = small_w * small_h * 3
    frames = np.frombuffer(decode_small, dtype=np.uint8)
    if len(frames) % frame_size:
        raise RuntimeError("lettura cromatica incompleta")
    frames = frames.reshape(-1, small_h, small_w, 3)
    stats = np.empty((len(frames), 2), dtype=np.float32)
    for i, frame in enumerate(frames):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        stats[i] = np.median(lab[..., 1:3].reshape(-1, 2), axis=0)
    del frames, decode_small
    targets = stats.copy()
    shots = cmap.get("shots") or [{"start": 0, "end": len(stats)}]
    for shot in shots:
        start, end = max(0, int(shot["start"])), min(len(stats), int(shot["end"]))
        for i in range(start, end):
            lo, hi = max(start, i - 8), min(end, i + 9)
            targets[i] = np.median(stats[lo:hi], axis=0)
    decode = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-i", str(source), "-f", "rawvideo", "-pix_fmt",
                               "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=_flags())
    tmp = out.with_suffix(".part.mp4")
    encode = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                               f"{width}x{height}", "-framerate", f"{fps:.9f}", "-i", "-", "-an",
                               *video_encoder_args(14, gpu), str(tmp)], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=_flags())
    size = width * height * 3
    index = 0
    try:
        while index < min(total, len(stats)):
            raw = decode.stdout.read(size)
            if len(raw) != size:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
            current = np.median(lab[..., 1:3].reshape(-1, 2), axis=0)
            shift = np.clip(targets[index] - current, -10.0, 10.0) * strength
            lab[..., 1] = np.clip(lab[..., 1] + shift[0], 0, 255)
            lab[..., 2] = np.clip(lab[..., 2] + shift[1], 0, 255)
            encode.stdin.write(cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR).tobytes())
            index += 1
        encode.stdin.close()
        decode.stdout.close()
        enc_error = encode.stderr.read().decode(errors="replace") if encode.stderr else ""
        dec_error = decode.stderr.read().decode(errors="replace") if decode.stderr else ""
        if encode.wait(timeout=600) != 0 or decode.wait(timeout=600) != 0:
            raise RuntimeError(f"ancoraggio colore fallito: {(enc_error or dec_error)[-800:]}")
    finally:
        for proc in (decode, encode):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)
    if index != min(total, len(stats)):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ancoraggio colore: {index} frame invece di {min(total, len(stats))}")
    tmp.replace(out)
    return {"path": str(out), "frames": index, "fps": fps}


def _comparison(original: Path, restored: Path, out: Path, duration: float) -> Path:
    from core.modules.sigma_creative_lab.video.restoration import frame_jpeg
    from io import BytesIO
    times = np.linspace(max(1.0, duration * 0.04), duration * 0.96, 12)
    cells = []
    for at in times:
        pair = []
        for source in (original, restored):
            image = Image.open(BytesIO(frame_jpeg(source, float(at), 800))).convert("RGB")
            image.thumbnail((640, 360), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (640, 360), "#101014")
            canvas.paste(image, ((640 - image.width) // 2, (360 - image.height) // 2))
            pair.append(canvas)
        row = Image.new("RGB", (1280, 360), "#101014")
        row.paste(pair[0], (0, 0))
        row.paste(pair[1], (640, 0))
        cells.append(row)
    sheet = Image.new("RGB", (1280, 360 * len(cells)), "#101014")
    for i, row in enumerate(cells):
        sheet.paste(row, (0, i * 360))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=90)
    return out


def output_dimensions(source_width: int, source_height: int, target_height: int) -> tuple[int, int]:
    """Mantiene il rapporto originale: i film 4:3 non vanno stirati in 16:9."""
    if source_width < 1 or source_height < 1:
        raise ValueError("dimensioni della sorgente non valide")
    if target_height not in (1080, 1440, 2160):
        raise ValueError("altezza finale non supportata: scegliere 1080, 1440 o 2160")
    width = int(round((source_width * target_height / source_height) / 2) * 2)
    return max(2, width), target_height


def _valid_video(path: Path, duration: float | None = None, frames: int | None = None,
                 size: tuple[int, int] | None = None) -> dict | None:
    """Un checkpoint vale solo se FFprobe riesce a leggere durata, frame e dimensioni attese."""
    if not path.is_file():
        return None
    try:
        info = _ff()[1](path)
        if not info.get("width") or not info.get("height") or not info.get("frames"):
            return None
        if duration is not None and abs(float(info.get("duration") or 0) - duration) > 1.0:
            return None
        if frames is not None and abs(int(info["frames"]) - frames) > 1:
            return None
        if size is not None and (int(info["width"]), int(info["height"])) != size:
            return None
        return info
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        return None


def _checkpoint_dir(work_root: Path, source: Path, output_height: int, source_info: dict) -> Path:
    """Ritrova il checkpoint del film; l'identità sorgente impedisce di mescolare produzioni."""
    source = source.resolve()
    stat = source.stat()
    metadata = {"source": str(source), "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns, "output_height": output_height}
    candidates = sorted((p for p in work_root.glob("remaster_*") if p.is_dir()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        manifest_path = candidate / "checkpoint.json"
        # La sola durata non prova che un vecchio temporaneo appartenga a questo film.
        if not manifest_path.is_file():
            continue
        manifest = {}
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if any(manifest.get(k) != metadata[k] for k in ("source", "source_size", "source_mtime_ns")):
                continue
        # Migra i checkpoint temporanei creati dalla versione precedente del restauro.
        normalized = _valid_video(candidate / "cadence_18fps.mp4", float(source_info["duration"]))
        cleaned = _valid_video(candidate / "clean_18fps.mp4", float(source_info["duration"]))
        if normalized and cleaned:
            manifest.update(metadata)
            temp = manifest_path.with_suffix(".part")
            temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(manifest_path)
            return candidate
    key = uuid.uuid5(uuid.NAMESPACE_URL, f"{source}|{stat.st_size}|{stat.st_mtime_ns}|{output_height}").hex[:12]
    target = work_root / f"remaster_{key}_{output_height}h"
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "checkpoint.json"
    if not manifest_path.is_file():
        manifest_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def remaster_film(source: Path, output: Path, work_root: Path, score: Path | None = None, gpu: int = 0,
                  progress: Progress = _nop, output_height: int = 1080,
                  preserve_source_audio: bool = True, cancel_event=None) -> dict:
    """Restaura a fasi riprendibili: checkpoint e segmenti restano validi dopo un riavvio."""
    from core.modules.sigma_creative_lab.video import color_finish as CF
    from core.modules.sigma_creative_lab.video import restoration as R
    from core.modules.sigma_creative_lab.video.postprocess import recolor_clip, video_encoder_args
    ffmpeg_bin, probe = _ff()
    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            from core.modules.sigma_creative_lab.video.editor_jobs import JobCancelled
            raise JobCancelled("Restauro annullato")

    if not source.is_file():
        raise FileNotFoundError(source)
    source_info = probe(source)
    output_size = output_dimensions(int(source_info["width"]), int(source_info["height"]), int(output_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    tmp = _checkpoint_dir(work_root, source, output_height, source_info)
    manifest_path = tmp / "checkpoint.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def saved(stage: str) -> None:
        manifest["completed_stage"] = stage
        manifest["updated"] = time.time()
        part = manifest_path.with_suffix(".part")
        part.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        part.replace(manifest_path)

    profile = cadence_profile(source)
    if manifest.get("completed_stage") == "master_video":
        completed = _valid_video(output, float(source_info["duration"]), size=output_size)
        if completed:
            comparison = work_root / f"{output.stem}_prima_dopo.jpg"
            if not comparison.is_file():
                comparison = _comparison(source, output, comparison, float(completed["duration"]))
            return {"path": str(output), "comparison": str(comparison), "checkpoint_dir": str(tmp),
                    "source_fps": profile["source_fps"], "restored_fps": 24, "output_size": output_size,
                    "cadence": profile, "clean": _valid_video(tmp / "clean_18fps.mp4"),
                    "enhanced": _valid_video(tmp / f"seedvr_{output_height}h.mp4"), "final": completed,
                    "color_shots": 0, "titles": 0}
    progress("Analisi cadenza 3:2", 0.02)
    normalized = tmp / "cadence_18fps.mp4"
    if not _valid_video(normalized, float(source_info["duration"])):
        normalize_cadence(source, normalized, profile)
    saved("cadenza")
    check_cancelled()
    progress("Pulizia pellicola · polvere, graffi, deflicker e stabilizzazione", 0.06)
    clean = tmp / "clean_18fps.mp4"
    clean_info = _valid_video(clean, float(source_info["duration"]))
    if not clean_info:
        R.clean_film(normalized, clean, lambda m, p: progress(m, 0.06 + 0.16 * p), cadence_removed=True)
        clean_info = probe(clean)
    saved("pulizia")
    check_cancelled()
    fps = _rate(clean)
    total = int(clean_info["frames"] or 0)
    analysis_path = tmp / "analysis.json"
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        progress("Analisi delle inquadrature e dei cartelli", 0.20)
        analysis = R.analyze(clean, lambda _message, fraction: progress(
            "Analisi delle inquadrature e dei cartelli", 0.20 + 0.02 * fraction))
        analysis_part = analysis_path.with_suffix(".part")
        analysis_part.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        analysis_part.replace(analysis_path)
    cuts = _scene_boundaries(clean, fps, total, analysis)
    multiplier = min(3.0, float(output_size[1]) / max(1, int(clean_info["height"])))
    enhanced_size = (int(round(int(clean_info["width"]) * multiplier / 2) * 2),
                     int(round(int(clean_info["height"]) * multiplier / 2) * 2))
    progress(f"SeedVR2 · ricostruzione a scala {multiplier:.2f}×", 0.22)
    enhanced = tmp / f"seedvr_{output_height}h.mp4"
    enhanced_info = _valid_video(enhanced, float(clean_info["duration"]), total, enhanced_size)
    if not enhanced_info:
        upscale_temporal(clean, enhanced, fps, total, cuts, gpu,
                         lambda m, p: progress(m, 0.22 + 0.35 * p), multiplier=multiplier)
        enhanced_info = _valid_video(enhanced, float(clean_info["duration"]), total, enhanced_size)
        if not enhanced_info:
            raise RuntimeError("SeedVR2: il checkpoint ricomposto non supera la verifica di durata/dimensioni")
    saved("upscale")
    check_cancelled()
    enhanced_fps = _rate(enhanced)
    enhanced_frames = int(enhanced_info["frames"] or 0)
    if abs(enhanced_fps - 24.0) < 0.05:
        interpolated = enhanced
        progress("RIFE non necessario: il film è già a 24 fps", 0.75)
    else:
        enhanced_cuts = _scene_boundaries(enhanced, enhanced_fps, enhanced_frames, analysis)
        progress("RIFE · interpolazione fino a 24 fps", 0.57)
        interpolated = tmp / "rife_24fps.mp4"
        expected_frames = int(round(enhanced_frames * 24.0 / enhanced_fps))
        if not _valid_video(interpolated, float(enhanced_info["duration"]), expected_frames):
            interpolate_temporal(enhanced, interpolated, enhanced_fps, enhanced_frames, enhanced_cuts, gpu,
                                 lambda m, p: progress(m, 0.57 + 0.18 * p))
        check_cancelled()
    saved("interpolazione")
    progress("DDColor · colorazione", 0.75)
    gray = interpolated
    recolored = tmp / "ddcolor.mp4"
    if not _valid_video(recolored, float(probe(gray)["duration"]), int(probe(gray)["frames"])):
        recolor_clip(gray, recolored, gpu, 8, lambda p: progress("DDColor · colorazione", 0.75 + 0.08 * p),
                     cancel_event=cancel_event)
    saved("colore")
    check_cancelled()
    cmap = CF.color_map(gray, gpu)
    for shot in cmap.get("shots", []):
        shot.update(tinta="bn", grado="giorno", protetta=False, motivo="")
    cards = [{"start": a, "end": b, "kind": "title"} for a, b in analysis.get("titles", [])]
    card_frames = CF.card_spans(gray, cards, cmap["fps"], gpu)
    anchored = tmp / "anchored.mp4"
    progress("Ancoraggio cromatico per inquadratura", 0.84)
    if not _valid_video(anchored, float(probe(gray)["duration"]), int(probe(gray)["frames"])):
        anchor_chroma(recolored, anchored, cmap, gpu)
    saved("ancoraggio_colore")
    check_cancelled()
    graded = tmp / f"graded_{output_height}h.mp4"
    if not _valid_video(graded, float(probe(gray)["duration"]), int(probe(gray)["frames"])):
        lut = tmp / "ddcolor_verdi.cube"
        CF.green_lut(lut)
        cmap["shots"] = [{**s, "protetta": False, "grado": "giorno"} for s in cmap.get("shots", [])]
        CF.finish(gray, anchored, gray, cmap, card_frames, graded, gpu,
                  lambda m, p: progress(m, 0.84 + 0.06 * p), lut_path=lut)
    saved("finitura_colore")
    progress("Finitura · upscale alla risoluzione scelta", 0.91)
    final_tmp = output.with_suffix(".part.mp4")
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-i", str(graded)]
    source_audio = bool(preserve_source_audio and source_info["has_audio"] and not (score and score.is_file()))
    if score and score.is_file():
        cmd += ["-i", str(score)]
    elif source_audio:
        cmd += ["-i", str(source)]
    cmd += ["-map", "0:v:0"]
    if score and score.is_file():
        cmd += ["-map", "1:a:0"]
    elif source_audio:
        cmd += ["-map", "1:a:0"]
    cmd += ["-vf", f"eq=saturation=0.55,scale={output_size[0]}:{output_size[1]}:flags=lanczos,setsar=1", "-r", "24",
            *video_encoder_args(17, gpu)]
    if score and score.is_file():
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    elif source_audio:
        final_duration = float(probe(graded)["duration"])
        cmd += ["-af", f"apad,atrim=duration={final_duration:.6f}", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{final_duration:.6f}"]
    cmd += ["-movflags", "+faststart", str(final_tmp)]
    _run(cmd, timeout=7200)
    final_tmp.replace(output)
    out_info = probe(output)
    if (int(out_info["width"]), int(out_info["height"])) != output_size:
        raise RuntimeError(f"dimensioni finali {out_info['width']}×{out_info['height']} diverse da {output_size[0]}×{output_size[1]}")
    if abs(float(out_info["duration"]) - float(probe(source)["duration"])) > 0.25:
        raise RuntimeError("durata finale non allineata alla sorgente")
    saved("master_video")
    comparison = _comparison(source, output, work_root / f"{output.stem}_prima_dopo.jpg",
                            float(out_info["duration"]))
    progress("Restauro completato", 1.0)
    return {"path": str(output), "comparison": str(comparison), "checkpoint_dir": str(tmp),
            "source_fps": profile["source_fps"], "restored_fps": 24, "output_size": output_size,
            "cadence": profile, "clean": clean_info, "enhanced": enhanced_info, "final": out_info,
            "color_shots": len(cmap.get("shots") or []), "titles": len(card_frames)}
