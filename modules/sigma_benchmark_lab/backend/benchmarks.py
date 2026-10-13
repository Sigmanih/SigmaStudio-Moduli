# ==============================================================================
# core/training/benchmarks.py — Official Model Benchmark & Evaluation Engine
# Sigma Studio v7 — Training Lab Sub-package
# ==============================================================================
"""Motore di valutazione sui benchmark ufficiali:

1. MMLU (Massive Multitask Language Understanding — 57 materie)
2. MMLU-Pro (scelta multipla ad alto ragionamento, fino a 10 opzioni)
3. GSM8K (Grade School Math 8K)
4. MATH (matematica olimpica / competizioni)
5. HumanEval (completamento ed esecuzione di codice Python)
6. MBPP (Mostly Basic Python Problems)
7. ARC (AI2 Reasoning Challenge — scienze)
8. HellaSwag (buon senso)
9. TruthfulQA (allucinazioni e veridicita')
10. GPQA (domande di livello specialistico)
11. BIG-Bench Hard (BBH — ragionamento multi-step, 27 task)

Modalita' dataset integrale, seed deterministico (42), temperatura 0.0 e
certificato di riproducibilita' SHA-256.

Il giudizio di ogni risposta sta in `core.training.answer_parser`: una risposta
che contiene piu' scelte in conflitto, o nessuna scelta riconoscibile, non e' un
errore del modello ma un esito **da valutare a parte**, e viene contata nella
coda di revisione invece di finire fra i fallimenti.
"""

import datetime
import traceback
from collections import OrderedDict
import hashlib
import random
import json
import os
import re
import threading
import time
import uuid

import requests

from core import paths
from core.engine.evaluation import (
    STOP_CODE, STOP_MATH, STOP_MULTIPLE_CHOICE, STOP_SHORT_ANSWER,
)
from core.modules.sigma_benchmark_lab.protocols import (
    MODE_CODE, MODE_CONTINUATION, MODE_COT, MODE_LETTER,
    describe as protocol_describe, protocol_for, resolve_protocol,
)
from core.logger import get_logger
from core.modules.sigma_benchmark_lab import paths as module_paths
from core.modules.sigma_benchmark_lab import benchmark_store as store
from core.modules.sigma_benchmark_lab.answer_parser import (
    REVIEW_VERDICTS, VERDICT_AMBIGUOUS, VERDICT_ERROR, VERDICT_FAIL,
    VERDICT_PASS, VERDICT_UNPARSABLE,
    extract_chosen_letter, grade_answer, grade_code_result,
)

log = get_logger(__name__)

# Ancorati alla radice dell'installazione, non alla directory da cui si lancia
# il server. Con un percorso relativo `_is_cached` rispondeva "no" ogni volta
# che il processo partiva da un'altra cartella, e la preparazione riscaricava
# per intero undici dataset per tenerne cento quesiti — senza un errore, perche'
# `makedirs` creava allegramente l'albero vuoto accanto. E' lo stesso incidente
# documentato in `sigma_training_lab/paths.py`, che esiste apposta.
BENCHMARKS_FILE = str(module_paths.OFFICIAL_BENCHMARK_FILE)
BENCHMARK_CACHE_DIR = str(module_paths.TRAINING_LAB_DIR / "benchmark_cache")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

_benchmark_lock = threading.RLock()
_cancel_requested: set[str] = set()   # job in attesa di annullamento
_pause_requested: set[str] = set()    # job in attesa di pausa
_active_threads: dict[str, threading.Thread] = {}  # job_id -> thread worker

#: Ogni quanti quesiti versare il buffer degli esiti su disco (immediato per streaming live).
_FLUSH_EVERY = 1
#: Intervallo minimo fra due scritture dell'indice job durante un run.
_PROGRESS_INTERVAL_SEC = 0.1
#: Quanti quesiti consegnare al motore locale per volta. Non e' la dimensione
#: del lotto — quella la decide il motore dalla memoria libera — ma quanti
#: quesiti restano in volo prima che il progresso, la pausa e l'annullamento
#: tornino a essere osservabili. Un run che non si puo' fermare per dieci
#: minuti e' un run che l'utente spegne dal task manager.
_SIGMA_CHUNK = 64
#: Lo stesso, per i quesiti da scrivere. Piu' piccolo perche' costano molto di
#: piu': un quesito di matematica con mille token di budget su un GGUF servito
#: da llama.cpp — che decodifica una sequenza alla volta — puo' durare minuti,
#: e la pausa va vista prima della fine della coda, non dopo.
_WRITTEN_CHUNK = 8

# `extract_chosen_letter` resta importato per i chiamanti storici e per i test.
__all__ = [
    "get_available_models_for_benchmark", "get_suite_info", "get_benchmark_items",
    "download_suite", "start_benchmark_run", "extend_benchmark_job", "rerun_suite_job", "list_benchmark_jobs", "get_job_detail",
    "pause_benchmark_job", "resume_benchmark_job", "cancel_benchmark_job",
    "delete_benchmark_job", "extract_chosen_letter", "OFFICIAL_BENCHMARKS_INFO",
    "audit_benchmark_job",
]


class ModelUnavailable(Exception):
    def __init__(self, message: str = "", diagnosis: str = ""):
        super().__init__(message)
        self.diagnosis = diagnosis


def _raise_if_unavailable(outcomes: list) -> None:
    """Solleva ModelUnavailable se un esito segnala un errore fatale o modello non disponibile."""
    if not outcomes:
        return
    for item in outcomes:
        if isinstance(item, dict) and item.get("fatal"):
            raise ModelUnavailable(
                str(item.get("error") or "Modello non disponibile"),
                str(item.get("diagnosis") or "")
            )
        elif hasattr(item, "fatal") and getattr(item, "fatal", False):
            raise ModelUnavailable(
                str(getattr(item, "error", "") or "Modello non disponibile"),
                str(getattr(item, "diagnosis", "") or "")
            )


# ==============================================================================
# INDICE DEI JOB (solo metadati e metriche: il dettaglio sta in benchmark_store)
# ==============================================================================

def _ensure_dir():
    os.makedirs(module_paths.TRAINING_LAB_DIR, exist_ok=True)
    if not os.path.exists(BENCHMARKS_FILE):
        with open(BENCHMARKS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def _load_benchmarks() -> list[dict]:
    _ensure_dir()
    with _benchmark_lock:
        try:
            with open(BENCHMARKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []

        changed = False
        from core.modules.sigma_benchmark_lab.model_resolver import resolve_underlying_model, GENERIC_ALIASES
        for job in data:
            current_m = str(job.get("model", "")).strip()
            if not current_m or current_m.lower() in GENERIC_ALIASES or current_m.lower() in ("sigma", "test-model"):
                job["model"] = resolve_underlying_model(current_m)
                changed = True
            # I run salvati col vecchio schema portano il dettaglio inline: va
            # spostato nello store, altrimenti ogni polling rispedisce megabyte.
            if store.migrate_inline_results(job):
                changed = True
            if job.get("status") in ("running", "executing"):
                jid = job.get("id", "")
                thread = _active_threads.get(jid)
                if thread is None or not thread.is_alive():
                    job["status"] = "interrupted"
                    job["updated_at"] = datetime.datetime.now().isoformat()
                    changed = True
                    log.warning("Job benchmark %s risultava in corso senza worker: marcato 'interrupted'.", jid)
        if changed:
            _save_benchmarks(data)
        return data


def _save_benchmarks(benchmarks: list[dict]):
    _ensure_dir()
    with _benchmark_lock:
        tmp = f"{BENCHMARKS_FILE}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(benchmarks, f, indent=2, ensure_ascii=False)

            # Retry loop per Windows NTFS (WinError 5 durante lettura concorrente o antivirus)
            replaced = False
            last_err = None
            for attempt in range(12):
                try:
                    os.replace(tmp, BENCHMARKS_FILE)
                    replaced = True
                    break
                except PermissionError as err:
                    last_err = err
                    time.sleep(0.04 * (attempt + 1))

            if not replaced:
                # Fallback su Windows: scrittura diretta se os.replace è bloccato dal filesystem
                log.warning("os.replace su %s fallito (%s), applico fallback di scrittura diretta.", BENCHMARKS_FILE, last_err)
                with open(BENCHMARKS_FILE, "w", encoding="utf-8") as f:
                    json.dump(benchmarks, f, indent=2, ensure_ascii=False)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass


def _update_job_state(job_id: str, updates: dict):
    """Fonde `updates` nel job indicato, unendo metriche e riproducibilita'."""
    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        for job in benchmarks:
            if job.get("id") == job_id:
                nested = {k: updates[k] for k in ("metrics", "reproducibility") if k in updates}
                job.update({k: v for k, v in updates.items() if k not in nested})
                for key, value in nested.items():
                    if isinstance(value, dict):
                        job.setdefault(key, {}).update(value)
                    else:
                        job[key] = value
                break
        _save_benchmarks(benchmarks)


# ==============================================================================
# MODELLI DISPONIBILI
# ==============================================================================

#: Famiglie che non generano testo: valutarle produce solo errori HTTP.
_NON_GENERATIVE_HINTS = ("embed", "embedding", "bge-", "gte-", "e5-", "reranker", "rerank",
                         "nomic-embed", "mxbai-embed", "all-minilm")


def _is_generative(name: str, details: dict) -> bool:
    lowered = (name or "").lower()
    if any(hint in lowered for hint in _NON_GENERATIVE_HINTS):
        return False
    return (details or {}).get("family", "").lower() not in ("bert", "nomic-bert")


def _param_size(details: dict) -> str:
    return (details or {}).get("parameter_size", "") or ""


def get_available_models_for_benchmark() -> list[dict]:
    """Modelli disponibili per la valutazione benchmark (SigmaEngine, Ollama, LM Studio, Cloud API)."""
    models: list[dict] = []
    seen_ids: set[str] = set()

    # 1. ⚡ SIGMAENGINE (Modelli Locali GGUF + Proxy 'sigma' + Residente in VRAM)
    try:
        # Proxy "sigma" risolto con il modello sottostante reale
        from core.modules.sigma_benchmark_lab.model_resolver import resolve_underlying_model, clean_model_display_name
        underlying = resolve_underlying_model("sigma")
        underlying_clean = clean_model_display_name(underlying)
        proxy_title = f"SigmaEngine ({underlying_clean})" if underlying_clean else 'SigmaEngine (Proxy "sigma")'
        models.append({
            "id": "sigma",
            "name": proxy_title,
            "resolved_target": underlying,
            "provider": "SigmaEngine",
            "provider_label": "⚡ SigmaEngine",
            "provider_key": "sigma_engine",
            "badge": "⚡ PROXY",
            "family": "SigmaEngine",
            "is_proxy": True,
            "is_active": True,
            "category": "sigma_engine",
            "parameter_size": "Hardware Autotune",
            "quantization": "Native/FlashAttn",
            "details": {
                "type": "proxy",
                "description": f"Modello sottostante attivo: {underlying_clean or underlying}"
            }
        })
        seen_ids.add("sigma")

        # Modello residente in VRAM (se noto)
        try:
            from core.engine.unified_runtime import sigma_engine
            if sigma_engine and getattr(sigma_engine, "loaded_model_name", None):
                vram_name = sigma_engine.loaded_model_name
                mid = f"sigma:{vram_name}"
                if mid not in seen_ids:
                    models.append({
                        "id": mid,
                        "name": f"In VRAM ({vram_name})",
                        "provider": "SigmaEngine",
                        "provider_label": "⚡ SigmaEngine",
                        "provider_key": "sigma_engine",
                        "badge": "⚡ IN VRAM",
                        "family": "VRAM",
                        "category": "sigma_engine",
                        "parameter_size": "Resident",
                        "quantization": "Loaded",
                        "is_active": True,
                        "details": {"type": "vram", "description": "Attualmente caricato in memoria"}
                    })
                    seen_ids.add(mid)
        except Exception:
            pass

        # Ispezione modelli locali SigmaEngine (GGUF, Safetensors, ecc.)
        try:
            from core.modules.sigma_model_hub.backend.model_inventory import scan_local_models
            local_models = scan_local_models()
            for lm in local_models:
                m_name = lm.get("model_id") or lm.get("display_name") or lm.get("filename") or lm.get("name") or lm.get("id")
                if not m_name:
                    continue
                mid = f"sigma:{m_name}"
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                fmt = (lm.get("format") or "GGUF").upper()
                badge = "⚡ GGUF" if "GGUF" in fmt else ("⚡ SAFETENSORS" if "SAFETENSORS" in fmt else "⚡ LOCALE")
                size_gb = lm.get("size_gb")
                size_str = f"{size_gb} GB" if size_gb else (lm.get("size_label") or "")
                param_label = lm.get("params_label") or lm.get("parameter_size") or ""
                models.append({
                    "id": mid,
                    "name": m_name,
                    "provider": "SigmaEngine (Locale)",
                    "provider_label": "⚡ SigmaEngine (Locale)",
                    "provider_key": "sigma_engine",
                    "badge": badge,
                    "family": lm.get("architecture") or lm.get("format_tag") or "Locale",
                    "parameter_size": param_label,
                    "size_gb": size_gb,
                    "size_label": size_str,
                    "quantization": lm.get("quantization") or "Standard",
                    "category": "sigma_engine",
                    "details": lm,
                    "is_active": True,
                })
        except Exception as err:
            log.debug("Scansione modelli locali per benchmark: %s", err)
    except Exception as err:
        log.warning("Errore caricamento modelli SigmaEngine per benchmark: %s", err)

    # 2. 🐙 OLLAMA
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=0.5)
        if res.status_code == 200:
            for m in res.json().get("models", []):
                name = m.get("name", "")
                if not name:
                    continue
                mid = f"ollama:{name}"
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                details = m.get("details", {}) or {}
                if not _is_generative(name, details):
                    continue
                size_gb = round(m.get("size", 0) / (1024 ** 3), 2)
                models.append({
                    "id": mid,
                    "name": name,
                    "provider": "Ollama",
                    "provider_label": "🐙 Ollama",
                    "provider_key": "ollama",
                    "badge": "🐙 OLLAMA",
                    "size_gb": size_gb,
                    "family": details.get("family", "") or "",
                    "parameter_size": _param_size(details),
                    "quantization": details.get("quantization_level", "") or "",
                    "category": "ollama",
                    "details": details,
                    "is_active": True,
                })
    except Exception as err:
        log.debug("Elenco modelli Ollama non disponibile: %s", err)

    # 3. 💻 LM STUDIO & LOCALI
    try:
        res = requests.get("http://127.0.0.1:1234/v1/models", timeout=0.5)
        if res.status_code == 200:
            for m in res.json().get("data", []):
                mid_raw = m.get("id") or m.get("name")
                if not mid_raw:
                    continue
                mid = f"lmstudio:{mid_raw}"
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                models.append({
                    "id": mid,
                    "name": mid_raw,
                    "provider": "LM Studio",
                    "provider_label": "💻 LM Studio",
                    "provider_key": "lmstudio",
                    "badge": "💻 LM STUDIO",
                    "family": "LMStudio",
                    "category": "local_provider",
                    "parameter_size": "Local",
                    "quantization": "Local",
                    "is_active": True,
                })
    except Exception:
        pass

    # 4. ☁️ CLOUD PROVIDERS (OpenAI, DeepSeek, Anthropic, Groq, Google Gemini, Mistral...)
    try:
        from core.ai_providers import load_ai_config
        config = load_ai_config() or {}
        p_settings = config.get("providers", {})

        POPULAR_CLOUD = [
            ("openai", "OpenAI", [("gpt-4o", "GPT-4o (Omni)"), ("gpt-4o-mini", "GPT-4o Mini"), ("o3-mini", "o3 Mini Reasoning"), ("o1-mini", "o1 Mini")]),
            ("deepseek", "DeepSeek", [("deepseek-chat", "DeepSeek V3 (Chat)"), ("deepseek-reasoner", "DeepSeek R1 (Reasoner)")]),
            ("anthropic", "Anthropic", [("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"), ("claude-3-5-haiku-20241022", "Claude 3.5 Haiku")]),
            ("groq", "Groq LPU", [("llama-3.3-70b-versatile", "Llama 3.3 70B Versatile"), ("mixtral-8x7b-32768", "Mixtral 8x7B 32k")]),
            ("google", "Google Gemini", [("gemini-1.5-flash", "Gemini 1.5 Flash"), ("gemini-1.5-pro", "Gemini 1.5 Pro")]),
            ("mistral", "Mistral AI", [("mistral-small-latest", "Mistral Small"), ("mistral-large-latest", "Mistral Large")]),
            ("openrouter", "OpenRouter", [("openrouter/auto", "OpenRouter Auto"), ("anthropic/claude-3.5-sonnet", "Claude 3.5 via OpenRouter")]),
        ]

        for p_key, p_label, p_models in POPULAR_CLOUD:
            cfg = p_settings.get(p_key, {})
            has_key = bool(cfg.get("api_key") or cfg.get("has_api_key") or config.get(f"{p_key}_api_key") or os.environ.get(f"{p_key.upper()}_API_KEY"))
            for m_id, m_name in p_models:
                cid = f"{p_key}:{m_id}"
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                models.append({
                    "id": cid,
                    "name": f"{p_label}: {m_name}",
                    "provider": p_label,
                    "provider_label": f"☁️ {p_label}",
                    "provider_key": p_key,
                    "badge": f"☁️ {p_label.upper()}",
                    "is_cloud": True,
                    "has_key": has_key,
                    "category": "cloud",
                    "parameter_size": "Cloud API",
                    "quantization": "FP16/API",
                    "is_active": has_key,
                })
    except Exception as err:
        log.warning("Errore caricamento cloud providers per benchmark: %s", err)

    # 4. 🏆 Arricchimento con referti ufficiali di Benchmark e Tool Score
    try:
        from core.modules.sigma_training_lab.training.model_scores import (
            normalizza, scores_by_model,
        )
        referti = scores_by_model(include_suites=True)
        for m in models:
            cand_names = [
                m.get("resolved_target"),
                m.get("id"),
                m.get("name"),
                (m.get("details") or {}).get("model_id"),
                (m.get("details") or {}).get("filename"),
                (m.get("details") or {}).get("display_name"),
            ]
            summary = None
            for cn in cand_names:
                if not cn:
                    continue
                chiave = normalizza(cn)
                summary = referti.get(chiave)
                if not summary and chiave:
                    coda = chiave.split("/")[-1]
                    summary = next((r for k, r in referti.items() if k.split("/")[-1] == coda), None)
                if summary:
                    break

            m["benchmark_summary"] = summary or {"has_benchmarks": False}
            if summary:
                m["tool_score"] = summary.get("tool_score")
                m["tool_passed"] = summary.get("tool_passed")
                m["tool_total"] = summary.get("tool_total")
                m["has_tool_benchmark"] = summary.get("has_tool_benchmark", False)
                if summary.get("tokens_per_sec"):
                    m["tokens_per_sec"] = summary.get("tokens_per_sec")
    except Exception as err:
        log.debug("Referti benchmark in get_available_models_for_benchmark non disponibili: %s", err)

    return models


def get_benchmark_models_payload() -> dict:
    """Modelli + stato dei servizi (SigmaEngine, Ollama, Cloud)."""
    models = get_available_models_for_benchmark()
    ollama_up = True
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=0.5)
        ollama_up = res.status_code == 200
    except Exception:
        ollama_up = False
    return {
        "success": True,
        "models": models,
        "count": len(models),
        "sigma_engine_available": True,
        "ollama_available": ollama_up,
        "ollama_url": OLLAMA_URL,
    }


