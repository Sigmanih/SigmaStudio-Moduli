"""Grafo ComfyUI (formato API) per MiniMax H3, ricavato dal template ufficiale.

Il template distribuito con ComfyUI (`video_minimax_h3_i2v.json`) e' in formato
UI con un sottografo: non si puo' inviare a /prompt. Qui lo stesso grafo e'
costruito nodo per nodo, con primo e ultimo frame opzionali: senza immagini e'
text-to-video, con la prima e' image-to-video, con entrambe first/last-frame.
Con `ref_images` diventa reference-to-video (`video_minimax_h3_r2v.json`): i
personaggi delle immagini restano riconoscibili, e serve il DiT ref2va.
"""

from __future__ import annotations

#: Varianti del DiT pubblicate da Comfy-Org, per formato dei pesi. Su Blackwell
#: int8 e fp8 usano tensor core nativi. w6a8 occupa meno VRAM ma ComfyUI 0.31.1
#: rifiuta il formato (`w6a8_int8`): serve una versione piu' recente.
H3_UNETS = {
    "int8": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "fp8": "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
    "w6a8": "minimax_h3_fl2va_pruned_w6a8.safetensors",
}
H3_REF_UNETS = {
    "int8": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "fp8": "minimax_h3_ref2va_pruned_fp8_scaled.safetensors",
    "w6a8": "minimax_h3_ref2va_pruned_w6a8.safetensors",
}

H3_FILES = {
    "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
}


def h3_frame_count(seconds: float, fps: int = 24) -> int:
    """Stessa formula del template: H3 accetta solo lunghezze 17k + 5."""
    n = max(5, round(seconds * fps))
    return n + (5 - n % 17) % 17


def build_h3_video(p: dict) -> dict:
    """Grafo API. Chiavi di `p`: prompt, width, height, length, seed, steps,
    sampler, scheduler, first_frame, last_frame (nomi in input/), unet, clip,
    vae, audio_vae, filename_prefix, loras [{name, strength}]."""
    files = {**H3_FILES, **{k: p[k] for k in H3_FILES if p.get(k)}}
    refs = [r for r in (p.get("ref_images") or []) if r]
    if p.get("ref_audios") and not refs:
        raise ValueError("gli audio di riferimento richiedono la modalita' R2V (almeno un'immagine di riferimento)")
    if not p.get("unet"):
        w = p.get("weights", "int8")
        variants = H3_REF_UNETS if refs else H3_UNETS
        if w in variants:
            files["unet"] = variants[w]
        elif w:
            files["unet"] = w
        else:
            files["unet"] = variants["int8"]
    g: dict = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": files["unet"], "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": files["clip"], "type": "minimax", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["vae"]}},
        "audio_vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["audio_vae"]}},
    }
    model_ref = ["unet", 0]
    for i, lora in enumerate(p.get("loras") or []):
        node = f"lora_{i}"
        g[node] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": model_ref, "lora_name": lora["name"], "strength_model": float(lora.get("strength", 1.0))}}
        model_ref = [node, 0]
    if p.get("easycache"):
        # Riusa l'uscita del DiT negli step in cui cambia poco: meno passaggi
        # completi del modello, a costo di una piccola perdita di dettaglio.
        g["easycache"] = {"class_type": "EasyCache", "inputs": {
            "model": model_ref, "reuse_threshold": float(p.get("easycache_threshold", 0.2)),
            "start_percent": float(p.get("easycache_start", 0.15)), "end_percent": float(p.get("easycache_end", 0.95)),
            "verbose": False}}
        model_ref = ["easycache", 0]

    cond_inputs = {
        "clip": ["clip", 0], "vae": ["vae", 0], "prompt": p["prompt"],
        "width": int(p.get("width", 864)), "height": int(p.get("height", 480)), "length": int(p.get("length", 124)),
    }
    if refs:
        # Reference-to-video: i riferimenti non si combinano con primo/ultimo frame.
        cond_inputs.update({"audio_vae": ["audio_vae", 0], "ref_image_size": p.get("ref_image_size", "match")})
        for i, name in enumerate(refs[:9]):
            g[f"ref_{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            cond_inputs[f"ref_images.ref_image_{i}"] = [f"ref_{i}", 0]
        # Audio di riferimento (voce di un personaggio): nel prompt e' <Audio 1>, <Audio 2>...
        for i, name in enumerate((p.get("ref_audios") or [])[:3]):
            g[f"ref_audio_{i}"] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
            cond_inputs[f"ref_audios.ref_audio_{i}"] = [f"ref_audio_{i}", 0]
        g["cond"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": cond_inputs}
    else:
        for key in ("first_frame", "last_frame"):
            if p.get(key):
                g[f"load_{key}"] = {"class_type": "LoadImage", "inputs": {"image": p[key]}}
                cond_inputs[key] = [f"load_{key}", 0]
        g["cond"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": cond_inputs}

    g.update({
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(p.get("seed", 0)) & 0xFFFFFFFFFFFFFFFF}},
        "guider": {"class_type": "BasicGuider", "inputs": {"model": model_ref, "conditioning": ["cond", 0]}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": p.get("sampler", "res_multistep")}},
        "sigmas": {"class_type": "BasicScheduler",
                   "inputs": {"model": model_ref, "scheduler": p.get("scheduler", "simple"),
                              "steps": int(p.get("steps", 20)), "denoise": 1.0}},
        "sample": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0],
                              "sigmas": ["sigmas", 0], "latent_image": ["cond", 1]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "decode_audio": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sample", 0], "vae": ["audio_vae", 0]}},
        "video": {"class_type": "CreateVideo",
                  "inputs": {"images": ["decode", 0], "audio": ["decode_audio", 0], "fps": float(p.get("fps", 24))}},
        "save": {"class_type": "SaveVideo",
                 "inputs": {"video": ["video", 0], "filename_prefix": p.get("filename_prefix", "sigma/h3"),
                            "format": "mp4", "codec": "auto"}},
    })
    return g
