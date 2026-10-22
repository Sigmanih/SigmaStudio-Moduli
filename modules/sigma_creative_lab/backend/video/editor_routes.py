"""Rotte dell'editor video: timeline, media per il player, job AI, voci dei personaggi."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import paths
from core.logger import get_logger
from core.modules.sigma_creative_lab.video import media_cache, timeline as T

log = get_logger("creative_editor_routes")


def _qs(handler) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(handler.path).query).items()}


def _ok(handler, **data):
    handler.send_json_response({"success": True, **data})


def _err(handler, msg: str, status: int = 400):
    handler.send_json_response({"success": False, "error": msg}, status)


def _url(path: str) -> str:
    from core.modules.sigma_creative_lab.video.production_routes import _url as to_url
    return to_url(path)


def _store():
    from core.modules.sigma_creative_lab.video.production import manager
    return manager.store, T.TimelineStore(manager.store)


def _payload(pid: str, tl: dict) -> dict:
    prods, ts = _store()
    prod = prods.get(pid)
    lay = T.layout(tl, prod)
    for it in lay["items"]:
        it["clip_url"] = _url(it["clip_path"])
    audio = []
    for track in tl["audio"]:
        audio.append({**track, "clips": [{**c, "url": _url(c["src"])} for c in track["clips"]]})
    shots = {s["id"]: {"id": s["id"], "prompt": s.get("prompt", ""), "scene": s.get("scene", ""),
                       "origin": s.get("origin", "storyboard"), "take": s.get("take"),
                       "takes": [{"id": t["id"], "kind": t.get("kind"), "prompt": t.get("prompt", ""),
                                  "created": t.get("created"), "url": _url(t.get("clip_path", "")),
                                  "heard": t.get("heard"), "match": t.get("match"), "judge": t.get("judge")}
                                 for t in T.ensure_takes(s)]}
             for s in prod["shots"] if s.get("takes") or s.get("clip_path")}
    characters = [{"name": c.get("name"), "has_image": bool(c.get("ref_image")),
                   "voice_url": _url(c.get("voice_sample", "")), "voice_engine": c.get("voice_engine", "kokoro"),
                   "voice": c.get("voice", ""), "voice_description": c.get("voice_description", ""),
                   "voice_seed": c.get("voice_seed", 7)} for c in (prod.get("bible") or {}).get("characters") or []]
    return {"timeline": {**tl, "audio": audio}, "items": lay["items"], "duration": lay["duration"],
            "shots": shots, "characters": characters, "history": ts.history_depth(pid),
            "video_model": (prod.get("settings") or {}).get("video_model", "h3"),
            "output_url": _url(prod.get("output_path", ""))}


def handle_editor_timeline(self):
    """GET /api/creative/editor/timeline?id=..."""
    pid = _qs(self).get("id", "")
    try:
        _prods, ts = _store()
        _ok(self, **_payload(pid, ts.get(pid)))
    except (T.TimelineError, ValueError) as e:
        _err(self, str(e), 404)


def handle_editor_media(self):
    """GET /api/creative/editor/media?id=&item=  oppure &clip= — copie per scrubbing, miniature, forma d'onda."""
    q = _qs(self)
    try:
        prods, ts = _store()
        prod = prods.get(q.get("id", ""))
        tl = ts.get(q.get("id", ""))
        if q.get("item"):
            item = next((it for it in T.layout(tl, prod)["items"] if it["id"] == q["item"]), None)
            if not item:
                return _err(self, "elemento inesistente", 404)
            clip = Path(item["clip_path"])
            thumbs = media_cache.thumbnails(clip)
            _ok(self, scrub_url=_url(str(media_cache.scrub_copy(clip))),
                thumbs={**thumbs, "url": _url(thumbs["path"])}, peaks=media_cache.peaks(clip))
        elif q.get("clip"):
            _track, _i, clip = T._find_audio_clip(tl, q["clip"])
            _ok(self, peaks=media_cache.peaks(Path(clip["src"])))
        else:
            _err(self, "serve item o clip")
    except Exception as e:
        log.error(f"media dell'editor: {e}")
        _err(self, str(e), 500)


def handle_editor_op(self):
    """POST /api/creative/editor/op {id, op, args}"""
    data = self.read_json_body()
    try:
        _prods, ts = _store()
        tl, result = ts.apply(data.get("id", ""), data.get("op", ""), data.get("args") or {})
        _ok(self, result=result, **_payload(data["id"], tl))
    except (T.TimelineError, ValueError, TypeError) as e:
        _err(self, str(e))


