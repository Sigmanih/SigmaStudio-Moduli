"""Worker delle voci: sintesi (Kokoro, Chatterbox, Qwen3-TTS, VoxCPM2) e trascrizione (Whisper).

Gira nel venv isolato `store/engine_runtime/voice/.venv`, non nel Python di
Sigma: Chatterbox fissa versioni di torch e transformers che romperebbero gli
altri moduli. Per questo il file non importa nulla da `core`.

    python worker.py --port 8095      (token in SIGMA_VOICE_TOKEN)

I modelli si caricano al primo uso e restano in memoria; /unload li libera
(serve quando la GPU va lasciata al modello video).

Lo stesso file gira anche nel venv `voice_qwen`: Qwen3-TTS vuole un
transformers piu' recente di quello che Chatterbox accetta; e nel venv `voice_voxcpm`
per VoxCPM2. Ogni processo risponde solo per i motori che il suo venv sa importare.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ.get("SIGMA_VOICE_TOKEN", "")
KOKORO_VOICES = {
    # Voci italiane di Kokoro 82M (Apache 2.0).
    "if_sara": "Sara (donna)", "im_nicola": "Nicola (uomo)",
}
_models: dict = {}
_lock = threading.Lock()          # una sintesi alla volta: i modelli non sono rientranti


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _kokoro():
    if "kokoro" not in _models:
        from kokoro import KPipeline
        _models["kokoro"] = KPipeline(lang_code="i", repo_id="hexgrad/Kokoro-82M")
    return _models["kokoro"]


def _chatterbox():
    if "chatterbox" not in _models:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _models["chatterbox"] = ChatterboxMultilingualTTS.from_pretrained(device=_device())
    return _models["chatterbox"]


def _vc():
    if "vc" not in _models:
        from chatterbox.vc import ChatterboxVC
        _models["vc"] = ChatterboxVC.from_pretrained(_device())
    return _models["vc"]


QWEN_LANG = {"it": "Italian", "en": "English", "fr": "French", "de": "German", "es": "Spanish",
             "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"}


def _qwen(kind: str):
    """Qwen3-TTS (Apache 2.0): "design" crea una voce da una descrizione, "clone" la ripete da un campione."""
    key = f"qwen_{kind}"
    if key not in _models:
        import torch
        from qwen_tts import Qwen3TTSModel
        repo = {"design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "clone": "Qwen/Qwen3-TTS-12Hz-1.7B-Base"}[kind]
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        _models[key] = Qwen3TTSModel.from_pretrained(repo, device_map=_device(), dtype=dtype)
    return _models[key]


def _voxcpm():
    """VoxCPM2 (Apache 2.0, 30 lingue, 48 kHz): voce da descrizione e clonazione con trascrizione."""
    if "voxcpm" not in _models:
        from voxcpm import VoxCPM
        _models["voxcpm"] = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    return _models["voxcpm"]


def _whisper():
    if "whisper" not in _models:
        from faster_whisper import WhisperModel
        # Sulla CPU: la trascrizione e' breve e non deve contendere la GPU al video.
        _models["whisper"] = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    return _models["whisper"]


def synthesize(req: dict) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    text = str(req.get("text", "")).strip()
    if not text:
        raise ValueError("testo vuoto")
    out = Path(req["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    engine = req.get("engine", "chatterbox")
    t0 = time.monotonic()
    if engine == "kokoro":
        pipe = _kokoro()
        voice = req.get("voice") or "if_sara"
        chunks = [a for _, _, a in pipe(text, voice=voice, speed=float(req.get("speed", 1.0)))]
        audio = torch.cat([torch.as_tensor(c) for c in chunks]).numpy() if chunks else np.zeros(1)
        sr = 24000
    elif engine == "chatterbox":
        model = _chatterbox()
        if req.get("seed") is not None:
            torch.manual_seed(int(req["seed"]))
        ref = req.get("voice_ref") or None
        if ref and not Path(ref).is_file():
            raise ValueError(f"campione di voce inesistente: {ref}")
        wav = model.generate(text, language_id=req.get("language", "it"), audio_prompt_path=ref,
                             exaggeration=float(req.get("exaggeration", 0.5)), cfg_weight=float(req.get("cfg_weight", 0.5)),
                             temperature=float(req.get("temperature", 0.8)))
        audio = wav.squeeze(0).cpu().numpy()
        sr = model.sr
    elif engine == "qwen_design":
        instruct = str(req.get("instruct", "")).strip()
        if not instruct:
            raise ValueError("serve la descrizione della voce (instruct)")
        if req.get("seed") is not None:
            torch.manual_seed(int(req["seed"]))
        wavs, sr = _qwen("design").generate_voice_design(text=text, instruct=instruct,
                                                          language=QWEN_LANG.get(req.get("language", "it"), "Italian"))
        audio = np.asarray(wavs[0])
    elif engine == "qwen_clone":
        ref = req.get("voice_ref") or ""
        if not Path(ref).is_file():
            raise ValueError(f"campione di voce inesistente: {ref}")
        if req.get("seed") is not None:
            torch.manual_seed(int(req["seed"]))
        ref_text = str(req.get("ref_text", "")).strip()
        # Senza la trascrizione del campione si usa solo l'impronta della voce: un
        # po' meno fedele, ma non serve far passare ogni campione da Whisper.
        wavs, sr = _qwen("clone").generate_voice_clone(
            text=text, language=QWEN_LANG.get(req.get("language", "it"), "Italian"), ref_audio=ref,
            ref_text=ref_text or None, x_vector_only_mode=not ref_text)
        audio = np.asarray(wavs[0])
    elif engine in ("voxcpm_design", "voxcpm_clone"):
        model = _voxcpm()
        if req.get("seed") is not None:
            torch.manual_seed(int(req["seed"]))
        style = str(req.get("instruct", "")).strip()
        steps = int(req.get("steps", 10))
        if engine == "voxcpm_design":
            if not style:
                raise ValueError("serve la descrizione della voce (instruct)")
            audio = model.generate(text=f"({style}){text}", cfg_value=2.0, inference_timesteps=steps)
        else:
            ref = req.get("voice_ref") or ""
            if not Path(ref).is_file():
                raise ValueError(f"campione di voce inesistente: {ref}")
            ref_text = str(req.get("ref_text", "")).strip()
            if ref_text and not style:
                # Clonazione piena (campione + sua trascrizione): il timbro piu' fedele.
                audio = model.generate(text=text, prompt_wav_path=ref, prompt_text=ref_text, reference_wav_path=ref,
                                       cfg_value=2.0, inference_timesteps=steps)
            else:
                # Con un tono ("worried", "whispering") la clonazione controllabile: la parentesi e' in
                # inglese, in italiano il modello la leggeva ad alta voce.
                audio = model.generate(text=f"({style}){text}" if style else text, reference_wav_path=ref,
                                       cfg_value=2.0, inference_timesteps=steps)
        audio = np.asarray(audio)
        sr = model.tts_model.sample_rate
    else:
        raise ValueError(f"motore sconosciuto: {engine}")
    sf.write(out, audio, sr)
    return {"output_path": str(out), "duration": round(len(audio) / sr, 3), "sample_rate": sr,
            "seconds": round(time.monotonic() - t0, 2), "engine": engine}


def convert(req: dict) -> dict:
    """Porta un parlato alla voce di un campione mantenendo i tempi.

    Serve ai dialoghi generati da H3: il labiale e' gia' sincronizzato con il
    parlato del modello, e cambiare solo il timbro non lo sposta.
    """
    import soundfile as sf
    src, target = req["source"], req["target_voice"]
    for f in (src, target):
        if not Path(f).is_file():
            raise ValueError(f"file inesistente: {f}")
    out = Path(req["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    model = _vc()
    if req.get("seed") is not None:
        # La conversione parte da rumore casuale: un altro seed rifa' la parola rovinata in modo diverso.
        import torch
        torch.manual_seed(int(req["seed"]))
    wav = model.generate(src, target_voice_path=target)
    audio = wav.squeeze(0).cpu().numpy()
    sf.write(out, audio, model.sr)
    return {"output_path": str(out), "duration": round(len(audio) / model.sr, 3), "seconds": round(time.monotonic() - t0, 2)}


def transcribe(req: dict) -> dict:
    model = _whisper()
    # VAD e niente condizionamento sul testo precedente: senza, nel rumore di
    # fondo (vento, mare) Whisper "sente" di nuovo l'ultima frase pronunciata.
    segs, info = model.transcribe(req["path"], language=req.get("language") or None, word_timestamps=True,
                                  vad_filter=True, condition_on_previous_text=False)
    segs = list(segs)
    if not any(s.text.strip() for s in segs):
        # Il VAD scartava battute intere di VoxCPM2 perfettamente udibili: senza parlato trovato si
        # riprova senza filtro, che su una battuta breve non ha rumore da cui difendersi.
        segs, info = model.transcribe(req["path"], language=req.get("language") or None, word_timestamps=True,
                                      vad_filter=False, condition_on_previous_text=False)
    segments, words = [], []
    for seg in segs:
        segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
        # La confidenza per parola rivela i difetti: una parola "impastata" dalla
        # sintesi o dalla conversione scende anche se il testo resta giusto.
        words += [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
                   "p": round(float(w.probability), 3)} for w in (seg.words or [])]
    return {"language": info.language, "text": " ".join(s["text"] for s in segments), "segments": segments,
            "words": words}


def _load(path: str, sr: int | None = None):
    import librosa
    audio, rate = librosa.load(path, sr=sr, mono=True)
    return audio, rate


def splice(req: dict) -> dict:
    """Rimette in `base` i tratti `regions` presi da `patch`, con dissolvenze incrociate.

    Serve quando la conversione vocale rovina una parola: in quel tratto torna
    il parlato originale (timbro un po' diverso, ma pulito e con gli stessi tempi,
    quindi il labiale resta giusto).
    """
    import numpy as np
    import soundfile as sf
    base, sr = _load(req["base"])
    patch, _ = _load(req["patch"], sr)
    if len(patch) < len(base):
        patch = np.pad(patch, (0, len(base) - len(patch)))
    # Stessa intensita' percepita nel tratto sostituito: senza, la parola "salta" di volume.
    rms = lambda x: float(np.sqrt(np.mean(np.square(x)) + 1e-12))
    out = base.copy()
    fade = max(1, int(float(req.get("fade", 0.03)) * sr))
    for a, b in req.get("regions") or []:
        i, j = max(0, int(a * sr)), min(len(base), int(b * sr))
        if j - i < 2 * fade:
            continue
        seg = patch[i:j] * (rms(base[i:j]) / rms(patch[i:j]))
        w = np.ones(j - i)
        ramp = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2          # dissolvenza a potenza costante
        w[:fade], w[-fade:] = ramp, ramp[::-1]
        out[i:j] = base[i:j] * (1 - w) + seg * w
    peak = float(np.max(np.abs(out))) or 1.0
    if peak > 0.99:
        out = out * (0.99 / peak)
    Path(req["output_path"]).parent.mkdir(parents=True, exist_ok=True)
    sf.write(req["output_path"], out, sr)
    return {"output_path": req["output_path"], "regions": req.get("regions") or []}


def audio_check(req: dict) -> dict:
    """Difetti misurabili senza capire il parlato: clipping, click, buchi di silenzio a meta' frase."""
    import numpy as np
    audio, sr = _load(req["path"])
    if not len(audio):
        return {"issues": ["audio vuoto"], "clipping": 0.0, "clicks": 0, "gaps": []}
    issues = []
    clipping = float(np.mean(np.abs(audio) > 0.985))
    if clipping > 0.001:
        issues.append(f"clipping sull'{clipping * 100:.1f}% dei campioni")
    # Click: salto fra campioni adiacenti molto oltre la variazione tipica del segnale.
    d = np.abs(np.diff(audio))
    clicks = int(np.sum(d > max(0.25, 12 * float(np.median(d)) + 1e-4)))
    if clicks > 3:
        issues.append(f"{clicks} click o scatti nel segnale")
    # Buchi: silenzio netto (< -60 dB) piu' lungo di 0.35 s fra due tratti parlati.
    hop = int(0.01 * sr)
    frames = np.array([np.sqrt(np.mean(audio[k:k + hop] ** 2) + 1e-12) for k in range(0, len(audio) - hop, hop)])
    loud = frames > 10 ** (-40 / 20) * float(frames.max())
    gaps, start = [], None
    first, last = (np.argmax(loud), len(loud) - np.argmax(loud[::-1])) if loud.any() else (0, 0)
    for k in range(first, last):
        quiet = frames[k] < 10 ** (-60 / 20) * float(frames.max())
        if quiet and start is None:
            start = k
        elif not quiet and start is not None:
            if (k - start) * 0.01 > 0.35:
                gaps.append([round(start * 0.01, 2), round(k * 0.01, 2)])
            start = None
    if gaps:
        issues.append(f"{len(gaps)} buchi di silenzio a meta' parlato")
    return {"issues": issues, "clipping": round(clipping, 5), "clicks": clicks, "gaps": gaps}


