# ==============================================================================
# sigma_knowledge/backend/handlers.py
# HTTP routes & MCP server registration for Argomenti, Memoria & Knowledge Graph
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger

log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Registra tutte le route HTTP di Knowledge e Nodes su FastAPI / Handler Adapter."""
    from .node_handler import handle_get_nodes, handle_create_node, handle_delete_node
    from core.data_handler import handle_knowledge_db

    get_routes = {
        '/api/nodes': handle_get_nodes,
        '/api/knowledge_db': handle_knowledge_db,
    }

    post_routes = {
        '/api/nodes/create': handle_create_node,
        '/api/nodes/delete': handle_delete_node,
    }

    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        for path, fn in get_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._GET_HANDLERS[path] = fn.__name__
        for path, fn in post_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._POST_HANDLERS[path] = fn.__name__
        log.info('[sigma_knowledge] Route Knowledge e Nodes collegate a FastAPIHandlerAdapter.')
    except Exception as e:
        log.warning(f'[sigma_knowledge] Avviso binding FastAPIHandlerAdapter: {e}')


def register_mcp(mcp_hub) -> None:
    """Registra il server MCP di Memoria ed Episodic Context nell'hub MCP del kernel."""
    try:
        from .memory_server import MemoryMCPServer
        mcp_hub.register_server(MemoryMCPServer)
        log.info('[sigma_knowledge] Memory MCP Server registrato con successo.')
    except Exception as e:
        log.warning(f'[sigma_knowledge] Memory MCP Server non registrato: {e}')
