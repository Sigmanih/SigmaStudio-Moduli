"""Installazione dei componenti video da Sigma Studio.

Ogni componente ha un controllo "e' installato?" e un'azione di installazione
che gira su un thread, con avanzamento leggibile dalla UI. Le sorgenti sono
fisse e scritte qui (release ufficiali su GitHub e Hugging Face): la UI sceglie
un componente, non un URL.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from core import paths
from core.logger import get_logger

log = get_logger("creative_video_installer")

IS_WINDOWS = sys.platform.startswith("win")
SDCPP_TAG = "master-948-228c707"
SDCPP_BASE = f"https://github.com/leejet/stable-diffusion.cpp/releases/download/{SDCPP_TAG}"
FFMPEG_ZIP = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip"
H3_REPO = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main"
ACE_URL = ("https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/resolve/main/checkpoints/"
           "ace_step_1.5_turbo_aio.safetensors")
ESRGAN_BASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"
# Giudice delle clip (video/clip_judge.py, stesso elenco in MODELS): Apache 2.0.
# Sulla GPU dedicata l'8B (tutto in VRAM) e' il piu' rapido e il piu' preciso;
# il 30B-A3B serve a chi giudica sulla CPU (vedi clip_judge.model_files).
VLM_VARIANTS = {
    "vlm_judge": ("Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF", "Qwen--Qwen3-VL-30B-A3B-Instruct-GGUF",
                  ("Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf")),
    "vlm_judge_light": ("Qwen/Qwen3-VL-8B-Instruct-GGUF", "Qwen--Qwen3-VL-8B-Instruct-GGUF",
                        ("Qwen3VL-8B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-8B-Instruct-F16.gguf")),
}


def _runtime_dir() -> Path:
    return paths.store_dir() / "engine_runtime"


def _models_root() -> Path | None:
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    root = discover_models_root()
    return Path(root) if root else None


@dataclass
class InstallJob:
    component: str
    status: str = "running"          # running | done | error
    message: str = ""
    downloaded: int = 0
    total: int = 0
    started: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        pct = round(100 * self.downloaded / self.total, 1) if self.total else None
        return {"component": self.component, "status": self.status, "message": self.message, "progress": pct}


def _hf_token() -> str:
    try:
        from core.modules.sigma_creative_lab.video.studio_routes import _creative_cfg
        token = str(_creative_cfg().get("hf_token") or "")
    except Exception:
        token = ""
    if token:
        return token
    # Lo stesso token che usa "Download modelli": chiederlo due volte confondeva (l'utente l'aveva gia' messo).
    try:
        from core.modules.sigma_model_hub.backend.hf_client import get_effective_hf_token
        return get_effective_hf_token() or ""
    except Exception:
        return ""


def _download(url: str, dest: Path, job: InstallJob) -> Path:
    """Download con ripresa da .part."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    start = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "SigmaStudio/1.0", **({"Range": f"bytes={start}-"} if start else {})}
    token = _hf_token() if "huggingface.co/" in url else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True) as resp:
        if resp.status_code == 416:
            part.replace(dest)
            return dest
        if resp.status_code in (401, 403) and "huggingface.co/" in url:
            # Repository "gated": la licenza la accetta l'utente sul sito, con il suo account.
            repo = "/".join(url.split("huggingface.co/", 1)[1].split("/")[:2])
            raise RuntimeError(f"{repo} richiede di accettare la licenza su huggingface.co/{repo} e un token "
                               "Hugging Face in Impostazioni → Creative (hf_token)"
                               + ("" if token else ": nessun token configurato"))
        resp.raise_for_status()
        resumed = start and resp.status_code == 206
        job.total = int(resp.headers.get("Content-Length", 0)) + (start if resumed else 0)
        job.downloaded = start if resumed else 0
        with open(part, "ab" if resumed else "wb") as f:
            for chunk in resp.iter_content(1024 * 1024):
                f.write(chunk)
                job.downloaded += len(chunk)
    part.replace(dest)
    return dest


