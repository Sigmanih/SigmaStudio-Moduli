"""Post-produzione dei clip: controllo qualita' tecnico e correzione colore.

Il controllo qualita' cerca i difetti che un modello video produce davvero e
che si misurano senza un modello visivo: fotogrammi neri, immagine congelata,
salti bruschi dentro una ripresa continua, audio muto. Un clip difettoso torna
in coda con un altro seed invece di finire nel montaggio.

La correzione colore serve alle catene di `continue`: ogni clip parte
dall'ultimo fotogramma del precedente e il colore tende a scivolare (piu'
saturo, piu' scuro) lungo la catena. Il clip viene riportato verso le
statistiche cromatiche del primo clip della catena, gradualmente, cosi' il
punto di aggancio resta invisibile.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from core.logger import get_logger

log = get_logger("creative_postprocess")


def _ff():
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, _run, probe
    return ffmpeg_bin, _run, probe


def quality_check(clip: Path, continuous: bool = True) -> list[str]:
    """Difetti tecnici del clip; lista vuota = clip accettabile."""
    ffmpeg_bin, _run, probe = _ff()
    info = probe(clip)
    issues: list[str] = []
    if info["frames"] < 5:
        return [f"solo {info['frames']} fotogrammi"]
    # Una sola passata di ffmpeg con tre rilevatori: costa meno di un secondo per clip.
    vf = "blackdetect=d=0.4:pix_th=0.06,freezedetect=n=0.002:d=1.5"
    if continuous:
        vf += ",select='gt(scene,0.45)',metadata=print:key=lavfi.scene_score"
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(clip), "-vf", vf]
    if info["has_audio"]:
        cmd += ["-af", "silencedetect=n=-55dB:d=1.5"]
    cmd += ["-f", "null", "-"]
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    log_text = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=flags).stderr
    blacks = re.findall(r"black_duration:([\d.]+)", log_text)
    if blacks:
        issues.append(f"fotogrammi neri per {sum(float(b) for b in blacks):.1f} s")
    if "freeze_start" in log_text:
        frozen = re.findall(r"freeze_duration: ([\d.]+)", log_text)
        total = sum(float(f) for f in frozen) if frozen else 0.0
        if total == 0.0 or total > 0.5 * max(info["duration"], 0.1):
            issues.append("immagine congelata")
    cuts = len(re.findall(r"lavfi\.scene_score=", log_text))
    if continuous and cuts:
        issues.append(f"{cuts} salti bruschi in una ripresa continua")
    if info["has_audio"]:
        silent = sum(float(s) for s in re.findall(r"silence_duration: ([\d.]+)", log_text))
        if silent > 0.9 * info["duration"]:
            issues.append("audio muto")
    return issues


def _read_frames(clip: Path, size: tuple[int, int]) -> np.ndarray:
    ffmpeg_bin, _run, _probe = _ff()
    w, h = size
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(clip), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=600).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[: n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)


def _read_image(path: Path, size: tuple[int, int]) -> np.ndarray:
    ffmpeg_bin, _run, _probe = _ff()
    w, h = size
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=120).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)


def color_cast(img: np.ndarray) -> np.ndarray:
    """Dominante cromatica: scarto medio di R, G, B dalla luminanza del pixel.

    Luminosita' e contrasto restano fuori di proposito: cambiano quando cambia
    cio' che e' in scena (una spinta verso un cielo chiaro), e "correggerli"
    appiattirebbe l'immagine. La deriva delle catene image-to-video e' invece
    una dominante che si accumula (tutto piu' giallo, piu' magenta).
    """
    f = img.reshape(-1, 3).astype(np.float32)
    return (f - f.mean(axis=1, keepdims=True)).mean(axis=0)


def color_drift(a: np.ndarray, b: np.ndarray) -> float:
    """Differenza di dominante cromatica fra due immagini (0-255)."""
    return float(np.abs(color_cast(a) - color_cast(b)).mean())


def color_match(clip: Path, anchor: Path, out: Path, strength: float = 0.7, min_drift: float = 2.5,
                max_drift: float = 25.0) -> dict:
    """Toglie al clip la dominante accumulata rispetto all'ancora (primo fotogramma della catena).

    La correzione cresce dal primo all'ultimo fotogramma: il primo coincide gia'
    con l'ultimo del clip precedente, e correggerlo di colpo creerebbe proprio
    il salto che si vuole evitare. Sotto `min_drift` non serve; sopra `max_drift`
    il cambio di colore e' voluto (tramonto, luce al neon) e non si tocca.
    """
    ffmpeg_bin, _run, probe = _ff()
    info = probe(clip)
    size = (int(info["width"]), int(info["height"]))
    frames = _read_frames(clip, size)
    if len(frames) < 2:
        return {"applied": False, "drift": 0.0}
    ref = _read_image(anchor, size)
    drift = color_drift(frames[-1], ref)
    if drift < min_drift or drift > max_drift:
        return {"applied": False, "drift": round(drift, 2),
                "reason": "nessuna deriva" if drift < min_drift else "cambio di colore voluto dalla scena"}
    target = color_cast(ref)
    out_frames = np.empty_like(frames)
    n = len(frames)
    for k, f in enumerate(frames):
        w = strength * (k / (n - 1))
        shift = (color_cast(f) - target) * w
        out_frames[k] = np.clip(f.astype(np.float32) - shift, 0, 255).astype(np.uint8)
    fps = int(round(info["frames"] / info["duration"])) if info["duration"] else 24
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
           "-r", str(fps), "-i", "-", "-i", str(clip), "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
           "-c:v", "libx264", "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p", str(out)]
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    proc = subprocess.run(cmd, input=out_frames.tobytes(), capture_output=True, timeout=900, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError(f"correzione colore fallita: {proc.stderr.decode(errors='replace')[-400:]}")
    after = color_drift(out_frames[-1], ref)
    return {"applied": True, "drift": round(drift, 2), "drift_after": round(after, 2)}


# ---------------------------------------------------------------------------
# Upscale con Real-ESRGAN
# ---------------------------------------------------------------------------
#
# Lanczos ingrandisce i pixel; Real-ESRGAN ricostruisce linee e texture, e per
# le immagini generate (tratti netti, superfici pulite) la differenza si vede.
# La rete gira in esrgan_worker.py dentro il venv delle voci (torch con CUDA).

# Il modello generale e non realesr-animevideov3: quello "anime" trasformava
# una staccionata in segni simili a ideogrammi e dava un tratto da cartone;
# il generale tiene il tratteggio dell'incisione e non inventa dettagli.
ESRGAN_WEIGHTS = "realesr-general-x4v3.pth"
ESRGAN_NUM_CONV = 32


def esrgan_weights() -> Path:
    from core import paths
    return paths.store_dir() / "engine_runtime" / "realesrgan" / ESRGAN_WEIGHTS


def esrgan_ready() -> bool:
    return esrgan_weights().is_file() and torch_python() is not None


def upscale_esrgan(clip: Path, target_height: int, gpu: int = 0) -> Path:
    """Copia ingrandita del clip alla misura richiesta, in cache accanto al clip."""
    ffmpeg_bin, _run, probe = _ff()
    if not esrgan_ready():
        raise RuntimeError("Real-ESRGAN non installato (Video Studio → Motori)")
    out = clip.with_suffix(f".esr{target_height}.mp4")
    if out.is_file() and out.stat().st_mtime >= clip.stat().st_mtime:
        return out
    info = probe(clip)
    w, h = int(info["width"]), int(info["height"])
    out_h = int(target_height)
    out_w = int(round(w * out_h / h / 2) * 2)
    fps = (info["frames"] / info["duration"]) if info["duration"] else 24
    tmp_out = out.with_suffix(".part.mp4")
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    decode = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-i", str(clip), "-fps_mode", "passthrough",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, creationflags=flags)
    worker = subprocess.Popen([str(torch_python()), str(Path(__file__).with_name("esrgan_worker.py")),
                               "--weights", str(esrgan_weights()), "--width", str(w), "--height", str(h),
                               "--out-width", str(out_w), "--out-height", str(out_h), "--gpu", str(gpu),
                               "--num-conv", str(ESRGAN_NUM_CONV)],
                              stdin=decode.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    decode.stdout.close()           # il worker resta l'unico lettore: se muore, ffmpeg riceve EPIPE e termina
    encode = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                               "-s", f"{out_w}x{out_h}", "-framerate", f"{fps:.6f}", "-i", "-", "-i", str(clip),
                               "-map", "0:v", "-map", "1:a?", "-c:a", "copy", "-c:v", "libx264", "-crf", "15",
                               "-preset", "medium", "-pix_fmt", "yuv420p", str(tmp_out)],
                              stdin=worker.stdout, stderr=subprocess.PIPE, creationflags=flags)
    worker.stdout.close()
    try:
        _, enc_err = encode.communicate(timeout=3600)
        w_err = worker.stderr.read()
        worker.wait(timeout=60)
        decode.wait(timeout=60)
    except subprocess.TimeoutExpired:
        for proc in (decode, worker, encode):
            proc.kill()
        raise RuntimeError("Real-ESRGAN: tempo scaduto")
    if worker.returncode != 0 or encode.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"Real-ESRGAN fallito: {(w_err or enc_err).decode(errors='replace')[-400:]}")
    got = probe(tmp_out)["frames"]
    if info["frames"] and abs(got - info["frames"]) > 1:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"Real-ESRGAN: {got} frame invece di {info['frames']}")
    tmp_out.replace(out)
    return out


# ---------------------------------------------------------------------------
# Ricolorazione di filmati in bianco e nero (DDColor, Apache 2.0)
# ---------------------------------------------------------------------------
#
# La rete e la stabilizzazione nel tempo stanno in recolor_worker.py; qui solo
# l'aggancio fra ffmpeg, il worker e la codifica, come per Real-ESRGAN.

DDCOLOR_WEIGHTS = "ddcolor_modelscope.bin"
DDCOLOR_URL = "https://huggingface.co/piddnad/ddcolor_modelscope/resolve/main/pytorch_model.bin"


def ddcolor_weights() -> Path:
    from core import paths
    return paths.store_dir() / "engine_runtime" / "ddcolor" / DDCOLOR_WEIGHTS


_PY_CHECKED: dict[str, bool] = {}


def torch_python() -> Path | None:
    """Interprete con torch e OpenCV per i worker (Real-ESRGAN, DDColor).

    Il venv delle voci se c'e', altrimenti quello del server: senza ripiego
    ESRGAN restava inutilizzabile su una macchina con torch ma senza le Voci.
    Il server non importa torch (lo fa il worker in un processo a parte): il
    controllo lancia l'interprete una volta e ricorda l'esito.
    """
    from core.modules.sigma_creative_lab.voice.runtime import venv_python
    for py in (venv_python(), Path(sys.executable)):
        if not py.is_file():
            continue
        key = str(py)
        if key not in _PY_CHECKED:
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            try:
                _PY_CHECKED[key] = subprocess.run([key, "-c", "import torch, cv2"], capture_output=True,
                                                  timeout=120, creationflags=flags).returncode == 0
            except (OSError, subprocess.TimeoutExpired) as e:
                log.warning(f"controllo di {key} per la ricolorazione fallito: {e}")
                _PY_CHECKED[key] = False
        if _PY_CHECKED[key]:
            return py
    return None


def recolor_ready() -> bool:
    return ddcolor_weights().is_file() and torch_python() is not None


def _rate_and_frames(clip: Path, info: dict) -> tuple[float, int]:
    """Fotogrammi al secondo e numero di fotogrammi, anche per file che non li dichiarano.

    I .webm (Wikimedia, Internet Archive) non hanno ne' durata ne' conteggio nel
    flusso video: con i valori di ripiego un film a 29,97 fps usciva a 24, rallentato.
    """
    if info.get("frames") and info.get("duration"):
        return info["frames"] / info["duration"], int(info["frames"])
    ffmpeg_bin, _run, _probe = _ff()
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    res = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate:format=duration", "-of", "default=nw=1", str(clip)],
                         capture_output=True, text=True, timeout=120, creationflags=flags)
    fields = dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line)
    try:
        num, den = fields.get("r_frame_rate", "24/1").split("/")
        fps = float(num) / float(den or 1)
        duration = float(fields.get("duration", "0"))
    except ValueError as e:
        raise RuntimeError(f"misure del video non leggibili ({clip.name}): {e}")
    return fps, max(1, int(round(fps * duration)))


def recolor_clip(clip: Path, out: Path, gpu: int = 0, window: int = 8, progress=None) -> dict:
    """Copia a colori del clip in `out`, con l'audio originale."""
    import threading
    ffmpeg_bin, _run, probe = _ff()
    py = torch_python()
    if not ddcolor_weights().is_file() or py is None:
        raise RuntimeError("DDColor non installato (Video Studio → Motori → DDColor)")
    info = probe(clip)
    w, h = int(info["width"]), int(info["height"])
    fps, total = _rate_and_frames(clip, info)
    tmp_out = out.with_suffix(".part.mp4")
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    decode = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-i", str(clip), "-fps_mode", "passthrough",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, creationflags=flags)
    worker = subprocess.Popen([str(py), str(Path(__file__).with_name("recolor_worker.py")),
                               "--weights", str(ddcolor_weights()), "--width", str(w), "--height", str(h),
                               "--gpu", str(gpu), "--window", str(window)],
                              stdin=decode.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    decode.stdout.close()           # il worker resta l'unico lettore: se muore, ffmpeg riceve EPIPE e termina
    encode = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                               "-s", f"{w}x{h}", "-framerate", f"{fps:.6f}", "-i", "-", "-i", str(clip),
                               "-map", "0:v", "-map", "1:a?", "-c:a", "copy", "-c:v", "libx264", "-crf", "16",
                               "-preset", "medium", "-pix_fmt", "yuv420p", str(tmp_out)],
                              stdin=worker.stdout, stderr=subprocess.PIPE, creationflags=flags)
    worker.stdout.close()
    tail: list[str] = []

    def read_progress() -> None:
        # stderr va letto mentre il worker lavora: pieno, bloccherebbe tutta la catena.
        for raw in worker.stderr:
            line = raw.decode(errors="replace").strip()
            tail[:] = (tail + [line])[-20:]
            if progress and line.startswith("frame "):
                try:
                    progress(min(1.0, int(line.split()[1]) / total))
                except ValueError:
                    pass

    reader = threading.Thread(target=read_progress, name="recolor-progress", daemon=True)
    reader.start()
    try:
        # Sulla CPU (Pi) DDColor large impiega secondi a fotogramma: margine ampio.
        _, enc_err = encode.communicate(timeout=max(3600, total * 10))
        worker.wait(timeout=60)
        decode.wait(timeout=60)
    except subprocess.TimeoutExpired:
        for proc in (decode, worker, encode):
            proc.kill()
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError("ricolorazione: tempo scaduto")
    reader.join(timeout=10)
    if worker.returncode != 0 or encode.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        detail = "\n".join(t for t in tail if not t.startswith("frame ")) or enc_err.decode(errors="replace")
        raise RuntimeError(f"ricolorazione fallita: {detail[-400:]}")
    got = probe(tmp_out)["frames"]
    if info["frames"] and abs(got - info["frames"]) > 1:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"ricolorazione: {got} fotogrammi invece di {info['frames']}")
    tmp_out.replace(out)
    return {"path": str(out), "frames": got, "width": w, "height": h}


