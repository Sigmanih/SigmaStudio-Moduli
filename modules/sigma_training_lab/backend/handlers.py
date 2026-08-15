# ==============================================================================
# sigma_training_lab/backend/handlers.py
# HTTP routes & MCP server registration for Training Lab & SLM Forge
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger

log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Registra tutti gli handler di Training Lab sull'adapter FastAPI."""
    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        from .training_api import register_training_handlers
        register_training_handlers(FastAPIHandlerAdapter)
        log.info('[sigma_training_lab] Route Training Lab registrate.')
    except Exception as e:
        log.warning(f'[sigma_training_lab] Avviso registrazione route: {e}')


def register_mcp(mcp_hub) -> None:
    """Registra i server MCP di Training e Benchmark nell'hub MCP del kernel."""
    try:
        from .training_server import TrainingMCPServer
        from .benchmark_server import BenchmarkMCPServer
        mcp_hub.register_server(TrainingMCPServer)
        mcp_hub.register_server(BenchmarkMCPServer)
        log.info('[sigma_training_lab] Training & Benchmark MCP Server registrati.')
    except Exception as e:
        log.warning(f'[sigma_training_lab] MCP Server non registrati: {e}')
