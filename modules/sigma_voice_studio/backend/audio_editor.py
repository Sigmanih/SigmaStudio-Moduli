"""Progetti audio non distruttivi: clip, forme d'onda, mix e passaggio al video."""
from __future__ import annotations
import asyncio
import copy
import hashlib
import math
from pathlib import Path
import re
import shutil
import threading
import uuid

import numpy as np
from core import paths
from core.job_worker import JobCancelled
from core.store import JsonStore

_lock = threading.RLock()


def root():
    return paths.works_area('audio_studio') / 'projects'


def directory(pid):
    if not isinstance(pid, str) or not re.fullmatch(r'audio_[a-f0-9]{16}', pid):
        raise ValueError('Progetto audio non valido')
    return root() / pid


def load(pid):
    value = JsonStore(directory(pid) / 'project.json', default={}).load()
    if not value:
        raise ValueError('Progetto audio non trovato')
    return value


def save(value):
    JsonStore(directory(value['id']) / 'project.json').save(value)


def listing():
    if not root().exists():
        return []
    return [value for path in root().glob('audio_*/project.json') if (value := JsonStore(path, default={}).load())]


def number(value, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError('Valore numerico non valido')
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'Valore fuori intervallo {minimum}–{maximum}')
    return value


def add_clip(project, source, label, start=0):
    start = number(start,0,3600)
    if len(project['clips']) >= 32:
        raise ValueError('Il progetto può contenere al massimo 32 clip')
    from core.modules.sigma_creative_lab.video.production import probe, ffmpeg_bin
    source = Path(source)
    info = probe(source)
    duration = float(info.get('audio_duration') or info.get('duration') or 0)
    if not info.get('has_audio') or not math.isfinite(duration) or duration <= 0 or duration + start > 3600:
        raise ValueError('La sorgente deve contenere audio di durata non superiore a un’ora')
    cid = uuid.uuid4().hex[:12]
    target = directory(project['id']) / 'assets' / (cid + source.suffix.lower())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    # La primitiva testuale non trasporta PCM: la forma d'onda usa un processo binario dedicato.
    import subprocess
    result = subprocess.run([ffmpeg_bin(), '-v', 'error', '-i', str(target), '-ac', '1', '-ar', '2000', '-f', 'f32le', '-'],
                            capture_output=True, timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Impossibile leggere la forma d’onda: ' + result.stderr.decode(errors='replace')[-300:])
    samples = np.abs(np.nan_to_num(np.frombuffer(result.stdout, dtype='<f4')))
    if not samples.size:
        target.unlink(missing_ok=True)
        raise ValueError('La sorgente non contiene campioni audio')
    block = max(1, math.ceil(len(samples) / 800))
    padded = np.pad(samples, (0, (-len(samples)) % block))
    peaks = padded.reshape(-1, block).max(axis=1).round(4).tolist()
    clip = {'id': cid, 'label': str(label)[:100], 'src': str(target), 'url': paths.public_url(target),
            'start': number(start, 0, 3600), 'in': 0, 'out': duration, 'source_duration': duration,
            'gain': 0, 'pan': 0, 'fade_in': 0, 'fade_out': 0, 'mute': False, 'peaks': peaks}
    project['clips'].append(clip)
    return clip


def create(service, source_job, title='', request_id=None):
    if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id)):
        raise ValueError('Identificativo della richiesta non valido')
    previous = service.worker.store.get(source_job) if source_job else None
    if source_job and (not previous or previous['status'] != 'done' or not (previous.get('result') or {}).get('wav')):
        raise ValueError('Scegli una composizione completata')
    result = previous['result'] if previous else {'title': title or 'Nuovo progetto audio', 'recipe': {'bpm':72,'key':'C major'}}
    from .music import BY_ID
    recipe = {**(result.get('recipe') or {})}
    recipe.setdefault('key',(BY_ID.get(recipe.get('genre')) or {}).get('key','C major'))
    with _lock:
        pid='audio_' + (hashlib.sha256((request_id+str(source_job)).encode()).hexdigest()[:16] if request_id else uuid.uuid4().hex[:16])
        if (directory(pid)/'project.json').is_file():
            return load(pid)
        project = {'id': pid, 'title': str(title or result['title'])[:100],
                   'revision': 1, 'clips': [], 'history': [], 'recipe': recipe,
                   'visual_theme': result.get('visual_theme', 'space'), 'export': None}
        if previous:
            add_clip(project, result['wav'], result['title'])
        save(project)
    return project


