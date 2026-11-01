"""Immagini per i video: ritratti dei personaggi e fotogrammi chiave delle inquadrature.

Il modello video anima bene ma decide da solo lo stile: per un anime o un
cartone 3D coerente conviene che sia un modello d'immagine specializzato a
disegnare il personaggio e il primo fotogramma, e che il video parta da li'.

Modelli (licenze aperte, scelti il 2026-10-11):
  - Z-Image-Turbo (Apache 2.0): realismo, 3D, illustrazione; 8 passi.
  - Animagine XL 4.0 (OpenRAIL++): anime; vuole i tag di qualita' in coda al prompt.
  - FLUX.2 klein 4B (Apache 2.0, 2026-10-12): riceve le immagini dei personaggi come
    riferimento. Niente LoRA per personaggio: la scheda della libreria basta a
    ridisegnarlo identico in qualsiasi scena, anche con piu' personaggi insieme.
    La 9B e' non commerciale: non usarla.
"""

from __future__ import annotations

import time
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_image_gen")

MODELS = {
    "zimage": {"label": "Z-Image-Turbo (realistico, 3D, illustrazione)", "license": "Apache 2.0",
               "files": {"unet": "z_image_turbo_int8_convrot.safetensors",
                         "clip": "qwen_3_4b_fp8_mixed.safetensors", "vae": "ae.safetensors"}},
    "animagine": {"label": "Animagine XL 4.0 (anime)", "license": "OpenRAIL++",
                  "files": {"ckpt": "animagine-xl-4.0-opt.safetensors"}},
    "klein": {"label": "FLUX.2 klein 4B (personaggi dai riferimenti)", "license": "Apache 2.0",
              "files": {"unet": "flux-2-klein-4b-fp8.safetensors",
                        "clip": "qwen_3_4b_fp8_mixed.safetensors", "vae": "flux2-vae.safetensors"}},
}

#: Riferimenti per immagine: oltre, il modello confonde i personaggi e la VRAM sale.
MAX_REFS = 4

# Tag che Animagine 4 si aspetta: senza, le immagini escono piatte e sbagliate.
ANIMAGINE_POSITIVE = "masterpiece, high score, great score, absurdres"
ANIMAGINE_NEGATIVE = ("lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, fewer digits, "
                      "cropped, worst quality, low quality, low score, bad score, average score, signature, "
                      "watermark, username, blurry")


def installed(model: str) -> bool:
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    root = discover_models_root()
    if not root:
        return False
    folders = {"unet": "diffusion_models", "clip": "text_encoders", "vae": "vae", "ckpt": "checkpoints"}
    return all((Path(root) / folders[k] / name).is_file() for k, name in MODELS[model]["files"].items())


def _zimage_graph(prompt: str, width: int, height: int, seed: int, steps: int, loras: list, prefix: str) -> dict:
    f = MODELS["zimage"]["files"]
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": f["unet"], "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": f["clip"], "type": "lumina2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": f["vae"]}},
    }
    model = ["unet", 0]
    for i, lora in enumerate(loras or []):
        g[f"lora_{i}"] = {"class_type": "LoraLoaderModelOnly",
                          "inputs": {"model": model, "lora_name": lora["name"], "strength_model": lora.get("strength", 1.0)}}
        model = [f"lora_{i}", 0]
    g.update({
        "shift": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model, "shift": 3.0}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        # Modello distillato: cfg 1, il negativo non serve e si azzera.
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
        "latent": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sample": {"class_type": "KSampler", "inputs": {
            "model": ["shift", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["latent", 0],
            "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple",
            "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": prefix}},
    })
    return g


def _sdxl_graph(ckpt: str, prompt: str, negative: str, width: int, height: int, seed: int, steps: int,
                loras: list, prefix: str, cfg: float = 5.0) -> dict:
    g = {"ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}}}
    model, clip = ["ckpt", 0], ["ckpt", 1]
    for i, lora in enumerate(loras or []):
        g[f"lora_{i}"] = {"class_type": "LoraLoader", "inputs": {
            "model": model, "clip": clip, "lora_name": lora["name"],
            "strength_model": lora.get("strength", 1.0), "strength_clip": lora.get("strength", 1.0)}}
        model, clip = [f"lora_{i}", 0], [f"lora_{i}", 1]
    g.update({
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": negative}},
        "latent": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sample": {"class_type": "KSampler", "inputs": {
            "model": model, "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["latent", 0],
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler_ancestral", "scheduler": "normal",
            "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": prefix}},
    })
    return g