# ==============================================================================
# DATASET UFFICIALI
# ==============================================================================

OFFICIAL_BENCHMARKS_INFO = {
    "mmlu": {
        "name": "MMLU",
        "description": "Massive Multitask Language Understanding (57 materie: medicina, legge, fisica, matematica, economia...)",
        "type": "multiple_choice",
        "dataset": "cais/mmlu",
    },
    "mmlu_pro": {
        "name": "MMLU-Pro",
        "description": "Versione avanzata ad alto ragionamento con 10 opzioni e quesiti complessi",
        "type": "multiple_choice",
        "dataset": "TIGER-Lab/MMLU-Pro",
    },
    "gsm8k": {
        "name": "GSM8K",
        "description": "Grade School Math (problemi aritmetici con passaggi logici)",
        "type": "math_reasoning",
        "dataset": "openai/gsm8k",
    },
    "math": {
        "name": "MATH",
        "description": "Problemi matematici olimpici avanzati (algebra, calcolo, teoria dei numeri)",
        "type": "advanced_math",
        "dataset": "qwedsacf/competition_math",
    },
    "humaneval": {
        "name": "HumanEval",
        "description": "Completamento ed esecuzione di codice Python (pass@1 su test unitari reali)",
        "type": "code_execution",
        "dataset": "openai/openai_humaneval",
    },
    "mbpp": {
        "name": "MBPP",
        "description": "Mostly Basic Python Problems (sfide Python di base, verificate per esecuzione)",
        "type": "code_execution",
        "dataset": "google-research-datasets/mbpp",
    },
    "arc": {
        "name": "ARC",
        "description": "AI2 Reasoning Challenge (quesiti scientifici di ragionamento)",
        "type": "multiple_choice",
        "dataset": "allenai/ai2_arc",
    },
    "hellaswag": {
        "name": "HellaSwag",
        "description": "Valutazione del buon senso e continuazione naturale degli eventi",
        "type": "multiple_choice",
        "dataset": "Rowan/hellaswag",
    },
    "truthfulqa": {
        "name": "TruthfulQA",
        "description": "Rilevamento delle allucinazioni e veridicita' delle risposte",
        "type": "multiple_choice",
        "dataset": "truthfulqa/truthful_qa",
    },
    "gpqa": {
        "name": "GPQA",
        "description": "Graduate-Level Google-Proof Q&A (domande di livello specialistico universitario)",
        "type": "multiple_choice",
        "dataset": "ankner/gpqa",
    },
    "bbh": {
        "name": "BIG-Bench Hard",
        "description": "27 task complessi di ragionamento multi-step e logica simbolica",
        "type": "multi_step_reasoning",
        "dataset": "lukaemon/bbh",
    },
}

#: Suite verificate eseguendo i test ufficiali invece di confrontare testo.
CODE_SUITES = ("humaneval", "mbpp")

#: I 27 task di BIG-Bench Hard. Prima ne veniva scaricato solo il primo, quindi
#: "BBH" misurava soltanto le espressioni booleane.
BBH_TASKS = (
    "boolean_expressions", "causal_judgement", "date_understanding", "disambiguation_qa",
    "dyck_languages", "formal_fallacies", "geometric_shapes", "hyperbaton",
    "logical_deduction_five_objects", "logical_deduction_seven_objects",
    "logical_deduction_three_objects", "movie_recommendation", "multistep_arithmetic_two",
    "navigate", "object_counting", "penguins_in_a_table", "reasoning_about_colored_objects",
    "ruin_names", "salient_translation_error_detection", "snarks", "sports_understanding",
    "temporal_sequences", "tracking_shuffled_objects_five_objects",
    "tracking_shuffled_objects_seven_objects", "tracking_shuffled_objects_three_objects",
    "web_of_lies", "word_sorting",
)


def _get_hf_token() -> str:
    try:
        with open(paths.config_file(), "r", encoding="utf-8") as f:
            return json.load(f).get("hf_token", "")
    except Exception:
        return ""


def _get_cache_path(suite_id: str) -> str:
    return os.path.join(BENCHMARK_CACHE_DIR, f"{suite_id}.json")


def _is_cached(suite_id: str) -> bool:
    return os.path.exists(_get_cache_path(suite_id))


#: Suite tenute in memoria fra una chiamata e l'altra. Le undici suite insieme
#: sono circa 60.000 dizionari: tenerle tutte e' comodo su una workstation e
#: fatale su una scheda da 8 GB che ha gia' i pesi di un modello in RAM. Due
#: bastano: un run guarda una suite alla volta, e la seconda copre il passaggio
#: da una all'altra in modalita' "tutte".
_IN_MEMORY_LIMIT = 2
_IN_MEMORY_SUITES: "OrderedDict[str, list[dict]]" = OrderedDict()


def _remember(suite_id: str, items: list[dict]) -> None:
    """Tiene in memoria le ultime suite lette, e lascia andare le precedenti."""
    if not items:
        return
    _IN_MEMORY_SUITES[suite_id] = items
    _IN_MEMORY_SUITES.move_to_end(suite_id)
    while len(_IN_MEMORY_SUITES) > _IN_MEMORY_LIMIT:
        _IN_MEMORY_SUITES.popitem(last=False)


