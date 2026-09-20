# ==============================================================================
# sigma_eda_lab/bridge.py — Il confine con EasyEDA
# ==============================================================================
"""Tutto cio' che sa che dall'altra parte c'e' EasyEDA sta qui dentro.

Il resto del modulo lavora su `Board`: millimetri, centri, designator. EasyEDA
lavora in mil, con identificativi di primitiva e numeri di layer. La traduzione
fra i due mondi vive in questo file solo, cosi' `placement` ed `evaluate` si
provano senza aprire niente, e quando EasyEDA cambia una convenzione c'e' un
posto solo da correggere.

**Le unita'.** `easyeda_pcb_modify_component` dichiara di ricevere mil, e non
dichiara in che unita' `easyeda_pcb_components` restituisca le posizioni. Invece
di scegliere per fede, `detect_scale` confronta l'ingombro dei componenti letti
con le dimensioni della scheda — che quelle arrivano in millimetri dichiarati —
e ricava il fattore vero. Se i due non tornano lo dice, invece di piazzare pezzi
quaranta volte fuori scala.

**Cosa e' verificato.** Le chiamate qui dentro sono scritte sugli schemi di
ingresso e di uscita che il server MCP dichiara, non su risposte osservate: al
momento in cui sono state scritte il bridge verso EasyEDA Pro non era ancora
collegato. Gli schemi fissano i nomi dei campi, non i loro valori, quindi il
primo giro su un progetto vero va fatto con `dry_run` — ed e' il motivo per cui
`apply_placement` parte da li'.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger

from .netlist import (Board, Component, Net, Pin, SIDE_BOTTOM, SIDE_TOP,
                      CLASS_GROUND, CLASS_POWER, CLASS_SIGNAL)
from .placement import PlacementResult

log = get_logger(__name__)

MM_PER_MIL = 0.0254
MIL_PER_MM = 1.0 / MM_PER_MIL

SERVER_ID = "easyeda_pro"

# EasyEDA numera i layer di rame partendo da 1 in alto. Il 2 e' il fondo sulle
# schede a due strati; su schede a piu' strati il fondo e' l'ultimo, ma il lato
# di montaggio resta la distinzione fra 1 e tutto il resto.
LAYER_TOP = 1

# Nomi che indicano una net di alimentazione o di massa quando il progetto non
# dichiara una classe. Servono a dare un peso sensato senza chiedere niente a
# nessuno; chi vuole precisione passa le classi a mano.
_GROUND_HINTS = ("GND", "AGND", "DGND", "VSS", "GROUND", "PGND", "EARTH")
_POWER_HINTS = ("VCC", "VDD", "VBUS", "VIN", "VOUT", "+3V3", "+5V", "3V3",
                "5V", "12V", "VBAT", "AVDD", "VVDD")


class BridgeError(RuntimeError):
    """La chiamata a EasyEDA non e' andata a buon fine."""


class ApprovalRequired(BridgeError):
    """Il gate di governance ha parcheggiato la chiamata in attesa di un umano.

    Non e' un errore: e' il sistema che funziona. Viene distinta perche' chi
    chiama deve poter mostrare la richiesta di approvazione invece di
    presentarla come un guasto.
    """

    def __init__(self, approval: Dict[str, Any]):
        self.approval = approval
        super().__init__(
            f"'{approval.get('tool')}' richiede l'approvazione dell'operatore "
            f"(richiesta {approval.get('request_id')})."
        )

    @property
    def request_id(self) -> str:
        return self.approval.get("request_id", "")


# --- chiamate ------------------------------------------------------------------

#: Un processo nuovo trova l'hub senza server esterni collegati: `reload` li
#: costruisce dalla config, `connect` avvia l'handshake. Senza, ogni chiamata
#: risponde «strumento inesistente» e sembra un difetto del tool invece che una
#: connessione mai aperta.
_collegato = {"fatto": False}


def _assicura_collegamento(hub) -> None:
    if _collegato["fatto"]:
        server = hub.external.get(SERVER_ID)
        if server is not None and server.is_configured():
            return
    hub.reload_external_servers()
    hub.connect_external(SERVER_ID)
    # La prima `tools/call` di ogni sessione HTTP torna con il flusso SSE
    # troncato — un difetto del server. Invece di farla pagare alla prima
    # chiamata vera, che sarebbe imprevedibile, se ne spende una finta qui e se
    # ne ignora l'esito: da quel momento la sessione risponde.
    try:
        hub.execute_tool("easyeda_health_check", {})
    except Exception:
        pass
    _collegato["fatto"] = True


