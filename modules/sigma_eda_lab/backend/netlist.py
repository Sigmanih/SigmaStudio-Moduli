# ==============================================================================
# sigma_eda_lab/netlist.py — The board as data
# ==============================================================================
"""Il modello di scheda su cui lavorano piazzamento e valutazione.

EasyEDA sa dire cosa c'e' sulla scheda, e sa applicare una trasformazione a un
componente. Fra le due cose non c'e' niente: nessuno calcola *dove* andrebbero
messi i pezzi. Questo modulo tiene la scheda in una forma su cui quel calcolo si
puo' fare — componenti con un ingombro, pin con un offset, net che li legano — e
resta deliberatamente ignorante di EasyEDA, cosi' gli algoritmi si possono
provare senza aprire il bridge.

Le unita' sono millimetri ovunque. EasyEDA Pro lavora internamente in unita' che
non sono millimetri e la conversione vive in `bridge.py`, in un posto solo.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Sequence, Tuple

# Le rotazioni ammesse. EasyEDA accetta angoli arbitrari, ma un piazzamento a
# passo libero e' peggiore di uno ortogonale: complica il routing e non e' cio'
# che un assemblatore si aspetta di vedere.
ROTATIONS = (0, 90, 180, 270)

SIDE_TOP = "top"
SIDE_BOTTOM = "bottom"

# Classi di net, in ordine di quanto corta va tenuta la connessione.
CLASS_CRITICAL = "critical"   # cristalli, linee differenziali, feedback
CLASS_POWER = "power"
CLASS_GROUND = "ground"
CLASS_SIGNAL = "signal"

CLASS_WEIGHT: Dict[str, float] = {
    CLASS_CRITICAL: 4.0,
    CLASS_POWER: 1.5,
    CLASS_GROUND: 0.5,   # il ritorno passa dal piano, non dalla pista
    CLASS_SIGNAL: 1.0,
}


class BoardError(ValueError):
    """Il modello descrive una scheda che non puo' esistere."""


@dataclass(frozen=True)
class Pin:
    """Un pin, nel sistema di riferimento del suo componente non ruotato."""

    number: str
    dx: float
    dy: float
    net: str = ""


@dataclass
class Component:
    """Un pezzo sulla scheda.

    `x`/`y` sono il centro dell'ingombro, non un angolo: ruotare intorno al
    centro e' l'unica scelta che non sposta anche il pezzo quando lo si gira.
    `locked` e' il modo in cui l'operatore dice all'ottimizzatore di non
    toccare qualcosa — un connettore sul bordo, un foro di fissaggio, un'antenna
    che e' stata posizionata a mano per una ragione che il costo non conosce.
    """

    designator: str
    width: float
    height: float
    x: float = 0.0
    y: float = 0.0
    rotation: int = 0
    side: str = SIDE_TOP
    locked: bool = False
    footprint: str = ""
    primitive_id: str = ""
    pins: Tuple[Pin, ...] = ()

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise BoardError(
                f"{self.designator}: ingombro non valido {self.width}x{self.height} mm"
            )
        if self.rotation not in ROTATIONS:
            raise BoardError(
                f"{self.designator}: rotazione {self.rotation} fuori da {ROTATIONS}"
            )
        if self.side not in (SIDE_TOP, SIDE_BOTTOM):
            raise BoardError(f"{self.designator}: lato '{self.side}' inesistente")

    # --- geometria -----------------------------------------------------------

    @property
    def extent(self) -> Tuple[float, float]:
        """Ingombro dopo la rotazione: a 90 e 270 larghezza e altezza si scambiano."""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """(x_min, y_min, x_max, y_max) in coordinate scheda."""
        w, h = self.extent
        return (self.x - w / 2, self.y - h / 2, self.x + w / 2, self.y + h / 2)

    def pin_position(self, pin: Pin) -> Tuple[float, float]:
        """La posizione assoluta di un pin, ruotato e specchiato come il pezzo.

        Il lato bottom specchia la X. E' la convenzione che rende un componente
        visto da sopra attraverso la scheda: cambiare lato senza specchiare
        produce piazzamenti che sembrano giusti e non saldano.
        """
        dx, dy = pin.dx, pin.dy
        if self.side == SIDE_BOTTOM:
            dx = -dx
        if self.rotation == 90:
            dx, dy = -dy, dx
        elif self.rotation == 180:
            dx, dy = -dx, -dy
        elif self.rotation == 270:
            dx, dy = dy, -dx
        return self.x + dx, self.y + dy

    def moved(self, x: float, y: float, rotation: int = None) -> "Component":
        return replace(self, x=x, y=y,
                       rotation=self.rotation if rotation is None else rotation)


