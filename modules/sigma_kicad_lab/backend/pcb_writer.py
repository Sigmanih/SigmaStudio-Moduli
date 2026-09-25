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


# --- modifica di cio' che c'e' gia' --------------------------------------------
#
# Aggiungere e' una cosa, correggere e' un'altra. Le primitive qui sopra
# creano nodi; queste riscrivono o tolgono nodi che ci sono. Il modo di
# trovarli e' lo stesso — si cammina il testo contando le parentesi e
# rispettando le stringhe — perche' un `(at 10 20)` dentro un pad non e' la
# posizione del footprint, e un `(segment` dentro una proprieta' non e' rame.


def _primo_nodo(testo: str, inizio: int, fine: int,
                nome: str) -> Optional[Tuple[int, int]]:
    """L'estensione del primo `(nome ...)` dell'intervallo, o None."""
    i = inizio
    dentro_stringa = False
    while i < fine:
        c = testo[i]
        if dentro_stringa:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                dentro_stringa = False
            i += 1
            continue
        if c == '"':
            dentro_stringa = True
            i += 1
            continue
        if _apre(testo, i, nome):
            return i, _fine_nodo(testo, i)
        i += 1
    return None


def _apre(testo: str, i: int, nome: str) -> bool:
    """Se a `i` comincia il nodo `(nome ...)`, con il nome intero."""
    if testo[i] != "(" or not testo.startswith(nome, i + 1):
        return False
    dopo = i + 1 + len(nome)
    return dopo >= len(testo) or testo[dopo] in " \t\r\n)"


def _nodi(testo: str, nome: str) -> List[Tuple[int, int]]:
    """Tutti i nodi `(nome ...)` del file, stringhe escluse.

    Non scende dentro i nodi trovati: un `(pad ...)` dentro un footprint non e'
    un pad di primo livello, e trattarlo come tale lo toglierebbe dalla scheda
    lasciando i suoi due punti di riferimento all'aria.
    """
    trovati: List[Tuple[int, int]] = []
    i = 0
    dentro_stringa = False
    while i < len(testo):
        c = testo[i]
        if dentro_stringa:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                dentro_stringa = False
            i += 1
            continue
        if c == '"':
            dentro_stringa = True
            i += 1
            continue
        if _apre(testo, i, nome):
            fine = _fine_nodo(testo, i)
            trovati.append((i, fine))
            i = fine
            continue
        i += 1
    return trovati


def _togli(testo: str, inizio: int, fine: int) -> str:
    """Il file senza il nodo [inizio, fine), con la riga rimasta pulita."""
    return testo[:inizio].rstrip() + "\n" + testo[fine:].lstrip("\n")


def _vicino(a: Sequence[float], b: Sequence[float], tolleranza: float) -> bool:
    return (abs(float(a[0]) - float(b[0])) <= tolleranza
            and abs(float(a[1]) - float(b[1])) <= tolleranza)


def _punto(valore: Sequence[float], nome: str) -> Tuple[float, float]:
    if len(valore) != 2:
        raise PcbWriteError(f"{nome} e' una coppia (x, y) in millimetri.")
    x, y = float(valore[0]), float(valore[1])
    if x != x or y != y:      # NaN non si confronta con niente, nemmeno con se'
        raise PcbWriteError(f"{nome} contiene un numero non valido.")
    return x, y


