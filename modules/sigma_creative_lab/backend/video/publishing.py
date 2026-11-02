"""Pacchetto YouTube locale: standard editoriale, localizzazioni e media verificati."""
import hashlib
import json
from pathlib import Path
import re

from core.store import JsonStore
from .audio_export import LANG_TAGS

LOCALES = {'pt': 'pt-BR', 'zh': 'zh-Hans'}
LANG_NAMES = {'en': 'English', 'it': 'Italiano', 'fr': 'Français', 'de': 'Deutsch',
              'es': 'Español', 'pt': 'Português brasileiro', 'zh': '中文（简体）', 'ar': 'العربية'}
STANDARD = 'sigma-restoration-1'


def _run(args, timeout=1800):
    from .production import _run as execute, ffmpeg_bin
    return execute([ffmpeg_bin(), '-hide_banner', '-v', 'error', '-y', *map(str, args)], timeout)


def media_info(path):
    from .production import _run as execute, ffmpeg_bin
    result = execute([ffmpeg_bin('ffprobe'), '-v', 'error', '-show_entries',
        'format=duration:stream=index,codec_type,width,height,duration:stream_tags=language', '-of', 'json', str(path)])
    data = json.loads(result.stdout)
    if float(data.get('format', {}).get('duration') or 0) <= 0:
        raise ValueError('Video finale senza durata valida')
    return data


def _validate_localization(data):
    if not isinstance(data, dict):
        raise ValueError('Titolo e descrizione devono essere un oggetto')
    title, description = data.get('title'), data.get('description')
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or any(c in title for c in '<>\r\n'):
        raise ValueError('Il titolo deve contenere da 1 a 100 caratteri, senza parentesi angolari o ritorni a capo')
    if not isinstance(description, str) or not description.strip() or len(description.encode('utf-8')) > 5000 or any(c in description for c in '<>'):
        raise ValueError('La descrizione deve essere presente e non superare 5000 byte UTF-8')
    return {'title': title.strip(), 'description': description.strip()}


def _clock(seconds):
    value = max(0, int(seconds))
    return f'{value // 3600}:{value // 60 % 60:02d}:{value % 60:02d}' if value >= 3600 else f'{value // 60}:{value % 60:02d}'


def chapters(cards, duration, intro_duration=0):
    # Le sigle brevi fanno parte del primo capitolo: YouTube richiede almeno dieci secondi per capitolo.
    result = [(0, 'Intro and opening')]
    interval = max(120, (duration - intro_duration) / 10)
    last = 0
    for card in sorted(cards, key=lambda c: c['start']):
        if card.get('deleted'):
            continue
        when = float(card['start']) + intro_duration
        if when - last < interval or duration - when < 10:
            continue
        label = ' '.join(str(card.get('text') or '').split()[:9]).strip(' \"“”')
        if label:
            result.append((when, label))
            last = when
    return result if len(result) >= 3 else []


def english_metadata(facts, info, cards):
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    if not video:
        raise ValueError('Il master non contiene video')
    name = str(facts.get('title') or '').strip()
    if not name:
        raise ValueError('Manca il titolo del film')
    year = str(facts.get('year') or '').strip()
    if year and not re.fullmatch(r'(18|19|20)\d{2}', year):
        raise ValueError('Anno del film non valido')
    prefix = name + (f' ({year})' if year else '')
    resolution = f"{video['height']}p"
    extended = ' with Narration and New Score' if facts.get('make_music') else ' with Narration'
    suffix = next((s for s in (f' – Restored in Color & {resolution} | AI Remaster{extended}',
                    f' – Restored in Color & {resolution} | AI Remaster', f' | {resolution} · Sigma Studio', '')
                   if len(prefix + s) <= 100), '')
    # Si abbrevia solo l'etichetta editoriale, mai il titolo originale.
    title = prefix + suffix
    lines = [f'{prefix}, restored by Sigma Studio.', '', 'What we did:',
             '• AI-assisted film cleanup, stabilization and restoration',
             '• Consistent color processing, preserving protected original-color scenes',
             f'• Restored master at {resolution}',
             '• Multilingual narration and subtitles. Audio languages: ' + ', '.join(LANG_NAMES[x] for x in facts['languages'])]
    if facts.get('content_type') == 'documentary':
        lines.append('• Original speech transcribed and translated; dubbed tracks are aligned to the original timing')
    if facts.get('make_music'):
        lines.append('• An original score composed for this restoration (AI-generated)')
    lines += ['', 'This is a passion project, built with artificial intelligence and offered free to the community. '
              'Colors interpreted by AI are not a historical record.']
    if facts.get('source_credit'):
        lines += ['', 'Source: ' + str(facts['source_credit']).strip()]
    points = chapters(cards, float(info['format']['duration']), float(facts.get('intro_duration') or 0))
    if points:
        lines += ['', 'Chapters', *[f'{_clock(t)} {label}' for t, label in points]]
    lines += ['', '#SigmaStudio #Restored #AIRestoration' + (' #Documentary' if facts.get('content_type') == 'documentary' else ' #SilentFilm')]
    return _validate_localization({'title': title, 'description': '\n'.join(lines)})


