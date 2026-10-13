# ==============================================================================
# core/modules/sigma_benchmark_lab/protocol/__init__.py — Package Protocol Bench
# Sigma Studio v8 — Benchmark Aderenza Protocollo Tool in Sandbox
# ==============================================================================
"""Package per la valutazione dell'aderenza dei modelli al protocollo dei tool.

Tutto il processo di misurazione risiede all'interno del modulo di benchmark ed
esegue ogni test dentro una SandboxJail isolata per impedire modifiche al kernel.
"""

from core.modules.sigma_benchmark_lab.protocol.sandbox import (
    SandboxJail,
    SandboxJailError,
    pulisci,
    _prepara,
)
from core.modules.sigma_benchmark_lab.protocol.scenarios import (
    SCENARI,
    Scenario,
    _controlla_json,
    _controlla_contiene,
    _controlla_non_contiene,
)
from core.modules.sigma_benchmark_lab.protocol.evaluator import (
    EsitoScenario,
    Prova,
    Traccia,
    osserva,
    prova_arriva_in_fondo,
    prova_chiude_con_prove,
    prova_legge_prima_di_modificare,
    prova_niente_segnaposto,
    prova_nomi_veri,
    prova_non_scrive_da_terminale,
    prova_non_riscrive_la_prova,
    prova_si_corregge_da_solo,
    prova_verifica_la_premessa,
    prova_reagisce_al_rifiuto,
    prova_rispetto_sandbox,
    prova_spec_per_prima,
    prova_verifica_prima_di_chiudere,
    SEGNAPOSTO_DEL_PROMPT,
    SCRITTURA_INLINE,
)
from core.modules.sigma_benchmark_lab.protocol.engine import esegui, esegui_scenario

__all__ = [
    "SandboxJail",
    "SandboxJailError",
    "pulisci",
    "_prepara",
    "SCENARI",
    "Scenario",
    "EsitoScenario",
    "Prova",
    "Traccia",
    "osserva",
    "esegui",
    "esegui_scenario",
    "SEGNAPOSTO_DEL_PROMPT",
    "SCRITTURA_INLINE",
    "_controlla_json",
    "_controlla_contiene",
    "_controlla_non_contiene",
    "prova_arriva_in_fondo",
    "prova_chiude_con_prove",
    "prova_legge_prima_di_modificare",
    "prova_niente_segnaposto",
    "prova_nomi_veri",
    "prova_non_scrive_da_terminale",
    "prova_non_riscrive_la_prova",
    "prova_si_corregge_da_solo",
    "prova_verifica_la_premessa",
    "prova_reagisce_al_rifiuto",
    "prova_rispetto_sandbox",
    "prova_spec_per_prima",
    "prova_verifica_prima_di_chiudere",
]
