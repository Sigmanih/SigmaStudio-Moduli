"""Vincoli della ripresa unica: dipendenze esplicite e sorgenti dei raccordi verificabili."""
from pathlib import Path
import re
import math

from .manual_review import fingerprint


def enabled(prod: dict) -> bool:
    return bool(prod.get('settings', {}).get('continuous_journey'))


def ready(prod: dict, shot: dict) -> bool:
    if shot.get('status') == 'done':
        return True
    if not enabled(prod) or shot.get('status') != 'review_required':
        return False
    if not Path(shot.get('clip_path') or '').is_file():
        return False
    from .visual_integrity import valid
    # La generazione può avanzare dopo i controlli automatici; il montaggio attende la revisione esplicita.
    boundary = shot.get('continuity_check') or {}
    coherent = (not shot.get('continuation_source') or
                (boundary.get('status') == 'pass' and boundary.get('clip_sha256') == fingerprint(shot['clip_path'])))
    if shot.get('continuation_source'):
        index = next((i for i, item in enumerate(prod.get('shots', [])) if item['id'] == shot['id']), 0)
        try:
            coherent = coherent and index > 0 and shot['continuation_source'] == binding(prod['shots'][index-1])
        except (OSError, ValueError):
            coherent = False
    verdict = shot.get('judge') or {}
    return (bool(verdict.get('ok')) and not verdict.get('error') and not shot.get('qa_issues')
            and valid(shot) and coherent and quality_valid(shot))


def arrival(shot: dict) -> dict:
    from .ambient_loop import reference
    if not shot.get('end_reference'):
        raise ValueError('Ripresa continua: serve un riferimento finale pulito per la clip '+shot['id'])
    source = reference(shot['end_reference'])
    return {'path': str(source), 'sha256': fingerprint(source)}


def quality_valid(shot: dict) -> bool:
    check = shot.get('journey_quality') or {}
    try:
        return (check.get('status') == 'pass' and check.get('version') in (3, 4)
                and bool((check.get('motion') or {}).get('ok'))
                and shot.get('temporal_guide_sources', []) == temporal_guides(shot, int(shot.get('frames') or 0))
                and check.get('clip_sha256') == fingerprint(shot['clip_path'])
                and check.get('arrival') == arrival(shot))
    except (OSError, KeyError, ValueError):
        return False


def temporal_guides(shot: dict, frames: int) -> list[dict]:
    from .ambient_loop import reference
    guides = shot.get('temporal_guides') or []
    if not isinstance(guides, list) or len(guides) > 15:
        raise ValueError('Servono al massimo 15 guide temporali')
    result, indices = [], set()
    for guide in guides:
        if not isinstance(guide, dict):
            raise ValueError('Guida temporale non valida')
        idx = guide.get('frame_idx')
        if type(idx) is not int or not 0 < idx < frames - 1 or idx in indices:
            raise ValueError('Indice della guida temporale duplicato o fuori dalla clip')
        indices.add(idx)
        strength = float(guide.get('strength', 1.0))
        if not math.isfinite(strength) or not 0 < strength <= 1:
            raise ValueError('Forza della guida temporale non valida')
        path = reference(guide.get('image') or '')
        result.append({'image': str(path), 'frame_idx': idx, 'strength': strength, 'sha256': fingerprint(path)})
    return sorted(result, key=lambda item: item['frame_idx'])


def binding(previous: dict) -> dict:
    clip, frame = Path(previous.get('clip_path') or ''), Path(previous.get('last_frame') or '')
    if not clip.is_file() or not frame.is_file():
        raise ValueError('Ripresa continua: mancano la clip o il fotogramma finale precedenti')
    return {'shot_id': previous['id'], 'clip_sha256': fingerprint(clip), 'frame_sha256': fingerprint(frame)}


def validate_plan(prod: dict) -> None:
    if not enabled(prod):
        return
    if prod.get('settings', {}).get('video_model') != 'ltx25':
        raise ValueError('La ripresa continua vincolata richiede LTX-2.5')
    if any(s.get('transition') != 'continue' for s in prod.get('shots', [])[1:]):
        raise ValueError('Ripresa continua: tutte le clip successive devono proseguire dalla precedente')
    if any(s.get('status') == 'skipped' for s in prod.get('shots', [])):
        raise ValueError('Ripresa continua: una clip saltata spezzerebbe il viaggio')
    for shot in prod.get('shots', []):
        if shot.get('status') != 'done':
            arrival(shot)