def localizations(base, languages, ask_text, cache_path, progress, check_cancelled):
    identity = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()
    store = JsonStore(cache_path, default={})
    cached = store.load()
    saved = cached.get('localizations', {}) if cached.get('source') == identity else {}
    output = {}
    source_times = re.findall(r'^\d+:\d\d(?::\d\d)?(?= )', base['description'], re.M)
    for index, language in enumerate(languages):
        check_cancelled()
        if language == 'en':
            value = base
        else:
            value = saved.get(language)
            if value:
                value = _validate_localization(value)
            else:
                error = ''
                for _ in range(2):
                    answer = ask_text('Translate this YouTube title and description into ' + LANG_NAMES[language] + '. '
                        'Preserve facts, proper names, resolution, every chapter timestamp and the Sigma Studio brand. '
                        'Do not add dates, cast, sources, public-domain claims or other facts. '
                        'Title at most 100 characters; description at most 5000 UTF-8 bytes. '
                        'Return only a JSON object with title and description. ' + error + '\n' + json.dumps(base, ensure_ascii=False), 3000)
                    try:
                        text = answer.strip()
                        value = _validate_localization(json.loads(text[text.index('{'):text.rindex('}') + 1]))
                        if re.findall(r'^\d+:\d\d(?::\d\d)?(?= )', value['description'], re.M) != source_times:
                            raise ValueError('I tempi dei capitoli sono stati modificati')
                        break
                    except (ValueError, TypeError) as exc:
                        value = None
                        error = 'Correct this validation problem: ' + str(exc)
                if value is None:
                    raise ValueError(f'Metadati {language}: {error}')
        output[LOCALES.get(language, language)] = value
        saved[language] = value
        store.save({'source': identity, 'localizations': saved})
        progress(f'Titolo e descrizione {language.upper()}', .1 + .4 * (index + 1) / len(languages))
    return output


def _thumbnail(video, target, duration, intro):
    from PIL import Image, ImageStat
    best, best_score = None, -1
    for index, fraction in enumerate((.25, .5, .75)):
        candidate = target.with_name(f'.thumbnail_{index}.jpg')
        when = min(duration - .1, intro + max(0, duration - intro) * fraction)
        _run(['-ss', when, '-i', video, '-frames:v', 1, '-vf',
              'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1',
              '-q:v', 2, '-update', 1, candidate], 120)
        with Image.open(candidate) as image:
            stats = ImageStat.Stat(image.convert('L'))
            score = stats.stddev[0] if 15 < stats.mean[0] < 240 else 0
        if score > best_score:
            best, best_score = candidate, score
    if best is None:
        raise ValueError('Impossibile preparare la miniatura')
    target.write_bytes(best.read_bytes())
    for index in range(3):
        target.with_name(f'.thumbnail_{index}.jpg').unlink(missing_ok=True)


