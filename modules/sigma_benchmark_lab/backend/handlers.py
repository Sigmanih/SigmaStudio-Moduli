# ==============================================================================
# core/modules/sigma_benchmark_lab/handlers.py
# HTTP routes & MCP server registration per Benchmark Lab
# ==============================================================================
from __future__ import annotations

import json
from urllib.parse import urlparse, parse_qs
from typing import Any

from core.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------- helpers

def _query(handler, key: str, default: str = "") -> str:
    return parse_qs(urlparse(handler.path).query).get(key, [default])[0]


def _query_int(handler, key: str, default: int) -> int:
    try:
        return int(_query(handler, key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _job_id(handler) -> str:
    from_query = _query(handler, "job_id") or _query(handler, "id")
    if from_query:
        return from_query
    body = handler.read_json_body()
    return body.get("job_id") or body.get("id") or ""


# ---------------------------------------------------------------- endpoints

def handle_benchmark_models(self):
    from core.modules.sigma_benchmark_lab.benchmarks import get_benchmark_models_payload
    self.send_json_response(get_benchmark_models_payload())


def handle_benchmark_jobs(self):
    from core.modules.sigma_benchmark_lab.benchmarks import list_benchmark_jobs
    self.send_json_response(list_benchmark_jobs())


def handle_benchmark_results(self):
    from core.modules.sigma_benchmark_lab.benchmarks import get_job_detail
    self.send_json_response(get_job_detail(
        job_id=_job_id(self),
        page=_query_int(self, "page", 1),
        page_size=_query_int(self, "page_size", 15),
        verdict=_query(self, "verdict", "all"),
        suite=_query(self, "suite", "all"),
        query=_query(self, "q", ""),
    ))


def handle_benchmark_audit(self):
    from core.modules.sigma_benchmark_lab.benchmarks import audit_benchmark_job
    self.send_json_response(audit_benchmark_job(
        _query(self, "id") or _query(self, "job_id")
        or self.read_json_body().get("id", "")))


def handle_benchmark_review(self):
    from core.modules.sigma_benchmark_lab.benchmarks import get_review_queue
    self.send_json_response(get_review_queue(_job_id(self)))


def handle_benchmark_capacity(self):
    from core.modules.sigma_benchmark_lab.capacity import estimate_capacity, get_profile
    model = _query(self, "model")
    if not model:
        return self.send_json_response({"success": False, "error": "Parametro 'model' mancante"}, 400)
    self.send_json_response({
        "success": True,
        "model": model,
        "estimate": estimate_capacity(model),
        "profile": get_profile(model),
    })


def handle_benchmark_capacity_probe(self):
    from core.modules.sigma_benchmark_lab.capacity import DEFAULT_LEVELS, start_capacity_probe
    body = self.read_json_body()
    model = body.get("model", "")
    if not model:
        return self.send_json_response({"success": False, "error": "Parametro 'model' mancante"}, 400)
    levels = body.get("levels") or list(DEFAULT_LEVELS)
    self.send_json_response(start_capacity_probe(model, levels))


def handle_benchmark_capacity_status(self):
    from core.modules.sigma_benchmark_lab.capacity import get_probe_status
    self.send_json_response(get_probe_status(_query(self, "probe_id")))


def handle_benchmark_endpoints(self):
    from core.modules.sigma_benchmark_lab.capacity import cuda_devices
    from core.modules.sigma_benchmark_lab.endpoints import (
        active_endpoints, free_port, instance_command, managed_instances
    )

    endpoints = active_endpoints()
    bound = {e.get("gpu_index") if e.get("gpu_index") is not None else 0
             for e in endpoints if e.get("reachable")}
    devices = cuda_devices()

    port = free_port()
    suggestions = []
    for device in devices:
        if device["index"] in bound:
            continue
        suggestions.append({
            "gpu": device,
            **instance_command(device["index"], port + len(suggestions), device.get("backend", "cuda")),
        })

    self.send_json_response({
        "success": True,
        "endpoints": endpoints,
        "gpus": devices,
        "managed": managed_instances(),
        "suggestions": suggestions,
    })


def handle_benchmark_endpoint_start(self):
    from core.modules.sigma_benchmark_lab.capacity import cuda_devices
    from core.modules.sigma_benchmark_lab.endpoints import start_instance

    body = self.read_json_body()
    if body.get("gpu_index") is None:
        return self.send_json_response({"success": False, "error": "Parametro 'gpu_index' mancante"}, 400)
    gpu_index = int(body["gpu_index"])
    backend = next((d.get("backend", "cuda") for d in cuda_devices() if d["index"] == gpu_index), "cuda")
    port = body.get("port")
    self.send_json_response(start_instance(
        gpu_index=gpu_index,
        port=int(port) if port else None,
        backend=backend,
    ))


def handle_benchmark_endpoint_stop(self):
    from core.modules.sigma_benchmark_lab.endpoints import stop_instance
    port = self.read_json_body().get("port")
    if not port:
        return self.send_json_response({"success": False, "error": "Parametro 'port' mancante"}, 400)
    self.send_json_response(stop_instance(int(port)))


def handle_benchmark_endpoint_add(self):
    from core.modules.sigma_benchmark_lab.endpoints import add_endpoint
    body = self.read_json_body()
    self.send_json_response(add_endpoint(
        body.get("url", ""), body.get("gpu_index"), body.get("label", "")))


def handle_benchmark_endpoint_remove(self):
    from core.modules.sigma_benchmark_lab.endpoints import remove_endpoint
    self.send_json_response(remove_endpoint(self.read_json_body().get("url", "")))


def handle_benchmark_run(self):
    from core.modules.sigma_benchmark_lab.benchmarks import start_benchmark_run
    body = self.read_json_body()
    thinking_mode = body.get("thinking_mode") or body.get("thinking") or "auto"
    job = start_benchmark_run(
        model_name=body.get("model", "qwen2.5-coder:14b"),
        suite_id=body.get("suite", "all"),
        num_samples=int(body.get("samples", 0)),
        mode=body.get("mode", "full"),
        concurrency=body.get("concurrency", "auto"),
        thinking_mode=thinking_mode,
    )
    self.send_json_response({"success": True, "job": job})


def handle_benchmark_extend(self):
    from core.modules.sigma_benchmark_lab.benchmarks import extend_benchmark_job
    body = self.read_json_body()
    res = extend_benchmark_job(
        job_id=body.get("id") or body.get("job_id", ""),
        added_samples=int(body.get("samples", 25)),
        additional_suite=body.get("suite", ""),
        mode=body.get("mode", "sample"),
        concurrency=body.get("concurrency", "auto"),
        thinking_mode=body.get("thinking_mode"),
    )
    self.send_json_response(res)


def handle_benchmark_rerun_suite(self):
    from core.modules.sigma_benchmark_lab.benchmarks import rerun_suite_job
    body = self.read_json_body()
    res = rerun_suite_job(
        job_id=body.get("id") or body.get("job_id", ""),
        suite_id=body.get("suite", "all"),
        concurrency=body.get("concurrency", "auto"),
    )
    self.send_json_response(res)


def handle_benchmark_delete(self):
    from core.modules.sigma_benchmark_lab.benchmarks import delete_benchmark_job
    ok = delete_benchmark_job(self.read_json_body().get("id", ""))
    self.send_json_response({"success": ok})


def handle_benchmark_cancel(self):
    from core.modules.sigma_benchmark_lab.benchmarks import cancel_benchmark_job
    ok = cancel_benchmark_job(self.read_json_body().get("id", ""))
    self.send_json_response({"success": ok})


def handle_benchmark_pause(self):
    from core.modules.sigma_benchmark_lab.benchmarks import pause_benchmark_job
    ok = pause_benchmark_job(self.read_json_body().get("id", ""))
    self.send_json_response({"success": ok})


def handle_benchmark_resume(self):
    from core.modules.sigma_benchmark_lab.benchmarks import resume_benchmark_job
    ok = resume_benchmark_job(self.read_json_body().get("id", ""))
    self.send_json_response({"success": ok})


def handle_benchmark_suite_info(self):
    from core.modules.sigma_benchmark_lab.benchmarks import get_suite_info
    self.send_json_response(get_suite_info(_query(self, "suite", "all") or "all"))


def handle_benchmark_download(self):
    from core.modules.sigma_benchmark_lab.benchmarks import download_suite
    body = self.read_json_body()
    try:
        limit = int(body.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    self.send_json_response(download_suite(body.get("suite", "all"), limit=limit))


def handle_benchmark_protocol_scenarios(self):
    from core.modules.sigma_benchmark_lab.protocol_runner import get_protocol_scenarios
    self.send_json_response({"success": True, "scenarios": get_protocol_scenarios()})


def handle_benchmark_protocol_run(self):
    from core.modules.sigma_benchmark_lab.protocol_runner import start_protocol_bench
    body = self.read_json_body()
    model = body.get("model", "")
    if not model:
        return self.send_json_response({"success": False, "error": "Parametro 'model' mancante"}, 400)
    scenarios = body.get("scenarios")
    livello = body.get("livello")
    if livello is not None:
        try:
            livello = int(livello)
        except (ValueError, TypeError):
            livello = None
    self.send_json_response(start_protocol_bench(model_name=model, scenarios=scenarios, livello=livello))


def handle_benchmark_protocol_status(self):
    from core.modules.sigma_benchmark_lab.protocol_runner import get_protocol_status
    job_id = _query(self, "job_id") or _query(self, "id") or None
    self.send_json_response({"success": True, "job": get_protocol_status(job_id)})


def handle_benchmark_protocol_cancel(self):
    from core.modules.sigma_benchmark_lab.protocol_runner import cancel_protocol_bench
    body = self.read_json_body()
    job_id = body.get("job_id") or body.get("id") or ""
    if not job_id:
        return self.send_json_response({"success": False, "error": "Parametro 'job_id' mancante"}, 400)
    ok = cancel_protocol_bench(job_id)
    self.send_json_response({"success": ok})


def handle_benchmark_protocol_delete(self):
    from core.modules.sigma_benchmark_lab.protocol_runner import delete_protocol_job
    body = self.read_json_body()
    job_id = body.get("job_id") or body.get("id") or ""
    if not job_id:
        return self.send_json_response({"success": False, "error": "Parametro 'job_id' o 'id' mancante"}, 400)
    ok = delete_protocol_job(job_id)
    self.send_json_response({"success": ok})


def handle_benchmark_protocol_history(self):
    from core.modules.sigma_benchmark_lab.protocol_runner import list_protocol_history
    self.send_json_response({"success": True, "history": list_protocol_history()})



# ---------------------------------------------------------------- route tables

GET_ROUTES = {
    # Nuove route canoniche
    "/api/benchmark/models": handle_benchmark_models,
    "/api/benchmark/jobs": handle_benchmark_jobs,
    "/api/benchmark/suite_info": handle_benchmark_suite_info,
    "/api/benchmark/results": handle_benchmark_results,
    "/api/benchmark/review": handle_benchmark_review,
    "/api/benchmark/audit": handle_benchmark_audit,
    "/api/benchmark/capacity": handle_benchmark_capacity,
    "/api/benchmark/capacity/status": handle_benchmark_capacity_status,
    "/api/benchmark/endpoints": handle_benchmark_endpoints,
    "/api/benchmark/protocol/scenarios": handle_benchmark_protocol_scenarios,
    "/api/benchmark/protocol/status": handle_benchmark_protocol_status,
    "/api/benchmark/protocol/history": handle_benchmark_protocol_history,
    # Alias retrocompatibili
    "/api/training/benchmark/models": handle_benchmark_models,
    "/api/training/benchmark/jobs": handle_benchmark_jobs,
    "/api/training/benchmark/suite_info": handle_benchmark_suite_info,
    "/api/training/benchmark/results": handle_benchmark_results,
    "/api/training/benchmark/review": handle_benchmark_review,
    "/api/training/benchmark/audit": handle_benchmark_audit,
    "/api/training/benchmark/capacity": handle_benchmark_capacity,
    "/api/training/benchmark/capacity/status": handle_benchmark_capacity_status,
    "/api/training/benchmark/endpoints": handle_benchmark_endpoints,
    "/api/training/benchmark/protocol/scenarios": handle_benchmark_protocol_scenarios,
    "/api/training/benchmark/protocol/status": handle_benchmark_protocol_status,
    "/api/training/benchmark/protocol/history": handle_benchmark_protocol_history,
}

POST_ROUTES = {
    # Nuove route canoniche
    "/api/benchmark/run": handle_benchmark_run,
    "/api/benchmark/extend": handle_benchmark_extend,
    "/api/benchmark/rerun_suite": handle_benchmark_rerun_suite,
    "/api/benchmark/delete": handle_benchmark_delete,
    "/api/benchmark/cancel": handle_benchmark_cancel,
    "/api/benchmark/pause": handle_benchmark_pause,
    "/api/benchmark/resume": handle_benchmark_resume,
    "/api/benchmark/download": handle_benchmark_download,
    "/api/benchmark/capacity/probe": handle_benchmark_capacity_probe,
    "/api/benchmark/endpoints/start": handle_benchmark_endpoint_start,
    "/api/benchmark/endpoints/stop": handle_benchmark_endpoint_stop,
    "/api/benchmark/endpoints/add": handle_benchmark_endpoint_add,
    "/api/benchmark/endpoints/remove": handle_benchmark_endpoint_remove,
    "/api/benchmark/protocol/run": handle_benchmark_protocol_run,
    "/api/benchmark/protocol/cancel": handle_benchmark_protocol_cancel,
    "/api/benchmark/protocol/delete": handle_benchmark_protocol_delete,
    # Alias retrocompatibili
    "/api/training/benchmark/run": handle_benchmark_run,
    "/api/training/benchmark/extend": handle_benchmark_extend,
    "/api/training/benchmark/rerun_suite": handle_benchmark_rerun_suite,
    "/api/training/benchmark/delete": handle_benchmark_delete,
    "/api/training/benchmark/cancel": handle_benchmark_cancel,
    "/api/training/benchmark/pause": handle_benchmark_pause,
    "/api/training/benchmark/resume": handle_benchmark_resume,
    "/api/training/benchmark/download": handle_benchmark_download,
    "/api/training/benchmark/capacity/probe": handle_benchmark_capacity_probe,
    "/api/training/benchmark/endpoints/start": handle_benchmark_endpoint_start,
    "/api/training/benchmark/endpoints/stop": handle_benchmark_endpoint_stop,
    "/api/training/benchmark/endpoints/add": handle_benchmark_endpoint_add,
    "/api/training/benchmark/endpoints/remove": handle_benchmark_endpoint_remove,
    "/api/training/benchmark/protocol/run": handle_benchmark_protocol_run,
    "/api/training/benchmark/protocol/cancel": handle_benchmark_protocol_cancel,
    "/api/training/benchmark/protocol/delete": handle_benchmark_protocol_delete,
}


def register_routes(app: Any = None) -> None:
    """Registra le route HTTP di Benchmark Lab sull'adapter FastAPI."""
    try:
        from core.fastapi_app import FastAPIHandlerAdapter

        # Registra i metodi di dispatch
        for name, fn in list(globals().items()):
            if name.startswith("handle_benchmark_") and callable(fn):
                setattr(FastAPIHandlerAdapter, name, fn)

        # Registra le mappature url -> metodo
        existing_get = getattr(FastAPIHandlerAdapter, "_GET_HANDLERS", {})
        FastAPIHandlerAdapter._GET_HANDLERS = {
            **{url: fn.__name__ for url, fn in GET_ROUTES.items()},
            **existing_get,
        }

        existing_post = getattr(FastAPIHandlerAdapter, "_POST_HANDLERS", {})
        FastAPIHandlerAdapter._POST_HANDLERS = {
            **{url: fn.__name__ for url, fn in POST_ROUTES.items()},
            **existing_post,
        }

        log.info("[sigma_benchmark_lab] Route Benchmark Lab registrate (%d GET, %d POST).",
                 len(GET_ROUTES), len(POST_ROUTES))
    except Exception as e:
        log.warning("[sigma_benchmark_lab] Avviso registrazione route: %s", e)


def register_mcp(mcp_hub: Any) -> None:
    """Registra il server MCP di Benchmark nell'hub MCP del kernel."""
    try:
        from .benchmark_server import BenchmarkMCPServer
        mcp_hub.register_server(BenchmarkMCPServer)
        log.info("[sigma_benchmark_lab] Benchmark MCP Server registrato.")
    except Exception as e:
        log.warning("[sigma_benchmark_lab] MCP Server non registrato: %s", e)
