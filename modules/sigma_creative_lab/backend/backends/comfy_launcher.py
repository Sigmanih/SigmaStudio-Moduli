"""Istanze headless di ComfyUI, una per GPU.

ComfyUI usa una sola GPU per processo. Per lavorare con tutte le schede si
avviano piu' istanze della stessa installazione (`--cuda-device N`, porta
8288+N) che condividono la cartella dei modelli: nessun peso viene copiato, e
ogni istanza tiene in memoria solo cio' che la sua GPU sta usando.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from core import paths
from core.logger import get_logger

log = get_logger("comfy_launcher")

# Non 8188: e' la porta di ComfyUI Desktop, che l'utente puo' tenere aperto
# per conto suo. Un'istanza che non abbiamo avviato noi non va mai toccata.
BASE_PORT = 8288
IS_WINDOWS = sys.platform.startswith("win")

_MODEL_FOLDERS = (
    "checkpoints", "clip_vision", "configs", "controlnet", "diffusers", "diffusion_models", "embeddings",
    "loras", "text_encoders", "upscale_models", "vae", "vae_approx", "clip", "unet", "audio_encoders",
    "latent_upscale_models", "frame_interpolation",
)


def find_install(configured: str = "") -> tuple[Path, Path] | None:
    """(python, cartella con main.py) di un'installazione ComfyUI locale."""
    py = "python.exe" if IS_WINDOWS else "python"
    scripts = "Scripts" if IS_WINDOWS else "bin"
    roots = [Path(configured)] if configured else []
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots += [
        local / "Comfy-Desktop" / "ComfyUI-Installs" / "ComfyUI" / "ComfyUI",
        Path.home() / "ComfyUI",
        Path("C:/ComfyUI_windows_portable/ComfyUI"),
        Path.home() / "Documents" / "ComfyUI",
    ]
    for root in roots:
        if not (root / "main.py").is_file():
            continue
        for candidate in (root / ".venv" / scripts / py, root / "venv" / scripts / py,
                          root.parent / "python_embeded" / py):
            if candidate.is_file():
                return candidate, root
    return None


def sage_available(python: Path) -> bool:
    """SageAttention installata nel venv di ComfyUI (pacchetto `sageattention` + Triton)."""
    site = python.parent.parent / "Lib" / "site-packages" if IS_WINDOWS else None
    if site and site.is_dir():
        return (site / "sageattention").is_dir() and any(site.glob("triton*"))
    try:
        out = subprocess.run([str(python), "-c", "import sageattention, triton"], capture_output=True, timeout=60)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def default_flags(python: Path) -> list[str]:
    """Ottimizzazioni sicure per la qualita': SageAttention se installata.

    `--fast fp16_accumulation` accelera ancora ma accumula in FP16: va scelto
    esplicitamente (creative.backends.comfyui.extra_flags) dopo averne visto l'effetto.
    """
    return ["--use-sage-attention"] if sage_available(python) else []


def write_model_paths(models_root: str) -> Path:
    """extra_model_paths.yaml che punta alla cartella modelli condivisa."""
    target = paths.var_dir() / "comfyui" / "extra_model_paths.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["sigma_shared:", f"  base_path: {Path(models_root).as_posix()}", "  is_default: true"]
    lines += [f"  {f}: {f}" for f in _MODEL_FOLDERS]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


