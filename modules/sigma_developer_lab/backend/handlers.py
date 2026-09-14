# ==============================================================================
# core/developer_studio/handlers.py — FastAPI Handlers for Developer Studio
# Sigma Studio v8 — Developer Studio API Endpoints
# ==============================================================================
"""Registers and exposes all REST and SSE streaming endpoints for Developer Studio."""

import os
import json
import queue
import asyncio
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from core import paths
from core.logger import get_logger
from core.harness.fs_manager import (
    get_workspace_tree,
    read_file_content,
    write_file_content,
    delete_fs_entry,
    create_fs_entry,
    rename_fs_entry,
    search_workspace_files,
    get_default_workspace_root,
    list_file_backups,
    restore_file_backup,
)
from core.harness.terminal import execute_shell_command_sync, stream_shell_command
from core.harness.loop import stream_admin_agent_turn, execute_admin_tool
from core.harness import review

log = get_logger("developer_handlers")

#: Gli orchestratori in esecuzione, per sessione. Serve perche' l'approvazione
#: di una fase arriva su una richiesta HTTP diversa da quella che sta
#: streammando il lavoro: senza un posto dove ritrovarlo, il thread in attesa
#: non e' raggiungibile e la modalita' interattiva resta una promessa.
_ORCHESTRATORS: Dict[str, Any] = {}
_ORCHESTRATORS_LOCK = threading.RLock()


def _register_orchestrator(key: str, orchestrator: Any) -> None:
    with _ORCHESTRATORS_LOCK:
        _ORCHESTRATORS[key] = orchestrator


def _unregister_orchestrator(key: str) -> None:
    with _ORCHESTRATORS_LOCK:
        _ORCHESTRATORS.pop(key, None)


def _get_orchestrator(key: str) -> Optional[Any]:
    with _ORCHESTRATORS_LOCK:
        return _ORCHESTRATORS.get(key)


async def handle_fs_tree(request: Request):
    """GET /api/developer/fs/tree?path=<optional> — Returns workspace directory tree."""
    path = request.query_params.get("path") or get_default_workspace_root()
    depth = int(request.query_params.get("depth", 4))
    tree = await asyncio.to_thread(get_workspace_tree, path, depth)
    return JSONResponse(status_code=200, content={"success": True, "tree": tree, "root": path})


async def handle_fs_read(request: Request):
    """GET /api/developer/fs/read?path=<file_path> — Reads file content in admin mode."""
    path = request.query_params.get("path")
    if not path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'path' mancante."})
    res = await asyncio.to_thread(read_file_content, path)
    return JSONResponse(status_code=200 if res.get("success") else 400, content=res)


async def handle_fs_raw(request: Request):
    """GET /api/developer/fs/raw?path=<file_path> — Serves raw binary files (images, audio, video)."""
    from fastapi.responses import FileResponse
    path = request.query_params.get("path")
    if not path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'path' mancante."})
    p = Path(path).resolve()
    if not p.exists() or p.is_dir():
        return JSONResponse(status_code=404, content={"success": False, "error": "File non trovato."})
    return FileResponse(str(p))


async def handle_fs_write(request: Request):
    """POST /api/developer/fs/write — Writes content to a file with automatic backup snapshot."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = body.get("path")
    content = body.get("content", "")
    if not path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'path' mancante."})
    res = await asyncio.to_thread(write_file_content, path, content)
    if res.get("success"):
        # Se il file appartiene a un modulo, quel lavoro va nel repository del
        # modulo: qui non e' versionato. In background e con un'attesa minima
        # fra una volta e l'altra, perche' salvare nell'editor e' un gesto che
        # si ripete e non deve ne' rallentare ne' produrre un commit per volta.
        try:
            from core.module_sync import auto_sync_in_background
            auto_sync_in_background([res.get("path") or path], nota="Modifica dall'editor")
        except Exception as exc:
            log.debug("[Developer] sincronizzazione moduli non avviata: %s", exc)
    return JSONResponse(status_code=200 if res.get("success") else 500, content=res)


async def handle_fs_delete(request: Request):
    """POST /api/developer/fs/delete — Deletes a file or directory in admin mode."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = body.get("path")
    recursive = bool(body.get("recursive", True))
    if not path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'path' mancante."})
    res = await asyncio.to_thread(delete_fs_entry, path, recursive)
    return JSONResponse(status_code=200 if res.get("success") else 500, content=res)


