"""Rotte della libreria dei personaggi (/api/creative/characters/*)."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

from core.logger import get_logger
from core.modules.sigma_creative_lab.video import character_library as lib

log = get_logger("creative_character_routes")


def _qs(handler) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(handler.path).query).items()}


def _ok(handler, **data):
    handler.send_json_response({"success": True, **data})


def _err(handler, msg: str, status: int = 400):
    handler.send_json_response({"success": False, "error": msg}, status)


def _decorate(char: dict) -> dict:
    """URL delle immagini per il frontend (i file stanno in data/, serviti come /data/...)."""
    from core.modules.sigma_creative_lab.video.production_routes import _url

    def url(name: str) -> str:
        path = lib.file_path(char, name)
        return _url(str(path)) if path else ""
    out = dict(char)
    out["front_url"] = url(char.get("front", ""))
    out["candidates"] = [{**c, "url": url(c["file"])} for c in char.get("candidates") or []]
    out["sheet"] = {v: {**e, "url": url(e["file"]), "label": lib.VIEW_LABELS.get(v, v)}
                    for v, e in (char.get("sheet") or {}).items()}
    out["has_voice"] = lib.voice_sample(char) is not None
    return out


def _run(handler, fn, *args, status_on_error: int = 500, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        return result
    except ValueError as e:
        _err(handler, str(e))
    except RuntimeError as e:
        _err(handler, str(e), 409)
    except Exception as e:
        log.error(f"libreria personaggi: {e}")
        _err(handler, str(e), status_on_error)
    return None


def handle_characters_list(self):
    """GET /api/creative/characters — tutti i personaggi, con le viste e i generi disponibili."""
    from core.modules.sigma_creative_lab.video import genres
    _ok(self, characters=[_decorate(c) for c in lib.list_characters()],
        views=[{"id": v, "label": lib.VIEW_LABELS[v]} for v in lib.VIEWS],
        genres=[{"id": k, "label": g["label"]} for k, g in genres.GENRES.items() if k not in ("lesson", "presentation")])


def handle_character_create(self):
    """POST /api/creative/characters/create {name, description?, genre?, voice_id?}"""
    d = self.read_json_body()
    char = _run(self, lib.create, d.get("name", ""), d.get("description", ""), d.get("genre", "realistic"),
                d.get("voice_id", ""))
    if char:
        _ok(self, character=_decorate(char))


def handle_character_update(self):
    """POST /api/creative/characters/update {id, name?, description?, genre?, voice_id?, notes?}"""
    d = self.read_json_body()
    fields = {k: d.get(k) for k in ("name", "description", "genre", "voice_id", "notes")}
    char = _run(self, lib.update, d.get("id", ""), **fields)
    if char:
        _ok(self, character=_decorate(char))


def handle_character_delete(self):
    """POST /api/creative/characters/delete {id}"""
    d = self.read_json_body()
    done = _run(self, lib.delete, d.get("id", ""))
    if done is not None:
        _ok(self, deleted=bool(done))


def handle_character_candidates(self):
    """POST /api/creative/characters/candidates {id, count?} — proposte del riferimento (~10 s l'una)."""
    d = self.read_json_body()
    char = _run(self, lib.candidates, d.get("id", ""), int(d.get("count") or 4))
    if char:
        _ok(self, character=_decorate(char))


def handle_character_pick(self):
    """POST /api/creative/characters/pick {id, file}"""
    d = self.read_json_body()
    char = _run(self, lib.pick, d.get("id", ""), d.get("file", ""))
    if char:
        _ok(self, character=_decorate(char))


def handle_character_sheet(self):
    """POST /api/creative/characters/sheet {id, views?, check?} — model sheet controllato dal giudice."""
    d = self.read_json_body()
    char = _run(self, lib.sheet, d.get("id", ""), d.get("views"), check=d.get("check", True) is not False)
    if char:
        _ok(self, character=_decorate(char))


def handle_character_image(self):
    """POST /api/creative/characters/image?id=&filename=  (corpo: byte dell'immagine) — foto o disegno come riferimento."""
    q = _qs(self)
    data = getattr(self, "_body_bytes", b"") or b""
    char = _run(self, lib.import_image, q.get("id", ""), data, q.get("filename", ""))
    if char:
        _ok(self, character=_decorate(char))


def handle_character_to_production(self):
    """POST /api/creative/characters/to_production {id, production}"""
    d = self.read_json_body()
    entry = _run(self, lib.to_production, d.get("id", ""), d.get("production", ""))
    if entry:
        _ok(self, character=entry)


def handle_character_from_production(self):
    """POST /api/creative/characters/from_production {production, name, character?}"""
    d = self.read_json_body()
    character = d.get("character") if isinstance(d.get("character"), dict) else None
    char = _run(self, lib.from_production, d.get("production", ""), d.get("name", ""), character)
    if char:
        _ok(self, character=_decorate(char))


GET_ROUTES = {
    "/api/creative/characters": handle_characters_list,
}

POST_ROUTES = {
    "/api/creative/characters/create": handle_character_create,
    "/api/creative/characters/update": handle_character_update,
    "/api/creative/characters/delete": handle_character_delete,
    "/api/creative/characters/candidates": handle_character_candidates,
    "/api/creative/characters/pick": handle_character_pick,
    "/api/creative/characters/sheet": handle_character_sheet,
    "/api/creative/characters/image": handle_character_image,
    "/api/creative/characters/to_production": handle_character_to_production,
    "/api/creative/characters/from_production": handle_character_from_production,
}
