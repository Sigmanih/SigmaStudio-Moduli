"""Rotte HTTP delle produzioni video lunghe.

Il render dura ore: le rotte avviano il lavoro su un thread e rispondono
subito; la UI segue lo stato leggendo il manifest e gli eventi.
"""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import paths
from core.logger import get_logger
from core.modules.sigma_creative_lab.video.production import (
    DEFAULT_SETTINGS, manager, new_shot, plan_storyboard, summary, writer,
)

log = get_logger("creative_production_routes")

_planning: dict[str, str] = {}          # id produzione -> messaggio di avanzamento
_planning_lock = threading.Lock()
_planning_stop: dict[str, threading.Event] = {}   # id produzione -> richiesta di stop dello storyboard/fotogrammi


def _begin_planning(pid: str, message: str) -> threading.Event | None:
    """Prenota la preparazione di una produzione; None se ce n'e' gia' una in corso."""
    with _planning_lock:
        if _planning.get(pid):
            return None
        _planning[pid] = message
        _planning_stop[pid] = threading.Event()
        return _planning_stop[pid]


def _end_planning(pid: str) -> None:
    with _planning_lock:
        _planning.pop(pid, None)
        _planning_stop.pop(pid, None)


def _note(pid: str):
    def note(msg: str) -> None:
        with _planning_lock:
            if pid in _planning:
                _planning[pid] = msg
    return note


def _qs(handler) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(handler.path).query).items()}


def _url(path: str) -> str:
    """URL servito dal frontend per un file dell'utente (/data/... o /works/...)."""
    return paths.public_url(path)


def _decorate(prod: dict) -> dict:
    prod = dict(prod)
    prod["output_url"] = _url(prod.get("output_path", ""))
    prod["shots"] = [{**s, "clip_url": _url(s.get("clip_path", "")), "frame_url": _url(s.get("last_frame", "")),
                      "keyframe_url": _url(s.get("keyframe", ""))} for s in prod.get("shots", [])]
    prod["summary"] = summary(prod)
    prod["style_image_url"] = _url((prod.get("bible") or {}).get("style_image", ""))
    prod["animatic_url"] = _url(prod.get("animatic_path", ""))
    out = Path(prod.get("output_path") or "")
    for key, ext in (("subtitles_url", ".srt"), ("subtitles_vtt_url", ".vtt")):
        prod[key] = _url(str(out.with_suffix(ext))) if out.name and out.with_suffix(ext).is_file() else ""
    with _planning_lock:
        prod["planning"] = _planning.get(prod["id"], "")
    return prod


def _ok(handler, **data):
    handler.send_json_response({"success": True, **data})


def _err(handler, msg: str, status: int = 400):
    handler.send_json_response({"success": False, "error": msg}, status)


def handle_productions_list(self):
    """GET /api/creative/productions"""
    try:
        from core.modules.sigma_creative_lab.native.runtime import auto_lanes, get_runtime
        ok, why = get_runtime().availability()
        _ok(self, productions=manager.store.list(), active=manager.active(),
            native={"installed": ok, "detail": why, "lanes": auto_lanes()}, defaults=DEFAULT_SETTINGS)
    except Exception as e:
        log.error(f"elenco produzioni: {e}")
        _err(self, str(e), 500)


def handle_production_get(self):
    """GET /api/creative/productions/get?id=..."""
    try:
        prod = manager.store.get(_qs(self).get("id", ""))
        if not prod:
            return _err(self, "produzione inesistente", 404)
        _ok(self, production=_decorate(prod), active=manager.active())
    except ValueError as e:
        _err(self, str(e))


def handle_production_events(self):
    """GET /api/creative/productions/events?since=<timestamp>"""
    try:
        since = float(_qs(self).get("since", 0) or 0)
    except ValueError:
        since = 0.0
    _ok(self, events=manager.events(since), active=manager.active())