def _klein_graph(prompt: str, refs: list[str], width: int, height: int, seed: int, prefix: str) -> dict:
    """FLUX.2 klein distillato (4 passi) con le immagini dei personaggi come riferimento (template ufficiale)."""
    f = MODELS["klein"]["files"]
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": f["unet"], "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": f["clip"], "type": "flux2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": f["vae"]}},
        "pos0": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg0": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos0", 0]}},
    }
    pos, neg = ["pos0", 0], ["neg0", 0]
    for i, name in enumerate(refs[:MAX_REFS]):
        # Ogni riferimento a ~1 megapixel, codificato e agganciato sia al positivo sia al negativo.
        g[f"ref_{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[f"ref_scale_{i}"] = {"class_type": "ImageScaleToTotalPixels",
                               "inputs": {"image": [f"ref_{i}", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                          "resolution_steps": 16}}
        g[f"ref_lat_{i}"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"ref_scale_{i}", 0], "vae": ["vae", 0]}}
        g[f"pos{i + 1}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [f"ref_lat_{i}", 0]}}
        g[f"neg{i + 1}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [f"ref_lat_{i}", 0]}}
        pos, neg = [f"pos{i + 1}", 0], [f"neg{i + 1}", 0]
    g.update({
        "guider": {"class_type": "CFGGuider", "inputs": {"model": ["unet", 0], "positive": pos, "negative": neg, "cfg": 1.0}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sigmas": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": width, "height": height}},
        "latent": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0], "sigmas": ["sigmas", 0],
            "latent_image": ["latent", 0]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": prefix}},
    })
    return g


def build_graph(model: str, prompt: str, negative: str = "", width: int = 1024, height: int = 1024,
                seed: int = 0, loras: list | None = None, prefix: str = "sigma/img", refs: list | None = None) -> dict:
    # Multipli di 64: entrambi i modelli lavorano a blocchi e sbordano con misure qualsiasi.
    width, height = max(512, width // 64 * 64), max(512, height // 64 * 64)
    seed = int(seed) & 0xFFFFFFFFFFFFFFFF
    if model == "klein":
        return _klein_graph(prompt, list(refs or []), width, height, seed, prefix)
    if model == "zimage":
        return _zimage_graph(prompt, width, height, seed, 8, loras or [], prefix)
    if model == "animagine":
        full = f"{prompt.strip().rstrip(',')}, {ANIMAGINE_POSITIVE}"
        neg = ", ".join(x for x in (negative, ANIMAGINE_NEGATIVE) if x)
        return _sdxl_graph(MODELS["animagine"]["files"]["ckpt"], full, neg, width, height, seed, 28, loras or [], prefix)
    raise ValueError(f"modello d'immagine sconosciuto: {model}")


async def generate(model: str, prompt: str, out: Path, negative: str = "", width: int = 1024, height: int = 1024,
                   seed: int | None = None, loras: list | None = None, gpu: int = 0, refs: list | None = None) -> dict:
    """Genera un'immagine con l'istanza ComfyUI della GPU indicata e la salva in `out`.

    `refs` (solo klein): immagini dei personaggi da ridisegnare identici.
    """
    from core.modules.sigma_creative_lab.video.production import ComfyClipEngine
    if not installed(model):
        raise RuntimeError(f"{MODELS[model]['label']} non installato (Video Studio → Motori)")
    engine = ComfyClipEngine({"gpu": gpu})
    await engine._ensure()
    seed = int(time.time() * 1000) % 2**31 if seed is None else int(seed)
    names = [await engine.backend.upload_image(Path(r).read_bytes(), f"ref_{Path(r).parent.name}_{Path(r).name}")
             for r in (refs or [])[:MAX_REFS]]
    t0 = time.monotonic()
    data, _name = await engine._run_watched(build_graph(model, prompt, negative, width, height, seed, loras,
                                                        f"sigma/img_{out.stem}", names), None, 900)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {"path": str(out), "seed": seed, "seconds": round(time.monotonic() - t0, 1), "model": model}