async def handle_fs_backups(request: Request):
    """GET /api/developer/fs/backups?path=<optional>&limit=50 — Lists previous file backup snapshots."""
    path = request.query_params.get("path")
    limit = int(request.query_params.get("limit", 50))
    backups = await asyncio.to_thread(list_file_backups, file_path=path, limit=limit)
    return JSONResponse(status_code=200, content={"success": True, "backups": backups, "count": len(backups)})


async def handle_fs_restore(request: Request):
    """POST /api/developer/fs/restore — Restores a file to its previous backup snapshot."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = body.get("path")
    backup_id = body.get("backup_id")
    if not path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'path' mancante."})
    res = await asyncio.to_thread(restore_file_backup, file_path=path, backup_id=backup_id)
    return JSONResponse(status_code=200 if res.get("success") else 400, content=res)


async def handle_fs_create(request: Request):
    """POST /api/developer/fs/create — Creates an empty file or folder."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = body.get("path")
    is_dir = bool(body.get("is_dir", False))
    if not path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'path' mancante."})
    res = await asyncio.to_thread(create_fs_entry, path, is_dir)
    return JSONResponse(status_code=200 if res.get("success") else 500, content=res)


async def handle_fs_rename(request: Request):
    """POST /api/developer/fs/rename — Renames or moves a file or folder."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    old_path = body.get("old_path") or body.get("source_path")
    new_path = body.get("new_path") or body.get("target_path")
    if not old_path or not new_path:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametri 'old_path' e 'new_path' richiesti."})
    res = await asyncio.to_thread(rename_fs_entry, old_path, new_path)
    return JSONResponse(status_code=200 if res.get("success") else 500, content=res)


async def handle_fs_search(request: Request):
    """POST /api/developer/fs/search — Searches workspace files."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    query = body.get("query", "")
    path = body.get("path") or get_default_workspace_root()
    is_regex = bool(body.get("is_regex", False))
    res = await asyncio.to_thread(search_workspace_files, path, query, is_regex)
    return JSONResponse(status_code=200 if res.get("success") else 500, content=res)


