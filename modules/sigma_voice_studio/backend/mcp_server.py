# ==============================================================================
# sigma_voice_studio/backend/mcp_server.py — Voice & TTS MCP Server
# ==============================================================================
import base64
from core.mcp.base_server import BaseMCPServer
from core.mcp.governance import SAFE
from core.logger import get_logger
from .tts import list_engines, synthesize, resolve_default

log = get_logger(__name__)


class VoiceMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__(
            name="Voice MCP",
            version="1.0.0",
            description="Sintesi vocale neurale, gestione voci e clonazione vocale"
        )
        self._init_tools()

    def _init_tools(self):
        self.register_tool(
            name="synthesize_speech",
            description="Synthesize input text into WAV audio using Kokoro or XTTS neural engine.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to synthesize"},
                    "engine": {"type": "string", "description": "TTS engine (kokoro, xtts)"},
                    "voice": {"type": "string", "description": "Voice ID/Name (e.g. if_sara, af_heart)"},
                    "speed": {"type": "number", "description": "Speech speed factor (0.5 to 2.0)", "default": 1.0}
                },
                "required": ["text"]
            },
            handler=self._handle_synthesize_speech,
            safety=SAFE,
            category="voice"
        )

        self.register_tool(
            name="list_neural_voices",
            description="List all available neural voice engines and voices.",
            input_schema={"type": "object", "properties": {}},
            handler=self._handle_list_voices,
            safety=SAFE,
            category="voice"
        )

    def _handle_synthesize_speech(self, args: dict) -> dict:
        text = args.get("text", "")
        engine_id = args.get("engine")
        voice = args.get("voice")
        speed = float(args.get("speed", 1.0))

        if not engine_id or not voice:
            default_choice = resolve_default()
            engine_id = engine_id or default_choice["engine"]
            voice = voice or default_choice["voice"]

        try:
            wav_bytes = synthesize(text=text, engine_id=engine_id, voice=voice, speed=speed)
            b64_audio = base64.b64encode(wav_bytes).decode("ascii")
            return {
                "success": True,
                "engine": engine_id,
                "voice": voice,
                "audio_base64": b64_audio,
                "format": "audio/wav",
                "bytes_length": len(wav_bytes)
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _handle_list_voices(self, args: dict) -> dict:
        return {"success": True, "engines": list_engines()}
