"""Contratti del restauro pubblicabile, senza inferenza o accesso alla GPU."""
import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.store import JsonStore
from core.modules.sigma_creative_lab.video import publishing as P
from core.modules.sigma_creative_lab.video import restoration as R
from core.modules.sigma_creative_lab.video import restoration_preferences as prefs
from core.modules.sigma_creative_lab.video import restoration_text as text


def test_preset_non_riusa_dati_editoriali(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, 'store', lambda: JsonStore(tmp_path / 'preset.json', default={}))
    saved = prefs.save_defaults({'publication_title': 'Un film', 'publication_year': '1926',
                                'source_credit': 'Archivio', 'languages': ['it'], 'include_sigla': False})
    assert not {'publication_title', 'publication_year', 'source_credit'} & saved.keys()
    assert prefs.load_defaults()['default_language'] == 'it'


@pytest.mark.parametrize('invalid', [{'languages': []}, {'languages': ['../../x']}, {'make_music': 'false'},
                                   {'output_height': 42}, {'made_for_kids': 'false'}])
def test_opzioni_errate_non_arrivano_alla_gpu(invalid):
    with pytest.raises(ValueError):
        prefs.options(invalid, prefs.DEFAULTS)


def test_documentario_conserva_audio_originale():
    assert prefs.options({'content_type': 'documentary'}, prefs.DEFAULTS)['preserve_source_audio'] is True


def test_trascrizione_a_blocchi_riprende_cache_senza_duplicare_parole(tmp_path, monkeypatch):
    from core.modules.sigma_creative_lab.video import production
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    source = tmp_path / 'film.mp4'
    source.write_bytes(b'video')
    monkeypatch.setattr(production, 'probe', lambda _: {'duration': 100})
    monkeypatch.setattr(production, '_run', lambda *_: None)
    calls = []
    def transcribe(path, language):
        calls.append(language)
        words = ([{'word': 'Prima', 'start': 89, 'end': 89.8}] if len(calls) == 1 else
                 [{'word': 'Prima', 'start': 0, 'end': .8}, {'word': 'Dopo', 'start': 1.1, 'end': 2}])
        return {'language': 'it', 'words': words}
    monkeypatch.setattr(voice_runtime, 'transcribe', transcribe)
    monkeypatch.setattr(voice_runtime, 'unload', lambda: None)
    editor = SimpleNamespace(check_cancelled=lambda _: None, _note=lambda *_: None)
    job = {'args': {'source_language': 'auto'}}
    first = asyncio.run(text.transcribe_chunks(editor, job, source, tmp_path / 'asr'))
    assert ' '.join(s['text'] for s in first['segments']) == 'Prima Dopo'
    assert calls == ['', 'it']
    assert asyncio.run(text.transcribe_chunks(editor, job, source, tmp_path / 'asr')) == first
    assert len(calls) == 2


def test_mix_parlato_originale_non_applica_filtro_musicale(tmp_path, monkeypatch):
    from core.modules.sigma_creative_lab.video import production, audio_export, score_quality
    commands = []
    monkeypatch.setattr(production, '_run', lambda command, **_: commands.append(command))
    monkeypatch.setattr(score_quality, 'source_music_filter', lambda *_: pytest.fail('Filtro musicale sul parlato'))
    audio_export._audio_mix([], 'it', tmp_path / 'mix.m4a', 10, tmp_path / 'source.mp4', source_is_dialogue=True)
    graph = commands[0][commands[0].index('-filter_complex') + 1]
    assert 'volume=0dB' in graph
    assert '[original]anull[speech]' in graph


def test_traduzione_incompleta_non_usa_testo_originale():
    state = {'source_language': 'en', 'cards': [{'text': 'Hello', 'start': 0, 'end': 2}]}
    with pytest.raises(ValueError, match='incompleta'):
        text.ensure_translations(state, 'it', lambda *_: '[]')
    with pytest.raises(ValueError, match='mancante'):
        text.localized_cards(state, 'it')


def test_modifica_originale_invalida_traduzione_e_voce(tmp_path):
    state = {'source_language': 'en', 'cards': [{'text': 'Hello', 'start': 0, 'end': 2}]}
    text.ensure_translations(state, 'it', lambda *_: '["Ciao"]')
    before = text.translation_fingerprint(state, 'it')
    R.save_state(tmp_path, 'shot', state)
    R.update_cards(tmp_path, 'shot', [{'index': 0, 'text': 'Goodbye'}])
    changed = R.load_state(tmp_path, 'shot')
    text.ensure_translations(changed, 'it', lambda *_: '["Addio"]')
    assert text.localized_cards(changed, 'it')[0]['text_spoken'] == 'Addio'
    assert text.translation_fingerprint(changed, 'it') != before


