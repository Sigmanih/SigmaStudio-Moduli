# ==============================================================================
# core/tts/kokoro_engine.py — Kokoro 82M Neural TTS
# ==============================================================================
"""Kokoro is a small (82M parameter) Apache-2.0 TTS model.

It is the recommended default: the weights are ~330 MB, it runs comfortably on
CPU, and — unlike XTTS v2 — its licence puts no restriction on commercial use,
which matters for a dual-licensed project.
"""

import importlib.util
import tempfile
from pathlib import Path

from core.modules.sigma_voice_studio.tts.base import TTSEngine

# lang_code 'i' selects the Italian frontend inside Kokoro's phonemiser.
KOKORO_LANG = "i"
KOKORO_REPO = "hexgrad/Kokoro-82M"

VOICES = [
    {"id": "if_sara", "name": "Sara", "lang": "it-IT", "gender": "female"},
    {"id": "im_nicola", "name": "Nicola", "lang": "it-IT", "gender": "male"},
]


class KokoroEngine(TTSEngine):
    id = "kokoro"
    name = "Kokoro 82M"
    description = "Voce neurale leggera, gira su CPU. Voci italiane Sara e Nicola."
    license = "Apache-2.0 (uso commerciale consentito)"
    install_hint = "pip install kokoro soundfile misaki[it]"
    sample_rate = 24000
    default_voice = "if_sara"

    def is_installed(self) -> bool:
        return self._local() or self._worker() is not None

    @staticmethod
    def _local() -> bool:
        return importlib.util.find_spec("kokoro") is not None

    @staticmethod
    def _worker():
        """Kokoro gira anche nel venv delle voci del Creative Lab: senza questo Voice Studio rispondeva 503
        su una macchina dove la voce c'era, solo in un altro ambiente Python."""
        from core.modules.sigma_voice_studio import library
        try:
            voice, _qwen = library._runtimes()
        except RuntimeError:
            return None
        return voice if voice.installed() else None

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0) -> bytes:
        worker = None if self._local() else self._worker()
        if worker is None:
            return super().synthesize(text, voice, speed)
        if not text or not text.strip():
            return b""
        if voice not in {v["id"] for v in VOICES}:
            voice = self.default_voice
        with tempfile.TemporaryDirectory(prefix="sigma_tts_") as tmp:
            out = Path(tmp) / "line.wav"
            worker.synthesize(text, out, engine="kokoro", voice=voice, speed=speed)
            data = out.read_bytes()
        self._model = True                              # per lo stato "caricato" mostrato in Voice Studio
        return data

    def list_voices(self) -> list[dict]:
        return list(VOICES)

    def _load(self):
        from kokoro import KPipeline
        return KPipeline(lang_code=KOKORO_LANG, repo_id=KOKORO_REPO)

    def _synthesize(self, text: str, voice: str, speed: float):
        known = {v["id"] for v in VOICES}
        if voice not in known:
            voice = self.default_voice

        samples = []
        for _graphemes, _phonemes, audio in self._model(text, voice=voice, speed=speed):
            if audio is None:
                continue
            # torch tensor / numpy array / plain sequence, depending on version
            samples.extend(audio.tolist() if hasattr(audio, "tolist") else list(audio))
        return samples