def require(prod: dict) -> None:
    if not enabled(prod):
        return
    validate_plan(prod)
    shots = prod.get('shots') or []
    if not shots or any(s.get('status') != 'done' for s in shots):
        raise ValueError('Ripresa continua: completa e revisiona tutte le clip prima del montaggio')
    if shots[0].get('arrival_source') and not quality_valid(shots[0]):
        raise ValueError('Controllo della deriva assente o scaduto per la prima clip')
    for index, shot in enumerate(shots[1:], 1):
        if not shot.get('continued') or shot.get('continuation_source') != binding(shots[index - 1]):
            raise ValueError('Raccordo non valido o sorgente cambiata per la clip ' + shot['id'])
        check = shot.get('continuity_check') or {}
        if check.get('status') != 'pass' or check.get('clip_sha256') != fingerprint(shot['clip_path']):
            raise ValueError('Manca il controllo del raccordo per la clip ' + shot['id'])
        if shot.get('arrival_source') and not quality_valid(shot):
            raise ValueError('Controllo della deriva assente o scaduto per la clip '+shot['id'])


QUALITY_PROMPT = '''Image 1 is a CLEAN planned destination frame. The following images are temporal samples
of a video traveling toward that destination. Inspect the VIDEO samples for cumulative generative degradation:
large flat polygonal patches, stained-glass patterns, colored outlines along the frame borders, warped picture
planes, rectangular overlays, ringing, ghost contours and smeared or duplicated objects/stars.
Compare the rendering quality to image 1, allowing the camera viewpoint and object positions to evolve.
A natural bright comet or star flare alone is not a defect. A scene without people is valid, and very slow
motion is intentional. Smooth dark photographic vignetting and black space are allowed. Never describe a
smooth black/dark falloff as a colored outline: require an actual tinted geometric edge, patch or distortion.
Do not demand a visible spacecraft, observer, body, text or interface.
Any visible digital/geometric degradation MUST mean fail, even when the subject remains recognizable.
Answer these concrete questions, using actual boolean values:
polygonal_patches: are unnatural large flat colored patches or stained-glass patterns visible?
warped_frame: is there a tinted geometric frame, warped picture plane or rectangular overlay?
smeared_objects: are there clearly smeared/duplicated objects or conspicuous ghost contours?
uncertain: is the evidence too ambiguous to answer these questions?
Also evaluate the chronological video samples (do NOT count image 1 as a temporal sample):
relative_motion: does the visible scene evolve, even very gently, through apparent enlargement, drift or parallax?
Small changes in the apparent size/position of a comet count as motion even if distant stars stay fixed.
Do not try to distinguish camera translation from subject motion in deep space: judge the apparent motion.
abrupt_motion: is there a clearly jarring jump, teleportation, viewpoint reset or violent camera roll?
observer_visible: is a spacecraft, cockpit, observer body or interface visible in front of the environment?
scene_matches: do the visible environment and objects match the intended environment label provided below?
Return ONLY JSON with all eight booleans, observations (specific factual string), and issues (list).
If none of the image defects is visible, use false for the first four booleans and an empty issues list.
Relative motion can be true without any defect. Extremely gentle motion is intentional.
Do not include a pass/fail label: the application calculates it from the concrete findings.'''


def parse_quality(text: str) -> dict:
    from .clip_judge import _extract_json
    raw = _extract_json(text)
    flags = ('polygonal_patches', 'warped_frame', 'smeared_objects', 'uncertain')
    if (not isinstance(raw, dict) or any(type(raw.get(key)) is not bool for key in flags)
            or not isinstance(raw.get('observations'), str) or not raw['observations'].strip()
            or not isinstance(raw.get('issues'), list)
            or any(not isinstance(issue, str) for issue in raw['issues'])):
        raise ValueError('Il controllo della deriva non contiene osservazioni verificabili')
    status = ('fail' if raw['issues'] or any(raw[key] for key in flags[:3]) else
              'uncertain' if raw['uncertain'] else 'pass')
    return {**raw, 'status': status}


