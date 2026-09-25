# ==============================================================================
# sigma_kicad_lab/handlers.py — FastAPI Handlers & HTTP Routes for KiCad Lab
# ==============================================================================
"""Espone le route HTTP REST e SSE per la Tab Hardware Studio & KiCad Lab.

Supporta:
- Ispezione stato KiCad (CLI version, percorsi)
- Esplorazione e creazione progetti (.kicad_pro, .kicad_sch, .kicad_pcb)
- Lettura e visualizzazione vettoriale della scheda (outline, layer, tracce, vias, footprint, pad, net)
- Piazzamento automatico a ricottura simulata
- Esecuzione headless DRC ed ERC con kicad-cli
- Generazione render 3D fotorealistico ed esportazione Gerber / BOM
- Chat streaming SSE con l'orchestratore del team di agenti hardware (ad anello chiuso)
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from core import paths
from core.logger import get_logger
from . import bridge, kicad_cli as cli, kicad_parser as parser
from .orchestrator import RUOLO_SCHEDA, HardwareTeamOrchestrator

log = get_logger("kicad_handlers")


#: Cartelle da non attraversare cercando progetti. `.sigma_backups` contiene
#: le copie che `pcb_writer` fa prima di ogni scrittura: sono `.kicad_pcb`
#: validi a tutti gli effetti, e senza questo filtro ogni modifica farebbe
#: comparire nella tab dieci progetti fantasma col nome della scheda vera.
_CARTELLE_DA_SALTARE = {
    ".sigma_backups", ".git", "node_modules", "__pycache__",
    "-backups", "fp-info-cache", "gerbers",
}

#: Quanto in profondita' cercare sotto `projects/`. Sotto quella cartella ci
#: sono decine di migliaia di file che non c'entrano niente con KiCad: una
#: ricerca senza limite li attraverserebbe tutti a ogni apertura della tab.
_PROFONDITA_MASSIMA = 4


def _get_projects_dir() -> Path:
    """Dove si creano i progetti hardware nuovi."""
    d = paths.project_root() / "projects" / "hardware"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _radici_progetti() -> List[Path]:
    """Dove cercare i progetti esistenti.

    Non solo `projects/hardware`: una scheda creata altrove sotto `projects/`
    e' comunque una scheda, e non comparire nella tab la rende invisibile
    anche quando gli agenti ci stanno lavorando sopra.
    """
    radice = paths.project_root() / "projects"
    return [radice] if radice.is_dir() else []


def _trova_schede(radice: Path) -> List[Path]:
    """I file .kicad_pcb sotto `radice`, saltando backup e rumore."""
    trovati: List[Path] = []
    base = len(radice.parts)
    for cartella, sottocartelle, file in os.walk(radice):
        corrente = Path(cartella)
        if len(corrente.parts) - base >= _PROFONDITA_MASSIMA:
            sottocartelle[:] = []
            continue
        # Si potano in loco: os.walk non scende in cio' che si toglie da qui.
        sottocartelle[:] = [s for s in sottocartelle
                            if s not in _CARTELLE_DA_SALTARE
                            and not s.startswith(".")]
        trovati.extend(corrente / f for f in file if f.endswith(".kicad_pcb"))
    return trovati


# -----------------------------------------------------------------------------
# Handlers
# -----------------------------------------------------------------------------

async def handle_kicad_status(request: Request):
    """GET /api/kicad/status — Stato dell'integrazione e di kicad-cli."""
    st = bridge.status()
    # Un ruolo solo: e' l'agente KiCad dell'harness. La scheda lo mostra con il
    # suo nome vero invece di cinque nomi che descrivevano fasi di un copione.
    return JSONResponse(status_code=200, content={
        "success": True,
        "status": st,
        "roles": [RUOLO_SCHEDA],
        "default_projects_dir": str(_get_projects_dir()),
    })


