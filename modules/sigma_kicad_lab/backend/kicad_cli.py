# ==============================================================================
# sigma_kicad_lab/kicad_cli.py — Wrapper per kicad-cli
# ==============================================================================
"""Invocazione headless di KiCad per le operazioni che il parser non copre.

Il parser S-expression legge e scrive i file. Ma certe operazioni — DRC, ERC,
export Gerber, BOM — le fa KiCad meglio di chiunque: ha la conoscenza dei
vincoli elettrici, le tabelle di clearance, la conoscenza dei layer di
produzione. Per queste si delega a `kicad-cli`, che e' lo strumento ufficiale
per l'automazione headless.

**Dove trovare kicad-cli.** Su Windows l'installazione standard mette
l'eseguibile in `C:\\Program Files\\KiCad\\<versione>\\bin\\`. Il modulo cerca
prima nel PATH, poi nei percorsi standard. Se non lo trova restituisce un
errore chiaro invece di un FileNotFoundError.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)

# Timeout per le operazioni kicad-cli: DRC e export sono veloci, ma un progetto
# enorme potrebbe metterci qualche decina di secondi.
CLI_TIMEOUT_SECONDS = 120

# Percorsi standard di installazione su Windows
_WINDOWS_SEARCH_PATHS = [
    Path(r"C:\Program Files\KiCad"),
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "KiCad",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad",
]


class KiCadCLIError(RuntimeError):
    """kicad-cli non ha potuto completare l'operazione."""

    def __init__(self, message: str, returncode: int = -1, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(message)


def find_kicad_cli() -> Optional[Path]:
    """Cerca l'eseguibile kicad-cli sul sistema.

    Ordine di ricerca:
    1. Variabile d'ambiente KICAD_CLI_PATH (override esplicito)
    2. PATH di sistema (shutil.which)
    3. Percorsi standard di installazione Windows
    """
    # Override esplicito
    env_path = os.environ.get("KICAD_CLI_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p

    # PATH di sistema
    found = shutil.which("kicad-cli")
    if found:
        return Path(found)

    # Percorsi standard Windows
    if platform.system() == "Windows":
        for base in _WINDOWS_SEARCH_PATHS:
            if not base.is_dir():
                continue
            # Cerca nelle sottocartelle di versione: KiCad/8.0/bin, KiCad/9.0/bin, ...
            for child in sorted(base.iterdir(), reverse=True):
                candidate = child / "bin" / "kicad-cli.exe"
                if candidate.is_file():
                    return candidate
            # Potrebbe essere direttamente in bin/
            direct = base / "bin" / "kicad-cli.exe"
            if direct.is_file():
                return direct

    return None


def require_kicad_cli() -> Path:
    """Come find_kicad_cli, ma solleva se non lo trova."""
    cli = find_kicad_cli()
    if cli is None:
        raise KiCadCLIError(
            "kicad-cli non trovato. Installa KiCad 8+ e assicurati che "
            "l'eseguibile sia nel PATH o in un percorso standard, oppure "
            "imposta la variabile d'ambiente KICAD_CLI_PATH."
        )
    return cli


def kicad_version() -> Dict[str, Any]:
    """Restituisce la versione di KiCad installata."""
    cli = require_kicad_cli()
    try:
        result = subprocess.run(
            [str(cli), "version"],
            capture_output=True, text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        version_str = result.stdout.strip()
        return {"ok": True, "version": version_str, "path": str(cli)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout durante la lettura della versione."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# =============================================================================
# DRC — Design Rule Check
# =============================================================================

import re as _re


def parse_drc_violations(violations_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trasforma le violazioni grezze del report JSON DRC in oggetti con coordinate.

    Ogni violazione KiCad ha la forma:
      {"type": "clearance", "severity": "error",
       "description": "Clearance 0.15mm < 0.20mm ...",
       "net1": "GND", "net2": "VCC",
       "position": {"x": 12.5, "y": 34.0},
       "pad1": {...}, "pad2": {...}}

    Restituisce una lista di:
      {"type", "severity", "message", "net1", "net2", "x", "y"}
    dove x/y sono float in mm (o None se non disponibili).
    """
    parsed: List[Dict[str, Any]] = []
    for v in violations_raw:
        if not isinstance(v, dict):
            continue
        pos = v.get("position") or v.get("pos") or {}
        x = pos.get("x") if isinstance(pos, dict) else None
        y = pos.get("y") if isinstance(pos, dict) else None
        # Fallback: alcune versioni mettono x/y a livello superiore
        if x is None:
            x = v.get("x")
        if y is None:
            y = v.get("y")
        parsed.append({
            "type": v.get("type", "unknown"),
            "severity": v.get("severity", "error"),
            "message": v.get("description", v.get("message", "Violazione DRC")),
            "net1": v.get("net1", ""),
            "net2": v.get("net2", ""),
            "x": float(x) if x is not None else None,
            "y": float(y) if y is not None else None,
        })
    return parsed


def parse_erc_violations(violations_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trasforma le violazioni ERC in oggetti normalizzati (senza coordinate, l'ERC e' logico)."""
    parsed: List[Dict[str, Any]] = []
    for v in violations_raw:
        if not isinstance(v, dict):
            continue
        parsed.append({
            "type": v.get("type", "unknown"),
            "severity": v.get("severity", "error"),
            "message": v.get("description", v.get("message", "Violazione ERC")),
            "net1": v.get("net1", ""),
            "net2": v.get("net2", ""),
            "x": None,
            "y": None,
        })
    return parsed


def _checked_report(kind: str, source: Path, output_path=None) -> Dict[str, Any]:
    cli = require_kicad_cli()
    if not source.is_file():
        raise KiCadCLIError(f"File di progetto non trovato: {source}")
    operation = "drc" if kind == "pcb" else "erc"
    destination = Path(output_path) if output_path else source.with_name(f"{source.stem}_{operation}.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sigma-check-", dir=destination.parent) as directory:
        fresh = Path(directory) / "report.json"
        result = _run([str(cli), kind, operation, "--severity-all", "--format", "json",
                       "-o", str(fresh), str(source)], operation.upper())
        if not fresh.is_file():
            raise KiCadCLIError(f"{operation.upper()}: KiCad non ha prodotto il report.")
        try:
            raw = json.loads(fresh.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Struttura del report non valida.")
            if kind == "sch" and isinstance(raw.get("sheets"), list):
                sheets = raw["sheets"]
                if any(not isinstance(sheet, dict) or not isinstance(sheet.get("violations"), list) for sheet in sheets):
                    raise ValueError("Foglio ERC privo di violazioni leggibili.")
                violations = [violation for sheet in sheets for violation in sheet["violations"]]
            else:
                violations = raw.get("violations")
            if not isinstance(violations, list):
                raise ValueError("Elenco delle violazioni assente.")
            groups = [violations, raw.get("unconnected_items", []), raw.get("schematic_parity", [])]
            if any(not isinstance(group, list) or any(not isinstance(item, dict) for item in group) for group in groups):
                raise ValueError("Elenco delle violazioni non valido.")
        except (OSError, ValueError) as exc:
            raise KiCadCLIError(f"{operation.upper()}: report non interpretabile: {exc}") from exc
        errors = sum(item.get("severity", "error") == "error" for group in groups for item in group)
        fresh.replace(destination)
    return {"ok": True, "returncode": result.returncode, "success": errors == 0,
            "violations": groups[0], "unconnected": groups[1], "schematic_parity": groups[2],
            "total_errors": errors, "total_unconnected": len(groups[1]), "output_path": str(destination)}


def run_drc(pcb_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Il verdetto richiede un report nuovo, leggibile e prodotto da KiCad."""
    return _checked_report("pcb", Path(pcb_path), output_path)


# =============================================================================
# ERC — Electrical Rule Check
# =============================================================================

def run_erc(sch_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Il verdetto richiede un report nuovo, leggibile e prodotto da KiCad."""
    return _checked_report("sch", Path(sch_path), output_path)


# =============================================================================
# Export
# =============================================================================

def export_gerbers(pcb_path: Path, output_dir: Path = None) -> Dict[str, Any]:
    """Esporta i file Gerber per la produzione.

    kicad-cli pcb export gerbers -o <dir> <file>
    """
    cli = require_kicad_cli()
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise KiCadCLIError(f"File PCB non trovato: {pcb_path}")

    if output_dir is None:
        output_dir = pcb_path.parent / "gerbers"
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli), "pcb", "export", "gerbers",
        "-o", str(output_dir) + os.sep,
        str(pcb_path),
    ]

    result = _run(cmd, "Gerber export")

    # Elenca i file generati
    generated = sorted(str(f.name) for f in output_dir.iterdir() if f.is_file())

    return {
        "ok": True,
        "success": result.returncode == 0,
        "output_dir": str(output_dir),
        "files": generated,
        "total_files": len(generated),
    }


def export_drill(pcb_path: Path, output_dir: Path = None) -> Dict[str, Any]:
    """Esporta i file di foratura (drill).

    kicad-cli pcb export drill -o <dir> <file>
    """
    cli = require_kicad_cli()
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise KiCadCLIError(f"File PCB non trovato: {pcb_path}")

    if output_dir is None:
        output_dir = pcb_path.parent / "gerbers"
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli), "pcb", "export", "drill",
        "-o", str(output_dir) + os.sep,
        str(pcb_path),
    ]

    result = _run(cmd, "Drill export")
    generated = sorted(str(f.name) for f in output_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in (".drl", ".exc"))

    return {
        "ok": True,
        "success": result.returncode == 0,
        "output_dir": str(output_dir),
        "files": generated,
    }


def export_bom(sch_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Esporta la Bill of Materials (BOM) dallo schematico.

    kicad-cli sch export bom -o <file> <schematic>
    """
    cli = require_kicad_cli()
    sch_path = Path(sch_path)
    if not sch_path.is_file():
        raise KiCadCLIError(f"File schematico non trovato: {sch_path}")

    if output_path is None:
        output_path = sch_path.parent / f"{sch_path.stem}_bom.csv"

    cmd = [
        str(cli), "sch", "export", "bom",
        "-o", str(output_path),
        str(sch_path),
    ]

    result = _run(cmd, "BOM export")

    return {
        "ok": True,
        "success": result.returncode == 0,
        "output_path": str(output_path),
        "exists": output_path.is_file(),
    }


def export_positions(pcb_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Esporta il file pick-and-place (posizioni componenti per l'assemblaggio).

    kicad-cli pcb export pos -o <file> <pcb>
    """
    cli = require_kicad_cli()
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise KiCadCLIError(f"File PCB non trovato: {pcb_path}")

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}_pos.csv"

    cmd = [
        str(cli), "pcb", "export", "pos",
        "--format", "csv",
        "--units", "mm",
        "-o", str(output_path),
        str(pcb_path),
    ]

    result = _run(cmd, "Position export")

    return {
        "ok": True,
        "success": result.returncode == 0,
        "output_path": str(output_path),
        "exists": output_path.is_file(),
    }


def export_netlist(sch_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Esporta la netlist dallo schematico — la sorgente definitiva della connettivita'.

    kicad-cli sch export netlist -o <file> <schematic>
    """
    cli = require_kicad_cli()
    sch_path = Path(sch_path)
    if not sch_path.is_file():
        raise KiCadCLIError(f"File schematico non trovato: {sch_path}")

    if output_path is None:
        output_path = sch_path.parent / f"{sch_path.stem}_netlist.xml"

    cmd = [
        str(cli), "sch", "export", "netlist",
        "-o", str(output_path),
        str(sch_path),
    ]

    result = _run(cmd, "Netlist export")

    return {
        "ok": True,
        "success": result.returncode == 0,
        "output_path": str(output_path),
        "exists": output_path.is_file(),
    }


def render_3d(pcb_path: Path, output_path: Path = None, width: int = 1600,
              height: int = 900, side: str = "top", quality: str = "basic") -> Dict[str, Any]:
    """Genera un render 3D fotorealistico del PCB in formato PNG.

    kicad-cli pcb render -o <output> --width <w> --height <h> --side <side> --quality <q> <pcb>
    """
    cli = require_kicad_cli()
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise KiCadCLIError(f"File PCB non trovato: {pcb_path}")

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}_render_{side}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli), "pcb", "render",
        "-o", str(output_path),
        "--width", str(int(width)),
        "--height", str(int(height)),
        "--side", str(side),
        "--quality", str(quality),
        "--background", "transparent",
        str(pcb_path),
    ]

    result = _run(cmd, f"3D Render ({side})")

    return {
        "ok": True,
        "success": result.returncode == 0 and output_path.is_file(),
        "output_path": str(output_path),
        "exists": output_path.is_file(),
        "width": width,
        "height": height,
        "side": side,
    }


def export_svg(pcb_path: Path, output_dir: Path = None,
               layers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Esporta i layer del PCB in formato vettoriale SVG per rendering visuale immediato.

    kicad-cli pcb export svg -o <output_dir> --page-size-mode 2 --exclude-drawing-sheet -l <layers> <pcb>
    """
    cli = require_kicad_cli()
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise KiCadCLIError(f"File PCB non trovato: {pcb_path}")

    if output_dir is None:
        output_dir = pcb_path.parent / "svg"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not layers:
        layers = ["F.Cu", "B.Cu", "Edge.Cuts", "F.Silkscreen", "B.Silkscreen"]

    cmd = [
        str(cli), "pcb", "export", "svg",
        "-o", str(output_dir) + os.sep,
        "--page-size-mode", "2",
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
        "-l", ",".join(layers),
        str(pcb_path),
    ]

    result = _run(cmd, "SVG export")
    files = sorted(str(f.name) for f in output_dir.iterdir()
                   if f.is_file() and f.suffix.lower() == ".svg")

    return {
        "ok": True,
        "success": result.returncode == 0,
        "output_dir": str(output_dir),
        "files": files,
        "total_files": len(files),
    }


# =============================================================================
# Internals
# =============================================================================

def _run(cmd: List[str], operation: str) -> subprocess.CompletedProcess:
    """Esegue un comando kicad-cli con gestione errori uniforme."""
    log.info("[kicad_cli] %s: %s", operation, " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            log.warning("[kicad_cli] %s uscito con codice %d: %s",
                        operation, result.returncode, result.stderr[:500])
            raise KiCadCLIError(f"{operation} fallito: {result.stderr[-1000:]}",
                                returncode=result.returncode, stderr=result.stderr)
        return result
    except subprocess.TimeoutExpired:
        raise KiCadCLIError(
            f"{operation} non completato entro {CLI_TIMEOUT_SECONDS} secondi.",
            returncode=-1,
        )
    except FileNotFoundError:
        raise KiCadCLIError(
            f"Impossibile eseguire il comando: {cmd[0]} non trovato. "
            "Verifica che KiCad sia installato.",
            returncode=-1,
        )
