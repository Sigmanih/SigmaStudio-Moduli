"""Contabilita AiloCoin per Sigma Network.

Registro locale di ricevute firmate: il provider emette una ricevuta per il
lavoro svolto, il consumer la controfirma. Il saldo e la somma delle ricevute
con firma valida. Progettato per essere regolato in seguito sulla crypto
AiloNetwork (campo ``settlement_ref``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.modules.sigma_network.identity import sign, verify

logger = logging.getLogger(__name__)

_DEFAULT_WALLET_PATH = "data/sigma_network/wallet.json"

# Campi della ricevuta ESCLUSI dal messaggio firmato.
_SIGNED_EXCLUDED = {"provider_signature", "consumer_signature", "settlement_ref"}


def _signed_payload(receipt: Dict[str, Any]) -> str:
    """Serializzazione deterministica dei campi firmabili della ricevuta.

    Esclude i due campi di firma e ``settlement_ref`` cosi che provider e
    consumer firmino esattamente la stessa stringa.
    """
    payload = {k: v for k, v in receipt.items() if k not in _SIGNED_EXCLUDED}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    """Scrittura atomica: file temporaneo + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


class Wallet:
    """Registro locale di ricevute AiloCoin con persistenza atomica.

    Lo stato e protetto da un lock per la sicurezza in concorrenza (route HTTP
    in lettura, thread di discovery in scrittura).
    """

    def __init__(self, path: str | os.PathLike[str] = _DEFAULT_WALLET_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._receipts: List[Dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> None:
        """Carica le ricevute da disco; se il file non esiste parte da zero."""
        with self._lock:
            if not self._path.exists():
                return
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                receipts = data.get("receipts", [])
                if isinstance(receipts, list):
                    self._receipts = receipts
            except (OSError, json.JSONDecodeError) as exc:
                logger.error("Impossibile caricare il wallet da %s: %s", self._path, exc)
                self._receipts = []

    def _save(self) -> None:
        """Persiste lo stato corrente in modo atomico."""
        with self._lock:
            _atomic_write(self._path, {"receipts": self._receipts})

    # ------------------------------------------------------------- ricevute

    def issue_receipt(
        self,
        request_id: str,
        provider_id: str,
        consumer_id: str,
        model: str,
        tokens: int,
        rate: float,
        private_key_bytes: bytes,
    ) -> Dict[str, Any]:
        """Il provider emette una ricevuta firmata per il lavoro svolto.

        ``amount = tokens / rate``. La firma copre tutti i campi della
        ricevuta tranne le due firme e ``settlement_ref``.
        """
        if rate <= 0:
            raise ValueError("rate deve essere positivo")
        if tokens < 0:
            raise ValueError("tokens non puo essere negativo")

        receipt: Dict[str, Any] = {
            "receipt_id": str(uuid.uuid4()),
            "request_id": request_id,
            "provider_id": provider_id,
            "consumer_id": consumer_id,
            "model": model,
            "tokens": tokens,
            "amount": tokens / rate,
            "created_at": time.time(),
            "provider_signature": None,
            "consumer_signature": None,
            "settlement_ref": None,
        }

        receipt["provider_signature"] = sign(private_key_bytes, _signed_payload(receipt))

        with self._lock:
            self._receipts.append(receipt)
            self._save()

        logger.info(
            "Ricevuta emessa: id=%s provider=%s consumer=%s amount=%.4f",
            receipt["receipt_id"], provider_id, consumer_id, receipt["amount"],
        )
        return receipt

    def countersign(
        self,
        receipt: Dict[str, Any],
        private_key_bytes: bytes,
        provider_public_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Il consumer controfirma la ricevuta.

        Rifiuta (``ValueError``) se la firma del provider non e valida. La
        verifica della firma provider richiede ``provider_public_key``; se non
        fornita, si fa solo un controllo di presenza della firma.

        Aggiorna la ricevuta gia registrata (se presente) o la aggiunge.
        """
        provider_sig = receipt.get("provider_signature")
        if not provider_sig:
            raise ValueError("La ricevuta non ha la firma del provider")

        if provider_public_key is not None:
            payload = _signed_payload(receipt)
            if not verify(provider_public_key, payload, provider_sig):
                raise ValueError("Firma del provider non valida: controfirma rifiutata")

        receipt = dict(receipt)  # copia per non mutare l'originale del chiamante
        receipt["consumer_signature"] = sign(private_key_bytes, _signed_payload(receipt))

        with self._lock:
            self._upsert_receipt(receipt)
            self._save()

        logger.info("Ricevuta controfirmata: id=%s", receipt.get("receipt_id"))
        return receipt

    def verify_receipt(
        self,
        receipt: Dict[str, Any],
        provider_public_key: str,
        consumer_public_key: Optional[str] = None,
    ) -> bool:
        """Verifica che entrambe le firme (provider e consumer) siano valide.

        Se ``consumer_public_key`` e ``None`` o ``consumer_signature`` e assente,
        verifica solo la firma del provider.
        """
        payload = _signed_payload(receipt)

        provider_sig = receipt.get("provider_signature")
        if not provider_sig:
            return False
        if not verify(provider_public_key, payload, provider_sig):
            return False

        consumer_sig = receipt.get("consumer_signature")
        if consumer_sig and consumer_public_key:
            if not verify(consumer_public_key, payload, consumer_sig):
                return False

        return True

    # --------------------------------------------------------------- saldo

    def balance(self, peer_id: str) -> Dict[str, float]:
        """Restituisce ``{balance, earned, spent}`` per il peer indicato.

        ``earned``: somma degli importi dove il peer e provider.
        ``spent``: somma degli importi dove il peer e consumer.
        Solo ricevute con firma provider valida contano (la verifica completa
        richiede le chiavi pubbliche; qui si usa la presenza della firma come
        indicatore, la verifica crittografica e in ``verify_receipt``).
        """
        with self._lock:
            earned = 0.0
            spent = 0.0
            for r in self._receipts:
                if not r.get("provider_signature"):
                    continue
                amount = float(r.get("amount", 0.0))
                if r.get("provider_id") == peer_id:
                    earned += amount
                elif r.get("consumer_id") == peer_id:
                    spent += amount
            return {"balance": earned - spent, "earned": earned, "spent": spent}

    def receipts(self) -> List[Dict[str, Any]]:
        """Storico delle ricevute, ordinate dalla piu recente."""
        with self._lock:
            return sorted(
                (dict(r) for r in self._receipts),
                key=lambda r: r.get("created_at", 0.0),
                reverse=True,
            )

    # ------------------------------------------------------------- interno

    def _upsert_receipt(self, receipt: Dict[str, Any]) -> None:
        """Aggiorna la ricevuta con lo stesso ``receipt_id`` o la aggiunge."""
        rid = receipt.get("receipt_id")
        for i, existing in enumerate(self._receipts):
            if existing.get("receipt_id") == rid:
                self._receipts[i] = receipt
                return
        self._receipts.append(receipt)
