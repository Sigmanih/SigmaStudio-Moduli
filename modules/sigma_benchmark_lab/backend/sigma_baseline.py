"""Profilo di partenza di Sigma: misure di coding, senza modificare i pesi."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import threading
import time

from core.logger import get_logger

log = get_logger(__name__)
_prepare_lock = threading.Lock()
ACTIVE_STATUSES = {"preparing", "loading_model", "running", "executing", "pausing", "paused", "cancelling"}

CODE_SUITES = ("humaneval", "mbpp")
MAX_JOBS = 12
MAX_ROWS_PER_SUITE = 800
PROFILE = {
    "id": "sigma-v0",
    "name": "sigma",
    "suite": ",".join(CODE_SUITES),
    "samples": 100,
    "mode": "sample",
    "thinking_mode": "no_thinking",
    "concurrency": 1,
    "temperature": 0.0,
    "seed": 42,
    "optimization_target": {
        "gpu": "RTX 5070 Ti", "vram_gib": 16,
        "weights_budget_gib": 13, "context_tokens": 8192,
        "batch_size": 1, "allow_cpu_offload": False, "allow_second_gpu": False,
    },
}


def is_target(model: str) -> bool:
    if re.fullmatch(r'sigma:sigma(?:[-_.][a-z0-9][a-z0-9_.-]{0,95})?', str(model).strip().lower()):
        return True
    normalized = re.sub(r"[^a-z0-9]", "", str(model).lower())
    return "qwen3827b" in normalized


def failure_category(row: dict) -> str:
    execution = row.get("execution") or {}
    status = execution.get("status")
    if row.get("error"):
        return "inference_error"
    if status == "passed" and row.get("passed") is True:
        return "passed"
    if row.get("finish_reason") == "length":
        return "token_limit"
    if status in ("timeout", "no_code", "no_tests", "error"):
        return status
    if status == "failed":
        detail = execution.get("detail", "")
        if "SyntaxError" in detail or "IndentationError" in detail:
            return "syntax_error"
        if "AssertionError" in detail:
            return "wrong_result"
        return "runtime_error"
    # Un verdetto storico privo di prova eseguibile non certifica correttezza.
    return "unverified"


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def summarize(job: dict, rows: list[dict], truncated: bool = False) -> dict:
    from .sigma_assessment import stable_checkpoint, runtime_signature
    coding = [r for r in rows if r.get("suite") in CODE_SUITES]
    identities = [(r.get("suite"), r.get("id"), r.get("prompt"),
                   r.get("verification")) for r in coding]
    unique = {(r.get("suite"), r.get("id")) for r in coding}
    valid = bool(coding) and len(unique) == len(coding) and all(
        r.get("id") and r.get("prompt") and r.get("verification") for r in coding)
    repro = job.get("reproducibility") or {}
    settings = {k: repro.get(k) for k in ("temperature", "seed", "prompt_protocol", "grader")}
    settings["protocols"] = {s: (repro.get("protocols") or {}).get(s) for s in CODE_SUITES}
    settings["thinking_mode"] = job.get("thinking_mode", repro.get("thinking_mode"))
    settings["answer_protocols"] = sorted({str(r.get("answer_protocol", "")) for r in coding})
    settings['concurrency'] = job.get('concurrency')
    settings['implementation'] = (job.get('execution_environment') or {}).get('evaluation_implementation')
    valid = valid and all(settings[k] is not None for k in (
        "temperature", "seed", "prompt_protocol", "grader", "thinking_mode"))
    valid = valid and all(settings["protocols"].values())
    valid = valid and all(r.get("answer_protocol") for r in coding)
    requested = set(str(job.get('suite', '')).split(','))
    if requested and requested <= set(CODE_SUITES) and type(job.get('total')) is int:
        valid = valid and len(coding) == job['total']
    counts = Counter(failure_category(r) for r in coding)
    by_suite = {}
    for suite in CODE_SUITES:
        selected = [r for r in coding if r["suite"] == suite]
        passed = sum(failure_category(r) == "passed" for r in selected)
        by_suite[suite] = {"total": len(selected), "passed": passed}
    total = len(coding)
    latencies = [r.get("latency_ms", 0) or 0 for r in coding]
    seconds = sum(latencies) / 1000
    tokens = sum(r.get("tokens", 0) or 0 for r in coding)
    environment = job.get('execution_environment') or {}
    stable = (not job.get('checkpoint_history_unverified')
              and runtime_signature(environment) == runtime_signature(environment.get('runtime_after') or {}))
    return {
        "job_id": job["id"], "model": job.get("model"),
        "purpose": job.get('purpose', 'benchmark'),
        "created_at": job.get("created_at"), "status": job.get("status"),
        "total": total, "passed": counts["passed"], "suites": by_suite,
        "pass_at_1_pct": round(100 * counts["passed"] / total, 2) if total else None,
        "failures": {k: n for k, n in counts.items() if k != "passed"},
        "avg_latency_ms": round(sum(latencies) / total) if total else None,
        "tokens_per_second": round(tokens / seconds, 2) if seconds else None,
        "dataset_hash": _digest(sorted(identities, key=lambda x: (str(x[0]), str(x[1])))),
        "settings_hash": _digest(settings),
        "comparable": valid and not truncated and job.get("status") == "completed",
        "truncated": truncated,
        "execution_environment": job.get("execution_environment"),
        "checkpoint_sha256": stable_checkpoint(
            (job.get('execution_environment') or {}).get('checkpoint'),
            (job.get('execution_environment') or {}).get('checkpoint_after')) if stable else None,
        "runtime_signature": runtime_signature(job.get('execution_environment') or {}),
        "cases": [{'id': f"{r.get('suite')}:{r.get('id')}",
                   'passed': failure_category(r) == 'passed',
                   'ended': r.get('finish_reason') != 'length'} for r in coding],
    }


def compare(left: dict, right: dict) -> dict:
    comparable = (left["comparable"] and right["comparable"]
                  and left["dataset_hash"] == right["dataset_hash"]
                  and left["settings_hash"] == right["settings_hash"])
    return {
        "left": left["job_id"], "right": right["job_id"],
        "comparable": comparable,
        "delta_points": round(right["pass_at_1_pct"] - left["pass_at_1_pct"], 2)
        if comparable else None,
    }


def placement_matches_target(settings: dict, placement: dict, gpu_id: int) -> bool:
    return (settings.get("forced_single_gpu") is True
            and settings.get("main_gpu") == gpu_id
            and settings.get("n_ctx") == PROFILE["optimization_target"]["context_tokens"]
            and not settings.get("tensor_split")
            and placement.get("fully_offloaded") is True
            and placement.get("layers_on_cpu") == 0)


def prepare_baseline(model: str) -> dict:
    """Carica il candidato nel vincolo hardware prima di consentire la misura."""
    from . import benchmarks, protocol_runner
    from core.engine.unified_runtime import sigma_engine

    if not _prepare_lock.acquire(blocking=False):
        return {"success": False, "error": "Preparazione di un candidato gia' in corso"}
    try:
        if any(j.get("status") in ACTIVE_STATUSES for j in benchmarks.list_benchmark_jobs()) or any(
                j.get("status") in ACTIVE_STATUSES for j in protocol_runner.list_protocol_history()):
            return {"success": False, "error": "Completa le valutazioni attive prima di cambiare modello"}
        available = benchmarks.get_available_models_for_benchmark()
        if not is_target(model) or not any(m.get("id") == model and not m.get("is_proxy") for m in available):
            return {"success": False, "error": "Seleziona un modello locale compatibile con il profilo sigma"}
        devices = (sigma_engine.hardware_profile or {}).get("accelerators", [])
        target = next((g for g in devices if "5070" in g.get("name", "")
                       and "ti" in g.get("name", "").lower()), None)
        if target is None or target.get("device_id") is None:
            return {"success": False, "error": "RTX 5070 Ti non rilevata: vincolo non verificabile"}
        gpu_id = int(target["device_id"])
        # Il riuso del residente ignora un nuovo contesto: occorre ricaricarlo.
        sigma_engine.unload()
        loaded = sigma_engine.load_native_model(
            model.removeprefix("sigma:"),
            context_tokens=PROFILE["optimization_target"]["context_tokens"],
            target_hardware=f"gpu:{gpu_id}",
            require_full_offload=True,
        )
        if not loaded.get("success"):
            return loaded
        backend = sigma_engine.active_backend_instance
        settings = backend.telemetry() if backend else {}
        placement = backend.describe_placement() if backend else {}
        if not placement_matches_target(settings, placement, gpu_id):
            return {"success": False, "error": "Il candidato non rispetta il vincolo: tutti i layer "
                    "sulla sola 5070 Ti, contesto 8192, senza offload CPU", "placement": placement}
        return {"success": True, "model": model, "gpu": target["name"],
                "context_tokens": settings["n_ctx"], "placement": placement}
    except Exception as exc:
        log.warning("Preparazione candidato Sigma fallita: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        _prepare_lock.release()


def get_baseline_report() -> dict:
    from . import benchmarks, benchmark_store, protocol_runner
    from .sigma_assessment import summarize_agent, associate_runs

    deadline = time.monotonic() + 8
    jobs = [j for j in benchmarks.list_benchmark_jobs() if is_target(j.get("model", ""))]
    runs = []
    partial = False
    for job in jobs[:MAX_JOBS]:
        rows = []
        truncated = False
        for suite in CODE_SUITES:
            for page in range(1, MAX_ROWS_PER_SUITE // 200 + 1):
                if time.monotonic() > deadline:
                    partial = truncated = True
                    break
                data = benchmark_store.read_page(job["id"], page, 200, suite=suite)
                rows.extend(data.get("results", []))
                if page >= data.get("pages", 1):
                    break
            else:
                truncated = truncated or data.get("total", 0) > MAX_ROWS_PER_SUITE
        if rows:
            runs.append(summarize(job, rows, truncated))
        if partial:
            break
    protocols = []
    for job in protocol_runner.list_protocol_history()[:50]:
        if not is_target(job.get("model", "")):
            continue
        protocols.append(summarize_agent(job))
    runtime = {}
    try:
        from core.engine.unified_runtime import sigma_engine
        backend = sigma_engine.active_backend_instance
        if backend:
            settings = backend.telemetry() or {}
            runtime = {k: settings.get(k) for k in (
                "main_gpu", "forced_single_gpu", "split_mode", "tensor_split",
                "n_ctx", "n_gpu_layers", "n_batch", "kv_quant")}
            runtime["placement"] = backend.describe_placement()
            runtime["model"] = sigma_engine.loaded_model_name
    except Exception as exc:
        log.debug("Configurazione corrente del motore non disponibile: %s", exc)
    return {"success": True, "profile": dict(PROFILE), "runs": runs,
            "current_runtime": runtime,
            "protocol_runs": protocols,
            "combined_evaluation": associate_runs(runs, protocols),
            "comparisons": [compare(a, b) for i, a in enumerate(runs) for b in runs[i + 1:]],
            "partial": partial or len(jobs) > MAX_JOBS,
            "note": "Confronto dei dati e protocolli registrati; ambiente e backend storici non certificati. "
                    "Questi quesiti sono di valutazione e non vanno usati come dataset di training."}
