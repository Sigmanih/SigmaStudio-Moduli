import asyncio
from unittest.mock import AsyncMock

from core.modules.sigma_creative_lab.backends.comfy_launcher import ComfyInstances
from core.modules.sigma_creative_lab import creative_router as router


def test_profilo_prudente_riconosciuto_senza_riavvio():
    flags = ["--disable-comfy-compiler", "--vram-headroom", "2"]
    assert ComfyInstances._flags_of({"system": {"argv": ["main.py", "--port", "8288", *flags]}}) == ComfyInstances._normalize(flags)


def test_modifica_senza_maschera_conserva_sorgente(monkeypatch):
    class Result:
        def to_dict(self):
            return {"id": "nuova-versione"}

    class Handler:
        def __init__(self):
            self.responses = []
        def read_json_body(self):
            return {"task_type": "img_to_img", "asset_id": "originale", "params": {"prompt": "luce serale", "strength": 0.45}}
        def send_json_response(self, payload, *args):
            self.responses.append(payload)

    edit = AsyncMock(return_value=Result())
    monkeypatch.setattr(router.image_generator, "image_to_image", edit)
    monkeypatch.setattr(router, "_send_creative_sse", lambda *args: None)
    handler = Handler()
    router.handle_creative_edit(handler)
    edit.assert_awaited_once_with("originale", "luce serale", strength=0.45)
    assert handler.responses[-1]["asset"]["id"] == "nuova-versione"
