"""Runtime nativo: il worker Rust `sigma-diffusion` su stable-diffusion.cpp.

Questo modulo sa tre cose:

  - dove stanno il worker, la libreria stable-diffusion.cpp e ffmpeg;
  - quali file compongono un profilo di modello (es. MiniMax H3 in Q4_K_M);
  - come avviare il worker, tenerlo vivo e liberargli la GPU.

Il worker tiene i modelli residenti: il costo di caricamento (decine di GB per
H3) si paga una volta per produzione, non una volta per clip. Per questo il
runtime e' un singleton di processo e il caricamento e' idempotente.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from core import paths
from core.logger import get_logger

log = get_logger("creative_native_runtime")

DEFAULT_PORT = 8091
TOKEN_HEADER = "X-Sigma-Token"
IS_WINDOWS = sys.platform.startswith("win")
_EXE = ".exe" if IS_WINDOWS else ""


# ---------------------------------------------------------------------------
# Profili di modello
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelProfile:
    """Insieme di file che il worker carica in un unico contesto.

    Ogni ruolo elenca piu' nomi di file in ordine di preferenza: il primo
    trovato su disco vince. Cosi' lo stesso profilo funziona sia con i pesi
    scaricati per ComfyUI sia con quelli in `store/`.
    """
    id: str
    label: str
    family: str
    files: dict                       # ruolo LoadSpec -> tuple di nomi file
    capabilities: tuple
    defaults: dict = field(default_factory=dict)
    notes: str = ""


H3_DEFAULTS = {
    # Valori del template ufficiale ComfyUI: confrontare i motori ha senso solo a parita' di ricetta.
    "sample_method": "res_multistep", "scheduler": "simple", "steps": 20, "cfg_scale": 1.0,
    "fps": 24, "width": 864, "height": 480,
}

H3_CAPS = ("text_to_video", "image_to_video", "first_last_to_video", "ref_to_video")

PROFILES: dict[str, ModelProfile] = {p.id: p for p in (
    ModelProfile(
        id="minimax-h3-q4", label="MiniMax H3 · GGUF Q4_K_M", family="minimax_h3",
        files={
            "diffusion_model": ("minimax_h3_fl2va_pruned-Q4_K_M.gguf", "minimax_h3_fl2va-Q4_K_M.gguf"),
            "llm": ("qwen3vl_32b_minimax_h3-Q4_K_M.gguf",),
            "vae": ("minimax_h3_video_vae_fp16.safetensors",),
            "audio_vae": ("minimax_h3_audio_vae_fp32.safetensors",),
        },
        capabilities=H3_CAPS, defaults=H3_DEFAULTS,
        notes="DiT pruned da 11,4 GB: entra quasi tutto nella VRAM di una 16 GB.",
    ),
    ModelProfile(
        id="minimax-h3-int8", label="MiniMax H3 · int8 convrot (pesi ComfyUI)", family="minimax_h3",
        files={
            "diffusion_model": ("minimax_h3_fl2va_pruned_int8_convrot.safetensors",),
            # L'encoder nvfp4_awq di ComfyUI ha scale per blocco che sd.cpp 228c707
            # rifiuta con un GGML_ASSERT (crash del worker): si usa il GGUF.
            "llm": ("qwen3vl_32b_minimax_h3-Q4_K_M.gguf",),
            "vae": ("minimax_h3_video_vae_fp16.safetensors",),
            "audio_vae": ("minimax_h3_audio_vae_fp32.safetensors",),
        },
        capabilities=H3_CAPS, defaults=H3_DEFAULTS,
        notes="Stessi file del template ComfyUI: confronto a parita' di pesi.",
    ),
    ModelProfile(
        id="minimax-h3-ref-q4", label="MiniMax H3 Ref2VA · GGUF Q4_K_M", family="minimax_h3",
        files={
            "diffusion_model": ("minimax_h3_ref2va_pruned-Q4_K_M.gguf", "minimax_h3_ref2va-Q4_K_M.gguf"),
            "llm": ("qwen3vl_32b_minimax_h3-Q4_K_M.gguf",),
            "vae": ("minimax_h3_video_vae_fp16.safetensors",),
            "audio_vae": ("minimax_h3_audio_vae_fp32.safetensors",),
        },
        capabilities=("text_to_video", "ref_to_video"), defaults=H3_DEFAULTS,
        notes="Variante addestrata per i riferimenti: identita' del personaggio piu' stabile.",
    ),
)}

#: Disposizioni dei moduli sui device. I nomi dei device sono quelli di ggml
#: (CUDA0, CUDA1, Vulkan0, CPU) e si leggono da /v1/info.
PLACEMENTS = {
    "offload": {
        "label": "GPU principale + pesi in RAM",
        "spec": {"offload_to_cpu": True},
        "min_gpus": 1,
    },
    "dual_gpu": {
        "label": "DiT su GPU principale, text encoder sulla seconda",
        "spec": {"backend": "diffusion={g0},vae={g0},te={g1}", "offload_to_cpu": True},
        "min_gpus": 2,
    },
    "split_gpu": {
        "label": "DiT diviso su due GPU (layer split)",
        "spec": {"backend": "diffusion={g0}&{g1},vae={g0},te={g1}", "params_backend": "te=cpu"},
        "min_gpus": 2,
    },
    "cpu": {
        "label": "Solo CPU (Raspberry Pi / nessuna GPU)",
        "spec": {"backend": "cpu"},
        "min_gpus": 0,
    },
}


def model_search_dirs(extra: list | None = None) -> list[Path]:
    """Cartelle in cui cercare i pesi, dalla piu' specifica alla piu' generica."""
    dirs: list[Path] = [Path(p) for p in (extra or []) if p]
    dirs += [paths.store_dir() / "engine_runtime" / "sdcpp" / "models", paths.store_dir() / "models" / "diffusion"]
    try:
        from core.modules.sigma_creative_lab.model_downloader import discover_models_root
        root = discover_models_root()
        if root:
            base = Path(root)
            dirs += [base / sub for sub in ("diffusion_models", "unet", "text_encoders", "clip", "vae", "checkpoints", "loras")]
    except Exception as e:
        log.debug(f"cartella modelli ComfyUI non individuabile: {e}")
    return [d for d in dirs if d.is_dir()]


def find_model_file(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        candidate = d / name
        if candidate.is_file():
            return candidate
    return None


def resolve_profile(profile_id: str, extra_dirs: list | None = None) -> tuple[dict, list[str]]:
    """LoadSpec con percorsi assoluti, e l'elenco dei file mancanti."""
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise ValueError(f"profilo sconosciuto: {profile_id}")
    dirs = model_search_dirs(extra_dirs)
    spec, missing = {}, []
    for role, names in profile.files.items():
        found = next((p for p in (find_model_file(n, dirs) for n in names) if p), None)
        if found:
            spec[role] = str(found.resolve())
        else:
            missing.append(names[0])
    return spec, missing