def motion_verdict(result: dict) -> dict:
    flags = ('relative_motion', 'abrupt_motion', 'observer_visible', 'scene_matches')
    if any(type(result.get(key)) is not bool for key in flags):
        raise ValueError('Il controllo del viaggio non contiene osservazioni sul movimento')
    issues = list(result.get('issues') or [])
    if not result['relative_motion']:
        issues.append('Movimento relativo non verificabile nei campioni temporali')
    if result['abrupt_motion']:
        issues.append('Salto o cambio brusco del punto di vista')
    if result['observer_visible']:
        issues.append('Osservatore, veicolo o interfaccia visibile nel quadro')
    if not result['scene_matches']:
        issues.append('Ambiente o oggetti incoerenti con la tappa prevista')
    ok = result['status'] == 'pass' and not issues
    return {'ok': ok, 'score': .9 if ok else .2, 'seen': result['observations'], 'issues': issues,
            'severe': bool(result['abrupt_motion'] or result['observer_visible']), 'prompt_fix': '',
            'policy': 'continuous_journey_relative_motion_v1'}


def inspect_quality(shot: dict, device: str = 'cpu', evidence_dir: Path | None = None) -> dict:
    import tempfile
    import time
    from .clip_judge import judge, installed, sample_frames
    from .production import extract_last_frame
    target = arrival(shot)
    if target != shot.get('arrival_source'):
        raise ValueError('Il riferimento finale è cambiato durante il render')
    last = extract_last_frame(Path(shot['clip_path']))
    if last is None:
        raise ValueError('Fotogramma finale non leggibile')
    source = {'id': 'clean_arrival', 'clip_path': shot['clip_path'], 'last_frame': target['path']}
    frame = {'clip_path': str(last), 'continuation_source': binding(source)}
    full = inspect(source, frame)
    # La scala ridotta confronta geometria e illuminazione senza confondere la ricostruzione delle texture
    # con una deriva della scena. I campioni a piena risoluzione controllano separatamente gli artefatti.
    comparison = inspect(source, frame, min_ssim=.90, comparison_width=256)
    record = {'version': 4, 'clip_sha256': fingerprint(shot['clip_path']), 'arrival': target,
              'endpoint_ssim': comparison['ssim'], 'endpoint_full_ssim': full['ssim'],
              'comparison_width': 256, 'threshold': comparison['threshold']}
    if comparison['status'] != 'pass':
        return {**record, 'status': 'fail', 'issues': ['Il fotogramma finale devia dal riferimento pulito']}
    if not installed():
        raise RuntimeError('Il controllo della deriva richiede il modello visivo')
    with tempfile.TemporaryDirectory(prefix='sigma_journey_') as tmp:
        frames, _ = sample_frames(Path(shot['clip_path']), Path(tmp), n=3, width=1280)
        content = [judge._image_part(Path(target['path']), max_side=1024)]
        content.extend(judge._image_part(frame, max_side=1024) for frame in frames)
        with judge._lock:
            judge._ensure(device)
            label = str(shot.get('scene') or 'first-person celestial environment')[:160]
            result = parse_quality(judge._chat(content + [{
                'type': 'text', 'text': QUALITY_PROMPT+'\nIntended environment label: '+label}], 600))
            judge._last_use = time.monotonic()
        evidence = []
        if evidence_dir:
            import shutil
            folder = Path(evidence_dir) / record['clip_sha256'][:16]
            folder.mkdir(parents=True, exist_ok=True)
            for frame in frames:
                target_frame = folder / frame.name
                shutil.copy2(frame, target_frame)
                evidence.append(str(target_frame))
    return {**record, **result, 'motion': motion_verdict(result), 'evidence': evidence}


