"""Regia del restauro completo, con checkpoint delle fasi e pacchetto di pubblicazione."""
import asyncio
import hashlib
import json
from pathlib import Path

from core import paths
from core.store import JsonStore
from . import restoration as R
from .restoration_preferences import options


def preflight(editor, pid, args):
    from .editor_jobs import _item_source
    from .timeline import take_duration
    from .audio_export import validate_sigla_assets
    from .publishing import english_metadata
    value = options(args)
    if not value.get('item_id'):
        raise ValueError('Seleziona il video da restaurare')
    item, shot, take, _ = _item_source(editor, pid, value['item_id'])
    if shot.get('origin') != 'import':
        raise ValueError('La pipeline richiede un video caricato')
    if len(editor.timelines.get(pid).get('video') or []) != 1:
        raise ValueError('Per il pacchetto automatico usa un progetto con il solo film da restaurare')
    if float(item.get('src_in') or 0) > .05 or abs(float(item.get('src_out') or 0) - take_duration(take)) > .1:
        raise ValueError('La pipeline automatica richiede il film intero; ripristina i bordi del video prima di avviarla')
    if value['include_sigla']:
        validate_sigla_assets(value['sigla_assets_dir'], value['languages'])
        from .publication_identity import validate_template
        validate_template(value['sigla_assets_dir'])
    if value['output_dir'] and not Path(value['output_dir']).expanduser().is_absolute():
        raise ValueError('La destinazione del restauro deve essere un percorso assoluto')
    if value['output_dir']:
        destination = Path(value['output_dir']).expanduser()
        ancestor = destination
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        import os
        if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
            raise ValueError('La destinazione del restauro non è scrivibile')
    prod = editor.prods.get(pid)
    english_metadata({**value, 'title': value.get('publication_title') or prod['title'],
                      'year': value.get('publication_year', '')},
                     {'streams': [{'codec_type': 'video', 'height': value['output_height']}], 'format': {'duration': 1}}, [])
    return value


def _file_valid(result, key):
    return isinstance(result, dict) and bool(result.get(key)) and Path(result[key]).is_file()