async def handle_terminal_exec(request: Request):
    """POST /api/developer/terminal/exec — Executes a shell command synchronously or streaming."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    command = body.get("command", "")
    cwd = body.get("cwd") or get_default_workspace_root()
    stream = bool(body.get("stream", False))

    if not command:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'command' richiesto."})

    if stream:
        async def sse_gen():
            for item in stream_shell_command(command, cwd):
                yield f"data: {json.dumps(item)}\n\n"
                await asyncio.sleep(0.001)

        return StreamingResponse(
            sse_gen(),
            media_type="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
    else:
        res = await asyncio.to_thread(execute_shell_command_sync, command, cwd)
        return JSONResponse(status_code=200, content=res)


async def handle_agent_chat(request: Request):
    """POST /api/developer/agent/chat — Streams Admin AI Developer Agent reasoning and tools."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    messages = body.get("messages", [])
    workspace_root = body.get("workspace_root") or get_default_workspace_root()
    model = body.get("model") or "sigmaengine"
    auto_execute = bool(body.get("auto_execute_tools", True))
    pipeline = body.get("pipeline", [])
    context_tokens = int(body.get("context_tokens") or body.get("context_length") or 32768)
    # A tool call that carries a whole source file needs room for it.
    max_tokens = int(body.get("max_tokens") or 20000)
    # Requested off, but do not rely on it: on checkpoints whose chat
    # template ignores `enable_thinking` — Qwen3.8-27B among them — this
    # flag is inert and `/no_think` is ignored as well. The reasoning
    # block is then unavoidable, which is why max_tokens above has to
    # accommodate the reasoning *and* the file being written.
    thinking = body.get("thinking")
    thinking = False if thinking is None else bool(thinking)
    # A real development goal needs many more tool round-trips than a chat
    # answer: read, edit, re-read, test, fix. Capping at a handful of turns is
    # what made the agent stop half-way through its own plan.
    max_turns = max(1, min(int(body.get("max_turns") or 30), 100))
    # L'identificativo di sessione lega il run allo stato salvato su disco:
    # senza, ogni richiesta riparte da un ledger vuoto e l'agente rilegge
    # quello che aveva gia' letto un minuto prima.
    session_id = str(body.get("session_id") or "").strip() or None
    # Il profilo operativo: "read_only" per far esplorare senza toccare
    # nulla, "plan_only" per farsi proporre un piano prima di concedere
    # la scrittura. Assente significa nessun limite oltre a quelli del ruolo.
    profile = str(body.get("profile") or "").strip() or None
    # Con la revisione attiva ogni scrittura si ferma davanti all'utente prima
    # di restare. Richiede una sessione: la decisione arriva su un'altra
    # richiesta HTTP e senza identificativo non saprebbe quale run sbloccare.
    review_writes = bool(body.get("review_writes")) and bool(session_id)
    # L'agente lavora in una copia fisica del repository invece che nell'albero
    # vivo. Richiede una sessione perche' il worktree e' intestato a quella, ed
    # e' anche cio' che permette di ritrovarne il branch dopo.
    isolate_worktree = bool(body.get("isolate_worktree")) and bool(session_id)
    # La revisione del lavoro intero, una volta sola alla fine. E' la forma
    # che serve quando il run tocca molti file: duecento approvazioni una per
    # una nessuno le da'.
    review_run = bool(body.get("review_run")) and bool(session_id)

    # The agent loop is fully synchronous and blocking (model inference, filesystem
    # search, shell commands). It MUST run on a worker thread: executing it inline on
    # the event loop freezes every other Sigma Studio request until it finishes.
    async def sse_stream():
        cancel_event = threading.Event()
        events: "queue.Queue[Any]" = queue.Queue(maxsize=512)
        DONE = object()

        def producer():
            try:
                for event in stream_admin_agent_turn(
                    messages=messages,
                    workspace_root=workspace_root,
                    model_name=model,
                    auto_execute_tools=auto_execute,
                    should_cancel=cancel_event.is_set,
                    current_pipeline=pipeline,
                    context_tokens=context_tokens,
                    max_tokens=max_tokens,
                    max_turns=max_turns,
                    thinking=thinking,
                    session_id=session_id,
                    profile=profile,
                    review_writes=review_writes,
                    isolate_worktree=isolate_worktree,
                    review_run=review_run,
                ):
                    if cancel_event.is_set():
                        break
                    # Bounded queue: if the client stalls, block here instead of
                    # accumulating the whole transcript in RAM.
                    while not cancel_event.is_set():
                        try:
                            events.put(event, timeout=0.5)
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                log.exception("Admin agent stream failed: %s", e)
                try:
                    events.put({"type": "error", "error": str(e)}, timeout=1.0)
                except queue.Full:
                    pass
            finally:
                try:
                    events.put(DONE, timeout=1.0)
                except queue.Full:
                    pass

        worker = threading.Thread(target=producer, name="admin-agent-stream", daemon=True)
        worker.start()

        try:
            while True:
                try:
                    event = await asyncio.to_thread(events.get, True, 1.0)
                except queue.Empty:
                    if not worker.is_alive():
                        break
                    # Heartbeat keeps proxies from dropping a long tool execution
                    yield ": keep-alive\n\n"
                    continue

                if event is DONE:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            # Client aborted (Stop button / tab closed): stop the agent too.
            cancel_event.set()
            raise
        finally:
            cancel_event.set()

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


