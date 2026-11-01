"""Colonna sonora continua per le produzioni lunghe.

MiniMax H3 genera l'audio clip per clip: rumori e dialoghi tornano bene, la
musica no, perche' ogni clip ne inventa una diversa e a ogni taglio cambia
tonalita' e tempo. La musica si genera quindi a parte con ACE-Step 1.5 (via
ComfyUI), un brano per scena con tonalita' e BPM comuni, e si mixa sotto
l'audio dei clip, che le passa sopra quando c'e' un suono (ducking).
"""

from __future__ import annotations

import time
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_soundtrack")

ACE_CHECKPOINT = "ace_step_1.5_turbo_aio.safetensors"
MAX_SEGMENT_S = 240.0
CROSSFADE_S = 2.0

DEFAULT_SOUNDTRACK = {
    "enabled": False,
    "tags": "",                 # vuoto = stile audio della bibbia
    "bpm": 90,
    "keyscale": "D minor",
    "timesignature": "4",
    "instrumental": True,
    "music_db": -14.0,          # volume della musica rispetto al mix
    "clip_db": 0.0,             # volume dell'audio generato da H3
    "duck": True,               # la musica si abbassa sotto i suoni dei clip
}


def build_ace_step(tags: str, seconds: float, seed: int, bpm: int = 90, keyscale: str = "D minor",
                   timesignature: str = "4", lyrics: str = "", prefix: str = "sigma/music") -> dict:
    """Grafo API ACE-Step 1.5 turbo, ricavato dal template `audio_ace_step_1_5_checkpoint.json`."""
    return {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ACE_CHECKPOINT}},
        "enc": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["ckpt", 1], "tags": tags, "lyrics": lyrics or "[Instrumental]", "seed": int(seed),
            "bpm": int(bpm), "duration": float(seconds), "timesignature": str(timesignature), "language": "en",
            "keyscale": keyscale, "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85,
            "top_p": 0.9, "top_k": 0, "min_p": 0.0}},
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["enc", 0]}},
        "shift": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["ckpt", 0], "shift": 3.0}},
        "latent": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "sample": {"class_type": "KSampler", "inputs": {
            "model": ["shift", 0], "seed": int(seed), "steps": 8, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "positive": ["enc", 0], "negative": ["neg", 0], "latent_image": ["latent", 0],
            "denoise": 1.0}},
        "decode": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2]}},
        "save": {"class_type": "SaveAudio", "inputs": {"audio": ["decode", 0], "filename_prefix": prefix}},
    }


def scene_segments(prod: dict, fps: int = 24) -> list[dict]:
    """Durata reale di ogni scena nel montaggio (frame duplicati dei `continue` esclusi)."""
    segments: list[dict] = []
    done = [s for s in prod["shots"] if s.get("status") == "done"]
    for i, shot in enumerate(done):
        frames = int(shot.get("frames") or 0) - (1 if shot.get("transition") == "continue" and i > 0 else 0)
        seconds = max(0.0, frames / fps)
        scene = shot.get("scene") or "scena"
        if segments and segments[-1]["scene"] == scene:
            segments[-1]["seconds"] += seconds
        else:
            segments.append({"scene": scene, "seconds": seconds})
    # Scene troppo lunghe si dividono: oltre qualche minuto il brano perde coerenza.
    out = []
    for seg in segments:
        remaining = seg["seconds"]
        while remaining > MAX_SEGMENT_S:
            out.append({"scene": seg["scene"], "seconds": MAX_SEGMENT_S})
            remaining -= MAX_SEGMENT_S - CROSSFADE_S
        out.append({"scene": seg["scene"], "seconds": remaining})
    return [s for s in out if s["seconds"] >= 1.0]