def test_correzione_tradotta_non_altera_originale(tmp_path):
    state = {'source_language': 'it', 'cards': [{'text': 'Ciao', 'start': 0, 'end': 2}]}
    R.save_state(tmp_path, 'shot', state)
    R.update_cards(tmp_path, 'shot', [{'index': 0, 'language': 'fr', 'text': 'Bonjour'}])
    saved = R.load_state(tmp_path, 'shot')
    assert saved['cards'][0]['text'] == 'Ciao'
    assert text.ensure_translations(saved, 'fr', lambda *_: pytest.fail('Traduzione già corretta'))[0]['text_spoken'] == 'Bonjour'


def test_limite_descrizione_conta_byte_utf8():
    with pytest.raises(ValueError, match='5000 byte'):
        P._validate_localization({'title': 'Film', 'description': '界' * 1700})


def test_standard_non_inventa_fatti_e_rispetta_limiti():
    info = {'streams': [{'codec_type': 'video', 'height': 1440}], 'format': {'duration': 900}}
    value = P.english_metadata({'title': 'Titolo ' * 10, 'languages': ['en'], 'make_music': True}, info, [])
    assert len(value['title']) <= 100
    assert 'public domain' not in value['description'].lower()
    assert 'Source:' not in value['description']
    assert '1440p' in value['description']


def test_localizzazioni_cache_e_capitoli(tmp_path):
    base = {'title': 'Film', 'description': '0:00 Opening\n2:00 Train\n4:00 End'}
    calls = []
    def ask(*_):
        calls.append(1)
        return json.dumps(base)
    first = P.localizations(base, ['en', 'pt', 'zh'], ask, tmp_path / 'cache.json', lambda *_: None, lambda: None)
    assert set(first) == {'en', 'pt-BR', 'zh-Hans'}
    P.localizations(base, ['en', 'pt', 'zh'], lambda *_: pytest.fail('Cache ignorata'), tmp_path / 'cache.json', lambda *_: None, lambda: None)
    assert len(calls) == 2


def test_metadati_scartano_traduzione_con_tempi_alterati(tmp_path):
    with pytest.raises(ValueError, match='tempi dei capitoli'):
        P.localizations({'title': 'Film', 'description': '0:00 Opening'}, ['it'],
                        lambda *_: '{"title":"Film","description":"1:00 Apertura"}',
                        tmp_path / 'cache.json', lambda *_: None, lambda: None)


