"""Trascrizione, traduzioni complete e sottotitoli della pipeline di restauro."""
import asyncio
import hashlib
import json
from pathlib import Path

from core.store import JsonStore
from . import restoration as R


def text_fingerprint(card):
    return hashlib.sha256(str(card.get('text') or '').encode()).hexdigest()


def state_fingerprint(state):
    cards = [{key: card.get(key) for key in ('text', 'speaker', 'start', 'end', 'deleted')}
             for card in state.get('cards') or []]
    return hashlib.sha256(json.dumps([state.get('source_language'), cards], sort_keys=True).encode()).hexdigest()


def localized_cards(state, language):
    source = state.get('source_language') or 'en'
    saved = (state.get('translations') or {}).get(language) or {}
    result = []
    for index, card in enumerate(state.get('cards') or []):
        if card.get('deleted'):
            continue
        text = card.get('text', '') if language == source else saved.get(str(index), '')
        if not str(text).strip():
            raise ValueError(f'Traduzione {language.upper()} mancante per il testo {index + 1}')
        result.append({**card, 'text_spoken': str(text).strip()})
    return result


def translation_fingerprint(state, language):
    return hashlib.sha256(json.dumps(localized_cards(state, language), sort_keys=True).encode()).hexdigest()


def ensure_translations(state, language, ask_text):
    source = state.get('source_language') or 'en'
    saved = state.setdefault('translations', {}).setdefault(language, {})
    hashes = state.setdefault('translation_sources', {}).setdefault(language, {})
    pending = [(i, c) for i, c in enumerate(state.get('cards') or []) if not c.get('deleted')
               and (not saved.get(str(i)) or hashes.get(str(i), text_fingerprint(c)) != text_fingerprint(c))]
    if language == source:
        translated = [{'text_spoken': card['text']} for _, card in pending]
    else:
        translated = R.translate_cards([card for _, card in pending], language, ask_text, strict=True)
    for (index, card), value in zip(pending, translated):
        saved[str(index)] = value['text_spoken']
        hashes[str(index)] = text_fingerprint(card)
    return localized_cards(state, language)


def subtitle_path(prod_dir, title, language):
    from .production import _slug
    directory = Path(prod_dir) / 'subtitles'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f'{_slug(title)}_{language}.srt'


def write_subtitles(path, cards):
    def stamp(value):
        ms = max(0, round(float(value) * 1000))
        hours, ms = divmod(ms, 3600000)
        minutes, ms = divmod(ms, 60000)
        seconds, ms = divmod(ms, 1000)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'
    cues = []
    for index, card in enumerate(cards, 1):
        start = float(card.get('at', card['start']))
        end = start + float(card['duration']) if 'duration' in card else float(card['end'])
        if end <= start:
            raise ValueError('Sottotitolo con durata non positiva')
        cues.extend([str(index), f'{stamp(start)} --> {stamp(end)}', card.get('text_spoken') or card['text'], ''])
    if not cues:
        raise ValueError('Nessun sottotitolo da esportare')
    path.write_text('\n'.join(cues), encoding='utf-8-sig')


async def prepare_text(editor, job):
    from .editor_jobs import _item_source, _vista_asks, job_restore_read
    from .manga import GpuPerLaVista
    from .production import probe
    pid, args = job['production'], job['args']
    _, shot, take, source = _item_source(editor, pid, args['item_id'])
    prod = editor.prods.get(pid)
    pdir = editor.prods.path(pid)
    if args.get('content_type') == 'documentary':
        editor._note(job, 'Trascrizione del parlato originale', 0.1)
        transcript = await transcribe_chunks(editor, job, source, pdir / 'restoration' / shot['id'] / 'asr')
        language = str(transcript.get('language') or args.get('source_language') or 'en').lower()[:2]
        from .restoration_preferences import LANGUAGES
        if language not in LANGUAGES:
            raise ValueError(f'Lingua originale rilevata non supportata: {language}')
        cards = [{'start': float(s['start']), 'end': float(s['end']), 'text': str(s['text']).strip(),
                  'kind': 'speech', 'speaker': 'narrator'} for s in transcript.get('segments') or []
                 if str(s.get('text') or '').strip() and float(s['end']) > float(s['start'])]
        if not cards:
            raise ValueError('Non è stato riconosciuto parlato: scegli Film o documentario muto se la sorgente non contiene voci')
        analysis = await asyncio.to_thread(R.analyze, source)
        state = {'take': take['id'], 'title': prod['title'], 'cards': cards, 'analysis': analysis,
                 'source_language': language, 'content_type': 'documentary'}
        R.save_state(pdir, shot['id'], state)
        return {'shot': shot['id'], 'cards': len(cards), 'source_language': language}
    result = await job_restore_read(editor, job)
    state = R.load_state(pdir, shot['id'])
    state.update(source_language='en' if args.get('source_language') == 'auto' else args.get('source_language', 'en'),
                 content_type='silent')
    if not state.get('cards'):
        editor._note(job, 'Narrazione descrittiva delle scene senza didascalie', 0.7)
        ask_image, _ = _vista_asks()
        duration = float(probe(source)['duration'])
        cards = []
        with GpuPerLaVista('narrazione del documentario muto'):
            for start in range(0, max(1, int(duration)), 90):
                editor.check_cancelled(job)
                prompt = ('Write one short factual sentence in English describing only what is visibly happening. '
                          'Do not invent names, dates, locations, motives or historical facts. Return only the narration.')
                text = (await asyncio.to_thread(ask_image, R.frame_jpeg(source, min(start + 2, max(0, duration - .1))), prompt)).strip()
                if not text or text.upper() == 'NONE':
                    continue
                cards.append({'start': start, 'end': min(duration, start + 25), 'kind': 'narration',
                              'speaker': 'narrator', 'text': text})
        if not cards:
            raise ValueError('La lettura visiva non ha prodotto testi utilizzabili')
        state['cards'] = cards
        state['source_language'] = 'en'
    R.save_state(pdir, shot['id'], state)
    return {**result, 'cards': len(state['cards']), 'source_language': state['source_language']}


