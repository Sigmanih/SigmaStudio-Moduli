# ==============================================================================
# sigma_roadmap/backend/handlers.py
# HTTP routes registration for Roadmap, Tasks & Audit Trail
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger

log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Registra gli handler delle route /api/tasks sull'adapter FastAPI."""
    try:
        from core.task_handler import (
            handle_api_tasks_get,
            handle_api_tasks_post,
            handle_api_tasks_by_agent,
            handle_api_tasks_assign,
        )
        from core.fastapi_app import FastAPIHandlerAdapter

        FastAPIHandlerAdapter.handle_api_tasks_get = handle_api_tasks_get
        FastAPIHandlerAdapter.handle_api_tasks_post = handle_api_tasks_post
        FastAPIHandlerAdapter.handle_api_tasks_by_agent = handle_api_tasks_by_agent
        FastAPIHandlerAdapter.handle_api_tasks_assign = handle_api_tasks_assign

        FastAPIHandlerAdapter._GET_HANDLERS['/api/tasks'] = 'handle_api_tasks_get'
        FastAPIHandlerAdapter._GET_HANDLERS['/api/tasks/by_agent'] = 'handle_api_tasks_by_agent'
        FastAPIHandlerAdapter._POST_HANDLERS['/api/tasks'] = 'handle_api_tasks_post'
        FastAPIHandlerAdapter._POST_HANDLERS['/api/tasks/assign'] = 'handle_api_tasks_assign'

        log.info('[sigma_roadmap] Route /api/tasks collegate a FastAPIHandlerAdapter.')
    except Exception as e:
        log.warning(f'[sigma_roadmap] Avviso registrazione route: {e}')


def register_mcp(mcp_hub) -> None:
    """Registra Calendar MCP Server."""
    try:
        from .calendar_server import CalendarMCPServer
        server = CalendarMCPServer()
        mcp_hub.register_server(server)
    except Exception as e:
        log.warning(f'[sigma_roadmap] Avviso registrazione CalendarMCPServer: {e}')
