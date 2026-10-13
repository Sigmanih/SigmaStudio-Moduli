"""Import di modelli da Civitai: da un link a file pronti per ComfyUI e sd.cpp.

Un link Civitai puo' indicare un'immagine o un video (che cita le versioni di
modello usate), un modello o una singola versione. Una versione contiene piu'
file con ruoli diversi: il DiT, il text encoder, il VAE, LoRA di contorno.
L'import li risolve tutti e per ciascuno decide:

  - **dove va**: la cartella di ComfyUI giusta. L'etichetta di Civitai non
    basta: il pacchetto MiniMax H3 chiama `CLIPVision` un text encoder da
    26 GB, che in `clip_vision` non verrebbe mai trovato;
  - **se si puo' scaricare**: solo formati che non eseguono codice
    (safetensors, GGUF) e solo con le scansioni di Civitai concluse con esito
    positivo; un file `.ckpt`/`.pt` puo' contenere codice arbitrario;
  - **se e' integro**: lo SHA256 pubblicato da Civitai si verifica durante il
    download (vedi model_downloader).

Le parole chiave e il base model di una LoRA finiscono in un file accanto
(`<nome>.civitai.json`): servono per aggiungerle al prompt e per non applicare
una LoRA di un modello a un altro.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from core.logger import get_logger

log = get_logger("civitai_import")

API = "https://civitai.com/api/v1"
CIVITAI_HOSTS = ("civitai.com", "civitai.red")

#: baseModel di Civitai -> famiglia interna (prefissi, dal piu' specifico).
FAMILIES = (
    ("minimax h3", "minimax_h3"),
    ("wan video 2.2", "wan22"), ("wan video", "wan21"),
    ("ltxv", "ltx"), ("ltx", "ltx"),
    ("hunyuan video", "hunyuan_video"),
    ("flux.2", "flux2"), ("flux.1", "flux"), ("flux", "flux"),
    ("qwen", "qwen_image"),
    ("sd 3.5", "sd3"), ("sd 3", "sd3"),
    ("pony", "sdxl"), ("illustrious", "sdxl"), ("noobai", "sdxl"), ("sdxl", "sdxl"),
    ("sd 1.5", "sd15"), ("sd 1.4", "sd15"),
    ("z-image", "z_image"), ("chroma", "chroma"),
)

#: Famiglie che il worker nativo (stable-diffusion.cpp 228c707) sa caricare.
NATIVE_FAMILIES = {"minimax_h3", "wan21", "wan22", "ltx", "hunyuan_video", "flux", "flux2", "qwen_image",
                   "sd3", "sdxl", "sd15", "z_image", "chroma"}

SAFE_FORMATS = {"safetensor", "safetensors", "gguf"}

_TYPE_FOLDER = {
    "lora": "loras", "locon": "loras", "dora": "loras", "enhancement lora": "loras",
    "vae": "vae", "textualinversion": "embeddings", "controlnet": "controlnet", "upscaler": "upscale_models",
    "text encoder": "text_encoders", "diffusion model": "diffusion_models", "unet": "diffusion_models",
    "clipvision": "clip_vision",
}


def family_of(base_model: str) -> str:
    b = (base_model or "").lower()
    return next((fam for prefix, fam in FAMILIES if b.startswith(prefix)), "")


def _headers(token: str) -> dict:
    h = {"User-Agent": "SigmaStudio/1.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(path: str, token: str = "", host: str = "civitai.com", **params) -> dict:
    hosts_to_try = [host] + [h for h in CIVITAI_HOSTS if h != host]
    last_exc = None
    for cur_host in hosts_to_try:
        api_base = f"https://{cur_host}/api/v1"
        try:
            resp = requests.get(f"{api_base}{path}", params=params or None, headers=_headers(token), timeout=30)
            if resp.status_code == 401:
                raise RuntimeError("Civitai richiede un token per questa risorsa: impostalo in Impostazioni → Creative.")
            if resp.status_code == 404:
                last_exc = RuntimeError("risorsa Civitai inesistente o non pubblica")
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_exc = e
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("risorsa Civitai non raggiungibile")


def parse_link(url: str) -> dict:
    """Che cosa indica un link Civitai (.com o .red): immagine, modello o versione."""
    u = urlparse(url.strip())
    host = (u.netloc or "").lower()
    if host and not any(host == d or host.endswith("." + d) for d in CIVITAI_HOSTS):
        raise ValueError("non e' un link Civitai (atteso civitai.com o civitai.red)")
    domain = "civitai.red" if "civitai.red" in host else "civitai.com"
    qs = parse_qs(u.query)
    path = u.path.rstrip("/")
    if m := re.search(r"/images/(\d+)", path):
        return {"kind": "image", "id": int(m.group(1)), "domain": domain}
    if m := re.search(r"/api/download/models/(\d+)", path):
        return {"kind": "version", "id": int(m.group(1)), "domain": domain}
    if m := re.search(r"/model-versions/(\d+)", path):
        return {"kind": "version", "id": int(m.group(1)), "domain": domain}
    if m := re.search(r"/models/(\d+)", path):
        if qs.get("modelVersionId"):
            return {"kind": "version", "id": int(qs["modelVersionId"][0]), "domain": domain}
        return {"kind": "model", "id": int(m.group(1)), "domain": domain}
    if url.strip().isdigit():
        return {"kind": "version", "id": int(url.strip()), "domain": domain}
    raise ValueError("link Civitai non riconosciuto (atteso /images/, /models/ o un id di versione)")


def target_folder(file: dict, model_type: str, family: str) -> str:
    """Cartella ComfyUI per un file di una versione."""
    ftype = (file.get("type") or "").lower()
    size_gb = float(file.get("sizeKB") or 0) / 1024 / 1024
    name = (file.get("name") or "").lower()
    mtype = (model_type or "").lower()
    if ftype in ("model", "pruned model", "training data"):
        if mtype in ("lora", "locon", "dora"):
            return "loras"
        if mtype in ("textualinversion",):
            return "embeddings"
        if mtype == "vae":
            return "vae"
        if mtype == "controlnet":
            return "controlnet"
        if mtype == "upscaler":
            return "upscale_models"
        # Checkpoint: i modelli video e i DiT moderni vengono distribuiti senza
        # VAE/encoder dentro, e ComfyUI li cerca fra i diffusion_models.
        return "checkpoints" if family in ("sd15", "sdxl", "sd3") else "diffusion_models"
    if ftype == "clipvision" and (size_gb > 3 or any(k in name for k in ("qwen", "t5", "umt5", "text", "llm"))):
        return "text_encoders"     # etichetta sbagliata frequente: un vero CLIP vision pesa < 3 GB
    return _TYPE_FOLDER.get(ftype, "")


def _file_entry(f: dict, version: dict, family: str) -> dict:
    meta = f.get("metadata") or {}
    fmt = (meta.get("format") or Path(f.get("name", "")).suffix.lstrip(".")).lower()
    folder = target_folder(f, (version.get("model") or {}).get("type", ""), family)
    reasons = []
    if fmt not in SAFE_FORMATS:
        reasons.append(f"formato {fmt or 'sconosciuto'} non sicuro (puo' eseguire codice)")
    for scan in ("pickleScanResult", "virusScanResult"):
        if f.get(scan) != "Success":
            reasons.append(f"scansione {scan.replace('ScanResult', '')} di Civitai: {f.get(scan) or 'assente'}")
    if not folder:
        reasons.append(f"tipo di file '{f.get('type')}' senza cartella nota")
    return {
        "id": f.get("id"), "name": f.get("name"), "type": f.get("type"), "primary": bool(f.get("primary")),
        "size_gb": round(float(f.get("sizeKB") or 0) / 1024 / 1024, 2), "format": fmt, "precision": meta.get("fp"),
        "folder": folder, "sha256": ((f.get("hashes") or {}).get("SHA256") or "").lower(),
        "download_url": f.get("downloadUrl"), "importable": not reasons, "blocked_reasons": reasons,
    }


def describe_version(version: dict, token: str = "", model: dict | None = None, domain: str = "civitai.com") -> dict:
    family = family_of(version.get("baseModel", ""))
    if model is None and version.get("modelId"):
        try:
            model = _get(f"/models/{version['modelId']}", token, host=domain)
        except Exception as e:
            log.debug(f"licenza del modello {version.get('modelId')} non leggibile: {e}")
            model = {}
    model = model or {}
    words = version.get("trainedWords") or []
    return {
        "version_id": version.get("id"), "version_name": version.get("name"),
        "model_id": version.get("modelId"), "model_name": (version.get("model") or {}).get("name") or model.get("name"),
        "model_type": (version.get("model") or {}).get("type") or model.get("type"),
        "base_model": version.get("baseModel"), "family": family,
        "engines": ["comfyui"] + (["sigma_native"] if family in NATIVE_FAMILIES else []),
        "trained_words": words if isinstance(words, list) else [words],
        "early_access": bool(version.get("earlyAccessEndsAt") or version.get("paidAccess")),
        "license": {
            "commercial_use": model.get("allowCommercialUse"),
            "derivatives": model.get("allowDerivatives"),
            "no_credit": model.get("allowNoCredit"),
        },
        "url": f"https://{domain}/models/{version.get('modelId')}?modelVersionId={version.get('id')}",
        "files": [_file_entry(f, version, family) for f in version.get("files") or []],
    }


def resolve(url: str, token: str = "") -> dict:
    """Tutte le versioni (e i file) dietro un link (.com o .red)."""
    link = parse_link(url)
    domain = link.get("domain", "civitai.com")
    info = {"link": link, "image": None, "versions": []}
    if link["kind"] == "image":
        items = _get("/images", token, host=domain, imageId=link["id"], nsfw=True).get("items") or []
        if not items:
            # Riprova senza nsfw=True se l'endpoint rifiuta il filtro
            items = _get("/images", token, host=domain, imageId=link["id"]).get("items") or []
        if not items:
            raise RuntimeError("immagine Civitai non trovata (o non pubblica)")
        img = items[0]
        info["image"] = {"url": img.get("url"), "type": img.get("type"), "width": img.get("width"),
                         "height": img.get("height"), "base_model": img.get("baseModel"), "meta": img.get("meta")}
        version_ids = img.get("modelVersionIds") or []
    elif link["kind"] == "model":
        model = _get(f"/models/{link['id']}", token, host=domain)
        latest = (model.get("modelVersions") or [])[:1]
        version_ids = [v["id"] for v in latest]
    else:
        version_ids = [link["id"]]
    for vid in version_ids:
        try:
            info["versions"].append(describe_version(_get(f"/model-versions/{vid}", token, host=domain), token, domain=domain))
        except Exception as e:
            info["versions"].append({"version_id": vid, "error": str(e), "files": []})
    return info


def installed_path(models_root: str, entry: dict) -> Path | None:
    """Il file e' gia' presente con la stessa dimensione? (lo SHA256 di 30 GB non si ricalcola a ogni apertura)."""
    if not models_root or not entry.get("folder"):
        return None
    p = Path(models_root) / entry["folder"] / Path(entry["name"]).name
    if p.is_file() and abs(p.stat().st_size / 1024 ** 3 - entry["size_gb"]) < 0.02:
        return p
    return None


def write_sidecar(models_root: str, entry: dict, version: dict) -> Path:
    """Metadati accanto al file: parole chiave, famiglia, licenza, origine."""
    target = Path(models_root) / entry["folder"] / (Path(entry["name"]).name + ".civitai.json")
    target.write_text(json.dumps({
        "source": version.get("url"), "model_name": version.get("model_name"),
        "version_name": version.get("version_name"), "base_model": version.get("base_model"),
        "family": version.get("family"), "trained_words": version.get("trained_words"),
        "license": version.get("license"), "sha256": entry.get("sha256"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def start_import(version: dict, file_ids: list, models_root: str, token: str = "") -> list[dict]:
    """Avvia i download dei file scelti; ritorna un record per file."""
    from core.modules.sigma_creative_lab.model_downloader import custom_asset, download_manager
    out = []
    wanted = {int(i) for i in file_ids}
    for entry in version.get("files") or []:
        if int(entry["id"]) not in wanted:
            continue
        if not entry["importable"]:
            out.append({"file": entry["name"], "status": "blocked", "reasons": entry["blocked_reasons"]})
            continue
        existing = installed_path(models_root, entry)
        if existing:
            write_sidecar(models_root, entry, version)
            out.append({"file": entry["name"], "status": "installed", "path": str(existing)})
            continue
        url = entry["download_url"]
        if token:
            # Civitai non accetta l'header sul redirect di /download: il token va nella query.
            url += ("&" if "?" in url else "?") + f"token={token}"
        asset = custom_asset({
            "source": "civitai", "model_id": version.get("version_id"), "folder": entry["folder"],
            "filename": entry["name"], "url": url, "size_gb": entry["size_gb"], "sha256": entry["sha256"],
            "label": f"{version.get('model_name')} · {entry['name']}", "kind": entry["folder"],
            "license": json.dumps(version.get("license")),
        })
        job = download_manager.start(asset, models_root, "")
        write_sidecar(models_root, entry, version)
        out.append({"file": entry["name"], "status": "downloading", "job_id": job.job_id, "target": job.target})
    return out


def list_loras(models_root: str) -> list[dict]:
    """LoRA installate, con le informazioni Civitai quando ci sono."""
    root = Path(models_root) / "loras" if models_root else None
    if not root or not root.is_dir():
        return []
    out = []
    for f in sorted(root.rglob("*")):
        if f.suffix.lower() not in (".safetensors", ".gguf"):
            continue
        meta = {}
        side = f.with_name(f.name + ".civitai.json")
        if side.is_file():
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except ValueError:
                meta = {}
        out.append({"name": f.name, "path": str(f), "size_gb": round(f.stat().st_size / 1024 ** 3, 2),
                    "family": meta.get("family", ""), "base_model": meta.get("base_model", ""),
                    "trained_words": meta.get("trained_words") or [], "model_name": meta.get("model_name", f.stem)})
    return out


#: Cartelle in cui un import da Civitai puo' aver scritto: solo li' si cancella.
MANAGED_FOLDERS = ("loras", "checkpoints", "diffusion_models", "vae", "embeddings", "controlnet", "upscale_models",
                   "text_encoders", "clip_vision")


def _uses(name: str) -> list[dict]:
    """Produzioni che usano un file (le LoRA stanno nella bibbia per nome di file)."""
    from core.modules.sigma_creative_lab.video.production import manager
    out = []
    for summary in manager.store.list():
        prod = manager.store.get(summary["id"]) or {}
        if any(Path(str(l.get("path", ""))).name == name for l in (prod.get("bible") or {}).get("loras") or []):
            out.append({"id": prod["id"], "title": prod.get("title", "")})
    return out


def _download_state(name: str) -> dict:
    """Stato dell'ultimo download di un file (la scheda .civitai.json nasce all'avvio, non alla fine)."""
    try:
        from core.modules.sigma_creative_lab.model_downloader import download_manager
        jobs = [j for j in download_manager.list_jobs() if Path(str(j.get("target", ""))).name == name]
    except Exception:
        jobs = []
    if not jobs:
        return {"state": "incomplete", "error": ""}
    j = jobs[0]
    if j.get("status") in ("queued", "downloading"):
        return {"state": "downloading", "progress": j.get("progress"), "error": ""}
    return {"state": "incomplete", "error": j.get("error", "")}


def list_installed(models_root: str) -> list[dict]:
    """Tutto cio' che e' arrivato da Civitai (riconosciuto dalla scheda .civitai.json accanto al file).

    Una scheda senza file e' un download interrotto: compare come incompleto e si puo' ripulire.
    """
    if not models_root:
        return []
    out = []
    for folder in MANAGED_FOLDERS:
        base = Path(models_root) / folder
        if not base.is_dir():
            continue
        for side in sorted(base.rglob("*.civitai.json")):
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            f = side.with_name(side.name[: -len(".civitai.json")])
            present = f.is_file()
            out.append({
                "name": f.name, "folder": folder, "path": str(f) if present else "", "present": present,
                "size_gb": round(f.stat().st_size / 1024 ** 3, 2) if present else 0,
                "family": meta.get("family", ""), "base_model": meta.get("base_model", ""),
                "model_name": meta.get("model_name") or f.stem, "version_name": meta.get("version_name", ""),
                "trained_words": meta.get("trained_words") or [], "license": meta.get("license"),
                "source": meta.get("source", ""), "used_by": _uses(f.name) if present else [],
                **({"state": "installed", "error": ""} if present else _download_state(f.name)),
            })
    return out


def delete_installed(models_root: str, folder: str, name: str, force: bool = False) -> dict:
    """Rimuove un file importato da Civitai e la sua scheda.

    Solo file con la scheda .civitai.json: i modelli installati dal Video Studio (LTX, Z-Image...)
    o copiati a mano non si cancellano da qui. Se una produzione lo usa serve `force`.
    """
    if folder not in MANAGED_FOLDERS or not name or Path(name).name != name:
        raise ValueError("file non valido")
    base = (Path(models_root) / folder).resolve()
    target = (base / name).resolve()
    side = target.with_name(target.name + ".civitai.json")
    if base not in target.parents or not side.is_file():
        raise ValueError("si possono rimuovere solo i file importati da Civitai")
    users = _uses(name) if target.is_file() else []
    if users and not force:
        return {"deleted": False, "used_by": users}
    freed = target.stat().st_size if target.is_file() else 0
    if target.is_file():
        target.unlink()
    side.unlink()
    log.info(f"rimosso da Civitai: {folder}/{name} ({freed / 1024 ** 3:.2f} GB)")
    return {"deleted": True, "freed_gb": round(freed / 1024 ** 3, 2), "used_by": users}


def retry_install(models_root: str, folder: str, name: str, token: str = "") -> dict:
    """Riprende un download rimasto a meta': rilegge la versione dalla scheda e riscarica quel file."""
    if folder not in MANAGED_FOLDERS or not name or Path(name).name != name:
        raise ValueError("file non valido")
    side = Path(models_root) / folder / f"{name}.civitai.json"
    if not side.is_file():
        raise ValueError("scheda Civitai non trovata")
    source = json.loads(side.read_text(encoding="utf-8")).get("source", "")
    version = next((v for v in resolve(source, token)["versions"] if any(f["name"] == name for f in v["files"])), None)
    if version is None:
        raise ValueError("il file non e' piu' nella versione su Civitai")
    entry = next(f for f in version["files"] if f["name"] == name)
    return start_import(version, [entry["id"]], models_root, token)[0]