async def handle_workspace_roots(request: Request):
    """GET /api/developer/workspace/roots — le cartelle su cui si puo' lavorare.

    In cima sta l'indirizzo di sviluppo con i suoi progetti, perche' e' li' che
    nascono gli applicativi: lavorare su Sigma Studio stesso e' il caso
    speciale, non la norma, e va scelto apposta.

    L'ordine non e' un dettaglio estetico. Con Sigma Studio in cima, un
    compito che diceva «crea un programma **staccato da sigma**» e' stato
    lanciato sulla radice di Sigma Studio: l'agente ha scritto `backend/`,
    `frontend/` e `landing/` dentro il sorgente del programma che lo stava
    eseguendo, e un commit se li e' portati dentro insieme al resto. La prima
    voce di un elenco e' la scelta che si fa senza decidere.

    Le lettere di unita' restano perche' servono a navigare verso un progetto
    che sta altrove, ma portano `unsafe` con il motivo: un agente su `C:/` puo'
    scrivere ovunque, e chi sceglie deve vederlo scritto prima, non dopo.
    """
    from core.progetti import elenca_progetti, radice_pericolosa, radice_progetti

    roots = []
    try:
        radice = radice_progetti()
        roots.append({"label": f"Progetti ({radice.name})",
                      "path": str(radice).replace("\\", "/"), "kind": "projects_root"})
        for progetto in elenca_progetti():
            roots.append({
                "label": f"  {progetto['name']}" + (" ·git" if progetto["is_git"] else ""),
                "path": progetto["path"], "kind": "project",
            })
    except Exception as exc:  # l'elenco non deve poter rompere la pagina
        log.warning("[Developer] progetti non elencati: %s", exc)

    default_root = get_default_workspace_root()
    roots.append({"label": f"Sigma Studio ({Path(default_root).name}) — il programma stesso",
                  "path": default_root.replace("\\", "/"), "kind": "studio"})

    altre = [str(Path.home())]
    if os.name == "nt":
        import string
        altre += [f"{letter}:/" for letter in string.ascii_uppercase
                  if os.path.exists(f"{letter}:\\")]
    for percorso in altre:
        motivo = radice_pericolosa(percorso)
        voce = {"label": Path(percorso).name or percorso,
                "path": percorso.replace("\\", "/"), "kind": "other"}
        if motivo:
            voce["unsafe"] = motivo
        roots.append(voce)

    return JSONResponse(status_code=200, content={
        "success": True, "roots": roots,
        "current": default_root.replace("\\", "/")})


async def handle_sandbox(request: Request):
    """GET /api/developer/sandbox — dove girano i comandi, e se puo' funzionare.

    `active` e' vero solo se la sandbox e' chiesta **e** possibile: dire
    «accesa» quando Docker non c'e' sarebbe la bugia peggiore, perche' chi
    legge crederebbe di essere protetto.
    """
    from core.harness.esecutori import stato_sandbox

    try:
        return JSONResponse(status_code=200, content={"success": True,
                                                      **stato_sandbox()})
    except Exception as exc:
        return JSONResponse(status_code=500,
                            content={"success": False, "error": str(exc)})


async def handle_sandbox_save(request: Request):
    """POST /api/developer/sandbox — cambia la modalita' di esecuzione."""
    from core.harness.esecutori import salva_config, stato_sandbox

    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        salva_config(body)
        return JSONResponse(status_code=200, content={"success": True,
                                                      **stato_sandbox()})
    except (ValueError, OSError) as exc:
        return JSONResponse(status_code=400,
                            content={"success": False, "error": str(exc)})


async def handle_projects(request: Request):
    """GET /api/developer/projects — l'indirizzo di sviluppo e cosa contiene."""
    from core.progetti import elenca_progetti, radice_progetti

    try:
        return JSONResponse(status_code=200, content={
            "success": True,
            "root": str(radice_progetti()).replace("\\", "/"),
            "projects": elenca_progetti(),
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False, "error": str(exc), "projects": []})


async def handle_projects_root(request: Request):
    """POST /api/developer/projects/root — sposta l'indirizzo di sviluppo."""
    from core.progetti import imposta_radice

    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return JSONResponse(status_code=200, content={
            "success": True, **imposta_radice(str(body.get("root") or ""))})
    except (ValueError, OSError) as exc:
        return JSONResponse(status_code=400, content={
            "success": False, "error": str(exc)})


async def handle_project_create(request: Request):
    """POST /api/developer/projects — crea la cartella di un progetto nuovo."""
    from core.progetti import crea_progetto

    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        cartella = crea_progetto(str(body.get("name") or ""))
        return JSONResponse(status_code=200, content={
            "success": True, "name": cartella.name,
            "path": str(cartella).replace("\\", "/")})
    except (ValueError, OSError) as exc:
        return JSONResponse(status_code=400, content={
            "success": False, "error": str(exc)})


def _get_tasks_filepath() -> Path:
    target = paths.developer_tasks_file()
    paths.ensure(target.parent)
    return target


async def handle_get_tasks(request: Request):
    """GET /api/developer/tasks — Returns all developer tasks saved on server."""
    fp = _get_tasks_filepath()
    tasks = []
    if fp.exists():
        try:
            tasks = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Could not read developer_tasks.json: %s", e)
    return JSONResponse(status_code=200, content={"success": True, "tasks": tasks})