def handle_production_create(self):
    """POST /api/creative/productions/create {title, treatment?, settings?, bible?, shots?}"""
    data = self.read_json_body()
    if not str(data.get("title", "")).strip():
        return _err(self, "il titolo e' obbligatorio")
    try:
        shots = [new_shot(**s) if "status" not in s else s for s in (data.get("shots") or [])]
        settings, bible = dict(data.get("settings") or {}), dict(data.get("bible") or {})
        soundtrack = dict(data.get("soundtrack") or {})
        from core.modules.sigma_creative_lab.video.genres import GENRES
        genre = GENRES.get(str(data.get("genre") or ""))
        if genre:
            # Il genere riempie solo cio' che l'utente non ha scelto da se'.
            bible["genre"] = data["genre"]
            if not str(bible.get("style") or "").strip():
                bible["style"] = genre["style"]
            settings.setdefault("keyframes", genre["keyframes"])
            soundtrack.setdefault("tags", genre["music"])
        prod = manager.store.create(data["title"], settings=settings, bible=bible,
                                    shots=shots, treatment=data.get("treatment", ""),
                                    soundtrack=soundtrack or None)
        _ok(self, production=_decorate(prod))
    except (TypeError, ValueError) as e:
        _err(self, str(e))


_EDITABLE_SHOT_KEYS = {"prompt", "audio", "duration_s", "transition", "refs", "seed", "scene", "status", "props", "dialogue",
                       "location", "expressions", "engine"}


def handle_production_update(self):
    """POST /api/creative/productions/update {id, title?, treatment?, settings?, bible?, shots?}

    Le inquadrature si possono riscrivere solo a render fermo. Un'inquadratura
    modificata torna `pending`, cosi' il prossimo render la rigenera.
    """
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    active = manager.active()
    if active and active["production"] == prod["id"]:
        return _err(self, "render in corso: fermalo prima di modificare", 409)
    for key in ("title", "treatment"):
        if key in data:
            prod[key] = str(data[key])
    if isinstance(data.get("settings"), dict):
        prod["settings"].update(data["settings"])
    prev_bible = {"characters": [dict(c) for c in (prod.get("bible") or {}).get("characters") or []]}
    if isinstance(data.get("bible"), dict):
        prod["bible"].update(data["bible"])
    if isinstance(data.get("soundtrack"), dict):
        prod.setdefault("soundtrack", {}).update(data["soundtrack"])
        # Parametri musicali cambiati: i brani gia' generati non valgono piu'.
        music = manager.store.path(prod["id"]) / "music"
        for f in music.glob("music_*.flac") if music.is_dir() else []:
            f.unlink(missing_ok=True)
        prod.pop("soundtrack_path", None)
    edited: set = set()
    if isinstance(data.get("shots"), list):
        old = {s["id"]: s for s in prod["shots"]}
        shots = []
        for s in data["shots"]:
            prev = old.get(s.get("id"))
            if prev is None:
                shots.append(new_shot(**{k: v for k, v in s.items() if k in _EDITABLE_SHOT_KEYS | {"id"}}))
                edited.add(shots[-1]["id"])
                continue
            changed = any(k in s and s[k] != prev.get(k) for k in _EDITABLE_SHOT_KEYS - {"status"})
            merged = {**prev, **{k: v for k, v in s.items() if k in _EDITABLE_SHOT_KEYS - {"status"}}}
            # Dal browser solo "rimetti in coda" o "salta": uno stato "pronta" di una bozza vecchia
            # riportava indietro una clip che il server aveva appena rimesso in coda.
            if s.get("status") in ("pending", "skipped"):
                merged["status"] = s["status"]
            if changed:
                merged.update(status="pending", attempts=0, error="")
            if "prompt" in s and s["prompt"] != prev.get("prompt"):
                # Il fotogramma chiave disegnava la descrizione vecchia.
                merged.pop("keyframe", None)
                edited.add(merged["id"])
            shots.append(merged)
        prod["shots"] = shots
    if isinstance(data.get("bible"), dict):
        # Voce cambiata: le sue battute gia' rese parlano con la voce vecchia, vanno rifatte. Dopo l'unione
        # con le inquadrature inviate, che altrimenti riporterebbero il loro stato "pronta".
        before = {c.get("name"): c.get("voice_id", "") for c in prev_bible.get("characters") or []}
        voiced = {c.get("name") for c in prod["bible"].get("characters") or []
                  if c.get("name") in before and c.get("voice_id", "") != before[c.get("name")]}
        for sh in prod["shots"]:
            if (sh.get("dialogue") or {}).get("character") in voiced:
                sh.update(status="pending", attempts=0)
    _english_edits(prod, edited, data.get("bible") if isinstance(data.get("bible"), dict) else {})
    manager.store.save(prod)
    _ok(self, production=_decorate(prod))