def handle_editor_undo(self):
    """POST /api/creative/editor/undo {id, redo}"""
    data = self.read_json_body()
    try:
        _prods, ts = _store()
        tl = ts.undo(data.get("id", ""), redo=bool(data.get("redo")))
        _ok(self, **_payload(data["id"], tl))
    except (T.TimelineError, ValueError) as e:
        _err(self, str(e))


def handle_editor_rebuild(self):
    """POST /api/creative/editor/rebuild {id} — riparte dallo storyboard (annullabile)."""
    data = self.read_json_body()
    try:
        _prods, ts = _store()
        _ok(self, **_payload(data["id"], ts.rebuild(data.get("id", ""))))
    except (T.TimelineError, ValueError) as e:
        _err(self, str(e))


def handle_editor_job(self):
    """POST /api/creative/editor/job {id, kind, args}"""
    from core.modules.sigma_creative_lab.video.editor_jobs import editor_jobs
    data = self.read_json_body()
    try:
        _ok(self, job=editor_jobs().submit(data.get("id", ""), data.get("kind", ""), data.get("args") or {}))
    except ValueError as e:
        _err(self, str(e))


def handle_editor_jobs(self):
    """GET /api/creative/editor/jobs?id=..."""
    from core.modules.sigma_creative_lab.video.editor_jobs import editor_jobs
    _ok(self, jobs=editor_jobs().list(_qs(self).get("id") or None))


def handle_editor_job_cancel(self):
    """POST /api/creative/editor/job/cancel {job_id}"""
    from core.modules.sigma_creative_lab.video.editor_jobs import editor_jobs
    _ok(self, cancelled=editor_jobs().cancel(self.read_json_body().get("job_id", "")))


