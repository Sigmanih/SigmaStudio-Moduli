# ==============================================================================
# core/modules/sigma_laya_router/backend/handlers.py
# HTTP Route Handlers per il Laya Decision Router
# ==============================================================================
from __future__ import annotations

import json
from core.logger import get_logger
from . import decisore

log = get_logger(__name__)


# ──────────────────────────────────────────── GET

def handle_laya_status(self):
    """GET /api/laya/status — Stato del modello e statistiche."""
    return self.send_json_response({
        "success": True,
        **decisore.status(),
    })


# ──────────────────────────────────────────── POST

def handle_laya_decide(self):
    """POST /api/laya/decide — Decisione generica.

    Body:
        text (str): il testo da valutare
        questions (dict, opzionale): domande personalizzate
    """
    try:
        body = self.read_json_body()
        text = body.get("text", "")
        if not text:
            return self.send_json_response(
                {"success": False, "error": "campo 'text' obbligatorio"}, 400
            )
        questions = body.get("questions")
        result = decisore.decide(text, questions=questions)
        return self.send_json_response({
            "success": result.error is None,
            "result": result.raw,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "error": result.error,
        })
    except Exception as exc:
        log.error("[Laya] handle_laya_decide: %s", exc)
        return self.send_json_response(
            {"success": False, "error": str(exc)}, 500
        )


def handle_laya_classify(self):
    """POST /api/laya/classify — Classificazione dell'intento.

    Body:
        text (str): il prompt dell'utente
    """
    try:
        body = self.read_json_body()
        text = body.get("text", "")
        if not text:
            return self.send_json_response(
                {"success": False, "error": "campo 'text' obbligatorio"}, 400
            )
        result = decisore.classify_intent(text)
        return self.send_json_response({
            "success": result.error is None,
            "intent": result.intent,
            "confidence": round(result.intent_confidence, 4),
            "probabilities": result.raw.get("intent", {}).get("probabilities", {}),
            "elapsed_ms": round(result.elapsed_ms, 1),
            "error": result.error,
        })
    except Exception as exc:
        log.error("[Laya] handle_laya_classify: %s", exc)
        return self.send_json_response(
            {"success": False, "error": str(exc)}, 500
        )


def handle_laya_safety(self):
    """POST /api/laya/safety — Guardia di sicurezza.

    Body:
        text (str): il prompt da verificare
    """
    try:
        body = self.read_json_body()
        text = body.get("text", "")
        if not text:
            return self.send_json_response(
                {"success": False, "error": "campo 'text' obbligatorio"}, 400
            )
        result = decisore.check_safety(text)
        return self.send_json_response({
            "success": result.error is None,
            "safe": result.is_safe,
            "safety_score": round(result.safety_score, 4),
            "elapsed_ms": round(result.elapsed_ms, 1),
            "error": result.error,
        })
    except Exception as exc:
        log.error("[Laya] handle_laya_safety: %s", exc)
        return self.send_json_response(
            {"success": False, "error": str(exc)}, 500
        )


def handle_laya_triage(self):
    """POST /api/laya/triage — Triage completo: intento + sicurezza + complessita'.

    Body:
        text (str): il prompt dell'utente
    """
    try:
        body = self.read_json_body()
        text = body.get("text", "")
        if not text:
            return self.send_json_response(
                {"success": False, "error": "campo 'text' obbligatorio"}, 400
            )
        result = decisore.full_triage(text)
        return self.send_json_response({
            "success": result.error is None,
            "intent": result.intent,
            "intent_confidence": round(result.intent_confidence, 4),
            "safe": result.is_safe,
            "safety_score": round(result.safety_score, 4),
            "complexity": result.complexity,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "error": result.error,
        })
    except Exception as exc:
        log.error("[Laya] handle_laya_triage: %s", exc)
        return self.send_json_response(
            {"success": False, "error": str(exc)}, 500
        )


def handle_laya_quality(self):
    """POST /api/laya/quality — Scoring qualita' di una risposta.

    Body:
        text (str): la risposta dell'assistente da valutare
    """
    try:
        body = self.read_json_body()
        text = body.get("text", "")
        if not text:
            return self.send_json_response(
                {"success": False, "error": "campo 'text' obbligatorio"}, 400
            )
        result = decisore.score_quality(text)
        return self.send_json_response({
            "success": result.error is None,
            "score": result.quality_score,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "error": result.error,
        })
    except Exception as exc:
        log.error("[Laya] handle_laya_quality: %s", exc)
        return self.send_json_response(
            {"success": False, "error": str(exc)}, 500
        )


def handle_laya_preload(self):
    """POST /api/laya/preload — Carica il modello in anticipo."""
    try:
        ok = decisore.preload()
        return self.send_json_response({
            "success": ok,
            **decisore.status(),
        })
    except Exception as exc:
        log.error("[Laya] handle_laya_preload: %s", exc)
        return self.send_json_response(
            {"success": False, "error": str(exc)}, 500
        )


# ──────────────────────────────────────────── registrazione

def register_routes(app=None) -> None:
    """Registra tutte le route HTTP di Laya Router su FastAPIHandlerAdapter."""
    get_routes = {
        "/api/laya/status": handle_laya_status,
    }
    post_routes = {
        "/api/laya/decide": handle_laya_decide,
        "/api/laya/classify": handle_laya_classify,
        "/api/laya/safety": handle_laya_safety,
        "/api/laya/triage": handle_laya_triage,
        "/api/laya/quality": handle_laya_quality,
        "/api/laya/preload": handle_laya_preload,
    }

    try:
        from core.fastapi_app import FastAPIHandlerAdapter
        for path, fn in get_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._GET_HANDLERS[path] = fn.__name__
        for path, fn in post_routes.items():
            setattr(FastAPIHandlerAdapter, fn.__name__, fn)
            FastAPIHandlerAdapter._POST_HANDLERS[path] = fn.__name__
        log.info("[sigma_laya_router] Route Laya registrate su FastAPIHandlerAdapter.")
    except Exception as exc:
        log.warning("[sigma_laya_router] Binding FastAPIHandlerAdapter fallito: %s", exc)