def edit(pid, revision, operation, args):
    if not isinstance(args, dict):
        raise ValueError('Parametri della modifica non validi')
    with _lock:
        project = load(pid)
        if revision != project['revision']:
            raise ValueError('Il progetto è cambiato: ricaricalo prima di salvare')
        before = copy.deepcopy({'clips':project['clips'],'recipe':project['recipe'],'title':project['title']})
        if operation == 'undo':
            if not project['history']:
                raise ValueError('Nessuna modifica da annullare')
            snapshot = project['history'].pop()
            if isinstance(snapshot,list):
                project['clips'] = snapshot
            else:
                project.update(snapshot)
        elif operation == 'settings':
            project['recipe']['bpm'] = number(args.get('bpm'),40,140)
            key = args.get('key')
            if key not in ('C major','D major','E major','F major','G major','A minor','B minor','C minor','D minor','E minor','F minor','G minor'):
                raise ValueError('Tonalità non supportata')
            project['recipe']['key'] = key
            project['history'] = (project['history']+[before])[-40:]
        else:
            clip = next((c for c in project['clips'] if c['id'] == args.get('clip_id')), None)
            if clip is None:
                raise ValueError('Clip audio non trovata')
            if operation == 'delete':
                project['clips'].remove(clip)
            elif operation == 'duplicate':
                if len(project['clips']) >= 32:
                    raise ValueError('Il progetto può contenere al massimo 32 clip')
                duplicate = {**clip, 'id': uuid.uuid4().hex[:12], 'start': clip['start'] + clip['out'] - clip['in']}
                project['clips'].append(duplicate)
            elif operation == 'split':
                if len(project['clips']) >= 32:
                    raise ValueError('Il progetto può contenere al massimo 32 clip')
                at = number(args.get('at'), clip['start'] + .05, clip['start'] + clip['out'] - clip['in'] - .05)
                boundary = clip['in'] + at - clip['start']
                duplicate = {**clip, 'id': uuid.uuid4().hex[:12], 'in': boundary, 'start': at, 'fade_in': 0}
                clip.update(out=boundary, fade_out=0)
                project['clips'].append(duplicate)
            elif operation == 'update':
                limits = {'start': (0, 3600), 'in': (0, clip['source_duration']), 'out': (0, clip['source_duration']),
                          'gain': (-60, 12), 'pan': (-1, 1), 'fade_in': (0, 30), 'fade_out': (0, 30)}
                for key, bounds in limits.items():
                    if key in args:
                        clip[key] = number(args[key], *bounds)
                if 'mute' in args:
                    if not isinstance(args['mute'], bool):
                        raise ValueError('Muto deve essere un valore booleano')
                    clip['mute'] = args['mute']
                if clip['out'] - clip['in'] < .05:
                    raise ValueError('Il taglio deve conservare almeno 50 millisecondi')
            else:
                raise ValueError('Operazione audio non supportata')
            project['history'] = (project['history'] + [before])[-40:]
        if any(c['start'] + c['out'] - c['in'] > 3600 for c in project['clips']):
            raise ValueError('Le clip non possono superare un’ora nella timeline')
        project['revision'] += 1
        project['export'] = None
        save(project)
        return project


