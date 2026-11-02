"""Regressioni: identità della sigla, durate e completezza dei materiali YouTube."""
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from core.store import JsonStore
from core.modules.sigma_creative_lab.video import publication_checks as checks, publishing
from core.modules.sigma_creative_lab.video.publication_identity import title_overlay, validate_template, verify_title_frame


def test_template_modificato_richiede_nuova_verifica(tmp_path):
    for kind in ('intro', 'outro'):
        (tmp_path / f'{kind}.mp4').write_bytes(kind.encode())
    JsonStore(tmp_path / 'sigla_template.json').save({'layout': 'sigma-logo-title-v1',
        **{kind + '_sha256': hashlib.sha256((tmp_path / f'{kind}.mp4').read_bytes()).hexdigest() for kind in ('intro', 'outro')}})
    validate_template(tmp_path)
    (tmp_path / 'intro.mp4').write_bytes(b'un altro film')
    with pytest.raises(ValueError, match='cambiato'):
        validate_template(tmp_path)


@pytest.mark.parametrize('wrong_title,wrong_year', [('FRANKENSTEIN', '1910'), ('THE GENERAL', '1910')])
def test_sigla_di_altro_film_non_supera_la_verifica_visiva(tmp_path, wrong_title, wrong_year):
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
    wrong = title_overlay(640, 480, wrong_title, wrong_year, tmp_path / 'wrong.png')
    expected = title_overlay(640, 480, 'THE GENERAL', '1926', tmp_path / 'expected.png')
    video = tmp_path / 'intro.mp4'
    _run([ffmpeg_bin(), '-v', 'error', '-y', '-loop', '1', '-i', str(wrong), '-t', '1',
          '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', str(video)], 30)
    verify_title_frame(video, wrong, .5, tmp_path / 'correct.png')
    with pytest.raises(ValueError, match='non coincide'):
        verify_title_frame(video, expected, .5, tmp_path / 'incorrect.png')


@pytest.fixture
def package(tmp_path, monkeypatch):
    Image.new('RGB', (1280, 720), 'navy').save(tmp_path / 'miniatura.jpg')
    (tmp_path / 'en.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n')
    (tmp_path / 'title.txt').write_text('The General')
    (tmp_path / 'description.txt').write_text('Description')
    def info(path):
        return {'format': {'duration': 10}, 'streams': [
            {'codec_type': 'video', 'duration': 10, 'width': 640, 'height': 480},
            {'codec_type': 'audio', 'duration': 10}]}
    monkeypatch.setattr(publishing, 'media_info', info)
    value = {'video': 'master.mp4', 'thumbnail': 'miniatura.jpg', 'audio_tracks': {'en': 'audio.m4a'},
             'captions': {'en': 'en.srt'}, 'localizations': {'en': {'title': 'The General', 'description': 'Description'}},
             'text_files': {'en': {'title': 'title.txt', 'description': 'description.txt'}}}
    return value, tmp_path


def test_pacchetto_completo_verificato(package):
    value, directory = package
    assert checks.validate_package(value, directory)['complete'] is True


def test_audio_precedente_senza_sigla_blocca_pacchetto(package, monkeypatch):
    value, directory = package
    original = publishing.media_info
    def info(path):
        result = original(path)
        if Path(path).suffix == '.m4a':
            result['format']['duration'] = 1
        return result
    monkeypatch.setattr(publishing, 'media_info', info)
    with pytest.raises(ValueError, match='durata diversa'):
        checks.validate_package(value, directory)


def test_miniatura_mancante_blocca_pacchetto(package):
    value, directory = package
    (directory / 'miniatura.jpg').unlink()
    with pytest.raises(ValueError, match='Miniatura mancante'):
        checks.validate_package(value, directory)


def test_lingua_senza_titolo_blocca_pacchetto(package):
    value, directory = package
    value['text_files'] = {}
    with pytest.raises(ValueError, match='Lingue incoerenti'):
        checks.validate_package(value, directory)


def test_sottotitolo_oltre_il_video_blocca_pacchetto(package):
    value, directory = package
    (directory / 'en.srt').write_text('1\n00:00:01,000 --> 00:00:20,000\nHello\n')
    with pytest.raises(ValueError, match='fuori dalla durata'):
        checks.validate_package(value, directory)