def _english_edits(prod: dict, shot_ids: set, bible_in: dict) -> None:
    """Le descrizioni scritte a mano in un'altra lingua arrivano ai modelli in inglese.

    Solo i testi appena modificati: le battute restano nella lingua del film.
    """
    from core.modules.sigma_creative_lab.video.preproduction import needs_english, to_english
    slots = [(sh, "prompt") for sh in prod.get("shots") or [] if sh["id"] in shot_ids]
    pre = prod["bible"].get("pre") or {}
    if "pre" in bible_in:
        slots += [(x, "description") for x in (pre.get("locations") or []) + (pre.get("props") or [])]
    if "characters" in bible_in:
        slots += [(c, "description") for c in prod["bible"].get("characters") or []]
    slots = [(obj, key) for obj, key in slots if needs_english(str(obj.get(key) or ""))]
    if not slots:
        return
    for (obj, key), text in zip(slots, to_english([str(obj[key]) for obj, key in slots], writer(prod["settings"]))):
        obj[key] = text


def handle_production_preproduction(self):
    """POST /api/creative/productions/preproduction {id, minutes}

    L'agente sviluppa la storia e descrive luoghi e oggetti (bible["pre"]): l'utente li rilegge e
    li corregge prima che si scriva una sola inquadratura.
    """
    from core.modules.sigma_creative_lab.video.preproduction import PreproductionCancelled, preproduce
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    if not prod.get("treatment", "").strip():
        return _err(self, "scrivi prima il soggetto: anche solo un'idea, in qualsiasi lingua")
    if manager.active():
        return _err(self, "un render occupa la GPU: la storia userebbe l'LLM sulla stessa scheda", 409)
    pid = prod["id"]
    stop = _begin_planning(pid, "Sviluppo della storia...")
    if stop is None:
        return _err(self, "un'altra preparazione e' in corso", 409)
    minutes = float(data.get("minutes") or 1.0)

    def _work():
        try:
            fresh = manager.store.get(pid)
            pre = preproduce(fresh["treatment"], minutes, fresh["bible"].get("characters") or [],
                             fresh["bible"].get("style", ""), generate=writer(fresh["settings"]),
                             progress=_note(pid), cancel=stop)
            cur = manager.store.get(pid)
            cur["bible"]["pre"] = pre
            cur["error"] = ""
            manager.store.save(cur)
            log.info(f"pre-produzione di {pid}: {len(pre['scenes'])} scene, {len(pre['locations'])} luoghi, "
                     f"{len(pre['props'])} oggetti")
        except PreproductionCancelled as e:
            log.info(f"pre-produzione di {pid} fermata: {e}")
        except Exception as e:
            log.error(f"pre-produzione di {pid} fallita: {e}")
            cur = manager.store.get(pid)
            if cur:
                cur["error"] = f"storia: {e}"
                manager.store.save(cur)
        finally:
            _end_planning(pid)

    threading.Thread(target=_work, name=f"preproduction-{pid}", daemon=True).start()
    _ok(self, planning=True)


