# ==============================================================================
# sigma_kicad_lab/mcp_server.py — KiCad Lab MCP Server
# ==============================================================================
"""I tool con cui Sigma Studio lavora su un progetto KiCad.

La differenza col vecchio EDA Lab e' che questi tool lavorano sui file: non
c'e' un server esterno da collegare, nessun bridge MCP da scaldare, nessuna
GUI che deve restare aperta. Si passa il path del progetto e si lavora.

I tool sono divisi in tre categorie:

1. **Lettura e analisi** — leggono i file, non li modificano.
2. **Piazzamento** — calcola e applica posizioni ottimizzate.
3. **Verifica e produzione** — DRC, ERC, export Gerber e BOM via kicad-cli.

Gli schemi e i permessi provengono dallo stesso catalogo usato dall'harness.
"""
from __future__ import annotations

from core.logger import get_logger
from core.mcp.base_server import BaseMCPServer
from core.mcp.governance import SAFE, SENSITIVE

from . import tools

log = get_logger(__name__)


class KiCadLabMCPServer(BaseMCPServer):
    """Progettazione PCB su file KiCad, senza GUI."""

    def __init__(self):
        super().__init__(
            name="KiCad Lab MCP",
            version="1.0.0",
            description=(
                "Piazzamento ottimizzato, dimensionamento piste, DRC/ERC "
                "headless e export Gerber tramite integrazione nativa con KiCad."
            ),
        )
        self._init_tools()

    # --- registrazione -------------------------------------------------------

    def _init_tools(self) -> None:
        from functools import partial
        from .tool_schemas import SCHEMI
        for schema in SCHEMI:
            definition = schema["function"]
            name = definition["name"]
            self.register_tool(name=name, description=definition["description"],
                               input_schema=definition["parameters"],
                               handler=partial(self._dispatch, name),
                               safety=SAFE if name in tools.READ_TOOLS else SENSITIVE,
                               category="eda")
        self.register_tool(name="kicad_open_project", description="Nome storico di kicad_open.",
                           input_schema={"type": "object", "properties": {"path": {"type": "string"}},
                                         "required": ["path"]},
                           handler=partial(self._dispatch, "kicad_open"), safety=SAFE, category="eda")

    def _dispatch(self, name, **arguments):
        project = arguments.pop("project", None) or arguments.pop("pcb_path", None) or arguments.pop("sch_path", None)
        if project:
            with tools.project_scope(project):
                return tools.esegui(name, arguments)
        return tools.esegui(name, arguments)