async def generate_soundtrack(prod: dict, work_dir: Path, backend, progress=None) -> Path:
    """Genera i brani delle scene e li unisce con dissolvenze incrociate in un WAV."""
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, _run
    cfg = {**DEFAULT_SOUNDTRACK, **(prod.get("soundtrack") or {})}
    bible = prod.get("bible") or {}
    base_tags = cfg["tags"] or bible.get("audio_style") or "cinematic orchestral score"
    seed0 = int(prod["settings"].get("seed", 1000))
    work_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    segments = scene_segments(prod, int(prod["settings"].get("fps", 24)))
    if not segments:
        raise RuntimeError("nessuna scena completata per cui comporre la musica")
    for k, seg in enumerate(segments):
        target = work_dir / f"music_{k:03d}.flac"
        if target.is_file():
            parts.append(target)                 # gia' generato: la ripresa non lo rifa'
            continue
        if progress:
            progress(f"Musica {k + 1}/{len(segments)}: {seg['scene']}")
        # La scena colora il brano, tonalita' e tempo restano comuni: i passaggi
        # fra un brano e l'altro restano musicali.
        tags = f"{base_tags}, {seg['scene']}" if cfg["instrumental"] else base_tags
        seconds = seg["seconds"] + (CROSSFADE_S if k < len(segments) - 1 else 0.0)
        graph = build_ace_step(tags, seconds, seed0 + 101 * k, cfg["bpm"], cfg["keyscale"], cfg["timesignature"],
                               prefix=f"sigma/{prod['id']}/music_{k:03d}")
        t0 = time.monotonic()
        data, _name = await backend.run({"workflow": graph}, timeout_s=1800)
        raw = work_dir / f"music_{k:03d}.raw"
        raw.write_bytes(data)
        # Normalizza formato e durata esatta: ACE-Step puo' sforare di qualche frazione di secondo.
        _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(raw), "-t", f"{seconds:.3f}", "-ar", "48000", "-ac", "2",
              str(target)])
        raw.unlink(missing_ok=True)
        log.info(f"brano {k + 1}/{len(segments)} ({seconds:.0f} s) in {time.monotonic() - t0:.0f} s")
        parts.append(target)
    out = work_dir / "soundtrack.wav"
    if len(parts) == 1:
        _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(parts[0]), str(out)])
        return out
    # Catena di acrossfade: ogni brano entra mentre il precedente sfuma.
    inputs, chain, last = [], [], "[0:a]"
    for p in parts:
        inputs += ["-i", str(p)]
    for k in range(1, len(parts)):
        label = f"[x{k}]"
        chain.append(f"{last}[{k}:a]acrossfade=d={CROSSFADE_S}:c1=tri:c2=tri{label}")
        last = label
    _run([ffmpeg_bin(), "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", last, str(out)])
    return out


AMBIENCE_SECONDS = 10.0


def ambience_prompt(location: dict) -> str:
    """Il luogo vuoto, perche' LTX ne dia solo il suono d'ambiente."""
    desc = str(location.get("description") or location.get("name") or "").strip().rstrip(".")
    return (f"{desc}. A calm static wide shot of this place, nobody in the frame. Audio: only the natural ambient "
            f"sound of this place, continuous and gentle, like a field recording: no music, no speech, no voices.")


async def generate_ambience(prod: dict, work_dir: Path, backend, progress=None) -> dict:
    """Un tappeto sonoro per ogni luogo della pre-produzione, generato con l'audio di LTX.

    Nelle inquadrature con battuta l'audio e' solo la voce del personaggio: senza un ambiente sotto,
    il prato del picnic diventava muto appena qualcuno parlava. Niente modelli in piu': LTX genera
    gia' audio e video insieme, qui si tiene solo l'audio di una ripresa del posto vuoto.
    """
    import re
    from core.modules.sigma_creative_lab.generators.adapters.comfy_ltx import build_ltx_video, ltx_frame_count
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, _run
    locations = [x for x in ((prod.get("bible") or {}).get("pre") or {}).get("locations") or [] if x.get("name")]
    used = {str(sh.get("location") or "").strip().lower() for sh in prod.get("shots") or [] if sh.get("dialogue")}
    work_dir.mkdir(parents=True, exist_ok=True)
    out: dict = dict(prod.get("ambience") or {})
    for k, loc in enumerate(x for x in locations if x["name"].strip().lower() in used):
        key = loc["name"].strip().lower()
        target = work_dir / f"{re.sub(r'[^a-z0-9]+', '_', key).strip('_') or 'luogo'}.wav"
        if out.get(key) == str(target) and target.is_file():
            continue
        if progress:
            progress(f"Ambiente sonoro: {loc['name']}")
        graph = build_ltx_video({"prompt": ambience_prompt(loc), "width": 640, "height": 384,
                                 "length": ltx_frame_count(AMBIENCE_SECONDS), "fps": 24,
                                 "seed": int(prod["settings"].get("seed", 1000)) + 77 * k,
                                 "filename_prefix": f"sigma/{prod['id']}/ambience_{k}"})
        data, _name = await backend.run({"workflow": graph}, timeout_s=1800)
        raw = work_dir / f"amb_{k}.mp4"
        raw.write_bytes(data)
        # Volume uniforme fra i luoghi: il montaggio poi lo mette sotto la voce.
        _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(raw), "-vn", "-af", "loudnorm=I=-23:TP=-2:LRA=7",
              "-ar", "48000", "-ac", "2", str(target)])
        raw.unlink(missing_ok=True)
        out[key] = str(target)
    return out


def mix_soundtrack(video: Path, music: Path, out: Path, music_db: float = -14.0, clip_db: float = 0.0,
                   duck: bool = True) -> Path:
    """Mette la musica sotto l'audio dei clip, abbassandola quando i clip suonano."""
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, _run
    clip = f"[0:a]volume={clip_db}dB,asplit=2[clip][key]"
    mus = f"[1:a]volume={music_db}dB,apad[mus]"
    if duck:
        mix = ("[mus][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[ducked];"
               "[clip][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        mix = "[clip][mus]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(video), "-i", str(music), "-filter_complex",
          f"{clip};{mus};{mix}", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
          "-movflags", "+faststart", str(out)], timeout=7200)
    return out