def inspect(previous: dict, shot: dict, min_ssim: float = .92, comparison_width: int = 0,
            frame_index: int = 0) -> dict:
    """Confronta il fotogramma realmente generato con quello usato per il raccordo."""
    from .production import _run, ffmpeg_bin, probe
    source = binding(previous)
    if source != shot.get('continuation_source'):
        raise ValueError('La sorgente della continuazione è cambiata durante la generazione')
    clip = Path(shot['clip_path'])
    info = probe(clip)
    reference_filter = f"[0:v]scale={info['width']}:{info['height']},setsar=1"
    generated_filter = f"[1:v]select=eq(n\\,{int(frame_index)}),setpts=PTS-STARTPTS,setsar=1"
    if comparison_width:
        reference_filter += f',scale={int(comparison_width)}:-2'
        generated_filter += f',scale={int(comparison_width)}:-2'
    graph = reference_filter+'[reference];'+generated_filter+'[generated];[reference][generated]ssim'
    result = _run([ffmpeg_bin(), '-hide_banner', '-nostats', '-filter_complex_threads', '1',
                   '-i', str(previous['last_frame']), '-i', str(clip), '-filter_complex', graph,
                   '-frames:v', '1', '-an', '-f', 'null', '-'], 60)
    matches = re.findall(r'All:([0-9.]+)', result.stderr)
    if not matches:
        raise ValueError('FFmpeg non ha restituito il confronto del raccordo')
    similarity = float(matches[-1])
    return {'status': 'pass' if similarity >= min_ssim else 'fail', 'ssim': similarity,
            'threshold': min_ssim, 'frame_index': frame_index,
            'clip_sha256': fingerprint(clip), 'source': source}


def inspect_seam(previous: dict, shot: dict) -> dict:
    """Distingue uno stacco da una variazione normale fra fotogrammi di una scena in movimento."""
    import statistics
    import tempfile
    from .production import _run, ffmpeg_bin, probe
    anchor = inspect(previous, shot, frame_index=0)
    first = inspect(previous, shot, frame_index=1)
    result = {**first, 'method': 'anchor_and_local_motion_v2', 'anchor_ssim': anchor['ssim'],
              'nominal_threshold': .92, 'motion_adjusted': False}
    if anchor['status'] != 'pass':
        return {**result, 'status': 'fail', 'reason': 'Il fotogramma guida non conserva la sorgente'}
    if first['status'] == 'pass':
        return result
    structure = inspect(previous, shot, frame_index=1, comparison_width=256, min_ssim=.90)
    result['structural_ssim'] = structure['ssim']
    layout = inspect(previous, shot, frame_index=1, comparison_width=32, min_ssim=.90)
    result['scene_layout_ssim'] = layout['ssim']
    if layout['status'] != 'pass' or probe(Path(shot['clip_path']))['frames'] < 4:
        return {**result, 'status': 'fail', 'reason': 'Geometria del raccordo incoerente o campioni insufficienti'}
    similarities, structural_motion = [], []
    with tempfile.TemporaryDirectory(prefix='sigma_seam_motion_') as tmp:
        for left, right in ((0, 1), (1, 2), (2, 3)):
            frame = Path(tmp) / f'{left}.png'
            _run([ffmpeg_bin(), '-v', 'error', '-y', '-i', shot['clip_path'],
                  '-vf', f'select=eq(n\\,{left})', '-frames:v', '1', '-update', '1', str(frame)], 60)
            reference = {'id': shot.get('id', 'candidate'), 'clip_path': shot['clip_path'], 'last_frame': str(frame)}
            following = {'clip_path': shot['clip_path'], 'continuation_source': binding(reference)}
            fine = inspect(reference, following, frame_index=right)['ssim']
            coarse = inspect(reference, following, frame_index=right, comparison_width=256)['ssim']
            if left == 0:
                start_motion, start_structure = fine, coarse
            else:
                similarities.append(fine)
                structural_motion.append(coarse)
    # Le rocce vicine cambiano molti pixel anche in un movimento regolare: la soglia segue quel moto,
    # mantenendo un limite assoluto e il controllo indipendente della geometria e della guida iniziale.
    threshold = max(.80, min(.92, statistics.median(similarities)-.03))
    structural_threshold = max(.75, min(.90, statistics.median(structural_motion)-.03))
    # Il confronto con la sorgente contiene anche l'errore di ricostruzione del VAE. Il moto iniziale
    # va misurato fra fotogrammi della stessa ricostruzione, senza ignorare la fedeltà alla sorgente.
    ok = (first['ssim'] >= .80 and structure['ssim'] >= .75
          and start_motion >= threshold and start_structure >= structural_threshold)
    return {**result, 'status': 'pass' if ok else 'fail',
            'threshold': .80, 'structural_threshold': .75, 'motion_adjusted': True,
            'start_motion_ssim': start_motion, 'motion_threshold': threshold,
            'start_structural_ssim': start_structure, 'structural_motion_threshold': structural_threshold,
            'local_motion_ssim': similarities, 'local_structural_ssim': structural_motion}
