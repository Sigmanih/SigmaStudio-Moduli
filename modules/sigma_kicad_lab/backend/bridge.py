# ==============================================================================
# sigma_kicad_lab/bridge.py — Il confine con KiCad
# ==============================================================================
"""Traduzione fra il modello Board e i file KiCad.

Il vecchio bridge EasyEDA doveva gestire unita' incerte (mil? mm? decimi di
mil?), un transport MCP fragile che troncava le risposte, una GUI che doveva
stare aperta e una sessione HTTP da scaldare con chiamate finte. Niente di
tutto questo serve qui.

KiCad lavora in millimetri, i file si leggono dal disco, il formato e'
documentato e deterministico. Il bridge diventa una traduzione fra dataclass:
`KiCadBoardInfo` del parser → `Board` del modello, e viceversa.

**Cosa resta uguale.** Il modello (`Board`, `Component`, `Net`, `Pin`) e gli
algoritmi che ci lavorano (`placement.py`, `evaluate.py`, `rules.py`) non sanno
che KiCad esiste, esattamente come non sapevano di EasyEDA. Il confine e' qui,
in un file solo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger

# Il modello agnostico lo importiamo da sigma_eda_lab, dove e' gia' testato.
from core.modules.sigma_eda_lab.netlist import (
    Board, Component, Net, Pin,
    SIDE_TOP, SIDE_BOTTOM,
    CLASS_GROUND, CLASS_POWER, CLASS_SIGNAL, CLASS_CRITICAL,
)
from core.modules.sigma_eda_lab.placement import PlacementResult

from . import kicad_parser as parser
from . import kicad_cli as cli

log = get_logger(__name__)

# Nomi che indicano massa o alimentazione: stesse euristiche del vecchio bridge,
# perche' la fisica non cambia passando da un EDA all'altro.
_GROUND_HINTS = ("GND", "AGND", "DGND", "VSS", "GROUND", "PGND", "EARTH")
_POWER_HINTS = ("VCC", "VDD", "VBUS", "VIN", "VOUT", "+3V3", "+5V", "3V3",
                "5V", "12V", "VBAT", "AVDD", "DVDD")


class BridgeError(RuntimeError):
    """Qualcosa non ha funzionato nella traduzione verso KiCad."""


# =============================================================================
# Stato del sistema
# =============================================================================

def status() -> Dict[str, Any]:
    """Lo stato dell'integrazione KiCad: trovato? versione? pronto?"""
    kicad_path = cli.find_kicad_cli()
    if kicad_path is None:
        return {
            "ok": False,
            "kicad_found": False,
            "error": (
                "kicad-cli non trovato. Installa KiCad 8+ e assicurati che "
                "l'eseguibile sia nel PATH o in un percorso standard."
            ),
        }
    version_info = cli.kicad_version()
    return {
        "ok": True,
        "kicad_found": True,
        "kicad_cli_path": str(kicad_path),
        "version": version_info.get("version", "sconosciuta"),
    }


# =============================================================================
# Lettura — da file KiCad a modello Board
# =============================================================================

def read_board(pcb_path: Path, sch_path: Path = None) -> Board:
    """Legge un file .kicad_pcb e lo traduce in un Board.

    Se `sch_path` e' fornito, legge anche la connettivita' dallo schematico
    e la aggiunge come net. Altrimenti le net vengono estratte dai pad del PCB
    (meno preciso ma funziona senza lo schematico).
    """
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise BridgeError(f"File PCB non trovato: {pcb_path}")

    info = parser.read_pcb(pcb_path)

    if info.width_mm <= 0 or info.height_mm <= 0:
        raise BridgeError(
            "La scheda non ha un contorno definito su Edge.Cuts: senza contorno "
            "non si puo' ne' piazzare ne' giudicare un piazzamento."
        )

    board = Board(width=info.width_mm, height=info.height_mm)

    for fp in info.footprints:
        if not fp.reference or fp.reference.startswith("#"):
            continue

        pins = [
            Pin(number=pad.number, dx=pad.x - fp.x, dy=pad.y - fp.y,
                net=pad.net_name)
            for pad in fp.pads
        ]

        side = SIDE_TOP if fp.layer in ("F.Cu", "F.SilkS") else SIDE_BOTTOM
        rotation = _snap_rotation(fp.rotation)

        try:
            board.add(Component(
                designator=fp.reference,
                width=fp.width_mm,
                height=fp.height_mm,
                x=fp.x - info.origin_x,   # coordinate relative all'origine della scheda
                y=fp.y - info.origin_y,
                rotation=rotation,
                side=side,
                locked=fp.locked,
                footprint=fp.footprint_lib,
                primitive_id=fp.reference,  # in KiCad il reference e' l'identificativo
                pins=tuple(pins),
            ))
        except Exception as exc:
            log.warning("[kicad_bridge] componente '%s' scartato: %s",
                        fp.reference, exc)

    # Net: dal PCB (raggruppamento dei pad per net) o dallo schematico
    nets = _nets_from_pcb(info)
    if sch_path and Path(sch_path).is_file():
        try:
            sch_nets = _nets_from_schematic(Path(sch_path))
            if sch_nets:
                nets = sch_nets
        except Exception as exc:
            log.warning("[kicad_bridge] netlist dallo schematico fallita, "
                        "uso quella dal PCB: %s", exc)

    board.nets = nets
    return board