def placement_spec(placement: str, devices: list[str]) -> dict:
    """Parte di LoadSpec che dice dove gira ogni modulo."""
    gpus = [d for d in devices if d.upper().startswith(("CUDA", "VULKAN", "ROCM", "METAL", "SYCL"))]
    if placement.startswith("gpu:"):
        # Un worker per scheda: tutto il contesto su un solo device, pesi in RAM
        # condivisi via mmap fra i worker (lo stesso file non occupa due volte la RAM).
        idx = int(placement.split(":", 1)[1] or 0)
        if idx >= len(gpus):
            raise ValueError(f"GPU {idx} non disponibile (viste: {gpus})")
        return {"backend": gpus[idx], "offload_to_cpu": True, "enable_mmap": True}
    entry = PLACEMENTS.get(placement) or PLACEMENTS["offload"]
    if len(gpus) < entry["min_gpus"]:
        entry = PLACEMENTS["offload"] if gpus else PLACEMENTS["cpu"]
    g0 = gpus[0] if gpus else "CPU"
    g1 = gpus[1] if len(gpus) > 1 else g0
    return {k: (v.format(g0=g0, g1=g1) if isinstance(v, str) else v) for k, v in entry["spec"].items()}


# ---------------------------------------------------------------------------
# Processo del worker
# ---------------------------------------------------------------------------

def _first_existing(candidates: list[Path]) -> Path | None:
    return next((c for c in candidates if c and c.exists()), None)


def locate_worker(configured: str = "") -> Path | None:
    name = f"sigma-diffusion-worker{_EXE}"
    root = paths.project_root()
    return _first_existing([
        Path(configured) if configured else None,
        paths.store_dir() / "engine_runtime" / "sigma_diffusion" / name,
        root / "projects" / "sigma_engine_rust" / "target" / "release" / name,
    ])


def locate_library(configured: str = "") -> Path | None:
    lib = "stable-diffusion.dll" if IS_WINDOWS else "libstable-diffusion.so"
    base = paths.store_dir() / "engine_runtime" / "sdcpp"
    found = _first_existing([Path(configured) if configured else None, base / "bin" / lib, base / lib])
    return found.parent if found and found.is_file() else found


def locate_ffmpeg(configured: str = "") -> Path | None:
    exe = f"ffmpeg{_EXE}"
    local = _first_existing([
        Path(configured) / exe if configured else None,
        paths.store_dir() / "engine_runtime" / "ffmpeg" / "bin" / exe,
    ])
    if local:
        return local.parent
    from shutil import which
    system = which("ffmpeg")
    return Path(system).parent if system else None


