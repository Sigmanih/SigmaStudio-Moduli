# ==============================================================================
# sigma_youtube_studio/mcp_server.py — YouTube MCP Server
# ==============================================================================
"""Gli stessi tool dell'harness, esposti all'hub MCP (chat e client esterni).

Tutto cio' che cambia il canale e' SENSITIVE: pubblica a nome dell'operatore.
"""
from typing import Any, Dict

from core.mcp.base_server import BaseMCPServer
from core.mcp.governance import SAFE, SENSITIVE

from . import tools
from . import youtube_api as yt
from .tool_schemas import SCHEMI


class YouTubeMCPServer(BaseMCPServer):
    integration_key = yt.INTEGRATION_KEY
    config_fields = [
        {"key": "client_id", "label": "Client ID OAuth", "placeholder": "1234-abc.apps.googleusercontent.com",
         "type": "text", "help": "Google Cloud Console → Credenziali → ID client OAuth di tipo 'App desktop'. "
                                 "In alternativa lascia il JSON scaricato (client_secret_*.json) in config/."},
        {"key": "client_secret", "label": "Client secret OAuth", "placeholder": "GOCSPX-...", "type": "secret",
         "help": "Lo trovi nello stesso client OAuth."},
    ]

    def __init__(self):
        super().__init__(name="YouTube MCP", version="1.0.0",
                         description="Caricamento, traduzioni, sottotitoli, miniature e statistiche del canale YouTube")
        for schema in SCHEMI:
            fn: Dict[str, Any] = schema.get("function", schema)
            name = fn["name"]
            self.register_tool(
                name=name, description=fn.get("description", ""),
                input_schema=fn.get("parameters") or {"type": "object", "properties": {}},
                handler=lambda _n=name, **kw: tools.esegui(_n, kw),
                safety=SENSITIVE if name in tools.WRITE_TOOLS else SAFE, category="youtube")

    def is_configured(self) -> bool:
        return yt.status()["connected"]