def _nets_from_pcb(info: parser.KiCadBoardInfo) -> List[Net]:
    """Ricostruisce le net dai pad del PCB."""
    net_pins: Dict[str, List[Tuple[str, str]]] = {}

    for fp in info.footprints:
        for pad in fp.pads:
            if not pad.net_name or pad.net_name == "":
                continue
            if pad.net_name not in net_pins:
                net_pins[pad.net_name] = []
            net_pins[pad.net_name].append((fp.reference, pad.number))

    nets = []
    for name, connections in net_pins.items():
        if len(connections) < 2:
            continue
        nets.append(Net(
            name=name,
            connections=tuple(connections),
            net_class=classify_net(name),
        ))
    return nets


def _nets_from_schematic(sch_path: Path) -> List[Net]:
    """Prova a ricavare le net dalla netlist esportata da kicad-cli."""
    import xml.etree.ElementTree as ET

    netlist_path = sch_path.parent / f"{sch_path.stem}_netlist.xml"

    # Esporta la netlist
    result = cli.export_netlist(sch_path, netlist_path)
    if not result.get("success") or not netlist_path.is_file():
        return []

    try:
        tree = ET.parse(str(netlist_path))
        root = tree.getroot()
    except ET.ParseError:
        return []

    nets = []
    for net_elem in root.iter("net"):
        name = net_elem.get("name", "")
        if not name:
            continue
        connections = []
        for node in net_elem.findall("node"):
            ref = node.get("ref", "")
            pin = node.get("pin", "")
            if ref and pin:
                connections.append((ref, pin))
        if len(connections) >= 2:
            nets.append(Net(
                name=name,
                connections=tuple(connections),
                net_class=classify_net(name),
            ))
    return nets


# =============================================================================
# Scrittura — dal modello Board ai file KiCad
# =============================================================================

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
            "detail": {
                "applied": self.applied[:50],
                "skipped": self.skipped[:50],
                "failed": self.failed[:50],
            },
        }


def apply_placement(board: Board, pcb_path: Path,
                    origin: Tuple[float, float] = (0.0, 0.0),
                    dry_run: bool = True,
                    only: Optional[List[str]] = None) -> ApplyOutcome:
    """Riscrive nel file .kicad_pcb le posizioni calcolate.

    `dry_run=True` calcola gli spostamenti e li restituisce senza toccare il
    file — e' il modo sicuro per verificare che i reference tornino e i numeri
    abbiano senso prima di riscrivere.

    A differenza del bridge EasyEDA, qui non c'e' bisogno di un `preview` lato
    server: il file e' sul disco, si legge e si confronta. La sicurezza sta nel
    dry_run e nel gate di governance dell'MCP Server.
    """
    pcb_path = Path(pcb_path)
    outcome = ApplyOutcome(dry_run=dry_run)
    wanted = set(only) if only else None
    ox, oy = origin

    for designator, component in sorted(board.components.items()):
        if wanted is not None and designator not in wanted:
            continue
        if component.locked:
            outcome.skipped.append({"designator": designator, "reason": "bloccato"})
            continue

        abs_x = component.x + ox
        abs_y = component.y + oy

        move_info = {
            "designator": designator,
            "x_mm": round(abs_x, 4),
            "y_mm": round(abs_y, 4),
            "rotation": float(component.rotation),
        }

        if dry_run:
            outcome.applied.append(move_info)
        else:
            try:
                ok = parser.update_footprint_position(
                    pcb_path, designator, abs_x, abs_y,
                    rotation=float(component.rotation),
                )
                if ok:
                    outcome.applied.append(move_info)
                else:
                    outcome.failed.append({
                        "designator": designator,
                        "error": f"Footprint '{designator}' non trovato nel file.",
                    })
            except Exception as exc:
                outcome.failed.append({
                    "designator": designator,
                    "error": str(exc),
                })

    return outcome


# =============================================================================
# Utilità
# =============================================================================

def classify_net(name: str) -> str:
    """Indovina la classe di una net dal nome."""
    upper = (name or "").upper().strip()
    if any(upper == h or upper.startswith(h + "_") for h in _GROUND_HINTS):
        return CLASS_GROUND
    if any(upper == h or upper.startswith(h + "_") for h in _POWER_HINTS):
        return CLASS_POWER
    return CLASS_SIGNAL


def _snap_rotation(value: float) -> int:
    """Arrotonda alla rotazione ortogonale piu' vicina."""
    try:
        angle = int(round(float(value or 0.0) / 90.0)) * 90
    except (TypeError, ValueError):
        return 0
    return angle % 360


def find_project_files(project_path: Path) -> Dict[str, Optional[Path]]:
    """Dato un path (file .kicad_pro, .kicad_pcb, .kicad_sch o directory),
    trova tutti i file del progetto KiCad.

    Restituisce un dict con chiavi 'pcb', 'sch', 'pro' e i path trovati.
    """
    project_path = Path(project_path)

    if project_path.is_file():
        base_dir = project_path.parent
        stem = project_path.stem
    elif project_path.is_dir():
        base_dir = project_path
        # Cerca il primo .kicad_pro
        pros = list(base_dir.glob("*.kicad_pro"))
        stem = pros[0].stem if pros else None
    else:
        raise BridgeError(f"Percorso non valido: {project_path}")

    result: Dict[str, Optional[Path]] = {"pcb": None, "sch": None, "pro": None}

    if stem:
        for ext, key in [(".kicad_pcb", "pcb"), (".kicad_sch", "sch"),
                         (".kicad_pro", "pro")]:
            candidate = base_dir / f"{stem}{ext}"
            if candidate.is_file():
                result[key] = candidate

    # Se non trovati con lo stem, cerca qualsiasi file con l'estensione
    for ext, key in [(".kicad_pcb", "pcb"), (".kicad_sch", "sch"),
                     (".kicad_pro", "pro")]:
        if result[key] is None:
            candidates = list(base_dir.glob(f"*{ext}"))
            if candidates:
                result[key] = candidates[0]

    return result
