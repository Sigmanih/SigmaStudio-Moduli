# ==============================================================================
# sigma_creative_lab/backend/handlers.py
# Punto di ingresso del modulo per la registrazione delle route HTTP.
# Chiamato da core/module_loader.py al boot o all'installazione runtime.
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger
log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Registra tutte le 36 route HTTP di Creative Lab sull'adapter FastAPI / server."""
    from .creative_router import (
        handle_creative_assets, handle_creative_asset_get, handle_creative_asset_lineage,
        handle_creative_asset_versions, handle_creative_backends_status, handle_creative_stats,
        handle_creative_generate, handle_creative_asset_create, handle_creative_asset_update,
        handle_creative_asset_delete, handle_creative_backends_config, handle_creative_upload,
        handle_creative_edit, handle_creative_remove_bg, handle_creative_3d,
        handle_creative_mesh, handle_creative_mesh_info, handle_creative_material,
        handle_creative_render, handle_creative_pipeline_execute, handle_creative_agents_list,
        handle_creative_pipeline_nodes, handle_creative_models, handle_creative_vision,
        handle_creative_segment, handle_creative_video, handle_creative_discover,
        handle_creative_downloads, handle_creative_download_start, handle_creative_download_cancel,
        handle_creative_model_search, handle_creative_model_categories,
        handle_creative_model_inventory, handle_creative_workflows,
        handle_creative_workflow_save, handle_creative_workflow_delete,
    )

    get_routes = {
        '/api/creative/assets': handle_creative_assets,
        '/api/creative/assets/get': handle_creative_asset_get,
        '/api/creative/assets/lineage': handle_creative_asset_lineage,
        '/api/creative/assets/versions': handle_creative_asset_versions,
        '/api/creative/backends/status': handle_creative_backends_status,
        '/api/creative/stats': handle_creative_stats,
        '/api/creative/mesh/info': handle_creative_mesh_info,
        '/api/creative/agents': handle_creative_agents_list,
        '/api/creative/pipeline/nodes': handle_creative_pipeline_nodes,
        '/api/creative/models': handle_creative_models,
        '/api/creative/backends/discover': handle_creative_discover,
        '/api/creative/downloads': handle_creative_downloads,
        '/api/creative/models/search': handle_creative_model_search,
        '/api/creative/models/categories': handle_creative_model_categories,
        '/api/creative/models/inventory': handle_creative_model_inventory,
        '/api/creative/workflows': handle_creative_workflows,
    }

    post_routes = {
        '/api/creative/generate': handle_creative_generate,
        '/api/creative/assets/create': handle_creative_asset_create,
        '/api/creative/assets/update': handle_creative_asset_update,
        '/api/creative/assets/delete': handle_creative_asset_delete,
        '/api/creative/backends/config': handle_creative_backends_config,
        '/api/creative/upload': handle_creative_upload,
        '/api/creative/edit': handle_creative_edit,
        '/api/creative/remove-bg': handle_creative_remove_bg,
        '/api/creative/3d': handle_creative_3d,
        '/api/creative/mesh': handle_creative_mesh,
        '/api/creative/material': handle_creative_material,
        '/api/creative/render': handle_creative_render,
        '/api/creative/pipeline/execute': handle_creative_pipeline_execute,
        '/api/creative/vision': handle_creative_vision,
        '/api/creative/segment': handle_creative_segment,
        '/api/creative/video': handle_creative_video,
        '/api/creative/downloads/start': handle_creative_download_start,
        '/api/creative/downloads/cancel': handle_creative_download_cancel,
        '/api/creative/workflows/save': handle_creative_workflow_save,
        '/api/creative/workflows/delete': handle_creative_workflow_delete,
    }

    # Bind to FastAPIHandlerAdapter if present in runtime
    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        for path, fn in get_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._GET_HANDLERS[path] = fn.__name__
        for path, fn in post_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._POST_HANDLERS[path] = fn.__name__
        log.info('[sigma_creative_lab] 36 route collegate a FastAPIHandlerAdapter.')
    except Exception as e:
        log.warning(f'[sigma_creative_lab] Avviso binding FastAPIHandlerAdapter: {e}')


def register_mcp(mcp_hub) -> None:
    """Registra il server MCP di Creative Lab nell'hub MCP del kernel."""
    try:
        from .mcp_server import CreativeServer
        mcp_hub.register_server('creative', CreativeServer)
        log.info('[sigma_creative_lab] MCP server registrato.')
    except Exception as e:
        log.warning(f'[sigma_creative_lab] MCP server non registrato: {e}')
