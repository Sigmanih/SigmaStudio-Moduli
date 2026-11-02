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
    from .music_routes import handle_music_status, handle_music_jobs, handle_music_generate, handle_music_action
    from .audio_editor_routes import handle_audio_projects, handle_audio_editor_action, handle_audio_upload
    from .library_handler import (
        handle_voice_library, handle_voice_library_create, handle_voice_library_speak, handle_voice_library_update,
    )

    get_routes = {
        '/api/audio-studio/projects': handle_audio_projects,
        '/api/audio-studio/music/status': handle_music_status,
        '/api/audio-studio/music/jobs': handle_music_jobs,
        '/api/tts/engines': handle_tts_engines,
        '/api/voices/library': handle_voice_library,
    }

    post_routes = {
        '/api/audio-studio/editor': handle_audio_editor_action,
        '/api/audio-studio/upload': handle_audio_upload,
        '/api/audio-studio/music/generate': handle_music_generate,
        '/api/audio-studio/music/action': handle_music_action,
        '/api/tts/speak': handle_tts_speak,
        '/api/voices/library/create': handle_voice_library_create,
        '/api/voices/library/speak': handle_voice_library_speak,
        '/api/voices/library/update': handle_voice_library_update,
    }

    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        for path, fn in get_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            if hasattr(FastAPIHandlerAdapter, '_GET_HANDLERS') and isinstance(FastAPIHandlerAdapter._GET_HANDLERS, dict):
                FastAPIHandlerAdapter._GET_HANDLERS[path] = fn.__name__
        for path, fn in post_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            if hasattr(FastAPIHandlerAdapter, '_POST_HANDLERS') and isinstance(FastAPIHandlerAdapter._POST_HANDLERS, dict):
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