def handle_production_storyboard(self):
    """POST /api/creative/productions/storyboard {id, minutes, shot_min?, shot_max?, replace?}

    Lo storyboard e' scritto dall'LLM scena per scena: puo' durare minuti, quindi gira su un
    thread; la UI ne legge l'avanzamento nel campo `planning` e puo' fermarlo (planning/cancel).
    Ogni scena finita viene salvata subito: fermare non butta il lavoro gia' fatto.
    """
    from core.modules.sigma_creative_lab.video.preproduction import PreproductionCancelled
    from core.modules.sigma_creative_lab.video.production import (
        PlanningCancelled, detect_aliases, plan_storyboard, shot_bounds,
    )
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    if not prod.get("treatment", "").strip():
        return _err(self, "manca il soggetto (treatment) da cui scrivere lo storyboard")
    if manager.active():
        return _err(self, "un render occupa la GPU: lo storyboard userebbe l'LLM sulla stessa scheda", 409)
    pid = prod["id"]
    stop = _begin_planning(pid, "Personaggi del soggetto...")
    if stop is None:
        return _err(self, "storyboard gia' in preparazione", 409)
    minutes = float(data.get("minutes") or 1.0)
    lo, hi = shot_bounds(prod["settings"])
    bounds = (float(data.get("shot_min") or lo), float(data.get("shot_max") or hi))
    replace = data.get("replace", True)
    base = [] if replace else list(prod.get("shots") or [])

    def _work():
        note = _note(pid)
        try:
            fresh = manager.store.get(pid)
            chars = fresh["bible"].get("characters") or []
            # Il soggetto chiama spesso il protagonista con un ruolo ("lo shonen"): senza saperlo,
            # lo storyboard ne faceva una seconda persona identica a Mimoki.
            found = detect_aliases(fresh["treatment"], [c for c in chars if not c.get("aliases")],
                                   writer(fresh["settings"]))
            if found:
                for c in chars:
                    if c.get("name") in found and not c.get("aliases"):
                        c["aliases"] = found[c["name"]]
                manager.store.save(fresh)

            def partial(shots):
                cur = manager.store.get(pid)
                cur["shots"] = base + shots
                cur["status"] = "draft"
                manager.store.save(cur)

            pre = fresh["bible"].get("pre") or {}
            if not pre.get("scenes"):
                # Prima di ogni inquadratura la storia, i luoghi e gli oggetti descritti per filo e per segno.
                from core.modules.sigma_creative_lab.video.preproduction import preproduce
                pre = preproduce(fresh["treatment"], minutes, chars, fresh["bible"].get("style", ""),
                                 generate=writer(fresh["settings"]), progress=note, cancel=stop)
                cur = manager.store.get(pid)
                cur["bible"]["pre"] = pre
                manager.store.save(cur)
            note("Scrittura delle inquadrature...")
            shots = plan_storyboard(fresh["treatment"], minutes, style=fresh["bible"].get("style", ""),
                                    characters=chars, shot_seconds=bounds, progress=note, cancel=stop,
                                    on_scene=partial, pre=pre, generate=writer(fresh["settings"]))
            partial(shots)
            cur = manager.store.get(pid)
            cur["error"] = ""
            manager.store.save(cur)
            log.info(f"storyboard di {pid}: {len(shots)} inquadrature")
        except (PlanningCancelled, PreproductionCancelled) as e:
            log.info(f"storyboard di {pid} fermato: {e}")
            cur = manager.store.get(pid)
            if cur:
                cur["error"] = f"storyboard fermato ({e}): le scene gia' scritte sono salvate"
                manager.store.save(cur)
        except Exception as e:
            log.error(f"storyboard di {pid} fallito: {e}")
            cur = manager.store.get(pid)
            if cur:
                cur["error"] = f"storyboard: {e}"
                manager.store.save(cur)
        finally:
            _end_planning(pid)

    threading.Thread(target=_work, name=f"storyboard-{pid}", daemon=True).start()
    _ok(self, planning=True)


