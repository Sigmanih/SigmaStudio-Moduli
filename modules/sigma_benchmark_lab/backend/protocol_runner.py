# ==============================================================================
# core/modules/sigma_benchmark_lab/protocol_runner.py
# Runner asincrono per il banco di prova dell'aderenza ai tool (protocol_bench)
# ==============================================================================
"""Gestisce l'esecuzione e il tracciamento dei test di aderenza al protocollo dei tool.

Permette di lanciare le prove di `core.harness.protocol_bench` in background,
sorvegliare l'avanzamento per scenario in tempo reale, archiviare i referti e
renderli interrogabili dall'interfaccia di Benchmark Lab.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from core.modules.sigma_benchmark_lab import paths as module_paths

log = get_logger("protocol_runner")

PROTOCOL_HISTORY_FILE = module_paths.BENCHMARKS_DATA_DIR / "protocol_benchmark_history.json"

_lock = threading.RLock()
_jobs: Dict[str, Dict[str, Any]] = {}
_cancel_flags: Dict[str, bool] = {}
_threads: Dict[str, threading.Thread] = {}


def _save_history(record: Dict[str, Any]) -> None:
    """Archivia un esito di run nel registro storico su disco."""
    try:
        history: List[Dict[str, Any]] = []
        if PROTOCOL_HISTORY_FILE.is_file():
            try:
                history = json.loads(PROTOCOL_HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                history = []
        # Inserisci in cima
        history = [record] + [h for h in history if h.get("id") != record.get("id")]
        # Tieni al massimo 50 record
        history = history[:50]
        tmp = PROTOCOL_HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PROTOCOL_HISTORY_FILE)
    except Exception as exc:
        log.warning("[protocol_runner] impossibile salvare storico: %s", exc)


def _sanitize_job_model(job: Dict[str, Any]) -> Dict[str, Any]:
    """Assicura che il modello assegnato sia sempre il modello concreto sottostante."""
    from core.modules.sigma_benchmark_lab.model_resolver import resolve_underlying_model, GENERIC_ALIASES
    m = str(job.get("model", "")).strip()
    if not m or m.lower() in GENERIC_ALIASES or m.lower() in ("sigma", "test-model"):
        resolved = resolve_underlying_model(m)
        job["model"] = resolved
        if isinstance(job.get("results"), dict):
            job["results"]["model"] = resolved
            for sc in job["results"].get("scenari", []):
                sc["model"] = resolved
    return job


def _load_history() -> List[Dict[str, Any]]:
    """Carica lo storico delle prove completate sanificando i modelli generici."""
    if not PROTOCOL_HISTORY_FILE.is_file():
        return []
    try:
        items = json.loads(PROTOCOL_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(items, list):
            return [_sanitize_job_model(item) for item in items]
        return []
    except Exception as exc:
        log.warning("[protocol_runner] errore lettura storico: %s", exc)
        return []


def get_protocol_scenarios() -> List[Dict[str, Any]]:
    """Elenca gli scenari disponibili con le relative specifiche e livelli di difficolta'."""
    from core.modules.sigma_benchmark_lab.protocol import SCENARI

    return [
        {
            "id": s.id,
            "livello": s.livello,
            "livello_label": s.livello_label,
            "descrizione": s.descrizione,
            "obiettivo": s.obiettivo,
            "criteri": s.criteri,
            "tetto_turni": s.tetto_turni,
            "tetto_secondi": s.tetto_secondi,
            "verifica": s.verifica,
        }
        for s in SCENARI
    ]


def get_protocol_status(job_id: Optional[str] = None) -> Dict[str, Any]:
    """Restituisce lo stato del job indicato o dell'ultimo avviato."""
    with _lock:
        if job_id and job_id in _jobs:
            return _sanitize_job_model(dict(_jobs[job_id]))
        if not job_id and _jobs:
            # Ultimo job in ordine temporale
            latest_id = list(_jobs.keys())[-1]
            return _sanitize_job_model(dict(_jobs[latest_id]))

    # Se non c'è in memoria, cerca nello storico su disco
    history = _load_history()
    if job_id:
        for item in history:
            if item.get("id") == job_id:
                return _sanitize_job_model(item)
    if history:
        return _sanitize_job_model(history[0])

    return {
        "id": "",
        "status": "idle",
        "model": "",
        "progress": 0,
        "message": "Nessuna valutazione protocollo attiva",
    }


def list_protocol_history() -> List[Dict[str, Any]]:
    """Ritorna lo storico dei benchmark di protocollo eseguiti."""
    with _lock:
        mem_jobs = [_sanitize_job_model(dict(j)) for j in _jobs.values()]
    disk_jobs = _load_history()
    
    seen = set()
    combined = []
    # Prima i job in memoria
    for j in reversed(mem_jobs):
        jid = j.get("id")
        if jid and jid not in seen:
            seen.add(jid)
            combined.append(j)
    # Poi lo storico da disco
    for j in disk_jobs:
        jid = j.get("id")
        if jid and jid not in seen:
            seen.add(jid)
            combined.append(j)

    return combined


def cancel_protocol_bench(job_id: str) -> bool:
    """Richiede l'annullamento di una valutazione in corso."""
    with _lock:
        if job_id in _jobs and _jobs[job_id].get("status") == "running":
            _cancel_flags[job_id] = True
            _jobs[job_id]["status"] = "cancelling"
            _jobs[job_id]["message"] = "Annullamento in corso..."
            return True
        return False


