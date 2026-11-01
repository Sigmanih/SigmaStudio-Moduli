# ==============================================================================
# sigma_eda_lab/evaluate.py — Giudicare una scheda
# ==============================================================================
"""Un voto motivato su un piazzamento.

Il costo che guida la ricottura e' un numero solo, buono per confrontare due
disposizioni e inutile per capire *cosa* non va. Qui lo stesso piazzamento viene
guardato per controlli separati, ciascuno con la sua soglia e il suo elenco di
colpevoli, perche' «82 su 100» non dice a nessuno quale condensatore spostare.

Ogni controllo restituisce `ok`, `warn` o `fail`. La distinzione e' netta e non
e' una gradazione di gravita': `fail` e' una scheda che non funzionera' o non si
potra' montare, `warn` e' una scheda che funzionera' peggio di quanto potrebbe.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .netlist import Board, CLASS_CRITICAL, CLASS_GROUND, CLASS_POWER

OK = "ok"
WARN = "warn"
FAIL = "fail"

# Distanza oltre la quale un condensatore di disaccoppiamento non sta piu'
# disaccoppiando granche': l'induttanza del percorso cresce con la lunghezza, e
# a qualche millimetro dal pin il condensatore vede un'impedenza che annulla il
# motivo per cui e' li'.
DECOUPLING_GOOD_MM = 2.0
DECOUPLING_WARN_MM = 6.0

# Spazio minimo fra gli ingombri di due pezzi: sotto, il montatore non ci arriva
# e la pasta salda ponticella.
COURTYARD_MIN_MM = 0.25


@dataclass
class Check:
    """Un singolo controllo, con le prove di cio' che afferma."""

    name: str
    status: str
    detail: str
    offenders: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "offenders": self.offenders[:20]}


@dataclass
class Report:
    """L'esito completo."""

    checks: List[Check]
    metrics: Dict[str, Any]

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def verdict(self) -> str:
        if self.failures:
            return FAIL
        if self.warnings:
            return WARN
        return OK

    @property
    def score(self) -> int:
        """Cento meno quello che non va.

        Un `fail` pesa venticinque e un `warn` otto: quattro difetti veri
        portano una scheda a zero, che e' il messaggio giusto.
        """
        return max(0, 100 - 25 * len(self.failures) - 8 * len(self.warnings))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "checks": [c.to_dict() for c in self.checks],
            "metrics": self.metrics,
        }


def evaluate(board: Board, decoupling_prefix: str = "C") -> Report:
    """Passa la scheda ai controlli e raccoglie il verdetto."""
    checks = [
        _check_overlap(board),
        _check_outline(board),
        _check_courtyard(board),
        _check_decoupling(board, decoupling_prefix),
        _check_critical_nets(board),
        _check_unconnected(board),
    ]

    area = board.width * board.height
    used = sum((c.extent[0] * c.extent[1]) for c in board.components.values())
    metrics = {
        "components": len(board.components),
        "nets": len(board.nets),
        "board_mm2": round(area, 2),
        "occupancy_pct": round(100.0 * used / area, 2) if area else 0.0,
        "hpwl_mm": round(board.total_hpwl(weighted=False), 3),
        "hpwl_weighted": round(board.total_hpwl(weighted=True), 3),
        "longest_net_mm": round(max(
            (board.net_hpwl(n) for n in board.nets), default=0.0), 3),
    }
    return Report(checks=checks, metrics=metrics)


# --- i controlli ---------------------------------------------------------------