def handle_production_planning_cancel(self):
    """POST /api/creative/productions/planning/cancel {id} — ferma storyboard o fotogrammi chiave in corso."""
    data = self.read_json_body()
    with _planning_lock:
        stop = _planning_stop.get(data.get("id", ""))
        if stop:
            stop.set()
            _planning[data.get("id", "")] = "Fermo alla fine del passo in corso..."
    _ok(self, stopping=bool(stop))


def handle_production_scene(self):
    """POST /api/creative/productions/scene {id, scene, notes} — riscrive una scena con le tue indicazioni."""
    from core.modules.sigma_creative_lab.video.production import replan_scene
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    if not str(data.get("notes", "")).strip():
        return _err(self, "scrivi cosa cambiare nella scena")
    if manager.active():
        return _err(self, "un render e' in corso", 409)
    pid, scene = prod["id"], str(data.get("scene", ""))
    if _begin_planning(pid, f"Riscrittura della scena \"{scene}\"...") is None:
        return _err(self, "un'altra preparazione e' in corso", 409)

    def _work():
        try:
            cur = manager.store.get(pid)
            new = replan_scene(cur, scene, str(data["notes"]))
            cur["error"] = ""
            manager.store.save(cur)
            log.info(f"scena '{scene}' di {pid} riscritta: {len(new)} inquadrature")
        except Exception as e:
            log.error(f"scena '{scene}' di {pid}: {e}")
            cur = manager.store.get(pid)
            if cur:
                cur["error"] = f"scena \"{scene}\": {e}"
                manager.store.save(cur)
        finally:
            _end_planning(pid)

    threading.Thread(target=_work, name=f"scene-{pid}", daemon=True).start()
    _ok(self, planning=True)


def handle_production_shot_fix(self):
    """POST /api/creative/productions/shot_fix {id, shot_id, problem?, remove?, redo: "keyframe"|"clip"|"both"|""}

    Correzione dell'utente su un'inquadratura ("il vaso ha il becco come l'annaffiatoio"): diventa un vincolo
    positivo in inglese, salvato nell'inquadratura; poi, se chiesto, si rifanno immagine e/o clip.
    """
    from core.modules.sigma_creative_lab.video.production import user_fix
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    if manager.active():
        return _err(self, "un render e' in corso", 409)
    shot = next((x for x in prod["shots"] if x["id"] == data.get("shot_id")), None)
    if shot is None:
        return _err(self, "inquadratura inesistente", 404)
    try:
        if data.get("remove") is not None:
            k = int(data["remove"])
            shot["fixes"] = [f for i, f in enumerate(shot.get("fixes") or []) if i != k]
        else:
            user_fix(prod, shot["id"], str(data.get("problem", "")))
    except ValueError as e:
        return _err(self, str(e))
    redo = str(data.get("redo") or "")
    if redo in ("keyframe", "both"):
        shot.pop("keyframe", None)
    if redo:
        shot.update(status="pending", attempts=0, error="")
    manager.store.save(prod)
    _ok(self, production=_decorate(prod), fixes=shot.get("fixes") or [])


def handle_production_style_image(self):
    """POST /api/creative/productions/style_image {id, shot_id?} — il fotogramma che fissa lo stile (vuoto = nessuno)."""
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    shot = next((x for x in prod["shots"] if x["id"] == data.get("shot_id")), None)
    path = (shot or {}).get("keyframe", "")
    if data.get("shot_id") and not (path and Path(path).is_file()):
        return _err(self, "l'inquadratura non ha un fotogramma chiave")
    prod.setdefault("bible", {})["style_image"] = path
    manager.store.save(prod)
    _ok(self, production=_decorate(prod))

