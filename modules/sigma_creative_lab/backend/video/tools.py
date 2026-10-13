# ==============================================================================
# core/modules/sigma_creative_lab/video/tools.py — Tool Operativi per Video Studio
# ==============================================================================
"""Tool esecutivi per la regia, continuità, creazione personaggi e QA visivo.

Collega i ruoli dell'Agent Harness alle funzioni interne di:
- character_library (personaggi, model sheet, viste)
- production (produzioni, storyboard, inquadrature, render)
- clip_judge (ispezione fotogrammi, rilevazione anomalie fisiche e fisionomiche)
- timeline (struttura tracce e montaggio)
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.logger import get_logger
from .roles import VIDEO_ROLES
from .tool_schemas import SCHEMI

log = get_logger("video_tools")


def _esito(nome: str, riuscito: bool, **extra: Any) -> Dict[str, Any]:
    """Uniforma la risposta per l'harness loop."""
    res = {"tool": nome, "success": bool(riuscito)}
    res.update(extra)
    return res


# ---------------------------------------------------------------------------
# Esecutori: Personaggi
# ---------------------------------------------------------------------------

def video_char_list() -> dict:
    from . import character_library
    chars = character_library.list_characters()
    return _esito("video_char_list", True, characters=chars, count=len(chars))


def video_char_get(char_id: str) -> dict:
    from . import character_library
    char = character_library.get(str(char_id or "").strip())
    if not char:
        return _esito("video_char_get", False, error=f"Personaggio non trovato: {char_id}")
    return _esito("video_char_get", True, character=char)


def video_char_create(name: str, description: str, genre: str = "realistic", voice_id: str = "") -> dict:
    from . import character_library
    try:
        char = character_library.create(name=name, description=description, genre=genre, voice_id=voice_id)
        return _esito("video_char_create", True, character=char, char_id=char.get("id"))
    except Exception as exc:
        return _esito("video_char_create", False, error=str(exc))


def video_char_update(char_id: str, **fields) -> dict:
    from . import character_library
    try:
        char = character_library.update(char_id, **fields)
        return _esito("video_char_update", True, character=char)
    except Exception as exc:
        return _esito("video_char_update", False, error=str(exc))


def video_char_candidates(char_id: str, count: int = 4) -> dict:
    from . import character_library
    try:
        res = asyncio.run(character_library.candidates(char_id, count=count))
        return _esito("video_char_candidates", True, character=res)
    except Exception as exc:
        return _esito("video_char_candidates", False, error=str(exc))


def video_char_pick(char_id: str, file: str) -> dict:
    from . import character_library
    try:
        res = character_library.pick(char_id, file)
        return _esito("video_char_pick", True, character=res)
    except Exception as exc:
        return _esito("video_char_pick", False, error=str(exc))


def video_char_view_prompt(char_id: str, view: str, fix: str = "") -> dict:
    from . import character_library
    char = character_library.get(char_id)
    if not char:
        return _esito("video_char_view_prompt", False, error=f"Personaggio non trovato: {char_id}")
    try:
        prompt = character_library.view_prompt(char, view, fix=fix)
        return _esito("video_char_view_prompt", True, prompt=prompt, char_id=char_id, view=view)
    except Exception as exc:
        return _esito("video_char_view_prompt", False, error=str(exc))


# ---------------------------------------------------------------------------
# Esecutori: Produzioni & Storyboard
# ---------------------------------------------------------------------------

def video_prod_list() -> dict:
    from .production import manager
    items = manager.store.list()
    return _esito("video_prod_list", True, productions=items, count=len(items))


def _shot_summary(index: int, shot: dict) -> dict:
    """Inquadratura in forma compatta: i modelli locali dividono il contesto per slot."""
    history = shot.get("judge_history") or []
    last = history[-1] if history else {}
    return {
        "index": index, "id": shot.get("id"), "scene": shot.get("scene", ""), "status": shot.get("status"),
        "duration_s": shot.get("duration_s"), "transition": shot.get("transition"),
        "characters": shot.get("refs") or [], "props": shot.get("props") or [],
        "prompt": (shot.get("prompt") or "")[:300], "origin": shot.get("origin", ""),
        "has_keyframe": bool(shot.get("keyframe")), "has_clip": bool(shot.get("clip_path")),
        "judge_score": last.get("score"), "prompt_fixes": (shot.get("prompt_fixes") or [])[-2:],
    }