def call(tool: str, arguments: Dict[str, Any] = None,
         hub=None) -> Dict[str, Any]:
    """Chiama un tool EasyEDA attraverso l'hub, e restituisce il corpo JSON.

    Passa dall'hub e non dal transport per una ragione precisa: e' li' che sta
    il gate di governance. Una scorciatoia diretta al server aggirerebbe le
    approvazioni, che e' esattamente cio' che non deve poter fare un modulo.
    """
    esterno = hub is None
    if hub is None:
        from core.mcp.mcp_hub import mcp_hub as hub
        _assicura_collegamento(hub)

    outcome = hub.execute_tool(tool, arguments or {})
    status = outcome.get("status")

    if status == "confirmation_required":
        raise ApprovalRequired(outcome.get("approval", {}))
    if status != "ok":
        messaggio = str(outcome.get("error") or "")
        # «Strumento inesistente» non vuol dire che il tool non esista: vuol
        # dire che il server esterno si e' scollegato e l'hub non ha piu' il
        # suo catalogo. Si riprova una volta dopo aver riagganciato.
        if esterno and "inesistente" in messaggio.lower():
            _collegato["fatto"] = False
            _assicura_collegamento(hub)
            outcome = hub.execute_tool(tool, arguments or {})
            status = outcome.get("status")
            if status == "confirmation_required":
                raise ApprovalRequired(outcome.get("approval", {}))
        if status != "ok":
            raise BridgeError(outcome.get("error") or f"'{tool}' non eseguito.")

    return _payload(outcome.get("result") or {}, tool)


