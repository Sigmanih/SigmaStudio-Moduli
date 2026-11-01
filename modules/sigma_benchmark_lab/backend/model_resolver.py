# ==============================================================================
# core/modules/sigma_benchmark_lab/model_resolver.py
# Risoluzione dinamica del modello effettivo sottotraccia
# ==============================================================================
from __future__ import annotations

import os
from typing import Optional
from core.logger import get_logger

log = get_logger(__name__)

GENERIC_ALIASES = {
    "",
    "sigma",
    "sigmaengine",
    "sigma_engine",
    "test-model",
    "test_model",
    "proxy",
    "default",
    "auto",
    "local",
}


def resolve_underlying_model(model_name: Optional[str]) -> str:
    """Risolve il modello effettivo sottotraccia nel caso di proxy ('sigma', 'test-model', ecc.).

    Nessun report, storico o schermata deve mostrare 'sigma' o 'test-model' quando
    e' possibile risalire al modello effettivo che sta eseguendo o ha eseguito il test.
    """
    raw = (model_name or "").strip()
    cleaned = raw[6:].strip() if raw.startswith("sigma:") else raw

    # Se e' gia' un identificatore concreto (es. 'sigma:Qwen/Qwen3.8-27B' o 'gpt-4o'), usalo
    if cleaned and cleaned.lower() not in GENERIC_ALIASES:
        return raw

    # 1. Modello attualmente caricato e residente in VRAM (stato hardware reale)
    try:
        from core.engine.unified_runtime import sigma_engine
        if sigma_engine and getattr(sigma_engine, "has_resident_model", False) and sigma_engine.loaded_model_name:
            vram_m = sigma_engine.loaded_model_name.strip()
            if vram_m and vram_m.lower() not in GENERIC_ALIASES:
                return f"sigma:{vram_m}"
    except Exception as exc:
        log.debug("[model_resolver] VRAM inspection error: %s", exc)

    # 2. Modello target configurato nel file di configurazione AI (config.json)
    try:
        from core.ai_providers import load_ai_config
        cfg = load_ai_config()
        active_m = (
            cfg.get("model_proxy_target")
            or cfg.get("active_model")
            or cfg.get("model")
            or ""
        ).strip()
        if active_m and active_m.lower() not in GENERIC_ALIASES:
            if not (active_m.startswith("sigma:") or "/" in active_m or active_m.startswith("ollama:")):
                return f"sigma:{active_m}"
            return active_m if active_m.startswith("sigma:") else f"sigma:{active_m}"
    except Exception as exc:
        log.debug("[model_resolver] AI config error: %s", exc)

    # 3. Modello locale presente fisicamente su disco
    try:
        from core.model_paths import list_model_dirs
        dirs = list_model_dirs()
        if dirs:
            first_dir = os.path.basename(dirs[0].rstrip(os.sep + "/"))
            if first_dir and first_dir.lower() not in GENERIC_ALIASES:
                return f"sigma:{first_dir}"
    except Exception as exc:
        log.debug("[model_resolver] local dirs error: %s", exc)

    # Ripiego estremo se la macchina non ha alcun modello installato
    return "sigma:native-engine"


def clean_model_display_name(model_name: Optional[str]) -> str:
    """Restituisce un'etichetta pulita senza prefissi tecnici per visualizzazione nella UI."""
    resolved = resolve_underlying_model(model_name)
    if resolved.startswith("sigma:"):
        return resolved[6:]
    return resolved