def video_prod_get(prod_id: str) -> dict:
    """Riepilogo della produzione: impostazioni utili, personaggi, inquadrature compatte.

    La produzione intera (versioni, cronologia del giudice) supera facilmente le
    decine di migliaia di caratteri: per il dettaglio di una inquadratura c'e'
    `video_inspect_shot`.
    """
    from .production import manager, summary
    prod = manager.store.get(str(prod_id or "").strip())
    if not prod:
        return _esito("video_prod_get", False, error=f"Produzione non trovata: {prod_id}")
    s = prod.get("settings") or {}
    bible = prod.get("bible") or {}
    return _esito(
        "video_prod_get", True,
        production={
            **summary(prod), "treatment": prod.get("treatment", ""),
            "settings": {k: s.get(k) for k in ("video_model", "width", "height", "keyframes", "judge",
                                                "judge_threshold", "max_clip_seconds", "output_height")},
            "bible": {"genre": bible.get("genre"), "style": bible.get("style", ""),
                      "characters": [{"name": c.get("name"), "description": c.get("description", ""),
                                      "has_reference": bool(c.get("ref_image")),
                                      "has_voice": bool(c.get("voice_sample"))}
                                     for c in bible.get("characters") or []]},
            "shots": [_shot_summary(i, sh) for i, sh in enumerate(prod.get("shots") or [])],
        },
    )


def video_prod_create(title: str, treatment: str, style: str = "", video_model: str = "ltx25",
                      genre: str = "realistic") -> dict:
    from .production import manager
    try:
        settings = {"video_model": video_model}
        bible = {"style": style, "genre": genre}
        prod = manager.store.create(title=title, treatment=treatment, settings=settings, bible=bible)
        return _esito("video_prod_create", True, production=prod, prod_id=prod.get("id"))
    except Exception as exc:
        return _esito("video_prod_create", False, error=str(exc))


def video_prod_plan_storyboard(prod_id: str, minutes: float = 1.0, shot_min: float = 3.0,
                               shot_max: float = 6.0, replace: bool = True) -> dict:
    from .production import manager, plan_storyboard, writer
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_prod_plan_storyboard", False, error=f"Produzione non trovata: {prod_id}")
    try:
        bible = prod.setdefault("bible", {})
        pre = bible.get("pre") or {}
        if not pre.get("scenes"):
            # Come dalla UI: prima storia, luoghi e oggetti descritti, poi le inquadrature.
            from .preproduction import preproduce
            pre = bible["pre"] = preproduce(prod.get("treatment", ""), minutes, bible.get("characters", []),
                                            bible.get("style", ""), generate=writer(prod.get("settings")))
        shots = plan_storyboard(
            treatment=prod.get("treatment", ""),
            minutes=minutes,
            style=bible.get("style", ""),
            characters=bible.get("characters", []),
            shot_seconds=(shot_min, shot_max),
            pre=pre,
            generate=writer(prod.get("settings")),
        )
        if replace:
            prod["shots"] = shots
        else:
            prod.setdefault("shots", []).extend(shots)
        manager.store.save(prod)
        return _esito("video_prod_plan_storyboard", True, prod_id=prod_id, shots=prod["shots"], count=len(shots))
    except Exception as exc:
        return _esito("video_prod_plan_storyboard", False, error=str(exc))


def video_prod_add_shot(prod_id: str, prompt: str, seconds: float = 4.0, transition: str = "cut",
                        scene: str = "Scena", props: Optional[List[str]] = None,
                        characters: Optional[List[str]] = None, audio: str = "") -> dict:
    from .production import manager, new_shot
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_prod_add_shot", False, error=f"Produzione non trovata: {prod_id}")
    if transition not in ("cut", "continue"):
        return _esito("video_prod_add_shot", False, error="transition deve essere 'cut' o 'continue'")
    try:
        # new_shot vuole duration_s: passata come `seconds` finiva in un campo che nessuno legge.
        shot = new_shot(prompt, max(1.0, min(15.0, float(seconds))), transition,
                        scene=scene, props=list(props or []), refs=list(characters or []), audio=audio)
        prod.setdefault("shots", []).append(shot)
        manager.store.save(prod)
        idx = len(prod["shots"]) - 1
        return _esito("video_prod_add_shot", True, shot=_shot_summary(idx, shot), shot_index=idx, prod_id=prod_id)
    except Exception as exc:
        return _esito("video_prod_add_shot", False, error=str(exc))


