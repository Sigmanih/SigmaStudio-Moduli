"""Derivati dei media per l'editor: copie per lo scrubbing, miniature, forme d'onda, fotogrammi.

Si calcolano una volta, accanto al file sorgente, e si rigenerano solo se il
sorgente e' piu' recente. Sono tutti ricostruibili: cancellarli costa solo il
tempo di rifarli.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import numpy as np

from core.logger import get_logger

log = get_logger("creative_media_cache")

THUMB_HEIGHT = 54
THUMB_EVERY_S = 0.5
PEAKS_PER_S = 50
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _ff():
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    return ffmpeg_bin, _run, probe


def _fresh(derived: Path, source: Path) -> bool:
    return derived.is_file() and derived.stat().st_mtime >= source.stat().st_mtime


def _lock(path: Path) -> threading.Lock:
    """Due richieste per lo stesso derivato non devono calcolarlo in parallelo."""
    with _locks_guard:
        return _locks.setdefault(str(path), threading.Lock())


def scrub_copy(clip: Path) -> Path:
    """Copia con un fotogramma chiave per ogni frame: il player puo' posizionarsi
    su qualunque istante senza decodificare dal keyframe precedente."""
    out = clip.with_suffix(".scrub.mp4")
    with _lock(out):
        if not _fresh(out, clip):
            ffmpeg_bin, _run, _probe = _ff()
            _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "20", "-g", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                  "-movflags", "+faststart", str(out)])
    return out


def thumbnails(clip: Path) -> dict:
    """Striscia di miniature ogni mezzo secondo, in un'unica immagine."""
    out = clip.with_suffix(".thumbs.jpg")
    meta = clip.with_suffix(".thumbs.json")
    with _lock(out):
        if not (_fresh(out, clip) and meta.is_file()):
            ffmpeg_bin, _run, probe = _ff()
            info = probe(clip)
            count = max(1, int(info["duration"] / THUMB_EVERY_S + 0.999))
            _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-vf",
                  f"fps=1/{THUMB_EVERY_S},scale=-2:{THUMB_HEIGHT},tile={count}x1", "-frames:v", "1", "-q:v", "4", str(out)])
            w = int(round(THUMB_HEIGHT * (info["width"] or 16) / (info["height"] or 9)))
            meta.write_text(json.dumps({"count": count, "every_s": THUMB_EVERY_S, "width": w,
                                        "height": THUMB_HEIGHT}), encoding="utf-8")
    return {"path": str(out), **json.loads(meta.read_text(encoding="utf-8"))}


def peaks(media: Path) -> dict:
    """Picchi dell'audio (mono, 0-1) per disegnare la forma d'onda."""
    out = media.with_name(media.name + ".peaks.json")
    with _lock(out):
        if not _fresh(out, media):
            ffmpeg_bin, _run, _probe = _ff()
            rate = 8000
            raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(rate),
                                  "-f", "f32le", "-"], capture_output=True, timeout=300).stdout
            data = np.frombuffer(raw, dtype=np.float32)
            win = rate // PEAKS_PER_S
            n = len(data) // win
            values = np.abs(data[: n * win]).reshape(n, win).max(axis=1) if n else np.zeros(0)
            top = float(values.max()) if values.size else 0.0
            norm = (values / top) if top > 0 else values
            out.write_text(json.dumps({"per_s": PEAKS_PER_S, "peaks": [round(float(v), 3) for v in norm]}),
                           encoding="utf-8")
    return json.loads(out.read_text(encoding="utf-8"))


def frame_at(clip: Path, src_t: float, out: Path) -> Path:
    """Fotogramma esatto all'istante src_t della sorgente (PNG senza perdita)."""
    ffmpeg_bin, _run, _probe = _ff()
    out.parent.mkdir(parents=True, exist_ok=True)
    # -ss dopo -i: lento ma esatto al fotogramma, ed e' cio' che serve come ancora di H3.
    frame = max(0, int(round(src_t * 24)))
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-vf", f"select=eq(n\\,{frame})", "-fps_mode", "passthrough",
          "-frames:v", "1", str(out)])
    if not out.is_file():
        raise RuntimeError(f"fotogramma {frame} non estratto da {clip.name}")
    return out
