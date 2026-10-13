"""Route della libreria voci: elenco, creazione (descrizione, campione, predefinita), ascolto, rinomina, eliminazione."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger("voice_library_routes")


def _ok(handler, **data):
    handler.send_json_response({"success": True, **data})


def _err(handler, msg: str, status: int = 400):
    handler.send_json_response({"success": False, "error": msg}, status)


def _url(path: str) -> str:
    """URL del campione: le voci stanno in works/voci (prima data/voices)."""
    from core import paths
    return paths.public_url(path)


def _public(v: dict) -> dict:
    return {**{k: v[k] for k in v if k != "sample"}, "sample_url": _url(v["sample"]), "sample_path": v["sample"]}


def handle_voice_library(self):
    """GET /api/voices/library"""
    from . import library
    try:
        available = True
        try:
            voice, qwen = library._runtimes()
            from core.modules.sigma_creative_lab.voice.runtime import voxcpm_runtime
            engines = {"clone": voice.installed(), "preset": voice.installed(), "design": qwen.installed(),
                       "qwen": qwen.installed(), "voxcpm": voxcpm_runtime.installed()}
        except RuntimeError as e:
            available, engines = False, {"clone": False, "preset": False, "design": False, "reason": str(e)}
        _ok(self, voices=[_public(v) for v in library.list_voices()], engines=engines, available=available,
            types=list(library.VOICE_TYPES))
    except Exception as e:
        log.error(f"libreria voci: {e}")
        _err(self, str(e), 500)


def handle_voice_library_create(self):
    """POST /api/voices/library/create {name, mode: design|type|clone|preset, engine?, type?, description?, seed?, data?,
    filename?, preset?}"""
    from . import library
    data = self.read_json_body()
    name = str(data.get("name") or "").strip() or "Nuova voce"
    mode = data.get("mode")
    try:
        if mode == "design":
            v = library.create_from_description(name, str(data.get("description", "")), int(data.get("seed") or 7),
                                                engine=str(data.get("engine") or "qwen"))
        elif mode == "type":
            v = library.create_from_type(name, str(data.get("type") or ""), str(data.get("engine") or "qwen"),
                                         str(data.get("description") or ""), int(data.get("seed") or 7))
        elif mode == "clone":
            raw = str(data.get("data", ""))
            if raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            v = library.create_from_sample(name, base64.b64decode(raw, validate=True), str(data.get("filename", "")))
        elif mode == "preset":
            v = library.create_from_preset(name, str(data.get("preset") or "if_sara"),
                                           float(data.get("semitones") or 0.0), float(data.get("speed") or 1.0))
        else:
            return _err(self, "modo sconosciuto: design, type, clone o preset")
        _ok(self, voice=_public(v))
    except (ValueError, RuntimeError) as e:
        _err(self, str(e))
    except Exception as e:
        log.error(f"creazione voce: {e}")
        _err(self, str(e), 500)


def handle_voice_library_speak(self):
    """POST /api/voices/library/speak {id, text, engine?} — prova la voce su una frase."""
    from . import library
    data = self.read_json_body()
    text = str(data.get("text") or "").strip()[:600]
    if not text:
        return _err(self, "testo vuoto")
    try:
        with tempfile.TemporaryDirectory(prefix="sigma_voice_") as tmp:
            out = Path(tmp) / "prova.wav"
            library.speak(str(data.get("id", "")), text, out, engine=str(data.get("engine") or ""))
            audio = base64.b64encode(out.read_bytes()).decode("ascii")
        _ok(self, audio=audio, format="wav")
    except (ValueError, RuntimeError) as e:
        _err(self, str(e))
    except Exception as e:
        log.error(f"prova voce: {e}")
        _err(self, str(e), 500)


def handle_voice_library_update(self):
    """POST /api/voices/library/update {id, name?, delete?, semitones?, speed?}"""
    from . import library
    data = self.read_json_body()
    try:
        if data.get("delete"):
            return _ok(self, deleted=library.delete(str(data.get("id", ""))))
        if data.get("semitones") is not None or data.get("speed") is not None:
            v = library.get(str(data.get("id", ""))) or {}
            return _ok(self, voice=_public(library.update_tone(
                str(data.get("id", "")), float(data.get("semitones", v.get("semitones") or 0.0)),
                float(data.get("speed", v.get("speed") or 1.0)))))
        _ok(self, voice=_public(library.rename(str(data.get("id", "")), str(data.get("name", "")))))
    except ValueError as e:
        _err(self, str(e))
