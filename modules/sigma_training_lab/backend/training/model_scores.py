# ==============================================================================
# core/modules/sigma_training_lab/training/model_scores.py
# Il referto di un modello, letto una volta sola e nello stesso modo da tutti
# ==============================================================================
"""Che cosa sappiamo di un modello, dai benchmark che ha effettivamente fatto.

Due posti lo leggevano per conto proprio — l'inventario del Model Hub e il
generatore della scheda per Hugging Face — e sbagliavano gli stessi tre punti,
ognuno a modo suo:

* **il percorso relativo**. `training_lab/official_benchmark_results.json`
  esiste solo se il processo e' partito dalla radice del progetto. Altrove il
  file non si trova, non c'e' errore, e ogni modello risulta "mai valutato".

* **i nomi delle metriche**. Leggevano `passed_count`, `total_count`,
  `avg_tok_s`; il motore scrive `tests_passed`, `tests_total`,
  `tokens_per_sec`. Le chiavi assenti valgono zero, quindi il punteggio
  compariva e accanto "0 quesiti, 0 tok/s" — numeri veri di campi inesistenti.

* **la corrispondenza per sottostringa**. `"google/gemma-4-12b-it" in
  "google/gemma-4-12b-it-gguf-q4_k_m"` e' vero, quindi il checkpoint
  safetensors ereditava il punteggio della sua quantizzazione GGUF. Sono due
  artefatti diversi con due punteggi diversi, ed e' esattamente la confusione
  che un referto deve impedire.

Qui la lettura e' una sola, la corrispondenza e' esatta, e cio' che torna
indietro sono i parametri misurati — non un numero solo.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from core.modules.sigma_training_lab import paths as module_paths

log = get_logger(__name__)

RISULTATI = str(module_paths.OFFICIAL_BENCHMARK_FILE)

#: Prefissi di provider che non fanno parte del nome del modello.
_PREFISSI = re.compile(r"^(?:sigma|ollama|lmstudio|openai|deepseek|anthropic|"
                       r"groq|google|mistral|openrouter|together|xai):",
                       re.IGNORECASE)


def normalizza(identificativo: str) -> str:
    """Il nome di un modello nella forma con cui si confronta.

    `sigma:google--Gemma-4` e `google/gemma-4` sono lo stesso modello scritto
    in due modi: il prefisso indica chi lo serve, il doppio trattino e' come il
    disco rappresenta la barra, e le maiuscole non distinguono niente.
    """
    testo = _PREFISSI.sub("", str(identificativo or "")).strip()
    return testo.replace("--", "/").strip("/").lower()


def _carica_job() -> List[Dict[str, Any]]:
    if not os.path.exists(RISULTATI):
        return []
    try:
        with open(RISULTATI, "r", encoding="utf-8") as fh:
            dati = json.load(fh)
        return dati if isinstance(dati, list) else []
    except Exception as err:
        log.warning("Referti di benchmark illeggibili: %s", err)
        return []


def _referto(job: Dict[str, Any]) -> Dict[str, Any]:
    """Un job nella forma che serve a chi mostra o pubblica."""
    metriche = job.get("metrics") or {}
    riproducibilita = job.get("reproducibility") or {}
    completo = job.get("status") == "completed"

    # Un run interrotto ha uno `overall_score` che divide per i quesiti
    # previsti, non per quelli fatti: pubblicarlo come punteggio del modello
    # significherebbe attribuirgli come errori le domande che non ha visto.
    punteggio = (metriche.get("overall_score") if completo
                 else metriche.get("progress_score", 0))

    return {
        "has_benchmarks": True,
        "job_id": job.get("id"),
        "completed": completo,
        "status": job.get("status", ""),
        "score": round(float(punteggio or 0), 2),
        "decided_accuracy_pct": metriche.get("decided_accuracy_pct", 0),
        "tests_passed": metriche.get("tests_passed", 0),
        "tests_failed": metriche.get("tests_failed", 0),
        "tests_total": metriche.get("tests_total", 0),
        "tests_review": metriche.get("tests_review", 0),
        "tokens_per_sec": metriche.get("tokens_per_sec", 0),
        "avg_latency_ms": metriche.get("avg_latency_ms", 0),
        "suite_name": job.get("suite_name") or job.get("suite") or "Benchmark",
        "suite": job.get("suite", ""),
        "last_run_at": (job.get("created_at") or "")[:16].replace("T", " "),
        # Cio' che rende il punteggio confrontabile con quello di un altro
        # modello: senza queste righe due numeri accanto non vogliono dire
        # niente.
        "reproducible_hash": riproducibilita.get("reproducible_hash", ""),
        "dataset_mode": riproducibilita.get("mode", ""),
        "dataset_complete": riproducibilita.get("dataset_complete"),
        "objective_mode": riproducibilita.get("objective_mode"),
        "prompt_protocol": riproducibilita.get("prompt_protocol"),
        "answer_protocol": riproducibilita.get("answer_protocol", ""),
        "protocols": riproducibilita.get("protocols") or {},
        "temperature": riproducibilita.get("temperature", 0.0),
        "seed": riproducibilita.get("seed", 42),
        # Le due velocita' restano distinte fin qui. `tokens_per_sec` e' il
        # totale del run — con piu' richieste in volo e' sempre piu' alto di
        # quanto veda chi aspetta una risposta sola — e `single_stream` e' la
        # misura di quella singola risposta. Confonderle e' come promettere la
        # portata di un'autostrada a chi chiede quanto ci mette in macchina.
        "single_stream": riproducibilita.get("single_stream") or None,
    }


def _suite_per_job(job_id: str) -> Dict[str, Dict[str, int]]:
    """Passati e totali per suite, letti dall'archivio degli esiti."""
    if not job_id:
        return {}
    try:
        from core.modules.sigma_training_lab.training import benchmark_store as store
        return store.suite_breakdown(job_id)
    except Exception as err:
        log.debug("Dettaglio per suite non disponibile per %s: %s", job_id, err)
        return {}


