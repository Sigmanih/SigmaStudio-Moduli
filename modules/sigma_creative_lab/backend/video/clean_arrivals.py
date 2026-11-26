"""Guide fotografiche pulite, separate dalla ricorsione dei fotogrammi video."""
import json
import asyncio
import math
from pathlib import Path

from core.logger import get_logger
from core import paths
from . import image_gen
from .ambient_loop import reference
from .manual_review import fingerprint
from .production import _atomic_write_json, _run, ffmpeg_bin

log = get_logger('creative_clean_arrivals')


async def generate(plans: list[dict], width: int, height: int, gpu: int,
                   progress=None, cancel=None) -> int:
    count = 0
    for index, shot in enumerate(plans):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Preparazione degli arrivi interrotta dopo '+str(count)+' immagini')
        camera = shot.get('arrival_camera') or {}
        prompt = str(shot.get('end_frame_prompt') or '').strip()
        if (not prompt and not camera) or not shot.get('end_reference'):
            raise ValueError('Mancano descrizione fotografica o percorso di arrivo per '+shot['id'])
        out = Path(shot['end_reference']).resolve()
        if not out.is_relative_to(paths.works_dir().resolve()):
            raise ValueError('Le guide generate devono restare in works/')
        # Anche la ricorsione fra immagini sintetiche amplifica gli errori del VAE: solo sorgenti fisse.
        refs = ([str(reference(camera['source']))] if camera else
                list(dict.fromkeys(str(reference(v)) for v in shot.get('arrival_refs', []))))
        if not refs or len(refs) > image_gen.MAX_REFS:
            raise ValueError('Servono da uno a quattro riferimenti originali per la guida '+shot['id'])
        if any(Path(r).resolve() in {Path(p['end_reference']).resolve() for p in plans} for r in refs):
            raise ValueError('Una guida non può dipendere da un altro arrivo generato')
        spec = {'version': 1, 'model': 'klein', 'prompt': prompt, 'width': width, 'height': height,
                'seed': int(shot.get('arrival_seed') or shot.get('seed') or 1000),
                'refs': [{'path': r, 'sha256': fingerprint(r)} for r in refs]}
        if camera:
            zoom, pan_x, pan_y = [float(camera.get(key, default)) for key, default in
                                  (('zoom', 1), ('pan_x', .5), ('pan_y', .5))]
            if (not all(math.isfinite(v) for v in (zoom, pan_x, pan_y))
                    or not 1 <= zoom <= 4 or not 0 <= pan_x <= 1 or not 0 <= pan_y <= 1):
                raise ValueError('Percorso camera non valido per '+shot['id'])
            spec.update(model='camera_path', camera={'zoom': zoom, 'pan_x': pan_x, 'pan_y': pan_y})
        sidecar = out.with_suffix('.source.json')
        cached = False
        if out.is_file() and sidecar.is_file():
            try:
                old = json.loads(sidecar.read_text(encoding='utf-8'))
                cached = old.get('source') == spec and old.get('sha256') == fingerprint(out)
                if cached:
                    reference(str(out))
            except (OSError, ValueError):
                cached = False
        if not cached:
            log.info('Arrivo pulito %s/%s: %s', index+1, len(plans), shot['id'])
            if camera:
                sw, sh = math.ceil(width*zoom/2)*2, math.ceil(height*zoom/2)*2
                x, y = round((sw-width)*pan_x), round((sh-height)*pan_y)
                out.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(_run, [ffmpeg_bin(), '-v', 'error', '-y', '-i', refs[0], '-vf',
                    f'scale={sw}:{sh}:flags=lanczos,crop={width}:{height}:{x}:{y}',
                    '-frames:v', '1', '-update', '1', str(out)], 60)
            else:
                await image_gen.generate('klein', prompt, out, width=width, height=height,
                                         seed=spec['seed'], gpu=gpu, refs=refs)
            reference(str(out))
            _atomic_write_json(sidecar, {'source': spec, 'sha256': fingerprint(out)}, indent=2)
        count += 1
        if progress:
            progress(index+1, len(plans), out, cached)
    return count
