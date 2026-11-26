"""Una sola immagine e una sola base temporale, ripetuta senza inferenza video."""
import json
import os
import subprocess
import tempfile
import time

from .ambient_loop import reference


def plan(prod):
    from .production import new_shot
    settings = prod['settings']
    anchor = str(reference(settings.get('scene_reference', '')))
    return [new_shot(prod.get('treatment') or 'Scena statica',
                     duration_s=float(settings['loop_base_seconds']), keyframe=anchor,
                     refs=[c['name'] for c in prod['bible'].get('characters') or []],
                     scene='Immagine statica ripetuta')]


def render(store, prod, cancel):
    from .production import ffmpeg_bin, _run
    shots = plan(prod)
    settings = prod['settings']
    duration = float(settings['loop_duration_s'])
    base_seconds = float(settings['loop_base_seconds'])
    fps = int(settings.get('fps') or 24)
    folder = store.path(prod['id'])
    base = folder / 'assembly' / 'static_base.mp4'
    output = folder / 'exports' / 'static_loop.mp4'
    base.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    prod.update(status='rendering', error='', shots=shots, output_path='', quality_status='review_required')
    store.save(prod)
    commands = [
        [ffmpeg_bin(), '-y', '-loop', '1', '-i', shots[0]['keyframe'],
         '-t', str(base_seconds), '-r', str(fps), '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
         '-c:v', 'libx264', '-tune', 'stillimage', '-bf', '0', '-pix_fmt', 'yuv420p', '-an', str(base)],
        [ffmpeg_bin(), '-y', '-stream_loop', '-1', '-i', str(base), '-t', str(duration),
         '-c', 'copy', '-movflags', '+faststart', str(output)],
    ]
    for command in commands:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            deadline = time.monotonic() + 600
            try:
                while process.poll() is None:
                    if cancel.wait(.1) or time.monotonic() > deadline:
                        process.kill()
                        process.wait(timeout=10)
                        prod.update(status='cancelled' if cancel.is_set() else 'failed', error='Esportazione interrotta')
                        store.save(prod)
                        return prod
                if process.returncode:
                    errors.seek(0)
                    raise RuntimeError(errors.read().decode('utf-8', errors='replace')[-2000:])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
    result = _run([ffmpeg_bin('ffprobe'), '-v', 'error', '-show_entries', 'format=duration',
                   '-of', 'json', str(output)], timeout=30)
    actual = float(json.loads(result.stdout)['format']['duration'])
    if abs(actual - duration) > max(.1, 2 / fps):
        raise ValueError(f'Durata esportata {actual}s diversa da {duration}s')
    shots[0].update(status='done', clip_path=str(base))
    prod.update(status='rendered', output_path=str(output), stats={'duration_s': actual})
    store.save(prod)
    return prod