class NativeRuntime:
    """Avvia e sorveglia il worker; un'istanza per processo Sigma."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.port = int(self.config.get("port") or DEFAULT_PORT)
        self.url = f"http://127.0.0.1:{self.port}"
        self.token = os.environ.get("SIGMA_DIFFUSION_TOKEN") or secrets.token_hex(16)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._log_path = paths.var_dir() / "logs" / "sigma_diffusion_worker.log"

    # --- HTTP -------------------------------------------------------------

    def headers(self) -> dict:
        return {TOKEN_HEADER: self.token}

    def get(self, path: str, timeout: float = 10.0) -> dict:
        resp = requests.get(f"{self.url}{path}", headers=self.headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict, timeout: float = 30.0) -> dict:
        resp = requests.post(f"{self.url}{path}", json=body, headers=self.headers(), timeout=timeout)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error") or resp.text
            except ValueError:
                detail = resp.text
            raise RuntimeError(f"worker nativo {path}: {detail}")
        return resp.json()

    # --- ciclo di vita ----------------------------------------------------

    def availability(self) -> tuple[bool, str]:
        """Il runtime e' installato? (non dice se e' acceso)."""
        if not locate_worker(self.config.get("worker_path", "")):
            return False, "worker sigma-diffusion non compilato (cargo build --release -p sigma-diffusion)"
        if not locate_library(self.config.get("library_path", "")):
            return False, "stable-diffusion.cpp non installato in store/engine_runtime/sdcpp/bin"
        if not locate_ffmpeg(self.config.get("ffmpeg_path", "")):
            return False, "ffmpeg non trovato"
        return True, "pronto"

    def is_alive(self) -> bool:
        try:
            data = requests.get(f"{self.url}/health", timeout=1.5).json()
            return data.get("service") == "sigma_diffusion"
        except (requests.RequestException, ValueError):
            return False

    def _owns_worker(self) -> bool:
        """Un worker sulla porta ma non avviato da noi avrebbe un altro token."""
        try:
            requests.get(f"{self.url}/v1/info", headers=self.headers(), timeout=2).raise_for_status()
            return True
        except requests.RequestException:
            return False

    def ensure_started(self, timeout_s: float = 30.0) -> None:
        with self._lock:
            if self.is_alive():
                if self._owns_worker():
                    return
                raise RuntimeError(
                    f"sulla porta {self.port} risponde un worker sigma-diffusion avviato da un altro processo: "
                    "fermalo o imposta creative.backends.sigma_native.port")
            ok, why = self.availability()
            if not ok:
                raise RuntimeError(why)
            worker = locate_worker(self.config.get("worker_path", ""))
            lib = locate_library(self.config.get("library_path", ""))
            ffmpeg = locate_ffmpeg(self.config.get("ffmpeg_path", ""))
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "SIGMA_DIFFUSION_TOKEN": self.token, "RUST_LOG": os.environ.get("RUST_LOG", "info")}
            log_file = open(self._log_path, "ab")
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            try:
                self._proc = subprocess.Popen(
                    [str(worker), "--lib", str(lib), "--ffmpeg", str(ffmpeg), "--port", str(self.port)],
                    stdout=log_file, stderr=subprocess.STDOUT, env=env, creationflags=flags,
                )
            finally:
                log_file.close()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    raise RuntimeError(f"il worker nativo e' terminato all'avvio (codice {self._proc.returncode}); "
                                       f"vedi {self._log_path}")
                if self.is_alive():
                    log.info(f"Worker sigma-diffusion avviato su {self.url} (pid {self._proc.pid})")
                    return
                time.sleep(0.3)
            raise TimeoutError(f"il worker nativo non risponde dopo {timeout_s:.0f}s; vedi {self._log_path}")

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def devices(self) -> list[str]:
        info = self.get("/v1/info")
        return [d.get("name", "") for d in info.get("devices", [])]

    def loaded(self) -> dict | None:
        return (self.get("/health", timeout=3) or {}).get("loaded")

    def load_profile(self, profile_id: str, placement: str = "", overrides: dict | None = None,
                     free_llm: bool = True) -> dict:
        """Carica (o conferma gia' caricato) un profilo. Bloccante: puo' durare minuti."""
        self.ensure_started()
        spec, missing = resolve_profile(profile_id, self.config.get("model_dirs") or [])
        if missing:
            raise FileNotFoundError(f"pesi mancanti per {profile_id}: {', '.join(missing)}")
        placement = placement or self.config.get("placement") or "offload"
        spec.update(placement_spec(placement, self.devices()))
        spec.update({"diffusion_fa": True, "rng": "cpu", "eager_load": True})
        if placement != "cpu" and str(spec.get("backend", "")).lower() != "cpu":
            # SageAttention2++ (INT8 QK, FP8 PV): 17,5 -> 10,4 s/step su H3 a
            # 124 frame sulla 5070 Ti. Esiste solo nel backend CUDA.
            spec["sage_attn"] = True
        spec.update(overrides or {})

        current = self.loaded()
        if current and current.get("spec") == {**_LOADSPEC_DEFAULTS, **spec}:
            return current
        if free_llm:
            release_llm_vram()
        log.info(f"Caricamento profilo nativo {profile_id} ({placement})")
        return self.post("/v1/load", spec, timeout=3600)["loaded"]


#: Valori che il worker mette nei campi non specificati: servono a capire se
#: il profilo richiesto e' gia' quello residente senza ricaricarlo.
_LOADSPEC_DEFAULTS = {
    "model": "", "diffusion_model": "", "high_noise_diffusion_model": "", "llm": "", "llm_vision": "",
    "t5xxl": "", "clip_l": "", "vae": "", "audio_vae": "", "taesd": "", "backend": "", "params_backend": "",
    "max_vram": "", "split_mode": "", "offload_to_cpu": False, "diffusion_fa": False, "flash_attn": False,
    "sage_attn": False, "rng": "", "n_threads": 0, "eager_load": False, "enable_mmap": False,
    "conditioning_cache_size": 0, "tensor_type_rules": "", "wtype": "",
}


def release_llm_vram() -> None:
    """Scarica l'LLM della chat prima di un render.

    Il 27B e H3 non stanno insieme su 16 GB: senza questo passo il caricamento
    del video fallirebbe per memoria, o peggio andrebbe in swap sulla RAM
    condivisa del driver e renderebbe ogni clip dieci volte piu' lento.
    L'LLM si ricarica da solo alla prossima richiesta di chat.
    """
    try:
        from core.engine.unified_runtime import sigma_engine
        if getattr(sigma_engine, "loaded_model_name", None):
            # Si aspetta la fine della risposta in corso: scaricato a meta', l'agente
            # che aveva appena avviato il render perdeva la connessione (collaudo Mx0,
            # ConnectionResetError subito dopo video_shot_fix con rerender).
            lock = getattr(sigma_engine, "_generation_lock", None)
            if lock is not None and not lock.acquire(timeout=120):
                log.warning("LLM ancora occupato dopo 120 s: lo scarico comunque")
                lock = None
            try:
                result = sigma_engine.unload()
            finally:
                if lock is not None:
                    lock.release()
            log.info(f"LLM scaricato per liberare la GPU: {result.get('unloaded')}")
    except Exception as e:
        log.warning(f"Impossibile scaricare l'LLM prima del render: {e}")


_runtimes: dict[int, NativeRuntime] = {}
_runtime_lock = threading.Lock()


def get_runtime(config: dict | None = None) -> NativeRuntime:
    """Un runtime per porta: con piu' GPU gira un worker per scheda."""
    port = int((config or {}).get("port") or DEFAULT_PORT)
    with _runtime_lock:
        rt = _runtimes.get(port)
        if rt is None:
            rt = _runtimes[port] = NativeRuntime({**(config or {}), "port": port})
        elif config:
            rt.config.update(config)
        return rt


def all_runtimes() -> list[NativeRuntime]:
    with _runtime_lock:
        return list(_runtimes.values())


def gpu_inventory() -> list[dict]:
    """GPU CUDA con VRAM totale, dalla piu' capiente: decide quante corsie aprire."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit():
            gpus.append({"index": int(parts[0]), "name": parts[1], "vram_gb": round(float(parts[2]) / 1024, 1)})
    return sorted(gpus, key=lambda g: -g["vram_gb"])


def auto_lanes(min_vram_gb: float = 6.0, base_port: int = DEFAULT_PORT) -> list[dict]:
    """Una corsia per GPU con abbastanza VRAM per i blocchi del DiT e il VAE.

    I pesi stanno in RAM e scorrono in VRAM a segmenti, quindi anche una scheda
    da 8 GB genera clip H3: piu' lenta, ma in parallelo alla principale.
    """
    lanes = []
    for i, g in enumerate(sorted(gpu_inventory(), key=lambda g: g["index"])):
        if g["vram_gb"] >= min_vram_gb:
            lanes.append({"placement": f"gpu:{i}", "port": base_port + i, "device_index": g["index"],
                          "label": g["name"], "vram_gb": g["vram_gb"]})
    return sorted(lanes, key=lambda l: -l["vram_gb"])
