# ==============================================================================
# sigma_eda_lab/routing.py — Ispezione connessioni, routing e DRC PCB
# ==============================================================================
"""Strumenti di routing, analisi ratsnest e verifica DRC nativa su EasyEDA Pro.

EasyEDA Pro posiziona i componenti ma lascia il tracciamento delle piste
all'operatore o agli script. Questo modulo fornisce agli agenti:
1. L'elenco esatto dei pad e delle net ancora non instradate (ratsnest/unrouted).
2. Il calcolo di spezzate a 45 gradi conformi a IPC-2221.
3. Il tracciamento di piste (track) e fori di passaggio (via).
4. La verifica DRC nativa aggregata (errori di disconnessione, cortocircuito, clearance).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger
from . import bridge

log = get_logger(__name__)


def get_pcb_pads(project_id: str, hub=None) -> List[Dict[str, Any]]:
    """Legge tutti i pad presenti sul layout PCB con coordinate native in mil."""
    res = bridge.call("easyeda_api_call", {
        "path": "PCB_PrimitivePad.getAll",
        "args": [],
        "confirmWrite": True,
    }, hub)
    raw_pads = res.get("result") or []
    normalized = []
    for p in raw_pads:
        net = str(p.get("net") or p.get("Net") or "").strip()
        try:
            x = float(p.get("x") if p.get("x") is not None else p.get("X", 0.0))
            y = float(p.get("y") if p.get("y") is not None else p.get("Y", 0.0))
            layer = int(p.get("layer") if p.get("layer") is not None else p.get("Layer", 1))
        except (ValueError, TypeError):
            continue
        normalized.append({
            "primitive_id": p.get("primitiveId") or p.get("PrimitiveId") or "",
            "pad_number": str(p.get("padNumber") or p.get("PadNumber") or ""),
            "net": net,
            "x": x,
            "y": y,
            "layer": layer,
        })
    return normalized


def get_unrouted_summary(project_id: str, hub=None) -> Dict[str, Any]:
    """Analizza i pad per ciascuna net e calcola lo stato di instradamento."""
    pads = get_pcb_pads(project_id, hub)
    tracks_res = bridge.call("easyeda_pcb_tracks", {"projectId": project_id}, hub)
    tracks = tracks_res.get("tracks") or []

    # Net con tracce gia' tracciate
    routed_nets = {t.get("net") for t in tracks if t.get("net")}

    by_net: Dict[str, List[Dict[str, Any]]] = {}
    for p in pads:
        net = p["net"]
        if not net:
            continue
        by_net.setdefault(net, []).append(p)

    unrouted = []
    connected = []
    for net, net_pads in sorted(by_net.items()):
        if len(net_pads) >= 2:
            if net in routed_nets:
                connected.append({"net": net, "pads_count": len(net_pads)})
            else:
                unrouted.append({
                    "net": net,
                    "pads_count": len(net_pads),
                    "pads": [{"number": p["pad_number"], "x": round(p["x"], 2), "y": round(p["y"], 2)}
                             for p in net_pads[:12]],
                    "net_class": bridge.classify_net(net),
                })

    return {
        "project_id": project_id,
        "total_nets_with_pads": len(by_net),
        "unrouted_nets_count": len(unrouted),
        "routed_nets_count": len(connected),
        "unrouted_nets": unrouted,
    }


def make_45_deg_path(p1: Tuple[float, float], p2: Tuple[float, float]) -> List[Dict[str, float]]:
    """Genera una spezzata a 45 gradi tra due punti (x1, y1) e (x2, y2).

    Evita curve a 90 gradi per conformita' con gli standard ad alta frequenza/analogici.
    """
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1

    if abs(dx) < 1e-3 or abs(dy) < 1e-3:
        return [{"x": round(x1, 2), "y": round(y1, 2)},
                {"x": round(x2, 2), "y": round(y2, 2)}]

    # Sezione diagonale a 45 gradi poi ortogonale
    adx, ady = abs(dx), abs(dy)
    if adx > ady:
        mid_x = x1 + math.copysign(ady, dx)
        mid_y = y2
    else:
        mid_x = x2
        mid_y = y1 + math.copysign(adx, dy)

    return [
        {"x": round(x1, 2), "y": round(y1, 2)},
        {"x": round(mid_x, 2), "y": round(mid_y, 2)},
        {"x": round(x2, 2), "y": round(y2, 2)},
    ]


def route_pads_of_net(project_id: str, net_name: str, width_mil: float = 10.0,
                      layer: int = 1, hub=None) -> Dict[str, Any]:
    """Collega sequenzialmente i pad di una data net con spezzate a 45 gradi."""
    pads = [p for p in get_pcb_pads(project_id, hub) if p["net"] == net_name]
    if len(pads) < 2:
        return {"success": False, "net": net_name, "error": f"Meno di 2 pad per la net '{net_name}'."}

    # Ordina i pad per vicinanza (approccio greedy nearest neighbour)
    remaining = list(pads)
    ordered = [remaining.pop(0)]
    while remaining:
        curr = ordered[-1]
        best_idx = min(range(len(remaining)),
                       key=lambda i: (remaining[i]["x"] - curr["x"])**2 + (remaining[i]["y"] - curr["y"])**2)
        ordered.append(remaining.pop(best_idx))

    added_tracks = []
    for i in range(len(ordered) - 1):
        p1 = (ordered[i]["x"], ordered[i]["y"])
        p2 = (ordered[i + 1]["x"], ordered[i + 1]["y"])
        pts = make_45_deg_path(p1, p2)
        try:
            res = bridge.call("easyeda_pcb_add_track", {
                "projectId": project_id,
                "layer": layer,
                "width": float(width_mil),
                "netName": net_name,
                "points": pts,
                "confirmWrite": True,
            }, hub)
            if res.get("success"):
                added_tracks.extend(res.get("primitiveIds") or [res.get("primitiveId")])
        except Exception as exc:
            log.warning("[routing] Fallito collegamento net %s: %s", net_name, exc)

    return {
        "success": bool(added_tracks),
        "net": net_name,
        "tracks_added": len(added_tracks),
        "pads_connected": len(ordered),
    }


def run_drc_inspection(project_id: str, hub=None) -> Dict[str, Any]:
    """Esegue il DRC nativo e restituisce un resoconto strutturato."""
    res = bridge.call("easyeda_drc_run", {"projectId": project_id}, hub)
    errors = res.get("errors") or []
    
    by_category = {
        "disconnected": [],
        "clearance": [],
        "short_circuit": [],
        "other": [],
    }
    
    for err in errors:
        desc = (err.get("description") or "").lower()
        net = err.get("net") or ""
        item = {"net": net, "rule": err.get("rule"), "description": err.get("description")}
        if "disconnected" in desc:
            by_category["disconnected"].append(item)
        elif "clearance" in desc or "distance" in desc:
            by_category["clearance"].append(item)
        elif "short" in desc:
            by_category["short_circuit"].append(item)
        else:
            by_category["other"].append(item)

    total_errs = len(errors)
    return {
        "success": True,
        "total_errors": total_errs,
        "passed": total_errs == 0,
        "disconnected_count": len(by_category["disconnected"]),
        "clearance_count": len(by_category["clearance"]),
        "short_circuit_count": len(by_category["short_circuit"]),
        "by_net_disconnected": list(sorted({e["net"] for e in by_category["disconnected"] if e["net"]})),
        "details": by_category,
    }