async def handle_save_tasks(request: Request):
    """POST /api/developer/tasks — Persists developer tasks to server disk."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    tasks = body.get("tasks", [])
    fp = _get_tasks_filepath()
    try:
        fp.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
        return JSONResponse(status_code=200, content={"success": True})
    except Exception as e:
        log.error("Could not write developer_tasks.json: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


async def handle_orchestrator_run(request: Request):
    """POST /api/developer/orchestrator/run — Executes a full development workflow via SSE streaming."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    goal = body.get("goal", "")
    mode = body.get("mode", "interactive")
    model = body.get("model") or "sigmaengine"
    workspace_root = body.get("workspace_root") or get_default_workspace_root()
    session_id = str(body.get("session_id") or "").strip() or None

    # Le tre reti di sicurezza, come per il singolo agente. Tutte e tre
    # chiedono un session_id: senza, non c'e' un worktree da intestare ne' un
    # gate di revisione da interrogare, e accenderle darebbe solo l'impressione
    # di essere protetti.
    isolate_worktree = bool(body.get("isolate_worktree")) and bool(session_id)
    review_run = bool(body.get("review_run")) and bool(session_id)
    review_writes = bool(body.get("review_writes")) and bool(session_id)

    if not goal:
        return JSONResponse(status_code=400, content={"success": False, "error": "Parametro 'goal' richiesto."})

    from core.modules.sigma_developer_lab.orchestrator import DevOrchestrator

    async def sse_stream():
        cancel_event = threading.Event()
        events: "queue.Queue[Any]" = queue.Queue(maxsize=512)
        DONE = object()

        chiave = session_id or f"anon-{id(events)}"

        def producer():
            orchestrator = None
            try:
                orchestrator = DevOrchestrator(
                    workspace_root=workspace_root,
                    model_name=model,
                    session_id=session_id,
                )
                _register_orchestrator(chiave, orchestrator)
                for event in orchestrator.execute_goal(
                    goal=goal,
                    mode=mode,
                    model_name=model,
                    # Le tre reti di sicurezza valgono per la squadra quanto
                    # per il singolo agente. Servono un session_id: senza, non
                    # c'e' un worktree da intestare ne' un gate da interrogare.
                    isolate_worktree=isolate_worktree,
                    review_run=review_run,
                    review_writes=review_writes,
                ):
                    if cancel_event.is_set():
                        orchestrator.cancel()
                        break
                    while not cancel_event.is_set():
                        try:
                            events.put(event, timeout=0.5)
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                log.exception("Orchestrator stream failed: %s", e)
                try:
                    events.put({"type": "error", "error": str(e)}, timeout=1.0)
                except queue.Full:
                    pass
            finally:
                # Prima si toglie dal registro, poi si chiude lo stream: un
                # orchestratore raggiungibile ma finito accetterebbe
                # approvazioni che nessuno aspetta piu'.
                _unregister_orchestrator(chiave)
                try:
                    events.put(DONE, timeout=1.0)
                except queue.Full:
                    pass

        worker = threading.Thread(target=producer, name="orchestrator-stream", daemon=True)
        worker.start()

        try:
            while True:
                try:
                    event = await asyncio.to_thread(events.get, True, 1.0)
                except queue.Empty:
                    if not worker.is_alive():
                        break
                    yield ": keep-alive\n\n"
                    continue

                if event is DONE:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            cancel_event.set()
            raise
        finally:
            cancel_event.set()

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