def _payload(result: Dict[str, Any], tool: str) -> Dict[str, Any]:
    """Il corpo di una risposta MCP, comunque il server abbia scelto di darlo."""
    if result.get("isError"):
        text = " ".join(part.get("text", "") for part in result.get("content", []))
        raise BridgeError(text or f"'{tool}' ha risposto con un errore.")

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured

    for part in result.get("content", []):
        if part.get("type") != "text":
            continue
        try:
            parsed = json.loads(part.get("text", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    raise BridgeError(f"'{tool}' ha risposto in una forma non interpretabile.")


def connect(hub=None) -> Dict[str, Any]:
    """Collega il server EasyEDA se non lo e' gia'."""
    if hub is None:
        from core.mcp.mcp_hub import mcp_hub as hub
    hub.reload_external_servers()
    return hub.connect_external(SERVER_ID)


# --- lettura -------------------------------------------------------------------

@dataclass
class ScaleProbe:
    """Cosa si e' capito delle unita' del progetto."""

    scale_mm_per_unit: float
    guess: str
    board_mm: Tuple[float, float]
    span_units: Tuple[float, float]
    confident: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scale_mm_per_unit": self.scale_mm_per_unit,
            "guess": self.guess,
            "board_mm": list(self.board_mm),
            "span_units": list(self.span_units),
            "confident": self.confident,
            "note": self.note,
        }


def detect_scale(board_mm: Tuple[float, float],
                 positions: List[Tuple[float, float]]) -> ScaleProbe:
    """Ricava l'unita' delle coordinate confrontandole col contorno noto.

    I componenti stanno dentro la scheda. Se le loro coordinate coprono
    millequattrocento unita' su una scheda larga quaranta millimetri, l'unita'
    e' il mil; se ne coprono quaranta, e' il millimetro. Dedurlo e' piu' solido
    che fidarsi di una convenzione non documentata, e quando i numeri non
    tornano il risultato lo dice invece di inventarsi un fattore.
    """
    width_mm, height_mm = board_mm
    if not positions or width_mm <= 0 or height_mm <= 0:
        return ScaleProbe(MM_PER_MIL, "mil", board_mm, (0.0, 0.0), False,
                          "Nessuna coordinata o contorno: si assume il mil.")

    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    span = (max(xs) - min(xs), max(ys) - min(ys))

    # Si guarda l'asse con l'escursione maggiore: su una scheda con tutti i
    # pezzi in fila, l'altro asse non dice niente.
    if span[0] >= span[1]:
        span_units, board_side = span[0], width_mm
    else:
        span_units, board_side = span[1], height_mm

    if span_units <= 0:
        return ScaleProbe(MM_PER_MIL, "mil", board_mm, span, False,
                          "Tutti i pezzi nello stesso punto: unita' indeducibile.")

    ratio = span_units / board_side
    candidates = {"mm": 1.0, "mil": MIL_PER_MM, "mil/10": MIL_PER_MM * 10}
    guess, expected = min(candidates.items(), key=lambda kv: abs(_log(ratio / kv[1])))

    # L'escursione dei pezzi e' una frazione della scheda, mai piu' del 100%:
    # si accetta da un decimo in su, e si sospetta tutto il resto.
    fraction = ratio / expected
    confident = 0.10 <= fraction <= 1.10
    note = "" if confident else (
        f"I pezzi coprono il {fraction:.0%} della scheda interpretati come "
        f"'{guess}': la deduzione non e' affidabile, conviene indicare l'unita' "
        "a mano prima di scrivere qualsiasi cosa."
    )
    return ScaleProbe(1.0 / expected, guess, board_mm, span, confident, note)


def infer_footprint_dimensions(footprint: str) -> Tuple[float, float]:
    """Deduce larghezza e altezza in mm dal nome del footprint.

    EasyEDA Pro non espone le dimensioni del bounding box nel metadato
    del componente, ma include quasi sempre le quote nel nome del package
    (es. 'SOIC-8_L5.0-W4.0-...-LS6.1-BL' o 'C0402').
    """
    import re
    name = (footprint or "").upper().strip()
    if not name:
        return 1.0, 1.0

    discrete_match = re.search(r"[CR]?(0201|0402|0603|0805|1206|1210|2512)", name)
    if discrete_match:
        sizes = {
            "0201": (0.6, 0.3),
            "0402": (1.0, 0.5),
            "0603": (1.6, 0.8),
            "0805": (2.0, 1.25),
            "1206": (3.2, 1.6),
            "1210": (3.2, 2.5),
            "2512": (6.3, 3.2),
        }
        return sizes[discrete_match.group(1)]

    l_match = re.search(r"_?L([0-9]+(\.[0-9]+)?)", name)
    ls_match = re.search(r"[-_]LS([0-9]+(\.[0-9]+)?)", name)
    w_match = re.search(r"[-_]W([0-9]+(\.[0-9]+)?)", name)

    length = float(l_match.group(1)) if l_match else None
    width = float(ls_match.group(1)) if ls_match else (float(w_match.group(1)) if w_match else None)

    if length and width:
        return length, width
    if length:
        return length, length

    if "SOT-23-5" in name or "SOT-23" in name:
        return 3.0, 2.8
    if "SOIC-8" in name:
        return 5.0, 6.1
    if "VSSOP-8" in name or "MSOP-8" in name:
        return 3.0, 5.0
    if "QFP" in name or "QFN" in name:
        return 7.0, 7.0

    return 1.0, 1.0


def create_board_outline(project_id: str, width_mm: float = 100.0,
                         height_mm: float = 80.0, hub=None) -> Dict[str, Any]:
    """Crea un contorno scheda rettangolare chiuso sul layer Board Outline (11)."""
    w_mil = width_mm * MIL_PER_MM
    h_mil = height_mm * MIL_PER_MM
    lines = [
        (0, 0, w_mil, 0),
        (w_mil, 0, w_mil, h_mil),
        (w_mil, h_mil, 0, h_mil),
        (0, h_mil, 0, 0),
    ]
    created = []
    for x1, y1, x2, y2 in lines:
        res = call("easyeda_pcb_add_silkscreen_line", {
            "layer": 11,
            "startX": round(x1, 2),
            "startY": round(y1, 2),
            "endX": round(x2, 2),
            "endY": round(y2, 2),
            "lineWidth": 10,
            "confirmWrite": True,
        }, hub)
        created.append(res.get("primitiveId"))
    return {"success": True, "width_mm": width_mm, "height_mm": height_mm, "primitives": created}


def read_board(project_id: str, hub=None, scale_mm_per_unit: float = None,
               netlist: Optional[List[Net]] = None) -> Tuple[Board, ScaleProbe]:
    """Legge il PCB aperto e lo traduce in un `Board`.

    Il PCB conosce i pezzi ma non chi e' collegato a chi: la connettivita' sta
    nello schematico. Chi ce l'ha la passa in `netlist`; chi non la passa
    ottiene una scheda senza net, su cui si possono ancora controllare
    sovrapposizioni e contorno ma non la lunghezza dei collegamenti.
    """
    dimensions = call("easyeda_board_dimensions", {"projectId": project_id}, hub)
    if dimensions.get("not_available") or not dimensions.get("has_outline"):
        raise BridgeError(
            "La scheda non ha un contorno definito: senza contorno non si puo' "
            "ne' piazzare ne' giudicare un piazzamento."
        )
    width_mm = float(dimensions.get("width_mm") or 0.0)
    height_mm = float(dimensions.get("height_mm") or 0.0)

    raw = _read_all_components(project_id, hub)
    positions = [(float(c.get("x") or 0.0), float(c.get("y") or 0.0)) for c in raw]

    probe = detect_scale((width_mm, height_mm), positions)
    scale = scale_mm_per_unit if scale_mm_per_unit else probe.scale_mm_per_unit

    board = Board(width=width_mm or 1.0, height=height_mm or 1.0)
    for entry in raw:
        designator = entry.get("designator") or entry.get("primitiveId") or "?"
        fp_name = entry.get("footprintName") or ""
        def_w, def_h = infer_footprint_dimensions(fp_name)
        try:
            board.add(Component(
                designator=designator,
                width=float(entry.get("width_mm") or def_w),
                height=float(entry.get("height_mm") or def_h),
                x=float(entry.get("x") or 0.0) * scale,
                y=float(entry.get("y") or 0.0) * scale,
                rotation=_snap_rotation(entry.get("rotation")),
                side=SIDE_TOP if int(entry.get("layer") or LAYER_TOP) == LAYER_TOP
                     else SIDE_BOTTOM,
                locked=bool(entry.get("locked")),
                footprint=fp_name,
                primitive_id=entry.get("primitiveId") or "",
            ))
        except Exception as exc:
            log.warning("[eda_lab] componente '%s' scartato: %s", designator, exc)

    if netlist:
        board.nets = list(netlist)
    return board, probe


def _read_all_components(project_id: str, hub) -> List[Dict[str, Any]]:
    """Scorre la paginazione: il tool ne restituisce al massimo 200 per volta."""
    collected: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = call("easyeda_pcb_components",
                    {"projectId": project_id, "limit": 200, "offset": offset}, hub)
        if page.get("not_available"):
            raise BridgeError(
                page.get("error")
                or "EasyEDA non espone il PCB: serve una scheda PCB aperta e a fuoco."
            )
        items = page.get("components") or []
        collected.extend(items)
        total = int(page.get("total") or len(collected))
        offset += len(items)
        if not items or offset >= total:
            return collected


def _snap_rotation(value: Any) -> int:
    """Alla rotazione ortogonale piu' vicina.

    Un progetto puo' contenere pezzi ruotati di 37 gradi. Il modello ne ammette
    quattro, e arrotondare e' meglio che rifiutare la scheda — ma va detto,
    perche' riapplicare il piazzamento raddrizzerebbe quel pezzo.
    """
    try:
        angle = int(round(float(value or 0.0) / 90.0)) * 90
    except (TypeError, ValueError):
        return 0
    return angle % 360


# --- scrittura -----------------------------------------------------------------

@dataclass
class ApplyOutcome:
    """Esito della riscrittura delle posizioni."""

    applied: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    failed: List[Dict[str, Any]] = field(default_factory=list)
    dry_run: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "applied": len(self.applied),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
            "detail": {"applied": self.applied[:50], "skipped": self.skipped[:50],
                       "failed": self.failed[:50]},
        }