@dataclass
class Net:
    """Un collegamento elettrico fra due o piu' pin."""

    name: str
    connections: Tuple[Tuple[str, str], ...]   # (designator, numero pin)
    net_class: str = CLASS_SIGNAL

    @property
    def weight(self) -> float:
        return CLASS_WEIGHT.get(self.net_class, 1.0)

    @property
    def degree(self) -> int:
        return len(self.connections)


@dataclass
class Board:
    """Contorno, pezzi e net. L'unita' su cui lavora tutto il modulo."""

    width: float
    height: float
    components: Dict[str, Component] = field(default_factory=dict)
    nets: List[Net] = field(default_factory=list)
    # Margine dal bordo in cui non si piazza: e' dove passa la fresa.
    edge_clearance: float = 1.0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise BoardError(f"contorno non valido {self.width}x{self.height} mm")

    # --- costruzione ---------------------------------------------------------

    def add(self, component: Component) -> Component:
        if component.designator in self.components:
            raise BoardError(f"designator duplicato: {component.designator}")
        self.components[component.designator] = component
        return component

    def with_components(self, placed: Iterable[Component]) -> "Board":
        """Una copia con i componenti sostituiti — gli algoritmi non mutano."""
        clone = Board(self.width, self.height, dict(self.components),
                      list(self.nets), self.edge_clearance)
        for component in placed:
            clone.components[component.designator] = component
        return clone

    @property
    def movable(self) -> List[Component]:
        return [c for c in self.components.values() if not c.locked]

    # --- misure --------------------------------------------------------------

    def pin_xy(self, designator: str, pin_number: str) -> Tuple[float, float]:
        component = self.components.get(designator)
        if component is None:
            raise BoardError(f"net riferita a '{designator}', che non e' sulla scheda")
        for pin in component.pins:
            if pin.number == pin_number:
                return component.pin_position(pin)
        # Un pin non dichiarato vale il centro del pezzo: peggiora la stima ma
        # non ferma un'ottimizzazione per un footprint importato male.
        return component.x, component.y

    def net_hpwl(self, net: Net) -> float:
        """Semiperimetro del rettangolo che racchiude la net.

        HPWL e' la stima di lunghezza che ogni piazzatore usa al posto del
        routing vero: sotto i tre o quattro pin coincide con l'albero minimo, e
        sopra resta monotona con quello. Sbaglia il valore assoluto, ordina bene
        i piazzamenti — che e' tutto cio' che serve a un ottimizzatore.
        """
        if net.degree < 2:
            return 0.0
        xs, ys = [], []
        for designator, pin_number in net.connections:
            x, y = self.pin_xy(designator, pin_number)
            xs.append(x)
            ys.append(y)
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    def total_hpwl(self, weighted: bool = True) -> float:
        return sum(self.net_hpwl(n) * (n.weight if weighted else 1.0)
                   for n in self.nets)

    def overlap_area(self, inflate: float = 0.0) -> float:
        """Area di sovrapposizione fra pezzi sullo stesso lato, in mm².

        `inflate` allarga ogni ingombro di quel tanto per lato prima del
        confronto. Con meta' della distanza minima di montaggio, due pezzi che
        si sfiorano risultano sovrapposti: e' il modo di dire a un costo che
        conosce solo le sovrapposizioni che anche «attaccati» e' un difetto.
        """
        total = 0.0
        items = list(self.components.values())
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if a.side != b.side:
                    continue
                total += _rect_overlap(_grow(a.bbox, inflate), _grow(b.bbox, inflate))
        return total

    def decoupling_pairs(self, prefix: str = "C") -> List[Tuple[str, str, str]]:
        """Le coppie (condensatore, integrato) da tenere vicine.

        Un condensatore conta come disaccoppiamento se tocca sia una net di
        alimentazione sia una di massa. L'integrato a cui appartiene e' il pezzo
        piu' grande che condivide quella stessa alimentazione — una scelta
        topologica, non geometrica, e quindi stabile mentre i pezzi si muovono.
        Accoppiarlo invece «al piu' vicino» darebbe a un ottimizzatore il modo
        di soddisfare il criterio spostando un integrato qualsiasi accanto al
        condensatore, che e' esattamente il contrario di cio' che si vuole.
        """
        power = {n.name for n in self.nets if n.net_class == CLASS_POWER}
        ground = {n.name for n in self.nets if n.net_class == CLASS_GROUND}
        if not power or not ground:
            return []

        nets_of: Dict[str, set] = {}
        for net in self.nets:
            for designator, _ in net.connections:
                nets_of.setdefault(designator, set()).add(net.name)

        pairs: List[Tuple[str, str, str]] = []
        for designator, component in sorted(self.components.items()):
            if not designator.upper().startswith(prefix.upper()):
                continue
            touched = nets_of.get(designator, set())
            rails = touched & power
            if not rails or not (touched & ground):
                continue
            candidates = [
                (other.width * other.height, name)
                for name, other in self.components.items()
                if name != designator
                and not name.upper().startswith(prefix.upper())
                and (nets_of.get(name, set()) & rails)
            ]
            if candidates:
                pairs.append((designator, max(candidates)[1], sorted(rails)[0]))
        return pairs

    def decoupling_distance(self, cap_name: str, ic_name: str, rail: str) -> float:
        """Lunghezza dell'anello fra un condensatore e il suo integrato.

        Si misura da pin a pin sulla stessa alimentazione, non da centro a
        centro. La distanza fra i centri dice quanto e' grande l'integrato: su
        un QFN da 10 mm nessun condensatore potrebbe mai scendere sotto i 5 mm,
        e un criterio fissato piu' in basso boccerebbe ogni piazzamento
        possibile — punendo il chip per le sue dimensioni invece di giudicare
        dove sta il condensatore. Fra i pin, invece, si misura cio' che conta
        davvero: il percorso che la corrente impulsiva deve fare, e quindi
        l'induttanza che vanifica o no il condensatore.
        """
        cap = self.components.get(cap_name)
        ic = self.components.get(ic_name)
        if cap is None or ic is None:
            return float("inf")

        cap_pins = [p for p in cap.pins if p.net == rail]
        ic_pins = [p for p in ic.pins if p.net == rail]
        if cap_pins and ic_pins:
            import math as _math
            return min(
                _math.dist(cap.pin_position(a), ic.pin_position(b))
                for a in cap_pins for b in ic_pins
            )
        # Senza le net sui pin resta lo spazio fra gli ingombri, che e' la
        # stessa grandezza a meno del percorso interno al package.
        gap = _rect_gap(cap.bbox, ic.bbox)
        return max(0.0, gap)

    def outside_area(self) -> float:
        """Area dei pezzi che sborda dal contorno utile, in mm²."""
        margin = self.edge_clearance
        usable = (margin, margin, self.width - margin, self.height - margin)
        total = 0.0
        for component in self.components.values():
            x0, y0, x1, y1 = component.bbox
            area = (x1 - x0) * (y1 - y0)
            total += area - _rect_overlap(component.bbox, usable)
        return max(0.0, total)

    def connected_designators(self, designator: str) -> List[str]:
        """I pezzi che condividono almeno una net con questo."""
        found = []
        for net in self.nets:
            names = [d for d, _ in net.connections]
            if designator in names:
                found.extend(n for n in names if n != designator)
        return sorted(set(found))


def _rect_gap(a: Sequence[float], b: Sequence[float]) -> float:
    """Distanza fra i bordi di due rettangoli; negativa se si compenetrano."""
    dx = max(a[0] - b[2], b[0] - a[2])
    dy = max(a[1] - b[3], b[1] - a[3])
    if dx >= 0 and dy >= 0:
        return (dx * dx + dy * dy) ** 0.5
    if dx >= 0:
        return dx
    if dy >= 0:
        return dy
    return -1.0


def _grow(box: Sequence[float], margin: float) -> Tuple[float, float, float, float]:
    """Un rettangolo allargato di `margin` per lato."""
    if margin <= 0:
        return (box[0], box[1], box[2], box[3])
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def _rect_overlap(a: Sequence[float], b: Sequence[float]) -> float:
    """Area comune a due rettangoli (x0, y0, x1, y1). Zero se non si toccano."""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    if dx <= 0 or dy <= 0:
        return 0.0
    return dx * dy
