# ==============================================================================
# sigma_kicad_lab/pcb_writer.py — Scrivere dentro un .kicad_pcb
# ==============================================================================
"""Le primitive che mancavano: aggiungere piste, via, net e footprint.

`kicad_parser` sa leggere una scheda e spostare un footprint. Da li' in avanti
non c'era niente: nessun modo di tracciare rame, di aprire una net o di mettere
un pezzo. Senza queste, «interagire col PCB» vuol dire guardarlo.

**Chirurgia sul testo, non riscrittura.** Un `.kicad_pcb` e' una s-expression
sola, e rigenerarla da un albero parsato significa riscrivere anche cio' che non
si e' toccato: commenti, ordine dei nodi, formattazione, campi che il parser non
modella. KiCad riaprirebbe il file, ma il diff sarebbe illeggibile e ogni campo
non modellato andrebbe perso. Qui si inserisce testo prima della parentesi
finale e si lascia intatto tutto il resto — la stessa scelta che
`update_footprint_position` fa gia' per le posizioni.

**Si fa sempre una copia prima di scrivere.** Un layout e' lavoro che non si
rifa' in un pomeriggio, e un agente che sbaglia un'operazione non deve poterlo
perdere.
"""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.logger import get_logger

log = get_logger(__name__)

#: Layer di rame ammessi per piste e via. Scrivere su un layer inesistente
#: produce un file che KiCad apre e in cui il rame non c'e': meglio rifiutare.
COPPER_LAYERS = ("F.Cu", "B.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu",
                 "In5.Cu", "In6.Cu")

#: Quante copie tenere per file. Oltre, le piu' vecchie si cancellano: servono
#: a recuperare l'ultimo errore, non a essere un archivio.
BACKUP_DA_TENERE = 10


class PcbWriteError(RuntimeError):
    """La modifica non e' stata applicata, e il file e' rimasto com'era."""


@dataclass
class WriteResult:
    """Cosa e' stato scritto, e dove stava il file prima."""

    ok: bool
    operation: str
    detail: Dict[str, Any]
    backup: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "operation": self.operation,
                "backup": self.backup, **self.detail}


# --- servizio ------------------------------------------------------------------

def _leggi(pcb_path: Path) -> str:
    if not pcb_path.is_file():
        raise PcbWriteError(f"File PCB inesistente: {pcb_path}")
    return pcb_path.read_text(encoding="utf-8")


def _salva(pcb_path: Path, testo: str) -> str:
    """Scrive il file dopo averne messo da parte una copia. Torna la copia.

    La scrittura passa da un temporaneo e poi da `replace`: se il processo
    muore a meta', il `.kicad_pcb` non resta troncato.
    """
    cartella = pcb_path.parent / ".sigma_backups"
    cartella.mkdir(exist_ok=True)
    copia = cartella / f"{pcb_path.stem}-{int(time.time() * 1000)}.kicad_pcb"
    shutil.copy2(pcb_path, copia)
    _pota(cartella, pcb_path.stem)

    tmp = pcb_path.with_suffix(".kicad_pcb.tmp")
    tmp.write_text(testo, encoding="utf-8")
    tmp.replace(pcb_path)
    return str(copia)