def apply_placement(board: Board, scale_mm_per_unit: float = MM_PER_MIL,
                    dry_run: bool = True, hub=None,
                    only: Optional[List[str]] = None) -> ApplyOutcome:
    """Riscrive su EasyEDA le posizioni calcolate.

    `dry_run` usa il `preview` del tool EasyEDA invece di `apply`: il server
    calcola la trasformazione e la restituisce senza toccare il progetto. E' il
    modo di verificare le unita' e i riferimenti su una scheda vera prima di
    muovere qualcosa, ed e' per questo che e' il valore predefinito.

    Un pezzo senza `primitive_id` viene saltato e non silenziosamente ignorato:
    e' arrivato da un modello costruito a mano e non corrisponde a niente nel
    progetto aperto.
    """
    outcome = ApplyOutcome(dry_run=dry_run)
    wanted = set(only) if only else None

    for designator, component in sorted(board.components.items()):
        if wanted is not None and designator not in wanted:
            continue
        if component.locked:
            outcome.skipped.append({"designator": designator, "reason": "bloccato"})
            continue
        if not component.primitive_id:
            outcome.skipped.append({"designator": designator,
                                    "reason": "nessun primitiveId nel progetto"})
            continue

        arguments = {
            "primitiveId": component.primitive_id,
            "mode": "preview" if dry_run else "apply",
            "xMil": round(component.x / scale_mm_per_unit, 4),
            "yMil": round(component.y / scale_mm_per_unit, 4),
            "rotationDeg": float(component.rotation),
            "side": component.side,
        }
        if not dry_run:
            arguments["confirmWrite"] = True

        try:
            response = call("easyeda_pcb_modify_component", arguments, hub)
            outcome.applied.append({"designator": designator,
                                    "xMil": arguments["xMil"],
                                    "yMil": arguments["yMil"],
                                    "rotationDeg": arguments["rotationDeg"],
                                    "response": _brief(response)})
        except ApprovalRequired:
            raise
        except BridgeError as exc:
            outcome.failed.append({"designator": designator, "error": str(exc)})

    return outcome