def delete_protocol_job(job_id: str) -> bool:
    """Elimina un job di protocollo dallo storico su disco e dalla memoria."""
    with _lock:
        if job_id in _jobs:
            if _jobs[job_id].get("status") == "running":
                _cancel_flags[job_id] = True
            _jobs.pop(job_id, None)
            _cancel_flags.pop(job_id, None)
            _threads.pop(job_id, None)

    try:
        history = _load_history()
        new_history = [j for j in history if j.get("id") != job_id]
        if len(new_history) != len(history):
            PROTOCOL_HISTORY_FILE.write_text(
                json.dumps(new_history, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return True
    except Exception as exc:
        log.error("[protocol_runner] Errore cancellazione job %s: %s", job_id, exc)
        return False



def start_protocol_bench(
    model_name: str,
    scenarios: Optional[List[str]] = None,
    livello: Optional[int] = None,
) -> Dict[str, Any]:
    """Avvia il benchmark dell'aderenza ai tool in un thread in background."""
    from core.modules.sigma_benchmark_lab.protocol import SCENARI, esegui
    from core.modules.sigma_benchmark_lab.model_resolver import resolve_underlying_model

    resolved_model = resolve_underlying_model(model_name)
    model_name = resolved_model

    # Normalizza gli scenari richiesti
    if livello is not None:
        valid_ids = {s.id for s in SCENARI if s.livello == livello}
    else:
        valid_ids = {s.id for s in SCENARI}

    scenari_scelti = [s for s in (scenarios or []) if s in valid_ids] or (list(valid_ids) if livello is not None else None)

    job_id = f"proto_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now().isoformat()

    with _lock:
        # Se c'è già un job 'running', segnalalo
        for j in _jobs.values():
            if j.get("status") == "running":
                return {
                    "success": False,
                    "error": f"C'e' gia' un test di protocollo in corso ({j.get('id')})",
                    "job_id": j.get("id"),
                }

        job: Dict[str, Any] = {
            "id": job_id,
            "model": model_name,
            "status": "running",
            "created_at": now_iso,
            "finished_at": None,
            "scenarios_planned": scenari_scelti or list(valid_ids),
            "current_scenario": None,
            "current_index": 0,
            "total_scenarios": len(scenari_scelti or list(valid_ids)),
            "progress": 0,
            "logs": [],
            "results": None,
            "error": "",
            "message": "Inizializzazione test protocollo...",
        }
        _jobs[job_id] = job
        _cancel_flags[job_id] = False

    def _worker():
        log.info("[protocol_runner] Avvio run %s su modello '%s'", job_id, model_name)

        def should_cancel() -> bool:
            return _cancel_flags.get(job_id, False)

        def on_progresso(evento: Dict[str, Any]) -> None:
            fase = evento.get("fase")
            with _lock:
                if job_id not in _jobs:
                    return
                j = _jobs[job_id]
                if fase == "inizio":
                    sc_id = evento.get("scenario")
                    idx = evento.get("numero", 1)
                    tot = evento.get("totale", 1)
                    j["current_scenario"] = sc_id
                    j["current_index"] = idx
                    j["total_scenarios"] = tot
                    j["progress"] = int(100.0 * (idx - 1) / tot)
                    msg = f"Esecuzione scenario {idx}/{tot}: {sc_id}..."
                    j["message"] = msg
                    j["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                elif fase == "fine":
                    sc_id = evento.get("scenario")
                    superate = evento.get("superate", 0)
                    totali = evento.get("totali", 0)
                    sec = evento.get("secondi", 0.0)
                    msg = f"Scenario '{sc_id}': {superate}/{totali} prove superate in {sec}s"
                    j["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

        try:
            esito = esegui(
                model_name=model_name,
                scenari=scenari_scelti,
                should_cancel=should_cancel,
                progresso=on_progresso,
            )

            with _lock:
                if job_id in _jobs:
                    j = _jobs[job_id]
                    is_cancelled = should_cancel()
                    j["status"] = "cancelled" if is_cancelled else "completed"
                    j["finished_at"] = datetime.now().isoformat()
                    j["progress"] = 100
                    j["results"] = esito
                    j["message"] = (
                        "Test annullato." if is_cancelled
                        else f"Completato con punteggio {esito.get('punteggio', 0.0)}/100"
                    )
                    j["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {j['message']}")
                    _save_history(dict(j))

        except Exception as exc:
            log.error("[protocol_runner] Errore run %s: %s", job_id, exc, exc_info=True)
            with _lock:
                if job_id in _jobs:
                    j = _jobs[job_id]
                    j["status"] = "failed"
                    j["finished_at"] = datetime.now().isoformat()
                    j["error"] = str(exc)
                    j["message"] = f"Errore durante l'esecuzione: {exc}"
                    j["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ERRORE: {exc}")
                    _save_history(dict(j))

    t = threading.Thread(target=_worker, name=f"ProtoBench-{job_id}", daemon=True)
    _threads[job_id] = t
    t.start()

    return {
        "success": True,
        "job_id": job_id,
        "model": model_name,
        "message": f"Test di aderenza protocollo avviato per '{model_name}'",
    }