def handle_genres(self):
    """GET /api/creative/genres — generi di video con i modelli che usano."""
    from core.modules.sigma_creative_lab.video.genres import public_list
    _ok(self, genres=public_list())


def handle_production_portraits(self):
    """POST /api/creative/productions/portraits {id, name, description, count?}

    Ritratti di un personaggio nello stile del genere: l'utente sceglie quello
    giusto, che diventa l'immagine di riferimento. Qualche decina di secondi.
    """
    import asyncio
    from core.modules.sigma_creative_lab.video import genres, image_gen
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    description = str(data.get("description", "")).strip()
    if not description:
        return _err(self, "descrivi l'aspetto del personaggio (in inglese rende meglio)")
    if manager.active():
        return _err(self, "un render occupa la GPU: riprova a render finito", 409)
    model = genres.genre_of(prod)["image_model"]
    if not image_gen.installed(model):
        return _err(self, f"{image_gen.MODELS[model]['label']} non installato (Video Studio → Motori)")
    count = max(1, min(6, int(data.get("count") or 4)))
    name = "".join(c for c in str(data.get("name") or "personaggio") if c.isalnum())[:24] or "personaggio"
    base_seed = int(data.get("seed") or 0) or (abs(hash(description)) % 100000)
    prompt = genres.portrait_prompt(prod, description)

    async def run_all():
        out = []
        for k in range(count):
            seed = base_seed + k * 7919
            target = manager.store.path(prod["id"]) / "refs" / f"portrait_{name}_{seed}.png"
            r = await image_gen.generate(model, prompt, target, width=832, height=1216, seed=seed)
            out.append({"path": r["path"], "url": _url(r["path"]), "seed": seed})
        return out
    try:
        _ok(self, portraits=asyncio.run(run_all()), model=model)
    except Exception as e:
        log.error(f"ritratti di {name}: {e}")
        _err(self, str(e), 500)


def handle_production_keyframes(self):
    """POST /api/creative/productions/keyframes {id, shot_ids?, missing_only?}

    Storyboard illustrato: un'immagine per inquadratura, prima del render.
    Gira su un thread come lo storyboard; l'avanzamento sta in `planning`.
    """
    import asyncio
    from core.modules.sigma_creative_lab.video.production import generate_keyframes
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    if manager.active():
        return _err(self, "un render occupa la GPU: riprova a render finito", 409)
    pid = prod["id"]
    stop = _begin_planning(pid, "Fotogrammi chiave...")
    if stop is None:
        return _err(self, "un'altra preparazione e' in corso", 409)

    def _work():
        from core.modules.sigma_creative_lab.video.production import PlanningCancelled
        note = _note(pid)
        try:
            n = asyncio.run(generate_keyframes(manager.store, pid, data.get("shot_ids") or None,
                                               bool(data.get("missing_only")), note=note, cancel=stop))
            fresh = manager.store.get(pid)
            fresh["settings"]["keyframes"] = True
            manager.store.save(fresh)
            log.info(f"fotogrammi chiave di {pid}: {n}")
            if data.get("render_after") and not manager.active():
                # "Correggi entrambe": la clip riparte dal fotogramma appena ridisegnato.
                from core.modules.sigma_creative_lab.creative_router import model_router
                _end_planning(pid)
                manager.start(pid, config=model_router.get_config())
        except PlanningCancelled as e:
            cur = manager.store.get(pid)
            if cur:
                cur["error"] = f"fotogrammi chiave fermati ({e})"
                manager.store.save(cur)
        except Exception as e:
            log.error(f"fotogrammi chiave di {pid}: {e}")
            fresh = manager.store.get(pid)
            if fresh:
                fresh["error"] = f"fotogrammi chiave: {e}"
                manager.store.save(fresh)
        finally:
            _end_planning(pid)

    threading.Thread(target=_work, name=f"keyframes-{pid}", daemon=True).start()
    _ok(self, planning=True)


