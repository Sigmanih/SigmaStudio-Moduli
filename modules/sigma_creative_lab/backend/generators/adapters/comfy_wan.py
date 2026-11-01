"""Grafi ComfyUI (formato API) per Wan 2.2 14B (Apache 2.0), dai template ufficiali di ComfyUI 0.39.

- S2V (`video_wan2_2_14B_s2v.json`): un'immagine e una voce, il personaggio parla. Per le
  inquadrature con battuta: il labiale e i gesti nascono dall'audio, non da un testo.
- I2V (`video_wan2_2_14B_i2v.json`): due esperti (rumore alto e basso) a 4 passi con le LoRA
  lightx2v. Il movimento piu' fisico fra i modelli aperti, per le azioni che LTX lascia ferme.

Wan genera a 16 fps: il montaggio porta tutto a 24.
"""

from __future__ import annotations

WAN_FPS = 16
WAN_FILES = {
    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
    "s2v": "wan2.2_s2v_14B_fp8_scaled.safetensors",
    "s2v_lora": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
    "audio_encoder": "wav2vec2_large_english_fp16.safetensors",
    "i2v_high": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    "i2v_low": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    "i2v_lora_high": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    "i2v_lora_low": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
}
#: Il negativo ufficiale di Wan (con cfg 1 delle LoRA a 4 passi conta poco, ma resta quello addestrato).
NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，"
            "丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
            "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")
#: Fotogrammi per blocco di S2V: 77 a 16 fps sono 4,8 s; le battute piu' lunghe aggiungono blocchi.
S2V_CHUNK = 77


def wan_frames(seconds: float, fps: int = WAN_FPS) -> int:
    """Wan vuole lunghezze 4k + 1."""
    n = max(5, round(seconds * fps) + 1)
    return n + (1 - n % 4) % 4


def _common(g: dict, p: dict) -> None:
    g.update({
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": WAN_FILES["clip"], "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": WAN_FILES["vae"]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p["prompt"]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p.get("negative") or NEGATIVE}},
        "image": {"class_type": "LoadImage", "inputs": {"image": p["image"]}},
    })


def _save(g: dict, images: list, p: dict, audio: list | None = None) -> None:
    g["video"] = {"class_type": "CreateVideo", "inputs": {"images": images, "fps": float(WAN_FPS),
                                                          **({"audio": audio} if audio else {})}}
    g["save"] = {"class_type": "SaveVideo", "inputs": {"video": ["video", 0],
                                                       "filename_prefix": p.get("filename_prefix", "sigma/wan"),
                                                       "format": "mp4", "codec": "auto"}}


def build_wan_s2v(p: dict) -> dict:
    """Chiavi: prompt, image, audio (nomi in input/), width, height, seconds, seed, filename_prefix."""
    g: dict = {}
    _common(g, p)
    w, h = int(p.get("width", 832)), int(p.get("height", 480))
    total = wan_frames(float(p.get("seconds", 4.0)))
    first = min(total, S2V_CHUNK)
    g.update({
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": WAN_FILES["s2v"], "weight_dtype": "default"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": WAN_FILES["s2v_lora"],
                                                                 "strength_model": 1.0}},
        "shift": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lora", 0], "shift": 8.0}},
        "audio": {"class_type": "LoadAudio", "inputs": {"audio": p["audio"]}},
        "aenc_model": {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": WAN_FILES["audio_encoder"]}},
        "aenc": {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["aenc_model", 0], "audio": ["audio", 0]}},
        "s2v": {"class_type": "WanSoundImageToVideo", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "width": w, "height": h,
            "length": first, "batch_size": 1, "audio_encoder_output": ["aenc", 0], "ref_image": ["image", 0]}},
    })

    def sample(key: str, cond: str, seed: int) -> None:
        g[key] = {"class_type": "KSampler", "inputs": {
            "model": ["shift", 0], "seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "uni_pc", "scheduler": "simple",
            "positive": [cond, 0], "negative": [cond, 1], "latent_image": [cond, 2], "denoise": 1.0}}

    seed = int(p.get("seed", 42))
    sample("sample0", "s2v", seed)
    latent, done, k = ["sample0", 0], first, 0
    while done < total:
        # Ogni blocco riparte dalla coda del precedente, con la stessa voce: la battuta lunga resta una ripresa.
        k += 1
        g[f"ext{k}"] = {"class_type": "WanSoundImageToVideoExtend", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "length": S2V_CHUNK,
            "video_latent": latent, "audio_encoder_output": ["aenc", 0], "ref_image": ["image", 0]}}
        sample(f"sample{k}", f"ext{k}", seed + k)
        g[f"cat{k}"] = {"class_type": "LatentConcat", "inputs": {"samples1": latent, "samples2": [f"sample{k}", 0],
                                                                  "dim": "t"}}
        latent, done = [f"cat{k}", 0], done + S2V_CHUNK
    g["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": latent, "vae": ["vae", 0]}}
    # Solo i fotogrammi della battuta: i blocchi interi sforerebbero la durata dell'inquadratura.
    g["trim"] = {"class_type": "ImageFromBatch", "inputs": {"image": ["decode", 0], "batch_index": 0, "length": total}}
    _save(g, ["trim", 0], p, audio=["audio", 0])
    return g


def build_wan_i2v(p: dict) -> dict:
    """Chiavi: prompt, image (nome in input/), width, height, seconds, seed, filename_prefix."""
    g: dict = {}
    _common(g, p)
    w, h = int(p.get("width", 832)), int(p.get("height", 480))
    length = wan_frames(float(p.get("seconds", 5.0)))
    for tag in ("high", "low"):
        g[f"unet_{tag}"] = {"class_type": "UNETLoader", "inputs": {"unet_name": WAN_FILES[f"i2v_{tag}"],
                                                                   "weight_dtype": "default"}}
        g[f"lora_{tag}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": [f"unet_{tag}", 0], "lora_name": WAN_FILES[f"i2v_lora_{tag}"], "strength_model": 1.0}}
        g[f"shift_{tag}"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": [f"lora_{tag}", 0], "shift": 5.0}}
    g["i2v"] = {"class_type": "WanImageToVideo", "inputs": {
        "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "width": w, "height": h, "length": length,
        "batch_size": 1, "start_image": ["image", 0]}}
    # Primi 2 passi all'esperto del rumore alto (composizione e movimento), ultimi 2 a quello basso (dettaglio).
    common = {"steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
              "positive": ["i2v", 0], "negative": ["i2v", 1]}
    g["high"] = {"class_type": "KSamplerAdvanced", "inputs": {
        **common, "model": ["shift_high", 0], "add_noise": "enable", "noise_seed": int(p.get("seed", 42)),
        "latent_image": ["i2v", 2], "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}}
    g["low"] = {"class_type": "KSamplerAdvanced", "inputs": {
        **common, "model": ["shift_low", 0], "add_noise": "disable", "noise_seed": 0,
        "latent_image": ["high", 0], "start_at_step": 2, "end_at_step": 4, "return_with_leftover_noise": "disable"}}
    g["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["low", 0], "vae": ["vae", 0]}}
    _save(g, ["decode", 0], p)
    return g
