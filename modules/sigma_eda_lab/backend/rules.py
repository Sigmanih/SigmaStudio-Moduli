# ==============================================================================
# sigma_eda_lab/rules.py — Dimensionamento delle piste (IPC-2221)
# ==============================================================================
"""Quanto deve essere larga una pista per portare una corrente.

E' l'unico calcolo del modulo che produce un numero con un'unita' fisica, e per
questo e' l'unico che va tenuto separato e verificabile. La formula e' quella
di IPC-2221, che lega la sezione di rame alla corrente e al riscaldamento che
si accetta:

    A = ( I / (k · ΔT^b) ) ^ (1/c)

con A in mil quadri, I in ampere, ΔT in gradi centigradi sopra l'ambiente, e le
tre costanti che distinguono uno strato esterno — che si raffredda nell'aria —
da uno interno, sepolto nel laminato:

    k = 0.048 esterno, 0.024 interno      b = 0.44      c = 0.725

La larghezza esce dalla sezione una volta nota la quantita' di rame: un'oncia
per piede quadro sono 1.378 mil di spessore.

Il limite dichiarato della tabella IPC e' 35 A, 400 mil, 10 oz e ΔT 100 °C;
fuori da li' la formula continua a dare un numero, e quel numero non e' piu'
sostenuto da niente. `trace_width` si rifiuta di restituirlo.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict

MIL_PER_MM = 39.3701
OZ_TO_MIL = 1.378            # spessore di 1 oz/ft² di rame, in mil

_K_EXTERNAL = 0.048
_K_INTERNAL = 0.024
_B = 0.44
_C = 0.725

# I confini oltre cui IPC-2221 non si pronuncia piu'.
MAX_CURRENT_A = 35.0
MAX_DELTA_T_C = 100.0
MAX_THICKNESS_OZ = 10.0


class RuleError(ValueError):
    """Il dimensionamento e' stato chiesto fuori dal dominio della formula."""


@dataclass(frozen=True)
class TraceWidth:
    """Il risultato del dimensionamento, con dentro cio' che lo ha prodotto."""

    current_a: float
    delta_t_c: float
    thickness_oz: float
    layer: str
    cross_section_mil2: float
    width_mil: float
    width_mm: float
    standard: str = "IPC-2221"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def trace_width(current_a: float, delta_t_c: float = 10.0,
                thickness_oz: float = 1.0, layer: str = "external") -> TraceWidth:
    """La larghezza minima di una pista per `current_a` ampere.

    `delta_t_c` e' il riscaldamento accettato sopra l'ambiente: 10 °C e' la
    scelta prudente di chi non sa ancora quanto scalda il resto della scheda,
    20 °C e' comune su schede ventilate. Il valore predefinito resta il primo,
    perche' una pista troppo larga costa spazio e una troppo stretta costa la
    scheda.

    `layer` distingue lo strato esterno dall'interno: a parita' di corrente una
    pista interna deve essere circa il doppio, e scambiare i due e' l'errore
    che si scopre quando il prototipo scotta.
    """
    if current_a <= 0:
        raise RuleError("la corrente deve essere positiva")
    if delta_t_c <= 0:
        raise RuleError("il riscaldamento ammesso deve essere positivo")
    if thickness_oz <= 0:
        raise RuleError("lo spessore del rame deve essere positivo")
    if layer not in ("external", "internal"):
        raise RuleError(f"strato '{layer}' sconosciuto: usa 'external' o 'internal'")

    if current_a > MAX_CURRENT_A:
        raise RuleError(
            f"{current_a} A supera il limite di {MAX_CURRENT_A} A della tabella "
            "IPC-2221: a queste correnti si dimensiona con barre, piani o rame "
            "spesso, non estrapolando questa formula."
        )
    if delta_t_c > MAX_DELTA_T_C:
        raise RuleError(f"ΔT {delta_t_c} °C supera i {MAX_DELTA_T_C} °C tabellati")
    if thickness_oz > MAX_THICKNESS_OZ:
        raise RuleError(f"{thickness_oz} oz supera i {MAX_THICKNESS_OZ} oz tabellati")

    k = _K_EXTERNAL if layer == "external" else _K_INTERNAL
    area_mil2 = (current_a / (k * delta_t_c ** _B)) ** (1.0 / _C)
    width_mil = area_mil2 / (thickness_oz * OZ_TO_MIL)

    return TraceWidth(
        current_a=current_a,
        delta_t_c=delta_t_c,
        thickness_oz=thickness_oz,
        layer=layer,
        cross_section_mil2=round(area_mil2, 3),
        width_mil=round(width_mil, 3),
        width_mm=round(width_mil / MIL_PER_MM, 4),
    )


def current_capacity(width_mm: float, delta_t_c: float = 10.0,
                     thickness_oz: float = 1.0,
                     layer: str = "external") -> float:
    """La corrente che una pista larga cosi' regge — `trace_width` al contrario.

    Serve per giudicare una scheda che esiste gia': si misura la pista e si
    guarda se regge cio' che le passa dentro, invece di ridisegnarla.
    """
    if width_mm <= 0:
        raise RuleError("la larghezza deve essere positiva")
    k = _K_EXTERNAL if layer == "external" else _K_INTERNAL
    area_mil2 = (width_mm * MIL_PER_MM) * (thickness_oz * OZ_TO_MIL)
    return round(k * (delta_t_c ** _B) * (area_mil2 ** _C), 4)


def suggest_width_mm(current_a: float, layer: str = "external",
                     thickness_oz: float = 1.0, margin: float = 1.5) -> float:
    """Larghezza consigliata: il minimo IPC piu' un margine, arrotondato in su.

    Il margine copre cio' che la formula non sa — una piazzola che strozza la
    pista, un via sottodimensionato, l'incisione che toglie rame ai bordi. Il
    valore di serie e' 1.5, e chi ha misurato la propria scheda lo abbassa.
    """
    if margin < 1.0:
        raise RuleError("un margine sotto 1.0 assottiglia la pista, non la protegge")
    base = trace_width(current_a, thickness_oz=thickness_oz, layer=layer).width_mm
    # Al centesimo di millimetro: sotto quella soglia nessun fabbricante
    # distingue, e un numero con cinque decimali finge una precisione che non c'e'.
    return round(_ceil_to(base * margin, 0.01), 2)


def _ceil_to(value: float, step: float) -> float:
    steps = value / step
    rounded = int(steps)
    if steps - rounded > 1e-9:
        rounded += 1
    return rounded * step