def handle_production_render(self):
    """POST /api/creative/productions/render {id, shot_ids?} — con shot_ids rifa solo quelle inquadrature."""
    data = self.read_json_body()
    try:
        from core.modules.sigma_creative_lab.creative_router import model_router
        if data.get("shot_ids"):
            prod = manager.store.get(data.get("id", ""))
            if prod is None:
                return _err(self, "produzione inesistente", 404)
            wanted = set(data["shot_ids"])
            for sh in prod["shots"]:
                if sh["id"] in wanted:
                    sh.update(status="pending", attempts=0, error="")
            manager.store.save(prod)
        result = manager.start(data.get("id", ""), config=model_router.get_config())
        _ok(self, **result)
    except (RuntimeError, ValueError) as e:
        _err(self, str(e), 409)


def handle_production_cancel(self):
    """POST /api/creative/productions/cancel {id}"""
    data = self.read_json_body()
    _ok(self, cancelled=manager.cancel(data.get("id", "")))


def handle_production_assemble(self):
    """POST /api/creative/productions/assemble {id} — rimonta i clip gia' pronti (anche parziali)."""
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
        if not prod:
            return _err(self, "produzione inesistente", 404)
        if manager.active() and manager.active()["production"] == prod["id"]:
            return _err(self, "render in corso", 409)
        from core.modules.sigma_creative_lab.video.production import ProductionRunner
        out = ProductionRunner(manager.store, prod["id"]).assemble(prod)
        prod["output_path"] = str(out)
        manager.store.save(prod)
        _ok(self, production=_decorate(prod))
    except (RuntimeError, ValueError) as e:
        _err(self, str(e), 500)


def handle_production_animatic(self):
    """POST /api/creative/productions/animatic {id} — fotogrammi chiave + voci + tempi, prima del render."""
    from core.modules.sigma_creative_lab.video.production import animatic, prepare_dialogue
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
    except ValueError as e:
        return _err(self, str(e))
    if not prod:
        return _err(self, "produzione inesistente", 404)
    if manager.active():
        return _err(self, "un render e' in corso", 409)
    pid = prod["id"]
    if _begin_planning(pid, "Voci delle battute...") is None:
        return _err(self, "un'altra preparazione e' in corso", 409)

    def _work():
        try:
            cur = manager.store.get(pid)
            prepare_dialogue(manager.store, cur, note=_note(pid))
            manager.store.save(cur)
            _note(pid)("Montaggio dell'anteprima...")
            out = animatic(cur, manager.store.path(pid) / "animatic.mp4", fps=int(cur["settings"].get("fps", 24)))
            cur = manager.store.get(pid)
            cur["animatic_path"] = str(out)
            cur["error"] = ""
            manager.store.save(cur)
        except Exception as e:
            log.error(f"anteprima di {pid}: {e}")
            cur = manager.store.get(pid)
            if cur:
                cur["error"] = f"anteprima: {e}"
                manager.store.save(cur)
        finally:
            _end_planning(pid)

    threading.Thread(target=_work, name=f"animatic-{pid}", daemon=True).start()
    _ok(self, planning=True)


def handle_production_prune(self):
    """POST /api/creative/productions/prune {id} — toglie tentativi scartati e versioni vecchie non piu' usati."""
    from core.modules.sigma_creative_lab.video.production import prune_production
    data = self.read_json_body()
    try:
        _ok(self, **prune_production(manager.store, data.get("id", "")))
    except ValueError as e:
        _err(self, str(e), 404)
    except RuntimeError as e:
        _err(self, str(e), 409)