async def handle_kicad_projects(request: Request):
    """GET /api/kicad/projects — Elenco progetti KiCad nel workspace."""
    projects: List[Dict[str, Any]] = []
    visti = set()

    schede = []
    for radice in _radici_progetti():
        schede.extend(_trova_schede(radice))

    for p in schede:
        if str(p) in visti:
            continue
        visti.add(str(p))
        if True:
            pro_candidate = p.with_suffix(".kicad_pro")
            sch_candidate = p.with_suffix(".kicad_sch")
            projects.append({
                "name": p.stem,
                "dir": str(p.parent),
                "pcb_path": str(p),
                "sch_path": str(sch_candidate) if sch_candidate.is_file() else "",
                "pro_path": str(pro_candidate) if pro_candidate.is_file() else "",
                "last_modified": p.stat().st_mtime,
            })

    # Ordina dal più recente
    projects.sort(key=lambda x: x.get("last_modified", 0), reverse=True)
    return JSONResponse(status_code=200, content={"success": True, "projects": projects})


async def handle_kicad_create_project(request: Request):
    """POST /api/kicad/projects/create — Crea un nuovo progetto KiCad da template."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    name = str(body.get("name") or "new_pcb").strip()
    width = float(body.get("width_mm") or 80.0)
    height = float(body.get("height_mm") or 60.0)
    target_dir = body.get("dir")
    if target_dir:
        p_dir = Path(target_dir)
    else:
        p_dir = _get_projects_dir() / name

    created = parser.create_empty_project(p_dir, name, width_mm=width, height_mm=height)
    return JSONResponse(status_code=200, content={"success": True, "project": created})


async def handle_kicad_board(request: Request):
    """GET /api/kicad/board?pcb_path=... — Lettura completa dati scheda per canvas."""
    pcb_path_str = request.query_params.get("pcb_path")
    if not pcb_path_str:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'pcb_path' mancante."})

    pcb_p = Path(pcb_path_str)
    if not pcb_p.is_file():
        return JSONResponse(status_code=404, content={"success": False, "error": f"File '{pcb_p}' non trovato."})

    try:
        board_info = parser.read_pcb(pcb_p)
        data = parser.board_to_dict(board_info)
        return JSONResponse(status_code=200, content={"success": True, "board": data, "path": str(pcb_p)})
    except Exception as exc:
        log.exception("[handle_kicad_board] Errore lettura PCB: %s", exc)
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_schematic(request: Request):
    """GET /api/kicad/schematic?sch_path=... — Lettura simboli e connessioni schematico."""
    sch_path_str = request.query_params.get("sch_path")
    if not sch_path_str:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'sch_path' mancante."})

    sch_p = Path(sch_path_str)
    if not sch_p.is_file():
        return JSONResponse(status_code=404, content={"success": False, "error": f"File '{sch_p}' non trovato."})

    try:
        sch_info = parser.read_schematic(sch_p)
        return JSONResponse(status_code=200, content={
            "success": True,
            "components": [
                {
                    "reference": c.reference,
                    "value": c.value,
                    "lib_id": c.lib_id,
                    "x": c.x,
                    "y": c.y,
                }
                for c in sch_info.components
            ],
            "connections_count": len(sch_info.connections),
            "nets": list(sch_info.connections.keys()),
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_placement_optimize(request: Request):
    """POST /api/kicad/placement/optimize — Esegue simulated annealing su .kicad_pcb."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    pcb_path = body.get("pcb_path")
    sch_path = body.get("sch_path")
    iterations = int(body.get("iterations") or 3000)
    lock = body.get("lock") or []

    if not pcb_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "pcb_path mancante."})

    try:
        board = bridge.read_board(Path(pcb_path), sch_path=Path(sch_path) if sch_path else None)
        from core.modules.sigma_eda_lab import placement
        res = placement.optimize_placement(board, iterations=iterations, lock_components=set(lock))
        return JSONResponse(status_code=200, content={
            "success": True,
            "moves": res.moves,
            "initial_cost": round(res.initial_cost, 2),
            "final_cost": round(res.final_cost, 2),
            "improvement_pct": round(res.improvement_pct, 2),
            "iterations": res.iterations,
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_placement_apply(request: Request):
    """POST /api/kicad/placement/apply — Applica le nuove posizioni nel file .kicad_pcb."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    pcb_path = body.get("pcb_path")
    moves_list = body.get("moves") or []

    if not pcb_path or not moves_list:
        return JSONResponse(status_code=400, content={"success": False, "error": "pcb_path o moves mancanti."})

    moves_dict = {
        m["designator"]: (float(m["x_mm"]), float(m["y_mm"]), float(m.get("rotation", 0.0)))
        for m in moves_list if "designator" in m and "x_mm" in m and "y_mm" in m
    }

    try:
        res = parser.update_multiple_positions(Path(pcb_path), moves_dict)
        applied = sum(1 for v in res.values() if v)
        return JSONResponse(status_code=200, content={"success": True, "applied": applied, "total": len(moves_dict)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_drc(request: Request):
    """POST /api/kicad/drc — Esegue DRC con kicad-cli."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    pcb_path = body.get("pcb_path")
    if not pcb_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "pcb_path mancante."})

    try:
        report = cli.run_drc(Path(pcb_path))
        return JSONResponse(status_code=200, content={"success": True, "drc": report})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_erc(request: Request):
    """POST /api/kicad/erc — Esegue ERC con kicad-cli."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    sch_path = body.get("sch_path")
    if not sch_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "sch_path mancante."})

    try:
        report = cli.run_erc(Path(sch_path))
        return JSONResponse(status_code=200, content={"success": True, "erc": report})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_render(request: Request):
    """POST /api/kicad/render — Genera il render 3D della scheda in PNG."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    pcb_path = body.get("pcb_path")
    side = str(body.get("side") or "top")
    width = int(body.get("width") or 1280)
    height = int(body.get("height") or 720)

    if not pcb_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "pcb_path mancante."})

    try:
        rep = cli.render_3d(Path(pcb_path), width=width, height=height, side=side)
        out_p = Path(rep.get("output_path", ""))
        img_b64 = ""
        if out_p.is_file():
            img_b64 = base64.b64encode(out_p.read_bytes()).decode("ascii")
        return JSONResponse(status_code=200, content={
            "success": rep.get("success", False),
            "output_path": str(out_p),
            "data_url": f"data:image/png;base64,{img_b64}" if img_b64 else "",
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_export_gerbers(request: Request):
    """POST /api/kicad/export/gerbers — Esporta i file Gerber e Drill per JLCPCB."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    pcb_path = body.get("pcb_path")
    if not pcb_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "pcb_path mancante."})

    try:
        g_rep = cli.export_gerbers(Path(pcb_path))
        d_rep = cli.export_drill(Path(pcb_path))
        return JSONResponse(status_code=200, content={
            "success": g_rep.get("success", False),
            "gerbers": g_rep,
            "drill": d_rep,
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_export_bom(request: Request):
    """POST /api/kicad/export/bom — Esporta la distinta componenti BOM."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    sch_path = body.get("sch_path")
    if not sch_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "sch_path mancante."})

    try:
        b_rep = cli.export_bom(Path(sch_path))
        content = ""
        out_p = Path(b_rep.get("output_path", ""))
        if out_p.is_file():
            content = out_p.read_text(encoding="utf-8", errors="replace")
        return JSONResponse(status_code=200, content={
            "success": b_rep.get("success", False),
            "bom_path": str(out_p),
            "csv_preview": content[:2000],
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


async def handle_kicad_agent_chat(request: Request):
    """POST /api/kicad/agent/chat — SSE Streaming per il team di agenti hardware."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    task = str(body.get("task") or body.get("prompt") or "").strip()
    if not task:
        return JSONResponse(status_code=400, content={"success": False, "error": "Task non specificato."})

    project_dir = body.get("project_dir") or str(_get_projects_dir() / "active_board")
    pcb_path = body.get("pcb_path")
    sch_path = body.get("sch_path")

    orch = HardwareTeamOrchestrator(
        task=task,
        project_dir=project_dir,
        pcb_path=pcb_path,
        sch_path=sch_path,
    )

    return StreamingResponse(
        orch.run_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# -----------------------------------------------------------------------------
# Registro Route
# -----------------------------------------------------------------------------


# =============================================================================
# Modifica manuale — le stesse funzioni che usano gli agenti
# =============================================================================
#
# Queste route non reimplementano niente: chiamano `tools.py` di questo modulo,
# cioe' esattamente il codice che esegue la squadra di agenti. E' una scelta,
# non una scorciatoia — due implementazioni della stessa operazione divergono
# sempre, e divergono sulle validazioni prima che sul risultato: la via
# manuale finirebbe per accettare un via col foro piu' largo del diametro che
# quella automatica rifiuta, o per saltare la copia di sicurezza.
#
# Il corpo della richiesta e' il dizionario di argomenti del tool. La chiave
# `project` e' l'unica aggiunta: apre il progetto prima di eseguire, cosi' la
# tab non deve tenere uno stato di sessione col server.


def _route_per_tool(nome_tool: str):
    """Costruisce la route HTTP che espone un tool dell'harness."""

    async def handler(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={
                "success": False, "error": "Il corpo deve essere un oggetto JSON."})

        from . import tools

        argomenti = dict(body)
        progetto = argomenti.pop("project", None)
        if progetto:
            apertura = tools.kicad_open(str(progetto))
            if not apertura.get("success"):
                return JSONResponse(status_code=400, content=apertura)

        esito = tools.esegui(nome_tool, argomenti)
        if esito is None:
            return JSONResponse(status_code=404, content={
                "success": False, "error": f"Tool '{nome_tool}' inesistente."})
        return JSONResponse(status_code=200 if esito.get("success") else 400,
                            content=esito)

    handler.__name__ = f"handle_{nome_tool}"
    handler.__doc__ = f"POST /api/kicad/... — espone {nome_tool} dell'harness."
    return handler


#: (percorso, tool). Lettura e scrittura, la stessa lista che ha un agente.
ROUTE_MANUALI = (
    ("/api/kicad/open", "kicad_open"),
    ("/api/kicad/parts", "kicad_list_parts"),
    ("/api/kicad/pads", "kicad_pads"),
    ("/api/kicad/nets", "kicad_nets"),
    ("/api/kicad/trace_width", "kicad_trace_width"),
    ("/api/kicad/evaluate", "kicad_board_evaluate"),
    ("/api/kicad/track/add", "kicad_add_track"),
    ("/api/kicad/route/add", "kicad_add_route"),
    ("/api/kicad/via/add", "kicad_add_via"),
    ("/api/kicad/footprint/add", "kicad_add_footprint"),
    ("/api/kicad/footprint/remove", "kicad_remove_footprint"),
    # pcbnew: un footprint vero, caricato dalla libreria KiCad installata, con i
    # suoi pad e il suo disegno. E' questo che l'utente intende per «aggiungi un
    # componente»; `kicad_add_footprint` costruisce invece un pezzo sintetico,
    # buono per fori di fissaggio e fiducial.
    ("/api/kicad/part/add", "kicad_add_part"),
    ("/api/kicad/libraries", "kicad_libraries"),
    ("/api/kicad/footprint/search", "kicad_search_footprint"),
    # correzione: le stesse operazioni che fa l'utente trascinando sulla canvas
    ("/api/kicad/footprint/move", "kicad_move_footprint"),
    ("/api/kicad/footprint/rename", "kicad_rename_footprint"),
    ("/api/kicad/pad/net", "kicad_set_pad_net"),
    ("/api/kicad/track/delete", "kicad_delete_track"),
    ("/api/kicad/via/delete", "kicad_delete_via"),
    ("/api/kicad/outline/set", "kicad_set_board_outline"),
    ("/api/kicad/undo", "kicad_undo"),
    # task #6: undo/redo, zone, netclass, rules, costruttori, bom, sync, 3d, export
    ("/api/kicad/redo", "kicad_redo"),
    ("/api/kicad/zone_add", "kicad_zone_add"),
    ("/api/kicad/netclass_set", "kicad_netclass_set"),
    ("/api/kicad/rules_set", "kicad_rules_set"),
    ("/api/kicad/constructor_hole", "kicad_constructor_hole"),
    ("/api/kicad/constructor_fiducial", "kicad_constructor_fiducial"),
    ("/api/kicad/constructor_testpoint", "kicad_constructor_testpoint"),
    ("/api/kicad/constructor_silkscreen", "kicad_constructor_silkscreen"),
    ("/api/kicad/constructor_outline", "kicad_constructor_outline"),
    ("/api/kicad/bom_export", "kicad_bom_export"),
    ("/api/kicad/sync_netlist", "kicad_sync_netlist"),
    ("/api/kicad/render_3d", "kicad_render_3d"),
    ("/api/kicad/export_drill", "kicad_export_drill"),
    ("/api/kicad/export_pickplace", "kicad_export_pickplace"),
)


ROUTES = (
    ("/api/kicad/status", handle_kicad_status, ["GET"]),
    ("/api/kicad/projects", handle_kicad_projects, ["GET"]),
    ("/api/kicad/projects/create", handle_kicad_create_project, ["POST"]),
    ("/api/kicad/board", handle_kicad_board, ["GET"]),
    ("/api/kicad/schematic", handle_kicad_schematic, ["GET"]),
    ("/api/kicad/placement/optimize", handle_kicad_placement_optimize, ["POST"]),
    ("/api/kicad/placement/apply", handle_kicad_placement_apply, ["POST"]),
    ("/api/kicad/drc", handle_kicad_drc, ["POST"]),
    ("/api/kicad/erc", handle_kicad_erc, ["POST"]),
    ("/api/kicad/render", handle_kicad_render, ["POST"]),
    ("/api/kicad/export/gerbers", handle_kicad_export_gerbers, ["POST"]),
    ("/api/kicad/export/bom", handle_kicad_export_bom, ["POST"]),
    ("/api/kicad/agent/chat", handle_kicad_agent_chat, ["POST"]),
) + tuple(
    (percorso, _route_per_tool(tool), ["POST"])
    for percorso, tool in ROUTE_MANUALI
)


def register_routes(app=None) -> None:
    """Registra tutte le route HTTP di KiCad Lab su FastAPI."""
    if app is None:
        return
    try:
        for percorso, handler, metodi in ROUTES:
            app.add_api_route(percorso, handler, methods=list(metodi))
        log.info("[sigma_kicad_lab] %d route registrate con successo su FastAPI.", len(ROUTES))
    except Exception as exc:
        log.warning("[sigma_kicad_lab] Errore durante la registrazione delle route: %s", exc)


def register_mcp(mcp_hub) -> None:
    """Registra il server MCP di KiCad Lab nell'hub del kernel."""
    if mcp_hub is None:
        return
    try:
        from .mcp_server import KiCadLabMCPServer
        mcp_hub.register_server(KiCadLabMCPServer)
        log.info("[sigma_kicad_lab] KiCad Lab MCP Server registrato.")
    except Exception as exc:
        log.warning("[sigma_kicad_lab] KiCad Lab MCP Server non registrato: %s", exc)


def register_harness_tools() -> None:
    """Deposita nell'harness i tool dell'agente, con il ruolo che li concede.

    E' l'hook con cui questo modulo smette di essere nominato dal kernel: gli
    schemi, la classe di sicurezza di ogni tool e il ruolo `kicad_engineer`
    arrivano da qui, e il kernel li riceve senza sapere di chi siano. Se il
    modulo non c'e', i tool semplicemente non esistono — che e' la verita'.
    """
    try:
        from . import tools
        nomi = tools.registra()
        log.info("[sigma_kicad_lab] %d tool dell'harness registrati.", len(nomi))
    except Exception as exc:
        log.warning("[sigma_kicad_lab] Tool dell'harness non registrati: %s", exc)

