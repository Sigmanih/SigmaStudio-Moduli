# ==============================================================================
# sigma_eda_lab/placement.py — Dove vanno i pezzi
# ==============================================================================
"""Ricottura simulata sul piazzamento dei componenti.

Il piazzamento e' il punto in cui si decide la qualita' di una scheda. Un
autorouter lavora su cio' che trova: se i pezzi sono messi male nessuna
strategia di routing recupera, e le piste lunghe che ne escono sono un problema
di piazzamento travestito da problema di routing. EasyEDA non piazza — sa
spostare un componente se gli si dice dove — quindi il *dove* va calcolato qui.

Il metodo e' ricottura simulata, che e' quello che usano i piazzatori veri e per
la stessa ragione: la funzione di costo e' piena di minimi locali, e una discesa
che non accetta mai un peggioramento ci si siede dentro al primo. La ricottura
all'inizio accetta quasi tutto, e via via si irrigidisce.

Tre cose la rendono utilizzabile invece che soltanto corretta:

* **e' deterministica** — stesso seme, stessa scheda. Un piazzatore che dia
  risultati diversi a ogni giro non e' verificabile, e una differenza fra due
  esecuzioni non si potrebbe attribuire a niente.
* **rispetta `locked`** — i connettori sul bordo e i fori di fissaggio stanno
  dove qualcuno li ha messi, e l'ottimizzatore ci gira intorno.
* **non peggiora mai** — restituisce il piazzamento di partenza se non e'
  riuscita a batterlo.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .netlist import Board, Component, ROTATIONS

# Pesi del costo. La sovrapposizione domina di due ordini di grandezza: un
# millimetro quadro di pezzi impilati non vale nessuna lunghezza di pista
# risparmiata, perche' e' una scheda che non si puo' montare.
W_WIRE = 1.0
W_OVERLAP = 250.0
W_OUTSIDE = 500.0
W_DECOUPLING = 12.0

# Meta' della distanza minima di montaggio: due ingombri allargati di tanto si
# sovrappongono esattamente quando i pezzi veri sono troppo vicini. Senza questo
# il costo conosce solo le sovrapposizioni vere, e impacchetta i pezzi a
# contatto — un piazzamento che il valutatore poi boccia, con il costo convinto
# di aver fatto il suo lavoro.
COURTYARD_MARGIN = 0.125

# Lunghezza d'anello, da pin a pin, oltre la quale un condensatore di
# disaccoppiamento smette di disaccoppiare. Sotto, avvicinarlo ancora non serve
# a niente, quindi il costo non paga per farlo.
DECOUPLING_TARGET_MM = 2.0


@dataclass
class PlacementResult:
    """Cosa e' stato deciso, e quanto e' migliorato."""

    board: Board
    cost_before: float
    cost_after: float
    hpwl_before: float
    hpwl_after: float
    overlap_before: float
    overlap_after: float
    iterations: int
    accepted: int
    seed: int
    decoupling_pairs: int = 0
    moved: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def improvement_pct(self) -> float:
        if self.cost_before <= 0:
            return 0.0
        return round(100.0 * (self.cost_before - self.cost_after) / self.cost_before, 2)

    def summary(self) -> Dict[str, Any]:
        return {
            "cost_before": round(self.cost_before, 3),
            "cost_after": round(self.cost_after, 3),
            "improvement_pct": self.improvement_pct,
            "hpwl_before_mm": round(self.hpwl_before, 3),
            "hpwl_after_mm": round(self.hpwl_after, 3),
            "overlap_before_mm2": round(self.overlap_before, 3),
            "overlap_after_mm2": round(self.overlap_after, 3),
            "iterations": self.iterations,
            "accepted": self.accepted,
            "seed": self.seed,
            "decoupling_pairs": self.decoupling_pairs,
            "components_moved": len(self.moved),
        }


def cost(board: Board,
         decoupling: Optional[List[Tuple[str, str, str]]] = None) -> float:
    """Quanto e' cattivo questo piazzamento. Piu' basso e' meglio.

    I quattro termini sono le quattro cose che `evaluate` poi controlla. Tenerli
    allineati non e' eleganza: un costo che ignora un criterio produce schede
    che lo violano, e l'ottimizzatore le consegna convinto di aver migliorato.

    `decoupling` si passa gia' calcolato dal chiamante perche' dipende solo
    dalle net, che durante la ricottura non cambiano: ricavarlo a ogni
    iterazione sarebbe il costo dominante del ciclo.
    """
    if decoupling is None:
        decoupling = board.decoupling_pairs()
    return (W_WIRE * board.total_hpwl()
            + W_OVERLAP * board.overlap_area(inflate=COURTYARD_MARGIN)
            + W_OUTSIDE * board.outside_area()
            + W_DECOUPLING * _decoupling_penalty(board, decoupling))


def _decoupling_penalty(board: Board, pairs: List[Tuple[str, str, str]]) -> float:
    """Millimetri di anello in eccesso, sommati su tutte le coppie."""
    total = 0.0
    for cap_name, ic_name, rail in pairs:
        distance = board.decoupling_distance(cap_name, ic_name, rail)
        if distance != float("inf") and distance > DECOUPLING_TARGET_MM:
            total += distance - DECOUPLING_TARGET_MM
    return total


def optimize(board: Board, iterations: int = 4000, seed: int = 20260920,
             start_temp: Optional[float] = None,
             end_temp: float = 0.01) -> PlacementResult:
    """Cerca un piazzamento migliore di quello che riceve.

    `iterations` e' il bilancio fra tempo e qualita': qualche migliaio basta per
    le decine di pezzi di una scheda normale, e oltre il guadagno si appiattisce
    mentre il tempo no.
    """
    decoupling = board.decoupling_pairs()
    movable = board.movable
    if not movable:
        base = cost(board, decoupling)
        return PlacementResult(board, base, base, board.total_hpwl(),
                               board.total_hpwl(), board.overlap_area(),
                               board.overlap_area(), 0, 0, seed)

    rng = random.Random(seed)
    current = board.with_components([])
    current_cost = cost(current, decoupling)

    best = current
    best_cost = current_cost

    cost_before = current_cost
    hpwl_before = board.total_hpwl()
    overlap_before = board.overlap_area()

    # La temperatura iniziale si tara sulla scheda invece di essere una
    # costante: su una scheda grande le stesse mosse costano di piu', e una
    # temperatura fissa accetterebbe tutto o niente a seconda delle dimensioni.
    if start_temp is None:
        start_temp = max(1.0, current_cost / max(1, len(movable)) * 0.5)

    decay = (end_temp / start_temp) ** (1.0 / max(1, iterations))
    temperature = start_temp
    accepted = 0

    for step in range(iterations):
        candidate = _neighbour(current, rng, temperature, start_temp)
        if candidate is None:
            temperature *= decay
            continue

        candidate_cost = cost(candidate, decoupling)
        delta = candidate_cost - current_cost

        if delta <= 0 or rng.random() < math.exp(-delta / max(temperature, 1e-9)):
            current, current_cost = candidate, candidate_cost
            accepted += 1
            if current_cost < best_cost:
                best, best_cost = current, current_cost

        temperature *= decay

    # Non si consegna mai un peggioramento: se la ricerca e' andata male, la
    # scheda di partenza era la risposta.
    if best_cost >= cost_before:
        best, best_cost = board, cost_before

    return PlacementResult(
        board=best,
        cost_before=cost_before,
        cost_after=best_cost,
        hpwl_before=hpwl_before,
        hpwl_after=best.total_hpwl(),
        overlap_before=overlap_before,
        overlap_after=best.overlap_area(),
        decoupling_pairs=len(decoupling),
        iterations=iterations,
        accepted=accepted,
        seed=seed,
        moved=_diff(board, best),
    )


def _neighbour(board: Board, rng: random.Random, temperature: float,
               start_temp: float) -> Optional[Board]:
    """Una scheda vicina a questa: un pezzo spostato, girato o scambiato.

    Il passo di spostamento si restringe con la temperatura. All'inizio i pezzi
    attraversano la scheda, alla fine si assestano di frazioni di millimetro:
    e' la differenza fra cercare una disposizione e rifinirla.
    """
    movable = board.movable
    if not movable:
        return None

    roll = rng.random()
    if roll < 0.70:
        return _translate(board, rng, temperature, start_temp)
    if roll < 0.88:
        return _rotate(board, rng)
    return _swap(board, rng)


def _translate(board: Board, rng: random.Random, temperature: float,
               start_temp: float) -> Board:
    component = rng.choice(board.movable)
    scale = max(0.05, (temperature / start_temp)) * max(board.width, board.height) * 0.25
    x = component.x + rng.gauss(0.0, scale)
    y = component.y + rng.gauss(0.0, scale)

    # Si resta dentro il contorno utile: proporre pezzi fuori scheda spreca
    # iterazioni su candidati che la penalita' rifiutera' comunque.
    w, h = component.extent
    margin = board.edge_clearance
    x = _clamp(x, margin + w / 2, board.width - margin - w / 2)
    y = _clamp(y, margin + h / 2, board.height - margin - h / 2)
    return board.with_components([component.moved(x, y)])


def _rotate(board: Board, rng: random.Random) -> Board:
    component = rng.choice(board.movable)
    rotation = rng.choice([r for r in ROTATIONS if r != component.rotation])
    return board.with_components([component.moved(component.x, component.y, rotation)])


def _swap(board: Board, rng: random.Random) -> Optional[Board]:
    """Scambia due pezzi di ingombro simile.

    Lo scambio e' la mossa che lo spostamento non sa fare: due condensatori di
    disaccoppiamento finiti ciascuno accanto all'integrato sbagliato sono a un
    solo scambio dalla disposizione giusta, e a molte traslazioni sfortunate.
    """
    movable = board.movable
    if len(movable) < 2:
        return None
    a = rng.choice(movable)
    similar = [c for c in movable
               if c.designator != a.designator
               and abs(c.width - a.width) < 1.0
               and abs(c.height - a.height) < 1.0]
    if not similar:
        return None
    b = rng.choice(similar)
    return board.with_components([
        a.moved(b.x, b.y, b.rotation),
        b.moved(a.x, a.y, a.rotation),
    ])


def seed_grid(board: Board, spacing: float = 2.0, seed: int = 20260920) -> Board:
    """Un piazzamento iniziale ordinato, per quando non ce n'e' uno.

    La ricottura parte meglio da una griglia che da un mucchio: se tutti i pezzi
    arrivano sovrapposti nell'origine, le prime migliaia di iterazioni le spende
    solo a separarli.
    """
    movable = sorted(board.movable, key=lambda c: (-c.width * c.height, c.designator))
    if not movable:
        return board

    margin = board.edge_clearance
    cursor_x = margin
    cursor_y = margin
    row_height = 0.0
    placed = []

    for component in movable:
        w, h = component.extent
        if cursor_x + w > board.width - margin and placed:
            cursor_x = margin
            cursor_y += row_height + spacing
            row_height = 0.0
        placed.append(component.moved(cursor_x + w / 2, cursor_y + h / 2))
        cursor_x += w + spacing
        row_height = max(row_height, h)

    return board.with_components(placed)


def _diff(before: Board, after: Board) -> List[Dict[str, Any]]:
    """I pezzi che si sono davvero mossi, con di quanto."""
    moved = []
    for designator, new in after.components.items():
        old = before.components.get(designator)
        if old is None:
            continue
        dx, dy = new.x - old.x, new.y - old.y
        if abs(dx) < 1e-6 and abs(dy) < 1e-6 and new.rotation == old.rotation:
            continue
        moved.append({
            "designator": designator,
            "from": {"x": round(old.x, 4), "y": round(old.y, 4),
                     "rotation": old.rotation},
            "to": {"x": round(new.x, 4), "y": round(new.y, 4),
                   "rotation": new.rotation},
            "distance_mm": round(math.hypot(dx, dy), 4),
        })
    return sorted(moved, key=lambda m: -m["distance_mm"])


def _clamp(value: float, low: float, high: float) -> float:
    if low > high:          # pezzo piu' largo del contorno utile: si centra
        return (low + high) / 2
    return max(low, min(high, value))
