"""SeedVR2 (ByteDance, Apache 2.0): upscaling video in un passo, dal template ufficiale di ComfyUI.

Real-ESRGAN ingrandisce fotogramma per fotogramma e su un'animazione 3D affila i bordi ma non
aggiunge dettaglio coerente nel tempo. SeedVR2 e' un modello di diffusione video addestrato al
restauro: un solo passo, coerente fra i fotogrammi. Ricostruito dal template
`utility_seedvr2_3b_int8_upscale_video.json` (ComfyUI 0.39) senza gli interruttori della UI.

Il blocco a fette temporali ("auto") sceglie da se' quanti fotogrammi stanno nella VRAM libera.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import requests

from core.logger import get_logger

log = get_logger("creative_seedvr2")

SEEDVR2_FILES = {"unet": "seedvr2_3b_int8_convrot.safetensors", "vae": "seedvr2_ema_vae_fp16.safetensors"}


def build_seedvr2(p: dict) -> dict:
    """Grafo API. Chiavi: video (nome in input/), multiplier, seed, color ("lab"), filename_prefix."""
    # Tasselli da 1024: con quelli del template (512, sovrapposti di 128) il VAE impiegava 90 s per un
    # secondo di video a 1080p; cosi' 56.
    tiles = {"tile_size": 1024, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}
    return {
        "load": {"class_type": "LoadVideo", "inputs": {"file": p["video"]}},
        "parts": {"class_type": "GetVideoComponents", "inputs": {"video": ["load", 0]}},
        "resize": {"class_type": "ResizeImageMaskNode", "inputs": {
            "input": ["parts", 0], "resize_type": "scale by multiplier",
            "resize_type.multiplier": float(p.get("multiplier", 1.5)), "scale_method": "lanczos"}},
        "pre": {"class_type": "SeedVR2Preprocess", "inputs": {"resized_images": ["resize", 0]}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": SEEDVR2_FILES["vae"]}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": SEEDVR2_FILES["unet"], "weight_dtype": "default"}},
        "enc": {"class_type": "VAEEncodeTiled", "inputs": {"pixels": ["pre", 0], "vae": ["vae", 0], **tiles}},
        # Blocchi fissi da 21 fotogrammi: "auto" con i modelli del render ancora in VRAM sceglieva 1 fotogramma
        # per volta, piu' lento e senza la coerenza temporale che e' il motivo di usare SeedVR2.
        "chunk": {"class_type": "SeedVR2TemporalChunk", "inputs": {
            "latent": ["enc", 0], "temporal_overlap": 1, "chunking_mode": "manual",
            "chunking_mode.frames_per_chunk": int(p.get("frames_per_chunk", 21))}},
        "cond": {"class_type": "SeedVR2Conditioning", "inputs": {"model": ["unet", 0], "vae_conditioning": ["chunk", 0]}},
        "sample": {"class_type": "KSampler", "inputs": {
            "model": ["unet", 0], "seed": int(p.get("seed", 42)), "steps": 1, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "positive": ["cond", 0], "negative": ["cond", 1], "latent_image": ["chunk", 0],
            "denoise": 1.0}},
        "merge": {"class_type": "SeedVR2TemporalMerge", "inputs": {"latents": ["sample", 0], "temporal_overlap": ["chunk", 1]}},
        "dec": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["merge", 0], "vae": ["vae", 0], **tiles}},
        # "lab": i colori restano quelli del clip (con "none" SeedVR2 virava leggermente il tono).
        "post": {"class_type": "SeedVR2PostProcessing", "inputs": {
            "images": ["dec", 0], "original_resized_images": ["resize", 0],
            "color_correction_method": p.get("color", "lab")}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["post", 0], "audio": ["parts", 1], "fps": ["parts", 2]}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0],
                                                        "filename_prefix": p.get("filename_prefix", "sigma/seedvr2"),
                                                        "format": "mp4", "codec": "auto"}},
    }


def upscale_clip(base_url: str, clip: Path, out: Path, multiplier: float, timeout_s: float = 1800.0) -> Path:
    """Esegue il grafo su un'istanza ComfyUI gia' avviata, in modo sincrono (lo chiama il montaggio)."""
    base = base_url.rstrip("/")
    name = f"seedvr_{uuid.uuid4().hex[:10]}{clip.suffix}"
    with open(clip, "rb") as fh:
        r = requests.post(f"{base}/upload/image", files={"image": (name, fh, "video/mp4")},
                          data={"overwrite": "true"}, timeout=120)
    r.raise_for_status()
    uploaded = r.json().get("name", name)
    graph = build_seedvr2({"video": uploaded, "multiplier": multiplier, "filename_prefix": f"sigma/seedvr2/{clip.stem}"})
    r = requests.post(f"{base}/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"SeedVR2 rifiutato da ComfyUI: {r.text[:400]}")
    pid = r.json()["prompt_id"]
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        h = requests.get(f"{base}/history/{pid}", timeout=30).json().get(pid)
        if h:
            status = h.get("status") or {}
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages") or [] if m and m[0] == "execution_error"]
                raise RuntimeError(f"SeedVR2 fallito: {str(msgs)[-400:]}")
            for node in (h.get("outputs") or {}).values():
                for item in node.get("images") or node.get("videos") or node.get("gifs") or []:
                    # Solo cio' che ComfyUI ha scritto: anche LoadVideo compare fra le uscite, come anteprima
                    # del video d'ingresso, e scaricando quello l'"upscale" restava alla misura originale.
                    if item.get("type", "output") == "output" and                             str(item.get("filename", "")).endswith((".mp4", ".webm", ".mov")):
                        v = requests.get(f"{base}/view", params={"filename": item["filename"],
                                                                 "subfolder": item.get("subfolder", ""),
                                                                 "type": item.get("type", "output")}, timeout=300)
                        v.raise_for_status()
                        out.write_bytes(v.content)
                        log.info(f"SeedVR2 {clip.name}: {time.monotonic() - t0:.0f} s")
                        return out
            if status.get("completed"):
                raise RuntimeError("SeedVR2: nessun video in uscita")
        time.sleep(2)
    raise RuntimeError("SeedVR2: tempo scaduto")
