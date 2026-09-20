# ==============================================================================
# sigma_eda_lab/handlers.py — Registrazione del modulo nel kernel
# ==============================================================================
"""EDA Lab non aggiunge route HTTP: tutto cio' che fa passa dai suoi tool MCP.

Il modulo esiste come server MCP e basta. Una tab dedicata avrebbe senso il
giorno in cui ci fosse da mostrare un piazzamento su una tela; finche' il
risultato e' un elenco di spostamenti che un agente applica, un'interfaccia in
piu' sarebbe una superficie da mantenere senza niente da guardarci dentro.
"""
from __future__ import annotations

from core.logger import get_logger

log = get_logger(__name__)


def register_routes(app=None) -> None:
    """Nessuna route HTTP: il modulo vive interamente sui suoi tool MCP."""
    return None


def register_mcp(mcp_hub) -> None:
    """Registra il server MCP di EDA Lab nell'hub del kernel."""
    try:
        from .mcp_server import EdaLabMCPServer
        mcp_hub.register_server(EdaLabMCPServer)
        log.info("[sigma_eda_lab] EDA Lab MCP Server registrato.")
    except Exception as exc:
        log.warning("[sigma_eda_lab] EDA Lab MCP Server non registrato: %s", exc)
