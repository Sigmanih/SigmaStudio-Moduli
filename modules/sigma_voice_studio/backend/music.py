"""Composizione musicale durevole di AudioStudio, con motore Creative facoltativo."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
import time

from core import paths
from core.job_store import JobStore
from core.job_worker import JobCancelled, PersistentJobWorker
from core.store import JsonStore

PRESETS = (
    {'id': 'lofi_study', 'name': 'Lo-Fi Study Beats', 'bpm': 72, 'key': 'C major',
     'description': 'Pianoforte morbido, basso caldo, batteria discreta e texture analogiche.',
     'tags': 'lo-fi hip hop, mellow study beats, warm felt piano, soft Rhodes chords, rounded warm bass, '
             'gentle brushed boom bap drums, subtle tape warmth, quiet vinyl texture, intimate cozy mood, '
             'steady relaxed groove, sparse melody, gentle harmonic movement, soft transients, no dramatic builds',
     'visual': 'anime_study', 'scene': 'Una persona adulta studia alla scrivania, luce calda e pioggia alla finestra.'},
    {'id': 'deep_focus', 'name': 'Deep Focus Ambient', 'bpm': 60, 'key': 'D minor',
     'description': 'Pad lunghi e synth atmosferici, senza percussioni invadenti.',
     'tags': 'deep focus ambient, warm sustained synthesizer pads, slow spacious evolving harmonies, '
             'subtle airy textures, gentle low drone, floating calm atmosphere, no drums, no percussion, '
             'no sudden transitions, no dramatic builds, understated background for concentrated work',
     'visual': 'forest', 'scene': 'Foresta tranquilla, piccoli animali e luce soffusa tra gli alberi.'},
    {'id': 'neoclassical', 'name': 'Neoclassical Piano', 'bpm': 64, 'key': 'F major',
     'description': 'Pianoforte minimalista, archi leggeri e armonie delicate.',
     'tags': 'minimalist neoclassical piano, soft felt piano, delicate slow arpeggios, warm subtle chamber strings, '
             'gentle consonant harmonies, intimate evening reading atmosphere, restrained dynamics, '
             'sparse notes with breathing space, no percussion, no virtuoso flourishes, no dramatic crescendo',
     'visual': 'anime_reading', 'scene': 'Lettura serale in una biblioteca anime, movimenti minimi e luce morbida.'},
    {'id': 'cyber_ambient', 'name': 'Cyber Ambient / Coding Music', 'bpm': 76, 'key': 'A minor',
     'description': 'Elettronica minimale e sequenze sintetiche lente per il coding.',
     'tags': 'minimal cyber ambient, gentle slow analog synthesizer sequences, soft restrained electronic pulse, '
             'warm deep bass, spacious futuristic pads, quiet nocturnal coding atmosphere, subtle digital textures, '
             'unobtrusive rhythm, gradual timbral evolution, no aggressive lead, no drops, no abrupt changes',
     'visual': 'space', 'scene': 'Spazio procedurale: stelle, nebulose e un movimento lento e ciclico.'},
)
BY_ID = {preset['id']: preset for preset in PRESETS}


def normalize(data):
    if not isinstance(data, dict) or data.get('genre', 'lofi_study') not in BY_ID:
        raise ValueError('Scegli uno dei generi musicali disponibili')
    preset = BY_ID[data.get('genre', 'lofi_study')]
    duration = data.get('duration', 120)
    if type(duration) is not int or duration not in (120, 300, 900, 1800):
        raise ValueError('Scegli una durata di 2, 5, 15 o 30 minuti')
    seed = data.get('seed')
    seed = secrets.randbelow(2**31) if seed is None else seed
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Il seed deve essere un intero fra 0 e 2147483647')
    bpm = data.get('bpm', preset['bpm'])
    if type(bpm) is not int or not 40 <= bpm <= 140:
        raise ValueError('Il tempo deve essere fra 40 e 140 BPM')
    prompt = data.get('prompt', '')
    if not isinstance(prompt, str) or len(prompt) > 1200:
        raise ValueError('La descrizione musicale deve avere al massimo 1200 caratteri')
    return {'genre': preset['id'], 'duration': duration, 'seed': seed, 'bpm': bpm, 'prompt': prompt.strip()}


def backend():
    try:
        from core.modules.sigma_creative_lab.creative_router import model_router
        from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
    except ImportError as exc:
        raise RuntimeError('Installa Creative Lab per usare il motore musicale locale') from exc
    config = model_router.get_config().get('backends', {}).get('comfyui', {})
    if config.get('enabled') is False:
        raise RuntimeError('Abilita ComfyUI nei motori di Creative Lab')
    return ComfyUIBackend(base_url=config.get('url') or 'http://127.0.0.1:8188', config={'timeout': 15})


async def check_engine(engine=None):
    from core.modules.sigma_creative_lab.video.soundtrack import build_ace_step
    engine = engine or backend()
    report = await engine.validate_workflow(build_ace_step(BY_ID['lofi_study']['tags'], 78, 42))
    if not report['ok']:
        raise RuntimeError('Motore musicale non pronto: ' + '; '.join(report['problems'][:3]))
    return engine


def status():
    try:
        asyncio.run(asyncio.wait_for(check_engine(), timeout=12))
        return {'ready': True, 'engine': 'ACE-Step 1.5 turbo', 'message': 'Motore locale pronto'}
    except (ImportError, RuntimeError, OSError, ValueError, TimeoutError) as exc:
        return {'ready': False, 'engine': 'ACE-Step 1.5 turbo', 'message': str(exc) or 'ComfyUI non risponde: ricontrolla il motore'}


class CheckedBackend:
    """Annulla solo il prompt del lavoro corrente, mai tutta la coda ComfyUI."""
    def __init__(self, engine, job):
        self.engine, self.job = engine, job

    def check(self):
        if self.job['cancel_event'].is_set():
            raise JobCancelled('Composizione annullata')

    async def run(self, payload, timeout_s=1800):
        self.check()
        prompt = await self.engine.submit(payload)
        deadline = time.monotonic() + timeout_s
        try:
            while time.monotonic() < deadline:
                self.check()
                state = await asyncio.wait_for(self.engine.get_job_status(prompt), timeout=15)
                if state.status == 'error':
                    raise RuntimeError(state.error or 'Generazione musicale fallita')
                if state.status == 'done':
                    outputs = await self.engine.get_outputs(prompt)
                    if not outputs:
                        raise RuntimeError('Il motore non ha prodotto audio')
                    return outputs[0]
                await asyncio.sleep(1)
            raise TimeoutError('Il motore musicale non ha completato il brano entro 30 minuti')
        except (Exception, asyncio.CancelledError):
            await self.engine.cancel_job(prompt)
            raise


async def compose(service, job):
    from core.modules.sigma_creative_lab.video.soundtrack import generate_soundtrack
    from core.modules.sigma_creative_lab.video.score_quality import inspect_audio
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
    recipe = normalize(job['args'])
    preset = BY_ID[recipe['genre']]
    engine = await asyncio.wait_for(check_engine(), timeout=12)
    queue = await engine.get_queue()
    if queue['running_count'] or queue['pending_count']:
        raise RuntimeError('ComfyUI è occupato: attendi la fine del lavoro corrente e riprendi questa composizione')
    directory = paths.works_area('audio_studio') / recipe['genre'] / (job.get('operation_id') or job['id'])
    directory.mkdir(parents=True, exist_ok=True)
    job.update(message='Composizione musicale locale', progress=.05)
    # Identità stabile: lo stesso preset e seed riproducono la stessa ricetta anche dopo un riavvio.
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]
    tags = preset['tags'] + ', instrumental only, no vocals, no singing, no spoken words'
    if recipe['prompt']:
        tags += ', ' + recipe['prompt']
    prod = {'id': 'audio_' + identity, 'settings': {'seed': recipe['seed']},
            'soundtrack': {'tags': tags, 'bpm': recipe['bpm'], 'keyscale': preset['key'], 'instrumental': True,
                          'development': 'subtle natural variation, consistent restrained dynamics, seamless calm flow'},
            'shots': [{'id': 'composition', 'status': 'done', 'frames': recipe['duration'] * 24,
                       'scene': 'continuous calm instrumental study session'}]}
    checked = CheckedBackend(engine, job)
    def progress(message):
        checked.check()
        job.update(message=message, progress=min(.8, float(job.get('progress', .05)) + .05))
    music = await generate_soundtrack(prod, directory / 'segments', checked, progress)
    checked.check()
    target = directory / (recipe['genre'] + '.wav')
    mp3 = target.with_suffix('.mp3')
    job.update(message='Finitura e verifica del brano', progress=.85)
    # Le dissolvenze ammorbidiscono gli estremi; il master WAV conserva una copia senza perdita.
    await asyncio.to_thread(_run, [ffmpeg_bin(), '-v', 'error', '-y', '-i', str(music), '-t', str(recipe['duration']),
        '-af', f"afade=t=in:d=2,afade=t=out:st={recipe['duration'] - 3}:d=3,alimiter=limit=0.8913:level=false",
        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', str(target)], 300)
    report = await asyncio.to_thread(inspect_audio, target, recipe['duration'])
    if not report['ok']:
        raise RuntimeError('La base non supera la verifica audio: ' + ', '.join(report['issues']))
    await asyncio.to_thread(_run, [ffmpeg_bin(), '-v', 'error', '-y', '-i', str(target), '-c:a', 'libmp3lame',
                                  '-b:a', '256k', str(mp3)], 300)
    checked.check()
    result = {'title': preset['name'], 'genre': recipe['genre'], 'duration': recipe['duration'],
              'wav': str(target), 'mp3': str(mp3), 'wav_url': paths.public_url(target), 'mp3_url': paths.public_url(mp3),
              'quality': report, 'recipe': recipe, 'visual_theme': preset['visual'], 'scene': preset['scene']}
    JsonStore(directory / 'composition.json').save(result)
    job.update(message='Anteprima pronta' if recipe['duration'] == 120 else 'Base musicale pronta', progress=1)
    return result


class MusicService:
    def __init__(self, state_path=None):
        self.worker = PersistentJobWorker(JobStore(state_path or paths.var_dir() / 'audio_studio' / 'music.sqlite3'),
                                          {'compose': compose}, self, blocked=self.blocked, reserve=self.reserve,
                                          id_prefix='music')

    @staticmethod
    def blocked(job):
        try:
            from core.modules.sigma_creative_lab.backends.resources import accelerator_busy
        except ImportError:
            return 'Installa Creative Lab per riprendere la composizione'
        return 'In attesa: la GPU sta eseguendo un altro lavoro di Sigma Studio' if accelerator_busy() else ''

    @staticmethod
    def reserve(job):
        from core.modules.sigma_creative_lab.backends.resources import reserve_accelerator
        return reserve_accelerator(job['id'])

    def submit(self, data):
        args = normalize(data)
        engine_status = status()
        if not engine_status['ready']:
            raise ValueError(engine_status['message'])
        return self.worker.submit('audio_studio', 'compose', args)

    def list(self):
        return self.worker.list()

    def cancel(self, job_id):
        return self.worker.cancel(job_id)

    def resume(self, job_id):
        return self.worker.retry(job_id, {'compose'})

    def close(self, timeout=2):
        return self.worker.close(timeout)


_service = None
_lock = threading.Lock()


def music_service():
    global _service
    with _lock:
        if _service is None:
            _service = MusicService()
        return _service