def video_prod_update_shot(prod_id: str, shot_index: int, prompt: Optional[str] = None,
                           seconds: Optional[float] = None, transition: Optional[str] = None,
                           props: Optional[List[str]] = None, characters: Optional[List[str]] = None,
                           audio: Optional[str] = None) -> dict:
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_prod_update_shot", False, error=f"Produzione non trovata: {prod_id}")
    shots = prod.get("shots") or []
    if shot_index < 0 or shot_index >= len(shots):
        return _esito("video_prod_update_shot", False, error=f"Indice inquadratura non valido: {shot_index} (totali: {len(shots)})")
    
    shot = shots[shot_index]
    if prompt is not None:
        shot["prompt"] = prompt.strip()
    if seconds is not None:
        shot["duration_s"] = max(1.0, min(15.0, float(seconds)))
    if transition is not None:
        if transition.strip() not in ("cut", "continue"):
            return _esito("video_prod_update_shot", False, error="transition deve essere 'cut' o 'continue'")
        shot["transition"] = transition.strip()
    if props is not None:
        shot["props"] = props
    if characters is not None:
        shot["refs"] = characters
    if audio is not None:
        shot["audio"] = audio

    manager.store.save(prod)
    return _esito("video_prod_update_shot", True, shot=_shot_summary(shot_index, shot), shot_index=shot_index,
                  prod_id=prod_id)


# ---------------------------------------------------------------------------
# Esecutori: Render, QA e Clip Judge
# ---------------------------------------------------------------------------

def _start_render(prod_id: str) -> dict:
    from core.modules.sigma_creative_lab.creative_router import model_router
    from .production import manager
    return manager.start(prod_id, config=model_router.get_config())


def video_render_shot(prod_id: str, shot_index: int, gpu: int = 0) -> dict:
    """Rimette in coda una inquadratura e avvia il render della produzione (solo i clip mancanti)."""
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_render_shot", False, error=f"Produzione non trovata: {prod_id}")
    shots = prod.get("shots") or []
    if shot_index < 0 or shot_index >= len(shots):
        return _esito("video_render_shot", False, error=f"Indice inquadratura non valido: {shot_index}")
    if manager.active():
        return _esito("video_render_shot", False, error="un render e' gia' in corso: attendi con video_render_status")
    shots[shot_index].update(status="pending", attempts=0)
    manager.store.save(prod)
    try:
        _start_render(prod_id)
    except (RuntimeError, ValueError) as exc:
        return _esito("video_render_shot", False, error=str(exc))
    return _esito("video_render_shot", True, prod_id=prod_id, shot_index=shot_index, status="started",
                  hint="il render gira in background: controlla con video_render_status")


def video_render(prod_id: str) -> dict:
    """Rende tutte le inquadrature mancanti della produzione e alla fine la monta."""
    try:
        _start_render(prod_id)
    except (RuntimeError, ValueError) as exc:
        return _esito("video_render", False, error=str(exc))
    return _esito("video_render", True, prod_id=prod_id, status="started",
                  hint="il render gira in background: controlla con video_render_status")


def video_render_status(prod_id: str = "") -> dict:
    """Avanzamento del render e ultimi eventi (inquadratura corrente, nuovi tentativi, esiti del giudice)."""
    from .production import manager, summary
    active = manager.active()
    events = [{k: e.get(k) for k in ("type", "message", "shot", "status")} for e in manager.events()
              if not prod_id or e.get("production") in (prod_id, None)][-12:]
    prod = manager.store.get(prod_id) if prod_id else None
    return _esito("video_render_status", True, active=active, running=bool(active),
                  production=summary(prod) if prod else None, events=events)


