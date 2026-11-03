"""Il pacchetto editoriale non richiede otto tracce audio né può nascondere errori."""
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from PIL import Image

from core.modules.sigma_creative_lab.video import generated_publication as P


def test_pacchetto_otto_lingue_e_miniatura_senza_doppiaggi(tmp_path, monkeypatch):
    video = tmp_path / 'master.mp4'
    video.write_bytes(b'master')
    prod = {'id': 'test', 'title': 'Studio attivo', 'output_path': str(video), 'audio_project': {'mode': 'varied'}}
    monkeypatch.setattr(P, 'media_info', lambda _: {'format': {'duration': '1800'}})
    def thumbnail(video, target, *args, **kwargs):
        assert kwargs['edition'] == 'AI MUSIC VIDEO'
        Image.new('RGB', (1280, 720), 'blue').save(target)
    monkeypatch.setattr(P, '_thumbnail', thumbnail)
    def ask(prompt, tokens):
        if prompt.startswith('Write'):
            return json.dumps({'title': 'Study music', 'description': 'Instrumental music with AI-generated visuals and reused clips.'})
        if 'العربية' in prompt:
            return json.dumps({'title': 'موسيقى', 'description': 'موسيقى للدراسة'})
        if '中文' in prompt:
            return json.dumps({'title': '学习音乐', 'description': '学习背景音乐'})
        return json.dumps({'title': 'Titolo tradotto', 'description': 'Descrizione tradotta.'})
    directory = tmp_path / 'publication'
    result = P.create_package(prod, directory, ask)
    assert result['publication_ready'] and result['languages'] == list(P.LANGUAGES)
    manifest = json.loads(Path(result['package_path']).read_text())
    assert set(manifest['localizations']) == {'ar', 'en', 'it', 'es', 'de', 'fr', 'pt-BR', 'zh-Hans'}
    assert 'audio_tracks' not in manifest
    with zipfile.ZipFile(result['bundle_path']) as archive:
        assert len(archive.namelist()) == 18
        for locale, files in manifest['text_files'].items():
            for key, name in files.items():
                assert archive.read(name).decode().strip() == manifest['localizations'][locale][key]
    old = result['source']
    video.write_bytes(b'new master')
    assert P.source_identity(prod, video) != old


def test_errore_traduzione_non_promuove_pacchetto_e_conserva_master(tmp_path, monkeypatch):
    video = tmp_path / 'master.mp4'
    video.write_bytes(b'master')
    prod = {'id': 'test', 'title': 'Video', 'output_path': str(video), 'status': 'done',
            'publication': {'publication_ready': True}}
    saves = []
    store = SimpleNamespace(path=lambda _: tmp_path, save=lambda p: saves.append(dict(p)), get=lambda _: prod)
    def fail(*args):
        raise ValueError('Traduzione incompleta')
    monkeypatch.setattr(P, 'create_package', fail)
    result = P.prepare(store, prod, ask_text=lambda *_: '')
    assert result['status'] == 'failed' and not result['publication_ready']
    assert prod['status'] == 'done' and video.read_bytes() == b'master'
    assert saves[0]['publication']['status'] == 'preparing'


def test_cache_non_riusa_titolo_di_altro_video(tmp_path):
    video = tmp_path / 'master.mp4'
    video.write_bytes(b'master')
    prod = {'title': 'Primo', 'output_path': str(video)}
    first = P.source_identity(prod, video)
    assert P.source_identity({**prod, 'title': 'Secondo'}, video) != first


def test_export_editor_prepara_materiali_dopo_master(tmp_path, monkeypatch):
    import asyncio
    from core import paths
    from core.modules.sigma_creative_lab.video import editor_jobs, export
    prod = {'id': 'video_test', 'title': 'Studio', 'settings': {}, 'output_path': ''}
    calls = []
    def render(tl, prod, out, *args):
        Path(out).write_bytes(b'master pronto')
    def prepare(store, prod):
        assert Path(prod['output_path']).read_bytes() == b'master pronto'
        calls.append(prod['output_path'])
        return {'publication_ready': True}
    monkeypatch.setattr(paths, 'creative_output_dir', lambda _: tmp_path)
    monkeypatch.setattr(export, 'export_timeline', render)
    monkeypatch.setattr(P, 'prepare', prepare)
    editor = SimpleNamespace(prods=SimpleNamespace(get=lambda _: prod, save=lambda _: None),
                             timelines=SimpleNamespace(get=lambda _: {}), _note=lambda *_: None)
    result = asyncio.run(editor_jobs.job_export(editor, {'production': 'video_test'}))
    assert result['publication']['publication_ready'] and calls == [result['output_path']]


def test_modifica_durante_traduzione_conserva_titolo_nuovo(tmp_path, monkeypatch):
    video = tmp_path / 'master.mp4'
    video.write_bytes(b'master')
    prod = {'id': 'video_test', 'title': 'Titolo iniziale', 'output_path': str(video)}
    current = {**prod, 'title': 'Titolo corretto'}
    saved = []
    store = SimpleNamespace(path=lambda _: tmp_path, save=lambda p: saved.append(dict(p)), get=lambda _: current)
    monkeypatch.setattr(P, 'create_package', lambda p, *args: {
        'publication_ready': True, 'source': P.source_identity(p, p['output_path'])})
    result = P.prepare(store, prod, ask_text=lambda *_: '')
    assert result['status'] == 'stale' and not result['publication_ready']
    assert saved[-1]['title'] == 'Titolo corretto'
