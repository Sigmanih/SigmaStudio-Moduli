# ==============================================================================
# core/tts/__init__.py — Voice Synthesis Sub-package
# ==============================================================================
"""Neural text-to-speech engines (Kokoro, XTTS v2) behind a common registry."""

from core.modules.sigma_voice_studio.tts.base import TTSEngine, pcm_to_wav
from core.modules.sigma_voice_studio.tts.registry import (
    get_engine, list_engines, prewarm, resolve_default, synthesize,
)

__all__ = [
    "TTSEngine",
    "pcm_to_wav",
    "get_engine",
    "list_engines",
    "prewarm",
    "resolve_default",
    "synthesize",
]