def handle_production_delete(self):
    """POST /api/creative/productions/delete {id, exports?} — elimina la produzione e il suo contesto.

    Cartella, uscite e ingressi temporanei di ComfyUI, job dell'editor; i video esportati
    restano a meno di exports=true.
    """
    from core.modules.sigma_creative_lab.video.production import purge_production
    data = self.read_json_body()
    active = manager.active()
    if active and active["production"] == data.get("id"):
        return _err(self, "render in corso", 409)
    try:
        _ok(self, **purge_production(manager.store, data.get("id", ""), bool(data.get("exports"))))
    except ValueError as e:
        _err(self, str(e))
    except RuntimeError as e:
        _err(self, str(e), 409)


def handle_manga_review(self):
    """GET /api/creative/productions/manga/review?id=... — vignette da rivedere: chi c'e' e chi parla."""
    from core.modules.sigma_creative_lab.video import manga
    try:
        prod = manager.store.get(_qs(self).get("id", ""))
        if not prod:
            return _err(self, "produzione inesistente", 404)
        cartella = manga.cartella_di(prod)
        vignette = manga.elenco_revisione(cartella, (prod.get("manga") or {}).get("exclude"))
        for v in vignette:
            v["ritaglio_url"] = _url(v.pop("ritaglio"))
        nomi = [c["name"] for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name")]
        _ok(self, panels=vignette, characters=nomi)
    except (ValueError, OSError) as e:
        _err(self, str(e))


def handle_manga_review_save(self):
    """POST /api/creative/productions/manga/review — {id, panel_id, presenti, voci: {i: {chi, fuori_campo}}}"""
    from core.modules.sigma_creative_lab.video import manga
    data = self.read_json_body()
    try:
        prod = manager.store.get(data.get("id", ""))
        if not prod:
            return _err(self, "produzione inesistente", 404)
        cartella = manga.cartella_di(prod)
        nomi = [c["name"] for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name")]
        validi = set(nomi) | {"narrator"}
        voci = data.get("voci") or {}
        sbagliati = [v.get("chi") for v in voci.values() if v.get("chi") and v.get("chi") not in validi]
        if sbagliati:
            return _err(self, f"personaggi non in bibbia: {sbagliati}")
        manga.correggi_vignetta(cartella, str(data.get("panel_id", "")), data.get("presenti"), voci)
        narratore = str((prod.get("manga") or {}).get("narrator") or (nomi[0] if nomi else ""))
        comparsa = next((n for n in nomi if "compars" in n.lower() or "extra" in n.lower()), "Comparsa")
        cambiate = manga.applica_allo_storyboard(prod, cartella, str(data.get("panel_id", "")), narratore, comparsa)
        manager.store.save(prod)
        _ok(self, changed_shots=cambiate)
    except (ValueError, OSError) as e:
        _err(self, str(e))


GET_ROUTES = {
    "/api/creative/productions": handle_productions_list,
    "/api/creative/genres": handle_genres,
    "/api/creative/productions/get": handle_production_get,
    "/api/creative/productions/events": handle_production_events,
    "/api/creative/productions/manga/review": handle_manga_review,
}

POST_ROUTES = {
    "/api/creative/productions/create": handle_production_create,
    "/api/creative/productions/update": handle_production_update,
    "/api/creative/productions/preproduction": handle_production_preproduction,
    "/api/creative/productions/storyboard": handle_production_storyboard,
    "/api/creative/productions/planning/cancel": handle_production_planning_cancel,
    "/api/creative/productions/scene": handle_production_scene,
    "/api/creative/productions/style_image": handle_production_style_image,
    "/api/creative/productions/shot_fix": handle_production_shot_fix,
    "/api/creative/productions/render": handle_production_render,
    "/api/creative/productions/portraits": handle_production_portraits,
    "/api/creative/productions/keyframes": handle_production_keyframes,
    "/api/creative/productions/cancel": handle_production_cancel,
    "/api/creative/productions/assemble": handle_production_assemble,
    "/api/creative/productions/animatic": handle_production_animatic,
    "/api/creative/productions/delete": handle_production_delete,
    "/api/creative/productions/prune": handle_production_prune,
    "/api/creative/productions/manga/review": handle_manga_review_save,
}
