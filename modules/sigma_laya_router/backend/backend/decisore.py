# ==============================================================================
# core/modules/sigma_laya_router/backend/decisore.py
# Singleton Laya: caricamento lazy, decisioni System-1 per l'harness
#
# Il modello viene caricato una sola volta al primo uso e resta in memoria.
# Su CPU con 421M parametri pesa ~260 MB in Q4 e risponde in ~30-50 ms.
# Il modulo non importa mai niente dal kernel: e' il kernel che importa lui.
# ==============================================================================
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger("laya_router")

# ──────────────────────────────────────────────────────────────────────── stato

_agent = None
_agent_lock = threading.Lock()
_load_error: Optional[str] = None
_load_time_ms: float = 0.0
_stats = {"calls": 0, "total_ms": 0.0, "errors": 0}


def _get_agent():
    """Carica Laya al primo uso, poi restituisce sempre la stessa istanza."""
    global _agent, _load_error, _load_time_ms
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is not None:
            return _agent
        try:
            import laya
            t0 = time.perf_counter()
            _agent = laya.load()
            _load_time_ms = (time.perf_counter() - t0) * 1000
            log.info(
                "[Laya] Modello caricato in %.0f ms, device=%s",
                _load_time_ms, getattr(_agent, "device", "cpu"),
            )
            return _agent
        except Exception as exc:
            _load_error = str(exc)
            log.error("[Laya] Caricamento fallito: %s", exc)
            return None


# ──────────────────────────────────────────── domande pre-configurate

#: Domande riutilizzabili dall'harness. Ogni chiave e' il nome della decisione,
#: il valore e' il dizionario che Laya si aspetta: type, instructions, criteria.

INTENT_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "intent": {
        "type": "choice",
        "instructions": (
            "Classify the primary intent of the user message. "
            "Pick the single best category."
        ),
        "criteria": {
            "code": "The user wants to write, fix or modify code",
            "analysis": "The user wants to analyze data, review a design or understand something",
            "chat": "The user is making casual conversation, asking a general question or greeting",
            "debug": "The user is reporting a bug, an error or asking to troubleshoot something",
            "system": "The user is asking about system status, configuration or infrastructure",
        },
    },
}

SAFETY_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "safe": {
        "type": "noul",
        "instructions": (
            "Is this user prompt safe, appropriate and non-malicious? "
            "Answer yes if it is a normal, benign request."
        ),
    },
}

QUALITY_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "quality": {
        "type": "score",
        "instructions": (
            "Rate the quality and completeness of this AI assistant response "
            "on a scale from 1 (terrible, incomplete, wrong) to 10 (perfect, "
            "comprehensive, correct)."
        ),
        "low": 1,
        "high": 10,
    },
}

RETRY_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "retry": {
        "type": "choice",
        "instructions": (
            "A tool call just failed with the error shown. "
            "Should the agent retry the same tool, try a different approach, "
            "or give up and report the failure to the user?"
        ),
        "criteria": {
            "retry": "The error is transient (timeout, rate limit, lock); retrying will likely succeed",
            "alternative": "The tool or arguments are wrong; a different approach is needed",
            "abort": "The error is permanent or the task cannot be completed this way",
        },
    },
}

COMPLEXITY_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "complexity": {
        "type": "choice",
        "instructions": (
            "Estimate how complex this task is. A simple task needs one or two "
            "tool calls; a medium task needs a plan with several steps; a hard "
            "task requires research, multiple files or careful design."
        ),
        "criteria": {
            "simple": "Quick answer or one-shot edit, no planning needed",
            "medium": "Several coordinated steps, moderate planning",
            "hard": "Deep research, multi-file changes, architectural decisions",
        },
    },
}


# ──────────────────────────────────────────── risultato