def mix(project):
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    clips = [c for c in project['clips'] if not c['mute']]
    if not clips:
        raise ValueError('Il progetto non contiene clip udibili')
    duration = max(c['start'] + c['out'] - c['in'] for c in clips)
    if duration > 3600:
        raise ValueError('Il mix non può superare un’ora')
    out = directory(project['id']) / 'exports' / f"mix_r{project['revision']}.wav"
    out.parent.mkdir(exist_ok=True)
    command = [ffmpeg_bin(), '-v', 'error', '-y', '-filter_complex_threads', '2']
    graph = []
    for index, clip in enumerate(clips):
        if not Path(clip['src']).is_file():
            raise ValueError('Una sorgente audio non è disponibile: mix interrotto')
        command += ['-i', clip['src']]
        span = clip['out'] - clip['in']
        pan = clip['pan']
        graph.append(f"[{index}:a]atrim=start={clip['in']}:end={clip['out']},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=channel_layouts=stereo,volume={clip['gain']}dB,"
            f"pan=stereo|c0={min(1,1-pan)}*c0|c1={min(1,1+pan)}*c1,"
            f"afade=t=in:d={min(clip['fade_in'],span)},afade=t=out:st={max(0,span-clip['fade_out'])}:d={min(clip['fade_out'],span)},"
            f"adelay={round(clip['start']*1000)}|{round(clip['start']*1000)}[a{index}]")
    graph.append(''.join(f'[a{i}]' for i in range(len(clips))) +
                 f'amix=inputs={len(clips)}:duration=longest:normalize=0,alimiter=limit=0.8913:level=false:latency=true[mix]')
    _run([*command, '-filter_complex', ';'.join(graph), '-map', '[mix]', '-t', str(duration),
          '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', str(out)], 1200)
    if abs(float(probe(out)['duration']) - duration) > .1:
        raise ValueError('Il mix esportato ha una durata inattesa')
    return {'path': str(out), 'url': paths.public_url(out), 'duration': duration, 'revision': project['revision']}


def submit(service, pid, kind, args):
    project = load(pid)
    if kind not in ('mix', 'layer'):
        raise ValueError('Lavoro audio non supportato')
    payload = {'project_id': project['id']}
    if kind == 'layer':
        payload.update(seconds=number(args.get('seconds',30),5,120),start=number(args.get('start',0),0,3480))
        prompt = args.get('prompt')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>1200:
            raise ValueError('Descrivi lo strumento da generare (massimo 1200 caratteri)')
        payload['prompt'] = prompt.strip()
    elif not any(not clip['mute'] for clip in project['clips']):
        raise ValueError('Aggiungi almeno una clip udibile prima di esportare')
    return service.worker.submit(project['id'],kind,payload)


async def export_job(service, job):
    pid = job['args']['project_id']
    project = load(pid)
    result = await asyncio.to_thread(mix, project)
    if job['cancel_event'].is_set():
        raise JobCancelled('Esportazione annullata')
    with _lock:
        current = load(pid)
        if current['revision'] != project['revision']:
            raise ValueError('Progetto modificato durante il mix: esporta nuovamente')
        current['export'] = result
        save(current)
    return {'audio_project': pid, 'mix': result}


