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

def run_drc(pcb_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Esegue il DRC su un file .kicad_pcb e restituisce il report JSON.

    kicad-cli pcb drc --severity-all --format json -o <output> <file>
    """
    cli = require_kicad_cli()
    pcb_path = Path(pcb_path)
    if not pcb_path.is_file():
        raise KiCadCLIError(f"File PCB non trovato: {pcb_path}")

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}_drc.json"

    cmd = [
        str(cli), "pcb", "drc",
        "--severity-all",
        "--format", "json",
        "-o", str(output_path),
        str(pcb_path),
    ]

    result = _run(cmd, "DRC")

    # Leggi il report generato
    report = {"ok": True, "returncode": result.returncode}
    if output_path.is_file():
        try:
            raw = json.loads(output_path.read_text(encoding="utf-8"))
            report["violations"] = raw.get("violations", [])
            report["unconnected"] = raw.get("unconnected_items", [])
            report["schematic_parity"] = raw.get("schematic_parity", [])
            report["total_errors"] = len(report["violations"])
            report["total_unconnected"] = len(report["unconnected"])
            report["success"] = report["total_errors"] == 0
        except (json.JSONDecodeError, OSError) as exc:
            report["parse_error"] = str(exc)
            report["success"] = False
    else:
        report["success"] = result.returncode == 0

    return report


# =============================================================================
# ERC — Electrical Rule Check
# =============================================================================

def run_erc(sch_path: Path, output_path: Path = None) -> Dict[str, Any]:
    """Esegue l'ERC su un file .kicad_sch e restituisce il report JSON.

    kicad-cli sch erc --severity-all --format json -o <output> <file>
    """
    cli = require_kicad_cli()
    sch_path = Path(sch_path)
    if not sch_path.is_file():
        raise KiCadCLIError(f"File schematico non trovato: {sch_path}")

    if output_path is None:
        output_path = sch_path.parent / f"{sch_path.stem}_erc.json"

    cmd = [
        str(cli), "sch", "erc",
        "--severity-all",
        "--format", "json",
        "-o", str(output_path),
        str(sch_path),
    ]

    result = _run(cmd, "ERC")

    report = {"ok": True, "returncode": result.returncode}
    if output_path.is_file():
        try:
            raw = json.loads(output_path.read_text(encoding="utf-8"))
            report["violations"] = raw.get("violations", [])
            report["total_errors"] = len(report["violations"])
            report["success"] = report["total_errors"] == 0
        except (json.JSONDecodeError, OSError) as exc:
            report["parse_error"] = str(exc)
            report["success"] = False
    else:
        report["success"] = result.returncode == 0

    return report


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
        "-w", str(int(width)),
        "-h", str(int(height)),
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
