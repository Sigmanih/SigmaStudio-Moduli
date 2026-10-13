"""Grafo ComfyUI (formato API) per LTX-2.5 distillato, ricavato dal blueprint ufficiale.

Il blueprint "Image to Video (LTX-2.5)" di ComfyUI 0.39 e' un sottografo in
formato UI: qui e' ricostruito nodo per nodo. Due passaggi come consiglia
Lightricks: il primo a meta' risoluzione genera video e audio insieme, poi
l'upscaler latente x2 e un secondo passaggio breve rifiniscono i dettagli.
Senza immagini e' text-to-video; con `first_frame` image-to-video; con anche
`last_frame` il video arriva a quel fotogramma (guide di LTXVAddGuide).
Con `audio` (template ufficiale ia2v) l'audio e' dato e resta fermo: il modello
genera solo il video, con labiale e gesti sincronizzati sulla battuta. E' cosi'
che i personaggi parlano con le voci della libreria di Voice Studio.

Licenza dei pesi: LTX-2 Community License, senza esclusioni territoriali
(a differenza di MiniMax H3, che esclude l'UE).
"""

from __future__ import annotations

LTX_FILES = {
    "unet": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "clip": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    "vae": "ltx-2.5-video-vae-bf16.safetensors",
    "audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
    "upscaler": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
}

# Sigma del modello distillato, dal blueprint: 8 passi al primo giro, 3 al secondo.
STAGE1_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
STAGE2_SIGMAS = "0.85, 0.7250, 0.4219, 0.0"
NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly"


def ltx_frame_count(seconds: float, fps: int = 24) -> int:
    """LTX accetta solo lunghezze 8k + 1 (121 = 5 s a 24 fps)."""
    n = max(9, round(seconds * fps) + 1)
    return n + (1 - n % 8) % 8


def ltx_size(width: int, height: int) -> tuple[int, int]:
    """Dimensioni finali multiple di 64: la meta' del primo passaggio deve restare multipla di 32."""
    snap = lambda v: max(256, int(round(v / 64)) * 64)  # noqa: E731
    return snap(width), snap(height)