def video_judge_clip(clip_path: str, intent: str, camera: str = "", prod_id: str = "") -> dict:
    """Giudizio sulla clip con la stessa soglia della produzione: `passed` e' la decisione da seguire."""
    from . import clip_judge
    from .production import manager, resolve_judge_device
    target = Path(clip_path)
    if not target.is_file():
        return _esito("video_judge_clip", False, error=f"File video non trovato: {clip_path}")
    settings = ((manager.store.get(prod_id) or {}).get("settings") or {}) if prod_id else {}
    threshold = float(settings.get("judge_threshold", clip_judge.PASS_SCORE))
    full_intent = f"{intent.strip()} Camera: {camera.strip()}." if camera.strip() else intent
    try:
        # Il dispositivo come nella pipeline: 8B sulla GPU piccola (~15 s) invece del 30B sulla CPU (~85 s).
        verdict = clip_judge.judge.judge(target, full_intent, resolve_judge_device(settings), threshold)
        score = verdict.get("score")
        return _esito("video_judge_clip", True, verdict=verdict, clip_path=str(target), threshold=threshold,
                      passed=bool(verdict.get("ok", score is not None and score >= threshold)))
    except Exception as exc:
        return _esito("video_judge_clip", False, error=str(exc))


def video_inspect_shot(prod_id: str, shot_index: int) -> dict:
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_inspect_shot", False, error=f"Produzione non trovata: {prod_id}")
    shots = prod.get("shots") or []
    if shot_index < 0 or shot_index >= len(shots):
        return _esito("video_inspect_shot", False, error=f"Indice inquadratura non valido: {shot_index}")
    shot = shots[shot_index]
    takes = [{k: t.get(k) for k in ("id", "clip_path", "kind", "score", "heard", "match")}
             for t in shot.get("takes") or []]
    return _esito(
        "video_inspect_shot", True, prod_id=prod_id, shot_index=shot_index,
        shot={**_shot_summary(shot_index, shot), "prompt": shot.get("prompt", ""), "audio": shot.get("audio", ""),
              "clip_path": shot.get("clip_path", ""), "keyframe": shot.get("keyframe", ""),
              "keyframe_check": shot.get("keyframe_check")},
        judge_history=(shot.get("judge_history") or [])[-3:], takes=takes[-4:],
    )


# ---------------------------------------------------------------------------
# Esecutori: Timeline ed Editor
# ---------------------------------------------------------------------------

def video_timeline_get(prod_id: str) -> dict:
    from .production import manager
    from .timeline import TimelineStore
    try:
        ts = TimelineStore(manager.store)
        tl = ts.get(prod_id)
        history = ts.history_depth(prod_id)
        return _esito("video_timeline_get", True, prod_id=prod_id, timeline=tl, history=history)
    except Exception as exc:
        return _esito("video_timeline_get", False, error=str(exc))


# ---------------------------------------------------------------------------
# Esecutori: Model sheet, personaggi nella storia, fotogrammi chiave
# ---------------------------------------------------------------------------

def _busy_gpu() -> str:
    from .production import manager
    active = manager.active()
    return f"la GPU e' occupata dal render di {active['production']}: riprova a render finito" if active else ""


def video_char_sheet(char_id: str, views: Optional[List[str]] = None) -> dict:
    """Model sheet (profilo, retro, primo piano, espressioni) controllato dal giudice: ~40 s."""
    from . import character_library
    if _busy_gpu():
        return _esito("video_char_sheet", False, error=_busy_gpu())
    try:
        char = asyncio.run(character_library.sheet(char_id, views or None))
    except Exception as exc:
        return _esito("video_char_sheet", False, error=str(exc))
    sheet = {v: {"score": e.get("score"), "differences": e.get("differences") or []}
             for v, e in (char.get("sheet") or {}).items()}
    return _esito("video_char_sheet", True, char_id=char_id, sheet=sheet)


def video_char_to_production(char_id: str, prod_id: str) -> dict:
    """Porta un personaggio della libreria nella bibbia della produzione (riferimento, aspetto, voce)."""
    from . import character_library
    try:
        entry = character_library.to_production(char_id, prod_id)
    except Exception as exc:
        return _esito("video_char_to_production", False, error=str(exc))
    return _esito("video_char_to_production", True, prod_id=prod_id, name=entry["name"],
                  has_voice=bool(entry.get("voice_sample")),
                  hint=f"usa \"{entry['name']}\" in characters delle inquadrature in cui compare")