def move_footprint(pcb_path: Path, reference: str, x_mm: float, y_mm: float,
                   rotation: Optional[float] = None) -> WriteResult:
    """Sposta, e se serve ruota, un footprint solo.

    La rotazione si omette lasciando quella che c'e': un movimento di trascinamento
    non deve raddrizzare un pezzo che era ruotato apposta.

    Cambiare lato non si fa qui. Un flip in KiCad non e' una sostituzione di
    layer nell'`(at)`: i pad si rispecchiano, il testo si specchia, i fori
    restano. Farlo con una regex produce una scheda che sembra giusta e non lo
    e' — e questo e' peggio di non poterlo fare.
    """
    if not str(reference or "").strip():
        raise PcbWriteError("Serve il riferimento del footprint da spostare.")
    x, y = _punto((x_mm, y_mm), "La posizione")

    testo = _leggi(pcb_path)
    inizio = _inizio_footprint(testo, reference)
    if inizio is None:
        raise PcbWriteError(f"Nessun footprint con riferimento '{reference}'.")
    fine = _fine_nodo(testo, inizio)
    nodo = _primo_nodo(testo, inizio, fine, "at")
    if nodo is None:
        raise PcbWriteError(
            f"Il footprint '{reference}' non dichiara la sua `(at ...)`: "
            "spostarlo alla cieca riscriverebbe la prima coordinata trovata, "
            "che sarebbe quella di un pad."
        )

    coda = "" if rotation is None else f" {_num(float(rotation) % 360)}"
    esistente = testo[nodo[0]:nodo[1]]
    if rotation is None:
        # L'angolo che c'e' va rimesso: sostituendo tutto il nodo `(at ...)` con
        # due soli numeri si raddrizza il pezzo, e chi trascina non se ne
        # accorge finche' non e' troppo tardi per ricordare com'era.
        m = re.search(r"\(at\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)\)",
                      esistente)
        if m:
            coda = f" {_num(float(m.group(1)) % 360)}"

    nuovo = testo[:nodo[0]] + f"(at {_num(x)} {_num(y)}{coda})" + testo[nodo[1]:]
    backup = _salva(pcb_path, nuovo)
    return WriteResult(True, "move_footprint", {
        "reference": reference, "x_mm": x, "y_mm": y,
        "rotation": float(coda.strip()) if coda else None,
    }, backup)


def rename_footprint(pcb_path: Path, reference: str,
                     new_reference: str = "", value: str = "") -> WriteResult:
    """Cambia il riferimento e/o il valore di un footprint.

    Il riferimento nuovo dev'essere libero: due `R1` sulla stessa scheda sono un
    file che KiCad apre e una netlist che nessuno sa piu' leggere.
    """
    nuovo_rif = str(new_reference or "").strip()
    if not nuovo_rif and value == "":
        raise PcbWriteError("Non c'e' niente da cambiare: serve un riferimento "
                            "nuovo o un valore.")
    if '"' in nuovo_rif or "\n" in nuovo_rif:
        raise PcbWriteError("Un riferimento non contiene virgolette ne' a capo.")

    testo = _leggi(pcb_path)
    inizio = _inizio_footprint(testo, reference)
    if inizio is None:
        raise PcbWriteError(f"Nessun footprint con riferimento '{reference}'.")
    fine = _fine_nodo(testo, inizio)
    blocco = testo[inizio:fine]

    if nuovo_rif and nuovo_rif != reference:
        if _inizio_footprint(testo, nuovo_rif) is not None:
            raise PcbWriteError(
                f"Il riferimento '{nuovo_rif}' e' gia' di un altro footprint: "
                "due pezzi con lo stesso nome non si distinguono piu'."
            )
        blocco = re.sub(r'(\(property\s+"Reference"\s+)"(?:[^"\\]|\\.)*"',
                        lambda m: f'{m.group(1)}"{nuovo_rif}"', blocco, count=1)
    if value != "":
        blocco = re.sub(r'(\(property\s+"Value"\s+)"(?:[^"\\]|\\.)*"',
                        lambda m: f'{m.group(1)}"{value}"', blocco, count=1)

    backup = _salva(pcb_path, testo[:inizio] + blocco + testo[fine:])
    return WriteResult(True, "rename_footprint", {
        "reference": reference,
        "reference_new": nuovo_rif or reference,
        "value": value or None,
    }, backup)


