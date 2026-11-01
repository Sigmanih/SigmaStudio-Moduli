# ==============================================================================
# sigma_youtube_studio/handlers.py — Rotte /api/youtube/* e aggancio al kernel
# ==============================================================================
"""Le rotte del pannello YouTube. Funzioni sincrone apposta: le chiamate a
Google bloccano, e FastAPI le esegue nel suo pool di thread invece che nel loop."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.logger import get_logger

from . import tools
from . import youtube_api as yt

log = get_logger(__name__)
router = APIRouter()


def _out(result: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Errore YouTube"))
    return result


class ClientBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    client_json: str = ""


class PasteBody(BaseModel):
    url: str


class UploadBody(BaseModel):
    video_path: str
    title: str
    description: str = ""
    tags: Optional[List[str]] = None
    privacy: str = "private"
    default_language: str = ""
    category_id: str = "1"
    contains_synthetic_media: bool = False
    made_for_kids: bool = False
    publish_at: str = ""


class PackageBody(BaseModel):
    package_path: str
    privacy: str = ""


class UpdateBody(BaseModel):
    title: str = ""
    description: str = ""
    tags: Optional[List[str]] = None
    privacy: str = ""
    default_language: str = ""
    localizations: Optional[Dict[str, Dict[str, str]]] = None
    contains_synthetic_media: Optional[bool] = None


@router.get("/status")
def get_status():
    return tools.youtube_status()


@router.post("/client")
def save_client(body: ClientBody):
    try:
        return {"success": True, **yt.save_client_credentials(body.client_id, body.client_secret, body.client_json)}
    except yt.YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/auth/start")
def auth_start(request: Request):
    # Google accetta per le app desktop qualunque porta di loopback: si usa quella su cui ascolta
    # davvero il backend, non quella del dev server di Vite che fa da proxy.
    server = request.scope.get("server") or ("127.0.0.1", 8000)
    redirect = f"http://127.0.0.1:{server[1]}/api/youtube/oauth/callback"
    try:
        return {"success": True, **yt.authorization_url(redirect)}
    except yt.YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8"><title>Sigma Studio · YouTube</title>
<style>body{{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;display:grid;place-items:center;
height:100vh;margin:0}}div{{max-width:460px;text-align:center}}h1{{color:{color}}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div><script>setTimeout(()=>window.close(),{close})</script></body></html>"""


@router.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(_PAGE.format(color="#f85149", title="Accesso negato",
                                         text=f"Google ha risposto: {error}. Puoi chiudere questa finestra.",
                                         close=8000), status_code=400)
    try:
        out = yt.complete_authorization(code=code, state=state)
        name = (out.get("channel") or {}).get("title") or "il tuo canale"
        return HTMLResponse(_PAGE.format(color="#3fb950", title="Canale collegato",
                                         text=f"Sigma Studio ora gestisce {name}. Questa finestra si chiude da sola.",
                                         close=2500))
    except yt.YouTubeError as exc:
        return HTMLResponse(_PAGE.format(color="#f85149", title="Collegamento non riuscito", text=str(exc),
                                         close=15000), status_code=400)


@router.post("/auth/paste")
def auth_paste(body: PasteBody):
    try:
        return {"success": True, **yt.complete_authorization(pasted_url=body.url)}
    except yt.YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/disconnect")
def disconnect():
    return {"success": True, **yt.disconnect()}


@router.get("/videos")
def videos(limit: int = 25):
    return _out(tools.youtube_list_videos(limit=limit))


@router.post("/videos/{video_id}")
def update_video(video_id: str, body: UpdateBody):
    return _out(tools.youtube_update_video(video_id=video_id, **body.model_dump()))


@router.get("/uploads")
def uploads():
    return {"success": True, "uploads": [{**j, "session_uri": bool(j.get("session_uri"))} for j in yt.list_uploads()]}


@router.post("/uploads/{upload_id}/resume")
def resume(upload_id: str):
    return _out(tools.youtube_resume_upload(upload_id=upload_id))


@router.post("/upload")
def upload(body: UploadBody):
    return _out(tools.youtube_upload_video(**body.model_dump()))


@router.get("/package")
def package(path: str):
    try:
        return {"success": True, "package": yt.load_package(path)}
    except yt.YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/publish")
def publish(body: PackageBody):
    return _out(tools.youtube_publish_package(package_path=body.package_path, privacy=body.privacy))


@router.get("/analytics")
def analytics(days: int = 28, video_id: str = ""):
    return _out(tools.youtube_analytics(days=days, video_id=video_id))


def register_routes(app=None) -> None:
    if app is None:
        raise RuntimeError("register_routes richiede l'istanza FastAPI.")
    app.include_router(router, prefix="/api/youtube", tags=["YouTube"])
    log.info("[sigma_youtube_studio] rotte /api/youtube/* registrate.")


def register_mcp(mcp_hub) -> None:
    try:
        from .mcp_server import YouTubeMCPServer
        mcp_hub.register_server(YouTubeMCPServer())
        log.info("[sigma_youtube_studio] YouTubeMCPServer registrato.")
    except Exception as exc:
        log.warning("[sigma_youtube_studio] YouTubeMCPServer non registrato: %s", exc)


def register_harness_tools() -> List[str]:
    try:
        nomi = tools.registra()
        log.info("[sigma_youtube_studio] %d tool dell'harness registrati.", len(nomi))
        return nomi
    except Exception as exc:
        log.warning("[sigma_youtube_studio] Tool dell'harness non registrati: %s", exc)
        return []