def test_pacchetto_reale_ffmpeg_e_compatibilita_youtube(tmp_path):
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
    from core.modules.sigma_youtube_studio.youtube_api import load_package
    subtitle = tmp_path / 'test.srt'
    subtitle.write_text('1\n00:00:00,100 --> 00:00:01,500\nProva\n', encoding='utf-8')
    master = tmp_path / 'master.mp4'
    _run([ffmpeg_bin(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=24:d=2',
          '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-i', str(subtitle),
          '-map', '0:v', '-map', '1:a', '-map', '1:a', '-map', '2:s', '-map', '2:s',
          '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', '-c:s', 'mov_text',
          '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=ita',
          '-metadata:s:s:0', 'language=eng', '-metadata:s:s:1', 'language=ita', str(master)], 30)
    facts = {'title': 'Film di prova', 'languages': ['en', 'it'], 'default_language': 'en'}
    result = P.create_package(master, tmp_path / 'youtube', facts, [],
                              lambda *_: '{"title":"Film di prova","description":"Descrizione italiana."}')
    manifest = json.loads(Path(result['package_path']).read_text())
    assert manifest['validation']['complete'] is True
    assert manifest['privacy'] == 'private'
    assert manifest['video'] == '../master.mp4'
    assert len(manifest['captions']) == len(manifest['audio_tracks']) == 2
    assert (tmp_path / 'youtube/titles/title_it.txt').read_text().strip() == 'Film di prova'
    assert load_package(result['package_path'])['video'] == str(master)


def test_ripresa_dopo_errore_pubblicazione_non_rifacesse_restauro(tmp_path, monkeypatch):
    from core.modules.sigma_creative_lab.video import publication_checks
    monkeypatch.setattr(publication_checks, 'validate_package', lambda *_: {'complete': True})
    from core.modules.sigma_creative_lab.video import restoration_pipeline as pipe, editor_jobs, audio_export, production, manga
    args = prefs.options({'item_id': 'item', 'languages': ['en'], 'include_sigla': False,
                          'make_music': False, 'output_dir': str(tmp_path)}, prefs.DEFAULTS)
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source')
    video = tmp_path / 'restored.mp4'
    video.write_bytes(b'restored')
    sub = tmp_path / 'en.srt'
    sub.write_text('subtitle')
    clip = tmp_path / 'voice.wav'
    clip.write_bytes(b'audio')
    shot = {'id': 'shot', 'takes': [{'kind': 'import_video', 'clip_path': str(source)}]}
    prod = {'title': 'Film', 'settings': {}}
    tl = {'audio': [{'id': 'restore_voice_shot_en', 'clips': [{'src': str(clip)}]}]}
    editor = SimpleNamespace(prods=SimpleNamespace(path=lambda _: tmp_path, get=lambda _: prod, save=lambda _: None),
                             timelines=SimpleNamespace(get=lambda _: tl, apply=lambda *_: None),
                             check_cancelled=lambda _: None, _note=lambda *_: None)
    monkeypatch.setattr(pipe, 'preflight', lambda *_: args)
    monkeypatch.setattr(editor_jobs, '_item_source', lambda *_: ({}, shot, {}, source))
    monkeypatch.setattr(editor_jobs, '_remove_restoration_audio', lambda *_: None)
    monkeypatch.setattr(editor_jobs, '_vista_asks', lambda: (None, None))
    monkeypatch.setattr(production, 'probe', lambda _: {'width': 160})
    monkeypatch.setattr(manga, 'GpuPerLaVista', lambda *_: nullcontext())
    calls = []
    async def remaster(*_):
        calls.append('video')
        return {'path': str(video), 'take': 'restored'}
    async def prepare(*_):
        calls.append('text')
        R.save_state(tmp_path, 'shot', {'source_language': 'en', 'cards': [{'text': 'Hello', 'start': 0, 'end': 2}]})
        return {'cards': 1}
    async def translate(*_):
        state = R.load_state(tmp_path, 'shot')
        return {'translation_path': str(sub), 'source_sha256': text.state_fingerprint(state),
                'translation_sha256': text.translation_fingerprint(state, 'en')}
    async def voice(*_):
        return {'subtitle': str(sub), 'unclear': []}
    def export(*values):
        calls.append('export')
        values[3].write_bytes(b'final')
        return {'output_path': str(values[3])}
    def publish(video, directory, *_):
        calls.append('publication')
        if calls.count('publication') == 1:
            raise ValueError('Modello temporaneamente non disponibile')
        directory.mkdir(parents=True)
        manifest = directory / 'youtube_package.json'
        manifest.write_text(json.dumps({'video': str(video), 'thumbnail': str(clip), 'captions': {'en': str(sub)},
                                        'audio_tracks': {'en': str(clip)}, 'text_files': {'en': {'title': str(sub), 'description': str(sub)}},
                                        'validation': {'complete': True}, 'identity': {'title': 'Film'}}))
        (directory / 'pacchetto_youtube.md').write_text('Pacchetto')
        return {'package_path': str(manifest), 'publication_ready': True}
    monkeypatch.setattr(editor_jobs, 'job_remaster', remaster)
    monkeypatch.setattr(text, 'prepare_text', prepare)
    monkeypatch.setattr(text, 'translate_job', translate)
    monkeypatch.setattr(editor_jobs, 'job_restore_narrate', voice)
    monkeypatch.setattr(audio_export, 'export_multilingual', export)
    monkeypatch.setattr(P, 'create_package', publish)
    job = {'production': 'prod', 'id': 'job', 'args': args}
    with pytest.raises(ValueError, match='temporaneamente'):
        asyncio.run(pipe.run(editor, job))
    result = asyncio.run(pipe.run(editor, {**job, 'id': 'retry', 'operation_id': 'job'}))
    assert result['publication_ready'] is True
    assert calls == ['video', 'text', 'export', 'publication', 'publication']
    assert all(stage['reused'] for stage in result['stages'][:-1])
