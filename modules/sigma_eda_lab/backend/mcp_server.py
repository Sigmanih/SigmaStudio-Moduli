# ==============================================================================
# sigma_eda_lab/mcp_server.py — EDA Lab MCP Server
# ==============================================================================
"""I tool che Sigma Studio aggiunge a quelli di EasyEDA.

EasyEDA espone le mani: leggi cosa c'e' sulla scheda, sposta un pezzo, traccia
una pista, esporta i Gerber. Non espone nessuna decisione — dove vada messo un
pezzo, quanto larga debba essere una pista, se il risultato sia buono. Questi
tool sono quelle decisioni, ed e' l'unica ragione per cui il modulo esiste:
duplicare cio' che EasyEDA fa gia' sarebbe solo un altro strato da mantenere.

I tool sono **senza stato**. Ognuno rilegge la scheda da EasyEDA invece di
ereditarla dal precedente: un agente puo' chiamarli in qualunque ordine, e il
piazzamento proposto si riferisce sempre al progetto com'e' adesso, non a com'era
tre chiamate fa. Costa qualche lettura in piu' e toglie di mezzo un'intera
categoria di errori.

Uno solo scrive — `eda_placement_apply` — ed e' l'unico marcato SENSITIVE.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.logger import get_logger
from core.mcp.base_server import BaseMCPServer
from core.mcp.governance import SAFE, SENSITIVE

from . import bridge, evaluate as evaluator, placement, rules
from .netlist import Component, Net

log = get_logger(__name__)


class EdaLabMCPServer(BaseMCPServer):
    """Pianificazione, piazzamento e giudizio di una scheda."""

    def __init__(self):
        super().__init__(
            name="EDA Lab MCP",
            version="1.0.0",
            description=(
                "Piazzamento ottimizzato, dimensionamento delle piste e "
                "valutazione di una scheda, sopra il bridge EasyEDA Pro."
            ),
        )
        self._init_tools()

    # --- registrazione -------------------------------------------------------

    def _init_tools(self) -> None:
        self.register_tool(
            name="eda_trace_width",
            description=(
                "Larghezza minima di una pista per una data corrente, secondo "
                "IPC-2221. Restituisce sezione, mil e millimetri, piu' la "
                "larghezza consigliata con margine. Non tocca il progetto."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "current_a": {"type": "number", "minimum": 0,
                                  "description": "Corrente di regime in ampere."},
                    "delta_t_c": {"type": "number", "default": 10,
                                  "description": "Riscaldamento ammesso sopra l'ambiente, in °C."},
                    "thickness_oz": {"type": "number", "default": 1,
                                     "description": "Rame in once per piede quadro."},
                    "layer": {"type": "string", "enum": ["external", "internal"],
                              "default": "external"},
                },
                "required": ["current_a"],
            },
            handler=self._trace_width,
            safety=SAFE,
            category="eda",
        )

        self.register_tool(
            name="eda_board_read",
            description=(
                "Legge dal progetto EasyEDA aperto il contorno, i componenti PCB "
                "e la connettivita' dello schematico, e ne restituisce un modello "
                "con le misure gia' in millimetri. Riporta anche l'unita' dedotta "
                "per le coordinate: va controllata prima di scrivere qualsiasi cosa."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "with_netlist": {
                        "type": "boolean", "default": True,
                        "description": "Legge anche le net dallo schematico.",
                    },
                    "footprints": {
                        "type": "object",
                        "description": (
                            "Ingombri per designator, {\"U1\": {\"width_mm\": 10, "
                            "\"height_mm\": 10}}. EasyEDA non espone le dimensioni "
                            "dei footprint: senza questi ogni pezzo vale 1x1 mm e i "
                            "controlli di sovrapposizione non significano niente."
                        ),
                    },
                },
                "required": ["project_id"],
            },
            handler=self._board_read,
            safety=SAFE,
            category="eda",
        )

        self.register_tool(
            name="eda_placement_optimize",
            description=(
                "Calcola un piazzamento migliore per i componenti della scheda "
                "aperta: ricottura simulata su lunghezza dei collegamenti, "
                "sovrapposizioni, contorno e vicinanza dei condensatori di "
                "disaccoppiamento. Restituisce l'elenco degli spostamenti proposti "
                "in millimetri, con il prima e il dopo. NON scrive: per applicare "
                "serve eda_placement_apply."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "iterations": {"type": "integer", "default": 4000,
                                   "minimum": 100, "maximum": 100000},
                    "seed": {"type": "integer", "default": 20260920,
                             "description": "Stesso seme, stesso risultato."},
                    "lock": {"type": "array", "items": {"type": "string"},
                             "description": "Designator da non muovere, oltre a "
                                            "quelli gia' bloccati nel progetto."},
                    "footprints": {"type": "object"},
                    "regrid": {"type": "boolean", "default": False,
                               "description": "Riparte da una griglia ordinata "
                                              "invece che dal piazzamento attuale."},
                },
                "required": ["project_id"],
            },
            handler=self._placement_optimize,
            safety=SAFE,
            category="eda",
        )

        self.register_tool(
            name="eda_placement_apply",
            description=(
                "Scrive su EasyEDA le posizioni calcolate. Con dry_run usa la "
                "modalita' preview di EasyEDA e non modifica il progetto: e' il "
                "modo di verificare unita' e riferimenti prima di muovere davvero "
                "qualcosa. Con dry_run a falso sposta i componenti."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "moves": {
                        "type": "array",
                        "description": "Come li restituisce eda_placement_optimize.",
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
                "required": ["project_id", "moves"],
            },
            handler=self._placement_apply,
            safety=SENSITIVE,
            category="eda",
        )

        self.register_tool(
            name="eda_board_evaluate",
            description=(
                "Giudica il piazzamento della scheda aperta: sovrapposizioni, "
                "contorno, distanza fra i pezzi, disaccoppiamento, net critiche, "
                "pezzi scollegati. Restituisce un voto, un verdetto e per ogni "
                "controllo fallito l'elenco dei responsabili."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "footprints": {"type": "object"},
                    "decoupling_prefix": {"type": "string", "default": "C"},
                },
                "required": ["project_id"],
            },
            handler=self._board_evaluate,
            safety=SAFE,
            category="eda",
        )

        self.register_tool(
            name="eda_bridge_status",
            description=(
                "Stato del collegamento con EasyEDA Pro: se il server MCP e' "
                "connesso, quanti tool espone e quanti sono classificati come "
                "sensibili. Da chiamare per prima quando qualcosa non risponde."
            ),
            input_schema={"type": "object", "properties": {}},
            handler=self._bridge_status,
            safety=SAFE,
            category="eda",
        )

    # --- implementazioni -----------------------------------------------------

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
            "note": ("La larghezza consigliata include un margine del 50% su cio' "
                     "che la formula non modella: strozzature alle piazzole, via "
                     "sottodimensionati, incisione ai bordi."),
        }

    def _board_read(self, project_id: str, with_netlist: bool = True,
                    footprints: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            nets = bridge.netlist_from_schematic(project_id) if with_netlist else []
            board, probe = bridge.read_board(project_id, netlist=nets)
        except bridge.ApprovalRequired as exc:
            return {"ok": False, "approval": exc.approval}
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        board = _apply_footprints(board, footprints)
        return {
            "ok": True,
            "scale": probe.to_dict(),
            "board": {"width_mm": board.width, "height_mm": board.height},
            "components": [
                {"designator": c.designator, "x_mm": round(c.x, 4),
                 "y_mm": round(c.y, 4), "rotation": c.rotation, "side": c.side,
                 "locked": c.locked, "footprint": c.footprint,
                 "width_mm": c.width, "height_mm": c.height}
                for c in sorted(board.components.values(), key=lambda c: c.designator)
            ],
            "nets": [{"name": n.name, "class": n.net_class, "pins": n.degree}
                     for n in board.nets],
        }

    def _placement_optimize(self, project_id: str, iterations: int = 4000,
                            seed: int = 20260920, lock: List[str] = None,
                            footprints: Dict[str, Any] = None,
                            regrid: bool = False) -> Dict[str, Any]:
        try:
            nets = bridge.netlist_from_schematic(project_id)
            board, probe = bridge.read_board(project_id, netlist=nets)
        except bridge.ApprovalRequired as exc:
            return {"ok": False, "approval": exc.approval}
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        if not probe.confident:
            return {"ok": False, "scale": probe.to_dict(),
                    "error": ("L'unita' delle coordinate non e' deducibile con "
                              "sicurezza. Ottimizzare su una scala sbagliata "
                              "produce spostamenti senza senso: " + probe.note)}

        board = _apply_footprints(board, footprints)
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
                {"designator": c.designator, "x_mm": round(c.x, 4),
                 "y_mm": round(c.y, 4), "rotation": c.rotation}
                for c in sorted(result.board.components.values(),
                                key=lambda c: c.designator)
                if not c.locked
            ],
            "next": ("Applicare con eda_placement_apply, dry_run=true come primo "
                     "giro per verificare unita' e riferimenti."),
        }

    def _placement_apply(self, project_id: str, moves: List[Dict[str, Any]],
                         dry_run: bool = True) -> Dict[str, Any]:
        try:
            board, probe = bridge.read_board(project_id)
        except bridge.ApprovalRequired as exc:
            return {"ok": False, "approval": exc.approval}
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        if not probe.confident:
            return {"ok": False, "scale": probe.to_dict(),
                    "error": "Unita' delle coordinate incerta: " + probe.note}

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
        try:
            outcome = bridge.apply_placement(
                staged, scale_mm_per_unit=probe.scale_mm_per_unit,
                dry_run=dry_run, only=list(wanted))
        except bridge.ApprovalRequired as exc:
            return {"ok": False, "approval": exc.approval}
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "unknown_designators": unknown, **outcome.to_dict()}

    def _board_evaluate(self, project_id: str, footprints: Dict[str, Any] = None,
                        decoupling_prefix: str = "C") -> Dict[str, Any]:
        try:
            nets = bridge.netlist_from_schematic(project_id)
            board, probe = bridge.read_board(project_id, netlist=nets)
        except bridge.ApprovalRequired as exc:
            return {"ok": False, "approval": exc.approval}
        except bridge.BridgeError as exc:
            return {"ok": False, "error": str(exc)}

        board = _apply_footprints(board, footprints)
        report = evaluator.evaluate(board, decoupling_prefix)
        return {"ok": True, "scale": probe.to_dict(), **report.to_dict()}

    def _bridge_status(self) -> Dict[str, Any]:
        try:
            return {"ok": True, "easyeda": bridge.connect()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# --- servizio ------------------------------------------------------------------

def _apply_footprints(board, footprints: Dict[str, Any]):
    """Sostituisce gli ingombri di serie con quelli dichiarati dal chiamante."""
    if not footprints:
        return board
    resized = []
    for designator, size in footprints.items():
        component = board.components.get(designator)
        if component is None or not isinstance(size, dict):
            continue
        try:
            resized.append(Component(
                designator=component.designator,
                width=float(size.get("width_mm") or component.width),
                height=float(size.get("height_mm") or component.height),
                x=component.x, y=component.y, rotation=component.rotation,
                side=component.side, locked=component.locked,
                footprint=component.footprint,
                primitive_id=component.primitive_id, pins=component.pins,
            ))
        except Exception as exc:
            log.warning("[eda_lab] ingombro di '%s' ignorato: %s", designator, exc)
    return board.with_components(resized)


def _apply_locks(board, lock: List[str]):
    """Blocca i designator che il chiamante ha chiesto di non muovere."""
    if not lock:
        return board
    from dataclasses import replace
    pinned = [replace(board.components[d], locked=True)
              for d in lock if d in board.components]
    return board.with_components(pinned)