async def transcribe_chunks(editor, job, source, directory):
    from ..voice.runtime import voice_runtime
    from .production import _run, ffmpeg_bin, probe
    stat = source.stat()
    duration = float(probe(source)['duration'])
    language = '' if job['args'].get('source_language') == 'auto' else job['args'].get('source_language', 'en')
    identity = hashlib.sha256(f'{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{language}'.encode()).hexdigest()[:20]
    words = []
    detected = language
    directory.mkdir(parents=True, exist_ok=True)
    try:
        for start in range(0, max(1, int(duration + .999)), 90):
            editor.check_cancelled(job)
            offset, end = max(0, start - 1), min(duration, start + 90)
            cache = JsonStore(directory / f'{identity}_{start}.json', default={})
            transcript = cache.load()
            if not transcript or not isinstance(transcript.get('words'), list):
                audio = directory / f'{identity}_{start}.wav'
                await asyncio.to_thread(_run, [ffmpeg_bin(), '-v', 'error', '-y', '-ss', str(offset),
                    '-i', str(source), '-t', str(min(duration, end + 1) - offset), '-vn', '-ac', '1', '-ar', '16000', str(audio)], 300)
                transcript = await asyncio.to_thread(voice_runtime.transcribe, audio, detected)
                if not isinstance(transcript.get('words'), list):
                    raise ValueError('La trascrizione non contiene tempi delle parole')
                cache.save(transcript)
            if transcript['words']:
                detected = detected or str(transcript.get('language') or '')
            for word in transcript['words']:
                a, b = offset + float(word['start']), offset + float(word['end'])
                if b > a and start <= (a + b) / 2 < end and str(word.get('word') or '').strip():
                    words.append({'start': max(0, a), 'end': min(duration, b), 'word': word['word']})
            editor._note(job, f'Trascrizione del parlato: {min(int(duration), start + 90)} / {int(duration)} secondi',
                         0.1 + .6 * end / max(duration, 1))
    finally:
        await asyncio.to_thread(voice_runtime.unload)
    segments, pending = [], []
    for word in words:
        if pending and (word['end'] - pending[0]['start'] > 12 or word['start'] - pending[-1]['end'] > 1):
            segments.append({'start': pending[0]['start'], 'end': pending[-1]['end'], 'text': ' '.join(w['word'] for w in pending)})
            pending = []
        pending.append(word)
    if pending:
        segments.append({'start': pending[0]['start'], 'end': pending[-1]['end'], 'text': ' '.join(w['word'] for w in pending)})
    return {'language': detected, 'segments': segments}


async def translate_job(editor, job):
    from .editor_jobs import _item_source, _vista_asks
    from .manga import GpuPerLaVista
    pid, args = job['production'], job['args']
    _, shot, _, _ = _item_source(editor, pid, args['item_id'])
    pdir = editor.prods.path(pid)
    state = R.load_state(pdir, shot['id'])
    _, ask_text = _vista_asks()
    language = args['language']
    with GpuPerLaVista(f'traduzione {language}'):
        cards = await asyncio.to_thread(ensure_translations, state, language, ask_text)
    R.save_state(pdir, shot['id'], state)
    output = pdir / 'restoration' / shot['id'] / 'translations' / f'{language}.json'
    JsonStore(output).save({'source_language': state.get('source_language', 'en'), 'language': language, 'cards': cards})
    return {'shot': shot['id'], 'language': language, 'texts': len(cards), 'translation_path': str(output),
            'source_sha256': state_fingerprint(state), 'translation_sha256': translation_fingerprint(state, language)}


def fit_speech(lines, output_dir):
    from .production import _run, ffmpeg_bin
    result = []
    for index, line in enumerate(lines):
        span = max(.1, float(line['end']) - float(line['start']))
        duration = float(line['duration'])
        if duration > span:
            rate = duration / span
            if rate > 2:
                raise ValueError(f'La battuta {index + 1} è troppo lunga per il parlato originale: serve una traduzione più concisa')
            target = Path(output_dir) / f'{index:04d}_timed.wav'
            _run([ffmpeg_bin(), '-v', 'error', '-y', '-i', str(line['wav']), '-af', f'atempo={rate:.8f}',
                  '-ar', '48000', '-ac', '2', str(target)], timeout=300)
            line = {**line, 'wav': str(target), 'duration': span}
        result.append({**line, 'at': float(line['start'])})
    return result