async def handle_orchestrator_approve(request: Request):
    """POST /api/developer/orchestrator/approve — Approva o rifiuta una fase.

    E' la meta' mancante della modalita' interattiva: l'evento
    `approval_required` viaggia sullo stream SSE, la risposta torna di qui, e
    il thread che sta eseguendo l'obiettivo riparte o salta la fase.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_id = str(body.get("session_id") or "").strip()
    phase = str(body.get("phase") or "").strip()
    decision = str(body.get("decision") or "approved").strip()

    if not session_id or not phase:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "Parametri 'session_id' e 'phase' richiesti.",
        })

    orchestrator = _get_orchestrator(session_id)
    if orchestrator is None:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": f"Nessun orchestratore in esecuzione per la sessione '{session_id}'.",
        })

    accolta = orchestrator.approve(phase, decision)
    return JSONResponse(status_code=200, content={
        "success": True,
        "delivered": accolta,
        "phase": phase,
        "decision": decision,
        "message": (
            f"Fase '{phase}': {decision}."
            if accolta
            else f"Decisione registrata, ma nessuno era in attesa sulla fase '{phase}'."
        ),
    })


async def handle_orchestrator_status(request: Request):
    """GET /api/developer/orchestrator/status — Returns current orchestrator state."""
    session_id = (request.query_params.get("session_id") or "").strip()
    orchestrator = _get_orchestrator(session_id) if session_id else None
    if orchestrator is None:
        return JSONResponse(status_code=200, content={
            "success": True,
            "status": "idle",
            "message": "Orchestrator pronto. Invia un goal con POST /api/developer/orchestrator/run.",
        })
    in_attesa = orchestrator.pending_approval()
    return JSONResponse(status_code=200, content={
        "success": True,
        "status": "waiting_approval" if in_attesa else "running",
        "pending_phase": in_attesa,
        "session_id": session_id,
        "message": (
            f"In attesa di approvazione per la fase '{in_attesa}'."
            if in_attesa else "Esecuzione in corso."
        ),
    })


async def handle_roles_list(request: Request):
    """GET /api/developer/roles — I ruoli attivi, predefiniti piu' personalizzazioni."""
    from core.harness.role_registry import list_roles
    return JSONResponse(status_code=200, content={"success": True, "roles": list_roles()})


async def handle_role_save(request: Request):
    """POST /api/developer/roles — Personalizza un ruolo.

    E' il punto da cui la tab Pipelines modifica prompt, tool, modello e budget
    di un ruolo senza toccare il codice. Sul file finisce solo cio' che
    differisce dal predefinito.
    """
    from core.harness.role_registry import save_role
    try:
        body = await request.json()
    except Exception:
        body = {}
    role_id = str(body.get("id") or body.get("role_id") or "").strip()
    patch = body.get("patch") or {k: v for k, v in body.items()
                                   if k not in ("id", "role_id")}
    if not role_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'id' richiesto."})
    try:
        risultante = await asyncio.to_thread(save_role, role_id, patch)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except OSError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})
    return JSONResponse(status_code=200, content={"success": True, "role": risultante})


async def handle_role_reset(request: Request):
    """POST /api/developer/roles/reset — Riporta un ruolo al predefinito."""
    from core.harness.role_registry import delete_role
    try:
        body = await request.json()
    except Exception:
        body = {}
    role_id = str(body.get("id") or body.get("role_id") or "").strip()
    if not role_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'id' richiesto."})
    rimosso = await asyncio.to_thread(delete_role, role_id)
    return JSONResponse(status_code=200, content={
        "success": True, "reset": rimosso, "id": role_id})


async def handle_sessions_list(request: Request):
    """GET /api/developer/sessions?limit=50 — Elenca le sessioni di lavoro salvate."""
    from core.harness import store as session_store
    try:
        limite = int(request.query_params.get("limit") or 50)
    except (TypeError, ValueError):
        limite = 50
    return JSONResponse(status_code=200, content={
        "success": True,
        "sessions": session_store.list_sessions(limit=limite),
    })


async def handle_session_get(request: Request):
    """GET /api/developer/session?session_id=<id> — Stato di lavoro di una sessione.

    E' il pannello «cosa sa l'agente»: quali file conosce, cosa ha verificato,
    a che punto e' il piano. Serve alla UI dopo un refresh, e a un client
    esterno che voglia riprendere un lavoro senza rifare l'esplorazione.
    """
    from core.harness import store as session_store
    session_id = (request.query_params.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'session_id' richiesto."
        })
    documento = session_store.load(session_id)
    if not documento:
        return JSONResponse(status_code=404, content={
            "success": False, "error": f"Sessione '{session_id}' non trovata."
        })
    return JSONResponse(status_code=200, content={"success": True, "session": documento})


async def handle_session_delete(request: Request):
    """POST /api/developer/session/delete — Rimuove una sessione salvata."""
    from core.harness import store as session_store
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'session_id' richiesto."
        })
    return JSONResponse(status_code=200, content={
        "success": session_store.delete(session_id),
        "session_id": session_id,
    })