def scores_for_model(model_id: str, include_suites: bool = True) -> Optional[Dict[str, Any]]:
    """Il referto migliore per questo modello, o None se non ne ha.

    "Migliore" vuol dire: fra i run conclusi, quello con il punteggio piu' alto;
    se non ce ne sono di conclusi, il piu' recente comunque, marcato come
    parziale. Un run a meta' non e' un punteggio da esibire, ma nasconderlo
    farebbe sembrare che il modello non sia mai stato provato.
    """
    cercato = normalizza(model_id)
    if not cercato:
        return None

    candidati: List[Dict[str, Any]] = []
    for job in _carica_job():
        nome = normalizza(job.get("model") or job.get("model_id") or "")
        if not nome:
            continue
        # Corrispondenza esatta, oppure sul solo nome finale quando una delle
        # due forme non porta l'autore. Mai per sottostringa: e' cosi' che una
        # quantizzazione regalava il proprio punteggio al checkpoint originale.
        if nome == cercato or nome.split("/")[-1] == cercato.split("/")[-1]:
            candidati.append(job)

    if not candidati:
        return None

    conclusi = [j for j in candidati if j.get("status") == "completed"]
    if conclusi:
        migliore = max(conclusi,
                       key=lambda j: (j.get("metrics") or {}).get("overall_score", 0))
    else:
        migliore = max(candidati, key=lambda j: j.get("created_at") or "")

    referto = _referto(migliore)
    referto["runs_total"] = len(candidati)
    referto["runs_completed"] = len(conclusi)
    if include_suites:
        referto["suites"] = _suite_per_job(referto.get("job_id"))
    return referto


def scores_by_model(include_suites: bool = False) -> Dict[str, Dict[str, Any]]:
    """Il referto migliore di ogni modello che ne ha almeno uno.

    Serve all'inventario, che deve arricchire decine di modelli in una volta
    sola: chiedere il referto uno per uno rileggerebbe il file una volta per
    modello.
    """
    per_modello: Dict[str, List[Dict[str, Any]]] = {}
    for job in _carica_job():
        nome = normalizza(job.get("model") or job.get("model_id") or "")
        if nome:
            per_modello.setdefault(nome, []).append(job)

    referti: Dict[str, Dict[str, Any]] = {}
    for nome, job in per_modello.items():
        conclusi = [j for j in job if j.get("status") == "completed"]
        migliore = (max(conclusi, key=lambda j: (j.get("metrics") or {}).get("overall_score", 0))
                    if conclusi else max(job, key=lambda j: j.get("created_at") or ""))
        referto = _referto(migliore)
        referto["runs_total"] = len(job)
        referto["runs_completed"] = len(conclusi)
        if include_suites:
            referto["suites"] = _suite_per_job(referto.get("job_id"))
        referti[nome] = referto
    return referti