def delete_track(pcb_path: Path, start: Sequence[float], end: Sequence[float],
                 layer: str = "", tolerance_mm: float = 0.01) -> WriteResult:
    """Toglie la pista che unisce due punti, se c'e'.

    Non ci sono identificativi: una pista si riconosce dai suoi estremi, e si
    accetta anche l'ordine invertito perche' chi clicca non sa da quale capo il
    file l'ha scritta. Quando non si trova, l'errore dice quante piste ci sono e
    qual e' la piu' vicina: un «non trovato» senza numeri fa riprovare a caso.
    """
    a = _punto(start, "start")
    b = _punto(end, "end")
    tolleranza = abs(float(tolerance_mm))

    testo = _leggi(pcb_path)
    candidati: List[Tuple[int, int, Tuple[float, float], Tuple[float, float], str]] = []
    for inizio, fine in _nodi(testo, "segment"):
        blocco = testo[inizio:fine]
        m = re.search(r"\(start\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)\s*"
                      r"\(end\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)", blocco)
        if not m:
            continue
        ml = re.search(r'\(layer\s+"([^"]+)"\)', blocco)
        candidati.append((inizio, fine,
                          (float(m.group(1)), float(m.group(2))),
                          (float(m.group(3)), float(m.group(4))),
                          ml.group(1) if ml else ""))

    for inizio, fine, s, e, lay in candidati:
        dritta = _vicino(s, a, tolleranza) and _vicino(e, b, tolleranza)
        inversa = _vicino(s, b, tolleranza) and _vicino(e, a, tolleranza)
        if not (dritta or inversa):
            continue
        if layer and lay != layer:
            continue
        backup = _salva(pcb_path, _togli(testo, inizio, fine))
        return WriteResult(True, "delete_track", {
            "start": list(s), "end": list(e), "layer": lay}, backup)

    if not candidati:
        raise PcbWriteError("La scheda non ha nessuna pista da cancellare.")
    vicina = min(candidati,
                 key=lambda c: ((c[2][0] - a[0]) ** 2 + (c[2][1] - a[1]) ** 2) ** 0.5)
    raise PcbWriteError(
        f"Nessuna pista fra ({_num(a[0])}, {_num(a[1])}) e ({_num(b[0])}, "
        f"{_num(b[1])})" + (f" sul layer {layer}" if layer else "")
        + f". Ce ne sono {len(candidati)} sulla scheda, e la piu' vicina e' "
        f"({_num(vicina[2][0])}, {_num(vicina[2][1])}) -> "
        f"({_num(vicina[3][0])}, {_num(vicina[3][1])}) su {vicina[4]}."
    )


def delete_via(pcb_path: Path, at: Sequence[float],
               tolerance_mm: float = 0.05) -> WriteResult:
    """Toglie il via che sta in un punto, se c'e'.

    La tolleranza e' piu' larga di quella di una pista: un via si clicca al
    centro di un cerchio di ottavo di millimetro, e pretendere il decimo di
    precisione vorrebbe dire che meta' dei clic non trova niente.
    """
    punto = _punto(at, "at")
    tolleranza = abs(float(tolerance_mm))

    testo = _leggi(pcb_path)
    candidati: List[Tuple[int, int, Tuple[float, float]]] = []
    for inizio, fine in _nodi(testo, "via"):
        m = re.search(r"\(at\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)",
                      testo[inizio:fine])
        if m:
            candidati.append((inizio, fine,
                              (float(m.group(1)), float(m.group(2)))))

    for inizio, fine, centro in candidati:
        if not _vicino(centro, punto, tolleranza):
            continue
        backup = _salva(pcb_path, _togli(testo, inizio, fine))
        return WriteResult(True, "delete_via",
                           {"at": list(centro)}, backup)

    if not candidati:
        raise PcbWriteError("La scheda non ha nessun via da cancellare.")
    vicino = min(candidati,
                 key=lambda c: ((c[2][0] - punto[0]) ** 2
                                + (c[2][1] - punto[1]) ** 2) ** 0.5)
    raise PcbWriteError(
        f"Nessun via a ({_num(punto[0])}, {_num(punto[1])}). Ce ne sono "
        f"{len(candidati)} sulla scheda, e il piu' vicino e' a "
        f"({_num(vicino[2][0])}, {_num(vicino[2][1])})."
    )