def video_keyframes(prod_id: str, shot_indices: Optional[List[int]] = None, missing_only: bool = True) -> dict:
    """Primi fotogrammi delle inquadrature: con i riferimenti dei personaggi li disegna FLUX.2 klein."""
    from .production import generate_keyframes, manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_keyframes", False, error=f"Produzione non trovata: {prod_id}")
    if _busy_gpu():
        return _esito("video_keyframes", False, error=_busy_gpu())
    shots = prod.get("shots") or []
    ids = [shots[i]["id"] for i in shot_indices or [] if 0 <= int(i) < len(shots)] or None
    try:
        done = asyncio.run(generate_keyframes(manager.store, prod_id, ids, missing_only=missing_only))
    except Exception as exc:
        return _esito("video_keyframes", False, error=str(exc))
    fresh = manager.store.get(prod_id)
    checks = [{"index": i, "check": (sh.get("keyframe_check") or {}).get("issues") or []}
              for i, sh in enumerate(fresh.get("shots") or []) if sh.get("keyframe")]
    return _esito("video_keyframes", True, prod_id=prod_id, generated=done, keyframes=checks)


def video_shot_fix(prod_id: str, shot_index: int, fix: str, rerender: bool = False) -> dict:
    """Correzione del QA: entra nel prompt dei prossimi tentativi; con rerender la clip si rifa' subito."""
    from .production import add_prompt_fix, manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_shot_fix", False, error=f"Produzione non trovata: {prod_id}")
    shots = prod.get("shots") or []
    if shot_index < 0 or shot_index >= len(shots) or not str(fix or "").strip():
        return _esito("video_shot_fix", False, error="serve un indice valido e una correzione non vuota")
    shot = shots[shot_index]
    add_prompt_fix(shot, {"prompt_fix": str(fix).strip()})
    shot.update(status="pending", attempts=0)
    manager.store.save(prod)
    if rerender:
        return video_render_shot(prod_id, shot_index)
    return _esito("video_shot_fix", True, shot=_shot_summary(shot_index, shot))


# ---------------------------------------------------------------------------
# Esecutori: Editor (dialoghi, lezioni, scene didattiche, esportazione)
# ---------------------------------------------------------------------------

def _editor_job(nome: str, prod_id: str, kind: str, args: dict) -> dict:
    """I job dell'editor girano in coda sul server: si controllano con video_job_status."""
    from .editor_jobs import editor_jobs
    try:
        job = editor_jobs().submit(prod_id, kind, {k: v for k, v in args.items() if v not in (None, "")})
    except Exception as exc:
        return _esito(nome, False, error=str(exc))
    return _esito(nome, True, prod_id=prod_id, job_id=job["id"], status=job["status"],
                  hint="controlla l'avanzamento con video_job_status")


def video_dialogue(prod_id: str, character: str, text: str, action: str = "", emotion: str = "",
                   setting: str = "", ambience: str = "") -> dict:
    """Battuta in campo: voce del personaggio, poi video col labiale sincronizzato (LTX) o R2V (H3)."""
    return _editor_job("video_dialogue", prod_id, "dialogue", {"character": character, "text": text, "action": action,
                                                               "emotion": emotion, "setting": setting,
                                                               "ambience": ambience})


def video_scene(prod_id: str, description: str, seconds: float = 8.0, mode: str = "kit") -> dict:
    """Scena didattica esatta (formule, grafici, traiettorie, figure geometriche) resa dal browser."""
    return _editor_job("video_scene", prod_id, "scene", {"description": description, "seconds": float(seconds),
                                                         "mode": mode if mode in ("kit", "html") else "kit"})


def video_lesson(prod_id: str, topic: str, minutes: float = 1.0, audience: str = "", voice_id: str = "") -> dict:
    """Lezione animata intera: copione a capitoli, narrazione, una scena per capitolo, montaggio."""
    return _editor_job("video_lesson", prod_id, "lesson", {"topic": topic, "minutes": float(minutes),
                                                           "audience": audience, "voice_id": voice_id})


def video_export(prod_id: str) -> dict:
    """Esporta il montaggio della timeline in un MP4 (con upscale se impostato nella produzione)."""
    return _editor_job("video_export", prod_id, "export", {})


def video_job_status(prod_id: str = "", job_id: str = "") -> dict:
    from .editor_jobs import editor_jobs
    jobs = [j for j in editor_jobs().list(prod_id or None) if not job_id or j["id"] == job_id][:8]
    return _esito("video_job_status", True, jobs=[{k: j.get(k) for k in ("id", "kind", "status", "message", "progress",
                                                                          "error", "result")} for j in jobs])