def unload() -> dict:
    names = list(_models)
    _models.clear()
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass
    return {"unloaded": names}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):     # il log di Sigma basta: niente righe per ogni richiesta
        return

    def _send(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return not TOKEN or self.headers.get("X-Sigma-Token") == TOKEN

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "ok", "service": "sigma_voice", "loaded": list(_models)})
        if not self._authorized():
            return self._send(401, {"error": "token mancante o errato"})
        if self.path == "/voices":
            return self._send(200, {"kokoro": KOKORO_VOICES, "chatterbox": "clonazione da campione (23 lingue)",
                                    "qwen_design": "voce da descrizione (10 lingue)",
                                    "qwen_clone": "clonazione da campione (10 lingue)"})
        self._send(404, {"error": "rotta inesistente"})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"error": "token mancante o errato"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "JSON non valido"})
        routes = {"/synthesize": synthesize, "/convert": convert, "/transcribe": transcribe,
                  "/splice": splice, "/audio_check": audio_check, "/unload": lambda _r: unload()}
        fn = routes.get(self.path)
        if fn is None:
            return self._send(404, {"error": "rotta inesistente"})
        try:
            with _lock:
                return self._send(200, fn(req))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


def _parent_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return code.value == 259                                # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _watch_parent(pid: int) -> None:
    """Se Sigma muore, il worker non deve restare a tenere 4 GB di VRAM."""
    while True:
        time.sleep(5)
        if not _parent_alive(pid):
            os._exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--parent-pid", type=int, default=0)
    args = ap.parse_args()
    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid,), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"sigma-voice in ascolto su 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
