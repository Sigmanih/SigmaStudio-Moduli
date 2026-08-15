# ==============================================================================
# sigma_research_lab/backend/handlers.py
# HTTP routes registration for Pipelines Lab & Dynamic Swarm
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger

log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Registra tutte le route HTTP di Pipelines Lab su FastAPI / Handler Adapter."""
    from core.research_sessions import (
        handle_research_create, handle_research_list, handle_research_status,
        handle_research_delete, handle_research_update_objective,
        handle_research_chat_history, handle_research_update_agents,
    )
    from core.agent_orchestrator import (
        handle_research_decompose, handle_research_next_steps, handle_research_start
    )
    from core.pipeline_engine import (
        handle_pipeline_start, handle_pipeline_status, handle_pipeline_stop
    )

    get_routes = {
        '/api/research/list': handle_research_list,
        '/api/research/status': handle_research_status,
        '/api/research/chat_history': handle_research_chat_history,
        '/api/chat/pipeline/status': handle_pipeline_status,
    }

    post_routes = {
        '/api/research/create': handle_research_create,
        '/api/research/delete': handle_research_delete,
        '/api/research/update_objective': handle_research_update_objective,
        '/api/research/update_agents': handle_research_update_agents,
        '/api/research/decompose': handle_research_decompose,
        '/api/research/next_steps': handle_research_next_steps,
        '/api/research/start': handle_research_start,
        '/api/chat/pipeline/start': handle_pipeline_start,
        '/api/chat/pipeline/stop': handle_pipeline_stop,
    }

    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        for path, fn in get_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._GET_HANDLERS[path] = fn.__name__
        for path, fn in post_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._POST_HANDLERS[path] = fn.__name__
        log.info('[sigma_research_lab] 13 route HTTP collegate a FastAPIHandlerAdapter.')
    except Exception as e:
        log.warning(f'[sigma_research_lab] Avviso binding FastAPIHandlerAdapter: {e}')


def register_mcp(mcp_hub) -> None:
    """Nessun server MCP dedicato (gestito via dynamic swarm)."""
    pass