def _brief(response: Dict[str, Any]) -> Dict[str, Any]:
    """Le poche chiavi di una risposta che vale la pena riportare a un agente."""
    keep = ("applied", "mode", "status", "ok", "error", "warning", "not_available")
    return {k: v for k, v in response.items() if k in keep}


# --- connettivita' -------------------------------------------------------------

def classify_net(name: str) -> str:
    """Indovina la classe di una net dal nome.

    E' un'euristica, e come ogni euristica sbaglia: una net chiamata `VBUS_SENSE`
    e' un segnale, non un'alimentazione. Serve a dare pesi sensati a un progetto
    che non dichiara le classi, non a sostituire chi le dichiara.
    """
    upper = (name or "").upper().strip()
    if any(upper == h or upper.startswith(h + "_") for h in _GROUND_HINTS):
        return CLASS_GROUND
    if any(upper == h or upper.startswith(h + "_") for h in _POWER_HINTS):
        return CLASS_POWER
    return CLASS_SIGNAL


def netlist_from_schematic(project_id: str, hub=None) -> List[Net]:
    """Ricava le net dallo schematico, che e' dove vive la connettivita'.

    Il tool restituisce, per ogni net, i pin collegati. I nomi dei campi sono
    quelli dello schema dichiarato dal server; le varianti accettate qui sotto
    coprono i modi in cui un pin puo' essere identificato senza che la funzione
    debba conoscere quale il server userra' davvero.
    """
    payload = call("easyeda_schematic_validate_netlist", {"projectId": project_id}, hub)
    nets: List[Net] = []

    entries = payload.get("netlist") or payload.get("nets") or []
    for entry in entries:
        name = entry.get("name") or entry.get("netName") or entry.get("net_name") or ""
        connections = []
        pins_list = (entry.get("pins") or entry.get("connections")
                     or entry.get("connected_pins") or entry.get("connected_refs") or [])
        for pin in pins_list:
            if isinstance(pin, dict):
                designator = (pin.get("designator") or pin.get("reference")
                              or pin.get("component") or "")
                number = str(pin.get("pinNumber") or pin.get("number")
                             or pin.get("pin") or "")
            else:
                text = str(pin).replace("-", ".")
                designator, _, number = text.partition(".")
            if designator:
                connections.append((designator, number))
        if name and len(connections) >= 2:
            nets.append(Net(name=name, connections=tuple(connections),
                            net_class=classify_net(name)))
    return nets


def _log(value: float) -> float:
    import math
    return math.log(value) if value > 0 else float("-inf")
