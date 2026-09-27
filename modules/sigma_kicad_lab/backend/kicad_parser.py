# ==============================================================================
# sigma_kicad_lab/kicad_parser.py — Leggere e scrivere file KiCad
# ==============================================================================
"""Parser nativo per i file KiCad (.kicad_pcb, .kicad_sch, .kicad_pro).

I file KiCad sono S-expression: parentesi, atomi e stringhe virgolettate. Non
servono librerie esterne per leggerli, e non dipendere da `pcbnew` (SWIG, fragile
fra versioni, richiede l'ambiente KiCad) e' una scelta deliberata.

Il parser e' in due strati:

1. **Tokenizer** — spezza il testo in atomi, stringhe e parentesi.
2. **Tree builder** — le parentesi diventano liste Python annidate.

Da li' in poi ogni funzione `read_*` cammina sull'albero per estrarre cio' che
serve, e ogni funzione `write_*` modifica il file con sostituzioni mirate
(non riscrive l'intero albero, cosi' i commenti e la formattazione originale
restano).

**Le unita'.** KiCad 8+ usa millimetri ovunque nei file PCB e schematic. Non
c'e' bisogno del `detect_scale` che serviva per EasyEDA: un millimetro e' un
millimetro, sempre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from core.logger import get_logger

log = get_logger(__name__)

# Il tipo di un nodo nell'albero S-expression: una stringa (atomo) oppure una
# lista di nodi (sotto-espressione fra parentesi).
SExpr = Union[str, List["SExpr"]]


# =============================================================================
# Tokenizer
# =============================================================================

# Token: '(' , ')' , stringa virgolettata (con escape), oppure atomo nudo.
_TOKEN_RE = re.compile(
    r"""
    \s+                    |   # spazi e a-capo — saltati
    [()]                   |   # parentesi
    "(?:[^"\\]|\\.)*"      |   # stringa virgolettata con escape
    [^\s()"]+                  # atomo: tutto il resto
    """,
    re.VERBOSE,
)


def tokenize(text: str) -> List[str]:
    """Spezza il sorgente in token, saltando spazi e commenti."""
    tokens: List[str] = []
    for match in _TOKEN_RE.finditer(text):
        tok = match.group()
        if tok[0] in (" ", "\t", "\n", "\r"):
            continue
        tokens.append(tok)
    return tokens


def parse_sexpr(text: str) -> List[SExpr]:
    """Parsa un file KiCad intero e restituisce una lista di espressioni top-level.

    Il risultato e' una lista perche' un file puo' contenere piu' espressioni
    top-level (raro ma legale).
    """
    tokens = tokenize(text)
    pos = 0
    results: List[SExpr] = []

    def _parse() -> SExpr:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Fine inattesa del file.")
        tok = tokens[pos]
        if tok == "(":
            pos += 1
            children: List[SExpr] = []
            while pos < len(tokens) and tokens[pos] != ")":
                children.append(_parse())
            if pos >= len(tokens):
                raise ValueError("Parentesi aperta senza chiusura.")
            pos += 1   # consuma ')'
            return children
        if tok == ")":
            raise ValueError("Parentesi chiusa senza apertura.")
        pos += 1
        # Le stringhe virgolettate vengono dequotate.
        if tok.startswith('"') and tok.endswith('"'):
            return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return tok

    while pos < len(tokens):
        results.append(_parse())
    return results


# =============================================================================
# Navigazione dell'albero
# =============================================================================

def _find_all(tree: List[SExpr], tag: str) -> List[List[SExpr]]:
    """Tutti i figli di `tree` il cui primo elemento e' `tag`."""
    return [node for node in tree
            if isinstance(node, list) and len(node) > 0 and node[0] == tag]


def _find_one(tree: List[SExpr], tag: str) -> Optional[List[SExpr]]:
    """Il primo figlio con tag, o None."""
    for node in tree:
        if isinstance(node, list) and len(node) > 0 and node[0] == tag:
            return node
    return None


def _value_after(node: List[SExpr], tag: str, default: str = "") -> str:
    """Il valore scalare dopo un sotto-nodo con tag.

    Esempio: in (at 10.5 20.3) con tag='at' restituisce '10.5' (il primo
    valore), ma piu' spesso si usa su sotto-nodi tipo (net 3 "GND") dove
    il tag e' 'net' e il valore cercato e' subito dopo.

    Per estrarre valori multipli (come x e y da `at`) usa `_values_after`.
    """
    sub = _find_one(node, tag)
    if sub is None or len(sub) < 2:
        return default
    return str(sub[1])


def _values_after(node: List[SExpr], tag: str) -> List[str]:
    """Tutti i valori scalari dopo il tag in un sotto-nodo."""
    sub = _find_one(node, tag)
    if sub is None:
        return []
    return [str(v) for v in sub[1:] if isinstance(v, str)]


def _float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# =============================================================================
# Lettura PCB (.kicad_pcb)
# =============================================================================

@dataclass
class KiCadPad:
    """Un pad come letto dal file PCB."""
    number: str
    net_number: int
    net_name: str
    x: float         # posizione assoluta, gia' in mm
    y: float
    layer: str


@dataclass
class KiCadFootprint:
    """Un footprint (componente fisico) sulla scheda."""
    reference: str          # U1, R3, C5...
    value: str              # 100nF, LM7805, ...
    footprint_lib: str      # nome libreria:footprint
    x: float
    y: float
    rotation: float
    layer: str              # F.Cu, B.Cu
    locked: bool
    pads: List[KiCadPad] = field(default_factory=list)
    # dimensioni del courtyard, calcolate dal bounding box dei pad
    width_mm: float = 0.0
    height_mm: float = 0.0


@dataclass
class KiCadNet:
    """Una net dal file PCB."""
    number: int
    name: str


@dataclass
class KiCadTrack:
    """Un segmento di pista sul PCB."""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width_mm: float
    layer: str
    net_number: int
    net_name: str = ""


@dataclass
class KiCadVia:
    """Un via di passaggio tra layer."""
    x: float
    y: float
    size_mm: float
    drill_mm: float
    layers: List[str]
    net_number: int
    net_name: str = ""


@dataclass
class KiCadBoardInfo:
    """Risultato della lettura di un .kicad_pcb."""
    width_mm: float
    height_mm: float
    origin_x: float
    origin_y: float
    footprints: List[KiCadFootprint]
    nets: List[KiCadNet]
    layers: List[str]
    tracks: List[KiCadTrack] = field(default_factory=list)
    vias: List[KiCadVia] = field(default_factory=list)
    raw_tree: List[SExpr] = field(default_factory=list, repr=False)


def read_pcb(path: Path) -> KiCadBoardInfo:
    """Legge un file .kicad_pcb e ne estrae tutto il necessario."""
    text = path.read_text(encoding="utf-8")
    trees = parse_sexpr(text)

    # Il top-level e' (kicad_pcb ...)
    pcb = None
    for t in trees:
        if isinstance(t, list) and len(t) > 0 and t[0] == "kicad_pcb":
            pcb = t
            break
    if pcb is None:
        raise ValueError(f"'{path}' non contiene un nodo kicad_pcb.")

    nets = _read_nets(pcb)
    net_map = {n.number: n.name for n in nets}
    footprints = _read_footprints(pcb, net_map)
    width, height, ox, oy = _read_board_outline(pcb)
    tracks = _read_tracks(pcb, net_map)
    vias = _read_vias(pcb, net_map)
    layers = [str(n[2]) for n in _find_all(pcb, "layers")
              for n in (n[1:] if isinstance(n, list) else [])
              if isinstance(n, list) and len(n) >= 3]
    # Se i layer non si leggono con quel metodo, proviamo il nodo layers
    if not layers:
        layers_node = _find_one(pcb, "layers")
        if layers_node:
            for child in layers_node[1:]:
                if isinstance(child, list) and len(child) >= 3:
                    layers.append(str(child[2]))

    return KiCadBoardInfo(
        width_mm=width, height_mm=height,
        origin_x=ox, origin_y=oy,
        footprints=footprints, nets=nets,
        layers=layers, tracks=tracks, vias=vias,
        raw_tree=pcb,
    )


def _read_tracks(pcb: List[SExpr], net_map: Dict[int, str]) -> List[KiCadTrack]:
    """Legge tutti i segmenti di pista (segment ...) dal PCB."""
    tracks: List[KiCadTrack] = []
    for node in _find_all(pcb, "segment"):
        s_vals = _values_after(node, "start")
        e_vals = _values_after(node, "end")
        if len(s_vals) < 2 or len(e_vals) < 2:
            continue
        sx = _float(s_vals[0])
        sy = _float(s_vals[1])
        ex = _float(e_vals[0])
        ey = _float(e_vals[1])
        w = _float(_value_after(node, "width", "0.25"), default=0.25)
        layer = _value_after(node, "layer", "F.Cu")
        net_num_str = _value_after(node, "net", "0")
        try:
            net_num = int(net_num_str)
        except (ValueError, TypeError):
            net_num = 0
        net_name = net_map.get(net_num, "")
        tracks.append(KiCadTrack(
            start_x=sx, start_y=sy, end_x=ex, end_y=ey,
            width_mm=w, layer=layer, net_number=net_num, net_name=net_name
        ))
    return tracks


def _read_vias(pcb: List[SExpr], net_map: Dict[int, str]) -> List[KiCadVia]:
    """Legge tutti i via (via ...) dal PCB."""
    vias: List[KiCadVia] = []
    for node in _find_all(pcb, "via"):
        at_vals = _values_after(node, "at")
        if len(at_vals) < 2:
            continue
        vx = _float(at_vals[0])
        vy = _float(at_vals[1])
        size = _float(_value_after(node, "size", "0.8"), default=0.8)
        drill = _float(_value_after(node, "drill", "0.4"), default=0.4)
        layers = _values_after(node, "layers")
        if not layers:
            layers = ["F.Cu", "B.Cu"]
        net_num_str = _value_after(node, "net", "0")
        try:
            net_num = int(net_num_str)
        except (ValueError, TypeError):
            net_num = 0
        net_name = net_map.get(net_num, "")
        vias.append(KiCadVia(
            x=vx, y=vy, size_mm=size, drill_mm=drill,
            layers=layers, net_number=net_num, net_name=net_name
        ))
    return vias


def _read_nets(pcb: List[SExpr]) -> List[KiCadNet]:
    """Legge le dichiarazioni (net N "nome") dal pcb."""
    result = []
    for node in _find_all(pcb, "net"):
        if len(node) >= 3:
            try:
                num = int(node[1])
            except (ValueError, TypeError):
                continue
            name = str(node[2])
            result.append(KiCadNet(number=num, name=name))
    return result


def _read_board_outline(pcb: List[SExpr]) -> Tuple[float, float, float, float]:
    """Calcola le dimensioni della scheda dal layer Edge.Cuts.

    KiCad disegna il contorno come linee/archi sul layer Edge.Cuts. Si prende
    il bounding box di tutte le primitive su quel layer.
    """
    xs: List[float] = []
    ys: List[float] = []

    for tag in ("gr_line", "gr_rect", "gr_poly", "gr_arc", "gr_circle"):
        for node in _find_all(pcb, tag):
            layer_val = _value_after(node, "layer")
            if layer_val != "Edge.Cuts":
                continue
            # Raccogli tutti i punti da start, end, center, mid, xy
            for pt_tag in ("start", "end", "center", "mid"):
                vals = _values_after(node, pt_tag)
                if len(vals) >= 2:
                    xs.append(_float(vals[0]))
                    ys.append(_float(vals[1]))
            # Per i poligoni: punti dentro (pts (xy ...)(xy ...))
            pts_node = _find_one(node, "pts")
            if pts_node:
                for xy_node in _find_all(pts_node, "xy"):
                    if len(xy_node) >= 3:
                        xs.append(_float(xy_node[1]))
                        ys.append(_float(xy_node[2]))

    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return max_x - min_x, max_y - min_y, min_x, min_y


def _read_footprints(pcb: List[SExpr],
                     net_map: Dict[int, str]) -> List[KiCadFootprint]:
    """Legge tutti i footprint dal PCB."""
    result = []
    for fp_node in _find_all(pcb, "footprint"):
        if len(fp_node) < 2:
            continue
        fp_lib = str(fp_node[1])

        # Posizione: (at x y [rotation])
        at_vals = _values_after(fp_node, "at")
        x = _float(at_vals[0]) if len(at_vals) >= 1 else 0.0
        y = _float(at_vals[1]) if len(at_vals) >= 2 else 0.0
        rotation = _float(at_vals[2]) if len(at_vals) >= 3 else 0.0

        # Layer
        layer = _value_after(fp_node, "layer", "F.Cu")

        # Bloccato
        locked = any(isinstance(n, str) and n == "locked" for n in fp_node)

        # Proprietà: reference e value
        reference = ""
        value = ""
        for prop in _find_all(fp_node, "property"):
            if len(prop) >= 3:
                prop_name = str(prop[1])
                if prop_name == "Reference":
                    reference = str(prop[2])
                elif prop_name == "Value":
                    value = str(prop[2])

        # Fallback: nei file piu' vecchi reference e value sono in (fp_text)
        if not reference:
            for fp_text in _find_all(fp_node, "fp_text"):
                if len(fp_text) >= 3 and fp_text[1] == "reference":
                    reference = str(fp_text[2])
                elif len(fp_text) >= 3 and fp_text[1] == "value":
                    if not value:
                        value = str(fp_text[2])

        # Pad
        pads = _read_pads(fp_node, x, y, rotation, net_map)

        # Dimensioni dal bounding box dei pad (o courtyard se disponibile)
        width_mm, height_mm = _footprint_dimensions(fp_node, pads)

        result.append(KiCadFootprint(
            reference=reference, value=value, footprint_lib=fp_lib,
            x=x, y=y, rotation=rotation, layer=layer, locked=locked,
            pads=pads, width_mm=width_mm, height_mm=height_mm,
        ))
    return result


def _read_pads(fp_node: List[SExpr], fp_x: float, fp_y: float,
               fp_rotation: float, net_map: Dict[int, str]) -> List[KiCadPad]:
    """Legge i pad di un footprint e ne calcola la posizione assoluta."""
    import math
    result = []
    for pad_node in _find_all(fp_node, "pad"):
        if len(pad_node) < 2:
            continue
        pad_number = str(pad_node[1])

        at_vals = _values_after(pad_node, "at")
        dx = _float(at_vals[0]) if len(at_vals) >= 1 else 0.0
        dy = _float(at_vals[1]) if len(at_vals) >= 2 else 0.0

        # Posizione assoluta: ruota l'offset del pad per la rotazione del
        # footprint.
        #
        # Il segno di sin e' invertito rispetto alla rotazione antioraria dei
        # libri di testo, e non e' una svista: in un file KiCad l'asse Y punta
        # in basso, mentre l'angolo di `(at x y angolo)` e' antiorario come lo
        # vede chi guarda lo schermo. Le due convenzioni insieme danno una
        # rotazione oraria nelle coordinate del file.
        #
        # Con la formula standard i pad di ogni componente ruotato finivano
        # specchiati intorno al proprio centro: su una R_0603 a 90 gradi il pad
        # 1 e il pad 2 si scambiavano di posto, a 1,65 mm l'uno dall'altro.
        # Nessuna lettura se ne accorgeva — le coordinate erano plausibili — e
        # ogni pista tracciata verso quei pad sarebbe atterrata su quello
        # sbagliato. Lo ha rivelato il DRC di KiCad, che collocava il pad 1 di
        # R1 dove noi mettevamo il pad 2.
        rad = math.radians(fp_rotation)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        abs_x = fp_x + dx * cos_r + dy * sin_r
        abs_y = fp_y - dx * sin_r + dy * cos_r

        # Net
        net_num_str = _value_after(pad_node, "net", "0")
        try:
            net_num = int(net_num_str)
        except (ValueError, TypeError):
            net_num = 0
        net_name = ""
        # Il nome della net puo' essere nel nodo pad stesso: (net N "nome")
        net_node = _find_one(pad_node, "net")
        if net_node and len(net_node) >= 3:
            net_name = str(net_node[2])
        elif net_num in net_map:
            net_name = net_map[net_num]

        # Layer del pad
        layers_node = _find_one(pad_node, "layers")
        pad_layer = ""
        if layers_node and len(layers_node) >= 2:
            pad_layer = str(layers_node[1])

        result.append(KiCadPad(
            number=pad_number, net_number=net_num, net_name=net_name,
            x=abs_x, y=abs_y, layer=pad_layer,
        ))
    return result


def _footprint_dimensions(fp_node: List[SExpr],
                          pads: List[KiCadPad]) -> Tuple[float, float]:
    """Deduce le dimensioni di un footprint.

    Prima prova dal courtyard (piu' preciso), poi dal bounding box dei pad
    con un margine, infine da una stima dal nome della libreria.
    """
    # Courtyard
    for fab in _find_all(fp_node, "fp_poly"):
        layer_v = _value_after(fab, "layer")
        if "Courtyard" in layer_v:
            xs, ys = [], []
            pts_node = _find_one(fab, "pts")
            if pts_node:
                for xy_n in _find_all(pts_node, "xy"):
                    if len(xy_n) >= 3:
                        xs.append(_float(xy_n[1]))
                        ys.append(_float(xy_n[2]))
            if xs and ys:
                return max(xs) - min(xs), max(ys) - min(ys)

    # Bounding box dei pad con margine
    if pads:
        # Usa le coordinate relative (offset dal centro del footprint)
        at_vals_list = []
        for pad_node in _find_all(fp_node, "pad"):
            vals = _values_after(pad_node, "at")
            if len(vals) >= 2:
                at_vals_list.append((_float(vals[0]), _float(vals[1])))
        if at_vals_list:
            xs = [p[0] for p in at_vals_list]
            ys = [p[1] for p in at_vals_list]
            w = (max(xs) - min(xs)) + 1.0   # margine di 0.5mm per lato
            h = (max(ys) - min(ys)) + 1.0
            return max(w, 1.0), max(h, 1.0)

    return 1.0, 1.0


# =============================================================================
# Lettura schematico (.kicad_sch) — estrazione netlist
# =============================================================================

@dataclass
class KiCadSchComponent:
    """Un simbolo nello schematico."""
    reference: str
    value: str
    lib_id: str
    x: float
    y: float
    unit: int


@dataclass
class KiCadSchPin:
    """Un pin di uno schematico, con il suo collegamento."""
    reference: str
    pin_number: str
    pin_name: str
    x: float
    y: float
    net_name: str


@dataclass
class KiCadSchInfo:
    """Risultato della lettura di un .kicad_sch."""
    components: List[KiCadSchComponent]
    connections: Dict[str, List[Tuple[str, str]]]  # net_name -> [(ref, pin)]


def read_schematic(path: Path) -> KiCadSchInfo:
    """Legge un file .kicad_sch e ne estrae componenti e connettivita'.

    La connettivita' completa in KiCad si ricava dalla netlist generata da
    kicad-cli. Qui si fa un'estrazione di primo livello dai label e dai wire,
    sufficiente per il modello Board. Per la netlist definitiva si usa
    `kicad_cli.export_netlist()`.
    """
    text = path.read_text(encoding="utf-8")
    trees = parse_sexpr(text)

    sch = None
    for t in trees:
        if isinstance(t, list) and len(t) > 0 and t[0] == "kicad_sch":
            sch = t
            break
    if sch is None:
        raise ValueError(f"'{path}' non contiene un nodo kicad_sch.")

    components = _read_sch_symbols(sch)
    connections = _read_sch_connections(sch)
    return KiCadSchInfo(components=components, connections=connections)


def _read_sch_symbols(sch: List[SExpr]) -> List[KiCadSchComponent]:
    """Legge i simboli dallo schematico."""
    result = []
    for sym in _find_all(sch, "symbol"):
        if len(sym) < 2:
            continue

        # Proprietà
        reference = ""
        value = ""
        for prop in _find_all(sym, "property"):
            if len(prop) >= 3:
                pname = str(prop[1])
                if pname == "Reference":
                    reference = str(prop[2])
                elif pname == "Value":
                    value = str(prop[2])

        # Posizione
        at_vals = _values_after(sym, "at")
        x = _float(at_vals[0]) if len(at_vals) >= 1 else 0.0
        y = _float(at_vals[1]) if len(at_vals) >= 2 else 0.0

        # Unita'
        unit_val = _value_after(sym, "unit", "1")

        # Salta i simboli di libreria (lib_id contiene il nome, instances e' presente)
        lib_id = ""
        lib_node = _find_one(sym, "lib_id")
        if lib_node and len(lib_node) >= 2:
            lib_id = str(lib_node[1])

        # I simboli senza reference sono dichiarazioni di libreria, non istanze
        if not reference or reference.startswith("#"):
            continue

        result.append(KiCadSchComponent(
            reference=reference, value=value, lib_id=lib_id,
            x=x, y=y, unit=int(_float(unit_val, 1)),
        ))
    return result


def _read_sch_connections(sch: List[SExpr]) -> Dict[str, List[Tuple[str, str]]]:
    """Estrae le connessioni di base dallo schematico.

    Questa e' un'estrazione euristica dai label: la netlist vera si ottiene
    con `kicad-cli sch export netlist`. Per il modello Board e' sufficiente.
    """
    connections: Dict[str, List[Tuple[str, str]]] = {}

    # Cerca i net label e i global label
    for tag in ("net_label", "global_label", "hierarchical_label", "label"):
        for node in _find_all(sch, tag):
            if len(node) < 2:
                continue
            net_name = str(node[1])
            if net_name not in connections:
                connections[net_name] = []

    return connections


# =============================================================================
# Scrittura — modifiche mirate ai file
# =============================================================================

def update_footprint_position(pcb_path: Path, reference: str,
                              x_mm: float, y_mm: float,
                              rotation: float = None) -> bool:
    """Modifica la posizione di un footprint nel file .kicad_pcb.

    Invece di riscrivere l'intero albero (perdendo commenti e formattazione),
    si fa una sostituzione mirata della riga `(at ...)` dentro il footprint
    con il reference dato.
    """
    text = pcb_path.read_text(encoding="utf-8")
    trees = parse_sexpr(text)

    pcb = None
    for t in trees:
        if isinstance(t, list) and len(t) > 0 and t[0] == "kicad_pcb":
            pcb = t
            break
    if pcb is None:
        return False

    # Trova il footprint con il reference giusto
    for fp_node in _find_all(pcb, "footprint"):
        ref = ""
        for prop in _find_all(fp_node, "property"):
            if len(prop) >= 3 and str(prop[1]) == "Reference":
                ref = str(prop[2])
                break
        if not ref:
            for fp_text in _find_all(fp_node, "fp_text"):
                if len(fp_text) >= 3 and fp_text[1] == "reference":
                    ref = str(fp_text[2])
                    break
        if ref != reference:
            continue

        # Trovato: sostituisci la posizione nel testo originale
        at_node = _find_one(fp_node, "at")
        if at_node is None:
            continue

        # Ricostruisci la riga (at ...) originale per trovarla nel testo
        old_at = _reconstruct_at(at_node)
        if rotation is not None:
            new_at = f"(at {x_mm:.4f} {y_mm:.4f} {rotation:.1f})"
        else:
            # Mantieni la rotazione originale
            old_rot = _float(str(at_node[3])) if len(at_node) >= 4 else 0.0
            if old_rot != 0.0:
                new_at = f"(at {x_mm:.4f} {y_mm:.4f} {old_rot:.1f})"
            else:
                new_at = f"(at {x_mm:.4f} {y_mm:.4f})"

        # La sostituzione e' nel contesto del footprint, non globale: cerchiamo
        # il pattern del footprint con il suo reference per non colpire un
        # altro (at ...) che per caso ha gli stessi numeri.
        # Strategia: trova la porzione di testo del footprint e sostituisci li'.
        new_text = _replace_at_in_footprint(text, reference, old_at, new_at)
        if new_text != text:
            pcb_path.write_text(new_text, encoding="utf-8")
            return True

    return False


def _reconstruct_at(at_node: List[SExpr]) -> str:
    """Ricostruisce la stringa (at ...) da un nodo parsato."""
    parts = ["at"]
    for v in at_node[1:]:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            break   # sotto-nodi: non fanno parte della coordinata
    return "(" + " ".join(parts) + ")"


def _replace_at_in_footprint(text: str, reference: str,
                              old_at: str, new_at: str) -> str:
    """Sostituisce (at ...) dentro il footprint col reference dato.

    Cerca il footprint nel testo grezzo, poi dentro quel blocco cerca il
    primo (at ...) e lo sostituisce. Cosi' non si rischia di colpire un (at ...)
    che appartiene a un altro footprint.
    """
    # Trova il footprint con questo reference — cerchiamo il pattern della
    # property Reference o del fp_text reference
    ref_patterns = [
        f'(property "Reference" "{reference}"',
        f'(fp_text reference "{reference}"',
    ]
    fp_start = -1
    for pat in ref_patterns:
        idx = text.find(pat)
        if idx >= 0:
            # Risali al (footprint che contiene questo reference
            search_back = text.rfind("(footprint", 0, idx)
            if search_back >= 0:
                fp_start = search_back
                break

    if fp_start < 0:
        return text

    # Trova il primo (at ...) dopo fp_start
    at_idx = text.find(old_at, fp_start)
    if at_idx < 0:
        # Prova con spazi diversi: il parser normalizza ma il file potrebbe avere
        # spaziature diverse. Cerchiamo un pattern piu' flessibile.
        at_re = re.compile(
            r"\(at\s+" + r"\s+".join(re.escape(p) for p in old_at[4:-1].split()) + r"\)"
        )
        match = at_re.search(text, fp_start)
        if match:
            return text[:match.start()] + new_at + text[match.end():]
        return text

    return text[:at_idx] + new_at + text[at_idx + len(old_at):]


def update_multiple_positions(pcb_path: Path,
                               moves: Dict[str, Tuple[float, float, Optional[float]]]) -> Dict[str, bool]:
    """Aggiorna le posizioni di piu' footprint in una sola riscrittura.

    `moves` e' {reference: (x_mm, y_mm, rotation_or_None)}.
    Restituisce {reference: True/False} per ciascun tentativo.
    """
    results = {}
    for ref, (x, y, rot) in moves.items():
        ok = update_footprint_position(pcb_path, ref, x, y, rot)
        results[ref] = ok
    return results


def board_to_dict(info: KiCadBoardInfo) -> Dict[str, Any]:
    """Serializza KiCadBoardInfo in un dizionario JSON compatibile per le API del frontend."""
    return {
        "width_mm": round(info.width_mm, 3),
        "height_mm": round(info.height_mm, 3),
        "origin_x": round(info.origin_x, 3),
        "origin_y": round(info.origin_y, 3),
        "layers": info.layers,
        "nets": [{"number": n.number, "name": n.name} for n in info.nets],
        "components": [
            {
                "reference": fp.reference,
                "value": fp.value,
                "footprint_lib": fp.footprint_lib,
                "x_mm": round(fp.x, 3),
                "y_mm": round(fp.y, 3),
                "rotation": fp.rotation,
                "layer": fp.layer,
                "locked": fp.locked,
                "width_mm": round(fp.width_mm, 3),
                "height_mm": round(fp.height_mm, 3),
                "pads": [
                    {
                        "number": p.number,
                        "net_number": p.net_number,
                        "net_name": p.net_name,
                        "x_mm": round(p.x, 3),
                        "y_mm": round(p.y, 3),
                        "layer": p.layer,
                    }
                    for p in fp.pads
                ],
            }
            for fp in info.footprints
        ],
        "tracks": [
            {
                "start_x": round(t.start_x, 3),
                "start_y": round(t.start_y, 3),
                "end_x": round(t.end_x, 3),
                "end_y": round(t.end_y, 3),
                "width_mm": round(t.width_mm, 3),
                "layer": t.layer,
                "net_number": t.net_number,
                "net_name": t.net_name,
            }
            for t in info.tracks
        ],
        "vias": [
            {
                "x_mm": round(v.x, 3),
                "y_mm": round(v.y, 3),
                "size_mm": round(v.size_mm, 3),
                "drill_mm": round(v.drill_mm, 3),
                "layers": v.layers,
                "net_number": v.net_number,
                "net_name": v.net_name,
            }
            for v in info.vias
        ],
    }


def board_to_svg(info: KiCadBoardInfo) -> str:
    """Genera un'anteprima SVG della scheda PCB da KiCadBoardInfo.

    Disegna outline (Edge.Cuts), footprint come rettangoli con riferimento,
    pad come cerchi, tracce come linee e vias come anelli.
    Le coordinate sono in mm, con padding di 5 mm attorno alla board.
    """
    pad_mm = 5.0
    ox = info.origin_x - pad_mm
    oy = info.origin_y - pad_mm
    w = info.width_mm + 2 * pad_mm
    h = info.height_mm + 2 * pad_mm

    # Scala: 1 mm = 4 px per un SVG leggibile
    scale = 4.0
    sw = int(w * scale)
    sh = int(h * scale)

    def sx(mm_x: float) -> float:
        return (mm_x - ox) * scale

    def sy(mm_y: float) -> float:
        return (mm_y - oy) * scale

    parts: List[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {sw} {sh}" '
                 f'width="{sw}" height="{sh}">')
    parts.append('  <rect width="100%" height="100%" fill="#0f172a"/>')

    # Outline della board (rettangolo)
    bx, by = sx(info.origin_x), sy(info.origin_y)
    bw, bh = info.width_mm * scale, info.height_mm * scale
    parts.append(f'  <rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'fill="#1e293b" stroke="#475569" stroke-width="2" rx="2"/>')

    # Tracce (linee)
    for t in info.tracks:
        x1, y1 = sx(t.start_x), sy(t.start_y)
        x2, y2 = sx(t.end_x), sy(t.end_y)
        tw = max(0.5, t.width_mm * scale * 0.3)
        color = "#38bdf8" if t.layer == "F.Cu" else "#fb923c"
        parts.append(f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="{color}" stroke-width="{tw:.1f}" opacity="0.6"/>')

    # Vias (anelli)
    for v in info.vias:
        vx, vy = sx(v.x), sy(v.y)
        vr = max(2, v.size_mm * scale * 0.5)
        parts.append(f'  <circle cx="{vx:.1f}" cy="{vy:.1f}" r="{vr:.1f}" '
                     f'fill="none" stroke="#a78bfa" stroke-width="1.5"/>')

    # Footprint (rettangoli + riferimento + pad)
    for fp in info.footprints:
        cx, cy = sx(fp.x), sy(fp.y)
        fw = max(4, fp.width_mm * scale)
        fh = max(4, fp.height_mm * scale)
        fill = "#1e3a5f" if fp.layer == "F.Cu" else "#3d2b1f"
        stroke = "#60a5fa" if fp.layer == "F.Cu" else "#fb923c"
        parts.append(f'  <rect x="{cx - fw/2:.1f}" y="{cy - fh/2:.1f}" width="{fw:.1f}" '
                     f'height="{fh:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1" rx="1"/>')
        # Riferimento (U1, R3...)
        parts.append(f'  <text x="{cx:.1f}" y="{cy + 2:.1f}" text-anchor="middle" '
                     f'fill="#e2e8f0" font-size="{max(6, fw*0.3):.0f}" font-family="monospace">'
                     f'{fp.reference}</text>')

        # Pad (cerchi)
        for p in fp.pads:
            px, py = sx(p.x), sy(p.y)
            pr = max(1.5, 0.8 * scale * 0.5)
            parts.append(f'  <circle cx="{px:.1f}" cy="{py:.1f}" r="{pr:.1f}" '
                         f'fill="#94a3b8" stroke="#cbd5e1" stroke-width="0.5"/>')

    parts.append('</svg>')
    return "\n".join(parts)






def _fori_m3(width_mm: float, height_mm: float) -> List[str]:
    """Genera i fori di montaggio M3 a 5mm dai bordi (4 angoli)."""
    ox, oy = 100.0, 100.0
    x2, y2 = ox + width_mm, oy + height_mm
    m = 5.0  # distanza dal bordo
    r = 1.5  # raggio foro M3 (diametro 3mm)
    posizioni = [
        (ox + m, oy + m),
        (x2 - m, oy + m),
        (x2 - m, y2 - m),
        (ox + m, y2 - m),
    ]
    righe = []
    for i, (px, py) in enumerate(posizioni, 1):
        righe.append(
            '  (footprint "MountingHole:Mounting_Hole_3.2mm_M3"'
            '    (layer "F.Cu")'
            f'    (uuid "00000000-0000-0000-0000-{i:010d}")'
            f'    (at {px:.4f} {py:.4f})'
            '    (descr "Foro di montaggio M3")'
            '    (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))'
            '  )'
        )
    return righe


def _genera_pcb_base(clean_name: str, width_mm: float, height_mm: float,
                     extra_footprints: List[str] = None) -> str:
    """Genera il contenuto .kicad_pcb con contorno Edge.Cuts e fori M3."""
    ox, oy = 100.0, 100.0
    x2, y2 = ox + width_mm, oy + height_mm
    fori = _fori_m3(width_mm, height_mm)
    fp_block = "\n".join(extra_footprints or [])
    return f"""(kicad_pcb
  (version 20240108)
  (generator "pcbnew")
  (generator_version "10.0")
  (general
    (thickness 1.6)
  )
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (44 "Edge.Cuts" user)
  )
  (setup
    (pad_to_mask_clearance 0.05)
  )
  (net 0 "")
  (gr_line (start {ox:.4f} {oy:.4f}) (end {x2:.4f} {oy:.4f}) (layer "Edge.Cuts") (stroke (width 0.15) (type solid)))
  (gr_line (start {x2:.4f} {oy:.4f}) (end {x2:.4f} {y2:.4f}) (layer "Edge.Cuts") (stroke (width 0.15) (type solid)))
  (gr_line (start {x2:.4f} {y2:.4f}) (end {ox:.4f} {y2:.4f}) (layer "Edge.Cuts") (stroke (width 0.15) (type solid)))
  (gr_line (start {ox:.4f} {y2:.4f}) (end {ox:.4f} {oy:.4f}) (layer "Edge.Cuts") (stroke (width 0.15) (type solid)))
{fp_block}
)
"""


def _genera_sch_base(clean_name: str, extra_symbols: List[str] = None) -> str:
    """Genera il contenuto .kicad_sch con titolo e simboli opzionali."""
    sym_block = "\n".join(extra_symbols or [])
    return f"""(kicad_sch
  (version 20231120)
  (generator "eeschema")
  (generator_version "10.0")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  (title_block
    (title "{clean_name}")
    (company "Sigma Studio Hardware")
  )
{sym_block}
)
"""


def create_project_from_template(project_dir: Path, project_name: str,
                                 template: str = "vuota",
                                 width_mm: float = 80.0,
                                 height_mm: float = 60.0,
                                 mcu: str = "RP2040") -> Dict[str, str]:
    """Crea un progetto KiCad da uno dei tre template.

    Template disponibili:
      - "vuota": scheda vuota con contorno e fori M3.
      - "ldo_3v3": regolatore LDO 3.3V (AMS1117) con condensatori e connettori pin.
      - "breakout_mcu": breakout board microcontrollore (RP2040 o ESP32).
    """
    import json
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", project_name.strip()) or "project"
    pro_path = project_dir / f"{clean_name}.kicad_pro"
    sch_path = project_dir / f"{clean_name}.kicad_sch"
    pcb_path = project_dir / f"{clean_name}.kicad_pcb"

    # --- .kicad_pro ---
    pro_content = {
        "meta": {"filename": f"{clean_name}.kicad_pro", "version": 1},
        "project": {"name": clean_name},
        "schematic": {"annotate_start_num": 1},
        "board": {"design_settings": {}},
    }
    pro_path.write_text(json.dumps(pro_content, indent=2), encoding="utf-8")

    # --- Template specifici ---
    extra_fp: List[str] = []
    extra_sym: List[str] = []

    if template == "ldo_3v3":
        # LDO AMS1117 SOT-223 + C_in 10uF + C_out 10uF + connettori pin 2x1
        cx, cy = 150.0, 150.0
        extra_fp = [
            f'  (footprint "Regulator_Linear:TO-223-3"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000101")\n'
            f'    (at {cx:.4f} {cy:.4f})\n'
            f'    (descr "LDO AMS1117 3.3V")\n'
            f'    (pad "1" smd rect (at -2.3 0) (size 1.5 2.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "2" smd rect (at 0 0) (size 1.5 2.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "3" smd rect (at 2.3 0) (size 1.5 2.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'  )',
            f'  (footprint "Capacitor_SMD:C_0805_2012Metric"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000102")\n'
            f'    (at {cx - 15:.4f} {cy:.4f})\n'
            f'    (descr "C_in 10uF")\n'
            f'    (pad "1" smd rect (at -0.95 0) (size 0.5 1.6) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "2" smd rect (at 0.95 0) (size 0.5 1.6) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'  )',
            f'  (footprint "Capacitor_SMD:C_0805_2012Metric"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000103")\n'
            f'    (at {cx + 15:.4f} {cy:.4f})\n'
            f'    (descr "C_out 10uF")\n'
            f'    (pad "1" smd rect (at -0.95 0) (size 0.5 1.6) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "2" smd rect (at 0.95 0) (size 0.5 1.6) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'  )',
            f'  (footprint "Pin_Headers:Pin_Header_Straight_2x01"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000104")\n'
            f'    (at {cx:.4f} {cy + 25:.4f})\n'
            f'    (descr "Connettore Vin")\n'
            f'    (pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "2" thru_hole circle (at 2.54 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'  )',
        ]
        extra_sym = [
            '  (symbol (lib_id "Regulator_Linear:AMS1117-3.3") (at 100 100) (unit 1) (uuid "00000000-0000-0000-0000-000000000201"))',
            '  (symbol (lib_id "Device:C") (at 80 100) (unit 1) (uuid "00000000-0000-0000-0000-000000000202"))',
            '  (symbol (lib_id "Device:C") (at 120 100) (unit 1) (uuid "00000000-0000-0000-0000-000000000203"))',
            '  (symbol (lib_id "Connector:Conn_01x02") (at 100 130) (unit 1) (uuid "00000000-0000-0000-0000-000000000204"))',
        ]

    elif template == "breakout_mcu":
        mcu_clean = re.sub(r"[^a-zA-Z0-9]", "", mcu) or "RP2040"
        cx, cy = 150.0, 150.0
        # Footprint MCU (QFN/SOP generico) + connettori pin 2x8
        extra_fp = [
            f'  (footprint "Package_QFN:QFN-48_7x7mm_P0.5mm"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000301")\n'
            f'    (at {cx:.4f} {cy:.4f})\n'
            f'    (descr "MCU {mcu_clean}")\n'
            f'    (pad "1" smd rect (at -3.5 -3.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "2" smd rect (at -3.5 -2.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "3" smd rect (at -3.5 -1.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "4" smd rect (at -3.5 -0.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "5" smd rect (at -3.5 0.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "6" smd rect (at -3.5 1.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "7" smd rect (at -3.5 2.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'    (pad "8" smd rect (at -3.5 3.5) (size 0.5 1.0) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
            f'  )',
            f'  (footprint "Pin_Headers:Pin_Header_Straight_2x08"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000302")\n'
            f'    (at {cx - 15:.4f} {cy + 20:.4f})\n'
            f'    (descr "Connettore pin sinistro")\n'
            f'    (pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "2" thru_hole circle (at 0 2.54) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "3" thru_hole circle (at 0 5.08) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "4" thru_hole circle (at 0 7.62) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "5" thru_hole circle (at 0 10.16) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "6" thru_hole circle (at 0 12.7) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "7" thru_hole circle (at 0 15.24) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "8" thru_hole circle (at 0 17.78) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'  )',
            f'  (footprint "Pin_Headers:Pin_Header_Straight_2x08"\n'
            f'    (layer "F.Cu")\n'
            f'    (uuid "00000000-0000-0000-0000-000000000303")\n'
            f'    (at {cx + 15:.4f} {cy + 20:.4f})\n'
            f'    (descr "Connettore pin destro")\n'
            f'    (pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "2" thru_hole circle (at 0 2.54) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "3" thru_hole circle (at 0 5.08) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "4" thru_hole circle (at 0 7.62) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "5" thru_hole circle (at 0 10.16) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "6" thru_hole circle (at 0 12.7) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "7" thru_hole circle (at 0 15.24) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'    (pad "8" thru_hole circle (at 0 17.78) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))\n'
            f'  )',
        ]
        extra_sym = [
            f'  (symbol (lib_id "MCU:{mcu_clean}") (at 100 100) (unit 1) (uuid "00000000-0000-0000-0000-000000000401"))',
            '  (symbol (lib_id "Connector:Conn_02x08") (at 80 130) (unit 1) (uuid "00000000-0000-0000-0000-000000000402"))',
        ]

    # --- Genera .kicad_pcb con contorno + fori M3 + footprint extra ---
    pcb_content = _genera_pcb_base(clean_name, width_mm, height_mm, extra_fp)
    pcb_path.write_text(pcb_content, encoding="utf-8")

    # --- Genera .kicad_sch con simboli extra ---
    sch_content = _genera_sch_base(clean_name, extra_sym)
    sch_path.write_text(sch_content, encoding="utf-8")

    return {
        "project_name": clean_name,
        "template": template,
        "pro_path": str(pro_path),
        "sch_path": str(sch_path),
        "pcb_path": str(pcb_path),
    }