def _pota(cartella: Path, prefisso: str) -> None:
    copie = sorted(cartella.glob(f"{prefisso}-*.kicad_pcb"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for vecchia in copie[BACKUP_DA_TENERE:]:
        try:
            vecchia.unlink()
        except OSError:
            pass


def _inserisci(testo: str, nodo: str) -> str:
    """Mette `nodo` dentro `(kicad_pcb ...)`, subito prima della sua chiusura."""
    fine = testo.rstrip()
    if not fine.endswith(")"):
        raise PcbWriteError(
            "Il file non termina con una parentesi chiusa: non e' un "
            ".kicad_pcb valido, e non ci si scrive dentro alla cieca."
        )
    taglio = fine.rfind(")")
    return f"{fine[:taglio].rstrip()}\n{nodo}\n{fine[taglio:]}\n"


def _num(valore: float) -> str:
    """Un numero come lo scrive KiCad: senza zeri inutili in coda."""
    testo = f"{float(valore):.6f}".rstrip("0").rstrip(".")
    return testo if testo not in ("", "-") else "0"


def _controlla_layer(layer: str) -> str:
    if layer not in COPPER_LAYERS:
        raise PcbWriteError(
            f"Layer '{layer}' non e' di rame. Ammessi: {', '.join(COPPER_LAYERS)}"
        )
    return layer


# --- net -----------------------------------------------------------------------

def net_numbers(testo: str) -> Dict[str, int]:
    """Le net dichiarate nel file, per nome."""
    trovate: Dict[str, int] = {}
    for numero, nome in re.findall(r'\(net\s+(\d+)\s+"([^"]*)"\s*\)', testo):
        trovate[nome] = int(numero)
    return trovate


def ensure_net(pcb_path: Path, name: str) -> Tuple[int, bool]:
    """Il numero della net `name`, creandola se non c'e'. (numero, creata)."""
    nome = str(name).strip()
    if not nome:
        raise PcbWriteError("Una net senza nome non si puo' creare.")

    testo = _leggi(pcb_path)
    esistenti = net_numbers(testo)
    if nome in esistenti:
        return esistenti[nome], False

    nuovo = max(esistenti.values(), default=0) + 1
    _salva(pcb_path, _inserisci(testo, f'  (net {nuovo} "{nome}")'))
    log.info("[pcb_writer] net '%s' creata col numero %d", nome, nuovo)
    return nuovo, True


# --- rame ----------------------------------------------------------------------

def add_track(pcb_path: Path, start: Sequence[float], end: Sequence[float],
              width_mm: float, layer: str = "F.Cu",
              net: str = "") -> WriteResult:
    """Traccia un segmento di pista fra due punti, in millimetri.

    Una pista senza net e' rame che il DRC non sa a cosa appartenga: si accetta
    (serve per le fiducial e i simboli in rame) ma si dichiara nel risultato,
    perche' quasi sempre e' una dimenticanza.
    """
    if width_mm <= 0:
        raise PcbWriteError("La larghezza di una pista deve essere positiva.")
    if len(start) != 2 or len(end) != 2:
        raise PcbWriteError("start ed end sono coppie (x, y) in millimetri.")
    if tuple(start) == tuple(end):
        raise PcbWriteError("Una pista di lunghezza zero non e' una pista.")
    _controlla_layer(layer)

    numero = 0
    if net:
        numero, _ = ensure_net(pcb_path, net)

    testo = _leggi(pcb_path)
    nodo = (f'  (segment (start {_num(start[0])} {_num(start[1])}) '
            f'(end {_num(end[0])} {_num(end[1])}) '
            f'(width {_num(width_mm)}) (layer "{layer}") (net {numero}))')
    backup = _salva(pcb_path, _inserisci(testo, nodo))

    lunghezza = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return WriteResult(True, "add_track", {
        "start": list(start), "end": list(end), "width_mm": width_mm,
        "layer": layer, "net": net, "net_number": numero,
        "length_mm": round(lunghezza, 4),
        "warning": "" if net else "pista senza net: il DRC non la associera' a nulla",
    }, backup)


def add_via(pcb_path: Path, at: Sequence[float], size_mm: float = 0.8,
            drill_mm: float = 0.4, layers: Tuple[str, str] = ("F.Cu", "B.Cu"),
            net: str = "") -> WriteResult:
    """Mette un via passante fra due layer di rame."""
    if len(at) != 2:
        raise PcbWriteError("at e' una coppia (x, y) in millimetri.")
    if drill_mm <= 0 or size_mm <= 0:
        raise PcbWriteError("Diametro e foro devono essere positivi.")
    if drill_mm >= size_mm:
        raise PcbWriteError(
            f"Il foro ({drill_mm} mm) deve essere piu' piccolo del diametro "
            f"({size_mm} mm): altrimenti non resta corona di rame e il via non "
            "conduce."
        )
    for l in layers:
        _controlla_layer(l)

    numero = 0
    if net:
        numero, _ = ensure_net(pcb_path, net)

    testo = _leggi(pcb_path)
    nodo = (f'  (via (at {_num(at[0])} {_num(at[1])}) (size {_num(size_mm)}) '
            f'(drill {_num(drill_mm)}) (layers "{layers[0]}" "{layers[1]}") '
            f'(net {numero}))')
    backup = _salva(pcb_path, _inserisci(testo, nodo))
    return WriteResult(True, "add_via", {
        "at": list(at), "size_mm": size_mm, "drill_mm": drill_mm,
        "layers": list(layers), "net": net, "net_number": numero,
        "annular_ring_mm": round((size_mm - drill_mm) / 2, 4),
    }, backup)


def add_route(pcb_path: Path, points: Sequence[Sequence[float]],
              width_mm: float, layer: str = "F.Cu",
              net: str = "") -> WriteResult:
    """Una spezzata come catena di segmenti: il modo normale di instradare.

    Si dichiara la net una volta sola invece che per ogni segmento, cosi' un
    percorso non puo' finire meta' su una net e meta' su un'altra.
    """
    if len(points) < 2:
        raise PcbWriteError("Un percorso ha almeno due punti.")
    segmenti = []
    totale = 0.0
    backup = None
    for a, b in zip(points, points[1:]):
        esito = add_track(pcb_path, a, b, width_mm, layer, net)
        backup = backup or esito.backup
        segmenti.append(esito.detail)
        totale += esito.detail["length_mm"]
    return WriteResult(True, "add_route", {
        "segments": len(segmenti), "length_mm": round(totale, 4),
        "layer": layer, "net": net, "points": [list(p) for p in points],
    }, backup)


# --- footprint -----------------------------------------------------------------

def add_footprint(pcb_path: Path, library_id: str, reference: str,
                  value: str, at: Sequence[float], rotation: float = 0.0,
                  layer: str = "F.Cu",
                  pads: Optional[List[Dict[str, Any]]] = None) -> WriteResult:
    """Mette un footprint sulla scheda.

    Il flusso normale di KiCad porta i pezzi sul PCB dallo schematico, e questo
    resta il modo giusto quando lo schematico esiste: la netlist e' la' che si
    definisce. Aggiungere qui serve a cio' che uno schematico non descrive —
    fori di fissaggio, fiducial, marchi, schermature — e a costruire una scheda
    di prova senza schematico.

    Il riferimento deve essere libero: due `R1` sullo stesso PCB rendono
    ambiguo ogni comando successivo che parli per riferimento.
    """
    if len(at) != 2:
        raise PcbWriteError("at e' una coppia (x, y) in millimetri.")
    if not str(reference).strip():
        raise PcbWriteError("Un footprint senza riferimento non e' indirizzabile.")

    testo = _leggi(pcb_path)
    if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                 testo):
        raise PcbWriteError(
            f"Il riferimento '{reference}' e' gia' usato su questa scheda. "
            "Scegline un altro: due pezzi con lo stesso riferimento rendono "
            "ambiguo ogni comando che li nomini."
        )

    righe = [f'  (footprint "{library_id}"',
             f'    (at {_num(at[0])} {_num(at[1])}'
             + (f' {_num(rotation)}' if rotation else "") + ")",
             f'    (layer "{layer}")',
             f'    (property "Reference" "{reference}")',
             f'    (property "Value" "{value}")']

    for pad in (pads or []):
        numero_net = 0
        nome_net = str(pad.get("net") or "")
        if nome_net:
            numero_net, _ = ensure_net(pcb_path, nome_net)
            testo = _leggi(pcb_path)          # ensure_net ha riscritto il file
        px, py = pad.get("at", (0, 0))
        sx, sy = pad.get("size", (1, 1))
        righe.append(
            f'    (pad "{pad.get("number", "1")}" '
            f'{pad.get("type", "smd")} {pad.get("shape", "rect")} '
            f'(at {_num(px)} {_num(py)}) (size {_num(sx)} {_num(sy)}) '
            f'(layers "{layer}" "F.Paste" "F.Mask")'
            + (f' (net {numero_net} "{nome_net}")' if nome_net else "") + ")"
        )
    righe[-1] = righe[-1] + ")"

    backup = _salva(pcb_path, _inserisci(testo, "\n".join(righe)))
    return WriteResult(True, "add_footprint", {
        "reference": reference, "library_id": library_id, "value": value,
        "at": list(at), "rotation": rotation, "layer": layer,
        "pads": len(pads or []),
    }, backup)


def remove_footprint(pcb_path: Path, reference: str) -> WriteResult:
    """Toglie dalla scheda il footprint con quel riferimento.

    Le piste che lo raggiungevano restano: il rame non sa che il pezzo se n'e'
    andato. Il DRC le segnalera' come non connesse, ed e' giusto che sia una
    decisione di chi guarda e non una cancellazione automatica.
    """
    testo = _leggi(pcb_path)
    inizio = _inizio_footprint(testo, reference)
    if inizio is None:
        raise PcbWriteError(f"Nessun footprint con riferimento '{reference}'.")
    fine = _fine_nodo(testo, inizio)
    nuovo = testo[:inizio].rstrip() + "\n" + testo[fine:].lstrip("\n")
    backup = _salva(pcb_path, nuovo)
    return WriteResult(True, "remove_footprint",
                       {"reference": reference,
                        "removed_chars": fine - inizio}, backup)


def _inizio_footprint(testo: str, reference: str) -> Optional[int]:
    """L'indice della `(footprint` che contiene quel riferimento."""
    bersaglio = re.search(
        r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', testo)
    if not bersaglio:
        return None
    inizio = testo.rfind("(footprint", 0, bersaglio.start())
    return inizio if inizio >= 0 else None


def _fine_nodo(testo: str, inizio: int) -> int:
    """Dove si chiude il nodo aperto a `inizio`, contando le stringhe."""
    profondita = 0
    dentro_stringa = False
    i = inizio
    while i < len(testo):
        c = testo[i]
        if dentro_stringa:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                dentro_stringa = False
        elif c == '"':
            dentro_stringa = True
        elif c == "(":
            profondita += 1
        elif c == ")":
            profondita -= 1
            if profondita == 0:
                return i + 1
        i += 1
    raise PcbWriteError("Parentesi non bilanciate: il file e' corrotto.")


def restore_backup(pcb_path: Path, backup: str) -> WriteResult:
    """Rimette il file com'era prima di una modifica."""
    copia = Path(backup)
    if not copia.is_file():
        raise PcbWriteError(f"Copia inesistente: {backup}")
    prima = _salva(pcb_path, copia.read_text(encoding="utf-8"))
    return WriteResult(True, "restore_backup",
                       {"restored_from": backup}, prima)
