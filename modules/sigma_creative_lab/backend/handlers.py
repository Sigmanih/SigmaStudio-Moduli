# ==============================================================================
# sigma_creative_lab/backend/handlers.py
# Punto di ingresso del modulo per la registrazione delle route HTTP.
# Chiamato da core/module_loader.py al boot o all'installazione runtime.
# ==============================================================================
from __future__ import annotations
from core.logger import get_logger
log = get_logger(__name__)


def register_routes(app) -> None:
    """Registra tutte le 36 route HTTP di Creative Lab sull'app FastAPI."""
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

    # GET routes
    app.add_api_route('/api/creative/assets',            handle_creative_assets,           methods=['GET'])
    app.add_api_route('/api/creative/assets/get',        handle_creative_asset_get,        methods=['GET'])
    app.add_api_route('/api/creative/assets/lineage',    handle_creative_asset_lineage,    methods=['GET'])
    app.add_api_route('/api/creative/assets/versions',   handle_creative_asset_versions,   methods=['GET'])
    app.add_api_route('/api/creative/backends/status',   handle_creative_backends_status,  methods=['GET'])
    app.add_api_route('/api/creative/stats',             handle_creative_stats,            methods=['GET'])
    app.add_api_route('/api/creative/mesh/info',         handle_creative_mesh_info,        methods=['GET'])
    app.add_api_route('/api/creative/agents',            handle_creative_agents_list,      methods=['GET'])
    app.add_api_route('/api/creative/pipeline/nodes',    handle_creative_pipeline_nodes,   methods=['GET'])
    app.add_api_route('/api/creative/models',            handle_creative_models,           methods=['GET'])
    app.add_api_route('/api/creative/backends/discover', handle_creative_discover,         methods=['GET'])
    app.add_api_route('/api/creative/downloads',         handle_creative_downloads,        methods=['GET'])
    app.add_api_route('/api/creative/models/search',     handle_creative_model_search,     methods=['GET'])
    app.add_api_route('/api/creative/models/categories', handle_creative_model_categories, methods=['GET'])
    app.add_api_route('/api/creative/models/inventory',  handle_creative_model_inventory,  methods=['GET'])
    app.add_api_route('/api/creative/workflows',         handle_creative_workflows,        methods=['GET'])

    # POST routes
    app.add_api_route('/api/creative/generate',          handle_creative_generate,         methods=['POST'])
    app.add_api_route('/api/creative/assets/create',     handle_creative_asset_create,     methods=['POST'])
    app.add_api_route('/api/creative/assets/update',     handle_creative_asset_update,     methods=['POST'])
    app.add_api_route('/api/creative/assets/delete',     handle_creative_asset_delete,     methods=['POST'])
    app.add_api_route('/api/creative/backends/config',   handle_creative_backends_config,  methods=['POST'])
    app.add_api_route('/api/creative/upload',            handle_creative_upload,           methods=['POST'])
    app.add_api_route('/api/creative/edit',              handle_creative_edit,             methods=['POST'])
    app.add_api_route('/api/creative/remove-bg',         handle_creative_remove_bg,        methods=['POST'])
    app.add_api_route('/api/creative/3d',                handle_creative_3d,               methods=['POST'])
    app.add_api_route('/api/creative/mesh',              handle_creative_mesh,             methods=['POST'])
    app.add_api_route('/api/creative/material',          handle_creative_material,         methods=['POST'])
    app.add_api_route('/api/creative/render',            handle_creative_render,           methods=['POST'])
    app.add_api_route('/api/creative/pipeline/execute',  handle_creative_pipeline_execute, methods=['POST'])
    app.add_api_route('/api/creative/vision',            handle_creative_vision,           methods=['POST'])
    app.add_api_route('/api/creative/segment',           handle_creative_segment,          methods=['POST'])
    app.add_api_route('/api/creative/video',             handle_creative_video,            methods=['POST'])
    app.add_api_route('/api/creative/downloads/start',   handle_creative_download_start,   methods=['POST'])
    app.add_api_route('/api/creative/downloads/cancel',  handle_creative_download_cancel,  methods=['POST'])
    app.add_api_route('/api/creative/workflows/save',    handle_creative_workflow_save,    methods=['POST'])
    app.add_api_route('/api/creative/workflows/delete',  handle_creative_workflow_delete,  methods=['POST'])

    log.info('[sigma_creative_lab] 36 route HTTP registrate.')


def register_mcp(mcp_hub) -> None:
    """Registra il server MCP di Creative Lab nell'hub MCP del kernel."""
    try:
        from .mcp_server import CreativeServer
        mcp_hub.register_server('creative', CreativeServer)
        log.info('[sigma_creative_lab] MCP server registrato.')
    except Exception as e:
        log.warning(f'[sigma_creative_lab] MCP server non registrato: {e}')
