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


def video_soundtrack(prod_id: str, tags: str = "", enabled: bool = True, bpm: int = 0, keyscale: str = "",
                     music_db: float = 0.0, remix: bool = True) -> dict:
    """Colonna sonora della produzione (ACE-Step) e, a clip finite, nuovo montaggio con la musica sotto.

    Prima esisteva solo nell'interfaccia: nel collaudo Mx0 l'agente aveva il
    capitolo montato e nessun modo di aggiungere la musica che gli era chiesta.
    """
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_soundtrack", False, error=f"Produzione non trovata: {prod_id}")
    st = prod.setdefault("soundtrack", {})
    st["enabled"] = bool(enabled)
    if str(tags or "").strip():
        st["tags"] = str(tags).strip()
    if bpm:
        st["bpm"] = int(bpm)
    if str(keyscale or "").strip():
        st["keyscale"] = str(keyscale).strip()
    if music_db:
        st["music_db"] = float(music_db)
    manager.store.save(prod)
    shots = prod.get("shots") or []
    pronte = bool(shots) and all(s.get("status") == "done" for s in shots)
    if not (remix and enabled and pronte):
        return _esito("video_soundtrack", True, prod_id=prod_id, soundtrack=st,
                      hint="la musica entra al prossimo montaggio (video_render a clip finite)")
    try:
        _start_render(prod_id)
    except (RuntimeError, ValueError) as exc:
        return _esito("video_soundtrack", False, error=str(exc), soundtrack=st)
    return _esito("video_soundtrack", True, prod_id=prod_id, soundtrack=st, status="started",
                  hint="tutte le clip sono pronte: si rimonta con la musica; controlla con video_render_status")


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
    # Con i percorsi l'agente puo' confrontare subito fotogramma e vignetta con
    # view_image; senza, li cercava a tentoni con glob (collaudo Mx0: venti giri in data/).
    checks = [{"index": i, "keyframe": sh["keyframe"], "panel": sh.get("source_panel", ""),
               "check": (sh.get("keyframe_check") or {}).get("issues") or []}
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
    if shot.get("keyframe"):
        # LTX parte dal fotogramma chiave: se il difetto e' gia' li', correggere solo
        # il prompt del video lo lascia nella clip (collaudo Mx0, 005_03: il doppione
        # di Kuzumi restava). Il fotogramma si rifa' con la stessa correzione.
        kf = shot.setdefault("keyframe_fixes", [])
        if str(fix).strip() not in kf:
            kf.append(str(fix).strip())
            del kf[:-2]
        shot.pop("keyframe", None)
        shot.pop("keyframe_check", None)
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


# ---------------------------------------------------------------------------
# Esecutori: restauro di film muti
# ---------------------------------------------------------------------------

def _elemento(prod_id: str, item_id: str = "") -> dict:
    """L'elemento della timeline indicato, o l'unico presente: un film restaurato e' spesso un elemento solo."""
    from .production import manager
    from . import timeline as T
    prod = manager.store.get(prod_id)
    if prod is None:
        raise ValueError(f"produzione inesistente: {prod_id}")
    items = T.layout(T.TimelineStore(manager.store).get(prod_id), prod)["items"]
    if item_id:
        hit = next((it for it in items if it["id"] == item_id), None)
        if hit is None:
            raise ValueError(f"elemento {item_id} non nella timeline; elementi: {[it['id'] for it in items]}")
        return hit
    if len(items) != 1:
        raise ValueError(f"la timeline ha {len(items)} elementi: indica item_id fra {[it['id'] for it in items]}")
    return items[0]


def _job_su_elemento(nome: str, prod_id: str, item_id: str, kind: str, args: dict) -> dict:
    try:
        item = _elemento(prod_id, item_id)
    except ValueError as exc:
        return _esito(nome, False, error=str(exc))
    return _editor_job(nome, prod_id, kind, {"item_id": item["id"], **args})


def video_restore_fetch(prod_id: str, url: str, label: str = "") -> dict:
    """Scarica un film da Wikimedia Commons o Internet Archive e lo importa (pulldown rimosso se serve)."""
    return _editor_job("video_restore_fetch", prod_id, "restore_fetch", {"url": url, "label": label})


def video_recolor(prod_id: str, item_id: str = "") -> dict:
    """Ricolora un elemento in bianco e nero (DDColor, colori stabili nel tempo, didascalie lasciate in b/n)."""
    return _job_su_elemento("video_recolor", prod_id, item_id, "recolor", {})


def video_upscale(prod_id: str, item_id: str = "", height: int = 1440) -> dict:
    """Ingrandisce un elemento con Real-ESRGAN (nuova versione)."""
    return _job_su_elemento("video_upscale", prod_id, item_id, "upscale", {"height": int(height)})


def video_restore_read(prod_id: str, item_id: str = "", title: str = "") -> dict:
    """Trova didascalie e pagine scritte, le legge col modello visivo e decide chi pronuncia ciascuna."""
    return _job_su_elemento("video_restore_read", prod_id, item_id, "restore_read", {"title": title})


def video_restore_narrate(prod_id: str, item_id: str = "", language: str = "en") -> dict:
    """Legge ad alta voce i testi (una voce per personaggio) e li mette sulla traccia voce della timeline."""
    return _job_su_elemento("video_restore_narrate", prod_id, item_id, "restore_narrate", {"language": language})


def video_restore_score(prod_id: str, item_id: str = "", style: str = "", redescribe: bool = False) -> dict:
    """Colonna sonora a sequenze di ~3 minuti, con l'atmosfera di quello che si vede, sulla traccia musica."""
    return _job_su_elemento("video_restore_score", prod_id, item_id, "restore_score",
                            {"style": style, "redescribe": bool(redescribe)})


def video_restore_mood_fix(prod_id: str, index: int, tags: str, item_id: str = "") -> dict:
    """Corregge l'atmosfera di una sequenza; video_restore_score poi rifa' solo i brani cambiati."""
    from .production import manager
    from . import restoration as R
    try:
        item = _elemento(prod_id, item_id)
        moods = R.update_moods(manager.store.path(prod_id), item["shot_id"], [{"index": index, "tags": tags}])
    except ValueError as exc:
        return _esito("video_restore_mood_fix", False, error=str(exc))
    m = moods[int(index)]
    return _esito("video_restore_mood_fix", True, index=int(index), start=m["start"], end=m["end"], tags=m["tags"],
                  hint="rilancia video_restore_score (senza redescribe) per rifare i brani corretti")


def video_restore_cards(prod_id: str, item_id: str = "", start: int = 0, count: int = 40, query: str = "") -> dict:
    """Testi letti (con indice, tempo, tipo, personaggio) e voci assegnate; `query` filtra per parola."""
    from .production import manager
    from . import restoration as R
    try:
        item = _elemento(prod_id, item_id)
    except ValueError as exc:
        return _esito("video_restore_cards", False, error=str(exc))
    state = R.load_state(manager.store.path(prod_id), item["shot_id"])
    cards = [{"index": i, **{k: c.get(k) for k in ("start", "end", "kind", "speaker", "gender", "age", "menacing",
                                                    "text", "deleted", "needs_review", "seen")}}
             for i, c in enumerate(state.get("cards") or [])]
    if query == "needs_review":
        cards = [c for c in cards if c["needs_review"]]
    elif query:
        q = query.lower()
        cards = [c for c in cards if q in (c["text"] or "").lower() or q in (c["speaker"] or "").lower()]
    start = max(0, int(start))
    return _esito("video_restore_cards", True, total=len(cards), cards=cards[start:start + max(1, int(count))],
                  speakers=sorted({c["speaker"] for c in cards if c["speaker"]}),
                  voices={k: v.get("voice") for k, v in (state.get("voices") or {}).items()},
                  moods=[{"index": i, "start": m.get("start"), "end": m.get("end"), "tags": m.get("tags"),
                          "edited": bool(m.get("edited"))} for i, m in enumerate(state.get("moods") or [])])


def video_restore_card_fix(prod_id: str, index: int, item_id: str = "", text: str = "", speaker: str = "",
                           delete: bool = False, gender: str = "", age: str = "",
                           menacing: Optional[bool] = None) -> dict:
    """Corregge un testo letto (testo, personaggio, voce) o lo esclude dalla narrazione."""
    from .production import manager
    from . import restoration as R
    try:
        item = _elemento(prod_id, item_id)
        cards = R.update_cards(manager.store.path(prod_id), item["shot_id"], [{
            "index": index, "text": text or None, "speaker": speaker, "delete": delete, "gender": gender,
            "age": age, "menacing": menacing}])
    except ValueError as exc:
        return _esito("video_restore_card_fix", False, error=str(exc))
    c = cards[int(index)]
    return _esito("video_restore_card_fix", True, index=int(index), card={k: c.get(k) for k in (
        "speaker", "text", "deleted")}, hint="rilancia video_restore_narrate per rifare le voci")


def video_contact_sheet(prod_id: str, item_id: str = "", every_s: float = 0) -> dict:
    """Provino dell'elemento (36 fotogrammi su tutta la durata): guardalo con view_image."""
    from .production import manager
    from . import restoration as R
    try:
        item = _elemento(prod_id, item_id)
        out = manager.store.path(prod_id) / "restoration" / f"provino_{item['id']}_{item.get('take_id', '')}.jpg"
        R.contact_sheet(Path(item["clip_path"]), out, float(every_s or 0))
    except Exception as exc:
        return _esito("video_contact_sheet", False, error=str(exc))
    return _esito("video_contact_sheet", True, path=str(out), hint="guardalo con view_image")


#: Attesa massima di una sola chiamata: abbastanza per non martellare, non tanto da bloccare il turno.
ATTESA_MAX_S = 300


def video_job_status(prod_id: str = "", job_id: str = "", wait_s: float = 0) -> dict:
    """Stato dei job; con `wait_s` aspetta finche' qualcosa cambia o i job finiscono.

    Senza attesa l'agente interrogava lo stato a raffica, o si arrangiava con
    `Start-Sleep` dal terminale, per un job di lettura che dura un'ora.
    """
    import time
    from .editor_jobs import editor_jobs

    def istantanea():
        return [(j["id"], j["status"], j.get("message"), j.get("progress"))
                for j in editor_jobs().list(prod_id or None) if not job_id or j["id"] == job_id][:8]

    try:
        attesa = max(0.0, min(float(wait_s or 0), ATTESA_MAX_S))
    except (TypeError, ValueError):
        attesa = 0.0
    if attesa:
        prima = istantanea()
        scadenza = time.monotonic() + attesa
        while time.monotonic() < scadenza:
            ora = istantanea()
            attivi = [x for x in ora if x[1] in ("queued", "running")]
            # Un cambio di pagina o di stato basta: l'agente vede che il lavoro avanza.
            if ora != prima and (not attivi or [x[1:3] for x in ora] != [x[1:3] for x in prima]):
                break
            if not attivi:
                break
            time.sleep(5)
    jobs = [j for j in editor_jobs().list(prod_id or None) if not job_id or j["id"] == job_id][:8]
    return _esito("video_job_status", True, jobs=[{k: j.get(k) for k in ("id", "kind", "status", "message", "progress",
                                                                          "error", "result")} for j in jobs])


# ---------------------------------------------------------------------------
# Esecutori: trasposizione da fumetto (manga vignetta per vignetta)
# ---------------------------------------------------------------------------

def _percorso(path: str) -> Path:
    """Assoluto, o relativo alla radice del progetto: le scan stanno in data/, fuori dai worktree."""
    from core import paths
    p = Path(str(path or "").strip().strip('"'))
    return p if p.is_absolute() else paths.project_root() / p


def video_char_from_image(char_id: str, image_path: str, region: Optional[List[float]] = None,
                          count: int = 2) -> dict:
    """Proposte del riferimento ridisegnate da un'immagine dell'opera (copertina, tavola a colori, vignetta)."""
    from . import character_library
    try:
        char = asyncio.run(character_library.candidates_from_image(
            char_id, str(_percorso(image_path)), region=region, count=count))
    except Exception as exc:
        return _esito("video_char_from_image", False, error=str(exc))
    folder = character_library.characters_dir() / char_id
    nuove = [c for c in char.get("candidates") or [] if c.get("source")][:4]
    return _esito("video_char_from_image", True, char_id=char_id,
                  source_crop=str(folder / nuove[0]["source"]) if nuove else "",
                  candidates=[{"file": c["file"], "path": str(folder / c["file"])}
                              for c in char.get("candidates") or []][:4],
                  clothes_visible=nuove[0].get("clothes_visible") if nuove else None,
                  warning=("nel ritaglio non si vedono i vestiti: nelle proposte sono inventati dalla descrizione. "
                           "Rifai da una vignetta a figura intera o mezza figura dove si vede come e' vestito"
                           if nuove and nuove[0].get("clothes_visible") is False else ""),
                  hint="guarda con view_image PRIMA source_crop (deve contenere proprio questo personaggio) e poi "
                       "le proposte; scegli con video_char_pick solo se assomigliano al ritaglio")


def video_manga_read(prod_id: str, folder: str, exclude_pages: Optional[List[str]] = None) -> dict:
    """Collega un capitolo alla produzione e ne legge tutte le vignette (job lungo)."""
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_manga_read", False, error=f"Produzione non trovata: {prod_id}")
    cartella = _percorso(folder)
    if not cartella.is_dir():
        return _esito("video_manga_read", False, error=f"Cartella non trovata: {cartella}")
    escluse = [Path(str(x)).stem for x in exclude_pages or []]
    prod["manga"] = {"folder": str(cartella), "exclude": escluse}
    manager.store.save(prod)
    return _editor_job("video_manga_read", prod_id, "manga_read", {"folder": str(cartella), "exclude": escluse})


def _vignette(prod_id: str) -> tuple[dict, Path]:
    from .production import manager
    from . import manga
    prod = manager.store.get(prod_id)
    if not prod:
        raise ValueError(f"Produzione non trovata: {prod_id}")
    cartella = manga.cartella_di(prod)
    file = cartella / "vignette.json"
    if not file.is_file():
        raise ValueError("il capitolo non e' ancora stato letto: controlla il job con video_job_status")
    import json
    return json.loads(file.read_text(encoding="utf-8")), cartella


def video_manga_pages(prod_id: str) -> dict:
    """Panoramica del capitolo letto: vignette per pagina, testi, regia, immagini di controllo."""
    try:
        stato, cartella = _vignette(prod_id)
    except Exception as exc:
        return _esito("video_manga_pages", False, error=str(exc))
    pagine = []
    for p in stato.get("pagine") or []:
        vv = p.get("vignette") or []
        pagine.append({
            "page": p["pagina"], "panels": len(vv), "error": p.get("errore", ""),
            "segmentation": p.get("segmentazione", ""),
            "control_image": str(cartella / "vignette" / f"{Path(p['pagina']).stem}_controllo.png"),
            "texts": sum(len(v.get("testi") or []) for v in vv),
            "unreadable": [v["id"] for v in vv if v.get("errore")],
            "directed": sum(1 for v in vv if (v.get("regia") or {}).get("shot_en")),
        })
    from . import manga
    tipi = {}
    for f in sorted(cartella.iterdir()):
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            try:
                tipi[f.name] = manga.classifica_pagina(f)
            except Exception as exc:
                log.debug("[video_tools] pagina %s non classificata: %s", f.name, exc)
    foglio = cartella / "vignette" / "provino.png"
    try:
        if not foglio.is_file():
            manga.provino(cartella, foglio)
    except Exception as exc:
        log.warning("[video_tools] provino non creato: %s", exc)
    return _esito("video_manga_pages", True, folder=str(cartella), pages=pagine,
                  total_panels=sum(p["panels"] for p in pagine),
                  color_pages=[n for n, t in tipi.items() if t == "colore"],
                  dark_pages=[n for n, t in tipi.items() if t == "nera"],
                  contact_sheet=str(foglio) if foglio.is_file() else "",
                  hint="guarda contact_sheet con view_image per riconoscere copertine e crediti; "
                       "le color_pages danno i colori veri dei personaggi")


def video_manga_panel(prod_id: str, panel_id: str) -> dict:
    """Tutta la lettura di una vignetta, col percorso del ritaglio da guardare con view_image."""
    try:
        stato, cartella = _vignette(prod_id)
    except Exception as exc:
        return _esito("video_manga_panel", False, error=str(exc))
    for p in stato.get("pagine") or []:
        for v in p.get("vignette") or []:
            if v["id"] == str(panel_id).strip():
                return _esito("video_manga_panel", True, page=p["pagina"],
                              panel={**v, "ritaglio": str(cartella / v["ritaglio"])})
    return _esito("video_manga_panel", False, error=f"Vignetta non trovata: {panel_id} (formato: 008_04)")


#: Caratteri per risposta del copione: sta nell'osservazione di un modello locale senza troncarla.
COPIONE_MAX = 7000


def video_manga_script(prod_id: str, from_page: str = "", to_page: str = "", query: str = "") -> dict:
    """Il capitolo come copione compatto: una riga per testo, nell'ordine del manga.

    Nel collaudo Mx0 l'agente cercava i nomi dei personaggi con search_code su
    tutto il repository e poi leggeva vignette.json a blocchi di 200 righe:
    migliaia di righe di riquadri e descrizioni per arrivare a trecento
    battute. Qui ci sono solo le battute, con l'id della vignetta per tornare
    a guardarla, e `query` filtra per parola (un nome, un onorifico).
    """
    import re
    try:
        stato, _cartella = _vignette(prod_id)
    except Exception as exc:
        return _esito("video_manga_script", False, error=str(exc))
    da, a = Path(str(from_page or "")).stem, Path(str(to_page or "")).stem
    cerca = str(query or "").strip().lower()
    righe, prossima = [], ""
    totale = 0
    for p in stato.get("pagine") or []:
        pagina = Path(p["pagina"]).stem
        if (da and pagina < da) or (a and pagina > a):
            continue
        for v in p.get("vignette") or []:
            for t in v.get("testi") or []:
                if cerca and cerca not in t["testo"].lower():
                    continue
                chi = f" ({t['chi']})" if t.get("chi") and t["chi"] != "fuori campo" else ""
                riga = f"{v['id']} [{t['tipo']}]{chi} {t['testo']}"
                if totale + len(riga) > COPIONE_MAX:
                    prossima = prossima or pagina
                    continue
                righe.append(riga)
                totale += len(riga) + 1
    if not righe and cerca:
        return _esito("video_manga_script", True, lines=[], note=f"nessun testo contiene '{query}'")
    nomi = sorted({m for r in righe for m in re.findall(r"\b[A-Z]{3,}-(?:SENSEI|SENPAI|SAMA|KUN|CHAN|SAN)\b", r)})
    return _esito("video_manga_script", True, lines=righe, count=len(righe),
                  honorific_names=nomi,
                  next_from_page=prossima,
                  hint=(f"testo troncato: continua con from_page='{prossima}'" if prossima else ""))


#: Nomi che non sono nomi: con questi l'agente ha "creato" personaggi che nel fumetto non esistono.
NOMI_GENERICI = ("eroe", "avversario", "protagonista", "antagonista", "hero", "villain", "nemico", "rivale",
                 "personaggio", "character")
#: Una parola romanizzata giapponese: sillabe (consonante)+vocale, o N finale. Filtra i candidati
#: nomi fra le parole maiuscole dei balloon (AIKA, KUZUMI, TAIGA si', ANDARE no).
_ROMAJI = None


def _e_romaji(parola: str) -> bool:
    import re
    global _ROMAJI
    if _ROMAJI is None:
        _ROMAJI = re.compile(r"^(?:(?:SH|CH|TS|KY|SY|NY|HY|MY|RY|GY|BY|PY|[KSTNHMYRWGZDBPJF])?[AIUEO]|N)+$")
    return bool(_ROMAJI.match(parola))


#: Parole italiane frequenti che passano il filtro delle sillabe giapponesi.
_NON_NOMI = frozenset("""MANO SONO SANO NOME TUTTO TUTTI MAI SEI HAI NOI LEI LUI CHE NON SUO SUA MIO MIA TUO TUA
DOVE COME COSA ORA POI ANNO ANNI MESE GIORNO ZONA META MODO MURO MURA NUOVO NUOVA BUONO BUONA DONNA SEMBRA
SEMPRE SAPERE ANDARE DIRE FARE AMORE AMICO AMICI AMICA PADRE MADRE MONTE PIANO TENERE VIENI VENIRE GUARDA TIPO
DIAVOLO RAGAZZO RAGAZZA RAGAZZI SCUOLA SANTUARIO SEGUIRE SUBITO PURE MIRA RAMO SEGNO DITE DATO DATE RESTA
UNA UNO UNE ANCHE BENE MENO PUNTI PUNTO MAGIA MAGIE MAGO MAGHI TANTO TANTI TANTA POCO POCHI MOLTO MOLTI MOLTA
DOPO PRIMA SOPRA SOTTO DENTRO FUORI TUTTA TUTTE ANCORA PROPRIO SOLO SOLA NUOVI NUOVE STESSO STESSA ALTRO
ALTRA ALTRI SUBITO PERO NIENTE NESSUNO NESSUNA DUNQUE INSOMMA DAVVERO VERO VERA PARE PARI FATTO FATTA DETTO
DETTA DIRE SAI SAPPIAMO SIAMO SIETE ERANO ERA ERO SARA SARAI SARANNO STATO STATA TORNA TORNARE TEMPO MOMENTO
MANI PIEDI TESTA BOCCA OCCHI CUORE VITA MORTE CASA PORTA FINE INIZIO SENSO MONDO TERRA CIELO PIANETA ZONA
DIVENTARE DIVENTA DIVENTATO RIMANERE MANDARE MANGIARE PARLARE PORTARE TOCCARE TORNARE PENSARE TROVARE
""".split())


#: Davanti a un nome comune: articoli, preposizioni (anche articolate), possessivi.
_ARTICOLI = frozenset("""IL LO LA I GLI LE UN UNO UNA L DI A DA IN CON SU PER TRA FRA DEL DELLO DELLA DEI DEGLI
DELLE AL ALLO ALLA AI AGLI ALLE DAL DALLO DALLA DAI DAGLI DALLE NEL NELLO NELLA NEI NEGLI NELLE SUL SULLO
SULLA SUI SUGLI SULLE COL QUESTA QUESTO QUELLA QUELLO MIA MIO TUA TUO SUA SUO NOSTRA NOSTRO""".split())
_INTERIEZIONI = frozenset("EHI AHI OHI UHI HAI EH AH OH UH MAH BAH UFFA".split())


def video_manga_cast(prod_id: str) -> dict:
    """I nomi propri che compaiono nelle battute: chi e' nel capitolo, prima di creare personaggi.

    Nel collaudo Mx0 l'agente ha creato «Mx0 (Eroe)» e «Mx0 (Avversario)»
    senza aver trovato un nome, mentre il capitolo nominava AIKA, KUZUMI,
    TAIGA e HIRAGI-SENSEI. Qui i candidati sono gia' contati, con le vignette
    in cui compaiono e due righe di contesto: resta da decidere chi e' chi
    guardando quelle vignette.
    """
    import re
    from collections import defaultdict
    try:
        stato, _cartella = _vignette(prod_id)
    except Exception as exc:
        return _esito("video_manga_cast", False, error=str(exc))
    from .production import manager
    escluse = set(((manager.store.get(prod_id) or {}).get("manga") or {}).get("exclude") or [])
    trovati = defaultdict(list)
    didascalie, prima_persona = 0, 0
    for p in stato.get("pagine") or []:
        if Path(p["pagina"]).stem in escluse:
            continue
        for v in p.get("vignette") or []:
            for t in v.get("testi") or []:
                if t["tipo"] == "onomatopea":
                    continue
                if t["tipo"] == "didascalia":
                    didascalie += 1
                    if re.search(r"\b(MI|HO|SONO|MIO|MIA|NON L'HO|IO)\b", t["testo"]):
                        prima_persona += 1
                testo = t["testo"]
                for m in re.finditer(r"\b([A-Z]{3,})(?:-(SENSEI|SENPAI|SAMA|KUN|CHAN|SAN))?\b", testo):
                    parola, onorifico = m.group(1), m.group(2)
                    if not (onorifico or (_e_romaji(parola) and parola not in _NON_NOMI
                                          and parola not in _INTERIEZIONI)):
                        continue
                    nome = f"{parola}-{onorifico}" if onorifico else parola
                    prima = re.findall(r"[A-Z']+", testo[:m.start()].upper())
                    dopo = testo[m.end():m.end() + 2]
                    seguente = re.match(r"\s+([A-Z]{3,})", testo[m.end():])
                    trovati[nome].append((v["id"], testo, {
                        # «LA MAGIA», «DI MAGIA»: con l'articolo o la preposizione e' un nome comune.
                        "comune": bool(prima) and prima[-1].rstrip("'") in _ARTICOLI,
                        # «AIKA!», «KUZUMI TAIGA!!», «, AIKA»: cosi' si chiama una persona.
                        "vocativo": bool(re.match(r"\s*[!?,.]", dopo)) or testo[:m.start()].rstrip().endswith(","),
                        "accanto": bool(seguente and _e_romaji(seguente.group(1))
                                        and seguente.group(1) not in _NON_NOMI),
                    }))
    candidati = []
    for nome, usi in sorted(trovati.items(), key=lambda x: -len(x[1])):
        segni = [u[2] for u in usi]
        onorifico = "-" in nome
        comuni = sum(1 for s in segni if s["comune"])
        da_nome = sum(1 for s in segni if s["vocativo"] or s["accanto"])
        if not onorifico and (comuni * 2 > len(usi) or da_nome == 0):
            continue
        if len(usi) < 2 and not onorifico:
            continue
        candidati.append({"name": nome, "count": len(usi),
                          "panels": list(dict.fromkeys(u[0] for u in usi))[:8],
                          "context": [u[1] for u in usi[:2]]})
    narratore = (f"{prima_persona} didascalie su {didascalie} sono in prima persona (MI, HO, SONO...): "
                 "se sono la voce del protagonista, e' lui il narratore" if prima_persona else "")
    return _esito("video_manga_cast", True, candidates=candidates_limit(candidati), captions=didascalie,
                  narrator_hint=narratore,
                  hint="i candidati possono essere luoghi o parole: guarda le vignette in 'panels' con "
                       "video_manga_panel + view_image per capire chi e' chi, poi crea un personaggio per nome. "
                       "Nomi e cognomi dello stesso personaggio (es. TAIGA e KUZUMI) vanno in un solo personaggio.")


def candidates_limit(candidati: list, massimo: int = 15) -> list:
    return candidati[:massimo]


def _nomi_pagina(valori, cartella: Optional[Path]) -> List[str]:
    """Pagine come le scrive l'agente (4, "4", "004.jpg") ricondotte al nome del file (004).

    Nel collaudo l'agente ha passato 4 e 7: salvati cosi', non coincidevano con
    nessuna pagina e le pagine nere restavano nel video.
    """
    stems = []
    if cartella and Path(cartella).is_dir():
        stems = [f.stem for f in Path(cartella).iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    out = []
    for x in valori or []:
        s = Path(str(x).strip()).stem
        if s.isdigit():
            s = next((st for st in stems if st.isdigit() and int(st) == int(s)), s.zfill(3))
        if s:
            out.append(s)
    return sorted(set(out))


def video_manga_exclude(prod_id: str, pages: Optional[List[str]] = None,
                        not_characters: Optional[List[str]] = None) -> dict:
    """Le pagine fuori dalla storia e i nomi del cast che non sono personaggi (luoghi, parole)."""
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_manga_exclude", False, error=f"Produzione non trovata: {prod_id}")
    info = prod.setdefault("manga", {})
    if pages is not None:
        info["exclude"] = _nomi_pagina(pages, Path(info["folder"]) if info.get("folder") else None)
        info["esclusioni_decise"] = True
    if not_characters is not None:
        info["not_characters"] = sorted({str(x).strip().upper() for x in not_characters if str(x).strip()})
    escluse = info.get("exclude") or []
    manager.store.save(prod)
    return _esito("video_manga_exclude", True, excluded=escluse,
                  not_characters=info.get("not_characters") or [],
                  hint="richiama video_manga_next per il passo successivo")


def video_prod_remove_character(prod_id: str, name: str) -> dict:
    """Toglie un personaggio dalla bibbia della produzione (non dalla libreria)."""
    from .production import manager
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_prod_remove_character", False, error=f"Produzione non trovata: {prod_id}")
    bibbia = (prod.get("bible") or {}).get("characters") or []
    resto = [c for c in bibbia if c.get("name") != name]
    if len(resto) == len(bibbia):
        return _esito("video_prod_remove_character", False,
                      error=f"'{name}' non e' nella bibbia: {[c.get('name') for c in bibbia]}")
    prod["bible"]["characters"] = resto
    manager.store.save(prod)
    return _esito("video_prod_remove_character", True, removed=name, bible=[c.get("name") for c in resto])


def _job_attivo(prod_id: str, tipo: str) -> Optional[dict]:
    from .editor_jobs import editor_jobs
    for j in editor_jobs().list(prod_id):
        if j["kind"] == tipo and j["status"] in ("queued", "running"):
            return j
    return None


def _passo(fase: str, cosa: str, tool: str = "", **extra) -> dict:
    return _esito("video_manga_next", True, phase=fase, next_step=cosa, next_tool=tool, **extra)


def video_manga_next(prod_id: str) -> dict:
    """Dove e' arrivata la trasposizione e qual e' il prossimo passo, ricavato dallo stato su disco.

    La procedura scritta non bastava: nel collaudo Mx0 l'agente saltava la
    ricognizione, creava personaggi prima di leggere i nomi e, dopo un
    riavvio, ripartiva da un file sbagliato. Questo tool non ricorda niente:
    guarda produzione, lettura, bibbia e storyboard e dice cosa manca, nello
    stesso ordine ogni volta. Va chiamato a ogni passo.
    """
    import json
    from .production import manager
    from . import manga
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_manga_next", False, error=f"Produzione non trovata: {prod_id}")
    info = prod.get("manga") or {}
    if not info.get("folder"):
        return _passo("1 lettura", "collega il capitolo e leggi tutte le vignette", "video_manga_read",
                      args={"prod_id": prod_id, "folder": "<cartella delle pagine>"})
    job = _job_attivo(prod_id, "manga_read")
    if job:
        return _passo("1 lettura", f"lettura in corso: {job.get('message', '')}. Aspetta con "
                      "video_job_status e wait_s=300, poi richiama video_manga_next; non fare altro sulla GPU.",
                      "video_job_status", args={"prod_id": prod_id, "wait_s": 300})
    cartella = Path(info["folder"])
    if not (cartella / "vignette.json").is_file():
        return _passo("1 lettura", "la lettura non e' stata fatta o e' fallita: rilancia", "video_manga_read",
                      args={"prod_id": prod_id, "folder": str(cartella)})
    stato = json.loads((cartella / "vignette.json").read_text(encoding="utf-8"))
    pagine_cartella = [f for f in cartella.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if len(stato.get("pagine") or []) < len(pagine_cartella):
        return _passo("1 lettura", "mancano pagine da leggere: rilancia la lettura (riprende da dove era)",
                      "video_manga_read", args={"prod_id": prod_id, "folder": str(cartella)})

    if "exclude" not in info or info.get("exclude") is None or info.get("esclusioni_decise") is not True:
        pagine = video_manga_pages(prod_id)
        return _passo("2 ricognizione",
                      "guarda contact_sheet con view_image e decidi le pagine fuori dalla storia "
                      "(copertine, crediti, pagine nere, commento dell'autore), poi chiama video_manga_exclude "
                      "anche con una lista vuota se non ce ne sono",
                      "video_manga_exclude", contact_sheet=pagine.get("contact_sheet"),
                      color_pages=pagine.get("color_pages"), dark_pages=pagine.get("dark_pages"))

    escluse = set(_nomi_pagina(info.get("exclude") or [], cartella))
    illeggibili = [v["id"] for p in stato["pagine"] if Path(p["pagina"]).stem not in escluse
                   for v in p.get("vignette") or [] if v.get("errore")]

    bibbia = [c for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name")]
    generici = [c["name"] for c in bibbia
                if "(" in c["name"] or any(g in c["name"].lower() for g in NOMI_GENERICI)]
    senza_rif = [c["name"] for c in bibbia if not c.get("ref_image") or not Path(str(c["ref_image"])).is_file()]
    if generici:
        return _passo("3 personaggi", f"nella bibbia ci sono nomi generici {generici}: non sono personaggi del "
                      "fumetto. Toglili dalla produzione e crea i personaggi coi nomi trovati da video_manga_cast",
                      "video_manga_cast", problems=generici)
    from . import character_library
    pagine_info = video_manga_pages(prod_id)
    if len(bibbia) < 2:
        return _passo("3 personaggi",
                      "crea i personaggi del capitolo: nomi da video_manga_cast; per ognuno video_char_create "
                      "(genre anime, descrizione in inglese con i colori delle color_pages), poi "
                      "video_char_from_image su una color_page con region sul personaggio, view_image sulle "
                      "proposte, video_char_pick, video_char_to_production. Aggiungi anche una 'Comparsa'.",
                      "video_manga_cast", color_pages=pagine_info.get("color_pages"),
                      in_bible=[c["name"] for c in bibbia],
                      library_generic=[c["name"] for c in character_library.list_characters()
                                       if any(g in c["name"].lower() for g in NOMI_GENERICI)][:6])
    if senza_rif:
        return _passo("3 personaggi", f"personaggi senza immagine di riferimento: {senza_rif}. Generala con "
                      "video_char_from_image da una color_page e riportali con video_char_to_production",
                      "video_char_from_image", color_pages=pagine_info.get("color_pages"))
    # Ogni nome che il capitolo ripete deve avere il suo personaggio, e serve una
    # comparsa per chi non ha nome: nel collaudo la regia e' partita con due soli
    # personaggi, e le battute di Hiragi-sensei sarebbero finite a nessuno.
    cast = video_manga_cast(prod_id).get("candidates") or []
    nomi_bibbia = " ".join(c["name"].lower().replace("-", " ") for c in bibbia)
    non_personaggi = set(info.get("not_characters") or [])
    assenti = [c["name"] for c in cast if c["count"] >= 3 and c["name"].upper() not in non_personaggi
               and not all(parte in nomi_bibbia for parte in c["name"].lower().replace("-", " ").split()
                           if parte not in ("sensei", "senpai", "sama", "kun", "chan", "san"))]
    if assenti:
        return _passo("3 personaggi", f"nomi ricorrenti nelle battute senza personaggio in bibbia: {assenti}. "
                      "Se sono persone del capitolo, crea il personaggio (o, se esiste gia' in libreria, portalo "
                      "con video_char_to_production); se sono luoghi o parole, dichiaralo con "
                      "video_manga_exclude(prod_id, not_characters=[...])", "video_char_to_production",
                      in_bible=[c["name"] for c in bibbia], missing=assenti)
    if not any("compars" in c["name"].lower() or "extra" in c["name"].lower() for c in bibbia):
        return _passo("3 personaggi", "manca una comparsa generica per chi non ha nome (guardie, passanti, "
                      "studenti): creala e portala nella bibbia con video_char_to_production",
                      "video_char_to_production", in_bible=[c["name"] for c in bibbia])

    job = _job_attivo(prod_id, "manga_direct")
    if job:
        return _passo("4 regia", f"regia in corso: {job.get('message', '')}. Aspetta con video_job_status "
                      "e wait_s=300, poi richiama video_manga_next.", "video_job_status",
                      args={"prod_id": prod_id, "wait_s": 300})
    firma = manga._elenco_personaggi([{"name": c["name"], "description": c.get("description", "")}
                                      for c in bibbia])
    da_dirigere = [v["id"] for p in stato["pagine"] if Path(p["pagina"]).stem not in escluse
                   for v in p.get("vignette") or [] if (v.get("regia") or {}).get("firma") != firma]
    if da_dirigere:
        return _passo("4 regia", f"{len(da_dirigere)} vignette senza regia coi personaggi attuali: lanciala",
                      "video_manga_direct", args={"prod_id": prod_id}, unreadable_panels=illeggibili)

    # Le pagine nere restano fuori in ogni caso: nel collaudo l'agente ha escluso solo il
    # commento dell'autore, e copertine e separatori sarebbero diventati inquadrature.
    nere = [Path(n).stem for n in (pagine_info.get("dark_pages") or [])]
    mancanti = [n for n in nere if n not in escluse]
    if mancanti:
        return _passo("2 ricognizione", f"le pagine nere {mancanti} non sono escluse: nel video diventerebbero "
                      "inquadrature vuote. Guarda contact_sheet con view_image (prime e ultime pagine: copertine, "
                      "crediti, commento dell'autore) e richiama video_manga_exclude con la lista completa",
                      "video_manga_exclude", contact_sheet=pagine_info.get("contact_sheet"),
                      excluded=sorted(escluse), dark_pages=nere)

    job = _job_attivo(prod_id, "manga_speakers")
    if job:
        return _passo("4 voci", f"rilettura delle voci in corso: {job.get('message', '')}. Aspetta con "
                      "video_job_status e wait_s=300.", "video_job_status", args={"prod_id": prod_id, "wait_s": 300})
    da_rivedere = [v["id"] for p in stato["pagine"] if Path(p["pagina"]).stem not in escluse
                   for v in p.get("vignette") or []
                   if any(t["tipo"] != "onomatopea" for t in v.get("testi") or [])
                   and not (v.get("regia") or {}).get("voci_riviste")]
    if da_rivedere:
        return _passo("4 voci", f"{len(da_rivedere)} vignette con battute attribuite solo dalla vista, vignetta "
                      "per vignetta: fai rileggere il copione intero per correggere chi parla (narratore = chi "
                      "dice le didascalie in prima persona)", "video_manga_speakers",
                      args={"prod_id": prod_id, "narrator": "<nome>"})

    shots = prod.get("shots") or []
    if shots and stato.get("voci_riviste_il") and info.get("storyboard_voci") != stato.get("voci_riviste_il"):
        return _passo("5 storyboard", "le voci sono state riviste dopo lo storyboard: ricostruiscilo perche' "
                      "le battute abbiano chi le dice davvero", "video_manga_storyboard",
                      args={"prod_id": prod_id, "narrator": "<nome>"})
    if not shots or not all(s.get("panel_id") for s in shots):
        return _passo("5 storyboard", "costruisci lo storyboard dal fumetto (narratore = chi dice le didascalie)",
                      "video_manga_storyboard", args={"prod_id": prod_id, "narrator": "<nome>"})
    nomi = {c["name"] for c in bibbia}
    mute = sorted({s["dialogue"]["character"] for s in shots if s.get("dialogue")} - nomi)
    if mute:
        return _passo("5 storyboard", f"parlanti non in bibbia: {mute}. Aggiungili e rifai lo storyboard",
                      "video_char_create")
    prime = [i for i, s in enumerate(shots[:5]) if not s.get("keyframe")]
    if prime:
        return _passo("6 prova", "genera i fotogrammi chiave delle prime 5 inquadrature", "video_keyframes",
                      args={"prod_id": prod_id, "shot_indices": prime, "missing_only": True})
    da_guardare = [{"index": i, "keyframe": s.get("keyframe"), "panel": s.get("source_panel")}
                   for i, s in enumerate(shots[:5])]
    return _passo("7 controllo", "guarda ogni fotogramma con view_image accanto alla sua vignetta: stessa "
                  "inquadratura, pose, colori giusti, nessuna scritta. Rigenera quelli sbagliati con "
                  "video_shot_fix + video_keyframes; poi chiudi con complete_goal riportando cosa hai fatto e "
                  "chiedendo all'utente il via per il render", "view_image", check=da_guardare,
                  shots=len(shots))


def video_manga_fix_panel(prod_id: str, panel_id: str, texts: Optional[List[dict]] = None,
                          shot_size: str = "", action: str = "", note: str = "") -> dict:
    """Corregge la lettura di una vignetta dopo averla guardata: testi in ordine, piano, azione."""
    import json
    try:
        stato, cartella = _vignette(prod_id)
    except Exception as exc:
        return _esito("video_manga_fix_panel", False, error=str(exc))
    from . import manga
    for p in stato.get("pagine") or []:
        for v in p.get("vignette") or []:
            if v["id"] != str(panel_id).strip():
                continue
            if texts is not None:
                v["testi"] = manga._normalizza_lettura({"testi": texts})["testi"]
            if shot_size:
                v["inquadratura"] = shot_size.strip().lower()
            if action:
                v["azione"] = action.strip()
            if note:
                v.setdefault("correzioni", []).append(note.strip())
            v["corretta"] = True
            v.pop("regia", None)          # la regia va rifatta sulla lettura corretta
            (cartella / "vignette.json").write_text(json.dumps(stato, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
            return _esito("video_manga_fix_panel", True, panel=v)
    return _esito("video_manga_fix_panel", False, error=f"Vignetta non trovata: {panel_id}")


def video_manga_direct(prod_id: str) -> dict:
    """Regia di ogni vignetta coi personaggi della bibbia: chi c'e', chi parla, inquadratura in inglese."""
    return _editor_job("video_manga_direct", prod_id, "manga_direct", {})


def video_manga_speakers(prod_id: str, narrator: str) -> dict:
    """Dopo la regia: rilegge il copione intero e corregge chi dice ogni battuta (job lungo)."""
    return _editor_job("video_manga_speakers", prod_id, "manga_speakers", {"narrator": narrator})


def video_manga_storyboard(prod_id: str, narrator: str, extra_character: str = "Comparsa",
                           exclude_pages: Optional[List[str]] = None) -> dict:
    """Sostituisce le inquadrature con quelle del fumetto: una per vignetta, una per ogni battuta."""
    from .production import manager, new_shot
    from . import manga
    prod = manager.store.get(prod_id)
    if not prod:
        return _esito("video_manga_storyboard", False, error=f"Produzione non trovata: {prod_id}")
    nomi = {c.get("name") for c in (prod.get("bible") or {}).get("characters") or []}
    if narrator not in nomi:
        return _esito("video_manga_storyboard", False,
                      error=f"'{narrator}' non e' nella bibbia: personaggi disponibili {sorted(n for n in nomi if n)}")
    try:
        escluse = _nomi_pagina(exclude_pages, manga.cartella_di(prod))
        if escluse:
            prod.setdefault("manga", {})["exclude"] = sorted(set(escluse))
        escluse = _nomi_pagina((prod.get("manga") or {}).get("exclude") or [], manga.cartella_di(prod))
        shots = manga.storyboard(manga.cartella_di(prod), narrator, extra_character, escluse)
        prod.setdefault("manga", {})["narrator"] = narrator
    except Exception as exc:
        return _esito("video_manga_storyboard", False, error=str(exc))
    from .production import _prompt_hash
    prod["shots"] = [new_shot(**s) for s in shots]
    for shot in prod["shots"]:
        # La regia scrive gia' in inglese, un'azione e un movimento di camera per
        # inquadratura: la riscrittura per LTX col 27B (che ragiona sempre) costava
        # ore su 375 inquadrature senza aggiungere niente.
        shot["ltx_prompt"] = {"text": shot["prompt"], "source": _prompt_hash(shot["prompt"])}
    try:
        import json
        stato_v = json.loads((manga.cartella_di(prod) / "vignette.json").read_text(encoding="utf-8"))
        prod.setdefault("manga", {})["storyboard_voci"] = stato_v.get("voci_riviste_il")
    except Exception as exc:
        log.debug("[video_tools] impronta delle voci non letta: %s", exc)
    # Ogni inquadratura parte dalla sua vignetta ridisegnata: servono i fotogrammi chiave.
    prod.setdefault("settings", {})["keyframes"] = True
    manager.store.save(prod)
    senza_regia = sum(1 for s in shots if not s["refs"] and not s.get("dialogue"))
    battute = [s for s in shots if s.get("dialogue")]
    sconosciuti = sorted({s["dialogue"]["character"] for s in battute} - nomi)
    return _esito("video_manga_storyboard", True, prod_id=prod_id, shots=len(shots), lines=len(battute),
                  silent_without_characters=senza_regia,
                  speakers_missing_from_bible=sconosciuti,
                  hint=("aggiungi alla bibbia i personaggi in speakers_missing_from_bible (anche una comparsa "
                        "generica) prima del render, altrimenti quelle battute restano mute") if sconosciuti else "")


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
    "video_soundtrack": video_soundtrack,
    "video_dialogue": video_dialogue,
    "video_scene": video_scene,
    "video_lesson": video_lesson,
    "video_export": video_export,
    "video_job_status": video_job_status,
    "video_char_from_image": video_char_from_image,
    "video_manga_read": video_manga_read,
    "video_manga_pages": video_manga_pages,
    "video_manga_panel": video_manga_panel,
    "video_manga_script": video_manga_script,
    "video_manga_next": video_manga_next,
    "video_manga_cast": video_manga_cast,
    "video_manga_exclude": video_manga_exclude,
    "video_prod_remove_character": video_prod_remove_character,
    "video_manga_fix_panel": video_manga_fix_panel,
    "video_manga_direct": video_manga_direct,
    "video_manga_speakers": video_manga_speakers,
    "video_manga_storyboard": video_manga_storyboard,
    "video_restore_fetch": video_restore_fetch,
    "video_recolor": video_recolor,
    "video_upscale": video_upscale,
    "video_restore_read": video_restore_read,
    "video_restore_cards": video_restore_cards,
    "video_restore_card_fix": video_restore_card_fix,
    "video_restore_narrate": video_restore_narrate,
    "video_restore_score": video_restore_score,
    "video_restore_mood_fix": video_restore_mood_fix,
    "video_contact_sheet": video_contact_sheet,
}

READ_TOOLS = frozenset({
    "video_char_list", "video_char_get", "video_char_view_prompt",
    "video_prod_list", "video_prod_get", "video_inspect_shot", "video_timeline_get",
    "video_render_status", "video_job_status", "video_manga_pages", "video_manga_panel", "video_manga_script",
    "video_manga_next", "video_manga_cast", "video_restore_cards",
})

WRITE_TOOLS = frozenset({
    "video_char_create", "video_char_update", "video_char_candidates", "video_char_pick",
    "video_prod_create", "video_prod_plan_storyboard", "video_prod_add_shot",
    "video_prod_update_shot", "video_render_shot", "video_judge_clip",
    "video_render", "video_char_sheet", "video_char_to_production", "video_keyframes", "video_shot_fix",
    "video_soundtrack", "video_dialogue", "video_scene", "video_lesson", "video_export",
    "video_char_from_image", "video_manga_read", "video_manga_fix_panel", "video_manga_direct",
    "video_manga_storyboard", "video_manga_exclude", "video_prod_remove_character", "video_manga_speakers",
    "video_restore_fetch", "video_recolor", "video_upscale", "video_restore_read", "video_restore_card_fix",
    "video_restore_narrate", "video_restore_score", "video_restore_mood_fix", "video_contact_sheet",
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