def _load_cached(suite_id: str) -> list[dict]:
    if suite_id in _IN_MEMORY_SUITES:
        _IN_MEMORY_SUITES.move_to_end(suite_id)
        return _IN_MEMORY_SUITES[suite_id]
    path = _get_cache_path(suite_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else []
        _remember(suite_id, items)
        return items
    except Exception as err:
        log.warning("Cache %s illeggibile: %s", suite_id, err)
        return []


def _save_cache(suite_id: str, items: list[dict]):
    _remember(suite_id, items)
    os.makedirs(BENCHMARK_CACHE_DIR, exist_ok=True)
    path = _get_cache_path(suite_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _mc_item(suite_id: str, suite_name: str, index: int, category: str, prompt: str,
             labels: list[str], texts: list[str], correct_label: str) -> dict:
    """Costruisce un item a scelta multipla con opzioni etichettate."""
    correct_idx = labels.index(correct_label) if correct_label in labels else -1
    correct_text = texts[correct_idx] if 0 <= correct_idx < len(texts) else ""
    return {
        "id": f"{suite_id}_{index}",
        "suite": suite_id,
        "suite_name": suite_name,
        "category": category,
        "prompt": prompt,
        "options": [f"{lbl}) {txt}" for lbl, txt in zip(labels, texts)],
        "correct_choice": correct_label,
        "correct_answer": f"{correct_label}) {correct_text}",
        "expected_keywords": [correct_text] if correct_text else [],
    }


def _letters(count: int) -> list[str]:
    return [chr(65 + i) for i in range(count)]


def _split(name: str, limit: int) -> str:
    """Lo split da chiedere a Hugging Face, tagliato se il chiamante lo vuole.

    ATTENZIONE a cosa e' e a cosa non e': `test[:2000]` sono i **primi** duemila
    quesiti, non duemila quesiti a caso. MMLU e' ordinato per materia, quindi un
    prefisso di duemila righe copre le prime materie in ordine alfabetico e
    nessuna delle altre. Serve a provare in fretta, non a produrre un punteggio
    confrontabile: per questo la cache che ne esce resta marcata `partial` e il
    certificato non puo' dichiarare copertura piena.
    """
    return f"{name}[:{int(limit)}]" if limit and limit > 0 else name


def _meta_path(suite_id: str) -> str:
    return os.path.join(BENCHMARK_CACHE_DIR, f"{suite_id}.meta.json")


def _load_meta(suite_id: str) -> dict:
    """Cosa sappiamo della cache di una suite: quanta ne abbiamo e se e' tutta.

    Un file a parte invece di cambiare il formato della cache: le cache gia' sul
    disco sono liste JSON da decine di megabyte, e riscriverle per aggiungere due
    campi vorrebbe dire rileggerle e riscriverle tutte al primo avvio dopo
    l'aggiornamento. Una cache senza questo file e' una cache completa scaricata
    prima che il taglio esistesse, che e' esattamente cio' che era.
    """
    try:
        with open(_meta_path(suite_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"complete": True}


def _save_meta(suite_id: str, count: int, limit: int) -> None:
    os.makedirs(BENCHMARK_CACHE_DIR, exist_ok=True)
    payload = {
        "count": count,
        "limit": int(limit or 0),
        # Un taglio che ha reso meno righe di quante ne chiedeva ha esaurito lo
        # split: e' completo, per quanto sia stato chiesto parzialmente.
        "complete": not limit or count < limit,
        "fetched_at": datetime.datetime.now().isoformat(),
    }
    tmp = _meta_path(suite_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, _meta_path(suite_id))


def download_suite(suite_id: str, limit: int = 0) -> dict:
    """Scarica e mette in cache i quesiti ufficiali di una suite (o di tutte).

    `limit` prende solo le prime N righe dello split. Accorcia la prima
    preparazione, e in cambio la cache non e' piu' un campione della suite ma il
    suo inizio — vedi `_split`. La cache resta segnata come parziale e si puo'
    completare in seguito ripetendo la chiamata senza limite.
    """
    if suite_id == "all":
        totals, errors = 0, {}
        for sid in OFFICIAL_BENCHMARKS_INFO:
            result = download_suite(sid, limit=limit)
            if result.get("success"):
                totals += result.get("count", 0)
            else:
                errors[sid] = result.get("error", "errore sconosciuto")
        return {
            "success": not errors,
            "count": totals,
            "suite": "all",
            "errors": errors,
            "error": "; ".join(f"{k}: {v}" for k, v in errors.items()) if errors else "",
        }

    if suite_id not in OFFICIAL_BENCHMARKS_INFO:
        return {"success": False, "error": f"Suite sconosciuta: {suite_id}"}

    # Un assaggio non paga con la suite intera. Se in cache c'e' gia' piu' di
    # quanto il taglio chiederebbe, il taglio non serve: i quesiti ci sono
    # gia' e campionarli costa un millisecondo. Senza questo controllo
    # "scarica le prime 300 righe" sovrascriveva quattordicimila quesiti di
    # MMLU con trecento — un baratto che nessuno aveva accettato, e
    # irreversibile senza riscaricare.
    if limit and limit > 0 and _is_cached(suite_id):
        presenti = len(_load_cached(suite_id))
        if presenti >= limit:
            log.info("Assaggio di %s non necessario: in cache ci sono gia' "
                     "%d quesiti (ne servivano %d).", suite_id, presenti, limit)
            return {"success": True, "count": presenti, "suite": suite_id,
                    "complete": _load_meta(suite_id).get("complete", True),
                    "skipped": "cache gia' sufficiente"}

    try:
        from datasets import load_dataset
    except ImportError:
        return {"success": False, "error": "Pacchetto 'datasets' non installato: pip install datasets"}

    token = _get_hf_token() or None
    out: list[dict] = []

    try:
        if suite_id == "mmlu":
            for i, item in enumerate(load_dataset("cais/mmlu", "all", split=_split("test", limit), token=token)):
                choices = item.get("choices", []) or []
                labels = _letters(len(choices))
                answer_idx = item.get("answer", -1)
                correct = labels[answer_idx] if isinstance(answer_idx, int) and 0 <= answer_idx < len(labels) else ""
                out.append(_mc_item(suite_id, "MMLU", i, item.get("subject", ""),
                                    item.get("question", ""), labels, choices, correct))

        elif suite_id == "mmlu_pro":
            for i, item in enumerate(load_dataset("TIGER-Lab/MMLU-Pro", split=_split("test", limit), token=token)):
                choices = item.get("options", []) or []
                labels = _letters(len(choices))
                out.append(_mc_item(suite_id, "MMLU-Pro", i, item.get("category", ""),
                                    item.get("question", ""), labels, choices,
                                    (item.get("answer", "") or "").strip().upper()))

        elif suite_id == "gsm8k":
            for i, item in enumerate(load_dataset("openai/gsm8k", "main", split=_split("test", limit), token=token)):
                answer_full = item.get("answer", "")
                match = re.search(r"####\s*(.+)", answer_full)
                out.append({
                    "id": f"{suite_id}_{i}", "suite": suite_id, "suite_name": "GSM8K",
                    "category": "Math", "prompt": item.get("question", ""), "options": [],
                    "correct_choice": match.group(1).strip() if match else "",
                    "correct_answer": answer_full,
                    "expected_keywords": [match.group(1).strip()] if match else [],
                })

        elif suite_id == "math":
            for i, item in enumerate(load_dataset("qwedsacf/competition_math", split=_split("train", limit), token=token)):
                solution = item.get("solution", "")
                match = re.search(r"\\boxed\{(.+?)\}", solution)
                out.append({
                    "id": f"{suite_id}_{i}", "suite": suite_id, "suite_name": "MATH",
                    "category": item.get("type", ""), "prompt": item.get("problem", ""), "options": [],
                    "correct_choice": match.group(1).strip() if match else "",
                    "correct_answer": solution,
                    "expected_keywords": [match.group(1).strip()] if match else [],
                })

        elif suite_id == "humaneval":
            for i, item in enumerate(load_dataset("openai/openai_humaneval", split=_split("test", limit), token=token)):
                solution = item.get("canonical_solution", "")
                out.append({
                    "id": f"{suite_id}_{i}", "suite": suite_id, "suite_name": "HumanEval",
                    "category": "Code", "prompt": item.get("prompt", ""), "options": [],
                    "correct_choice": solution, "correct_answer": solution,
                    "expected_keywords": [],
                    # Senza `test` ed `entry_point` non esiste pass@1: la suite
                    # si misura eseguendo queste asserzioni, non confrontando testo.
                    "verification": {
                        "test": item.get("test", ""),
                        "entry_point": item.get("entry_point", ""),
                    },
                })

        elif suite_id == "mbpp":
            for i, item in enumerate(load_dataset("google-research-datasets/mbpp", split=_split("test", limit), token=token)):
                code = item.get("code", "")
                out.append({
                    "id": f"{suite_id}_{i}", "suite": suite_id, "suite_name": "MBPP",
                    "category": "Code", "prompt": item.get("text", ""), "options": [],
                    "correct_choice": code, "correct_answer": code, "expected_keywords": [],
                    "verification": {
                        "test_list": list(item.get("test_list", []) or []),
                        "test_setup_code": item.get("test_setup_code", "") or "",
                    },
                })

        elif suite_id == "arc":
            for i, item in enumerate(load_dataset("allenai/ai2_arc", "ARC-Challenge", split=_split("test", limit), token=token)):
                choices = item.get("choices", {}) or {}
                out.append(_mc_item(suite_id, "ARC", i, "Science", item.get("question", ""),
                                    list(choices.get("label", [])), list(choices.get("text", [])),
                                    item.get("answerKey", "")))

        elif suite_id == "hellaswag":
            for i, item in enumerate(load_dataset("Rowan/hellaswag", split=_split("validation", limit), token=token)):
                endings = item.get("endings", []) or []
                labels = _letters(len(endings))
                label = str(item.get("label", ""))
                correct = labels[int(label)] if label.isdigit() and int(label) < len(labels) else ""
                out.append(_mc_item(suite_id, "HellaSwag", i, "Reasoning", item.get("ctx", ""),
                                    labels, endings, correct))

        elif suite_id == "truthfulqa":
            ds = load_dataset("truthfulqa/truthful_qa", "multiple_choice", split=_split("validation", limit), token=token)
            for i, item in enumerate(ds):
                targets = item.get("mc1_targets", {}) or {}
                choices = list(targets.get("choices", []))
                marks = list(targets.get("labels", []))
                labels = _letters(len(choices))
                idx = marks.index(1) if 1 in marks else -1
                out.append(_mc_item(suite_id, "TruthfulQA", i, "Truthfulness", item.get("question", ""),
                                    labels, choices, labels[idx] if 0 <= idx < len(labels) else ""))

        elif suite_id == "gpqa":
            import random
            for i, item in enumerate(load_dataset("ankner/gpqa", split=_split("train", limit), token=token)):
                question = item.get("Question") or item.get("question", "")
                correct_answer = item.get("Correct Answer") or item.get("answer", "")
                wrong = [item.get(f"Incorrect Answer {j}", "") for j in (1, 2, 3)
                         if item.get(f"Incorrect Answer {j}")]
                if not wrong:
                    wrong = list(item.get("incorrect_answers", []) or [])
                options = [correct_answer] + wrong
                # Mescolare col seed dell'indice evita che la risposta giusta
                # sia sempre in prima posizione, restando riproducibile.
                random.Random(i).shuffle(options)
                labels = _letters(len(options))
                idx = options.index(correct_answer) if correct_answer in options else 0
                out.append(_mc_item(suite_id, "GPQA", i, "Expert QA", question, labels, options,
                                    labels[idx] if idx < len(labels) else ""))

        elif suite_id == "bbh":
            loaded_tasks, failed_tasks = 0, []
            # BBH sono 27 task in 27 file: un limite applicato a ciascuno ne
            # darebbe 27 volte tanto. Diviso fra i task e' anche piu' giusto —
            # un taglio di BBH che contenesse solo i primi task non sarebbe BBH.
            per_task = max(1, limit // len(BBH_TASKS)) if limit and limit > 0 else 0
            for task in BBH_TASKS:
                if limit and len(out) >= limit:
                    break
                try:
                    ds = load_dataset("lukaemon/bbh", task,
                                      split=_split("test", per_task), token=token)
                except Exception as err:
                    failed_tasks.append(task)
                    log.debug("Task BBH %s non caricato: %s", task, err)
                    continue
                loaded_tasks += 1
                for i, item in enumerate(ds):
                    target = (item.get("target", "") or "").strip()
                    out.append({
                        "id": f"{suite_id}_{task}_{i}", "suite": suite_id,
                        "suite_name": "BIG-Bench Hard", "category": task.replace("_", " ").title(),
                        "prompt": item.get("input", ""), "options": [],
                        "correct_choice": target, "correct_answer": target,
                        "expected_keywords": [target] if target else [],
                    })
            if not loaded_tasks:
                return {"success": False, "error": "Nessun task BBH scaricabile"}
            if failed_tasks:
                log.warning("Task BBH saltati: %s", ", ".join(failed_tasks))

        if not out:
            return {"success": False, "error": f"Nessun quesito ottenuto per {suite_id}"}

        _save_cache(suite_id, out)
        _save_meta(suite_id, len(out), limit)
        meta = _load_meta(suite_id)
        return {
            "success": True, "count": len(out), "suite": suite_id,
            "complete": meta.get("complete", True),
        }

    except Exception as err:
        log.error("Errore nel download di %s: %s", suite_id, err)
        return {"success": False, "error": str(err)}


def get_suite_info(suite_id: str) -> dict:
    """Stato di una suite: presenza in cache, numero di quesiti, dettagli."""
    if suite_id == "all":
        suites, total, all_cached = {}, 0, True
        for sid in OFFICIAL_BENCHMARKS_INFO:
            info = get_suite_info(sid)
            suites[sid] = info
            total += info.get("count", 0)
            all_cached = all_cached and info.get("cached", False)
        return {
            "success": True, "suite": "all", "cached": all_cached, "count": total,
            "name": "Tutti i Benchmark Ufficiali", "suites": suites,
            "cached_suites": sum(1 for s in suites.values() if s.get("cached")),
            "total_suites": len(suites),
            "complete": all(s.get("complete", False) for s in suites.values()),
            "partial_suites": [sid for sid, s in suites.items()
                               if s.get("cached") and not s.get("complete")],
        }

    meta = OFFICIAL_BENCHMARKS_INFO.get(suite_id, {})
    cached = _is_cached(suite_id)
    meta_cache = _load_meta(suite_id) if cached else {}
    items = _load_cached(suite_id) if cached else []
    path = _get_cache_path(suite_id)

    categories = sorted({(i.get("category") or "") for i in items[:5000] if i.get("category")})

    # Una cache di suite di codice scaricata prima che salvassimo i test
    # ufficiali non permette il pass@1: va segnalato, non subito.
    needs_refresh = bool(
        suite_id in CODE_SUITES and items and not (items[0].get("verification") or {})
    )
    # Una cache BBH con pochissime categorie viene da quando scaricavamo un solo
    # task su 27: il punteggio direbbe "BBH" misurando un sottoinsieme minimo.
    if suite_id == "bbh" and items and len(categories) < 5:
        needs_refresh = True
    return {
        "success": True,
        "suite": suite_id,
        "cached": cached,
        "count": len(items),
        "name": meta.get("name", suite_id),
        "description": meta.get("description", ""),
        "type": meta.get("type", ""),
        "dataset": meta.get("dataset", ""),
        "categories": categories[:60],
        "size_mb": round(os.path.getsize(path) / (1024 ** 2), 2) if cached else 0,
        "needs_refresh": needs_refresh,
        # Una cache tagliata contiene l'inizio dello split, non un suo campione:
        # va detto qui, perche' un punteggio ottenuto su di essa non e'
        # confrontabile con uno ottenuto sulla suite intera.
        "complete": bool(meta_cache.get("complete", True)) if cached else False,
        "fetched_at": meta_cache.get("fetched_at", "") if cached else "",
    }


#: Frazione del campione riservata alla **verifica**. Un ciclo automatico che
#: decide guardando gli stessi quesiti su cui poi riporta il punteggio non
#: migliora il modello: scala quella classifica. Il set di selezione guida le
#: decisioni, il set di verifica non viene mai guardato durante il ciclo ed e'
#: l'unico numero che si comunica.
HOLDOUT_FRACTION = 0.5


def split_selection_holdout(items: list[dict], fraction: float = HOLDOUT_FRACTION
                            ) -> tuple[list[dict], list[dict]]:
    """Divide i quesiti in set di selezione e set di verifica.

    La divisione e' deterministica e stratificata per suite: due modelli
    valutati sullo stesso campione vedono la stessa partizione, altrimenti il
    confronto appaiato non sarebbe piu' appaiato.
    """
    rng = random.Random(1337)
    by_suite: dict[str, list[dict]] = {}
    for item in items:
        by_suite.setdefault(item.get("suite", "?"), []).append(item)

    selection, holdout = [], []
    for suite in sorted(by_suite):
        pool = sorted(by_suite[suite], key=lambda i: str(i.get("id", "")))
        rng.shuffle(pool)
        cut = int(len(pool) * (1 - fraction))
        selection.extend(pool[:cut])
        holdout.extend(pool[cut:])
    return selection, holdout


#: Quesiti minimi che ogni suite ottiene in un campione, quando ce ne stanno.
#: Sotto questa soglia una suite non dice niente di utile; a zero, sparisce.
_MIN_PER_SUITE = 5


def _stratified_sample(by_suite: dict[str, list[dict]], total: int) -> list[dict]:
    """A sample where every suite is represented, not just the big ones.

    Un campione casuale sull'unione delle suite le pesa per dimensione: MMLU ha
    14.042 quesiti e GSM8K 1.319, quindi su 100 estrazioni GSM8K ne prende due
    — e capita che ne prenda zero. E' successo davvero: un modello messo a punto
    proprio su GSM8K e' stato confrontato con la sua base su un campione che di
    GSM8K non conteneva un solo quesito.

    Qui ogni suite riceve prima una quota minima, e il resto viene diviso in
    proporzione. Il seed e' fisso: due modelli valutati con lo stesso `total`
    vedono gli stessi quesiti, che e' cio' che rende il confronto appaiato.
    """
    rng = random.Random(42)
    suites = {sid: found for sid, found in by_suite.items() if found}
    if not suites:
        return []

    floor = min(_MIN_PER_SUITE, max(1, total // len(suites)))
    quota = {sid: min(floor, len(found)) for sid, found in suites.items()}

    remaining = total - sum(quota.values())
    if remaining > 0:
        spare = {sid: len(found) - quota[sid] for sid, found in suites.items()}
        pool = sum(spare.values())
        if pool > 0:
            for sid, extra in spare.items():
                quota[sid] += min(extra, int(remaining * extra / pool))
    # Gli arrotondamenti lasciano qualche posto libero: vanno alle suite che
    # hanno ancora quesiti da offrire, in ordine di grandezza.
    leftover = total - sum(quota.values())
    for sid in sorted(suites, key=lambda s: -len(suites[s])):
        if leftover <= 0:
            break
        room = len(suites[sid]) - quota[sid]
        take = min(room, leftover)
        quota[sid] += take
        leftover -= take

    out: list[dict] = []
    for sid, found in suites.items():
        take = min(quota[sid], len(found))
        if take:
            out.extend(rng.sample(found, take))
    return out


def suites_in(suite_id: str) -> list[str]:
    """Le suite che un identificatore copre: una, alcune, o tutte."""
    if suite_id == "all":
        return list(OFFICIAL_BENCHMARKS_INFO)
    if "," in suite_id:
        return [s.strip() for s in suite_id.split(",")
                if s.strip() in OFFICIAL_BENCHMARKS_INFO]
    return [suite_id] if suite_id in OFFICIAL_BENCHMARKS_INFO else []


def dataset_is_complete(suite_id: str) -> bool:
    """Se i quesiti in cache sono la suite intera o solo il suo inizio.

    Sta nel certificato perche' cambia cosa significa il punteggio: un run su una
    cache tagliata a duemila righe di MMLU ha visto le prime materie in ordine
    alfabetico e nessuna delle altre, e confrontarlo con un run sulla suite
    intera e' un confronto fra due misure diverse che portano lo stesso nome.
    """
    suites = suites_in(suite_id)
    if not suites:
        return False
    return all(_load_meta(sid).get("complete", True) for sid in suites
               if _is_cached(sid))


#: Download contemporanei di suite diverse. Tre e' un numero di rete, non di
#: processore: oltre, la banda si divide e basta, mentre ogni dataset in
#: costruzione tiene memoria — e su una scheda piccola sono tre picchi insieme.
_DOWNLOAD_INSIEME = 3


def _scarica_insieme(suite_ids: list[str], announce) -> None:
    """Scarica piu' suite in parallelo, dicendo quali via via arrivano.

    Ogni download e' un'attesa di rete durante la quale la macchina non fa
    niente: metterne tre in volo accorcia la preparazione della somma dei tempi
    morti. Su una macchina con poca memoria si torna a una alla volta, perche'
    tre dataset in costruzione sono tre picchi contemporanei.
    """
    import concurrent.futures

    paralleli = _DOWNLOAD_INSIEME
    if _ram_disponibile_gb() and _ram_disponibile_gb() < _RAM_MINIMA_PER_PARALLELO_GB:
        paralleli = 1
        log.info("Download in serie: memoria libera sotto la soglia.")

    if paralleli <= 1:
        return                              # il percorso normale li fa in fila

    announce(f"⬇️ Scarico {len(suite_ids)} dataset da Hugging Face "
             f"({paralleli} alla volta, solo la prima volta)...")
    fatti = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=paralleli) as pool:
        futuri = {pool.submit(download_suite, sid): sid for sid in suite_ids}
        for futuro in concurrent.futures.as_completed(futuri):
            sid = futuri[futuro]
            fatti += 1
            try:
                esito = futuro.result()
            except Exception as err:
                log.warning("Download di %s non riuscito: %s", sid, err)
                continue
            if esito.get("success"):
                announce(f"✅ {fatti}/{len(suite_ids)}: {_suite_label(sid)} "
                         f"({esito.get('count', 0)} quesiti)")
            else:
                announce(f"⚠️ {_suite_label(sid)}: {esito.get('error', 'non scaricata')}")


def _suite_label(suite_id: str) -> str:
    return (OFFICIAL_BENCHMARKS_INFO.get(suite_id, {}) or {}).get("name") or suite_id.upper()


def _get_preset_path(suite_id: str, mode: str, num_samples: int) -> str:
    presets_dir = os.path.join(module_paths.TRAINING_LAB_DIR, "benchmark_presets")
    os.makedirs(presets_dir, exist_ok=True)
    safe_sid = suite_id.replace(",", "_").replace(":", "_").replace("/", "_")
    return os.path.join(presets_dir, f"preset_{safe_sid}_{mode}_{num_samples}.json")


def _load_preset(suite_id: str, mode: str, num_samples: int) -> list[dict] | None:
    path = _get_preset_path(suite_id, mode, num_samples)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) == num_samples:
                return data
    except Exception as err:
        log.debug("Preset %s non leggibile: %s", path, err)
    return None


def _save_preset(suite_id: str, mode: str, num_samples: int, items: list[dict]) -> None:
    if not items or len(items) != num_samples:
        return
    try:
        path = _get_preset_path(suite_id, mode, num_samples)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as err:
        log.debug("Preset %s non salvabile: %s", suite_id, err)


def get_benchmark_items(suite_id: str, mode: str = "full", num_samples: int = 0,
                        progress=None) -> list[dict]:
    """Quesiti da valutare; scarica la suite se manca dalla cache.

    Supporta suite singole ('mmlu'), tutte ('all'), o combinazioni separate da
    virgola ('mmlu,gsm8k,humaneval'). Supporta caricamento istantaneo da preset cache.
    """
    # 0. Scorciatoia istantanea da preset cache (tempo di caricamento < 1ms)
    if mode == "sample" and num_samples > 0:
        cached_preset = _load_preset(suite_id, mode, num_samples)
        if cached_preset is not None:
            return cached_preset

    def announce(message: str) -> None:
        if progress:
            try:
                progress(message)
            except Exception as err:      # la UI non deve poter fermare un run
                log.debug("Notifica di preparazione ignorata: %s", err)

    if "," in suite_id or suite_id == "all":
        if suite_id == "all":
            selected_suites = list(OFFICIAL_BENCHMARKS_INFO)
        else:
            selected_suites = [s.strip() for s in suite_id.split(",")
                                if s.strip() in OFFICIAL_BENCHMARKS_INFO]

        # Le suite che mancano si scaricano insieme. E' tempo di rete: undici
        # dataset presi uno alla volta sono undici attese in fila, e nessuna
        # delle undici sta usando il processore mentre aspetta la successiva.
        da_scaricare = [sid for sid in selected_suites if not _is_cached(sid)]
        if len(da_scaricare) > 1:
            _scarica_insieme(da_scaricare, announce)

        by_suite: dict[str, list[dict]] = {}
        for position, sid in enumerate(selected_suites, start=1):
            announce(f"📚 Preparazione {position}/{len(selected_suites)}: "
                     f"{_suite_label(sid)}")
            found = get_benchmark_items(sid, mode="full", num_samples=0,
                                        progress=progress)
            if found:
                by_suite[sid] = found

        if mode == "sample" and num_samples > 0:
            total_available = sum(len(found) for found in by_suite.values())
            if num_samples < total_available:
                sampled = _stratified_sample(by_suite, num_samples)
                _save_preset(suite_id, mode, num_samples, sampled)
                return sampled
        full_items = [item for found in by_suite.values() for item in found]
        return full_items

    if not _is_cached(suite_id):
        announce(f"⬇️ Scarico {_suite_label(suite_id)} da Hugging Face "
                 f"(solo la prima volta)...")
        result = download_suite(suite_id)
        if not result.get("success"):
            log.error("Download di %s non riuscito: %s", suite_id, result.get("error"))
            announce(f"⚠️ {_suite_label(suite_id)} non scaricabile: "
                     f"{result.get('error', 'errore sconosciuto')}")
            return []

    items = _load_cached(suite_id)
    if mode == "sample" and 0 < num_samples < len(items):
        chosen = random.Random(42).sample(range(len(items)), num_samples)
        sampled = [items[i] for i in chosen]
        _save_preset(suite_id, mode, num_samples, sampled)
        return sampled
    return items


# ==============================================================================
# ESECUZIONE
# ==============================================================================

def _fewshot_block(item: dict, shots: int) -> str:
    """Esempi risolti da mettere davanti al quesito, presi dalla stessa suite.

    MMLU si pubblica con cinque esempi della *stessa materia*: servono a fissare
    il formato della risposta, non a insegnare l'argomento. A zero esempi un
    modello perde punti prima ancora di sapere la risposta, perche' sbaglia la
    forma — ed e' un costo che lo strumento gli impone, non una sua debolezza.

    Gli esempi vengono dai quesiti della suite che *non* sono nel campione in
    valutazione: usarne uno su cui si sta misurando sarebbe mostrargli la
    risposta. La scelta e' deterministica (ordinata per identificativo), quindi
    due modelli valutati sullo stesso campione vedono gli stessi esempi.
    """
    if shots <= 0:
        return ""

    suite = item.get("suite", "")
    category = item.get("category", "")
    pool = _load_cached(suite)
    if not pool:
        return ""

    chosen = _fewshot_cache.get((suite, category, shots))
    if chosen is None:
        excluded = _fewshot_excluded.get(suite) or set()
        same_subject, others = [], []
        for candidate in pool:
            if candidate.get("id") in excluded:
                continue
            if not candidate.get("options") or not candidate.get("correct_choice"):
                continue
            if candidate.get("category") == category:
                same_subject.append(candidate)
                if len(same_subject) >= shots:
                    break
            elif len(others) < shots:
                # Riserva, non magazzino: senza questo tetto la lista cresceva
                # fino a tutta la suite ogni volta che la materia cercata stava
                # in fondo, e MMLU e' ordinato per materia.
                others.append(candidate)
        chosen = (same_subject + others)[:shots]
        # Gli esempi dipendono solo da materia e numero: calcolarli una volta
        # per materia invece che una volta per quesito toglie una scansione di
        # quattordicimila righe da ogni singola domanda.
        _fewshot_cache[(suite, category, shots)] = chosen

    if not chosen:
        return ""

    blocks = []
    for example in chosen:
        options = "\n".join(example.get("options") or [])
        blocks.append(f"{example.get('prompt', '')}\n{options}\n"
                      f"Answer: {example.get('correct_choice', '')}")
    return "\n\n".join(blocks) + "\n\n"


#: Identificativi esclusi dagli esempi, per suite: sono i quesiti su cui si sta
#: misurando. Popolato all'avvio del run, letto da `_fewshot_block`.
_fewshot_excluded: dict[str, set] = {}

#: Esempi gia' scelti, per (suite, materia, numero). Dipendono solo da quelli.
_fewshot_cache: dict[tuple, list] = {}


def register_evaluated_ids(items: list[dict]) -> None:
    """Segna quali quesiti sono in valutazione, perche' non finiscano fra gli esempi."""
    _fewshot_excluded.clear()
    _fewshot_cache.clear()
    for item in items:
        suite = item.get("suite", "")
        if suite:
            _fewshot_excluded.setdefault(suite, set()).add(item.get("id"))


def _prepare_benchmark_payload(item: dict, model_name: str, thinking_mode: str = "auto") -> dict:
    """Prompt e parametri di generazione per un quesito, secondo il suo protocollo e modalita' thinking."""
    suite = item.get("suite", "")
    options = item.get("options", [])
    protocol = resolve_protocol(suite, thinking_mode=thinking_mode)
    base_options = {"temperature": 0.0, "seed": 42, "top_p": 1.0}
    budget = protocol.max_tokens or 1024

    if suite == "mbpp":
        verification = item.get("verification") or {}
        test_list = verification.get("test_list") or []
        tests_str = "\n".join(test_list[:3]) if test_list else ""
        prompt = f"Task: {item.get('prompt', '')}\n\n"
        if tests_str:
            prompt += f"Your code should satisfy the following test cases:\n```python\n{tests_str}\n```\n\n"
        prompt += ("Write a complete, self-contained Python solution inside a single ```python "
                   "code block. Include the exact function definition and any imports it needs.")
        return {
            "model": model_name,
            "system": "You are an expert Python engineer. Output only working code in one code block.",
            "prompt": prompt,
            "stream": False,
            "think": protocol.thinking,
            "stop": STOP_CODE,
            "options": {**base_options, "num_predict": budget},
        }

    if suite in CODE_SUITES:
        prompt = (f"Task: {item.get('prompt', '')}\n\n"
                  "Write a complete, self-contained Python solution inside a single ```python "
                  "code block. Include the full function definition and any imports it needs.")
        return {
            "model": model_name,
            "system": "You are an expert Python engineer. Output only working code in one code block.",
            "prompt": prompt,
            "stream": False,
            "think": protocol.thinking,
            "stop": STOP_CODE,
            "options": {**base_options, "num_predict": budget},
        }

    if suite in ("gsm8k", "math"):
        if thinking_mode == "no_thinking":
            prompt = (f"Question: {item['prompt']}\n\n"
                      "Provide only the final direct numerical answer inside \\boxed{...} (e.g. \\boxed{49}). "
                      "Do NOT write reasoning steps or explanations. Give exactly one answer and stop.")
            system = ("You are a direct mathematical solver. Output only the final answer inside \\boxed{...} "
                      "with NO chain-of-thought or reasoning steps.")
        else:
            prompt = (f"Question: {item['prompt']}\n\n"
                      "Solve the problem step by step. When you are done, write the final "
                      "answer on its own last line, inside \\boxed{...} (e.g. \\boxed{49}). "
                      "Give exactly one final answer and stop there.")
            system = ("You are an expert mathematical problem solver. Reason step by step, "
                      "then end your reply with the final result inside \\boxed{...} on the "
                      "last line. Give exactly one final answer and write nothing after it.")
        return {
            "model": model_name,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "think": protocol.thinking,
            "stop": STOP_MATH,
            "options": {**base_options, "num_predict": budget},
        }

    if options:
        shots = _fewshot_block(item, protocol.shots)
        prompt = (f"{shots}Question: {item['prompt']}\n\n" + "\n".join(options))
        if thinking_mode == "no_thinking":
            prompt += ("\n\nOutput only the letter of the correct option (e.g. A, B, C, D). "
                       "Do NOT provide reasoning or explanations. Conclude on the last line with: Answer: <LETTER>")
            system = ("You are a direct multiple-choice benchmark solver. Output only the chosen option letter "
                      "as 'Answer: <LETTER>' with NO explanations.")
        elif protocol.mode == MODE_COT:
            prompt += ("\n\nThink through the problem step by step, then finish "
                       "with the chosen option letter on its own last line as: "
                       "Answer: <LETTER>")
            system = ("You are an expert benchmark solver. Reason carefully, then "
                      "end your reply with 'Answer: <LETTER>' on the last line.")
        else:
            prompt += ("\n\nAnswer with the letter of the correct option (e.g. A, B, C, D). "
                       "Conclude your reply on the last line with: Answer: <LETTER>")
            system = ("You are an expert multiple-choice benchmark solver. Carefully identify "
                      "the correct option and output the chosen option letter on your final "
                      "line as 'Answer: <LETTER>'.")
        return {
            "model": model_name,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "think": protocol.thinking,
            "stop": STOP_MULTIPLE_CHOICE,
            "options": {**base_options, "num_predict": budget},
        }

    if thinking_mode == "no_thinking":
        prompt = (f"Task: {item['prompt']}\n\n"
                  "Give only the final answer directly with no explanation, on the last line prefixed with 'Answer:'.")
        return {
            "model": model_name,
            "system": "You are a direct benchmark solver. Answer directly with 'Answer: <final answer>' on the last line without reasoning.",
            "prompt": prompt,
            "stream": False,
            "think": False,
            "stop": STOP_SHORT_ANSWER,
            "options": {**base_options, "num_predict": min(budget, 256)},
        }

    if protocol.mode == MODE_COT:
        prompt = (f"Task: {item['prompt']}\n\n"
                  "Work through it step by step, then give the final answer on its "
                  "own last line, prefixed with 'Answer:'.")
        return {
            "model": model_name,
            "system": ("You are a reasoning benchmark solver. Reason step by step, then "
                       "end with 'Answer: <final answer>' on the last line."),
            "prompt": prompt,
            "stream": False,
            "think": protocol.thinking,
            "stop": STOP_SHORT_ANSWER,
            "options": {**base_options, "num_predict": budget},
        }

    prompt = f"Task: {item['prompt']}\n\nGive only the final answer, with no explanation.\nAnswer:"
    return {
        "model": model_name,
        "system": ("You are a reasoning benchmark engine. Reply with the final answer only, "
                   "in the shortest possible form."),
        "prompt": prompt,
        "stream": False,
        "think": protocol.thinking,
        "stop": STOP_SHORT_ANSWER,
        "options": {**base_options, "num_predict": min(budget, 256)},
    }

# Versione del protocollo di prompting. Va nell'impronta di riproducibilita':
# due run con prompt diversi non sono confrontabili, e senza questo marcatore
# nulla nel certificato lo direbbe.
#   1 — risposta sulla prima riga, poi il ragionamento (ritirato: misurava
#       quanto il modello indovina prima di fare i conti)
#   2 — ragionamento passo passo, risposta finale in chiusura
#   3 — come il 2, ma in modalita' oggettiva: nessuna persona, nessuno
#       strumento, campionamento neutro (greedy, penalita' di ripetizione 1.0),
#       blocco di ragionamento disattivato e sequenze di stop esplicite. Sulle
#       suite a scelta multipla la lettera si legge dalla distribuzione invece
#       che dalla prosa, quando il backend residente espone i logit.
PROMPT_PROTOCOL = 3

GRADER_VERSION = "sigma.answer_parser/3"

#: Come si e' ottenuta la scelta su un item a risposta multipla. Sta nel
#: certificato accanto al protocollo di prompting perche' due run che hanno
#: scelto in modi diversi non sono la stessa misura, per quanto simili
#: sembrino i punteggi.
ANSWER_PROTOCOL_LOGITS = "logit-ranking"
ANSWER_PROTOCOL_CONSTRAINED = "grammar-constrained"
ANSWER_PROTOCOL_CONTINUATION = "continuation-ranking"
ANSWER_PROTOCOL_GENERATIVE = "generative-parse"


def _request_timeout(suite: str) -> int:
    """Timeout HTTP per suite: matematica e codice generano molto piu' testo."""
    if suite in ("gsm8k", "math"):
        return 300
    if suite in CODE_SUITES:
        return 240
    return 90


def _grade(item: dict, output_text: str) -> dict:
    """Verdetto di un quesito, con esecuzione dei test per le suite di codice."""
    if (item.get("suite") or "").lower() in CODE_SUITES:
        from core.modules.sigma_benchmark_lab.code_exec import run_code_item
        return grade_code_result(run_code_item(item, output_text))
    return grade_answer(item, output_text)


def _empty_metrics() -> dict:
    return {
        "overall_score": 0, "accuracy_pct": 0, "decided_accuracy_pct": 0,
        "tokens_per_sec": 0, "avg_latency_ms": 0, "total_tokens": 0,
        "tests_passed": 0, "tests_failed": 0, "tests_total": 0,
        "tests_ambiguous": 0, "tests_unparsable": 0, "tests_error": 0,
        "tests_review": 0, "review_pct": 0,
        "thinking_passed": 0, "thinking_total": 0, "thinking_accuracy": 0.0,
        "no_thinking_passed": 0, "no_thinking_total": 0, "no_thinking_accuracy": 0.0,
    }


def _compute_metrics(counts: dict, total_done: int, planned_total: int,
                     total_tokens: int, total_duration: float, latency_sum_ms: int,
                     thinking_counts: dict | None = None,
                     no_thinking_counts: dict | None = None) -> dict:
    """Aggrega i contatori in metriche, separando lo score dal giudizio sospeso e calcolando thinking vs no-thinking."""
    passed = counts.get(VERDICT_PASS, 0)
    failed = counts.get(VERDICT_FAIL, 0)
    review = sum(counts.get(v, 0) for v in REVIEW_VERDICTS)
    decided = passed + failed
    th_p = (thinking_counts or {}).get("passed", 0)
    th_t = (thinking_counts or {}).get("total", 0)
    no_th_p = (no_thinking_counts or {}).get("passed", 0)
    no_th_t = (no_thinking_counts or {}).get("total", 0)

    return {
        "overall_score": round((passed / planned_total) * 100, 2) if planned_total else 0,
        "progress_score": round((passed / total_done) * 100, 2) if total_done else 0,
        "accuracy_pct": round((passed / planned_total) * 100, 2) if planned_total else 0,
        "decided_accuracy_pct": round((passed / decided) * 100, 2) if decided else 0,
        "tokens_per_sec": round(total_tokens / total_duration, 2) if total_duration > 0 else 0,
        "avg_latency_ms": int(latency_sum_ms / total_done) if total_done else 0,
        "total_tokens": total_tokens,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_total": total_done,
        "tests_ambiguous": counts.get(VERDICT_AMBIGUOUS, 0),
        "tests_unparsable": counts.get(VERDICT_UNPARSABLE, 0),
        "tests_error": counts.get(VERDICT_ERROR, 0),
        "tests_review": review,
        "review_pct": round((review / total_done) * 100, 2) if total_done else 0,
        "thinking_passed": th_p,
        "thinking_total": th_t,
        "thinking_accuracy": round((th_p / th_t) * 100, 2) if th_t else 0.0,
        "no_thinking_passed": no_th_p,
        "no_thinking_total": no_th_t,
        "no_thinking_accuracy": round((no_th_p / no_th_t) * 100, 2) if no_th_t else 0.0,
    }



# ==============================================================================
# ESECUZIONE IN MODALITA' OGGETTIVA (SIGMAENGINE)
# ==============================================================================
# Un benchmark misura il checkpoint, non Sigma Studio. Tutto cio' che il
# prodotto normalmente aggiunge — la persona, gli strumenti MCP, la memoria di
# progetto, la ricetta di campionamento della famiglia — qui e' rumore che
# sposta il punteggio e lo rende incomparabile con i numeri pubblicati per lo
# stesso modello altrove. `core.engine.evaluation` e' quello strato tolto di
# proposito, in un posto solo.

#: Quante generazioni scadute di fila bastano per fermare il run. Un timeout
#: isolato e' un quesito difficile; tre di fila sono un backend che non serve
#: piu' — e a quel punto proseguire significa passare ore a raccogliere errori
#: con un tetto di dieci minuti l'uno, senza che niente lo dica.
_TIMEOUT_CONSECUTIVI_MAX = 3


class ModelUnavailable(RuntimeError):
    """I pesi non si caricano: nessun quesito di questo run puo' avere risposta.

    Distinta da un errore su un singolo quesito apposta. Un modello che non
    entra in memoria non e' un modello che sbaglia cento domande: scrivere cento
    righe "ERRORE MODELLO" e poi un punteggio dello 0% descrive il run come una
    misura riuscita di un modello pessimo, quando invece la misura non e' mai
    iniziata. Il run si ferma e dice perche'.
    """

    def __init__(self, message: str, diagnosis: str = ""):
        super().__init__(message)
        self.diagnosis = diagnosis or message


def _raise_if_unavailable(outcomes) -> None:
    """Ferma il run se il motore ha detto che i pesi non si caricano."""
    for outcome in outcomes:
        if outcome.get("fatal"):
            raise ModelUnavailable(outcome.get("error") or "caricamento fallito",
                                   outcome.get("diagnosis") or "")


def _is_sigma_model(model_name: str) -> bool:
    return model_name.startswith("sigma:") or model_name in ("sigma", "sigmaengine")


def _sigma_target(model_name: str) -> str:
    if model_name.startswith("sigma:"):
        return model_name.replace("sigma:", "", 1)
    return "sigmaengine"


def _choice_messages(item: dict) -> list[dict]:
    """Il quesito posto in modo che la risposta sia la lettera e basta.

    Nessuna richiesta di ragionare: qui non si legge cio' che il modello scrive,
    si legge la distribuzione sul primo token di risposta. Chiedere il
    ragionamento cambierebbe quella distribuzione senza che nessuno legga il
    ragionamento.
    """
    options = "\n".join(item.get("options") or [])
    shots = _fewshot_block(item, protocol_for(item.get("suite", "")).shots)
    return [{
        "role": "user",
        "content": (f"{shots}{item.get('prompt', '')}\n\n{options}\n\n"
                    "Answer with the letter of the correct option only."),
    }]


def _continuation_question(item: dict) -> tuple[str, list[str]]:
    """Il contesto e le continuazioni candidate, senza etichette.

    Le lettere spariscono di proposito: qui non si chiede al modello di
    scegliere, si misura quale finale trova piu' probabile. Lasciare "A) " in
    testa a una continuazione ne cambierebbe la verosimiglianza per ragioni che
    non hanno niente a che fare con il senso della frase.
    """
    from core.modules.sigma_benchmark_lab.answer_parser import _option_body

    template = protocol_for(item.get("suite", "")).context or "{q}"
    context = template.replace("{q}", str(item.get("prompt", "")).rstrip()).rstrip()
    bodies = [_option_body(opt) for opt in (item.get("options") or [])]
    # Uno spazio davanti: e' cosi' che la continuazione compare davvero nel
    # testo, e il tokenizer la spezza di conseguenza.
    return context, [f" {body}" for body in bodies]


def _generative_messages(item: dict, model_name: str, thinking_mode: str = "auto") -> tuple[list[dict], dict]:
    """Conversazione e parametri per un quesito da risolvere scrivendo."""
    payload = _prepare_benchmark_payload(item, model_name, thinking_mode=thinking_mode)
    messages = []
    if payload.get("system"):
        messages.append({"role": "system", "content": payload["system"]})
    messages.append({"role": "user", "content": payload["prompt"]})
    return messages, payload


def _run_sigma_choice_scoring(items: list[dict], target_model: str,
                              batch_size: int) -> dict[int, dict]:
    """Sceglie fra le opzioni leggendo i logit, non il testo.

    Restituisce {indice_in_items: esito}. Un dizionario vuoto significa che il
    backend residente non espone i logit — un GGUF servito da llama.cpp — e che
    il chiamante deve ripiegare sul percorso generativo.
    """
    from core.engine import evaluation
    from core.modules.sigma_benchmark_lab.answer_parser import option_letters

    conversations = [_choice_messages(item) for item in items]
    letters = [option_letters(item.get("options") or []) for item in items]

    started = time.time()
    outcomes = evaluation.choose(
        conversations=conversations,
        letters=letters,
        model_name=target_model,
        batch_size=batch_size,
    )
    _raise_if_unavailable(outcomes)

    if not outcomes:
        return {}

    elapsed = max(time.time() - started, 1e-3)
    per_item_ms = int((elapsed / max(len(items), 1)) * 1000)
    scored: dict[int, dict] = {}
    for position, outcome in enumerate(outcomes):
        letter = outcome.get("choice")
        if not letter:
            # Il modello non stava per scrivere un'etichetta in quella
            # posizione. Non e' ne' un errore ne' una risposta sbagliata: e'
            # una lettura che non si puo' fare, e il quesito torna al percorso
            # scritto invece di essere contato come illeggibile.
            continue
        scored[position] = {
            # Il verdetto passa comunque dal parser ufficiale: una sola strada
            # per arrivare a "pass", altrimenti due protocolli producono due
            # tabelle che nessuno puo' confrontare.
            "text": f"Answer: {letter}",
            "tokens": 1,
            "latency_ms": per_item_ms,
            "error": "",
            "fatal": False,
            "diagnosis": "",
            "choice_probs": outcome.get("probs", {}),
            "choice_margin": outcome.get("margin", 0.0),
            "choice_mass": outcome.get("mass", 0.0),
            "constrained": bool(outcome.get("constrained")),
        }
    return scored


def _run_sigma_continuation(items: list[dict], target_model: str,
                            batch_size: int) -> dict[int, dict]:
    """Sceglie confrontando la verosimiglianza del testo delle opzioni.

    E' il metodo con cui HellaSwag, ARC e TruthfulQA vengono pubblicati, e
    misura una cosa diversa dalla lettura di una lettera: non "sa rispondere a
    una domanda a scelta multipla" ma "trova piu' probabile il finale giusto".
    Un modello piccolo che non riesce a emettere "Answer: C" in modo affidabile
    risponde comunque bene a questo — ed e' il motivo per cui i punteggi
    pubblicati di quelle suite non si riproducono leggendo una lettera.

    Un dizionario vuoto significa che il backend residente non espone le
    verosimiglianze, e i quesiti vanno mandati sul percorso scritto.
    """
    from core.engine import evaluation
    from core.modules.sigma_benchmark_lab.answer_parser import option_letters

    protocol = protocol_for(items[0].get("suite", "")) if items else protocol_for("")
    questions = [_continuation_question(item) for item in items]

    started = time.time()
    outcomes = evaluation.rank_continuations(
        questions,
        model_name=target_model,
        normalize=protocol.normalize or "char",
        batch_size=batch_size,
    )
    _raise_if_unavailable(outcomes)
    if not outcomes:
        # Backend senza verosimiglianze (un GGUF su llama.cpp): invece di
        # mandare tutto sul percorso scritto, che su queste suite costa mille
        # token per quesito, si ripiega sulla scelta vincolata da grammatica —
        # esito univoco e un token, solo su un protocollo diverso. Il
        # certificato lo registra per item, quindi la differenza resta visibile.
        return _run_sigma_choice_scoring(items, target_model, batch_size)

    elapsed = max(time.time() - started, 1e-3)
    per_item_ms = int((elapsed / max(len(items), 1)) * 1000)

    scored: dict[int, dict] = {}
    for position, outcome in enumerate(outcomes):
        winner = outcome.get("choice")
        if winner is None:
            continue
        letters = option_letters(items[position].get("options") or [])
        if winner >= len(letters):
            continue
        scored[position] = {
            # Il verdetto passa comunque dal parser ufficiale: la lettera qui
            # e' la traduzione di una scelta gia' fatta, non una nuova lettura.
            "text": f"Answer: {letters[winner]}",
            "tokens": 1,
            "latency_ms": per_item_ms,
            "error": "",
            "fatal": False,
            "diagnosis": "",
            "choice_probs": {},
            "choice_margin": outcome.get("margin", 0.0),
            "choice_mass": 0.0,
            "continuation_scores": outcome.get("scores", []),
            "constrained": False,
        }
    return scored


def _run_sigma_generative(items: list[dict], model_name: str, target_model: str,
                          batch_size: int, cancel=None, on_item=None,
                          thinking_mode: str = "auto") -> dict[int, dict]:
    """Risposte scritte, ma in lotti: e' cio' che tiene occupata la GPU.

    A batch 1 un modello decoder-only e' limitato dalla banda con cui legge i
    pesi, non dai suoi FLOP: il secondo prompt del lotto legge gli stessi pesi
    del primo e costa quasi zero. E' la ragione per cui un run che impiegava
    ore lasciava la scheda a utilizzo di una cifra.
    """
    from core.engine import evaluation

    grouped: dict[tuple, list[int]] = {}
    prepared: dict[int, tuple] = {}
    for position, item in enumerate(items):
        messages, payload = _generative_messages(item, model_name, thinking_mode=thinking_mode)
        budget = int(payload.get("options", {}).get("num_predict", 512))
        stop = tuple(payload.get("stop") or ())
        thinking = payload.get("think")
        prepared[position] = (messages, budget, stop)
        # Il ragionamento fa parte della chiave: un lotto misto costringerebbe
        # meta' dei quesiti a essere misurati con l'impostazione dell'altra.
        grouped.setdefault((budget, stop, thinking), []).append(position)

    results: dict[int, dict] = {}
    scaduti_di_fila = {"n": 0}
    for (budget, stop, thinking), positions in grouped.items():
        # Un lotto solo con lo stesso tetto di token: mischiare un quesito da
        # 128 token con uno da 2048 fa pagare a entrambi il piu' lungo.
        started = time.time()
        seen = {"n": 0, "at": started}
        seen_lock = threading.Lock()

        def _arrived(entry, _positions=positions, _seen=seen):
            """Riporta un quesito appena il motore lo consegna.

            Senza questo, una coda di trenta quesiti su un backend che decodifica
            una sequenza alla volta — un GGUF su llama.cpp — non produce niente
            di visibile finche' non finisce l'intera coda: la barra resta ferma
            per un'ora e l'utente legge un blocco. Il costo e' identico, cambia
            solo quando lo si viene a sapere.
            """
            now = time.time()
            index = _positions[int(entry.get("index", 0))]
            # Con piu' richieste in volo il tempo di un quesito non e' l'intervallo
            # dall'ultimo arrivo: quattro risposte che tornano insieme si
            # sarebbero prese la prima tutto il tempo e le altre zero, che e'
            # esattamente cio' che si leggeva — "300.013 ms" seguito da "6 ms",
            # "0 ms", "2 ms". Il tempo medio del gruppo e' una misura onesta.
            with seen_lock:
                _seen["n"] += 1
                trascorso = now - started
                latency_ms = int((trascorso / max(_seen["n"], 1)) * 1000)
            results[index] = {
                "text": str(entry.get("text") or ""),
                "tokens": int(entry.get("tokens") or 0),
                "tokens_per_sec": float(entry.get("tokens_per_sec") or 0.0),
                "latency_ms": latency_ms,
                "error": str(entry.get("error") or ""),
                "warning": str(entry.get("warning") or ""),
                "fatal": bool(entry.get("fatal")),
                "diagnosis": str(entry.get("diagnosis") or ""),
                "batch_size": int(entry.get("batch_size") or 1),
                "finish_reason": str(entry.get("finish_reason") or "stop"),
            }
            with seen_lock:
                if results[index]["finish_reason"] == "timeout" or (
                        "timed out" in results[index]["error"].lower()):
                    scaduti_di_fila["n"] += 1
                else:
                    scaduti_di_fila["n"] = 0
                di_fila = scaduti_di_fila["n"]

            if on_item:
                on_item(index, results[index])

            if di_fila >= _TIMEOUT_CONSECUTIVI_MAX:
                # Si chiede al backend perche': "pesi in VRAM e schede a zero"
                # e' lo stesso sintomo per un processo morto e per uno che
                # genera lentissimo, e i due rimedi sono opposti.
                diagnosi = ""
                try:
                    from core.engine.unified_runtime import sigma_engine
                    backend = sigma_engine.active_backend_instance
                    if backend is not None and hasattr(backend, "diagnosi"):
                        diagnosi = backend.diagnosi()
                except Exception as err:
                    log.debug("Diagnosi del backend non disponibile: %s", err)

                raise ModelUnavailable(
                    f"{di_fila} generazioni scadute di fila",
                    diagnosi or (
                        "Il backend ha smesso di rispondere entro il tempo "
                        "concesso. Riavvia il runtime dal Model Hub, oppure "
                        "riduci il budget di token del protocollo."))

        answers = evaluation.complete_batch(
            conversations=[prepared[p][0] for p in positions],
            model_name=target_model,
            max_tokens=budget,
            stop=stop,
            thinking=thinking,
            batch_size=batch_size,
            cancel=cancel,
            on_result=_arrived,
        )
        _raise_if_unavailable([{"fatal": a.fatal, "error": a.error,
                                "diagnosis": a.diagnosis} for a in answers])

        # Un backend che non chiama on_result lascia i risultati qui: si
        # raccolgono comunque, altrimenti il percorso dipenderebbe da una
        # cortesia del backend invece che dal suo valore di ritorno.
        elapsed = max(time.time() - started, 1e-3)
        per_item_ms = int((elapsed / max(len(positions), 1)) * 1000)
        for position, answer in zip(positions, answers):
            if position in results:
                continue
            results[position] = {
                "text": answer.text,
                "tokens": answer.tokens,
                "tokens_per_sec": answer.tokens_per_sec,
                "latency_ms": per_item_ms,
                "error": answer.error,
                "warning": answer.warning,
                "fatal": answer.fatal,
                "diagnosis": answer.diagnosis,
                "batch_size": answer.batch_size,
                "finish_reason": answer.finish_reason,
            }
            if on_item:
                on_item(position, results[position])
    return results


def _dispatch_benchmark_completion(
    item: dict,
    model_name: str,
    pool_endpoints=None,
    timeout: int = 120,
    thinking_mode: str = "auto"
) -> tuple[str, float, int, str, str]:
    """Invia il prompt di benchmark al modello tramite il provider corretto.
    
    Ritorna: (output_text, tok_per_sec, tokens, transport_error, endpoint_used)
    """
    payload = _prepare_benchmark_payload(item, model_name, thinking_mode=thinking_mode)
    system_prompt = payload.get("system", "")
    user_prompt = payload.get("prompt", "")
    max_tokens = payload.get("options", {}).get("num_predict", 512)
    started = time.time()

    # 1. Parsing provider e nome modello
    raw_id = model_name
    provider = "ollama"
    target_model = raw_id

    if raw_id.startswith("sigma:") or raw_id in ("sigma", "sigmaengine"):
        provider = "sigma_engine"
        target_model = raw_id.replace("sigma:", "") if raw_id.startswith("sigma:") else "sigmaengine"
    elif ":" in raw_id:
        parts = raw_id.split(":", 1)
        prefix = parts[0].lower()
        if prefix in ("ollama", "lmstudio", "openai", "deepseek", "anthropic", "groq", "google", "mistral", "openrouter", "together", "xai"):
            provider = prefix
            target_model = parts[1]
        else:
            target_model = raw_id
    else:
        target_model = raw_id

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    tok_limit = max_tokens

    # 2. Routing ed esecuzione
    try:
        # A) SIGMAENGINE (In-Process Diretto o Endpoint Locale)
        if provider == "sigma_engine":
            try:
                # In-process e in modalita' oggettiva. NON passa dal provider
                # server: quello e' dietro un interruttore in "Impostazioni AI
                # -> Providers Hub", e un benchmark che riporta zeri perche' un
                # toggle nella UI e' spento e' peggio di uno che si rifiuta di
                # partire. Il motore e' qui: lo si chiama.
                from core.engine import evaluation

                answer = evaluation.complete(
                    messages=messages,
                    model_name=target_model,
                    max_tokens=tok_limit,
                    stop=payload.get("stop") or (),
                    thinking=False,
                )
                if answer.error and not answer.text:
                    return "", 0, 0, answer.error, f"⚡ SigmaEngine ({target_model})"
                if answer.text:
                    elapsed = time.time() - started
                    tokens = answer.tokens or len(answer.text.split())
                    tok_s = answer.tokens_per_sec or round(tokens / max(elapsed, 0.01), 2)
                    return answer.text, tok_s, tokens, "", f"⚡ SigmaEngine ({target_model})"
            except Exception as in_proc_err:
                log.debug("In-process inference fallback to HTTP: %s", in_proc_err)

            # Fallback HTTP loopback
            endpoint = "http://127.0.0.1:8000/v1/chat/completions"
            body = {
                "model": target_model,
                "messages": messages,
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 42,
                "max_tokens": tok_limit,
                "stop": list(payload.get("stop") or ()),
                "think": False,
                "stream": False
            }
            try:
                resp = requests.post(endpoint, json=body, timeout=timeout)
                if resp.status_code != 200:
                    endpoint = "http://127.0.0.1:5001/v1/chat/completions"
                    resp = requests.post(endpoint, json=body, timeout=timeout)
            except Exception:
                endpoint = "http://127.0.0.1:5001/v1/chat/completions"
                resp = requests.post(endpoint, json=body, timeout=timeout)

            elapsed = time.time() - started
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                text = (choices[0].get("message", {}).get("content", "") if choices else "").strip()
                tokens = data.get("usage", {}).get("completion_tokens") or len(text.split())
                tok_s = round(tokens / max(elapsed, 0.01), 2)
                return text, tok_s, tokens, "", f"⚡ SigmaEngine ({target_model})"
            return "", 0, 0, f"SigmaEngine HTTP {resp.status_code}: {resp.text[:200]}", f"⚡ SigmaEngine ({target_model})"

        # B) OLLAMA
        elif provider == "ollama":
            endpoint = OLLAMA_URL
            ollama_payload = {
                "model": target_model,
                "prompt": user_prompt,
                "system": system_prompt,
                "stream": False,
                # `think: false` spegne il blocco di ragionamento sui modelli
                # che ne hanno uno: senza, il budget di token se ne va nel
                # <think> e la risposta viene troncata prima di comparire.
                # `repeat_penalty: 1.0` toglie il pollice dalla bilancia: la
                # penalita' di ripetizione aiuta la prosa e danneggia
                # l'aritmetica, dove la risposta giusta ripete legittimamente
                # cifre gia' presenti nel prompt.
                "think": False,
                "options": {
                    "temperature": 0.0,
                    "seed": 42,
                    "num_predict": max_tokens,
                    "top_p": 1.0,
                    "top_k": 0,
                    "repeat_penalty": 1.0,
                    "stop": list(payload.get("stop") or ()),
                }
            }
            if pool_endpoints:
                with pool_endpoints.lease() as leased_ep:
                    endpoint = leased_ep
                    resp = requests.post(f"{endpoint}/api/generate", json=ollama_payload, timeout=timeout)
            else:
                resp = requests.post(f"{endpoint}/api/generate", json=ollama_payload, timeout=timeout)

            elapsed = time.time() - started
            if resp.status_code == 200:
                data = resp.json()
                text = (data.get("response") or "").strip()
                if not text:
                    text = (data.get("thinking") or "").strip()
                eval_count = data.get("eval_count") or len(text.split())
                eval_ns = data.get("eval_duration") or 0
                tok_s = (round(eval_count / (eval_ns / 1e9), 2) if eval_ns > 0
                         else round(eval_count / max(elapsed, 0.01), 2))
                return text, tok_s, eval_count, "", f"🐙 Ollama ({endpoint})"
            return "", 0, 0, f"Ollama HTTP {resp.status_code}: {resp.text[:200]}", f"🐙 Ollama ({endpoint})"

        # C) LM STUDIO
        elif provider == "lmstudio":
            endpoint = "http://127.0.0.1:1234/v1/chat/completions"
            body = {
                "model": target_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 42,
                "max_tokens": max_tokens,
                "stop": list(payload.get("stop") or ()),
                "stream": False
            }
            resp = requests.post(endpoint, json=body, timeout=timeout)
            elapsed = time.time() - started
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                text = (choices[0].get("message", {}).get("content", "") if choices else "").strip()
                tokens = data.get("usage", {}).get("completion_tokens") or len(text.split())
                tok_s = round(tokens / max(elapsed, 0.01), 2)
                return text, tok_s, tokens, "", "💻 LM Studio"
            return "", 0, 0, f"LM Studio HTTP {resp.status_code}: {resp.text[:200]}", "💻 LM Studio"

        # D) CLOUD PROVIDERS VIA AI CALL
        else:
            from core.ai_providers import call_ai_model, load_ai_config
            ai_cfg = load_ai_config() or {}
            p_cfg = ai_cfg.get("providers", {}).get(provider, {})
            api_key = p_cfg.get("api_key") or os.environ.get(f"{provider.upper()}_API_KEY", "")
            api_url = p_cfg.get("api_url") or p_cfg.get("endpoint")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            full_res, info, err = call_ai_model(
                messages=messages,
                ai_cfg=ai_cfg,
                model=target_model,
                provider=provider,
                endpoint=p_cfg.get("endpoint"),
                api_url=api_url,
                api_key=api_key,
                temperature=0.0,
                max_tokens=max_tokens,
                top_p=1.0,
                request_timeout=timeout
            )
            elapsed = time.time() - started
            if err:
                return "", 0, 0, f"{provider.upper()} API error: {err}", f"☁️ {provider.upper()}"
            text = (full_res or "").strip()
            tokens = len(text.split())
            tok_s = round(tokens / max(elapsed, 0.01), 2)
            return text, tok_s, tokens, "", f"☁️ {provider.upper()}"

    except Exception as exc:
        elapsed = time.time() - started
        return "", 0, 0, f"Inference exception ({provider}): {exc}", f"{provider}"


def start_benchmark_run(model_name: str, suite_id: str = "all", num_samples: int = 0,
                        mode: str = "full", concurrency="auto", thinking_mode: str = "auto") -> dict:
    """Avvia un run di valutazione su worker paralleli con opzione thinking selezionabile.

    `concurrency` accetta anche "auto": in quel caso il numero di richieste
    contemporanee lo decide `core.training.capacity`, dall'ultima misura del
    modello o, se manca, dalla stima sulla VRAM libera.
    """
    from core.modules.sigma_benchmark_lab.capacity import resolve_concurrency
    from core.modules.sigma_benchmark_lab.model_resolver import resolve_underlying_model

    resolved_model_name = resolve_underlying_model(model_name)
    model_name = resolved_model_name

    job_id = f"bm_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    now = datetime.datetime.now().isoformat()
    suite_meta = OFFICIAL_BENCHMARKS_INFO.get(suite_id, {})
    suite_name = suite_meta.get("name") or ("Tutti i Benchmark Ufficiali" if suite_id == "all" else suite_id.upper())
    is_full = mode == "full" or num_samples == 0
    workers, concurrency_source = resolve_concurrency(model_name, concurrency)

    job = {
        "id": job_id,
        "model": model_name,
        "suite": suite_id,
        "suite_name": suite_name,
        "execution_mode": mode,
        "thinking_mode": thinking_mode,
        "concurrency": workers,
        "concurrency_source": concurrency_source,
        "status": "preparing",
        "progress": 0,
        "created_at": now,
        "updated_at": now,
        "reproducibility": {
            "temperature": 0.0,
            "seed": 42,
            "reproducible_hash": "",
            "mode": "FULL_DATASET_100%_CLEAN" if is_full else "AUDIT_SAMPLE",
            "objective_mode": _is_sigma_model(model_name),
            "answer_protocol": "",
            "prompt_protocol": PROMPT_PROTOCOL,
            "grader": GRADER_VERSION,
            "thinking_mode": thinking_mode,
        },
        "metrics": _empty_metrics(),
    }

    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        benchmarks.insert(0, job)
        _save_benchmarks(benchmarks)

    thread = threading.Thread(
        target=_worker_run_official_benchmark,
        args=(job_id, model_name, suite_id, mode, num_samples, workers, False, thinking_mode),
        daemon=True,
    )
    _active_threads[job_id] = thread
    thread.start()
    return job


def _worker_run_official_benchmark(job_id: str, model_name: str, suite_id: str,
                                   mode: str, num_samples: int, concurrency: int,
                                   is_extension: bool = False, thinking_mode: str | None = None):
    """Rete di sicurezza attorno al run: nessun guasto puo' restare invisibile.

    Un thread daemon che muore per un'eccezione non lascia niente dietro di se':
    il job resta "running" nell'indice, la UI lo interroga all'infinito, i pesi
    restano in VRAM e le schede a zero. Da fuori si vede un blackout senza
    causa. Qui qualunque cosa esca dal run diventa uno stato "failed" con dentro
    la traccia, e il thread viene comunque deregistrato.
    """
    try:
        if is_extension:
            _run_official_benchmark(job_id, model_name, suite_id, mode,
                                    num_samples, concurrency, is_extension=True, thinking_mode=thinking_mode)
        else:
            _run_official_benchmark(job_id, model_name, suite_id, mode,
                                    num_samples, concurrency, thinking_mode=thinking_mode)
    except BaseException as err:                     # anche KeyboardInterrupt
        log.error("Job benchmark %s: worker terminato da %s",
                  job_id, type(err).__name__, exc_info=True)
        try:
            _update_job_state(job_id, {
                "status": "failed",
                "status_message": f"❌ Run interrotto: {type(err).__name__}: {err}",
                "error": "".join(traceback.format_exception(
                    type(err), err, err.__traceback__))[-4000:],
                "updated_at": datetime.datetime.now().isoformat(),
            })
        except Exception as inner:
            log.error("Job benchmark %s: stato non aggiornabile (%s)", job_id, inner)
    finally:
        # L'indice degli esiti vive in memoria durante il run: qui va riversato
        # comunque, anche se il run e' finito male.
        try:
            store.flush_index(job_id)
        except Exception as inner:
            log.warning("Indice di %s non riversato: %s", job_id, inner)
        _active_threads.pop(job_id, None)
        _cancel_requested.discard(job_id)
        _pause_requested.discard(job_id)


# ==============================================================================
# AVVIO: I DUE COSTI CHE NON DIPENDONO L'UNO DALL'ALTRO
# ==============================================================================
# Preparare i quesiti e caricare i pesi sono lavori indipendenti — nessuno dei
# due ha bisogno del risultato dell'altro — e finora si aspettavano in fila. Il
# tempo perso e' il piu' corto dei due: quasi niente con la cache calda (dai
# millisecondi al terzo di secondo), l'intero caricamento del modello quando la
# cache e' fredda e la preparazione dura minuti di rete.
#
# Non si parallelizza sempre. Caricare un modello mentre si costruiscono
# decine di migliaia di dizionari significa chiedere alla macchina due picchi di
# memoria nello stesso istante: su una workstation e' irrilevante, su una
# scheda da 8 GB e' la differenza fra funzionare e andare in swap. La memoria
# libera decide, e sotto la soglia si torna in fila — piu' lento e sicuro.


#: RAM libera sotto la quale il caricamento non si sovrappone alla preparazione.
#: Due picchi di memoria insieme su una macchina che ne ha poca non fanno
#: guadagnare tempo: lo fanno perdere, passando dallo swap.
_RAM_MINIMA_PER_PARALLELO_GB = 4.0


def _ram_disponibile_gb() -> float:
    """RAM libera adesso, o 0 se non si riesce a misurarla."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception as err:
        log.debug("Memoria disponibile non misurabile: %s", err)
        return 0.0


class _CaricamentoAnticipato:
    """Carica i pesi mentre qualcun altro prepara i quesiti.

    Restituisce sempre lo stesso esito che avrebbe dato il caricamento in linea:
    chi lo aspetta non deve sapere se e' partito prima o no. Se l'anticipo non
    e' possibile — poca memoria, modello non locale — l'oggetto esiste lo stesso
    e il caricamento avviene alla prima attesa, esattamente come prima.
    """

    def __init__(self, target: str, consentito: bool):
        self._target = target
        self._esito: dict | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        if consentito:
            self._thread = threading.Thread(
                target=self._carica, name=f"warmup-{target[:24]}", daemon=True)
            self._thread.start()

    def _carica(self) -> None:
        from core.engine.unified_runtime import sigma_engine
        try:
            esito = sigma_engine._ensure_resident(self._target)
        except Exception as err:
            # Il fallimento non si perde: viene consegnato a chi aspetta, con
            # la stessa forma che avrebbe avuto in linea.
            esito = {"success": False, "error": f"{type(err).__name__}: {err}"}
            log.error("Caricamento anticipato di %s fallito: %s",
                      self._target, err, exc_info=True)
        with self._lock:
            self._esito = esito

    def attendi(self) -> dict:
        """L'esito del caricamento, aspettando se serve."""
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            if self._esito is not None:
                return self._esito
        # Nessun anticipo: si carica adesso, in linea.
        from core.engine.unified_runtime import sigma_engine
        return sigma_engine._ensure_resident(self._target)


def _avvia_caricamento(model_name: str) -> "_CaricamentoAnticipato | None":
    """Mette i pesi in moto prima che i quesiti siano pronti, se conviene."""
    if not _is_sigma_model(model_name):
        return None

    libera = _ram_disponibile_gb()
    consentito = libera == 0.0 or libera >= _RAM_MINIMA_PER_PARALLELO_GB
    if not consentito:
        log.info("Caricamento e preparazione restano in fila: %.1f GB liberi, "
                 "sotto la soglia di %.1f.", libera, _RAM_MINIMA_PER_PARALLELO_GB)
    return _CaricamentoAnticipato(_sigma_target(model_name), consentito)


def _run_official_benchmark(job_id: str, model_name: str, suite_id: str,
                            mode: str, num_samples: int, concurrency: int,
                            is_extension: bool = False, thinking_mode: str | None = None):
    """Esegue i quesiti su un pool di worker, versando gli esiti nello store."""
    import concurrent.futures

    from core.modules.sigma_benchmark_lab.endpoints import EndpointPool

    original_thinking_mode = "auto"
    with _benchmark_lock:
        for _j in _load_benchmarks():
            if _j.get("id") == job_id:
                original_thinking_mode = _j.get("thinking_mode") or _j.get("reproducibility", {}).get("thinking_mode") or "auto"
                break

    if thinking_mode is None:
        thinking_mode = original_thinking_mode
    if not thinking_mode:
        thinking_mode = "auto"

    effective_job_thinking_mode = thinking_mode
    if is_extension and original_thinking_mode and original_thinking_mode != thinking_mode:
        effective_job_thinking_mode = "mixed"

    # Con piu' servitori Ollama (uno per GPU) le richieste si alternano fra loro:
    # e' cio' che mette al lavoro tutte le schede invece della sola prima.
    pool_endpoints = EndpointPool()

    # Il download della suite puo' durare minuti: il job resta 'preparing' cosi'
    # la UI non mostra 0% "in corso" mentre in realta' sta scaricando, e ogni
    # suite dice il proprio nome mentre arriva.
    def _announce(message: str) -> None:
        _update_job_state(job_id, {
            "status": "preparing",
            "status_message": message,
            "updated_at": datetime.datetime.now().isoformat(),
        })

    # I pesi partono adesso, mentre i quesiti si preparano: sono due lavori che
    # non si aspettano a vicenda, e finora lo facevano.
    caricamento = _avvia_caricamento(model_name)

    existing_ids = store.get_evaluated_item_ids(job_id) if is_extension else set()
    existing_counts = store.verdict_counts(job_id) if is_extension else {}
    existing_completed = len(existing_ids)

    if is_extension:
        candidate_items = get_benchmark_items(suite_id, mode="full" if mode == "full" else "sample",
                                              num_samples=0 if mode == "full" else (num_samples * 3 + existing_completed),
                                              progress=_announce)
        unseen = [it for it in candidate_items
                  if str(it.get("id", "")) not in existing_ids and str(it.get("prompt", "")) not in existing_ids]
        if mode == "sample" and num_samples > 0:
            items = unseen[:num_samples]
        else:
            items = unseen
        if not items:
            all_items = get_benchmark_items(suite_id, mode="full", progress=_announce)
            unseen_all = [it for it in all_items
                          if str(it.get("id", "")) not in existing_ids and str(it.get("prompt", "")) not in existing_ids]
            items = unseen_all[:num_samples] if num_samples > 0 and mode == "sample" else unseen_all
    else:
        items = get_benchmark_items(suite_id, mode, num_samples, progress=_announce)

    dataset_complete = dataset_is_complete(suite_id)
    # Gli esempi few-shot non possono venire dai quesiti su cui si misura:
    # sarebbe mostrare al modello la risposta prima di chiedergliela.
    register_evaluated_ids(items)
    total = existing_completed + len(items)
    if total == 0 or (len(items) == 0 and not is_extension):
        _update_job_state(job_id, {
            "status": "failed", "progress": 100,
            "error": f"Nessun quesito disponibile per la suite '{suite_id}'",
            "updated_at": datetime.datetime.now().isoformat(),
        })
        _active_threads.pop(job_id, None)
        return
    elif len(items) == 0 and is_extension:
        _update_job_state(job_id, {
            "status": "completed",
            "status_message": "Tutti i quesiti per queste suite sono già stati completati.",
            "updated_at": datetime.datetime.now().isoformat(),
        })
        _active_threads.pop(job_id, None)
        return

    raw_id = model_name
    is_sigma = raw_id.startswith("sigma:") or raw_id in ("sigma", "sigmaengine")
    clean_target = raw_id.replace("sigma:", "") if raw_id.startswith("sigma:") else raw_id

    if is_sigma:
        _update_job_state(job_id, {
            "status": "loading_model",
            "status_message": f"⏳ Caricamento pesi modello '{clean_target}' in memoria VRAM...",
            "progress": min(100, int((existing_completed / total) * 100)) if total else 0,
            "items_planned": total,
            "endpoints": list(pool_endpoints.urls),
            "updated_at": datetime.datetime.now().isoformat(),
        })
    else:
        _update_job_state(job_id, {
            "status": "running",
            "status_message": f"⚡ Avvio inferenza su {model_name}...",
            "progress": min(100, int((existing_completed / total) * 100)) if total else 0,
            "items_planned": total,
            "endpoints": list(pool_endpoints.urls),
            "updated_at": datetime.datetime.now().isoformat(),
        })

    #: Velocita' di una risposta sola su questo hardware, misurata prima del run.
    velocita_chat: dict = {}
    counts: dict[str, int] = dict(existing_counts) if is_extension else {}
    thinking_counts: dict[str, int] = {"passed": 0, "total": 0}
    no_thinking_counts: dict[str, int] = {"passed": 0, "total": 0}
    buffer: list[dict] = []
    #: Quali quesiti hanno prodotto una riga. Un quesito che sparisce fra un
    #: percorso e l'altro non lascia traccia da nessuna parte, e il run finisce
    #: con un punteggio calcolato su meno quesiti di quelli promessi senza che
    #: niente lo dica.
    recorded: set[int] = set(range(existing_completed)) if is_extension else set()
    completed = existing_completed
    tokens_total = latency_sum = 0
    duration_total = 0.0
    if is_extension:
        try:
            with _benchmark_lock:
                for _j in _load_benchmarks():
                    if _j.get("id") == job_id:
                        _m = _j.get("metrics") or {}
                        tokens_total = int(_m.get("total_tokens") or 0)
                        thinking_counts["passed"] = int(_m.get("thinking_passed") or 0)
                        thinking_counts["total"] = int(_m.get("thinking_total") or 0)
                        no_thinking_counts["passed"] = int(_m.get("no_thinking_passed") or 0)
                        no_thinking_counts["total"] = int(_m.get("no_thinking_total") or 0)
                        break
        except Exception:
            pass
    last_progress = time.time()
    lock = threading.Lock()

    def flush(force: bool = False):
        """Versa il buffer su disco e aggiorna metriche/progresso, con freno."""
        nonlocal buffer, last_progress
        with lock:
            if not force and len(buffer) < _FLUSH_EVERY:
                return
            pending, buffer = buffer, []
            snapshot = (dict(counts), completed, tokens_total, duration_total, latency_sum,
                        dict(thinking_counts), dict(no_thinking_counts))
        if pending:
            store.append_results(job_id, pending)
        now = time.time()
        if force or now - last_progress >= _PROGRESS_INTERVAL_SEC:
            last_progress = now
            done_counts, done, toks, dur, lat, th_c, no_th_c = snapshot
            _update_job_state(job_id, {
                "status": "running",
                "status_message": f"⚡ Esecuzione: {done}/{total} quesiti completati ({min(100, int((done / total) * 100))}%)",
                "progress": min(100, int((done / total) * 100)),
                "updated_at": datetime.datetime.now().isoformat(),
                "thinking_mode": effective_job_thinking_mode,
                "metrics": _compute_metrics(done_counts, done, total, toks, dur, lat, th_c, no_th_c),
            })

    def record(index: int, item: dict, output_text: str, tok_per_sec: float,
               tokens: int, transport_error: str, endpoint_used: str,
               latency_ms: int = 0, extra: dict | None = None):
        """Giudica un esito e lo versa nei contatori. Unica strada verso il verdetto."""
        nonlocal completed, tokens_total, latency_sum, duration_total

        if transport_error:
            graded = {
                "verdict": VERDICT_ERROR, "passed": False, "needs_review": True,
                "parsed": {"status": "unparsable", "value": None, "tier": "",
                           "confidence": "none", "candidates": [], "rejected": [],
                           "reason": f"Modello non raggiungibile: {transport_error}"},
            }
            output_text = ""
        else:
            graded = _grade(item, output_text)

        if not latency_ms:
            latency_ms = int((tokens / max(tok_per_sec, 0.01)) * 1000) if tok_per_sec > 0 else 0

        recorded.add(index)
        s_proto = resolve_protocol(item.get("suite", ""), thinking_mode)
        result = {
            "id": item.get("id", f"item_{index}"),
            "index": index,
            "suite": item.get("suite", ""),
            "suite_name": item.get("suite_name", ""),
            "category": item.get("category", ""),
            "prompt": item.get("prompt", ""),
            "options": item.get("options", []),
            "verification": item.get("verification", {}),
            "given_answer": output_text,
            "correct_answer": item.get("correct_answer", ""),
            "correct_choice": item.get("correct_choice", ""),
            "verdict": graded["verdict"],
            "passed": graded["passed"],
            "needs_review": graded["needs_review"],
            "parsed": graded.get("parsed", {}),
            "execution": graded.get("execution"),
            "error": transport_error,
            "endpoint": endpoint_used,
            "tokens_per_sec": tok_per_sec,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "thinking_mode": thinking_mode,
            "is_thinking": s_proto.thinking,
        }
        if extra:
            result.update(extra)

        with lock:
            completed += 1
            tokens_total += tokens
            duration_total += latency_ms / 1000.0
            latency_sum += latency_ms
            counts[graded["verdict"]] = counts.get(graded["verdict"], 0) + 1
            if s_proto.thinking:
                thinking_counts["total"] += 1
                if graded["passed"]:
                    thinking_counts["passed"] += 1
            else:
                no_thinking_counts["total"] += 1
                if graded["passed"]:
                    no_thinking_counts["passed"] += 1
            buffer.append(result)
        flush()

    def process(index: int, item: dict):
        if job_id in _cancel_requested:
            return
        while job_id in _pause_requested:
            if job_id in _cancel_requested:
                return
            time.sleep(0.5)

        output_text, tok_per_sec, tokens, transport_error, endpoint_used = _dispatch_benchmark_completion(
            item=item,
            model_name=model_name,
            pool_endpoints=pool_endpoints,
            timeout=_request_timeout(item.get("suite", "")),
            thinking_mode=thinking_mode,
        )
        record(index, item, output_text, tok_per_sec, tokens,
               transport_error, endpoint_used)

    def run_batched_on_sigma():
        """Esegue tutto il run sul motore locale, in modalita' oggettiva.

        Quattro percorsi, uno per protocollo, scelti dalla suite e non dalla
        forma dell'item:

        * verosimiglianza sulle lettere (MMLU) — una passata in avanti;
        * verosimiglianza sulle continuazioni (HellaSwag, ARC, TruthfulQA) —
          una passata per opzione, tutte in lotto;
        * ragionamento poi risposta (MMLU-Pro, GPQA, BBH, GSM8K, MATH) — con il
          blocco di pensiero **acceso**, perche' quelle suite esistono per
          misurarlo;
        * codice eseguito (HumanEval, MBPP).

        Un quesito che il suo lettore non riesce a decidere non viene contato
        come sbagliato: passa al percorso scritto. Un quesito perso in silenzio
        e' un punteggio falso, e nel conteggio pesa esattamente come un errore
        del modello.
        """
        from core.engine.unified_runtime import sigma_engine

        target = _sigma_target(model_name)

        # I pesi si caricano qui, prima del primo quesito. Due ragioni: un
        # modello che non si carica deve fermare il run subito invece che al
        # primo lotto, e la dimensione del lotto dipende da quale runtime lo
        # serve — un GGUF su llama.cpp decodifica una sequenza alla volta, e
        # chiederla prima del caricamento faceva scrivere "x16" accanto a un
        # lavoro che procedeva uno per uno.
        load = (caricamento.attendi() if caricamento is not None
                else sigma_engine._ensure_resident(target))
        if not load.get("success"):
            raise ModelUnavailable(load.get("error") or "caricamento fallito",
                                   load.get("message") or "")

        batch = sigma_engine.auto_batch_size(concurrency)
        endpoint_used = (f"⚡ SigmaEngine ({target})"
                         + (f" x{batch}" if batch > 1 else " sequenziale"))

        # La velocita' che conta per chi chatta e' quella di una risposta sola,
        # non il totale diviso il tempo di un run a lotti. Sono due numeri
        # diversi e il secondo e' sempre piu' alto: quattro richieste che
        # decodificano insieme producono piu' token al secondo di quanti ne
        # veda chi ne aspetta una. Si misura qui, una volta, e finisce nel
        # certificato accanto all'altro invece che al posto suo.
        try:
            sonda = sigma_engine.benchmark(prompt_tokens=128, decode_tokens=64)
            if sonda.get("success"):
                velocita_chat.update({
                    "decode_tok_s": sonda.get("decode_tok_s", 0),
                    "prefill_tok_s": sonda.get("prefill_tok_s", 0),
                    "prefill_ms": sonda.get("prefill_ms", 0),
                    "backend": sonda.get("backend", ""),
                })
                log.info("Job benchmark %s: velocita' a stream singolo %.1f tok/s "
                         "(prefill %.0f tok/s)", job_id,
                         velocita_chat["decode_tok_s"], velocita_chat["prefill_tok_s"])
        except Exception as err:
            log.debug("Sonda di velocita' non eseguita: %s", err)

        # Un controllo da un decimo di secondo prima del primo quesito: se la
        # verosimiglianza di questo modello e' fuori scala, i punteggi delle
        # suite a continuazione saranno bassi e credibili — la combinazione
        # peggiore. Meglio saperlo adesso e scriverlo nel certificato.
        try:
            calibration = sigma_engine.calibration_check(target)
            if not calibration.get("ok") and not calibration.get("skipped"):
                log.warning("Job benchmark %s: calibrazione sospetta (%s)",
                            job_id, calibration)
                _update_job_state(job_id, {
                    "calibration": calibration,
                    "status_message": (
                        "⚠️ Calibrazione sospetta: le suite decise per "
                        "verosimiglianza potrebbero dare punteggi non "
                        "affidabili su questo modello."),
                    "updated_at": datetime.datetime.now().isoformat(),
                })
            else:
                _update_job_state(job_id, {"calibration": calibration})
        except Exception as err:
            log.debug("Calibrazione non eseguita: %s", err)

        if batch != concurrency:
            # L'intestazione del job dichiarava il numero stimato prima di
            # sapere quale runtime avrebbe servito i pesi: "16x parallelo"
            # sopra un lavoro che procede uno per uno. Ora che il modello e'
            # residente il numero e' noto, e va corretto dove l'utente lo legge.
            _update_job_state(job_id, {
                "concurrency": batch,
                "concurrency_source": (
                    f"lotto da {batch} prompt per passaggio" if batch > 1
                    else "runtime GGUF: una sequenza alla volta"),
                "updated_at": datetime.datetime.now().isoformat(),
            })

        # Ogni quesito va dove dice il protocollo della sua suite, non dove dice
        # la sua forma. MMLU e MMLU-Pro hanno la stessa forma — domanda con
        # opzioni — e si misurano in due modi diversi, perche' MMLU-Pro esiste
        # proprio per premiare il ragionamento che MMLU non chiede.
        by_mode: dict[str, list[int]] = {}
        for position, item in enumerate(items):
            mode = resolve_protocol(item.get("suite", ""), thinking_mode).mode
            if mode in (MODE_LETTER, MODE_CONTINUATION) and not item.get("options"):
                mode = MODE_COT      # un item senza opzioni non si puo' ordinare
            by_mode.setdefault(mode, []).append(position)

        written = list(by_mode.get(MODE_COT, [])) + list(by_mode.get(MODE_CODE, []))
        answer_protocol = ANSWER_PROTOCOL_GENERATIVE

        def cancelled() -> bool:
            return job_id in _cancel_requested

        def wait_if_paused() -> bool:
            while job_id in _pause_requested:
                if cancelled():
                    return False
                time.sleep(0.5)
            return not cancelled()

        class _JobCancel:
            """Il pulsante Ferma, nella forma che il motore sa leggere.

            Senza, l'annullamento arrivava solo fra un lotto e l'altro: su un
            backend che decodifica una sequenza per volta significava aspettare
            l'ultimo quesito della coda, che con un budget da mille token puo'
            essere un quarto d'ora dopo il clic.
            """

            @property
            def cancelled(self) -> bool:
                return job_id in _cancel_requested

            def is_cancelled(self) -> bool:
                return job_id in _cancel_requested

            def __bool__(self) -> bool:
                return job_id in _cancel_requested

        cancel_token = _JobCancel()

        def _score_in_chunks(positions: list[int], runner, protocol_name: str) -> list[int]:
            """Manda un gruppo al suo lettore, e restituisce i quesiti non decisi.

            Non decisi non vuol dire sbagliati: vuol dire che quella lettura non
            si e' potuta fare su quel quesito con quel backend. Vanno riprovati
            scrivendo, non contati come errori — che era il modo piu' rapido di
            far sembrare pessimo un modello che rispondeva benissimo.
            """
            nonlocal answer_protocol
            leftover: list[int] = []
            for start in range(0, len(positions), _SIGMA_CHUNK):
                if not wait_if_paused():
                    return leftover + positions[start:]
                slice_idx = positions[start:start + _SIGMA_CHUNK]
                subset = [items[i] for i in slice_idx]
                scored = runner(subset, target, batch)
                if not scored:
                    leftover.extend(slice_idx)
                    continue
                answer_protocol = protocol_name
                for offset in range(len(subset)):
                    if offset not in scored:
                        leftover.append(slice_idx[offset])
                for offset, outcome in scored.items():
                    local_index = slice_idx[offset]
                    global_index = existing_completed + local_index if is_extension else local_index
                    latency_ms = outcome["latency_ms"]
                    record(
                        global_index, items[local_index], outcome["text"],
                        round(outcome["tokens"] / max(latency_ms / 1000, 1e-3), 2),
                        outcome["tokens"], outcome.get("error", ""),
                        endpoint_used, latency_ms=latency_ms,
                        extra={"choice_probs": outcome.get("choice_probs", {}),
                               "choice_margin": outcome.get("choice_margin", 0.0),
                               "choice_mass": outcome.get("choice_mass", 0.0),
                               "continuation_scores": outcome.get("continuation_scores", []),
                               "answer_protocol": (ANSWER_PROTOCOL_CONSTRAINED
                                                   if outcome.get("constrained")
                                                   else protocol_name)},
                    )
                flush(force=True)
            return leftover

        if by_mode.get(MODE_LETTER):
            written += _score_in_chunks(by_mode[MODE_LETTER],
                                        _run_sigma_choice_scoring,
                                        ANSWER_PROTOCOL_LOGITS)
        if by_mode.get(MODE_CONTINUATION):
            written += _score_in_chunks(by_mode[MODE_CONTINUATION],
                                        _run_sigma_continuation,
                                        ANSWER_PROTOCOL_CONTINUATION)

        written = sorted(set(written))
        for start in range(0, len(written), _WRITTEN_CHUNK):
            if not wait_if_paused():
                return answer_protocol
            slice_idx = written[start:start + _WRITTEN_CHUNK]
            subset = [items[i] for i in slice_idx]

            def _wrote(position, outcome, _slice=slice_idx):
                local_index = _slice[position]
                global_index = existing_completed + local_index if is_extension else local_index
                record(
                    global_index, items[local_index], outcome["text"],
                    outcome.get("tokens_per_sec", 0.0), outcome["tokens"],
                    outcome.get("error", ""), endpoint_used,
                    latency_ms=outcome["latency_ms"],
                    extra={"batch_size": outcome.get("batch_size", 1),
                           "finish_reason": outcome.get("finish_reason", "stop"),
                           "warning": outcome.get("warning", ""),
                           "answer_protocol": ANSWER_PROTOCOL_GENERATIVE},
                )

            _run_sigma_generative(subset, model_name, target, batch,
                                  cancel=cancel_token, on_item=_wrote,
                                  thinking_mode=thinking_mode)
            # Il freno sul progresso salta l'ultima scrittura di un lotto, e
            # l'indice resta indietro di un quesito rispetto agli esiti su
            # disco: si vede come "61/100" accanto a 62 righe. A fine lotto si
            # scrive comunque.
            flush(force=True)
        return answer_protocol

    answer_protocol = ANSWER_PROTOCOL_GENERATIVE
    unavailable: ModelUnavailable | None = None
    crash: BaseException | None = None
    try:
        if is_sigma:
            try:
                answer_protocol = run_batched_on_sigma()
            except ModelUnavailable as err:
                unavailable = err
            except Exception as err:
                # Qualunque altra cosa: un backend che chiude la connessione, un
                # errore di rete, un OOM del driver. Senza questo ramo
                # l'eccezione usciva dal worker e ne uccideva il thread: nessun
                # errore nella UI, il job che restava "running" per sempre, i
                # pesi ancora in VRAM e le schede a zero. Un blackout, dal punto
                # di vista di chi guarda — e non c'era modo di sapere perche'.
                crash = err
                log.error("Job benchmark %s: worker interrotto da %s",
                          job_id, type(err).__name__, exc_info=True)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(process, existing_completed + i if is_extension else i, item)
                           for i, item in enumerate(items)]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as err:
                        log.warning("Quesito benchmark non completato: %s", err)
    finally:
        flush(force=True)

    if unavailable is not None or crash is not None:
        _cancel_requested.discard(job_id)
        _pause_requested.discard(job_id)
        if unavailable is not None:
            titolo = f"❌ Modello non caricabile: {unavailable}"
            dettaglio = unavailable.diagnosis
        else:
            titolo = f"❌ Run interrotto: {type(crash).__name__}: {crash}"
            dettaglio = "".join(traceback.format_exception(
                type(crash), crash, crash.__traceback__))[-4000:]
        _update_job_state(job_id, {
            "status": "failed",
            "status_message": titolo,
            "error": dettaglio,
            # Aggiorna metriche e progresso anche se il run muore a meta': un run
            # interrotto a meta' e' una misura parziale, non una misura persa.
            "progress": min(100, int((completed / total) * 100)) if total else 0,
            "updated_at": datetime.datetime.now().isoformat(),
            "metrics": _compute_metrics(counts, completed, total, tokens_total,
                                        duration_total, latency_sum,
                                        thinking_counts, no_thinking_counts),
        })
        _active_threads.pop(job_id, None)
        log.error("Job benchmark %s interrotto: %s", job_id, unavailable or crash)
        return

    cancelled = job_id in _cancel_requested
    if not cancelled:
        missing = [i for i in range(total) if i not in recorded]
        if missing:
            # Non dovrebbe succedere: se succede, va contato e detto, non
            # nascosto in una divisione con un denominatore piu' piccolo.
            log.error("Job benchmark %s: %d quesiti non hanno prodotto un esito.",
                      job_id, len(missing))
            for index in missing:
                local_index = index - existing_completed if is_extension else index
                item = items[local_index] if 0 <= local_index < len(items) else {"id": f"item_{index}"}
                record(index, item, "", 0.0, 0,
                       "Nessun percorso di valutazione ha prodotto un esito",
                       "—")
            flush(force=True)

    _cancel_requested.discard(job_id)
    _pause_requested.discard(job_id)

    metrics = _compute_metrics(counts, completed, total, tokens_total, duration_total, latency_sum,
                               thinking_counts, no_thinking_counts)
    # L'impronta copre modello, suite ed esito completo: due run identici la
    # riproducono, e un run con conteggi diversi no.
    fingerprint = (f"{model_name}:{suite_id}:{total}:{completed}:"
                   f"{metrics['tests_passed']}:{metrics['tests_failed']}:"
                   f"{metrics['tests_review']}:{tokens_total}:seed42:temp0.0:"
                   f"prompt{PROMPT_PROTOCOL}:{answer_protocol}:{GRADER_VERSION}")
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16].upper()

    _update_job_state(job_id, {
        "status": "cancelled" if cancelled else "completed",
        "status_message": f"Valutazione completata con successo: {metrics['tests_passed']}/{total} superati ({metrics['accuracy_pct']}%)" if not cancelled else "Annullato dall'utente",
        "error": None,
        "progress": min(100, int((completed / total) * 100)) if cancelled else 100,
        "updated_at": datetime.datetime.now().isoformat(),
        "thinking_mode": effective_job_thinking_mode,
        "metrics": metrics,
        "reproducibility": {
            "temperature": 0.0,
            "seed": 42,
            "reproducible_hash": f"SHA256-{digest}",
            "dataset_items_planned": total,
            "dataset_items_processed": completed,
            "dataset_coverage": f"{round((completed / total) * 100, 1)}%",
            "mode": ("FULL_DATASET_100%_CLEAN"
                     if mode == "full" and dataset_complete else "AUDIT_SAMPLE"),
            "dataset_complete": dataset_complete,
            "grader": GRADER_VERSION,
            "prompt_protocol": PROMPT_PROTOCOL,
            "answer_protocol": answer_protocol,
            "thinking_mode": effective_job_thinking_mode,
            # Due velocita', tenute separate perche' misurano cose diverse:
            # `single_stream` e' cio' che sente chi chatta, `tokens_per_sec`
            # nelle metriche e' il totale del run, che con piu' richieste in
            # volo e' sempre piu' alto.
            "single_stream": dict(velocita_chat) if velocita_chat else None,
            "objective_mode": bool(is_sigma),
            # Il protocollo per suite sta nel certificato perche' e' cio' che
            # rende un punteggio confrontabile: due run con lo stesso nome e
            # protocolli diversi misurano cose diverse.
            "protocols": {sid: protocol_describe(sid)
                          for sid in sorted({i.get("suite", "") for i in items})
                          if sid},
        },
    })
    # Deregistrato solo dopo l'ultimo aggiornamento: togliendolo prima, il
    # ricaricamento dell'indice vedeva un job "running" senza worker e lo
    # marcava interrotto un istante prima di scriverlo come completato.
    _active_threads.pop(job_id, None)
    log.info("Job benchmark %s terminato: %s/%s superati, %s da rivedere.",
             job_id, metrics["tests_passed"], completed, metrics["tests_review"])


# ==============================================================================
# CONSULTAZIONE E CONTROLLO DEI JOB
# ==============================================================================

def list_benchmark_jobs() -> list[dict]:
    """Elenco dei job con metriche aggregate, senza il dettaglio dei quesiti."""
    return _load_benchmarks()


def get_job_detail(job_id: str, page: int = 1, page_size: int = 15,
                   verdict: str = "all", suite: str = "all", query: str = "") -> dict:
    """Una pagina di esiti di un job, con riepilogo per suite e per verdetto."""
    job = next((j for j in _load_benchmarks() if j.get("id") == job_id), None)
    if not job:
        return {"success": False, "error": f"Job {job_id} non trovato"}
    payload = store.read_page(job_id, page, page_size, verdict, suite, query)
    payload.update({
        "job": job,
        "verdict_counts": store.verdict_counts(job_id),
        "suite_breakdown": store.suite_breakdown(job_id),
    })
    return payload


def get_review_queue(job_id: str) -> dict:
    """Quesiti da valutare a parte: risposta duplice, illeggibile o in errore."""
    job = next((j for j in _load_benchmarks() if j.get("id") == job_id), None)
    if not job:
        return {"success": False, "error": f"Job {job_id} non trovato"}
    items = store.read_review_queue(job_id)
    return {
        "success": True,
        "job_id": job_id,
        "model": job.get("model", ""),
        "suite": job.get("suite_name") or job.get("suite", ""),
        "count": len(items),
        "verdict_counts": store.verdict_counts(job_id),
        "items": items,
    }


def pause_benchmark_job(job_id: str) -> bool:
    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        for job in benchmarks:
            if job.get("id") == job_id and job.get("status") in ("running", "executing"):
                _pause_requested.add(job_id)
                job["status"] = "paused"
                job["updated_at"] = datetime.datetime.now().isoformat()
                _save_benchmarks(benchmarks)
                log.info("Job benchmark %s: pausa richiesta.", job_id)
                return True
    return False


def resume_benchmark_job(job_id: str) -> bool:
    """Riprende un job in pausa, oppure riavvia l'esecuzione dei quesiti mancanti per un job interrotto o fallito."""
    from core.modules.sigma_benchmark_lab.capacity import resolve_concurrency

    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        job = next((j for j in benchmarks if j.get("id") == job_id), None)
        if not job:
            log.warning("Ripresa benchmark: job %s non trovato.", job_id)
            return False

        status = job.get("status")

        # Se il thread worker è ancora vivo in memoria e il job era semplicemente in pausa
        thread = _active_threads.get(job_id)
        if status == "paused" and thread and thread.is_alive():
            _pause_requested.discard(job_id)
            job["status"] = "running"
            job["updated_at"] = datetime.datetime.now().isoformat()
            _save_benchmarks(benchmarks)
            log.info("Job benchmark %s: ripresa richiesta da stato di pausa (worker attivo).", job_id)
            return True

        # Se il job è fallito, interrotto, o in pausa con thread terminato
        if status in ("paused", "failed", "interrupted", "cancelled"):
            evaluated_ids = store.get_evaluated_item_ids(job_id)
            done_count = len(evaluated_ids)
            planned = int(job.get("items_planned") or 0)
            mode = job.get("execution_mode", "sample")
            model_name = job.get("model", "")
            suite_id = job.get("suite", "all")

            if planned > 0 and done_count >= planned and mode == "sample":
                job["status"] = "completed"
                job["status_message"] = "Tutti i quesiti pianificati sono stati completati."
                job["progress"] = 100
                job["updated_at"] = datetime.datetime.now().isoformat()
                _save_benchmarks(benchmarks)
                return True

            remaining_samples = max(0, planned - done_count) if (planned > 0 and mode == "sample") else 0
            workers, concurrency_source = resolve_concurrency(model_name, job.get("concurrency", "auto"))

            _pause_requested.discard(job_id)
            _cancel_requested.discard(job_id)

            now = datetime.datetime.now().isoformat()
            job["status"] = "preparing"
            job["status_message"] = f"Ripresa benchmark dal quesito {done_count + 1}/{planned or 'totale'}..."
            job["error"] = None
            job["updated_at"] = now
            _save_benchmarks(benchmarks)

            new_thread = threading.Thread(
                target=_worker_run_official_benchmark,
                args=(job_id, model_name, suite_id, mode, remaining_samples, workers, True),
                daemon=True,
            )
            _active_threads[job_id] = new_thread
            new_thread.start()
            log.info("Job benchmark %s: worker riavviato per riprendere da %d/%d quesiti completati.", job_id, done_count, planned)
            return True

    return False


def cancel_benchmark_job(job_id: str) -> bool:
    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        for job in benchmarks:
            if job.get("id") == job_id and job.get("status") in ("running", "paused", "preparing"):
                _pause_requested.discard(job_id)
                _cancel_requested.add(job_id)
                job["status"] = "cancelling"
                job["updated_at"] = datetime.datetime.now().isoformat()
                _save_benchmarks(benchmarks)
                log.info("Job benchmark %s: annullamento richiesto.", job_id)
                return True
    return False


def delete_benchmark_job(job_id: str) -> bool:
    _pause_requested.discard(job_id)
    _cancel_requested.add(job_id)
    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        remaining = [j for j in benchmarks if j.get("id") != job_id]
        if len(remaining) == len(benchmarks):
            return False
        _save_benchmarks(remaining)
    store.delete_results(job_id)
    _active_threads.pop(job_id, None)
    return True


def audit_benchmark_job(job_id: str) -> dict:
    """Verifica che i verdetti di un run reggano, quesito per quesito.

    Un punteggio si legge solo dopo questo: dice quanti verdetti sono stati
    dati per il motivo giusto, e mostra quelli che non lo sono.
    """
    from core.modules.sigma_benchmark_lab.audit import audit_run

    # L'audit guarda il run intero: paginarlo lo renderebbe cieco proprio sui
    # quesiti che non stanno nella prima pagina. `read_page` limita comunque la
    # pagina a un tetto suo, quindi si scorre finche' ci sono pagine.
    rows: list[dict] = []
    page, pages = 1, 1
    while page <= pages:
        chunk = store.read_page(job_id, page=page, page_size=1000)
        rows.extend(chunk.get("results", []))
        pages = chunk.get("pages", 1)
        page += 1
    if not rows:
        return {"success": False, "error": f"Nessun esito salvato per il job '{job_id}'."}
    result = audit_run(rows)
    result["job_id"] = job_id
    return result


def extend_benchmark_job(job_id: str, added_samples: int = 25, additional_suite: str = "",
                         mode: str = "sample", concurrency="auto", thinking_mode: str | None = None) -> dict:
    """Amplia un benchmark esistente aggiungendo nuovi quesiti senza rieseguire quelli già fatti."""
    from core.modules.sigma_benchmark_lab.capacity import resolve_concurrency

    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        job = next((j for j in benchmarks if j.get("id") == job_id), None)
        if not job:
            return {"success": False, "error": f"Job {job_id} non trovato"}
        if job.get("status") in ("running", "loading_model", "preparing", "executing"):
            return {"success": False, "error": "Il job è attualmente in esecuzione"}

        model_name = job.get("model", "")
        suite_id = additional_suite.strip() if additional_suite.strip() else job.get("suite", "all")
        workers, concurrency_source = resolve_concurrency(model_name, concurrency)

        orig_thinking_mode = job.get("thinking_mode") or job.get("reproducibility", {}).get("thinking_mode") or "auto"
        eff_thinking_mode = thinking_mode if thinking_mode else orig_thinking_mode

        now = datetime.datetime.now().isoformat()
        job["status"] = "preparing"
        th_label = "Thinking CoT" if eff_thinking_mode == "thinking" else "No-Thinking" if eff_thinking_mode == "no_thinking" else "Auto"
        job["status_message"] = f"Ampliamento benchmark ({added_samples if mode == 'sample' else 'full'} quesiti, {th_label})..."
        job["updated_at"] = now
        if orig_thinking_mode != eff_thinking_mode:
            job["thinking_mode"] = "mixed"
            if "reproducibility" in job:
                job["reproducibility"]["thinking_mode"] = "mixed"
        else:
            job["thinking_mode"] = eff_thinking_mode
            if "reproducibility" in job:
                job["reproducibility"]["thinking_mode"] = eff_thinking_mode

        if additional_suite.strip() and additional_suite.strip() != "all":
            curr_suites = [s.strip() for s in job.get("suite", "").split(",") if s.strip()]
            if additional_suite.strip() not in curr_suites and job.get("suite") != "all":
                curr_suites.append(additional_suite.strip())
                job["suite"] = ",".join(curr_suites)

        _save_benchmarks(benchmarks)

    thread = threading.Thread(
        target=_worker_run_official_benchmark,
        args=(job_id, model_name, suite_id, mode, added_samples, workers, True, eff_thinking_mode),
        daemon=True,
    )
    _active_threads[job_id] = thread
    thread.start()
    return {"success": True, "job": job}


def rerun_suite_job(job_id: str, suite_id: str, concurrency="auto") -> dict:
    """Riesegue la valutazione di una singola suite sui medesimi quesiti già presenti nel job,
    aggiornando i risultati e i punteggi del job esistente."""
    from core.modules.sigma_benchmark_lab.capacity import resolve_concurrency

    with _benchmark_lock:
        benchmarks = _load_benchmarks()
        job = next((j for j in benchmarks if j.get("id") == job_id), None)
        if not job:
            return {"success": False, "error": f"Job {job_id} non trovato"}
        if job.get("status") in ("running", "loading_model", "preparing", "executing"):
            return {"success": False, "error": "Il job è attualmente in esecuzione"}

        model_name = job.get("model", "")
        clean_suite = suite_id.strip().lower() if suite_id.strip() else "all"
        workers, concurrency_source = resolve_concurrency(model_name, concurrency)

        now = datetime.datetime.now().isoformat()
        job["status"] = "preparing"
        job["status_message"] = f"Riesecuzione valutazione suite {clean_suite.upper()}..."
        job["updated_at"] = now
        _save_benchmarks(benchmarks)

    thread = threading.Thread(
        target=_worker_run_rerun_suite,
        args=(job_id, model_name, clean_suite, workers),
        daemon=True,
    )
    _active_threads[job_id] = thread
    thread.start()
    return {"success": True, "job": job}


def _worker_run_rerun_suite(job_id: str, model_name: str, suite_id: str, concurrency: int):
    """Worker in background per la riesecuzione di una specifica suite."""
    try:
        _run_suite_rerun(job_id, model_name, suite_id, concurrency)
    except BaseException as err:
        log.error("Job benchmark %s: rerun suite %s terminato da %s",
                  job_id, suite_id, type(err).__name__, exc_info=True)
        try:
            _update_job_state(job_id, {
                "status": "failed",
                "status_message": f"❌ Rerun interrotto: {type(err).__name__}: {err}",
                "error": "".join(traceback.format_exception(
                    type(err), err, err.__traceback__))[-4000:],
                "updated_at": datetime.datetime.now().isoformat(),
            })
        except Exception as inner:
            log.error("Job benchmark %s: stato non aggiornabile (%s)", job_id, inner)
    finally:
        try:
            store.flush_index(job_id)
        except Exception as inner:
            log.warning("Indice di %s non riversato: %s", job_id, inner)
        _active_threads.pop(job_id, None)
        _cancel_requested.discard(job_id)
        _pause_requested.discard(job_id)


def _run_suite_rerun(job_id: str, model_name: str, suite_id: str, concurrency: int):
    """Esegue nuovamente i quesiti della suite target conservando le altre suite."""
    from core.modules.sigma_benchmark_lab.endpoints import EndpointPool
    import concurrent.futures

    pool_endpoints = EndpointPool()

    def _announce(message: str) -> None:
        _update_job_state(job_id, {
            "status": "preparing",
            "status_message": message,
            "updated_at": datetime.datetime.now().isoformat(),
        })

    caricamento = _avvia_caricamento(model_name)

    all_results = store.read_all_results(job_id)
    if suite_id == "all":
        other_results = []
        target_results = all_results
    else:
        other_results = [r for r in all_results if (r.get("suite", "").lower() != suite_id.lower())]
        target_results = [r for r in all_results if (r.get("suite", "").lower() == suite_id.lower())]

    suite_datasets = {}
    def get_dataset_map(sid: str):
        sid = sid.lower().strip()
        if sid not in suite_datasets:
            try:
                full = get_benchmark_items(sid, mode="full", progress=_announce)
                suite_datasets[sid] = {
                    "by_id": {str(it.get("id", "")): it for it in full},
                    "by_prompt": {str(it.get("prompt", "")).strip(): it for it in full},
                }
            except Exception as err:
                log.warning("Impossibile caricare dataset %s per rerun: %s", sid, err)
                suite_datasets[sid] = {"by_id": {}, "by_prompt": {}}
        return suite_datasets[sid]

    if not target_results:
        items_to_run = get_benchmark_items(suite_id, mode="sample", num_samples=10, progress=_announce)
    else:
        items_to_run = []
        for r in target_results:
            item_suite = (r.get("suite") or suite_id).lower().strip()
            ds_map = get_dataset_map(item_suite)
            rid = str(r.get("id", ""))
            rprompt = str(r.get("prompt", "")).strip()
            orig = ds_map["by_id"].get(rid) or ds_map["by_prompt"].get(rprompt)
            if orig:
                it = dict(orig)
                it["id"] = r.get("id", orig.get("id"))
                it["index"] = r.get("index", orig.get("index"))
            else:
                verif = r.get("verification") or {}
                if not verif and (r.get("test_list") or r.get("test_code")):
                    verif = {
                        "test_list": r.get("test_list") or [],
                        "test_setup_code": r.get("test_setup_code", ""),
                        "test": r.get("test_code", "") or r.get("tests", ""),
                        "entry_point": r.get("entry_point", ""),
                    }
                it = {
                    "id": r.get("id"),
                    "suite": item_suite,
                    "suite_name": r.get("suite_name", item_suite.upper()),
                    "category": r.get("category", ""),
                    "prompt": r.get("prompt", ""),
                    "options": r.get("options", []),
                    "verification": verif,
                    "correct_answer": r.get("correct_answer", ""),
                    "correct_choice": r.get("correct_choice", ""),
                    "test_code": r.get("test_code", ""),
                    "test_list": r.get("test_list", []),
                    "code": r.get("code", ""),
                    "task_id": r.get("task_id", ""),
                    "canonical_solution": r.get("canonical_solution", ""),
                    "entry_point": r.get("entry_point", ""),
                    "tests": r.get("tests", ""),
                }
            items_to_run.append(it)

    total_target = len(items_to_run)
    total_all = len(other_results) + total_target

    if total_target == 0:
        _update_job_state(job_id, {
            "status": "completed",
            "status_message": f"Nessun quesito da rieseguire per '{suite_id}'.",
            "updated_at": datetime.datetime.now().isoformat(),
        })
        return

    raw_id = model_name
    is_sigma = raw_id.startswith("sigma:") or raw_id in ("sigma", "sigmaengine")
    clean_target = raw_id.replace("sigma:", "") if raw_id.startswith("sigma:") else raw_id

    _update_job_state(job_id, {
        "status": "running",
        "status_message": f"⚡ Riesecuzione {suite_id.upper()}: 0/{total_target} quesiti...",
        "progress": int((len(other_results) / total_all) * 100) if total_all else 0,
        "items_planned": total_all,
        "updated_at": datetime.datetime.now().isoformat(),
    })

    new_suite_results: list[dict] = []
    lock = threading.Lock()

    def process_item(index: int, item: dict):
        if job_id in _cancel_requested:
            return
        while job_id in _pause_requested:
            if job_id in _cancel_requested:
                return
            time.sleep(0.5)

        output_text, tok_per_sec, tokens, transport_error, endpoint_used = _dispatch_benchmark_completion(
            item=item,
            model_name=model_name,
            pool_endpoints=pool_endpoints,
            timeout=_request_timeout(item.get("suite", ""))
        )
        if transport_error:
            graded = {
                "verdict": VERDICT_ERROR, "passed": False, "needs_review": True,
                "parsed": {"status": "unparsable", "value": None, "tier": "",
                           "confidence": "none", "candidates": [], "rejected": [],
                           "reason": f"Modello non raggiungibile: {transport_error}"},
            }
            output_text = ""
        else:
            graded = _grade(item, output_text)

        latency_ms = int((tokens / max(tok_per_sec, 0.01)) * 1000) if tok_per_sec > 0 else 0

        res_obj = {
            "id": item.get("id", f"item_{index}"),
            "index": index,
            "suite": item.get("suite", suite_id),
            "suite_name": item.get("suite_name", suite_id.upper()),
            "category": item.get("category", ""),
            "prompt": item.get("prompt", ""),
            "options": item.get("options", []),
            "verification": item.get("verification", {}),
            "given_answer": output_text,
            "correct_answer": item.get("correct_answer", ""),
            "correct_choice": item.get("correct_choice", ""),
            "verdict": graded["verdict"],
            "passed": graded["passed"],
            "needs_review": graded["needs_review"],
            "parsed": graded.get("parsed", {}),
            "execution": graded.get("execution"),
            "error": transport_error,
            "endpoint": endpoint_used,
            "tokens_per_sec": tok_per_sec,
            "latency_ms": latency_ms,
            "tokens": tokens,
        }
        with lock:
            new_suite_results.append(res_obj)
            done_cnt = len(other_results) + len(new_suite_results)
            prog_pct = min(100, int((done_cnt / total_all) * 100)) if total_all else 0
            _update_job_state(job_id, {
                "status": "running",
                "status_message": f"⚡ Riesecuzione {suite_id.upper()}: {len(new_suite_results)}/{total_target} completati ({prog_pct}%)",
                "progress": prog_pct,
                "updated_at": datetime.datetime.now().isoformat(),
            })

    if is_sigma:
        from core.engine.unified_runtime import sigma_engine
        load = (caricamento.attendi() if caricamento is not None
                else sigma_engine._ensure_resident(clean_target))
        if not load.get("success"):
            raise ModelUnavailable(load.get("error") or "caricamento fallito",
                                   load.get("message") or "")

    worker_count = max(1, min(int(concurrency) if str(concurrency).isdigit() else 4, 16))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(process_item, i, it) for i, it in enumerate(items_to_run)]
        concurrent.futures.wait(futures)

    final_results = other_results + new_suite_results
    store.replace_job_results(job_id, final_results)

    counts: dict[str, int] = {}
    tot_tokens = 0
    tot_lat_ms = 0
    for r in final_results:
        v = r.get("verdict", "pass" if r.get("passed") else "fail")
        counts[v] = counts.get(v, 0) + 1
        tot_tokens += r.get("tokens", 0)
        tot_lat_ms += r.get("latency_ms", 0)

    tot_done = len(final_results)
    tot_dur = tot_lat_ms / 1000.0
    final_metrics = _compute_metrics(counts, tot_done, tot_done, tot_tokens, tot_dur, tot_lat_ms)

    passed_target = sum(1 for r in new_suite_results if r.get("passed"))
    pct_target = round((passed_target / total_target * 100), 1) if total_target else 0.0

    _update_job_state(job_id, {
        "status": "completed",
        "status_message": f"✅ Suite {suite_id.upper()} rieseguita: {passed_target}/{total_target} superati ({pct_target}%). Risultato complessivo: {final_metrics.get('overall_score', 0)}%",
        "progress": 100,
        "metrics": final_metrics,
        "updated_at": datetime.datetime.now().isoformat(),
    })
    store.flush_index(job_id)
