"""Rotte della tab Video Studio: motori, benchmark, componenti, Civitai, LoRA, upload."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import paths
from core.logger import get_logger

log = get_logger("creative_video_studio")

_bench: dict = {"running": False, "started": 0.0, "configs": "", "returncode": None}
_bench_lock = threading.Lock()
_resolved: dict[int, dict] = {}       # versione Civitai risolta -> descrizione (per l'import)


def _qs(handler) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(handler.path).query).items()}


def _ok(handler, **data):
    handler.send_json_response({"success": True, **data})


def _err(handler, msg: str, status: int = 400):
    handler.send_json_response({"success": False, "error": msg}, status)


def _creative_cfg() -> dict:
    from core.modules.sigma_creative_lab.creative_router import model_router
    return model_router.get_config()


def _bench_summary() -> list[dict]:
    """Per ogni configurazione il miglior run a regime (non il primo, che include il caricamento)."""
    f = paths.var_dir() / "bench_video" / "results.json"
    if not f.is_file():
        return []
    try:
        rows = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return []
    best: dict[str, dict] = {}
    for r in rows:
        if not r.get("ok") or (r.get("wall_s") or 0) < 1.0:   # < 1 s = risultato servito dalla cache di ComfyUI
            continue
        cur = best.get(r["config"])
        warm = not r.get("cold")
        if cur is None or (warm and cur.get("cold")) or (warm == (not cur.get("cold")) and r["wall_s"] < cur["wall_s"]):
            best[r["config"]] = r
    out = []
    for r in sorted(best.values(), key=lambda r: r["wall_s"]):
        out.append({"config": r["config"], "label": r.get("label"), "wall_s": round(r["wall_s"], 1),
                    "s_per_step": round(r["s_per_step"], 2) if r.get("s_per_step") else None,
                    "frames": r.get("frames_requested"), "peak_vram_mib": r.get("peak_vram_mib"),
                    "cold": r.get("cold"), "at": r.get("at"), "sheet": r.get("sheet", "")})
    return out


def handle_video_engines(self):
    """GET /api/creative/video/engines — GPU, motori, componenti, benchmark."""
    try:
        from core.modules.sigma_creative_lab.backends.comfy_launcher import (
            BASE_PORT, ComfyInstances, default_flags, find_install,
        )
        from core.modules.sigma_creative_lab.native.installer import _hf_token, installer
        from core.modules.sigma_creative_lab.native.runtime import auto_lanes, get_runtime, gpu_inventory
        from core.modules.sigma_creative_lab.video.production import default_lane_specs
        from core.engine.gpu_lease import leases
        install = find_install()
        instances = []
        for g in gpu_inventory():
            port = BASE_PORT + g["index"]
            stats = ComfyInstances._stats(port)
            instances.append({"gpu": g["index"], "port": port, "alive": stats is not None,
                              "flags": sorted(ComfyInstances._flags_of(stats)) if stats else []})
        ok, why = get_runtime().availability()
        with _bench_lock:
            bench_state = dict(_bench)
        _ok(self,
            gpus=gpu_inventory(), lanes={b: default_lane_specs(b) for b in ("comfyui", "hybrid", "sigma_native")},
            comfy={"installed": bool(install), "path": str(install[1]) if install else "",
                   "default_flags": default_flags(install[0]) if install else [], "instances": instances},
            native={"installed": ok, "detail": why, "lanes": auto_lanes()},
            components=installer.status(), benchmark=_bench_summary(), benchmark_state=bench_state,
            leases=leases.snapshot(), has_hf_token=bool(_hf_token()))
    except Exception as e:
        log.error(f"stato motori video: {e}")
        _err(self, str(e), 500)


def handle_video_benchmark(self):
    """POST /api/creative/video/benchmark {configs, frames, runs} — lancia tools/bench_video_backends.py."""
    from core.modules.sigma_creative_lab.video.production import manager
    data = self.read_json_body()
    if manager.active():
        return _err(self, "una produzione occupa le GPU: il benchmark ne falserebbe i tempi (e viceversa)", 409)
    configs = str(data.get("configs") or "comfy_sage,comfy_sage_easycache")
    if not all(c.replace("_", "").isalnum() for c in configs.split(",")):
        return _err(self, "elenco di configurazioni non valido")
    with _bench_lock:
        if _bench["running"]:
            return _err(self, "benchmark gia' in corso", 409)
        _bench.update(running=True, started=time.time(), configs=configs, returncode=None)
    cmd = [sys.executable, str(paths.project_root() / "tools" / "bench_video_backends.py"), "--configs", configs,
           "--frames", str(int(data.get("frames") or 124)), "--runs", str(int(data.get("runs") or 2)), "--keep",
           "--seed", str(int(time.time()) % 10000)]

    def run():
        log_path = paths.var_dir() / "logs" / "bench_video.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as out:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
            proc = subprocess.run(cmd, cwd=str(paths.project_root()), stdout=out, stderr=subprocess.STDOUT,
                                  creationflags=flags)
        with _bench_lock:
            _bench.update(running=False, returncode=proc.returncode)

    threading.Thread(target=run, name="bench-video", daemon=True).start()
    _ok(self, started=configs)


def handle_video_install(self):
    """POST /api/creative/video/install {component}"""
    from core.modules.sigma_creative_lab.native.installer import installer
    try:
        _ok(self, job=installer.start(str(self.read_json_body().get("component", ""))))
    except ValueError as e:
        _err(self, str(e))


def handle_video_restart(self):
    """POST /api/creative/video/restart — chiude i servizi video; ripartono alla prossima richiesta.

    Serve quando un'istanza resta bloccata o tiene memoria dopo un errore: prima
    l'unico rimedio era riavviare tutto Sigma Studio.
    """
    from core.modules.sigma_creative_lab.backends.comfy_launcher import BASE_PORT, instances
    from core.modules.sigma_creative_lab.video import clip_judge
    from core.modules.sigma_creative_lab.video.editor_jobs import editor_jobs
    from core.modules.sigma_creative_lab.video.production import manager
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    if manager.active():
        return _err(self, "una produzione e' in corso: annullala prima di riavviare i servizi", 409)
    if editor_jobs().busy():
        return _err(self, "un lavoro dell'editor e' in corso: aspetta che finisca", 409)
    try:
        from core.modules.sigma_creative_lab.native.runtime import gpu_inventory
        gpus = len(gpu_inventory()) or 1
    except Exception:
        gpus = 2
    done = {"comfyui": instances.stop_ours([BASE_PORT + g for g in range(gpus)])}
    done["voice"] = voice_runtime.stop()
    clip_judge.judge.stop()
    done["judge"] = True
    log.info(f"servizi video riavviati: {done}")
    _ok(self, stopped=done)


def handle_civitai_resolve(self):
    """GET /api/creative/civitai/resolve?url=..."""
    from core.modules.sigma_creative_lab import civitai_import
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    url = _qs(self).get("url", "")
    try:
        info = civitai_import.resolve(url, _creative_cfg().get("civitai_token", ""))
    except (ValueError, RuntimeError) as e:
        return _err(self, str(e))
    except Exception as e:
        log.error(f"risoluzione Civitai: {e}")
        return _err(self, f"Civitai non raggiungibile: {e}", 502)
    root = discover_models_root()
    for v in info["versions"]:
        if v.get("version_id"):
            _resolved[int(v["version_id"])] = v
        for f in v.get("files") or []:
            f["installed"] = bool(civitai_import.installed_path(root, f))
    _ok(self, **info, has_token=bool(_creative_cfg().get("civitai_token")))


def handle_civitai_import(self):
    """POST /api/creative/civitai/import {version_id, file_ids}"""
    from core.modules.sigma_creative_lab import civitai_import
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    data = self.read_json_body()
    version = _resolved.get(int(data.get("version_id") or 0))
    if not version:
        return _err(self, "versione non risolta: apri prima il link")
    root = discover_models_root()
    if not root:
        return _err(self, "cartella modelli di ComfyUI non trovata", 500)
    _ok(self, files=civitai_import.start_import(version, data.get("file_ids") or [], root,
                                                _creative_cfg().get("civitai_token", "")))


def handle_video_downloads(self):
    """GET /api/creative/video/downloads"""
    from core.modules.sigma_creative_lab.model_downloader import download_manager
    _ok(self, jobs=download_manager.list_jobs())


def handle_loras(self):
    """GET /api/creative/loras?family=minimax_h3"""
    from core.modules.sigma_creative_lab import civitai_import
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    family = _qs(self).get("family", "")
    loras = civitai_import.list_loras(discover_models_root())
    if family:
        # Una LoRA senza metadati non si scarta: puo' essere stata copiata a mano.
        loras = [l for l in loras if not l["family"] or l["family"] == family]
    _ok(self, loras=loras)


def handle_diffusion_models(self):
    """GET /api/creative/video/diffusion_models — elenca i modelli DiT presenti in models/diffusion_models/"""
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    root = discover_models_root()
    if not root:
        return _ok(self, models=[])
    d_dir = Path(root) / "diffusion_models"
    if not d_dir.is_dir():
        return _ok(self, models=[])
    out = []
    for f in sorted(d_dir.glob("*")):
        if f.suffix.lower() not in (".safetensors", ".gguf"):
            continue
        meta = {}
        side = f.with_name(f.name + ".civitai.json")
        if side.is_file():
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        out.append({
            "name": f.name,
            "filename": f.name,
            "path": str(f),
            "size_gb": round(f.stat().st_size / (1024 ** 3), 2),
            "format": f.suffix.lower().lstrip("."),
            "model_name": meta.get("model_name") or f.stem,
            "version_name": meta.get("version_name", ""),
            "family": meta.get("family", ""),
            "base_model": meta.get("base_model", ""),
        })
    _ok(self, models=out)


_IMG_TYPES = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp",
              # Campioni di voce per la clonazione e clip audio per le tracce.
              "wav": ".wav", "x-wav": ".wav", "wave": ".wav", "mpeg": ".mp3", "mp3": ".mp3", "flac": ".flac",
              "ogg": ".ogg"}


def handle_production_upload(self):
    """POST /api/creative/productions/upload {id, filename, data} (data URL o base64) — immagini di riferimento."""
    from core.modules.sigma_creative_lab.video.production import manager
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    raw = str(data.get("data", ""))
    ext = Path(str(data.get("filename", "ref.png"))).suffix.lower().lstrip(".")
    if raw.startswith("data:"):
        header, raw = raw.split(",", 1)
        ext = header.split("/")[1].split(";")[0] if "/" in header else ext
    if ext not in _IMG_TYPES:
        return _err(self, "sono ammesse immagini PNG/JPEG/WebP o audio WAV/MP3/FLAC/OGG")
    try:
        blob = base64.b64decode(raw, validate=True)
    except ValueError:
        return _err(self, "contenuto non valido")
    if len(blob) > 25 * 1024 * 1024:
        return _err(self, "immagine troppo grande (massimo 25 MB)")
    refs = manager.store.path(prod["id"]) / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    stem = "".join(c for c in Path(str(data.get("filename", "ref"))).stem if c.isalnum() or c in "-_")[:40] or "ref"
    target = refs / f"{stem}_{int(time.time())}{_IMG_TYPES[ext]}"
    target.write_bytes(blob)
    from core.modules.sigma_creative_lab.video.production_routes import _url
    _ok(self, path=str(target), url=_url(str(target)))


def handle_creative_secret(self):
    """POST /api/creative/video/token {civitai_token} oppure {hf_token} — salva il token senza rispedirlo alla UI."""
    from core.modules.sigma_creative_lab.creative_router import get_config, model_router, save_config
    data = self.read_json_body()
    key = "hf_token" if "hf_token" in data else "civitai_token"
    token = str(data.get(key, "")).strip()
    if key == "civitai_token" and token and (len(token) < 16 or not token.isalnum()):
        return _err(self, "il token Civitai e' una stringa alfanumerica (Account → API Keys)")
    if key == "hf_token" and token and not (token.startswith("hf_") and len(token) > 20):
        return _err(self, "il token Hugging Face comincia con hf_ (Settings → Access Tokens, tipo Read)")
    cfg = get_config()
    cfg.setdefault("creative", {})[key] = token
    save_config(cfg)
    model_router.update_config(cfg["creative"])
    _ok(self, has_token=bool(token), key=key)


def handle_civitai_installed(self):
    """GET /api/creative/civitai/installed — modelli e LoRA importati da Civitai, con chi li usa."""
    from core.modules.sigma_creative_lab import civitai_import
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    try:
        _ok(self, items=civitai_import.list_installed(discover_models_root()))
    except Exception as e:
        log.error(f"elenco modelli Civitai: {e}")
        _err(self, str(e), 500)


def handle_civitai_delete(self):
    """POST /api/creative/civitai/delete {folder, name, force?} — rimuove un file importato e la sua scheda."""
    from core.modules.sigma_creative_lab import civitai_import
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    data = self.read_json_body()
    try:
        _ok(self, **civitai_import.delete_installed(discover_models_root(), str(data.get("folder", "")),
                                                    str(data.get("name", "")), bool(data.get("force"))))
    except ValueError as e:
        _err(self, str(e))
    except OSError as e:
        # Su Windows un file aperto da ComfyUI non si cancella: lo si dice invece di fallire in silenzio.
        _err(self, f"file in uso (chiudi ComfyUI o attendi il render): {e}", 409)


def handle_civitai_retry(self):
    """POST /api/creative/civitai/retry {folder, name} — riprende un download Civitai interrotto."""
    from core.modules.sigma_creative_lab import civitai_import
    from core.modules.sigma_creative_lab.model_downloader import discover_models_root
    data = self.read_json_body()
    try:
        _ok(self, file=civitai_import.retry_install(discover_models_root(), str(data.get("folder", "")),
                                                   str(data.get("name", "")), _creative_cfg().get("civitai_token", "")))
    except ValueError as e:
        _err(self, str(e))
    except Exception as e:
        log.error(f"ripresa download Civitai: {e}")
        _err(self, str(e), 502)


GET_ROUTES = {
    "/api/creative/video/engines": handle_video_engines,
    "/api/creative/video/downloads": handle_video_downloads,
    "/api/creative/video/diffusion_models": handle_diffusion_models,
    "/api/creative/civitai/resolve": handle_civitai_resolve,
    "/api/creative/loras": handle_loras,
    "/api/creative/civitai/installed": handle_civitai_installed,
}

POST_ROUTES = {
    "/api/creative/video/benchmark": handle_video_benchmark,
    "/api/creative/video/install": handle_video_install,
    "/api/creative/video/restart": handle_video_restart,
    "/api/creative/video/token": handle_creative_secret,
    "/api/creative/civitai/import": handle_civitai_import,
    "/api/creative/civitai/delete": handle_civitai_delete,
    "/api/creative/civitai/retry": handle_civitai_retry,
    "/api/creative/productions/upload": handle_production_upload,
}