def _check_overlap(board: Board) -> Check:
    overlapping = []
    items = list(board.components.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.side != b.side:
                continue
            area = _overlap(a.bbox, b.bbox)
            if area > 1e-6:
                overlapping.append({"a": a.designator, "b": b.designator,
                                    "area_mm2": round(area, 4)})
    if overlapping:
        return Check("sovrapposizioni", FAIL,
                     f"{len(overlapping)} coppie di pezzi si sovrappongono.",
                     sorted(overlapping, key=lambda o: -o["area_mm2"]))
    return Check("sovrapposizioni", OK, "Nessun pezzo si sovrappone a un altro.")


def _check_outline(board: Board) -> Check:
    margin = board.edge_clearance
    usable = (margin, margin, board.width - margin, board.height - margin)
    outside = []
    for component in board.components.values():
        x0, y0, x1, y1 = component.bbox
        area = (x1 - x0) * (y1 - y0)
        out = area - _overlap(component.bbox, usable)
        if out > 1e-6:
            outside.append({"designator": component.designator,
                            "outside_mm2": round(out, 4)})
    if outside:
        return Check("contorno", FAIL,
                     f"{len(outside)} pezzi sbordano dal contorno o dal margine "
                     f"di fresa ({margin} mm).",
                     sorted(outside, key=lambda o: -o["outside_mm2"]))
    return Check("contorno", OK, "Tutti i pezzi stanno dentro il contorno utile.")


def _check_courtyard(board: Board) -> Check:
    tight = []
    items = list(board.components.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.side != b.side:
                continue
            gap = _gap(a.bbox, b.bbox)
            if 0.0 <= gap < COURTYARD_MIN_MM:
                tight.append({"a": a.designator, "b": b.designator,
                              "gap_mm": round(gap, 4)})
    if tight:
        return Check("distanza fra i pezzi", WARN,
                     f"{len(tight)} coppie stanno sotto {COURTYARD_MIN_MM} mm: "
                     "montaggio e rilavorazione diventano difficili.",
                     sorted(tight, key=lambda o: o["gap_mm"]))
    return Check("distanza fra i pezzi", OK,
                 f"Nessuna coppia sotto {COURTYARD_MIN_MM} mm.")


def _check_decoupling(board: Board, prefix: str) -> Check:
    """Quanto distano i condensatori di disaccoppiamento dal loro integrato.

    Un condensatore si considera di disaccoppiamento se tocca una net di
    alimentazione e una di massa: e' cio' che lo distingue da un condensatore
    di filtro o di accoppiamento senza dover indovinare dal valore.
    """
    power = {n.name for n in board.nets if n.net_class == CLASS_POWER}
    ground = {n.name for n in board.nets if n.net_class == CLASS_GROUND}
    if not power or not ground:
        return Check("disaccoppiamento", OK,
                     "Nessuna coppia alimentazione/massa dichiarata: controllo non applicabile.")

    far = []
    checked = 0
    for designator, partner, rail in board.decoupling_pairs(prefix):
        distance = board.decoupling_distance(designator, partner, rail)
        if distance == float("inf"):
            continue
        checked += 1
        if distance > DECOUPLING_WARN_MM:
            far.append({"capacitor": designator, "ic": partner,
                        "distance_mm": round(distance, 3), "level": "fail"})
        elif distance > DECOUPLING_GOOD_MM:
            far.append({"capacitor": designator, "ic": partner,
                        "distance_mm": round(distance, 3), "level": "warn"})

    if not checked:
        return Check("disaccoppiamento", OK,
                     "Nessun condensatore di disaccoppiamento riconosciuto.")
    if any(f["level"] == "fail" for f in far):
        return Check("disaccoppiamento", FAIL,
                     f"{len(far)} condensatori con anello oltre {DECOUPLING_GOOD_MM} mm "
                     f"dal loro integrato, alcuni oltre {DECOUPLING_WARN_MM} mm.",
                     sorted(far, key=lambda o: -o["distance_mm"]))
    if far:
        return Check("disaccoppiamento", WARN,
                     f"{len(far)} condensatori fra {DECOUPLING_GOOD_MM} e "
                     f"{DECOUPLING_WARN_MM} mm dal loro integrato.",
                     sorted(far, key=lambda o: -o["distance_mm"]))
    return Check("disaccoppiamento", OK,
                 f"Tutti i {checked} condensatori con anello entro "
                 f"{DECOUPLING_GOOD_MM} mm.")


def _check_critical_nets(board: Board) -> Check:
    """Le net critiche vanno corte. Quanto corte dipende dalla scheda, quindi
    il metro e' relativo: una critica che supera la mediana delle altre e' un
    segnale, indipendentemente dalle dimensioni del prodotto."""
    critical = [n for n in board.nets if n.net_class == CLASS_CRITICAL]
    if not critical:
        return Check("net critiche", OK, "Nessuna net dichiarata critica.")

    others = sorted(board.net_hpwl(n) for n in board.nets
                    if n.net_class != CLASS_CRITICAL)
    if not others:
        return Check("net critiche", OK, "Solo net critiche: niente con cui confrontare.")
    median = others[len(others) // 2]

    long_ones = []
    for net in critical:
        length = board.net_hpwl(net)
        if length > median and length > 0:
            long_ones.append({"net": net.name, "length_mm": round(length, 3),
                              "median_mm": round(median, 3)})
    if long_ones:
        return Check("net critiche", WARN,
                     f"{len(long_ones)} net critiche piu' lunghe della mediana "
                     "delle non critiche.",
                     sorted(long_ones, key=lambda o: -o["length_mm"]))
    return Check("net critiche", OK,
                 f"Tutte le {len(critical)} net critiche sotto la mediana.")


def _check_unconnected(board: Board) -> Check:
    """Pezzi che non compaiono in nessuna net.

    Quasi sempre e' un footprint importato senza netlist, non un pezzo che
    davvero non va collegato: i fori di fissaggio e i marchi sono l'eccezione,
    ed e' per questo che il controllo avverte invece di bocciare.
    """
    connected = {d for net in board.nets for d, _ in net.connections}
    orphans = [{"designator": d} for d in sorted(board.components)
               if d not in connected]
    if orphans:
        return Check("pezzi scollegati", WARN,
                     f"{len(orphans)} pezzi non compaiono in nessuna net.",
                     orphans)
    return Check("pezzi scollegati", OK, "Ogni pezzo appartiene ad almeno una net.")


# --- geometria di servizio -----------------------------------------------------

def _overlap(a, b) -> float:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0.0


def _gap(a, b) -> float:
    """Distanza fra i bordi di due rettangoli; negativa se si sovrappongono."""
    dx = max(a[0] - b[2], b[0] - a[2])
    dy = max(a[1] - b[3], b[1] - a[3])
    if dx >= 0 and dy >= 0:
        return math.hypot(dx, dy)
    if dx >= 0:
        return dx
    if dy >= 0:
        return dy
    return -1.0
