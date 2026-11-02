"""Verifica gli artefatti finali prima di segnare pronto un pacchetto editoriale."""
import re
import json
from pathlib import Path


def validate_package(package, directory):
    from PIL import Image
    from .publishing import media_info, _validate_localization
    root = Path(directory)
    languages = set(package['audio_tracks'])
    if not languages or any(set(package[key]) != languages for key in ('captions', 'localizations', 'text_files')):
        raise ValueError('Lingue incoerenti fra audio, sottotitoli, titoli e descrizioni')
    info = media_info(root / package['video'])
    duration = float(info['format']['duration'])
    if sum(s['codec_type'] == 'audio' for s in info['streams']) != len(languages):
        raise ValueError('Il numero di tracce audio nel master non coincide con le lingue del pacchetto')
    identity = package.get('identity') or {}
    if identity.get('include_sigla'):
        from .publication_identity import title_overlay, verify_title_frame
        video = (root / package['video']).resolve()
        try:
            proof = json.loads(video.with_suffix('.identity.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('Manca la verifica del titolo incorporato nella sigla') from exc
        if (str(proof.get('title', '')).casefold() != str(identity.get('title', '')).casefold()
                or str(proof.get('year', '')) != str(identity.get('year', '')) or proof.get('size') != video.stat().st_size):
            raise ValueError('La sigla appartiene a un altro film o il master è cambiato')
        stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
        checks = root / 'checks'
        checks.mkdir(exist_ok=True)
        expected = title_overlay(stream['width'], stream['height'], proof['title'], proof['year'], checks / 'expected_intro.png')
        verify_title_frame(video, expected, float(identity['intro_duration']) / 2, checks / 'intro_verified.png')
    for stream in info['streams']:
        if stream['codec_type'] in ('video', 'audio'):
            if abs(float(stream.get('duration') or 0) - duration) > .25:
                raise ValueError('Una traccia del master ha durata diversa dal video')
    thumbnail = root / package['thumbnail']
    if not thumbnail.is_file() or thumbnail.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Miniatura mancante o superiore a 2 MB')
    with Image.open(thumbnail) as image:
        if image.width < 1280 or abs(image.width / image.height - 16 / 9) > .01:
            raise ValueError('La miniatura deve essere almeno 1280×720 in formato 16:9')
    for language, audio in package['audio_tracks'].items():
        if abs(float(media_info(root / audio)['format']['duration']) - duration) > .25:
            raise ValueError(f'Audio {language}: durata diversa dal master definitivo')
        subtitle = root / package['captions'][language]
        text = subtitle.read_text(encoding='utf-8-sig')
        if not re.search(r'\d\d:\d\d:\d\d,\d{3} -->', text):
            raise ValueError(f'Sottotitoli {language} mancanti o vuoti')
        for start, end in re.findall(r'(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})', text):
            def seconds(stamp):
                hours, minutes, value = stamp.replace(',', '.').split(':')
                return int(hours) * 3600 + int(minutes) * 60 + float(value)
            if seconds(end) <= seconds(start) or seconds(end) > duration + .25:
                raise ValueError(f'Sottotitoli {language}: tempi fuori dalla durata del master')
    for language, value in package['localizations'].items():
        _validate_localization(value)
        for key in ('title', 'description'):
            if (root / package['text_files'][language][key]).read_text(encoding='utf-8').strip() != value[key].strip():
                raise ValueError(f'Il file {key} {language} non coincide con il manifest')
    return {'complete': True, 'duration': duration, 'checks': ['identity_metadata', 'master_durations',
            'audio_durations', 'captions', 'thumbnail', 'localized_files'], 'editorial_review_required': True}