@dataclass
class DecisionResult:
    """Risultato di una decisione Laya, normalizzato per il kernel."""
    raw: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    error: Optional[str] = None

    # scorciatoie per i casi piu' frequenti
    @property
    def intent(self) -> Optional[str]:
        return self.raw.get("intent", {}).get("choice")

    @property
    def intent_confidence(self) -> float:
        return self.raw.get("intent", {}).get("answer_confidence", 0.0)

    @property
    def is_safe(self) -> bool:
        """Vero se la probabilita' di 'unsafe' e' sotto soglia.

        La soglia e' 0.7 e non 0.5 perche' il checkpoint attuale di Laya ha
        temperature non calibrate (il warning all'avvio lo dice), che fanno
        salire il noul anche su prompt innocui. Con 0.7 passano i prompt
        normali e si fermano solo quelli genuinamente pericolosi.
        """
        noul = self.raw.get("safe", {}).get("noul", 1.0)
        return noul < 0.7

    @property
    def safety_score(self) -> float:
        """1.0 = sicurissimo, 0.0 = pericoloso."""
        return 1.0 - self.raw.get("safe", {}).get("noul", 0.0)

    @property
    def quality_score(self) -> Optional[float]:
        return self.raw.get("quality", {}).get("score")

    @property
    def retry_action(self) -> Optional[str]:
        return self.raw.get("retry", {}).get("choice")

    @property
    def complexity(self) -> Optional[str]:
        return self.raw.get("complexity", {}).get("choice")


# ──────────────────────────────────────────── API pubblica

def decide(text: str, questions: Optional[Dict[str, Dict]] = None) -> DecisionResult:
    """Esegue una decisione Laya su un testo.

    Se *questions* non e' specificato, usa INTENT_QUESTIONS + SAFETY_QUESTIONS
    (il caso piu' comune: classificare l'intento e verificare la sicurezza).

    Ritorna sempre un DecisionResult, anche in caso di errore — il chiamante
    non deve gestire eccezioni.
    """
    agent = _get_agent()
    if agent is None:
        return DecisionResult(
            error=_load_error or "Laya non disponibile",
        )

    if questions is None:
        questions = {**INTENT_QUESTIONS, **SAFETY_QUESTIONS}

    t0 = time.perf_counter()
    try:
        raw = agent.decide(text, questions=questions)
        elapsed = (time.perf_counter() - t0) * 1000
        _stats["calls"] += 1
        _stats["total_ms"] += elapsed
        log.debug("[Laya] decide() in %.1f ms: %s", elapsed, raw)
        return DecisionResult(raw=raw, elapsed_ms=elapsed)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        _stats["errors"] += 1
        log.warning("[Laya] decide() fallito in %.1f ms: %s", elapsed, exc)
        return DecisionResult(error=str(exc), elapsed_ms=elapsed)


def classify_intent(text: str) -> DecisionResult:
    """Classifica solo l'intento del prompt, senza guardia di sicurezza."""
    return decide(text, questions=INTENT_QUESTIONS)


def check_safety(text: str) -> DecisionResult:
    """Verifica solo se il prompt e' sicuro."""
    return decide(text, questions=SAFETY_QUESTIONS)


def score_quality(text: str) -> DecisionResult:
    """Valuta la qualita' di una risposta dell'assistente."""
    return decide(text, questions=QUALITY_QUESTIONS)


def decide_retry(error_text: str) -> DecisionResult:
    """Decide se riprovare un tool fallito, cambiare strategia o rinunciare."""
    return decide(error_text, questions=RETRY_QUESTIONS)


def estimate_complexity(text: str) -> DecisionResult:
    """Stima la complessita' di un task: simple / medium / hard."""
    return decide(text, questions=COMPLEXITY_QUESTIONS)


def full_triage(text: str) -> DecisionResult:
    """Triage completo: intento + sicurezza + complessita' in una sola chiamata."""
    questions = {**INTENT_QUESTIONS, **SAFETY_QUESTIONS, **COMPLEXITY_QUESTIONS}
    return decide(text, questions=questions)


# ──────────────────────────────────────────── diagnostica

def status() -> Dict[str, Any]:
    """Stato del modulo per la UI e la diagnostica."""
    loaded = _agent is not None
    avg_ms = (_stats["total_ms"] / _stats["calls"]) if _stats["calls"] else 0.0
    return {
        "loaded": loaded,
        "load_error": _load_error,
        "load_time_ms": round(_load_time_ms, 1),
        "device": str(getattr(_agent, "device", "n/d")) if loaded else "n/d",
        "model_id": str(getattr(_agent, "model_id", "n/d")) if loaded else "n/d",
        "calls": _stats["calls"],
        "errors": _stats["errors"],
        "avg_ms": round(avg_ms, 1),
    }


def preload() -> bool:
    """Carica il modello in anticipo (chiamato all'avvio se si vuole)."""
    return _get_agent() is not None