async def layer_job(service, job):
    from .music import backend, CheckedBackend
    from core.modules.sigma_creative_lab.video.soundtrack import build_ace_step
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
    from core.modules.sigma_creative_lab.video.score_quality import inspect_audio
    project = load(job['args']['project_id'])
    seconds = number(job['args'].get('seconds', 30), 5, 120)
    start = number(job['args'].get('start', 0), 0, 3480)
    prompt = str(job['args'].get('prompt', '')).strip()
    if not prompt or len(prompt) > 1200:
        raise ValueError('Descrivi lo strumento o il livello da generare')
    engine = backend()
    graph = build_ace_step(prompt + ', instrumental, no vocals, isolated musical layer, no full arrangement', seconds + 8,
                           int(uuid.uuid4().hex[:7],16), int(round(project['recipe'].get('bpm',72))),
                           keyscale=project['recipe'].get('key','C major'), prefix='sigma/audio_layers')
    validation = await engine.validate_workflow(graph)
    if not validation['ok']:
        raise ValueError('; '.join(validation['problems']))
    job.update(message='Generazione della nuova traccia musicale', progress=.15)
    data, _ = await CheckedBackend(engine, job).run({'workflow': graph})
    folder = directory(project['id']) / 'generated'
    folder.mkdir(exist_ok=True)
    raw, output = folder / (job['id'] + '.raw'), folder / (job['id'] + '.wav')
    raw.write_bytes(data)
    await asyncio.to_thread(_run, [ffmpeg_bin(), '-v', 'error', '-y', '-i', str(raw), '-t', str(seconds),
        '-af', 'afade=t=in:d=0.1,afade=t=out:st=' + str(seconds-.3) + ':d=0.3', '-ar', '48000', '-ac', '2', str(output)], 300)
    raw.unlink(missing_ok=True)
    if job['cancel_event'].is_set():
        raise JobCancelled('Generazione traccia annullata')
    from core.modules.sigma_creative_lab.video.production import probe
    if abs(float(probe(output)['audio_duration']) - seconds) > .1:
        raise ValueError('Il motore ha prodotto una traccia più corta del richiesto')
    quality = await asyncio.to_thread(inspect_audio,output,seconds)
    if not quality['ok'] or quality['silent_s'] >= seconds-1:
        raise ValueError('La nuova traccia non supera il controllo di durata, silenzio e ripetizioni')
    def attach():
        # Il lock resta nello stesso thread anche durante la lettura della forma d'onda.
        with _lock:
            current = load(project['id'])
            if current['recipe'] != project['recipe']:
                raise ValueError('I riferimenti musicali sono cambiati durante la generazione: riprova')
            if job['cancel_event'].is_set():
                raise JobCancelled('Generazione traccia annullata')
            current['history'] = (current['history'] + [copy.deepcopy(current['clips'])])[-40:]
            clip = add_clip(current, output, prompt[:70], start)
            current['revision'] += 1
            current['export'] = None
            save(current)
            return clip
    clip = await asyncio.to_thread(attach)
    return {'audio_project': project['id'], 'clip': clip['id'],'quality':quality}


def video_project(pid, prompt, mode='loop'):
    from core.modules.sigma_creative_lab.video.production import manager, new_shot, probe
    project = load(pid)
    export = project.get('export')
    if not export or export['revision'] != project['revision'] or not Path(export['path']).is_file():
        raise ValueError('Esporta il mix aggiornato prima di passare al video')
    prompt = str(prompt).strip()
    if not prompt or len(prompt) > 2000:
        raise ValueError('Descrivi la scena video da abbinare alla musica')
    if mode not in ('loop','sequence'):
        raise ValueError('Modalità video non supportata')
    duration = number(export['duration'],.05,3600)
    if abs(float(probe(Path(export['path']))['audio_duration'])-duration)>.1:
        raise ValueError('La durata del mix è cambiata: esportalo nuovamente')
    count = 1 if mode=='loop' else max(1, math.ceil(duration / 8))
    shots = [new_shot(prompt + '. Static camera, subtle natural movement, no speech, no music.',
                      duration_s=min(8, duration-index*8), scene='Video musicale') for index in range(count)]
    prod = manager.store.create(project['title'] + ' · Video', settings={'video_model':'ltx25','max_clip_seconds':10}, shots=shots,
                                bible={'style':prompt}, soundtrack={'enabled':True,'external_mix':True})
    snapshot=manager.store.path(prod['id'])/'music'/'audio_studio_mix.wav'
    snapshot.parent.mkdir(exist_ok=True);shutil.copy2(export['path'],snapshot)
    prod['soundtrack_path']=str(snapshot)
    prod['audio_project'] = {'id':pid,'revision':project['revision'],'mode':mode,'mix':{**export,'path':str(snapshot)}}
    manager.store.save(prod)
    return {'production_id':prod['id'], 'url':'/?tab=video_studio', 'title':prod['title']}
