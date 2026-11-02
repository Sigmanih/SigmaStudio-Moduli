"""Riconoscimento dei pesi e ricette automatiche, senza deserializzare tensori."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from core.logger import get_logger

log = get_logger('creative_model_setup')
TASK_TAGS = {
    'text_to_image': 'Immagini', 'img_to_img': 'Ritocco', 'inpaint': 'Ritocco',
    'outpaint': 'Ritocco', 'instruct_edit': 'Ritocco', 'upscale': 'Ingrandimento',
    'image_to_3d': '3D', 'multiview_to_3d': '3D', 'texture_3d': 'Materiali',
    'texture_pbr': 'Materiali', 'text_to_video': 'Video', 'image_to_video': 'Video',
    'segment': 'Scontorno', 'remove_background': 'Scontorno',
    'vision_describe': 'Analisi', 'vision_qa': 'Analisi', 'ocr': 'Testi',
}
COMPONENT_TAGS = {'lora': 'Adattatore', 'vae': 'Decoder', 'text_encoder': 'Encoder testo',
                  'clip_vision': 'Encoder visivo', 'controlnet': 'Guida strutturale',
                  'embedding': 'Concetti', 'upscaler': 'Ingrandimento'}


def usage_tags(tasks):
    return sorted({TASK_TAGS[t] for t in tasks if t in TASK_TAGS})


@lru_cache(maxsize=64)
def _header(filename, size, modified):
    # La chiave include i metadati del file: un download completato invalida la cache.
    try:
        with Path(filename).open('rb') as stream:
            prefix = stream.read(8)
            length = int.from_bytes(prefix, 'little')
            if len(prefix) != 8 or not 2 <= length <= min(8 * 1024 * 1024, size - 8):
                return {}
            data = json.loads(stream.read(length))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError) as exc:
        log.debug('Header modello non leggibile: %s: %s', filename, exc)
        return {}


def inspect_weights(path):
    path = Path(path)
    if path.suffix.lower() != '.safetensors':
        return {}
    try:
        stat = path.stat()
        return _header(str(path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return {}


def _shape(header, key):
    tensor = header.get(key)
    return tensor.get('shape', []) if isinstance(tensor, dict) else []


def recognize(header):
    """Riconosce solo firme compatibili con ricette disponibili in Sigma."""
    keys = set(header)
    if 'double_stream_modulation_img.lin.weight' in keys:
        if (_shape(header, 'img_in.weight') == [3072, 128]
                and _shape(header, 'txt_in.weight') == [3072, 7680]):
            return 'flux2-klein-4b'
        return ''
    if 'double_blocks.0.img_attn.qkv.weight' in keys and 'img_in.weight' in keys:
        if (_shape(header, 'img_in.weight') == [3072, 64]
                and _shape(header, 'txt_in.weight') == [3072, 4096]):
            return 'flux-dev' if 'guidance_in.in_layer.weight' in keys else 'flux-schnell'
        return ''
    prefix = 'model.diffusion_model.'
    tensor = header.get(prefix + 'input_blocks.0.0.weight')
    input_shape = tensor.get('shape', []) if isinstance(tensor, dict) else []
    contexts = {v['shape'][1] for k, v in header.items() if k.startswith(prefix)
                and k.endswith('attn2.to_k.weight') and isinstance(v, dict)
                and isinstance(v.get('shape'), list) and len(v['shape']) == 2 and isinstance(v['shape'][1], int)}
    # I checkpoint parziali o di inpainting non vanno instradati come txt2img standard.
    if not isinstance(input_shape, list) or len(input_shape) < 2 or input_shape[1] != 4:
        return ''
    vae = any(k.startswith('first_stage_model.decoder.') for k in keys)
    if vae and 2048 in contexts and any(k.startswith('conditioner.embedders.') for k in keys):
        return 'sdxl'
    if vae and any(k.startswith('cond_stage_model.') for k in keys):
        if contexts == {768}:
            return 'sd1'
        if contexts == {1024}:
            return 'sd2'
    return ''


def scan_models(root):
    """Elenca anche i componenti: nessun file viene scambiato per un generatore."""
    if not root:
        return []
    root = Path(root).resolve()
    from .model_hub import CATEGORIES
    files = []
    for category in CATEGORIES:
        folders = [category.folder]
        if category.id == 'text_encoder':
            folders.append('clip')
        if category.id == 'diffusion':
            folders.append('unet')
        for folder in folders:
            base = root / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob('*')):
                if not path.is_file() or path.suffix.lower() not in ('.safetensors', '.ckpt', '.gguf', '.pth', '.pt', '.bin', '.onnx'):
                    continue
                relative = path.relative_to(base).as_posix()
                identity = hashlib.sha256(f'{folder}/{relative}'.encode()).hexdigest()[:16]
                header = inspect_weights(path) if category.id in ('checkpoint', 'diffusion') else {}
                family = recognize(header)
                entry = {'id': f'local:{identity}', 'label': path.stem, 'filename': relative,
                         'kind': category.id, 'folder': folder, 'family': family,
                         'installed': True, 'tags': [COMPONENT_TAGS.get(category.id, 'Modello')],
                         'tasks': [], 'parameters': {}, 'issues': [], 'workflow': ''}
                if family in ('sdxl', 'sd1', 'sd2') and category.id == 'checkpoint':
                    entry.update(workflow='sdxl_txt2img', tasks=['text_to_image'],
                                 parameters={'ckpt': relative, 'width': 1024 if family == 'sdxl' else 512,
                                             'height': 1024 if family == 'sdxl' else 512,
                                             'steps': 30, 'cfg_scale': 7})
                elif family.startswith('flux') and category.id == 'diffusion':
                    names = {}
                    required = [
                        ('clip_l', ('text_encoders', 'clip'), ('clip_l.safetensors',)),
                        ('clip_t5', ('text_encoders', 'clip'), ('t5xxl_fp8_e4m3fn.safetensors', 't5xxl_fp16.safetensors')),
                        ('vae', ('vae',), ('ae.safetensors',)),
                    ]
                    if family == 'flux2-klein-4b':
                        required = [('text_encoder', ('text_encoders', 'clip'), ('qwen_3_4b.safetensors', 'qwen_3_4b_fp8_mixed.safetensors')),
                                    ('vae', ('vae',), ('flux2-vae.safetensors',))]
                    for component, directories, choices in required:
                        found = next((name for name in choices if any((root / d / name).is_file() for d in directories)), '')
                        if found:
                            names[component] = found
                        else:
                            entry['issues'].append(f'Manca {component}: {" oppure ".join(choices)}')
                    entry.update(workflow='flux2_txt2img' if family == 'flux2-klein-4b' else 'flux_txt2img', tasks=['text_to_image'], parameters={
                        **names, 'ckpt': relative, 'steps': 4 if family == 'flux-schnell' else 28,
                        'cfg_scale': 0 if family == 'flux-schnell' else 3.5, 'scheduler': 'simple',
                        'weight_dtype': 'default'})
                    if family == 'flux2-klein-4b':
                        distilled = path.name in ('flux-2-klein-4b.safetensors', 'flux-2-klein-4b-fp8.safetensors')
                        entry['parameters'].update(steps=4 if distilled else 20, cfg_scale=1 if distilled else 5)
                if entry['workflow']:
                    entry['tags'] = [*usage_tags(entry['tasks']), family.upper(), path.suffix[1:].upper()]
                elif category.id in ('checkpoint', 'diffusion'):
                    entry['issues'] = ['Architettura o formato da associare a un workflow compatibile']
                    entry['tags'] = ['Workflow richiesto', path.suffix[1:].upper()]
                    hints = {'wan': 'Video', 'ltx': 'Video', 'minimax': 'Video', 'ace_step': 'Musica', 'seedvr': 'Ingrandimento', 'z_image': 'Immagini'}
                    entry['tags'] = [value for key, value in hints.items() if key in path.stem.lower()] + entry['tags']
                else:
                    entry['tags'].append('Componente')
                entry['configured'] = bool(entry['workflow']) and not entry['issues']
                files.append(entry)
    return files