def seedvr2_ready() -> bool:
    """Pesi di SeedVR2 nella cartella dei modelli di ComfyUI."""
    try:
        from core.modules.sigma_creative_lab.generators.adapters.comfy_seedvr import SEEDVR2_FILES
        from core.modules.sigma_creative_lab.model_downloader import discover_models_root
        root = Path(discover_models_root())
    except Exception:
        return False
    return (root / "diffusion_models" / SEEDVR2_FILES["unet"]).is_file() and \
        (root / "vae" / SEEDVR2_FILES["vae"]).is_file()


def upscale_seedvr2(clip: Path, target_height: int, gpu: int = 0) -> Path:
    """Copia ingrandita con SeedVR2 (via ComfyUI), in cache accanto al clip."""
    from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
    from core.modules.sigma_creative_lab.generators.adapters.comfy_seedvr import upscale_clip
    _ff_bin, _run, probe = _ff()
    out = clip.with_suffix(f".svr{target_height}.mp4")
    if out.is_file() and out.stat().st_mtime >= clip.stat().st_mtime:
        return out
    info = probe(clip)
    multiplier = round(int(target_height) / max(1, int(info["height"] or 0)), 4)
    tmp_out = out.with_suffix(".part.mp4")
    upscale_clip(instances.ensure(gpu), clip, tmp_out, multiplier)
    got = probe(tmp_out)
    if info["frames"] and abs(got["frames"] - info["frames"]) > 1:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"SeedVR2: {got['frames']} frame invece di {info['frames']}")
    tmp_out.replace(out)
    return out


def upscaled_source(clip: Path, target_height: int, settings: dict) -> Path:
    """Il clip da montare: la copia SeedVR2 o Real-ESRGAN se richiesta e possibile, altrimenti l'originale.

    In caso di errore si torna all'originale (lo scala poi Lanczos): un upscale
    mancato non deve far fallire un montaggio di dieci minuti.
    """
    kind = settings.get("upscaler", "esrgan")
    if kind == "seedvr2" and target_height and seedvr2_ready():
        try:
            if target_height <= int(_ff()[2](clip)["height"] or 0):
                return clip
            return upscale_seedvr2(clip, target_height, int(settings.get("upscale_gpu", 0)))
        except Exception as e:
            log.warning(f"SeedVR2 non applicato a {clip.name}, resta Lanczos: {e}")
            return clip
    if kind != "esrgan" or not target_height or not esrgan_ready():
        return clip
    try:
        if target_height <= int(_ff()[2](clip)["height"] or 0):
            return clip
        return upscale_esrgan(clip, target_height, int(settings.get("upscale_gpu", 0)))
    except Exception as e:
        log.warning(f"Real-ESRGAN non applicato a {clip.name}, resta Lanczos: {e}")
        return clip