class ComfyInstances:
    def __init__(self):
        self._procs: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _stats(port: int) -> dict | None:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/system_stats", timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def _flags_of(stats: dict) -> set[str]:
        argv = (stats.get("system") or {}).get("argv") or []
        out, i = set(), 0
        while i < len(argv):
            a = argv[i]
            if a in ("--use-sage-attention", "--use-flash-attention") or a.startswith("--fast"):
                if a == "--fast":
                    vals = []
                    while i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                        i += 1
                        vals.append(argv[i])
                    out.add("--fast " + " ".join(sorted(vals)))
                else:
                    out.add(a)
            i += 1
        return out

    @staticmethod
    def _normalize(flags: list[str]) -> set[str]:
        out, i = set(), 0
        while i < len(flags):
            a = flags[i]
            if a == "--fast":
                vals = []
                while i + 1 < len(flags) and not flags[i + 1].startswith("--"):
                    i += 1
                    vals.append(flags[i])
                out.add("--fast " + " ".join(sorted(vals)))
            else:
                out.add(a)
            i += 1
        return out

    @staticmethod
    def _device_of(stats: dict) -> int | None:
        argv = (stats.get("system") or {}).get("argv") or []
        if "--cuda-device" in argv:
            try:
                return int(argv[argv.index("--cuda-device") + 1])
            except (IndexError, ValueError):
                return None
        return 0      # senza flag ComfyUI usa la prima GPU

    def ensure(self, gpu: int, port: int | None = None, configured_install: str = "",
               timeout_s: float = 180.0, flags: list[str] | None = None) -> str:
        """URL di un'istanza che usa la GPU indicata con i flag richiesti; la avvia se manca.

        `flags=None` significa le ottimizzazioni predefinite (vedi default_flags).
        Un'istanza nostra con flag diversi viene riavviata; una avviata da altri
        si usa cosi' com'e', perche' chiuderla interromperebbe il lavoro di qualcun altro.
        """
        port = port or BASE_PORT + gpu
        install = find_install(configured_install)
        with self._lock:
            wanted = self._normalize(flags if flags is not None else (default_flags(install[0]) if install else []))
            stats = self._stats(port)
            if stats is None and self._listener_pid(port):
                # Porta occupata ma nessuna risposta: puo' essere un'istanza
                # impegnata a caricare 20 GB di pesi. Si aspetta prima di decidere
                # che e' bloccata, e se e' nostra la si riavvia.
                stats = self._wait_healthy(port, 60)
                if stats is None:
                    pid = self._listener_pid(port)
                    if pid and not self._pid_is_ours(pid):
                        raise RuntimeError(f"ComfyUI sulla porta {port} non risponde e non e' stato avviato da Sigma")
                    log.warning(f"ComfyUI su GPU {gpu} (porta {port}) bloccato: riavvio")
                    self._stop_port(port)
            if stats is not None:
                if self._device_of(stats) != gpu:
                    raise RuntimeError(f"sulla porta {port} gira un ComfyUI su un'altra GPU")
                if self._flags_of(stats) == wanted or not self._is_ours(stats):
                    return f"http://127.0.0.1:{port}"
                log.info(f"ComfyUI su GPU {gpu}: riavvio con flag {sorted(wanted)}")
                self._stop_port(port)
            if not install:
                raise RuntimeError("installazione ComfyUI non trovata (imposta creative.backends.comfyui.install_dir)")
            python, root = install
            from core.modules.sigma_creative_lab.model_downloader import discover_models_root
            models_root = discover_models_root()
            args = [str(python), "main.py", "--listen", "127.0.0.1", "--port", str(port),
                    "--cuda-device", str(gpu), "--disable-auto-launch"]
            args += flags if flags is not None else default_flags(python)
            if "--database-url" in (root / "comfy" / "cli_args.py").read_text(encoding="utf-8", errors="ignore"):
                # Un database per istanza: ComfyUI 0.39 avvisa che due istanze sullo stesso
                # comfyui.db (le nostre o l'app Comfy Desktop) presto non partiranno piu'.
                db = paths.var_dir() / "comfyui" / f"comfyui_gpu{gpu}.db"
                db.parent.mkdir(parents=True, exist_ok=True)
                args += ["--database-url", f"sqlite:///{db.as_posix()}"]
            if models_root:
                args += ["--extra-model-paths-config", str(write_model_paths(models_root))]
                shared = Path(models_root).parent
                for flag, sub in (("--output-directory", "output"), ("--input-directory", "input")):
                    if (shared / sub).is_dir():
                        args += [flag, str(shared / sub)]
            log_path = paths.var_dir() / "logs" / f"comfyui_gpu{gpu}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "ab") as log_file:
                flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
                proc = subprocess.Popen(args, cwd=str(root), stdout=log_file, stderr=subprocess.STDOUT,
                                        creationflags=flags)
            self._procs[port] = proc
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"ComfyUI su GPU {gpu} terminato all'avvio; vedi {log_path}")
                if self._stats(port) is not None:
                    log.info(f"ComfyUI avviato su GPU {gpu} (porta {port}, pid {proc.pid})")
                    return f"http://127.0.0.1:{port}"
                time.sleep(1.0)
            raise TimeoutError(f"ComfyUI su GPU {gpu} non risponde dopo {timeout_s:.0f}s; vedi {log_path}")

    def free(self, port: int) -> None:
        """Libera la VRAM senza chiudere il processo: il prossimo render riparte subito."""
        try:
            requests.post(f"http://127.0.0.1:{port}/free", json={"unload_models": True, "free_memory": True},
                          timeout=30)
        except requests.RequestException as e:
            log.debug(f"/free su {port} non riuscito: {e}")

    @staticmethod
    def _listener_pid(port: int) -> int | None:
        try:
            import psutil
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN and conn.pid:
                    return conn.pid
        except Exception as e:
            log.debug(f"processo in ascolto su {port} non individuabile: {e}")
        return None

    @staticmethod
    def _pid_is_ours(pid: int) -> bool:
        try:
            import psutil
            cmd = " ".join(psutil.Process(pid).cmdline()).replace("\\", "/").lower()
            return str(paths.var_dir() / "comfyui" / "extra_model_paths.yaml").replace("\\", "/").lower() in cmd
        except Exception:
            return False

    def _wait_healthy(self, port: int, seconds: float) -> dict | None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            stats = self._stats(port)
            if stats is not None:
                return stats
            time.sleep(2.0)
        return None

    def restart(self, gpu: int, port: int | None = None) -> str:
        """Riavvia un'istanza nostra bloccata (vedi il watchdog di ComfyClipEngine)."""
        port = port or BASE_PORT + gpu
        pid = self._listener_pid(port)
        if pid and not self._pid_is_ours(pid):
            raise RuntimeError(f"il ComfyUI sulla porta {port} non e' stato avviato da Sigma: riavvialo a mano")
        with self._lock:
            self._stop_port(port)
        return self.ensure(gpu, port)

    @staticmethod
    def _is_ours(stats: dict) -> bool:
        """Avviata da Sigma (anche da un altro processo): riconoscibile dal suo extra_model_paths."""
        argv = (stats.get("system") or {}).get("argv") or []
        ours = str(paths.var_dir() / "comfyui" / "extra_model_paths.yaml")
        return any(Path(a).as_posix().lower() == Path(ours).as_posix().lower() for a in argv)

    def _stop_port(self, port: int) -> None:
        proc = self._procs.pop(port, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            # Avviata da un altro processo Sigma: la si trova dalla porta in ascolto.
            try:
                import psutil
                for conn in psutil.net_connections(kind="tcp"):
                    if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN and conn.pid:
                        target = psutil.Process(conn.pid)
                        for child in target.children(recursive=True):
                            child.kill()
                        target.kill()
            except Exception as e:
                log.warning(f"ComfyUI sulla porta {port} non fermato: {e}")
        deadline = time.monotonic() + 20
        while self._stats(port) is not None and time.monotonic() < deadline:
            time.sleep(0.5)

    def stop_ours(self, ports: list[int]) -> list[int]:
        """Ferma le istanze avviate da Sigma su quelle porte; le altre non si toccano."""
        stopped = []
        for port in ports:
            pid = self._listener_pid(port)
            if pid and self._pid_is_ours(pid):
                with self._lock:
                    self._stop_port(port)
                stopped.append(port)
        return stopped

    def stop_started(self) -> None:
        with self._lock:
            for port, proc in list(self._procs.items()):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                self._procs.pop(port, None)


instances = ComfyInstances()
