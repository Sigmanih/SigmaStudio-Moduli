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

Un solo tool scrive sui file del progetto: `kicad_placement_apply`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core.logger import get_logger
from core.mcp.base_server import BaseMCPServer
from core.mcp.governance import SAFE, SENSITIVE

from core.modules.sigma_eda_lab import evaluate as evaluator, placement, rules
from core.modules.sigma_eda_lab.netlist import Component, Net

from . import bridge
from . import kicad_cli as cli

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

        # -- Stato --

        self.register_tool(
            name="kicad_status",
            description=(
                "Stato dell'integrazione KiCad: kicad-cli trovato? Versione? "
                "Da chiamare per prima per verificare che tutto sia a posto."
            ),
            input_schema={"type": "object", "properties": {}},
            handler=self._status,
            safety=SAFE,
            category="eda",
        )

        # -- Lettura --

        self.register_tool(
            name="kicad_board_read",
            description=(
                "Legge un file .kicad_pcb: contorno, componenti, footprint, "
                "net e pad. Le misure sono gia' in millimetri (KiCad non ha "
                "ambiguita' di unita'). Se si passa anche il path dello "
                "schematico, la connettivita' viene dalla netlist completa."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pcb_path": {"type": "string",
                                 "description": "Path al file .kicad_pcb."},
                    "sch_path": {"type": "string",
                                 "description": "Path al file .kicad_sch (opzionale, "
                                                "per la connettivita')."},
                },
                "required": ["pcb_path"],
            },
            handler=self._board_read,
            safety=SAFE,
            category="eda",
        )

        # -- Piazzamento --

        self.register_tool(
            name="kicad_placement_optimize",
            description=(
                "Calcola un piazzamento migliore per i componenti della scheda: "
                "ricottura simulata su lunghezza dei collegamenti, "
                "sovrapposizioni, contorno e disaccoppiamento. NON scrive: "
                "per applicare serve kicad_placement_apply."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pcb_path": {"type": "string"},
                    "sch_path": {"type": "string"},
                    "iterations": {"type": "integer", "default": 4000,
                                   "minimum": 100, "maximum": 100000},
                    "seed": {"type": "integer", "default": 20260920},
                    "lock": {"type": "array", "items": {"type": "string"},
                             "description": "Designator da non muovere."},
                    "regrid": {"type": "boolean", "default": False},
                },
                "required": ["pcb_path"],
            },
            handler=self._placement_optimize,
            safety=SAFE,
            category="eda",
        )

        self.register_tool(
            name="kicad_placement_apply",
            description=(
                "Riscrive le posizioni calcolate nel file .kicad_pcb. Con "
                "dry_run (default) calcola gli spostamenti senza toccare il "
                "file. Con dry_run=false modifica il file."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pcb_path": {"type": "string"},
                    "moves": {
                        "type": "array",
                        "description": "Come li restituisce kicad_placement_optimize.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "designator": {"type": "string"},
                                "x_mm": {"type": "number"},
                                "y_mm": {"type": "number"},
                                "rotation": {"type": "integer",
                                             "enum": [0, 90, 180, 270]},
                            },
                            "required": ["designator", "x_mm", "y_mm"],
                        },
                    },
                    "dry_run": {"type": "boolean", "default": True},
                },
                "required": ["pcb_path", "moves"],
            },
            handler=self._placement_apply,
            safety=SENSITIVE,
            category="eda",
        )

        # -- Valutazione --

        self.register_tool(
            name="kicad_board_evaluate",
            description=(
                "Giudica il piazzamento: sovrapposizioni, contorno, distanze, "
                "disaccoppiamento, net critiche. Restituisce un voto, un "
                "verdetto e per ogni controllo fallito l'elenco dei responsabili."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pcb_path": {"type": "string"},
                    "sch_path": {"type": "string"},
                    "decoupling_prefix": {"type": "string", "default": "C"},
                },
                "required": ["pcb_path"],
            },
            handler=self._board_evaluate,
            safety=SAFE,
            category="eda",
        )

        # -- Dimensionamento piste --

        self.register_tool(
            name="kicad_trace_width",
            description=(
                "Larghezza minima di una pista per una data corrente, secondo "
                "IPC-2221. Non tocca il progetto."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "current_a": {"type": "number", "minimum": 0},
                    "delta_t_c": {"type": "number", "default": 10},
                    "thickness_oz": {"type": "number", "default": 1},
                    "layer": {"type": "string",
                              "enum": ["external", "internal"],
                              "default": "external"},
                },
                "required": ["current_a"],
            },
            handler=self._trace_width,
            safety=SAFE,
            category="eda",
        )

        # -- DRC --

        self.register_tool(
            name="kicad_drc",
            description=(
                "Esegue il DRC (Design Rule Check) via kicad-cli: verifica "
                "clearance, cortocircuiti, piste disconnesse, errori di "
                "schematic parity. Restituisce il report completo in JSON."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pcb_path": {"type": "string"},
                },
                "required": ["pcb_path"],
            },
            handler=self._drc,
            safety=SAFE,
            category="eda",
        )

        # -- ERC --

        self.register_tool(
            name="kicad_erc",
            description=(
                "Esegue l'ERC (Electrical Rule Check) via kicad-cli: verifica "
                "pin non collegati, conflitti di tipo, errori nello schematico. "
                "Restituisce il report in JSON."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sch_path": {"type": "string"},
                },
                "required": ["sch_path"],
            },
            handler=self._erc,
            safety=SAFE,
            category="eda",
        )

        # -- Export Gerber --

        self.register_tool(
            name="kicad_export_gerbers",
            description=(
                "Esporta i file Gerber e drill per la produzione del PCB. "
                "I file vengono salvati nella cartella 'gerbers/' accanto al "
                "file PCB, o nel percorso specificato."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pcb_path": {"type": "string"},
                    "output_dir": {"type": "string",
                                   "description": "Cartella di output (opzionale)."},
                },
                "required": ["pcb_path"],
            },
            handler=self._export_gerbers,
            safety=SAFE,
            category="eda",
        )

        # -- Export BOM --

        self.register_tool(
            name="kicad_export_bom",
            description=(
                "Esporta la Bill of Materials (distinta componenti) dallo "
                "schematico in formato CSV."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sch_path": {"type": "string"},
                    "output_path": {"type": "string",
                                    "description": "Path del file CSV (opzionale)."},
                },
                "required": ["sch_path"],
            },
            handler=self._export_bom,
            safety=SAFE,
            category="eda",
        )

    # --- implementazioni -----------------------------------------------------

    def _status(self) -> Dict[str, Any]:
        return bridge.status()

    def _board_read(self, pcb_path: str,
                    sch_path: str = None) -> Dict[str, Any]:
        try:
            board = bridge.read_board(
                Path(pcb_path),
                sch_path=Path(sch_path) if sch_path else None,
            )
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "board": {"width_mm": board.width, "height_mm": board.height},
            "components": [
                {
                    "designator": c.designator,
                    "x_mm": round(c.x, 4),
                    "y_mm": round(c.y, 4),
                    "rotation": c.rotation,
                    "side": c.side,
                    "locked": c.locked,
                    "footprint": c.footprint,
                    "width_mm": c.width,
                    "height_mm": c.height,
                }
                for c in sorted(board.components.values(),
                                key=lambda c: c.designator)
            ],
            "nets": [
                {"name": n.name, "class": n.net_class, "pins": n.degree}
                for n in board.nets
            ],
            "total_components": len(board.components),
            "total_nets": len(board.nets),
        }

    def _placement_optimize(self, pcb_path: str, sch_path: str = None,
                             iterations: int = 4000, seed: int = 20260920,
                             lock: List[str] = None,
                             regrid: bool = False) -> Dict[str, Any]:
        try:
            board = bridge.read_board(
                Path(pcb_path),
                sch_path=Path(sch_path) if sch_path else None,
            )
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        board = _apply_locks(board, lock)

        before = evaluator.evaluate(board)
        start = placement.seed_grid(board) if regrid else board
        result = placement.optimize(start, iterations=iterations, seed=seed)
        after = evaluator.evaluate(result.board)

        return {
            "ok": True,
            "summary": result.summary(),
            "verdict_before": {"verdict": before.verdict, "score": before.score},
            "verdict_after": {"verdict": after.verdict, "score": after.score},
            "checks_after": [c.to_dict() for c in after.checks],
            "moves": [
                {
                    "designator": c.designator,
                    "x_mm": round(c.x, 4),
                    "y_mm": round(c.y, 4),
                    "rotation": c.rotation,
                }
                for c in sorted(result.board.components.values(),
                                key=lambda c: c.designator)
                if not c.locked
            ],
            "next": (
                "Applicare con kicad_placement_apply, dry_run=true come "
                "primo giro per verificare i reference."
            ),
        }

    def _placement_apply(self, pcb_path: str,
                          moves: List[Dict[str, Any]],
                          dry_run: bool = True) -> Dict[str, Any]:
        pcb = Path(pcb_path)
        try:
            board = bridge.read_board(pcb)
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        wanted = {}
        unknown = []
        for move in moves:
            designator = move.get("designator")
            component = board.components.get(designator)
            if component is None:
                unknown.append(designator)
                continue
            wanted[designator] = component.moved(
                float(move.get("x_mm", component.x)),
                float(move.get("y_mm", component.y)),
                int(move.get("rotation", component.rotation)),
            )

        staged = board.with_components(wanted.values())

        # Calcola l'origine dalla lettura del PCB
        info = bridge.parser.read_pcb(pcb)
        origin = (info.origin_x, info.origin_y)

        try:
            outcome = bridge.apply_placement(
                staged, pcb, origin=origin,
                dry_run=dry_run, only=list(wanted),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "unknown_designators": unknown, **outcome.to_dict()}

    def _board_evaluate(self, pcb_path: str, sch_path: str = None,
                         decoupling_prefix: str = "C") -> Dict[str, Any]:
        try:
            board = bridge.read_board(
                Path(pcb_path),
                sch_path=Path(sch_path) if sch_path else None,
            )
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        report = evaluator.evaluate(board, decoupling_prefix)
        return {"ok": True, **report.to_dict()}

    def _trace_width(self, current_a: float, delta_t_c: float = 10.0,
                      thickness_oz: float = 1.0,
                      layer: str = "external") -> Dict[str, Any]:
        try:
            computed = rules.trace_width(current_a, delta_t_c, thickness_oz, layer)
        except rules.RuleError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            **computed.to_dict(),
            "recommended_mm": rules.suggest_width_mm(current_a, layer, thickness_oz),
            "note": (
                "La larghezza consigliata include un margine del 50% su cio' "
                "che la formula non modella: strozzature alle piazzole, via "
                "sottodimensionati, incisione ai bordi."
            ),
        }

    def _drc(self, pcb_path: str) -> Dict[str, Any]:
        try:
            report = cli.run_drc(Path(pcb_path))
            return {"ok": True, **report}
        except cli.KiCadCLIError as exc:
            return {"ok": False, "error": str(exc)}

    def _erc(self, sch_path: str) -> Dict[str, Any]:
        try:
            report = cli.run_erc(Path(sch_path))
            return {"ok": True, **report}
        except cli.KiCadCLIError as exc:
            return {"ok": False, "error": str(exc)}

    def _export_gerbers(self, pcb_path: str,
                         output_dir: str = None) -> Dict[str, Any]:
        try:
            out = Path(output_dir) if output_dir else None
            gerbers = cli.export_gerbers(Path(pcb_path), out)
            drill = cli.export_drill(Path(pcb_path), out or Path(pcb_path).parent / "gerbers")
            return {
                "ok": True,
                "gerbers": gerbers,
                "drill": drill,
            }
        except cli.KiCadCLIError as exc:
            return {"ok": False, "error": str(exc)}

    def _export_bom(self, sch_path: str,
                     output_path: str = None) -> Dict[str, Any]:
        try:
            out = Path(output_path) if output_path else None
            return cli.export_bom(Path(sch_path), out)
        except cli.KiCadCLIError as exc:
            return {"ok": False, "error": str(exc)}


# --- servizio ------------------------------------------------------------------

def _apply_locks(board, lock: List[str]):
    """Blocca i designator che il chiamante ha chiesto di non muovere."""
    if not lock:
        return board
    from dataclasses import replace
    pinned = [replace(board.components[d], locked=True)
              for d in lock if d in board.components]
    return board.with_components(pinned)
