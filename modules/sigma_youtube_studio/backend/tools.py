# ==============================================================================
# sigma_youtube_studio/tools.py — Le operazioni sul canale, per agenti e MCP
# ==============================================================================
"""Un solo elenco di operazioni, usato dall'harness e dal server MCP.

Ogni funzione restituisce un dizionario con `success`: un agente deve leggere
"quota esaurita, riprova domani" e non una traccia di errore Python.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.logger import get_logger

from . import youtube_api as yt

log = get_logger(__name__)


def _ok(**kw) -> Dict[str, Any]:
    return {"success": True, **kw}


def _guard(fn: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    def wrapper(**kw):
        try:
            return fn(**kw)
        except yt.YouTubeError as exc:
            return {"success": False, "error": str(exc)}
    wrapper.__name__ = fn.__name__
    wrapper.__wrapped__ = fn
    return wrapper


@_guard
def youtube_status() -> Dict[str, Any]:
    st = yt.status()
    if st["connected"]:
        try:
            st["channel"] = yt.channel_info()
        except yt.YouTubeError as exc:
            st["channel_error"] = str(exc)
    return _ok(**st)


@_guard
def youtube_list_videos(limit: int = 25) -> Dict[str, Any]:
    return _ok(videos=yt.list_videos(limit))


@_guard
def youtube_upload_video(video_path: str, title: str, description: str = "", tags: Optional[List[str]] = None,
                         privacy: str = "private", default_language: str = "", category_id: str = "1",
                         contains_synthetic_media: bool = False, made_for_kids: bool = False,
                         publish_at: str = "") -> Dict[str, Any]:
    job = yt.start_upload(video_path, title, description, tags, category_id, privacy, default_language,
                          made_for_kids=made_for_kids, contains_synthetic_media=contains_synthetic_media,
                          publish_at=publish_at)
    return _ok(upload_id=job["id"], size=job["size"],
               hint="Il caricamento prosegue in background: controlla con youtube_upload_status.")


@_guard
def youtube_publish_package(package_path: str, privacy: str = "") -> Dict[str, Any]:
    job = yt.publish_package(package_path, privacy)
    return _ok(upload_id=job["id"], size=job["size"],
               hint="Dopo il caricamento si applicano traduzioni, sottotitoli e miniatura del pacchetto.")


@_guard
def youtube_upload_status(upload_id: str = "") -> Dict[str, Any]:
    jobs = [yt.get_upload(upload_id)] if upload_id else yt.list_uploads()[:10]
    return _ok(uploads=[{"id": j["id"], "file": j["file"], "status": j["status"],
                         "percent": round(100 * j["sent"] / max(1, j["size"]), 1),
                         "video_id": j.get("video_id"), "error": j.get("error"), "steps": j.get("steps", [])}
                        for j in jobs])


@_guard
def youtube_resume_upload(upload_id: str) -> Dict[str, Any]:
    job = yt.resume_upload(upload_id)
    return _ok(upload_id=job["id"], status=job["status"])


@_guard
def youtube_update_video(video_id: str, title: str = "", description: str = "", tags: Optional[List[str]] = None,
                         privacy: str = "", default_language: str = "",
                         localizations: Optional[Dict[str, Dict[str, str]]] = None,
                         contains_synthetic_media: Optional[bool] = None) -> Dict[str, Any]:
    return _ok(**yt.update_video(video_id, title, description, tags, default_language=default_language,
                                 privacy=privacy, localizations=localizations,
                                 contains_synthetic_media=contains_synthetic_media))


@_guard
def youtube_upload_caption(video_id: str, language: str, path: str, name: str = "") -> Dict[str, Any]:
    return _ok(**yt.upload_caption(video_id, language, path, name))


@_guard
def youtube_set_thumbnail(video_id: str, image_path: str) -> Dict[str, Any]:
    return _ok(**yt.set_thumbnail(video_id, image_path))


@_guard
def youtube_analytics(days: int = 28, video_id: str = "") -> Dict[str, Any]:
    return _ok(**yt.analytics(days, video_id))


ESECUTORI: Dict[str, Callable[..., Dict[str, Any]]] = {
    "youtube_status": youtube_status,
    "youtube_list_videos": youtube_list_videos,
    "youtube_upload_video": youtube_upload_video,
    "youtube_publish_package": youtube_publish_package,
    "youtube_upload_status": youtube_upload_status,
    "youtube_resume_upload": youtube_resume_upload,
    "youtube_update_video": youtube_update_video,
    "youtube_upload_caption": youtube_upload_caption,
    "youtube_set_thumbnail": youtube_set_thumbnail,
    "youtube_analytics": youtube_analytics,
}

#: Tutto cio' che cambia il canale pubblico dell'operatore: parla a nome suo.
WRITE_TOOLS = {"youtube_upload_video", "youtube_publish_package", "youtube_resume_upload",
               "youtube_update_video", "youtube_upload_caption", "youtube_set_thumbnail"}
READ_TOOLS = set(ESECUTORI) - WRITE_TOOLS

#: I nomi che i tool restituiscono (upload_id, video_id, id) sono quelli che il modello
#: ripassa alla chiamata dopo: si accettano anche quando lo schema ne dichiara un altro.
_SINONIMI: Dict[str, Dict[str, str]] = {
    "youtube_upload_video": {"path": "video_path", "file": "video_path", "video": "video_path",
                             "lang": "default_language", "language": "default_language"},
    "youtube_publish_package": {"path": "package_path", "package": "package_path"},
    "youtube_upload_status": {"id": "upload_id", "job_id": "upload_id"},
    "youtube_resume_upload": {"id": "upload_id", "job_id": "upload_id"},
    "youtube_update_video": {"id": "video_id", "lang": "default_language"},
    "youtube_upload_caption": {"id": "video_id", "lang": "language", "file": "path", "srt": "path"},
    "youtube_set_thumbnail": {"id": "video_id", "path": "image_path", "file": "image_path",
                              "thumbnail": "image_path"},
    "youtube_analytics": {"id": "video_id"},
}


def esegui(tool_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Il punto d'ingresso dell'harness. None se il tool non e' di questo modulo."""
    nome = str(tool_name or "").strip().lower()
    funzione = ESECUTORI.get(nome)
    if funzione is None:
        return None
    tradotti = dict(args or {})
    for alias, canonico in _SINONIMI.get(nome, {}).items():
        if alias in tradotti and canonico not in tradotti:
            tradotti[canonico] = tradotti.pop(alias)
    try:
        return funzione(**tradotti)
    except TypeError as exc:
        import inspect
        attesi = list(inspect.signature(funzione.__wrapped__).parameters)
        return {"success": False, "error": f"Argomenti sbagliati per '{nome}': {exc}. "
                                           f"I parametri accettati sono: {', '.join(attesi) or 'nessuno'}.",
                "accepted_parameters": attesi}
    except Exception as exc:
        log.exception("[youtube] '%s' fallito", nome)
        return {"success": False, "error": str(exc)}


_ALIAS_TOOL = {"carica_su_youtube": "youtube_publish_package", "pubblica_video": "youtube_publish_package",
               "statistiche_youtube": "youtube_analytics"}


def provider():
    from core.harness.tool_providers import ToolProvider

    from .roles import ROLE_CHANNEL_MANAGER
    from .tool_schemas import SCHEMI

    alias = {nome: nome for nome in ESECUTORI}
    alias.update(_ALIAS_TOOL)
    return ToolProvider(id="sigma_youtube_studio", label="YouTube", schemas=tuple(SCHEMI), execute=esegui,
                        read_only=frozenset(READ_TOOLS), write=frozenset(WRITE_TOOLS), aliases=alias,
                        roles=(ROLE_CHANNEL_MANAGER,))


def registra() -> List[str]:
    from core.harness import tool_providers
    return tool_providers.register(provider())