def _extract(zip_path: Path, target: Path, flatten_bin: bool = False) -> None:
    """Estrae l'archivio; con flatten_bin tiene solo gli eseguibili/DLL in un'unica cartella."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            name = Path(member.filename)
            if member.is_dir() or ".." in name.parts:
                continue                      # niente percorsi che escono dalla cartella
            if flatten_bin:
                if name.suffix.lower() not in (".exe", ".dll") or "bin" not in [p.lower() for p in name.parts]:
                    continue
                out = target / name.name
            else:
                out = target / name.name if len(name.parts) == 1 else target / Path(*name.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ---------------------------------------------------------------------------
# Componenti
# ---------------------------------------------------------------------------

def _install_sdcpp(job: InstallJob) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("su Linux/Pi stable-diffusion.cpp si compila dai sorgenti (cmake -DSD_BUILD_SHARED_LIBS=ON)")
    dl = _runtime_dir() / "sdcpp" / "dl"
    files = [(f"sd-master-{SDCPP_TAG.split('-')[-1]}-bin-win-cuda12-x64.zip", "binari sd.cpp"),
             ("cudart-sd-bin-win-cu12-x64.zip", "runtime CUDA")]
    for fname, label in files:
        job.message = f"Download {label}"
        z = _download(f"{SDCPP_BASE}/{fname}", dl / fname, job)
        job.message = f"Estrazione {label}"
        _extract(z, _runtime_dir() / "sdcpp" / "bin")


def _install_ffmpeg(job: InstallJob) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("su Linux/Pi installa ffmpeg dal gestore pacchetti (apt install ffmpeg)")
    job.message = "Download ffmpeg"
    z = _download(FFMPEG_ZIP, _runtime_dir() / "ffmpeg" / "dl" / "ffmpeg.zip", job)
    job.message = "Estrazione"
    _extract(z, _runtime_dir() / "ffmpeg" / "bin", flatten_bin=True)


def _install_worker(job: InstallJob) -> None:
    """Copia il worker compilato; se non c'e', lo compila con cargo."""
    exe = "sigma-diffusion-worker" + (".exe" if IS_WINDOWS else "")
    project = paths.project_root() / "projects" / "sigma_engine_rust"
    built = project / "target" / "release" / exe
    if not built.exists():
        cargo = shutil.which("cargo")
        if not cargo:
            raise RuntimeError("cargo non trovato: installa Rust (rustup) per compilare il worker")
        job.message = "Compilazione del worker (cargo build --release)"
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        proc = subprocess.run([cargo, "build", "--release", "-p", "sigma-diffusion"], cwd=str(project),
                              capture_output=True, text=True, timeout=3600, creationflags=flags)
        if proc.returncode != 0:
            raise RuntimeError(f"compilazione fallita: {proc.stderr[-600:]}")
    target = _runtime_dir() / "sigma_diffusion" / exe
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, target)


# Versioni provate insieme: chatterbox-tts fissa torch 2.6, che non ha build
# per le Blackwell (sm_120); con l'override a 2.8 cu128 funziona. Perth (la
# filigrana di Chatterbox) usa pkg_resources, sparito da setuptools 81.
VOICE_PACKAGES = ["chatterbox-tts==0.1.7", "kokoro==0.9.4", "faster-whisper==1.2.1", "soundfile",
                  "setuptools<81",
                  # Kokoro in inglese (voci a_/b_) passa per spaCy: senza il modello la sintesi falliva (E050).
                  "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/"
                  "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"]
VOICE_OVERRIDES = "torch==2.8.0\ntorchaudio==2.8.0\n"
VOICE_MODULES = ("chatterbox", "kokoro", "faster_whisper")


def _voice_dir() -> Path:
    return _runtime_dir() / "voice"


def _find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    # Il server spesso parte senza ~/.local/bin nel PATH, dove l'installer di uv lo mette.
    local = Path.home() / ".local" / "bin" / ("uv.exe" if IS_WINDOWS else "uv")
    return str(local) if local.is_file() else None


# Qwen3-TTS (Apache 2.0) vuole transformers 4.57, Chatterbox lo blocca a una
# versione piu' vecchia: venv separato, con lo stesso torch 2.8 cu128.
QWEN_VOICE_PACKAGES = ["qwen-tts", "soundfile"]
VOXCPM_VOICE_PACKAGES = ["voxcpm", "soundfile"]


def _install_voice(job: InstallJob, venv: str = "voice", python: str = "3.11",
                   packages: list[str] | None = None, label: str = "Chatterbox, Kokoro e faster-whisper") -> None:
    """Venv separato per TTS, conversione voce e trascrizione.

    Separato perche' Chatterbox e Kokoro vogliono versioni di torch e numpy
    che non devono toccare l'ambiente del server. I pesi dei modelli arrivano
    da Hugging Face al primo uso.
    """
    from core.modules.sigma_creative_lab.voice.runtime import venv_python as _venv_python
    uv = _find_uv()
    if not uv:
        raise RuntimeError("uv non trovato: installalo (https://docs.astral.sh/uv/) e riprova")

    def venv_python() -> Path:
        return _venv_python(venv)
    base = _runtime_dir() / venv
    base.mkdir(parents=True, exist_ok=True)
    (base / "overrides.txt").write_text(VOICE_OVERRIDES, encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

    def run(args: list[str], label: str, timeout: int) -> None:
        job.message = label
        proc = subprocess.run([uv, *args], cwd=str(base), capture_output=True, text=True, timeout=timeout,
                              creationflags=flags)
        if proc.returncode != 0:
            raise RuntimeError(f"{label} fallito: {(proc.stderr or proc.stdout)[-600:]}")

    if not venv_python().is_file():
        run(["venv", "--python", python, ".venv"], f"Creazione ambiente Python {python}", 900)
    # Le ruote CUDA servono solo dove c'e' una GPU NVIDIA; sul Pi torch arriva da PyPI in versione CPU.
    index = (["--index", "https://download.pytorch.org/whl/cu128", "--index-strategy", "unsafe-best-match"]
             if shutil.which("nvidia-smi") else [])
    run(["pip", "install", "--python", str(venv_python()), "--override", "overrides.txt", *index,
         *(packages or VOICE_PACKAGES)], f"Installazione {label} (alcuni GB)", 3600)


def _install_voice_qwen(job: InstallJob) -> None:
    _install_voice(job, "voice_qwen", "3.12", QWEN_VOICE_PACKAGES, "Qwen3-TTS")


def _install_voice_voxcpm(job: InstallJob) -> None:
    _install_voice(job, "voice_voxcpm", "3.12", VOXCPM_VOICE_PACKAGES, "VoxCPM2")


def _check_voice_voxcpm() -> bool:
    from core.modules.sigma_creative_lab.voice.runtime import venv_python
    venv = _runtime_dir() / "voice_voxcpm" / ".venv"
    sites = [venv / "Lib" / "site-packages"] + list((venv / "lib").glob("python*/site-packages"))
    return venv_python("voice_voxcpm").is_file() and any((site / "voxcpm").is_dir() for site in sites)


def _check_voice_qwen() -> bool:
    from core.modules.sigma_creative_lab.voice.runtime import venv_python
    venv = _runtime_dir() / "voice_qwen" / ".venv"
    sites = [venv / "Lib" / "site-packages"] + list((venv / "lib").glob("python*/site-packages"))
    return venv_python("voice_qwen").is_file() and any((site / "qwen_tts").is_dir() for site in sites)


def _check_voice() -> bool:
    from core.modules.sigma_creative_lab.voice.runtime import venv_python
    if not venv_python().is_file():
        return False
    # Si guarda site-packages invece di importare: importare torch a ogni
    # aggiornamento dello stato costerebbe secondi.
    venv = _voice_dir() / ".venv"
    sites = [venv / "Lib" / "site-packages"] + list((venv / "lib").glob("python*/site-packages"))
    return any(all((s / m).is_dir() for m in VOICE_MODULES) for s in sites)


def _install_esrgan(job: InstallJob) -> None:
    """Pesi di realesr-general-x4v3 (BSD-3); la rete gira in un Python con torch (Voci o server)."""
    from core.modules.sigma_creative_lab.video.postprocess import ESRGAN_WEIGHTS, torch_python
    if torch_python() is None:
        raise RuntimeError("installa prima il componente Voci: Real-ESRGAN ha bisogno di PyTorch")
    job.message = f"Download {ESRGAN_WEIGHTS}"
    _download(f"{ESRGAN_BASE}/{ESRGAN_WEIGHTS}", _runtime_dir() / "realesrgan" / ESRGAN_WEIGHTS, job)


def _check_esrgan() -> bool:
    from core.modules.sigma_creative_lab.video.postprocess import esrgan_ready
    return esrgan_ready()


def _install_ddcolor(job: InstallJob) -> None:
    from core.modules.sigma_creative_lab.video.postprocess import DDCOLOR_URL, ddcolor_weights, torch_python
    job.message = "Download pesi DDColor"
    _download(DDCOLOR_URL, ddcolor_weights(), job)
    if torch_python() is None:
        raise RuntimeError("pesi scaricati, ma serve un Python con torch e opencv: installa prima le Voci")


def _check_ddcolor() -> bool:
    from core.modules.sigma_creative_lab.video.postprocess import recolor_ready
    return recolor_ready()


# LTX-2.5 (Lightricks): audio e video insieme come H3, ma con una licenza che vale
# anche in Europa (quella di H3 esclude UE, Regno Unito, Corea e USA). Distillato int8.
LTX_BASE = "https://huggingface.co/Lightricks/LTX-2.5/resolve/main"
LTX_FILES = [("vae", "ltx-2.5-video-vae-bf16.safetensors"), ("vae", "ltx-2.5-audio-vae-bf16.safetensors"),
             ("text_encoders", "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"),
             ("diffusion_models", "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"),
             # Secondo passaggio a risoluzione doppia: e' la pipeline consigliata da Lightricks.
             ("latent_upscale_models", "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors")]


def _install_ltx(job: InstallJob) -> None:
    root = _models_root()
    if not root:
        raise RuntimeError("cartella modelli di ComfyUI non trovata")
    for folder, name in LTX_FILES:
        if not (root / folder / name).is_file():
            job.message = f"Download {name}"
            _download(f"{LTX_BASE}/{folder}/{name}", root / folder / name, job)


def _check_ltx() -> bool:
    root = _models_root()
    return bool(root) and all((root / folder / name).is_file() for folder, name in LTX_FILES)


IMAGE_SOURCES = {
    "zimage": [("diffusion_models", "z_image_turbo_int8_convrot.safetensors",
                "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/"),
               ("text_encoders", "qwen_3_4b_fp8_mixed.safetensors",
                "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/"),
               ("vae", "ae.safetensors", "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/")],
    "animagine": [("checkpoints", "animagine-xl-4.0-opt.safetensors",
                   "https://huggingface.co/cagliostrolab/animagine-xl-4.0/resolve/main/")],
    # Text encoder condiviso con Z-Image: se c'e' gia', klein costa 4,4 GB.
    "klein": [("diffusion_models", "flux-2-klein-4b-fp8.safetensors",
               "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/resolve/main/"),
              ("text_encoders", "qwen_3_4b_fp8_mixed.safetensors",
               "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/"),
              ("vae", "flux2-vae.safetensors", "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/")],
}


def _image_model_ready(model: str) -> bool:
    from core.modules.sigma_creative_lab.video.image_gen import installed
    return installed(model)


def _install_image_model(job: InstallJob, model: str) -> None:
    root = _models_root()
    if not root:
        raise RuntimeError("cartella modelli di ComfyUI non trovata")
    for folder, name, base in IMAGE_SOURCES[model]:
        if (root / folder / name).is_file():
            continue
        job.message = f"Download {name}"
        _download(base + name, root / folder / name, job)


def _install_vlm(variant: str):
    repo, folder, files = VLM_VARIANTS[variant]

    def install(job: InstallJob) -> None:
        # Nella cartella dei modelli LLM e non in store/: cosi' lo vede anche il Model Hub.
        for name in files:
            job.message = f"Download {name}"
            _download(f"https://huggingface.co/{repo}/resolve/main/{name}", paths.models_dir() / folder / name, job)
    return install


def _check_vlm(variant: str):
    _repo, folder, files = VLM_VARIANTS[variant]
    return lambda: all((paths.models_dir() / folder / n).is_file() for n in files)


def _hf_model(folder: str, filename: str, url: str):
    def install(job: InstallJob) -> None:
        root = _models_root()
        if not root:
            raise RuntimeError("cartella modelli di ComfyUI non trovata")
        job.message = f"Download {filename}"
        _download(url, root / folder / filename, job)
    return install


def _check_model(folder: str, filename: str):
    def check() -> bool:
        root = _models_root()
        return bool(root and (root / folder / filename).is_file())
    return check


def _check_sdcpp() -> bool:
    lib = "stable-diffusion.dll" if IS_WINDOWS else "libstable-diffusion.so"
    return (_runtime_dir() / "sdcpp" / "bin" / lib).is_file()


def _check_ffmpeg() -> bool:
    from core.modules.sigma_creative_lab.native.runtime import locate_ffmpeg
    return locate_ffmpeg() is not None


def _check_worker() -> bool:
    from core.modules.sigma_creative_lab.native.runtime import locate_worker
    return locate_worker() is not None


COMPONENTS = {
    "ffmpeg": {"label": "ffmpeg (montaggio, NVENC)", "size_gb": 0.2, "check": _check_ffmpeg, "install": _install_ffmpeg},
    "sdcpp": {"label": "stable-diffusion.cpp CUDA (motore nativo)", "size_gb": 0.9, "check": _check_sdcpp,
              "install": _install_sdcpp},
    "worker": {"label": "Worker Rust sigma-diffusion", "size_gb": 0.01, "check": _check_worker,
               "install": _install_worker},
    "ace_step": {"label": "ACE-Step 1.5 turbo (colonna sonora)", "size_gb": 10.0,
                 "check": _check_model("checkpoints", "ace_step_1.5_turbo_aio.safetensors"),
                 "install": _hf_model("checkpoints", "ace_step_1.5_turbo_aio.safetensors", ACE_URL)},
    "voice": {"label": "Voci: Chatterbox, Kokoro, faster-whisper (dialoghi, TTS, sottotitoli)", "size_gb": 6.0,
              "check": _check_voice, "install": _install_voice},
    "voice_qwen": {"label": "Voci Qwen3-TTS (voce da descrizione, clonazione)", "size_gb": 8.0,
                   "check": _check_voice_qwen, "install": _install_voice_qwen},
    "voice_voxcpm": {"label": "Voci VoxCPM2 (voce da descrizione, clonazione, tono per battuta)", "size_gb": 9.0,
                     "check": _check_voice_voxcpm, "install": _install_voice_voxcpm},
    "video_ltx25": {"label": "LTX-2.5 distillato (video + audio, licenza valida in UE; richiede token HF)",
                    "size_gb": 38.7, "check": _check_ltx, "install": _install_ltx},
    # Modelli d'immagine dei generi (video/genres.py): ritratti e fotogrammi chiave.
    "image_zimage": {"label": "Z-Image-Turbo (immagini realistiche, 3D, illustrazione; Apache 2.0)", "size_gb": 12.2,
                     "check": lambda: _image_model_ready("zimage"), "install": lambda job: _install_image_model(job, "zimage")},
    "image_animagine": {"label": "Animagine XL 4.0 (immagini anime; OpenRAIL++)", "size_gb": 6.9,
                        "check": lambda: _image_model_ready("animagine"),
                        "install": lambda job: _install_image_model(job, "animagine")},
    "image_klein": {"label": "FLUX.2 klein 4B (personaggi identici dai riferimenti, piu' personaggi per scena; Apache 2.0)",
                    "size_gb": 4.4, "check": lambda: _image_model_ready("klein"),
                    "install": lambda job: _install_image_model(job, "klein")},
    "esrgan": {"label": "Real-ESRGAN (upscale delle clip a 720p/1080p)", "size_gb": 0.01,
               "check": _check_esrgan, "install": _install_esrgan},
    "ddcolor": {"label": "DDColor (ricolora video in bianco e nero; Apache 2.0)", "size_gb": 0.9,
                "check": _check_ddcolor, "install": _install_ddcolor},
    "vlm_judge": {"label": "Giudice visivo Qwen3-VL 30B-A3B (sulla CPU, per chi ha una sola GPU; ~20 GB di RAM)", "size_gb": 19.6,
                  "check": _check_vlm("vlm_judge"), "install": _install_vlm("vlm_judge")},
    "vlm_judge_light": {"label": "Giudice visivo Qwen3-VL 8B (sulla GPU dedicata: consigliato con due GPU, ~8 s a clip)",
                        "size_gb": 6.2, "check": _check_vlm("vlm_judge_light"),
                        "install": _install_vlm("vlm_judge_light")},
}
for _variant, _size in (("int8_convrot", 21.0), ("fp8_scaled", 21.0), ("w6a8", 16.0)):
    for _kind in ("fl2va", "ref2va"):
        _name = f"minimax_h3_{_kind}_pruned_{_variant}.safetensors"
        COMPONENTS[f"h3_{_kind}_{_variant}"] = {
            "label": f"MiniMax H3 {_kind.upper()} {_variant}", "size_gb": _size,
            "check": _check_model("diffusion_models", _name),
            "install": _hf_model("diffusion_models", _name, f"{H3_REPO}/diffusion_models/{_name}"),
        }


class Installer:
    def __init__(self):
        self.jobs: dict[str, InstallJob] = {}
        self._lock = threading.Lock()

    def status(self) -> list[dict]:
        out = []
        for key, comp in COMPONENTS.items():
            try:
                installed = bool(comp["check"]())
            except Exception as e:
                log.debug(f"controllo {key} fallito: {e}")
                installed = False
            job = self.jobs.get(key)
            out.append({"id": key, "label": comp["label"], "size_gb": comp["size_gb"], "installed": installed,
                        "job": job.to_dict() if job else None})
        return out

    def start(self, component: str) -> dict:
        comp = COMPONENTS.get(component)
        if not comp:
            raise ValueError(f"componente sconosciuto: {component}")
        with self._lock:
            job = self.jobs.get(component)
            if job and job.status == "running":
                return job.to_dict()
            job = self.jobs[component] = InstallJob(component)

        def run():
            try:
                comp["install"](job)
                job.status, job.message = "done", "installato"
                log.info(f"componente video installato: {component}")
            except Exception as e:
                job.status, job.message = "error", str(e)
                log.error(f"installazione {component} fallita: {e}")

        threading.Thread(target=run, name=f"install-{component}", daemon=True).start()
        return job.to_dict()


installer = Installer()