# ---------------------------------------------------------------------------
# Mappa Esecutori & Dispatcher
# ---------------------------------------------------------------------------

ESECUTORI: Dict[str, Callable] = {
    "video_char_list": video_char_list,
    "video_char_get": video_char_get,
    "video_char_create": video_char_create,
    "video_char_update": video_char_update,
    "video_char_candidates": video_char_candidates,
    "video_char_pick": video_char_pick,
    "video_char_view_prompt": video_char_view_prompt,
    "video_prod_list": video_prod_list,
    "video_prod_get": video_prod_get,
    "video_prod_create": video_prod_create,
    "video_prod_plan_storyboard": video_prod_plan_storyboard,
    "video_prod_add_shot": video_prod_add_shot,
    "video_prod_update_shot": video_prod_update_shot,
    "video_render_shot": video_render_shot,
    "video_judge_clip": video_judge_clip,
    "video_inspect_shot": video_inspect_shot,
    "video_timeline_get": video_timeline_get,
    "video_render": video_render,
    "video_render_status": video_render_status,
    "video_char_sheet": video_char_sheet,
    "video_char_to_production": video_char_to_production,
    "video_keyframes": video_keyframes,
    "video_shot_fix": video_shot_fix,
    "video_dialogue": video_dialogue,
    "video_scene": video_scene,
    "video_lesson": video_lesson,
    "video_export": video_export,
    "video_job_status": video_job_status,
}

READ_TOOLS = frozenset({
    "video_char_list", "video_char_get", "video_char_view_prompt",
    "video_prod_list", "video_prod_get", "video_inspect_shot", "video_timeline_get",
    "video_render_status", "video_job_status",
})

WRITE_TOOLS = frozenset({
    "video_char_create", "video_char_update", "video_char_candidates", "video_char_pick",
    "video_prod_create", "video_prod_plan_storyboard", "video_prod_add_shot",
    "video_prod_update_shot", "video_render_shot", "video_judge_clip",
    "video_render", "video_char_sheet", "video_char_to_production", "video_keyframes", "video_shot_fix",
    "video_dialogue", "video_scene", "video_lesson", "video_export",
})


def esegui(nome: str, argomenti: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Invocazione del tool con isolamento degli errori."""
    fn = ESECUTORI.get(nome)
    if fn is None:
        return _esito(nome, False, error=f"Tool sconosciuto: '{nome}'")
    args = dict(argomenti or {})
    try:
        return fn(**args)
    except TypeError as exc:
        try:
            params = [p for p in inspect.signature(fn).parameters]
        except (TypeError, ValueError):
            params = []
        return _esito(
            nome,
            False,
            error=f"Argomenti non validi per '{nome}': {exc}. Parametri attesi: {', '.join(params) or 'nessuno'}.",
            accepted_parameters=params,
        )
    except Exception as exc:
        log.exception("[video_tools] Errore esecuzione '%s'", nome)
        return _esito(nome, False, error=str(exc))


# ---------------------------------------------------------------------------
# Aggancio al Kernel
# ---------------------------------------------------------------------------

def provider():
    """Confeziona il ToolProvider per l'harness di Sigma Studio."""
    from core.harness.tool_providers import ToolProvider

    nomi_dichiarati = {
        s["function"]["name"] if isinstance(s, dict) and "function" in s
        else (getattr(s, "name", None) or s.get("name", ""))
        for s in SCHEMI
    }

    alias = {nome: nome for nome in ESECUTORI if nome in nomi_dichiarati}
    read_only = {t for t in READ_TOOLS if t in nomi_dichiarati}
    write = {t for t in WRITE_TOOLS if t in nomi_dichiarati}

    return ToolProvider(
        id="sigma_creative_video",
        label="Video Studio & Cinema",
        schemas=tuple(SCHEMI),
        execute=esegui,
        read_only=frozenset(read_only),
        write=frozenset(write),
        aliases=alias,
        roles=VIDEO_ROLES,
    )


def registra() -> List[str]:
    """Registra i tool e i 5 ruoli cinematografici nel kernel."""
    from core.harness import tool_providers
    return tool_providers.register(provider())
