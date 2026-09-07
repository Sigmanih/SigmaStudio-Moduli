"""Sigma Network — Inference Provider.

Serve le richieste di inferenza in arrivo dagli altri peer.

VINCOLO DI SICUREZZA: questo modulo espone SOLO generazione di testo.
Non importa e non invoca terminal, filesystem o tool del Developer Studio.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


class InferenceProvider:
    """Riceve richieste di inferenza da peer remoti e le serve localmente."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_requests: int = 0
        # finestra oraria: (timestamp_fine, token_budget_rirestante)
        self._window_end: float = 0.0
        self._window_budget: int = 0
        self._total_tokens_served: int = 0

    # ------------------------------------------------------------------
    # can_serve
    # ------------------------------------------------------------------
    def can_serve(
        self,
        peer_id: str,
        registry: Any,
        settings: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Verifica se il provider puo servire la richiesta.

        Restituisce (True, "") oppure (False, motivo).
        """
        # 1. sharing disattivato
        if not settings.get("sharing_enabled", False):
            return False, "sharing disattivato"

        # 2. peer non trusted
        trust = registry.get_trust(peer_id) if hasattr(registry, "get_trust") else None
        if trust != "trusted":
            return False, f"peer {peer_id} non trusted"

        now = time.monotonic()
        max_concurrent = int(settings.get("max_concurrent_requests", 4))
        window_seconds = float(settings.get("window_seconds", 3600))
        window_budget = int(settings.get("tokens_per_window", 100_000))

        with self._lock:
            # 3. limite concorrenti
            if self._active_requests >= max_concurrent:
                return False, "limite di richieste concorrenti raggiunto"

            # 4. limite orario
            if now >= self._window_end:
                self._window_end = now + window_seconds
                self._window_budget = window_budget
            if self._window_budget <= 0:
                return False, "limite orario di token raggiunto"

        return True, ""

    # ------------------------------------------------------------------
    # clamp_request
    # ------------------------------------------------------------------
    def clamp_request(
        self,
        payload: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Normalizza la richiesta: max_tokens e modello condiviso.

        Restituisce (payload_modificato, None) oppure ({}, errore).
        """
        # modello
        model = payload.get("model", "")
        shared_models: List[str] = settings.get("shared_models", [])
        if model not in shared_models:
            return {}, False

        # max_tokens
        max_allowed = int(settings.get("max_tokens_per_request", 2048))
        requested = int(payload.get("max_tokens", max_allowed))
        clamped = min(requested, max_allowed)
        if clamped <= 0:
            return {}, False

        payload["max_tokens"] = clamped
        return payload, True

    # ------------------------------------------------------------------
    # serve
    # ------------------------------------------------------------------
    def serve(self, payload: Dict[str, Any]) -> Generator[str, None, None]:
        """Generatore che produce i token chiamando l'engine locale.

        Conta i token realmente prodotti e aggiorna i contatori.
        """
        from core.engine.unified_runtime import sigma_engine  # noqa: import ritardato

        prompt = payload.get("prompt", "")
        model = payload.get("model", "")
        max_tokens = int(payload.get("max_tokens", 2048))

        with self._lock:
            self._active_requests += 1

        tokens_produced = 0
        try:
            for token in sigma_engine.generate_stream(
                prompt=prompt,
                model=model,
                max_tokens=max_tokens,
            ):
                tokens_produced += 1
                yield token
        finally:
            with self._lock:
                self._active_requests -= 1
                self._total_tokens_served += tokens_produced
                if self._window_budget > 0:
                    self._window_budget -= tokens_produced