def set_board_outline(pcb_path: Path, width_mm: float, height_mm: float,
                      thickness_mm: float = 0.05) -> WriteResult:
    """Sostituisce il contorno della scheda con un rettangolo con un angolo in (0, 0).

    Si tolgono prima i segmenti `Edge.Cuts` che ci sono: aggiungere i quattro
    nuovi sotto i vecchi lascerebbe due contorni, e KiCad rifiuta una scheda
    con piu' di un contorno perche' non sa quale sia il bordo da tagliare.
    """
    larghezza = float(width_mm)
    altezza = float(height_mm)
    if larghezza <= 0 or altezza <= 0:
        raise PcbWriteError("Larghezza e altezza della scheda devono essere positive.")

    testo = _leggi(pcb_path)
    precedenti = sorted(_nodi(testo, "gr_line") + _nodi(testo, "gr_rect"))
    tolti = 0
    # Dal fondo: ogni rimozione accorcia il testo e sposterebbe gli indici che
    # restano da togliere.
    for inizio, fine in reversed(precedenti):
        if '"Edge.Cuts"' not in testo[inizio:fine]:
            continue
        testo = _togli(testo, inizio, fine)
        tolti += 1

    spessore = _num(thickness_mm)
    vertici = ([((0.0, 0.0), (larghezza, 0.0)),
                ((larghezza, 0.0), (larghezza, altezza)),
                ((larghezza, altezza), (0.0, altezza)),
                ((0.0, altezza), (0.0, 0.0))])
    nodi = [f'  (gr_line (start {_num(p[0])} {_num(p[1])}) '
            f'(end {_num(q[0])} {_num(q[1])}) (layer "Edge.Cuts") '
            f'(stroke (width {spessore}) (type solid)))'
            for p, q in vertici]
    backup = _salva(pcb_path, _inserisci(testo, "\n".join(nodi)))
    return WriteResult(True, "set_board_outline", {
        "width_mm": larghezza, "height_mm": altezza,
        "removed_lines": tolti, "added_lines": len(nodi)}, backup)


def set_pad_net(pcb_path: Path, reference: str, pad: str, net: str) -> WriteResult:
    """Assegna una net al pad di un footprint, creando la net se non esiste.

    E' l'unico modo di dire a cosa serve un pad: la net non si deduce dal
    disegno, e un pad senza net e' un collegamento che il DRC non sa verificare.
    """
    nome_net = str(net or "").strip()
    if not nome_net:
        raise PcbWriteError("Serve il nome della net da assegnare al pad.")
    if '"' in nome_net or "\n" in nome_net:
        raise PcbWriteError("Una net non contiene virgolette ne' a capo.")
    numero, _ = ensure_net(pcb_path, nome_net)   # puo' riscrivere il file

    testo = _leggi(pcb_path)                     # quindi si rilegge dopo
    inizio = _inizio_footprint(testo, reference)
    if inizio is None:
        raise PcbWriteError(f"Nessun footprint con riferimento '{reference}'.")
    fine = _fine_nodo(testo, inizio)
    numero_pad = str(pad).strip()

    trovato: Optional[Tuple[int, int, str]] = None
    for rel_inizio, rel_fine in _nodi(testo[inizio:fine], "pad"):
        blocco = testo[inizio + rel_inizio:inizio + rel_fine]
        m = re.match(r'\(pad\s+"((?:[^"\\]|\\.)*)"', blocco)
        if m and m.group(1) == numero_pad:
            trovato = (inizio + rel_inizio, inizio + rel_fine, blocco)
            break
    if trovato is None:
        disponibili = re.findall(r'\(pad\s+"((?:[^"\\]|\\.)*)"',
                                 testo[inizio:fine])
        raise PcbWriteError(
            f"Il footprint '{reference}' non ha un pad '{numero_pad}'. "
            f"I suoi pad sono: {', '.join(disponibili) or 'nessuno'}."
        )

    pi, pf, blocco = trovato
    nuova = f'(net {numero} "{nome_net}")'
    if re.search(r'\(net\s+\d+\s+"[^"]*"\)', blocco):
        blocco = re.sub(r'\(net\s+\d+\s+"[^"]*"\)', nuova, blocco, count=1)
    else:
        # Dentro il nodo del pad, non dopo: fuori, la net non appartiene a
        # nessun pad e il file resta valido solo in apparenza.
        chiusa = blocco.rstrip()
        if not chiusa.endswith(")"):
            raise PcbWriteError(
                f"Il pad '{numero_pad}' di '{reference}' non si chiude: "
                "il file e' corrotto."
            )
        blocco = chiusa[:-1].rstrip() + " " + nuova + ")"

    backup = _salva(pcb_path, testo[:pi] + blocco + testo[pf:])
    return WriteResult(True, "set_pad_net", {
        "reference": reference, "pad": numero_pad, "net": nome_net,
        "net_number": numero}, backup)