def build_ltx_video(p: dict) -> dict:
    """Grafo API. Chiavi di `p`: prompt, negative, width, height, length, fps, seed,
    first_frame, last_frame, audio (nomi in input/), audio_start, filename_prefix, guide_strength,
    loras [{name, strength}] (stile o movimento, famiglia LTX su Civitai)."""
    files = {**LTX_FILES, **{k: p[k] for k in LTX_FILES if p.get(k)}}
    width, height = ltx_size(int(p.get("width", 1280)), int(p.get("height", 704)))
    length = int(p.get("length", 121))
    fps = float(p.get("fps", 24))
    seed = int(p.get("seed", 0)) & 0xFFFFFFFFFFFFFFFF
    first, last = p.get("first_frame"), p.get("last_frame")
    strength = float(p.get("guide_strength", 0.7))

    g: dict = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": files["unet"], "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": files["clip"], "type": "ltxv", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["vae"]}},
        "audio_vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["audio_vae"]}},
        "upscaler": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": files["upscaler"]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p["prompt"]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p.get("negative") or NEGATIVE}},
        "cond": {"class_type": "LTXVConditioning",
                 "inputs": {"positive": ["pos", 0], "negative": ["neg", 0], "frame_rate": fps}},
        "latent": {"class_type": "EmptyLTXVLatentVideo",
                   "inputs": {"width": width // 2, "height": height // 2, "length": length, "batch_size": 1}},
    }
    if p.get("audio"):
        # Maschera 0 = latente audio da non toccare: la voce resta quella fornita, parola per parola.
        g.update({
            "load_audio": {"class_type": "LoadAudio", "inputs": {"audio": p["audio"]}},
            "trim_audio": {"class_type": "TrimAudioDuration",
                           "inputs": {"audio": ["load_audio", 0], "start_index": float(p.get("audio_start", 0.0)),
                                      "duration": (length - 1) / fps}},
            "encode_audio": {"class_type": "LTXVAudioVAEEncode",
                             "inputs": {"audio": ["trim_audio", 0], "audio_vae": ["audio_vae", 0]}},
            "audio_mask": {"class_type": "SolidMask", "inputs": {"value": 0.0, "width": width, "height": height}},
            "audio_latent": {"class_type": "SetLatentNoiseMask",
                             "inputs": {"samples": ["encode_audio", 0], "mask": ["audio_mask", 0]}},
        })
    else:
        g["audio_latent"] = {"class_type": "LTXVEmptyLatentAudio",
                             "inputs": {"frames_number": length, "frame_rate": fps, "batch_size": 1,
                                        "audio_vae": ["audio_vae", 0]}}
    pos, neg, video1 = ["cond", 0], ["cond", 1], ["latent", 0]
    model = ["unet", 0]
    for i, lora in enumerate(p.get("loras") or []):
        g[f"lora_{i}"] = {"class_type": "LoraLoaderModelOnly",
                          "inputs": {"model": model, "lora_name": lora["name"],
                                     "strength_model": float(lora.get("strength", 1.0))}}
        model = [f"lora_{i}", 0]

    def image(name: str, key: str) -> list:
        g[f"load_{key}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[f"scale_{key}"] = {"class_type": "ImageScale", "inputs": {"image": [f"load_{key}", 0], "upscale_method": "lanczos",
                                                                    "width": width, "height": height, "crop": "center"}}
        # Compressione simulata: il modello e' addestrato su fotogrammi da video, non su immagini pulite.
        g[f"prep_{key}"] = {"class_type": "LTXVPreprocess", "inputs": {"image": [f"scale_{key}", 0], "img_compression": 18}}
        return [f"prep_{key}", 0]

    first_img = image(first, "first") if first else None
    last_img = image(last, "last") if last else None
    if first_img and not last_img:
        g["i2v1"] = {"class_type": "LTXVImgToVideoInplace",
                     "inputs": {"vae": ["vae", 0], "image": first_img, "latent": video1, "strength": strength, "bypass": False}}
        video1 = ["i2v1", 0]
    elif last_img:
        # Primo e ultimo fotogramma come guide: si aggiungono in coda al latente e si tolgono prima del decode.
        for key, img, idx in (("first", first_img, 0), ("last", last_img, -1)):
            if img is None:
                continue
            node = f"guide1_{key}"
            g[node] = {"class_type": "LTXVAddGuide",
                       "inputs": {"positive": pos, "negative": neg, "vae": ["vae", 0], "latent": video1,
                                  "image": img, "frame_idx": idx, "strength": strength}}
            pos, neg, video1 = [node, 0], [node, 1], [node, 2]

    def sample(stage: int, latent_av: list, sigmas: str, noise_seed: int, positive: list, negative: list) -> list:
        g[f"noise{stage}"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": noise_seed}}
        g[f"guider{stage}"] = {"class_type": "LTXVDualCFGGuider",
                               "inputs": {"model": model, "positive": positive, "negative": negative,
                                          "video_cfg": 1.0, "audio_cfg": 1.0}}
        g[f"sampler{stage}"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}}
        g[f"sigmas{stage}"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": sigmas}}
        g[f"sample{stage}"] = {"class_type": "SamplerCustomAdvanced",
                               "inputs": {"noise": [f"noise{stage}", 0], "guider": [f"guider{stage}", 0],
                                          "sampler": [f"sampler{stage}", 0], "sigmas": [f"sigmas{stage}", 0],
                                          "latent_image": latent_av}}
        g[f"split{stage}"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": [f"sample{stage}", 0]}}
        return [f"split{stage}", 0]

    g["av1"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": video1, "audio_latent": ["audio_latent", 0]}}
    video_out1 = sample(1, ["av1", 0], STAGE1_SIGMAS, seed, pos, neg)
    if last_img:
        g["crop1"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": pos, "negative": neg, "latent": video_out1}}
        pos, neg, video_out1 = ["crop1", 0], ["crop1", 1], ["crop1", 2]

    g["upsample"] = {"class_type": "LTXVLatentUpsampler",
                     "inputs": {"samples": video_out1, "upscale_model": ["upscaler", 0], "vae": ["vae", 0]}}
    video2 = ["upsample", 0]
    if first_img and not last_img:
        g["i2v2"] = {"class_type": "LTXVImgToVideoInplace",
                     "inputs": {"vae": ["vae", 0], "image": first_img, "latent": video2, "strength": 1.0, "bypass": False}}
        video2 = ["i2v2", 0]
    elif last_img:
        for key, img, idx in (("first", first_img, 0), ("last", last_img, -1)):
            if img is None:
                continue
            node = f"guide2_{key}"
            g[node] = {"class_type": "LTXVAddGuide",
                       "inputs": {"positive": pos, "negative": neg, "vae": ["vae", 0], "latent": video2,
                                  "image": img, "frame_idx": idx, "strength": 1.0}}
            pos, neg, video2 = [node, 0], [node, 1], [node, 2]

    g["av2"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": video2, "audio_latent": ["split1", 1]}}
    video_out2 = sample(2, ["av2", 0], STAGE2_SIGMAS, 42, pos, neg)
    if last_img:
        g["crop2"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": pos, "negative": neg, "latent": video_out2}}
        video_out2 = ["crop2", 2]

    g.update({
        "decode": {"class_type": "VAEDecodeTiled",
                   "inputs": {"samples": video_out2, "vae": ["vae", 0], "tile_size": 512, "overlap": 64,
                              "temporal_size": 64, "temporal_overlap": 16}},
        "decode_audio": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["split2", 1], "audio_vae": ["audio_vae", 0]}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["decode", 0], "audio": ["decode_audio", 0], "fps": fps}},
        "save": {"class_type": "SaveVideo",
                 "inputs": {"video": ["video", 0], "filename_prefix": p.get("filename_prefix", "sigma/ltx"),
                            "format": "mp4", "codec": "auto"}},
    })
    return g
