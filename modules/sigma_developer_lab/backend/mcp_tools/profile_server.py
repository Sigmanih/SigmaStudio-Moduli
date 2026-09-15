# ==============================================================================
# core/modules/sigma_developer_lab/mcp_tools/profile_server.py — Profiling MCP
# Sigma Studio v8 — Developer Studio AI-Native IDE
# =============================================================================
"""MCP server per il profiling applicativo.

Il tool `profile_app` esegue un profiling non invasivo (SAFE) di una funzione
Python o di un endpoint HTTP: misura tempo di esecuzione, picco di memoria,
count di chiamate e fornisce un riepilogo strutturato. Non modifica nulla:
solo esegue e riporta.
"""

import cProfile
import io
import json
import pstats
import resource
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from core.mcp.base_server import BaseMCPServer
from core.mcp.governance import SAFE

log = get_logger(__name__)


def _profile_function(func_path: str, args: List[Any] = None, kwargs: Dict[str, Any] = None) -> Dict[str, Any]:
    """Profila una funzione Python specificata per percorso (modulo.funzione)."""
    args = args or []
    kwargs = kwargs or {}
    
    # Importa la funzione
    try:
        module_path, func_name = func_path.rsplit('.', 1)
        import importlib
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
    except Exception as exc:
        return {
            "success": False,
            "error": f"Impossibile importare la funzione '{func_path}': {exc}",
        }

    # Esegue il profiling
    profiler = cProfile.Profile()
    start_time = time.perf_counter()
    start_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if sys.platform != 'win32' else 0
    
    try:
        profiler.runcall(lambda: func(*args, **kwargs))
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000
        
        # Estrae le statistiche principali
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats('cumulative')
        stats.print_stats(15)  # Top 15 funzioni per tempo cumulativo
        
        top_functions = []
        for func_name, calls, total_time, per_call, callers in stats.stats.items():
            if not isinstance(func_name, tuple):  # Salta le righe di header
                top_functions.append({
                    "function": str(func_name),
                    "calls": calls,
                    "total_time_s": round(total_time, 6),
                    "per_call_s": round(per_call, 6) if per_call else 0,
                })
        
        return {
            "success": True,
            "function": func_path,
            "duration_ms": round(duration_ms, 2),
            "peak_memory_kb": start_mem,  # Su Windows ru_maxrss non è affidabile
            "top_functions": top_functions[:10],
            "total_calls": len(stats.stats),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Errore durante il profiling: {exc}",
        }


def _profile_http_endpoint(url: str, method: str = "GET", timeout: float = 10.0) -> Dict[str, Any]:
    """Profila un endpoint HTTP: tempo di risposta, dimensione payload, status code."""
    import urllib.request
    
    start_time = time.perf_counter()
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            end_time = time.perf_counter()
            
            return {
                "success": True,
                "url": url,
                "method": method,
                "status_code": resp.status,
                "duration_ms": round((end_time - start_time) * 1000, 2),
                "payload_bytes": len(body),
                "content_type": resp.headers.get('Content-Type', 'unknown'),
            }
    except Exception as exc:
        end_time = time.perf_counter()
        return {
            "success": False,
            "url": url,
            "method": method,
            "duration_ms": round((end_time - start_time) * 1000, 2),
            "error": str(exc),
        }


class ProfileMCPServer(BaseMCPServer):
    """MCP server per il profiling applicativo."""

    def __init__(self):
        super().__init__(name="profile", description="Profiling applicativo: timing, memoria, CPU")
        self.register_tool(
            name="profile_app",
            description="Profila una funzione Python o un endpoint HTTP. Misura tempo, memoria e fornisce top funzioni per costo.",
            input_schema={
                "type": "object",
                "properties": {
                    "target_type": {"type": "string", "enum": ["function", "http"], "description": "Tipo di target da profilare"},
                    "target": {"type": "string", "description": "Percorso funzione (modulo.funzione) o URL endpoint"},
                    "args": {"type": "array", "description": "Argomenti posizionali (solo per function)"},
                    "kwargs": {"type": "object", "description": "Argomenti keyword (solo per function)"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"], "description": "Metodo HTTP (solo per http)"},
                    "timeout": {"type": "number", "description": "Timeout in secondi (default 10)"},
                },
                "required": ["target_type", "target"],
            },
            handler=self._handle_profile_app,
            safety=SAFE,
        )

    def _handle_profile_app(self, **kwargs) -> Dict[str, Any]:
        target_type = kwargs.get("target_type")
        target = kwargs.get("target")

        if target_type == "function":
            return _profile_function(target, kwargs.get("args"), kwargs.get("kwargs"))
        elif target_type == "http":
            return _profile_http_endpoint(target, kwargs.get("method", "GET"), kwargs.get("timeout", 10.0))
        else:
            return {"success": False, "error": f"target_type non valido: {target_type}"}
