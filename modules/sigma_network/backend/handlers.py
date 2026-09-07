"""Sigma Network — route HTTP locali del modulo (SPEC.md sezione 3).

Sono le route che serve la UI di questa istanza: identita, peer noti, wallet,
impostazioni di condivisione e controllo della scoperta. Le route peer-to-peer,
che parlano con le altre istanze e richiedono verifica di firma, stanno
separate: qui dentro non arriva mai una richiesta di un altro peer.

I singleton sono a livello di modulo e non nel costruttore di un oggetto
perche' il router e' incluso una volta sola nell'app, mentre i test devono
poterli ripuntare su una directory temporanea prima di ogni caso. Da cui
``_reset_singletons()``, che e' parte del contratto verso i test e non un
dettaglio interno.
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from core.modules.sigma_network.ailocoin import Wallet
from core.modules.sigma_network.discovery import PeerDiscovery
from core.modules.sigma_network.identity import (
    load_identity,
    peer_id_from_public_key,
    public_identity,
    sign,
    verify,
)
from core.modules.sigma_network.peer_registry import PeerRegistry
from core.modules.sigma_network.provider import InferenceProvider

log = get_logger("sigma_network.handlers")

router = APIRouter()

MODULE_VERSION = "0.1.0"

#: Percorsi di persistenza. Riassegnabili dai test prima di ``_reset_singletons``.
_identity_file: Optional[str] = None
_peers_file: Optional[str] = None
_wallet_file: Optional[str] = None

_identity: Optional[Dict[str, str]] = None
_registry_instance: Optional[PeerRegistry] = None
_wallet_instance: Optional[Wallet] = None
_discovery_instance: Optional[PeerDiscovery] = None
_settings: Optional[Dict[str, Any]] = None

_lock = threading.RLock()

#: Default di SPEC.md sezione 3. La condivisione parte SPENTA: mettere il
#: proprio hardware a disposizione di sconosciuti e' una decisione esplicita.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "sharing_enabled": False,
    "shared_models": [],
    "rate_tokens_per_coin": 1000,
    "max_tokens_per_request": 4096,
    "max_concurrent": 3,
    "max_requests_per_hour": 60,
    "display_name": "Sigma Peer",
}


def _default_path(filename: str) -> str:
    """Percorso di persistenza sotto data/sigma_network/."""
    from core.paths import project_root

    return str(project_root() / "data" / "sigma_network" / filename)


def _reset_singletons() -> None:
    """Scarta lo stato in memoria, fermando la scoperta se e' attiva.

    Chiamata dai test fra un caso e l'altro. Ferma il thread di discovery
    prima di dimenticarlo: lasciarlo vivo terrebbe un socket UDP aperto per
    tutta la sessione di test e il caso successivo lo troverebbe occupato.
    """
    global _identity, _registry_instance, _wallet_instance, _discovery_instance, _settings

    with _lock:
        if _discovery_instance is not None:
            try:
                _discovery_instance.stop()
            except Exception as exc:  # noqa: BLE001 - lo stop non deve mai propagare
                log.warning("Arresto discovery durante il reset fallito: %s", exc)
        _identity = None
        _registry_instance = None
        _wallet_instance = None
        _discovery_instance = None
        _settings = None


def _get_identity() -> Dict[str, str]:
    global _identity
    with _lock:
        if _identity is None:
            _identity = load_identity(_identity_file or _default_path("identity.json"))
        return _identity


def _get_registry() -> PeerRegistry:
    global _registry_instance
    with _lock:
        if _registry_instance is None:
            _registry_instance = PeerRegistry(_peers_file or _default_path("peers.json"))
        return _registry_instance


def _get_wallet() -> Wallet:
    global _wallet_instance
    with _lock:
        if _wallet_instance is None:
            _wallet_instance = Wallet(_wallet_file or _default_path("wallet.json"))
        return _wallet_instance


def _get_settings() -> Dict[str, Any]:
    global _settings
    with _lock:
        if _settings is None:
            _settings = dict(DEFAULT_SETTINGS)
        return _settings


def _get_discovery() -> PeerDiscovery:
    global _discovery_instance
    with _lock:
        if _discovery_instance is None:
            identity = _get_identity()
            settings = _get_settings()
            _discovery_instance = PeerDiscovery(
                registry=_get_registry(),
                peer_id=identity["peer_id"],
                name=str(settings.get("display_name") or "Sigma Peer"),
                models=list(settings.get("shared_models") or []),
                version=MODULE_VERSION,
            )
        return _discovery_instance


# ---------------------------------------------------------------------------
# Corpi delle richieste
# ---------------------------------------------------------------------------

class PeerAddRequest(BaseModel):
    host: str
    port: int


class PeerTrustRequest(BaseModel):
    peer_id: str
    trusted: bool


class SettingsRequest(BaseModel):
    sharing_enabled: Optional[bool] = None
    shared_models: Optional[List[str]] = None
    rate_tokens_per_coin: Optional[int] = None
    max_tokens_per_request: Optional[int] = None
    max_concurrent: Optional[int] = None
    max_requests_per_hour: Optional[int] = None
    display_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/identity")
def get_identity() -> Dict[str, Any]:
    """Identita pubblica di questo peer. Non espone mai la chiave privata."""
    identity = _get_identity()
    exposed = public_identity(identity)
    return {
        "peer_id": exposed["peer_id"],
        "public_key": exposed["public_key"],
        "name": str(_get_settings().get("display_name") or "Sigma Peer"),
        "version": MODULE_VERSION,
    }


@router.get("/peers")
def list_peers() -> List[Dict[str, Any]]:
    """Tutti i peer noti, in qualunque stato."""
    return _get_registry().all_peers()


@router.post("/peers/add")
def add_peer(body: PeerAddRequest) -> Dict[str, Any]:
    """Aggiunge manualmente un peer per host e porta.

    Il peer entra in stato ``discovered``: l'aggiunta manuale dice dove
    trovarlo, non che ci si fidi di lui. L'identita reale verra' sostituita al
    primo /p2p/hello riuscito; fino ad allora si usa un identificativo
    derivato dall'indirizzo, cosi' che due aggiunte dello stesso host non
    creino due voci.
    """
    if not body.host.strip():
        raise HTTPException(status_code=400, detail="host mancante")
    if not (0 < body.port < 65536):
        raise HTTPException(status_code=400, detail="porta non valida")

    placeholder = f"{body.host}:{body.port}".encode("utf-8")
    provisional_id = peer_id_from_public_key(placeholder)
    return _get_registry().add_peer(
        host=body.host.strip(),
        port=body.port,
        peer_id=provisional_id,
        public_key=base64.b64encode(placeholder).decode("ascii"),
        name=f"{body.host}:{body.port}",
        models=[],
    )


@router.post("/peers/trust")
def set_peer_trust(body: PeerTrustRequest) -> Dict[str, Any]:
    """Promuove un peer a ``trusted`` o lo riporta a ``discovered``."""
    state = "trusted" if body.trusted else "discovered"
    try:
        peer = _get_registry().set_state(body.peer_id, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if peer is None:
        raise HTTPException(status_code=404, detail=f"peer '{body.peer_id}' non trovato")
    return peer


@router.delete("/peers/{peer_id}")
def remove_peer(peer_id: str) -> Dict[str, Any]:
    """Dimentica un peer. 404 se non era noto."""
    if not _get_registry().remove(peer_id):
        raise HTTPException(status_code=404, detail=f"peer '{peer_id}' non trovato")
    return {"removed": True, "peer_id": peer_id}


@router.get("/wallet")
def get_wallet() -> Dict[str, Any]:
    """Saldo AiloCoin di questo peer e storico delle ricevute."""
    wallet = _get_wallet()
    totals = wallet.balance(_get_identity()["peer_id"])
    return {
        "balance": totals.get("balance", 0.0),
        "earned": totals.get("earned", 0.0),
        "spent": totals.get("spent", 0.0),
        "receipts": wallet.receipts(),
    }


@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    """Impostazioni di condivisione correnti."""
    return dict(_get_settings())


@router.post("/settings")
def update_settings(body: SettingsRequest) -> Dict[str, Any]:
    """Aggiorna le impostazioni. I campi assenti restano invariati."""
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    with _lock:
        current = _get_settings()
        current.update(changes)
        return dict(current)


@router.post("/discovery/start")
def start_discovery() -> Dict[str, Any]:
    """Avvia annuncio e ascolto UDP sulla rete locale."""
    try:
        _get_discovery().start()
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"scoperta non avviabile: {exc}") from exc
    return {"running": True}


@router.post("/discovery/stop")
def stop_discovery() -> Dict[str, Any]:
    """Ferma annuncio e ascolto."""
    with _lock:
        if _discovery_instance is not None:
            _discovery_instance.stop()
    return {"running": False}






_provider_instance: Optional[InferenceProvider] = None


def _provider() -> InferenceProvider:
    """Il provider di inferenza di questo nodo, creato alla prima richiesta."""
    global _provider_instance
    with _lock:
        if _provider_instance is None:
            _provider_instance = InferenceProvider()
        return _provider_instance


def _is_inference_engine_available() -> bool:
    """Se il motore locale puo' servire una richiesta adesso.

    Chiamata prima di accettare lavoro da un altro peer: promettere inferenza e
    poi fallire a meta' stream costa al chiamante una moneta e un timeout,
    mentre un 503 gli permette di rivolgersi altrove.
    """
    try:
        from core.engine.unified_runtime import sigma_engine

        return bool(getattr(sigma_engine, "model_instance", None)
                    or getattr(sigma_engine, "active_backend_instance", None))
    except Exception as exc:  # noqa: BLE001 - l'indisponibilita' e' una risposta
        log.warning("Motore non interrogabile: %s", exc)
        return False


@router.get("/p2p/hello")
def p2p_hello() -> Dict[str, Any]:
    """Presentazione di questo peer a chi lo interroga.

    Nome, versione e modelli non stanno nell'identita: l'identita e' la coppia
    di chiavi e non cambia mai, mentre questi sono impostazioni che l'utente
    modifica. Leggerli dal posto sbagliato li restituiva vuoti, e un peer senza
    nome ne' modelli e' indistinguibile da uno che non condivide nulla.
    """
    identity = _get_identity()
    settings = _get_settings()
    return {
        "peer_id": identity["peer_id"],
        "name": str(settings.get("display_name") or "Sigma Peer"),
        "version": MODULE_VERSION,
        "models": list(settings.get("shared_models") or []),
        "accepting": bool(settings.get("sharing_enabled")),
    }


@router.post("/p2p/infer")
def p2p_infer(body: Dict[str, Any]) -> StreamingResponse:
    """Esegue inferenza per conto di un altro peer.

    L'ordine dei controlli non e' arbitrario: prima si stabilisce CHI sta
    parlando, poi si verifica la firma con la chiave pubblica di quel peer.
    Verificare prima di aver trovato il mittente significa non poter usare la
    sua chiave, ed e' una verifica che non verifica.
    """
    peer_id = str(body.get("peer_id") or "")
    signature = body.get("signature")
    message = body.get("message")

    if not peer_id or not signature or not message:
        raise HTTPException(status_code=401, detail="peer_id, message o signature mancanti")

    peer = _get_registry().get(peer_id)
    if peer is None:
        raise HTTPException(status_code=401, detail="Peer sconosciuto")

    if not verify(peer["public_key"], str(message), str(signature)):
        raise HTTPException(status_code=401, detail="Firma non valida")

    if peer.get("state") != "trusted":
        raise HTTPException(status_code=403, detail="Peer non trusted")

    settings = _get_settings()
    ok, motivo = _provider().can_serve(peer_id, _get_registry(), settings)
    if not ok:
        raise HTTPException(status_code=429, detail=motivo)

    payload, errore = _provider().clamp_request(dict(body), settings)
    if errore:
        raise HTTPException(status_code=400, detail=errore)

    if not _is_inference_engine_available():
        raise HTTPException(status_code=503, detail="Motore di inferenza non disponibile")

    def event_generator():
        try:
            for token in _provider().serve(payload):
                yield "data: " + json.dumps({"token": token}, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001 - l'errore deve arrivare al peer
            log.warning("Inferenza per %s interrotta: %s", peer_id, exc)
            yield "data: " + json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream; charset=utf-8"
    )


@router.post("/p2p/receipt")
def p2p_receipt(body: Dict[str, Any]) -> Dict[str, Any]:
    """Controfirma una ricevuta emessa da un peer che ha svolto lavoro per noi.

    La ricevuta arriva gia' firmata dal provider: qui si aggiunge la seconda
    firma, quella del consumer, sullo STESSO documento. Costruirne uno nuovo
    lascerebbe le due parti con due carte diverse, ed e' il contrario di cio'
    che serve quando piu' avanti andranno regolate su AiloNetwork.

    Come su /p2p/infer, la firma del chiamante si verifica con la chiave
    pubblica del chiamante: quella di questo nodo non dice nulla su chi ha
    mandato la richiesta.
    """
    receipt = body.get("receipt")
    peer_id = str(body.get("peer_id") or "")
    signature = body.get("signature")
    message = body.get("message")

    if not isinstance(receipt, dict) or not peer_id or not signature or not message:
        raise HTTPException(
            status_code=400, detail="receipt, peer_id, message e signature sono obbligatori"
        )

    peer = _get_registry().get(peer_id)
    if peer is None:
        raise HTTPException(status_code=401, detail="Peer sconosciuto")

    if not verify(peer["public_key"], str(message), str(signature)):
        raise HTTPException(status_code=401, detail="Firma non valida")

    if peer.get("state") != "trusted":
        raise HTTPException(status_code=403, detail="Peer non trusted")

    identity = _get_identity()
    try:
        controfirmata = _get_wallet().countersign(
            receipt,
            base64.b64decode(identity["private_key"]),
            provider_public_key=peer["public_key"],
        )
    except ValueError as exc:
        # La firma del provider non regge: la ricevuta non descrive un lavoro
        # che quel peer possa dimostrare di aver svolto.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"countersigned": controfirmata}


@router.post('/inference/remote')
def inference_remote(body: dict):
    identity = _get_identity()
    signature = body.get('signature')
    message = body.get('message')
    remote_peer_id = body.get('remote_peer_id')
    
    if not signature or not message:
        raise HTTPException(status_code=401, detail='Firma o header mancanti')
    
    if not verify(identity['public_key'], message, signature):
        raise HTTPException(status_code=401, detail='Firma non valida')
    
    registry = _get_registry()
    remote_peer = registry.get(remote_peer_id)
    if not remote_peer or remote_peer['state'] != 'trusted':
        raise HTTPException(status_code=403, detail='Peer remoto non trusted')
    
    # Implementazione dell'inferenza SSE verso un peer remoto
    # (Assumendo che ci sia un motore di inferenza disponibile)
    if not _is_inference_engine_available():
        raise HTTPException(status_code=503, detail='Motore di inferenza non disponibile')
    
    # Esempio di SSE
    def event_generator():
        yield 'data: Inizio inferenza remota\n\n'
        # Implementazione dell'inferenza verso il peer remoto
        # yield f'data: {risultato}\n\n'
        yield 'data: Fine inferenza remota\n\n'
    
    return StreamingResponse(event_generator(), media_type='text/event-stream; charset=utf-8')