async def handle_project_rules(request: Request):
    """GET /api/developer/project/rules?workspace_root=<path> — Le regole del progetto.

    Dice quali istruzioni l'agente sta effettivamente applicando su questo
    workspace: e' l'unico modo che l'utente ha di accorgersi che il file di
    regole esiste ma sta nella cartella sbagliata, o che non esiste affatto.
    """
    from core.harness import rules as project_rules
    radice = (request.query_params.get("workspace_root") or "").strip() or get_default_workspace_root()
    trovati = project_rules.discover(radice)
    sezione = project_rules.load_section(radice)
    return JSONResponse(status_code=200, content={
        "success": True,
        "workspace_root": radice,
        "files": trovati,
        "chars": len(sezione),
        "supported": list(project_rules.RULE_FILES),
    })


# ---------------------------------------------------------------------------
# Tabella delle route
# ---------------------------------------------------------------------------
#
# Vive qui, accanto agli handler, e non nel modulo installabile che la
# registra: sono due file che si copiano l'uno dall'altro, e una rotta
# aggiunta solo da una parte e' una rotta che in produzione non esiste.
async def handle_review_decide(request: Request):
    """POST /api/developer/review/decide — Tiene o annulla una modifica proposta.

    E' la meta' mancante del gate di revisione: l'evento `write_proposed`
    viaggia sullo stream SSE con il diff, la risposta torna di qui, e il thread
    che sta eseguendo il run riprende — lasciando la modifica o annullandola.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_id = str(body.get("session_id") or "").strip()
    proposal_id = str(body.get("id") or body.get("proposal_id") or "").strip()
    decision = str(body.get("decision") or "approved").strip()

    if not session_id or not proposal_id:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "Parametri 'session_id' e 'id' richiesti.",
        })

    accolta = review.decide(session_id, proposal_id, decision)
    return JSONResponse(status_code=200, content={
        "success": True,
        "applied": accolta,
        "decision": decision,
        # Una decisione arrivata dopo il timeout non e' un errore, ma non ha
        # avuto effetto: dirlo evita che l'utente creda di aver approvato una
        # modifica che era gia' stata annullata.
        "message": ("Decisione registrata." if accolta else
                    "Nessuna proposta in attesa con questo identificativo: "
                    "potrebbe essere gia' scaduta o gia' decisa."),
    })


async def handle_review_pending(request: Request):
    """GET /api/developer/review/pending — Le modifiche in attesa di giudizio.

    Serve a una UI che si riapre a run gia' avviato: lo stream SSE porta la
    proposta una volta sola, e chi ha ricaricato la pagina altrimenti non
    saprebbe che il run e' fermo ad aspettarlo.
    """
    session_id = str(request.query_params.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'session_id' richiesto.",
        })
    gate = review.gate_for(session_id, create=False)
    proposte = []
    if gate is not None:
        # Con il diff: chi arriva adesso non l'ha mai visto passare.
        proposte = [gate.pending_detail(v["id"]) or v for v in gate.pending()]
    return JSONResponse(status_code=200, content={
        "success": True, "session_id": session_id, "pending": proposte,
    })


async def handle_run_checkpoints(request: Request):
    """GET /api/developer/run/checkpoints — I punti a cui si puo' tornare.

    Ha senso solo per un run isolato in worktree: senza, non ci sono
    checkpoint, e non c'e' niente a cui tornare.
    """
    from core.harness.worktree import session_checkpoints

    session_id = str(request.query_params.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'session_id' richiesto."})
    return JSONResponse(status_code=200, content={
        "success": True, "session_id": session_id,
        "checkpoints": session_checkpoints(session_id),
    })


async def handle_run_rollback(request: Request):
    """POST /api/developer/run/rollback — Riporta il lavoro indietro di N turni.

    Manuale per scelta: uno stallo del modello non dice che il codice scritto
    fino a quel punto sia sbagliato, e annullarlo d'ufficio butterebbe via
    lavoro buono. Chi torna indietro deve essere qualcuno che ha guardato.
    """
    from core.harness.worktree import rollback_session

    try:
        body = await request.json()
    except Exception:
        body = {}

    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Parametro 'session_id' richiesto."})

    esito = rollback_session(session_id, int(body.get("turns_back") or 1))
    return JSONResponse(status_code=200 if esito.get("success") else 400, content=esito)


ROUTES = (
    ("/api/developer/tasks", handle_get_tasks, ["GET"]),
    ("/api/developer/tasks", handle_save_tasks, ["POST"]),
    ("/api/developer/fs/tree", handle_fs_tree, ["GET"]),
    ("/api/developer/fs/read", handle_fs_read, ["GET"]),
    ("/api/developer/fs/raw", handle_fs_raw, ["GET"]),
    ("/api/developer/fs/write", handle_fs_write, ["POST"]),
    ("/api/developer/fs/delete", handle_fs_delete, ["POST"]),
    ("/api/developer/fs/backups", handle_fs_backups, ["GET"]),
    ("/api/developer/fs/restore", handle_fs_restore, ["POST"]),
    ("/api/developer/fs/create", handle_fs_create, ["POST"]),
    ("/api/developer/fs/rename", handle_fs_rename, ["POST"]),
    ("/api/developer/fs/search", handle_fs_search, ["POST"]),
    ("/api/developer/terminal/exec", handle_terminal_exec, ["POST"]),
    ("/api/developer/agent/chat", handle_agent_chat, ["POST"]),
    ("/api/developer/workspace/roots", handle_workspace_roots, ["GET"]),
    ("/api/developer/projects", handle_projects, ["GET"]),
    ("/api/developer/projects", handle_project_create, ["POST"]),
    ("/api/developer/projects/root", handle_projects_root, ["POST"]),
    ("/api/developer/sandbox", handle_sandbox, ["GET"]),
    ("/api/developer/sandbox", handle_sandbox_save, ["POST"]),
    ("/api/developer/orchestrator/run", handle_orchestrator_run, ["POST"]),
    ("/api/developer/orchestrator/status", handle_orchestrator_status, ["GET"]),
    ("/api/developer/orchestrator/approve", handle_orchestrator_approve, ["POST"]),
    ("/api/developer/roles", handle_roles_list, ["GET"]),
    ("/api/developer/roles", handle_role_save, ["POST"]),
    ("/api/developer/roles/reset", handle_role_reset, ["POST"]),
    ("/api/developer/sessions", handle_sessions_list, ["GET"]),
    ("/api/developer/session", handle_session_get, ["GET"]),
    ("/api/developer/session/delete", handle_session_delete, ["POST"]),
    ("/api/developer/project/rules", handle_project_rules, ["GET"]),
    ("/api/developer/review/decide", handle_review_decide, ["POST"]),
    ("/api/developer/review/pending", handle_review_pending, ["GET"]),
    ("/api/developer/run/checkpoints", handle_run_checkpoints, ["GET"]),
    ("/api/developer/run/rollback", handle_run_rollback, ["POST"]),
)


def register_routes(app) -> None:
    """Registra tutte le route di Developer Studio dinamicamente sull'app FastAPI.

    L'elenco arriva dalla tabella `ROUTES` definita accanto agli handler, non
    da una seconda copia scritta qui: erano due file che si copiano l'uno
    dall'altro, e una rotta aggiunta solo nel sorgente era una rotta che in
    produzione non esisteva.
    """
    if app is None:
        return
    try:
        for percorso, handler, metodi in ROUTES:
            app.add_api_route(percorso, handler, methods=list(metodi))
        log.info(
            "[sigma_developer_lab] %d route registrate con successo su FastAPI.",
            len(ROUTES),
        )
    except Exception as exc:
        log.warning("[sigma_developer_lab] Errore durante la registrazione delle route: %s", exc)


def register_mcp(mcp_hub) -> None:
    """Registra i server MCP di Git, Lint e Test nell'Hub MCP."""
    if mcp_hub is None:
        return
    try:
        from core.modules.sigma_developer_lab.mcp_tools.git_server import GitMCPServer
        from core.modules.sigma_developer_lab.mcp_tools.lint_server import LintMCPServer
        from core.modules.sigma_developer_lab.mcp_tools.test_server import TestMCPServer
        mcp_hub.register_server(GitMCPServer)
        mcp_hub.register_server(LintMCPServer)
        mcp_hub.register_server(TestMCPServer)
        log.info("[sigma_developer_lab] Server MCP registrati con successo in MCPHub.")
    except Exception as exc:
        log.warning("[sigma_developer_lab] Errore durante la registrazione MCP: %s", exc)
