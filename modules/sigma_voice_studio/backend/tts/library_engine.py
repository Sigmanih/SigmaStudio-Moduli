"""Le voci della libreria personale come motore della chat.

La chat legge ogni frase con il motore e la voce scelti in Voice Studio: con
questo motore puo' parlare con una voce creata da descrizione o clonata da un
campione, la stessa usata dai personaggi dei video. La sintesi e' Chatterbox
(clonazione dal campione), nel venv delle voci del Creative Lab.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.modules.sigma_voice_studio.tts.base import TTSEngine


class LibraryEngine(TTSEngine):
    id = "sigma_voices"
    name = "Le mie voci"
    description = "Voci create da descrizione o clonate da un campione (Chatterbox, Qwen3-TTS)."
    license = "MIT / Apache-2.0 (motori); il campione clonato deve essere tuo o autorizzato"
    install_hint = "Video Studio → Motori → Voci, poi crea una voce nella libreria di Voice Studio"
    sample_rate = 24000

    def is_installed(self) -> bool:
        from core.modules.sigma_voice_studio import library
        try:
            voice, _qwen = library._runtimes()
        except RuntimeError:
            return False
        return voice.installed() and bool(library.list_voices())

    def list_voices(self) -> list[dict]:
        from core.modules.sigma_voice_studio import library
        return [{"id": v["id"], "name": v["name"], "lang": "multi", "gender": "", "kind": v.get("kind", "")}
                for v in library.list_voices()]

    @property
    def default_voice(self) -> str:                    # type: ignore[override]
        voices = self.list_voices()
        return voices[0]["id"] if voices else ""

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0) -> bytes:
        """Il worker scrive un WAV completo: si restituisce cosi' com'e', niente ricampionamenti."""
        from core.modules.sigma_voice_studio import library
        if not text or not text.strip():
            return b""
        voice = voice or self.default_voice
        if not voice:
            raise RuntimeError("la libreria delle voci e' vuota: crea una voce in Voice Studio")
        with tempfile.TemporaryDirectory(prefix="sigma_tts_") as tmp:
            out = Path(tmp) / "line.wav"
            # Le frasi della chat sono brevi: un'esagerazione bassa suona piu' naturale nel parlato quotidiano.
            library.speak(voice, text, out, engine="chatterbox", exaggeration=0.4, cfg_weight=0.5)
            data = out.read_bytes()
        self._model = True                              # per lo stato "caricato" mostrato in Voice Studio
        return data
