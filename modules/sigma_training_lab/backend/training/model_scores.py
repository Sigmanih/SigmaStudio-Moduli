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
PROTOCOL_RISULTATI = str(module_paths.TRAINING_LAB_DIR / "protocol_benchmark_history.json")

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

    th_p = metriche.get("thinking_passed")
    th_t = metriche.get("thinking_total")
    no_th_p = metriche.get("no_thinking_passed")
    no_th_t = metriche.get("no_thinking_total")
    th_acc = metriche.get("thinking_accuracy")
    no_th_acc = metriche.get("no_thinking_accuracy")
    thinking_mode = job.get("thinking_mode") or riproducibilita.get("thinking_mode", "auto")

    # Se non calcolati in metriche (es. job eseguiti in precedenza):
    if th_t is None or no_th_t is None or (th_t == 0 and no_th_t == 0):
        suites = _suite_per_job(job.get("id"))
        protocols = riproducibilita.get("protocols") or {}
        p_th, t_th = 0, 0
        p_noth, t_noth = 0, 0
        for sid, s in suites.items():
            sp = int(s.get("passed", 0))
            st = int(s.get("total", 0))
            is_th = protocols.get(sid, {}).get("thinking")
            if is_th is None:
                is_th = sid in ("gsm8k", "math", "mmlu_pro", "gpqa", "bbh")
            if is_th:
                p_th += sp
                t_th += st
            else:
                p_noth += sp
                t_noth += st
        th_p, th_t = p_th, t_th
        no_th_p, no_th_t = p_noth, t_noth
        th_acc = round(p_th / t_th * 100, 2) if t_th else 0.0
        no_th_acc = round(p_noth / t_noth * 100, 2) if t_noth else 0.0

    if th_acc is None and th_t:
        th_acc = round(float(th_p or 0) / float(th_t) * 100, 1)
    if no_th_acc is None and no_th_t:
        no_th_acc = round(float(no_th_p or 0) / float(no_th_t) * 100, 1)

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
        "thinking_mode": thinking_mode,
        "thinking_eval": {
            "thinking_score": th_acc,
            "thinking_passed": th_p,
            "thinking_total": th_t,
            "no_thinking_score": no_th_acc,
            "no_thinking_passed": no_th_p,
            "no_thinking_total": no_th_t,
            "thinking_mode": thinking_mode,
        },
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

    # Rilevamento di eventuali run dedicati per Thinking vs No-Thinking
    dedicated_th = [j for j in conclusi if (j.get("thinking_mode") or (j.get("reproducibility") or {}).get("thinking_mode")) == "thinking"]
    dedicated_no_th = [j for j in conclusi if (j.get("thinking_mode") or (j.get("reproducibility") or {}).get("thinking_mode")) == "no_thinking"]
    if dedicated_th and dedicated_no_th:
        best_th = max(dedicated_th, key=lambda j: (j.get("metrics") or {}).get("overall_score", 0))
        best_no_th = max(dedicated_no_th, key=lambda j: (j.get("metrics") or {}).get("overall_score", 0))
        m_th = best_th.get("metrics") or {}
        m_noth = best_no_th.get("metrics") or {}
        referto["thinking_eval"]["thinking_score"] = m_th.get("overall_score", 0)
        referto["thinking_eval"]["thinking_passed"] = m_th.get("tests_passed", 0)
        referto["thinking_eval"]["thinking_total"] = m_th.get("tests_total", 0)
        referto["thinking_eval"]["no_thinking_score"] = m_noth.get("overall_score", 0)
        referto["thinking_eval"]["no_thinking_passed"] = m_noth.get("tests_passed", 0)
        referto["thinking_eval"]["no_thinking_total"] = m_noth.get("tests_total", 0)
        referto["thinking_eval"]["has_dedicated_runs"] = True

    # Arricchimento con il punteggio del benchmark dei tools / protocollo
    t_scores = tool_scores_by_model()
    t_info = t_scores.get(cercato)
    if not t_info:
        coda = cercato.split("/")[-1]
        t_info = next((v for k, v in t_scores.items() if k.split("/")[-1] == coda), None)
    if t_info:
        referto.update(t_info)

    return referto


def _carica_protocol_job() -> List[Dict[str, Any]]:
    """Carica i test di aderenza al protocollo dei tool da protocol_benchmark_history.json."""
    if not os.path.exists(PROTOCOL_RISULTATI):
        return []
    try:
        with open(PROTOCOL_RISULTATI, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception as err:
        log.warning("Storico protocollo illeggibile: %s", err)
        return []


def tool_scores_by_model() -> Dict[str, Dict[str, Any]]:
    """Restituisce il miglior punteggio del benchmark tools per ciascun modello."""
    per_modello: Dict[str, List[Dict[str, Any]]] = {}
    for job in _carica_protocol_job():
        nome = normalizza(job.get("model") or "")
        if nome:
            per_modello.setdefault(nome, []).append(job)

    risultati: Dict[str, Dict[str, Any]] = {}
    for nome, jobs in per_modello.items():
        conclusi = [j for j in jobs if j.get("status") == "completed"]
        best = (max(conclusi, key=lambda j: (j.get("results") or {}).get("punteggio", 0))
                if conclusi else max(jobs, key=lambda j: j.get("created_at") or ""))
        res = best.get("results") or {}
        punteggio = res.get("punteggio")
        superate = res.get("superate")
        totali = res.get("totali")
        risultati[nome] = {
            "tool_score": round(float(punteggio), 1) if punteggio is not None else None,
            "tool_passed": int(superate) if superate is not None else 0,
            "tool_total": int(totali) if totali is not None else 0,
            "tool_turns": res.get("turni_totali"),
            "tool_job_id": best.get("id"),
            "has_tool_benchmark": punteggio is not None,
        }
    return risultati


def scores_by_model(include_suites: bool = False) -> Dict[str, Dict[str, Any]]:
    """Il referto migliore di ogni modello che ne ha almeno uno (ufficiale e/o tools)."""
    per_modello: Dict[str, List[Dict[str, Any]]] = {}
    for job in _carica_job():
        nome = normalizza(job.get("model") or job.get("model_id") or "")
        if nome:
            per_modello.setdefault(nome, []).append(job)

    if not per_modello:
        return {}

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

    # Fonde i risultati dei test di aderenza ai tool per ogni modello
    t_scores = tool_scores_by_model()
    for nome, t_info in t_scores.items():
        if nome in referti:
            referti[nome].update(t_info)
        else:
            # Match sul nome terminale se mancava l'autore
            coda = nome.split("/")[-1]
            matched = next((k for k in referti.keys() if k.split("/")[-1] == coda), None)
            if matched:
                referti[matched].update(t_info)
            else:
                # Modello valutato esclusivamente sul banco di prova dei tools
                referti[nome] = {
                    "model": nome,
                    "has_benchmarks": False,
                    "has_tool_benchmark": True,
                    **t_info
                }

    return referti
