"""Avvio e uso del worker delle voci (vedi voice/worker.py)."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from core import paths
from core.logger import get_logger

log = get_logger("creative_voice_runtime")

PORT = 8095
IS_WINDOWS = sys.platform.startswith("win")


QWEN_PORT = 8097
VOXCPM_PORT = 8098


def venv_python(venv: str = "voice") -> Path:
    base = paths.store_dir() / "engine_runtime" / venv / ".venv"
    return base / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def _freest_gpu() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        rows = [tuple(int(x) for x in line.split(",")) for line in out.strip().splitlines() if "," in line]
        return max(rows, key=lambda r: r[1])[0] if rows else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class VoiceRuntime:
    def __init__(self, port: int = PORT, venv: str = "voice"):
        self.port, self.venv = port, venv
        self.url = f"http://127.0.0.1:{port}"
        self.token = os.environ.get("SIGMA_VOICE_TOKEN") or secrets.token_hex(16)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def installed(self) -> bool:
        return venv_python(self.venv).is_file()

    def alive(self) -> bool:
        try:
            return requests.get(f"{self.url}/health", timeout=2).json().get("service") == "sigma_voice"
        except (requests.RequestException, ValueError):
            return False

    def ensure(self, timeout_s: float = 60) -> None:
        with self._lock:
            if self.alive():
                try:
                    requests.get(f"{self.url}/voices", headers={"X-Sigma-Token": self.token}, timeout=3).raise_for_status()
                    return
                except requests.RequestException:
                    # Worker rimasto da un processo Sigma precedente (altro token): se e'
                    # il nostro worker.py lo si sostituisce, altrimenti non lo si tocca.
                    if not self._kill_orphan():
                        raise RuntimeError(f"sulla porta {self.port} gira un altro servizio, non il worker voci di Sigma")
            if not self.installed():
                raise RuntimeError("motori voce non installati (Video Studio → Motori → Voci)")
            log_path = paths.var_dir() / "logs" / "sigma_voice_worker.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            worker = Path(__file__).with_name("worker.py")
            env = {**os.environ, "SIGMA_VOICE_TOKEN": self.token, "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
                   "PYTHONWARNINGS": "ignore"}
            gpu = _freest_gpu()
            if gpu is not None and "CUDA_VISIBLE_DEVICES" not in os.environ:
                # La chat che parla tiene il suo LLM sulla GPU 0: il worker voci va dove
                # c'e' piu' memoria libera adesso, invece di contendere quella scheda.
                env["CUDA_VISIBLE_DEVICES"] = str(gpu)
            with open(log_path, "ab") as out:
                flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
                self._proc = subprocess.Popen([str(venv_python(self.venv)), str(worker), "--port", str(self.port),
                                               "--parent-pid", str(os.getpid())], stdout=out,
                                              stderr=subprocess.STDOUT, env=env, creationflags=flags)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    raise RuntimeError(f"il worker voci e' terminato all'avvio; vedi {log_path}")
                if self.alive():
                    return
                time.sleep(0.5)
            raise TimeoutError("il worker voci non risponde")

    def _kill_orphan(self) -> bool:
        try:
            import psutil
            worker = str(Path(__file__).with_name("worker.py")).lower()
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == self.port and conn.status == psutil.CONN_LISTEN and conn.pid:
                    proc = psutil.Process(conn.pid)
                    if any(worker == a.lower() for a in proc.cmdline()):
                        proc.kill()
                        proc.wait(timeout=10)
                        log.info("worker voci orfano sostituito")
                        return True
        except Exception as e:
            log.warning(f"worker voci sulla porta {self.port} non sostituito: {e}")
        return False

    def call(self, path: str, body: dict, timeout: float = 600) -> dict:
        self.ensure()
        resp = requests.post(f"{self.url}{path}", json=body, headers={"X-Sigma-Token": self.token}, timeout=timeout)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise RuntimeError(data.get("error") or f"worker voci: HTTP {resp.status_code}")
        return data

    def synthesize(self, text: str, output_path: Path, engine: str = "chatterbox", **opts) -> dict:
        return self.call("/synthesize", {"text": text, "output_path": str(output_path), "engine": engine, **opts})

    def convert(self, source: Path, target_voice: Path, output_path: Path, seed: int | None = None) -> dict:
        return self.call("/convert", {"source": str(source), "target_voice": str(target_voice),
                                      "output_path": str(output_path), "seed": seed})

    def splice(self, base: Path, patch: Path, regions: list, output_path: Path) -> dict:
        return self.call("/splice", {"base": str(base), "patch": str(patch), "regions": regions,
                                     "output_path": str(output_path)})

    def audio_check(self, path: Path) -> dict:
        return self.call("/audio_check", {"path": str(path)})

    def transcribe(self, path: Path, language: str = "it") -> dict:
        return self.call("/transcribe", {"path": str(path), "language": language})

    def stop(self) -> bool:
        """Chiude il worker (nostro o rimasto da un processo Sigma precedente)."""
        with self._lock:
            proc, self._proc = self._proc, None
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return True
            return self._kill_orphan()

    def unload(self) -> None:
        if self.alive():
            try:
                self.call("/unload", {}, timeout=60)
            except Exception as e:
                log.debug(f"unload del worker voci non riuscito: {e}")


voice_runtime = VoiceRuntime()
# Qwen3-TTS in un processo a parte (vedi worker.py): stesso protocollo, altro venv.
qwen_runtime = VoiceRuntime(QWEN_PORT, "voice_qwen")


# VoxCPM2 nel suo venv: vuole un torch e un transformers suoi.
voxcpm_runtime = VoiceRuntime(VOXCPM_PORT, "voice_voxcpm")


def runtime_for(engine: str) -> VoiceRuntime:
    if engine.startswith("qwen"):
        return qwen_runtime
    if engine.startswith("voxcpm"):
        return voxcpm_runtime
    return voice_runtime
