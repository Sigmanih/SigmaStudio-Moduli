"""Controlli conservativi sui difetti misurabili della musica generata."""

from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

import numpy as np

QUALITY_REVISION = 1
SAMPLE_RATE = 2000


def inspect_samples(samples: np.ndarray, seconds: float, sr: int = SAMPLE_RATE) -> dict:
    """Rileva audio corto, silenzi e loop quasi identici prolungati; non giudica lo stile."""
    a = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not math.isfinite(seconds) or seconds <= 0 or not np.isfinite(a).all():
        raise ValueError("Audio o durata della musica non validi")
    a = a[:math.ceil(seconds * sr)]
    blocks = len(a) // sr
    rms = np.sqrt((a[:blocks * sr].reshape(-1, sr) ** 2).mean(axis=1)) if blocks else np.array([])
    quiet = rms < 10 ** (-45 / 20)
    silent, run = max(0.0, seconds - len(a) / sr), 0
    for q in [*quiet, False]:
        if q:
            run += 1
        else:
            silent += run if run >= 2 else 0
            run = 0

    # Un tema puo' ritornare: si rifiuta solo la copia quasi esatta, protratta
    # per almeno trenta secondi. L'autocorrelazione FFT evita confronti quadratici.
    window, hop = 20 * sr, 10 * sr
    repeated, streak, longest = set(), 0, 0
    for start in range(0, max(0, len(a) - window + 1), hop):
        x = a[start:start + window].astype(np.float64)
        x -= x.mean()
        energy = np.cumsum(np.r_[0.0, x * x])
        if energy[-1] / window < 1e-7:
            streak = 0
            continue
        n = 1 << (2 * window - 1).bit_length()
        spectrum = np.fft.rfft(x, n)
        corr = np.fft.irfft(spectrum * spectrum.conj(), n)[:window]
        lags = np.arange(sr, 8 * sr + 1)
        denom = np.sqrt(energy[window - lags] * (energy[-1] - energy[lags]))
        peak = float(np.max(corr[lags] / np.maximum(denom, 1e-12)))
        if peak >= 0.97:
            streak += 1
            longest = max(longest, 20 + (streak - 1) * 10)
            repeated.update(range(start // sr, (start + window) // sr))
        else:
            streak = 0
    issues = []
    if len(a) / sr < seconds - 0.3:
        issues.append("durata_insufficiente")
    if silent > 8:
        issues.append("silenzi_prolungati")
    if longest >= 30:
        issues.append("loop_prolungato")
    return {"revision": QUALITY_REVISION, "duration": round(len(a) / sr, 3),
            "silent_s": round(silent, 3), "repeated_s": len(repeated), "longest_loop_s": longest,
            "fingerprint": hashlib.sha256(a.tobytes()).hexdigest(), "issues": issues, "ok": not issues}


def inspect_audio(audio: Path, seconds: float) -> dict:
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin

    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    result = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(audio), "-t", f"{seconds:.6f}",
                             "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
                            capture_output=True, timeout=600, creationflags=flags)
    if result.returncode:
        raise RuntimeError(f"Impossibile verificare la musica: {result.stderr.decode(errors='replace')[-500:]}")
    return inspect_samples(np.frombuffer(result.stdout, dtype="<f4"), seconds)


def source_music_filter(tracks: list[dict]) -> str:
    """La musica di restauro sostituisce l'originale solo dove e' presente e udibile."""
    spans = []
    for track in tracks:
        if track.get("kind") != "music" or track.get("mute"):
            continue
        for clip in track.get("clips") or []:
            if not (clip.get("meta") or {}).get("restoration_score"):
                continue
            if not Path(str(clip.get("src") or "")).is_file():
                continue
            start = float(clip.get("start", 0))
            end = start + float(clip["src_out"]) - float(clip.get("src_in", 0))
            if math.isfinite(start) and math.isfinite(end) and end > max(0, start):
                spans.append((max(0, start), end))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    if not merged:
        return "anull"
    enabled = "+".join(f"between(t,{a:.6f},{b:.6f})" for a, b in merged)
    return f"volume=0:enable='{enabled}'"
