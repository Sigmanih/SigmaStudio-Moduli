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
            version="1.5.0",
            description="AudioStudio: musica strumentale, sintesi vocale, gestione e clonazione delle voci"
        )
        self._init_tools()

    def _init_tools(self):
        self.register_tool(name='audio_projects', description='Elenca i progetti audio oppure legge clip, riferimenti musicali e revisione di un progetto.',
            input_schema={'type':'object','properties':{'id':{'type':'string'}}},
            handler=self._handle_audio_projects,safety=SAFE,category='music')
        self.register_tool(name='create_audio_project', description='Crea un progetto audio multitraccia vuoto o da una composizione completata, conservando la sorgente.',
            input_schema={'type':'object','properties':{'source_job':{'type':'string'},'title':{'type':'string','maxLength':100}}},
            handler=self._handle_audio_create,safety=SAFE,category='music')
        self.register_tool(name='edit_audio_project', description='Modifica clip senza sovrascrivere le sorgenti. Leggi prima audio_projects per la revisione. Operazioni: update (start,in,out,gain dB,pan,fade_in,fade_out,mute), split (at in secondi), duplicate, delete, settings (bpm,key), undo.',
            input_schema={'type':'object','properties':{'id':{'type':'string'},'revision':{'type':'integer'},
                'operation':{'type':'string','enum':['update','split','duplicate','delete','settings','undo']},
                'args':{'type':'object','properties':{'clip_id':{'type':'string'},'start':{'type':'number'},
                    'in':{'type':'number'},'out':{'type':'number'},'gain':{'type':'number'},'pan':{'type':'number'},
                    'fade_in':{'type':'number'},'fade_out':{'type':'number'},'mute':{'type':'boolean'},
                    'at':{'type':'number'},'bpm':{'type':'number'},'key':{'type':'string'}}}},'required':['id','revision','operation']},
            handler=self._handle_audio_edit,safety=SAFE,category='music')
        self.register_tool(name='render_audio_project', description='Accoda il mix WAV oppure genera una nuova traccia dal prompt (layer). Il layer usa BPM e tonalità del progetto; non separa gli strumenti già registrati. Segui music_jobs.',
            input_schema={'type':'object','properties':{'id':{'type':'string'},'kind':{'type':'string','enum':['mix','layer']},
                'prompt':{'type':'string','maxLength':1200},'seconds':{'type':'number','minimum':5,'maximum':120},
                'start':{'type':'number','minimum':0,'maximum':3480}},'required':['id','kind']},
            handler=self._handle_audio_render,safety=SAFE,category='music')
        self.register_tool(name='audio_to_video', description='Prepara una bozza VideoStudio dalla scena descritta e dal mix esportato aggiornato. Conserva una copia del mix approvato. Non avvia il render GPU.',
            input_schema={'type':'object','properties':{'id':{'type':'string'},'prompt':{'type':'string','maxLength':2000},'mode':{'type':'string','enum':['loop','sequence','varied']},'activity':{'type':'string','enum':['study','workout']},'style':{'type':'string','enum':['anime','realistic','illustration','cartoon3d']}},'required':['id','prompt']},
            handler=self._handle_audio_video,safety=SAFE,category='music')
        self.register_tool(name='revise_study_music',
            description='Rivede una composizione: feedback ricompone il brano; treatment modifica la registrazione in una nuova copia senza cambiare melodia.',
            input_schema={'type': 'object', 'properties': {'source_job': {'type': 'string'},
                'feedback': {'type': 'string', 'maxLength': 800},
                'treatment': {'type': 'string', 'enum': ['soft', 'warm', 'slower']}}, 'required': ['source_job']},
            handler=self._handle_generate_music, safety=SAFE, category='music')
        self.register_tool(
            name='list_music_presets', description='Elenca generi musicali e disponibilità del motore locale di AudioStudio.',
            input_schema={'type': 'object', 'properties': {}}, handler=self._handle_music_presets,
            safety=SAFE, category='music')
        self.register_tool(
            name='generate_study_music', description='Accoda una base strumentale locale; restituisce il job da seguire con music_jobs. Due minuti sono una anteprima. Non pubblica online.',
            input_schema={'type': 'object', 'properties': {
                'genre': {'type': 'string', 'enum': ['lofi_study', 'deep_focus', 'neoclassical', 'cyber_ambient', 'gym_energy']},
                'duration': {'type': 'integer', 'enum': [120, 300, 900, 1800], 'default': 120},
                'prompt': {'type': 'string', 'maxLength': 1200},
                'seed': {'type': 'integer', 'minimum': 0, 'maximum': 2147483647},
                'bpm': {'type': 'integer', 'minimum': 40, 'maximum': 140}}, 'required': ['genre']},
            handler=self._handle_generate_music, safety=SAFE, category='music')
        self.register_tool(
            name='music_jobs', description='Legge lo stato delle composizioni e i percorsi WAV/MP3 prodotti da AudioStudio.',
            input_schema={'type': 'object', 'properties': {}}, handler=self._handle_music_jobs,
            safety=SAFE, category='music')
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

    def _handle_music_presets(self, args):
        from .music import PRESETS, status
        return {'success': True, 'presets': list(PRESETS), **status()}

    def _handle_generate_music(self, args):
        from .music import music_service
        try:
            return {'success': True, 'job': music_service().submit(args)}
        except (ValueError, RuntimeError) as exc:
            return {'success': False, 'error': str(exc)}

    def _handle_music_jobs(self, args):
        from .music import music_service
        return {'success': True, 'jobs': music_service().list()}

    def _audio_call(self, operation):
        try:
            return {'success':True,**operation()}
        except (ValueError,TypeError,KeyError,OSError,RuntimeError,ImportError) as exc:
            return {'success':False,'error':str(exc)}

    def _handle_audio_projects(self,args):
        from . import audio_editor as editor
        from .audio_editor_routes import view
        return self._audio_call(lambda: {'project':view(editor.load(args['id']))} if args.get('id') else
            {'projects':[{k:p[k] for k in ('id','title','revision')} for p in editor.listing()]})

    def _handle_audio_create(self,args):
        from . import audio_editor as editor
        from .audio_editor_routes import view
        from .music import music_service
        return self._audio_call(lambda:{'project':view(editor.create(music_service(),args.get('source_job'),args.get('title')))})

    def _handle_audio_edit(self,args):
        from . import audio_editor as editor
        from .audio_editor_routes import view
        return self._audio_call(lambda:{'project':view(editor.edit(args.get('id'),args.get('revision'),args.get('operation'),args.get('args') or {}))})

    def _handle_audio_render(self,args):
        from . import audio_editor as editor
        from .music import music_service
        return self._audio_call(lambda:{'job':editor.submit(music_service(),args.get('id'),args.get('kind'),args)})

    def _handle_audio_video(self,args):
        from . import audio_editor as editor
        return self._audio_call(lambda:{'video':editor.video_project(args.get('id'),args.get('prompt',''),args.get('mode','loop'),args.get('style','anime'),args.get('activity'))})