def handle_editor_voice(self):
    """POST /api/creative/editor/voice {id, character, engine, voice, sample_path?, text?, description?, seed?}

    Imposta la voce di un personaggio: un campione caricato (clonazione) oppure
    una voce TTS da cui si ricava il campione. Il campione si rigenera subito,
    cosi' la UI lo fa ascoltare.
    """
    from core.modules.sigma_creative_lab.video.editor_jobs import _ensure_voice_sample, editor_jobs
    data = self.read_json_body()
    prods, _ts = _store()
    try:
        prod = prods.get(data.get("id", ""))
        ch = next((c for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name") == data.get("character")), None)
        if ch is None:
            return _err(self, "personaggio inesistente", 404)
        if data.get("sample_path"):
            sample = Path(data["sample_path"]).resolve()
            # Solo file dello spazio di lavoro: il percorso arriva dal client.
            if not sample.is_file() or not paths.is_user_path(sample):
                return _err(self, "campione inesistente")
            ch["voice_sample"] = data["sample_path"]
        elif data.get("description"):
            # Voce creata da una descrizione (Qwen3-TTS VoiceDesign); il seed la rende ripetibile.
            ch.update(voice_engine="qwen_design", voice_description=str(data["description"]).strip(),
                      voice_seed=int(data.get("seed") or 7))
            ch.pop("voice_sample", None)
            if data.get("text"):
                ch["voice_sample_text"] = data["text"]
        else:
            ch.update(voice_engine=data.get("engine") or "kokoro", voice=data.get("voice") or "im_nicola")
            ch.pop("voice_sample", None)
            ch.pop("voice_description", None)
            if data.get("text"):
                ch["voice_sample_text"] = data["text"]
        prods.save(prod)
        sample = _ensure_voice_sample(editor_jobs(), prod, ch)
        _ok(self, voice_url=_url(str(sample)))
    except Exception as e:
        log.error(f"voce del personaggio: {e}")
        _err(self, str(e), 500)


def handle_editor_import_chunk(self):
    """POST /api/creative/editor/import_chunk?id=&upload=&offset=  (corpo: byte grezzi del pezzo)"""
    from core.modules.sigma_creative_lab.video import media_import as mi
    q = _qs(self)
    prods, _ts = _store()
    try:
        prod = prods.get(q.get("id", ""))
        if prod is None:
            return _err(self, "produzione inesistente", 404)
        size = mi.append_chunk(prods.path(prod["id"]) / "imports" / ".uploads", q.get("upload", ""),
                               int(q.get("offset") or 0), getattr(self, "_body_bytes", b"") or b"")
        _ok(self, size=size)
    except ValueError as e:
        _err(self, str(e), 409)


def handle_editor_import(self):
    """POST /api/creative/editor/import {id, upload, filename, t?, track?, seconds?, motion?}

    Chiude il caricamento e mette in coda la conversione: video e immagini entrano
    nella traccia video al cursore, l'audio nella traccia scelta.
    """
    from core.modules.sigma_creative_lab.video import media_import as mi
    from core.modules.sigma_creative_lab.video.editor_jobs import editor_jobs
    data = self.read_json_body()
    prods, _ts = _store()
    try:
        prod = prods.get(data.get("id", ""))
        if prod is None:
            return _err(self, "produzione inesistente", 404)
        mi.kind_of(Path(str(data.get("filename", ""))))           # formato rifiutato prima di spostare il file
        imports = prods.path(prod["id"]) / "imports"
        path = mi.finish_upload(imports / ".uploads", str(data.get("upload", "")), str(data.get("filename", "")), imports)
        args = {k: data[k] for k in ("t", "track", "seconds", "motion", "label") if data.get(k) is not None}
        _ok(self, job=editor_jobs().submit(prod["id"], "import", {**args, "path": str(path)}))
    except ValueError as e:
        _err(self, str(e))


def handle_editor_voices(self):
    """GET /api/creative/editor/voices — motori e voci disponibili."""
    from core.modules.sigma_creative_lab.voice.runtime import qwen_runtime, voice_runtime
    engines = [{"id": "kokoro", "label": "Kokoro 82M (Apache 2.0, voci predefinite)",
                "voices": [{"id": "if_sara", "label": "Sara (donna)"}, {"id": "im_nicola", "label": "Nicola (uomo)"}]},
               {"id": "chatterbox", "label": "Chatterbox Multilingual (MIT, clonazione da campione, emozioni)",
                "voices": []}]
    if qwen_runtime.installed():
        engines += [{"id": "qwen_design", "label": "Qwen3-TTS VoiceDesign (Apache 2.0, voce da descrizione)",
                     "voices": []},
                    {"id": "qwen_clone", "label": "Qwen3-TTS (Apache 2.0, clonazione da campione)", "voices": []}]
    _ok(self, installed=voice_runtime.installed(), engines=engines)


def _restoration_view(state: dict) -> dict:
    """Quello che serve all'Inspector: testi e voci, senza l'analisi fotogramma per fotogramma."""
    analysis = state.get("analysis") or {}
    return {"title": state.get("title", ""), "cards": state.get("cards") or [], "voices": state.get("voices") or {},
            "moods": state.get("moods") or [], "titles": len(analysis.get("titles") or []),
            "pages": len(analysis.get("pages") or [])}


def handle_editor_restoration(self):
    """GET /api/creative/editor/restoration?id=&shot= — testi letti, chi li legge, voci e atmosfere."""
    from core.modules.sigma_creative_lab.video import restoration as R
    q = _qs(self)
    prods, _ts = _store()
    if prods.get(q.get("id", "")) is None:
        return _err(self, "produzione inesistente", 404)
    _ok(self, **_restoration_view(R.load_state(prods.path(q["id"]), q.get("shot", ""))))


def handle_editor_restoration_cards(self):
    """POST /api/creative/editor/restoration/cards {id, shot, edits:[{index, text?, speaker?, delete?}]}"""
    from core.modules.sigma_creative_lab.video import restoration as R
    data = self.read_json_body()
    prods, _ts = _store()
    try:
        if prods.get(data.get("id", "")) is None:
            return _err(self, "produzione inesistente", 404)
        R.update_cards(prods.path(data["id"]), str(data.get("shot", "")), list(data.get("edits") or []))
        _ok(self, **_restoration_view(R.load_state(prods.path(data["id"]), str(data.get("shot", "")))))
    except ValueError as e:
        _err(self, str(e))


GET_ROUTES = {
    "/api/creative/editor/restoration": handle_editor_restoration,
    "/api/creative/editor/timeline": handle_editor_timeline,
    "/api/creative/editor/media": handle_editor_media,
    "/api/creative/editor/jobs": handle_editor_jobs,
    "/api/creative/editor/voices": handle_editor_voices,
}

POST_ROUTES = {
    "/api/creative/editor/op": handle_editor_op,
    "/api/creative/editor/undo": handle_editor_undo,
    "/api/creative/editor/rebuild": handle_editor_rebuild,
    "/api/creative/editor/job": handle_editor_job,
    "/api/creative/editor/job/cancel": handle_editor_job_cancel,
    "/api/creative/editor/voice": handle_editor_voice,
    "/api/creative/editor/import_chunk": handle_editor_import_chunk,
    "/api/creative/editor/import": handle_editor_import,
    "/api/creative/editor/restoration/cards": handle_editor_restoration_cards,
}