def create_package(video, directory, facts, cards, ask_text, progress=lambda message, value: None,
                   check_cancelled=lambda: None):
    video, directory = Path(video).resolve(), Path(directory).resolve()
    languages = facts['languages']
    if not isinstance(languages, list) or not languages or len(set(languages)) != len(languages) or set(languages) - LANG_TAGS.keys():
        raise ValueError('Lingue del pacchetto non valide')
    if facts.get('default_language', languages[0]) not in languages:
        raise ValueError('Lingua predefinita assente dalle lingue del pacchetto')
    info = media_info(video)
    streams = info['streams']
    audio = [s for s in streams if s['codec_type'] == 'audio']
    subtitles = [s for s in streams if s['codec_type'] == 'subtitle']
    def index_for(kind, language):
        tags = {LANG_TAGS[language][0], language, LOCALES.get(language, language)}
        matches = [index for index, stream in enumerate(kind) if stream.get('tags', {}).get('language') in tags]
        if len(matches) != 1:
            raise ValueError(f'Traccia {language} assente o ambigua nel master')
        return matches[0]
    mapping = {language: (index_for(audio, language), index_for(subtitles, language)) for language in languages}
    base = english_metadata(facts, info, cards)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('audio', 'subtitles', 'titles', 'descriptions'):
        (directory / name).mkdir(exist_ok=True)
    locs = localizations(base, languages, ask_text, directory / 'translations.json', progress, check_cancelled)
    captions, dubs, text_files = {}, {}, {}
    duration = float(info['format']['duration'])
    for index, language in enumerate(languages):
        check_cancelled()
        a, s = mapping[language]
        audio_path, caption_path = directory / 'audio' / f'audio_{language}.m4a', directory / 'subtitles' / f'subtitles_{language}.srt'
        _run(['-i', video, '-map', f'0:a:{a}', '-vn', '-c:a', 'copy', '-movflags', '+faststart', audio_path])
        _run(['-i', video, '-map', f'0:s:{s}', '-c:s', 'srt', caption_path])
        if not caption_path.read_text(encoding='utf-8-sig').strip():
            raise ValueError(f'Sottotitoli {language} vuoti')
        audio_info = media_info(audio_path)
        if abs(float(audio_info['format']['duration']) - duration) > .25:
            raise ValueError(f'Audio {language} non allineato alla durata del video')
        locale = LOCALES.get(language, language)
        captions[locale] = caption_path.relative_to(directory).as_posix()
        dubs[locale] = audio_path.relative_to(directory).as_posix()
        (directory / 'titles' / f'title_{language}.txt').write_text(locs[locale]['title'] + '\n', encoding='utf-8')
        (directory / 'descriptions' / f'description_{language}.txt').write_text(locs[locale]['description'] + '\n', encoding='utf-8')
        text_files[locale] = {'title': f'titles/title_{language}.txt', 'description': f'descriptions/description_{language}.txt'}
        progress(f'Audio e sottotitoli {language.upper()}', .5 + .35 * (index + 1) / len(languages))
    check_cancelled()
    thumbnail = directory / 'miniatura.jpg'
    _thumbnail(video, thumbnail, duration, float(facts.get('intro_duration') or 0))
    import os
    relative_video = Path(os.path.relpath(video, directory)).as_posix()
    default = LOCALES.get(facts.get('default_language', languages[0]), facts.get('default_language', languages[0]))
    package = {'standard': STANDARD, 'video': relative_video, 'default_language': default,
               'default_audio_language': default, 'localizations': locs, 'captions': captions,
               'audio_tracks': dubs, 'text_files': text_files, 'thumbnail': thumbnail.name,
               'tags': [str(facts['title'])[:50], 'Sigma Studio', 'AI restoration', 'restored',
                        'documentary' if facts.get('content_type') == 'documentary' else 'silent film'],
               'category_id': '1', 'privacy': 'private', 'made_for_kids': bool(facts.get('made_for_kids', False)),
               'contains_synthetic_media': True,
               'notes': 'I doppiaggi audio_*.m4a si aggiungono in YouTube Studio → Lingue; il caricamento via API non li include.',
               'validation': {'complete': True, 'languages': languages, 'duration': duration}}
    body = ['# Pacchetto YouTube · ' + str(facts['title']), '',
            f'Video: `{relative_video}`', '', package['notes'], '',
            'Lingua predefinita: ' + default, 'Contenuto alterato o sintetico: sì', '']
    for language in languages:
        value = locs[LOCALES.get(language, language)]
        body += ['## ' + LANG_NAMES[language], '', '**Titolo**', value['title'], '', '**Descrizione**', value['description'], '']
    (directory / 'pacchetto_youtube.md').write_text('\n'.join(body), encoding='utf-8')
    JsonStore(directory / 'youtube_package.json').save(package)
    progress('Pacchetto YouTube completo e verificato', 1)
    return {'package_path': str(directory / 'youtube_package.json'), 'package_dir': str(directory),
            'publication_ready': True, 'languages': languages, 'standard': STANDARD}