async def run(editor, job):
    from . import editor_jobs as jobs
    from .audio_export import export_multilingual, add_sigla_to_master
    from .production import _slug, probe
    from .restoration_text import prepare_text, translate_job, localized_cards, state_fingerprint, translation_fingerprint
    from .publishing import create_package
    from .manga import GpuPerLaVista

    pid = job['production']
    args = preflight(editor, pid, job['args'])
    operation = job.get('operation_id') or job.get('retry_of') or job['id']
    _, shot, _, source = jobs._item_source(editor, pid, args['item_id'])
    original = next((t for t in shot.get('takes', []) if str(t.get('kind', '')).startswith('import')), None)
    source = Path(original['clip_path']) if original else source
    stat = source.stat()
    fingerprint = hashlib.sha256(json.dumps({'source': str(source.resolve()), 'size': stat.st_size,
        'mtime': stat.st_mtime_ns, 'args': args}, sort_keys=True).encode()).hexdigest()
    journal_path = editor.prods.path(pid) / 'restoration' / 'pipeline' / f'{hashlib.sha256(operation.encode()).hexdigest()[:20]}.json'
    store = JsonStore(journal_path, default={})
    journal = store.load()
    if journal.get('source') != fingerprint:
        journal = {'source': fingerprint, 'stages': {}}
    stages, dirty = [], False

    def state():
        return R.load_state(editor.prods.path(pid), shot['id'])

    async def phase(key, label, start, end, action, valid):
        nonlocal dirty
        editor.check_cancelled(job)
        previous = journal['stages'].get(key)
        try:
            reusable = not dirty and previous is not None and valid(previous)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            reusable = False
        if reusable:
            editor._note(job, label + ' · checkpoint verificato', end)
            stages.append({'phase': key, 'reused': True, **previous})
            return previous
        dirty = True
        editor._note(job, label, start)
        result = await action()
        if not valid(result):
            raise ValueError(f'La fase «{label}» non ha prodotto tutti i risultati previsti')
        journal['stages'][key] = result
        store.save(journal)
        stages.append({'phase': key, 'reused': False, **result})
        return result

    def sub(kind, extra, start, end):
        return {**job, 'kind': kind, 'args': {**args, **extra}, '_progress_parent': job,
                '_progress_range': (start, end)}

    def video_valid(value):
        if not _file_valid(value, 'path'):
            return False
        current = probe(Path(value['path']))
        expected = value.get('final') or {}
        return bool(current.get('width')) and all(current.get(k) == expected[k] for k in ('width', 'height', 'frames') if k in expected)
    remaster = await phase('video', 'Restauro video', 0, .55,
        lambda: jobs.job_remaster(editor, sub('remaster', {}, 0, .55)), video_valid)
    # Il riavvio può avere ripristinato una selezione diversa nella timeline.
    editor.timelines.apply(pid, 'set_take', {'item_id': args['item_id'], 'take_id': remaster['take']})
    await phase('text', 'Trascrizione e lettura dei testi', .55, .64,
        lambda: prepare_text(editor, sub('restore_read', {}, .55, .64)), lambda r: bool(state().get('cards')))
    text_state = state()
    prod = editor.prods.get(pid)
    prod.setdefault('settings', {}).update(restoration_content_type=args['content_type'],
                                         source_language=text_state.get('source_language') or 'en')
    editor.prods.save(prod)
    languages = args['languages']
    for index, language in enumerate(languages):
        start, end = .64 + .08 * index / len(languages), .64 + .08 * (index + 1) / len(languages)
        def translated_valid(result, lang=language):
            try:
                return (_file_valid(result, 'translation_path') and result.get('source_sha256') == state_fingerprint(state())
                        and result.get('translation_sha256') == translation_fingerprint(state(), lang)
                        and bool(localized_cards(state(), lang)))
            except ValueError:
                return False
        await phase('translate_' + language, f'Traduzione {language.upper()}', start, end,
                    lambda lang=language, a=start, b=end: translate_job(editor, sub('restore_translate', {'language': lang}, a, b)), translated_valid)
    if args['make_music']:
        def music_valid(result):
            clips = [c for tr in editor.timelines.get(pid).get('audio') or [] for c in tr.get('clips') or []
                     if (c.get('meta') or {}).get('restoration_score') == shot['id']]
            return bool(result.get('cues')) and len(clips) >= result['cues'] and all(Path(c['src']).is_file() for c in clips)
        await phase('music', 'Colonna sonora', .72, .8,
                    lambda: jobs.job_restore_score(editor, sub('restore_score', {'style': args['music_style']}, .72, .8)),
                    music_valid)
    else:
        jobs._remove_restoration_audio(editor, pid, shot['id'], 'restoration_score')
    for index, language in enumerate(languages):
        start, end = .8 + .1 * index / len(languages), .8 + .1 * (index + 1) / len(languages)
        def voice_valid(result, lang=language):
            if not _file_valid(result, 'subtitle') or result.get('unclear'):
                return False
            if result.get('native_audio'):
                return True
            clips = [clip for track in editor.timelines.get(pid).get('audio') or []
                     if str(track.get('id', '')).endswith(f"{shot['id']}_{lang}") for clip in track.get('clips') or []]
            return bool(clips) and all(Path(clip['src']).is_file() for clip in clips)
        await phase('voice_' + language, f'Voce e sottotitoli {language.upper()}', start, end,
            lambda lang=language, a=start, b=end: jobs.job_restore_narrate(editor, sub('restore_narrate',
                    {'language': lang, 'translations_prepared': True}, a, b)),
            voice_valid)
    prod, tl = editor.prods.get(pid), editor.timelines.get(pid)
    root = Path(args['output_dir']).expanduser() if args['output_dir'] else paths.creative_output_dir('video')
    root = root.resolve()
    if args['output_subfolder']:
        root /= f"{_slug(args.get('publication_title') or prod['title'])}_{pid[-6:]}"
    root.mkdir(parents=True, exist_ok=True)
    output = root / f"{_slug(prod['title'])}_{operation[-8:]}_restauro.mp4"
    base = output.with_name(output.stem + '_senza_sigla.mp4') if args['include_sigla'] else output
    result = await phase('export', 'Master multilingua', .9, .94,
        lambda: asyncio.to_thread(export_multilingual, tl, prod, editor.prods.path(pid), base, languages,
                                   lambda message, fraction: editor._note(job, message, .9 + .04 * fraction)),
        lambda r: _file_valid(r, 'output_path') and bool(probe(Path(r['output_path']))['width']))
    if args['include_sigla']:
        result = await phase('sigla', 'Intro e outro', .94, .97,
            lambda: asyncio.to_thread(add_sigla_to_master, base, output, args['sigla_assets_dir'], languages,
                args['sigla_cta_language'], lambda message, fraction: editor._note(job, message, .94 + .03 * fraction),
                film_title=args.get('publication_title') or prod['title'], film_year=args.get('publication_year', '')),
            lambda r: (_file_valid(r, 'output_path') and r.get('identity_title') == (args.get('publication_title') or prod['title'])
                       and r.get('identity_year') == args.get('publication_year', '')))
    publication = {}
    if args['make_publication']:
        facts = {**args, 'title': args.get('publication_title') or prod['title'],
                 'year': args.get('publication_year', ''), 'source_credit': args.get('source_credit', ''),
                 'intro_duration': result.get('intro_duration', 0)}
        _, ask_text = jobs._vista_asks()
        def publish():
            with GpuPerLaVista('titoli e descrizioni YouTube'):
                return create_package(output, root / ('youtube_' + operation[-8:]), facts, state()['cards'], ask_text,
                    lambda message, fraction: editor._note(job, message, .97 + .03 * fraction),
                    lambda: editor.check_cancelled(job))
        def publication_valid(value):
            if not _file_valid(value, 'package_path'):
                return False
            try:
                package = json.loads(Path(value['package_path']).read_text(encoding='utf-8'))
                directory = Path(value['package_path']).parent
                required = [package['video'], package['thumbnail'], 'pacchetto_youtube.md',
                            *package['captions'].values(), *package['audio_tracks'].values(),
                            *[path for files in package['text_files'].values() for path in files.values()]]
                from .publication_checks import validate_package
                expected = args.get('publication_title') or prod['title']
                return (package.get('identity', {}).get('title') == expected
                        and bool(validate_package(package, directory)['complete'])
                        and all((directory / path).is_file() for path in required))
            except (OSError, ValueError, KeyError):
                return False
        publication = await phase('publication', 'Pacchetto YouTube', .97, 1, lambda: asyncio.to_thread(publish), publication_valid)
    prod = editor.prods.get(pid)
    prod.update(output_path=str(output), publication=publication)
    editor.prods.save(prod)
    editor._note(job, 'Materiali completi · revisione editoriale richiesta' if publication else 'Restauro completato', 1)
    return {**result, **publication, 'output_path': str(output), 'languages': languages, 'stages': stages}
