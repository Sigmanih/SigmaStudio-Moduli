# ==============================================================================
# sigma_voice_studio/backend/handlers.py
# HTTP routes & MCP server registration for Voice Studio & Neural Speech
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger

log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Registra le route HTTP di Voice Studio su FastAPI / Handler Adapter."""
    from .tts_handler import handle_tts_engines, handle_tts_speak

    get_routes = {
        '/api/tts/engines': handle_tts_engines,
    }

    post_routes = {
        '/api/tts/speak': handle_tts_speak,
    }

    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        for path, fn in get_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._GET_HANDLERS[path] = fn.__name__
        for path, fn in post_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._POST_HANDLERS[path] = fn.__name__
        log.info('[sigma_voice_studio] Route TTS collegate a FastAPIHandlerAdapter.')
    except Exception as e:
        log.warning(f'[sigma_voice_studio] Avviso binding FastAPIHandlerAdapter: {e}')


def register_mcp(mcp_hub) -> None:
    """Registra il Voice MCP Server nell'hub del kernel."""
    try:
        from .mcp_server import VoiceMCPServer
        mcp_hub.register_server(VoiceMCPServer)
        log.info('[sigma_voice_studio] Voice MCP Server registrato.')
    except Exception as e:
        log.warning(f'[sigma_voice_studio] Voice MCP Server non registrato: {e}')
