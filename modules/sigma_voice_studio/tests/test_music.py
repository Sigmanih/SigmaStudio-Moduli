"""Contratti di AudioStudio e cancellazione del solo prompt posseduto."""
import asyncio
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from core.job_worker import JobCancelled
from core.modules.sigma_voice_studio import music


@pytest.mark.parametrize('genre', ['lofi_study', 'deep_focus', 'neoclassical', 'cyber_ambient'])
def test_presets_studio_hanno_ricetta_e_tema_visivo(genre):
    value = music.normalize({'genre': genre, 'seed': 42})
    assert value['duration'] == 120
    assert 40 <= value['bpm'] <= 140
    assert music.BY_ID[genre]['visual']
    assert music.BY_ID[genre]['tags']


@pytest.mark.parametrize('data', [None, {'genre': 'rock'}, {'duration': True}, {'duration': 0}, {'duration': 121},
                               {'seed': -1}, {'seed': '42'}, {'bpm': 400}, {'prompt': 'x' * 1201}])
def test_opzioni_errate_non_avviano_la_gpu(data):
    with pytest.raises(ValueError):
        music.normalize(data)


def test_seed_zero_rimane_riproducibile():
    assert music.normalize({'seed': 0})['seed'] == 0


def test_annullamento_interrompe_solo_il_prompt_corrente():
    event = threading.Event()
    cancelled = []
    async def submit(_):
        event.set()
        return 'nostro-prompt'
    async def cancel(prompt):
        cancelled.append(prompt)
    engine = SimpleNamespace(submit=submit, cancel_job=cancel)
    with pytest.raises(JobCancelled):
        asyncio.run(music.CheckedBackend(engine, {'cancel_event': event}).run({}))
    assert cancelled == ['nostro-prompt']


def test_errore_motore_non_diventa_successo():
    async def submit(_):
        return 'nostro-prompt'
    async def get_status(_):
        return SimpleNamespace(status='error', error='Memoria insufficiente')
    async def cancel(_):
        return True
    engine = SimpleNamespace(submit=submit, get_job_status=get_status, cancel_job=cancel)
    with pytest.raises(RuntimeError, match='Memoria insufficiente'):
        asyncio.run(music.CheckedBackend(engine, {'cancel_event': threading.Event()}).run({}))


def test_audio_reale_finitura_manifest_e_url(tmp_path, monkeypatch):
    from core.modules.sigma_creative_lab.video import soundtrack, production
    captured = []
    async def fake_engine():
        async def queue():
            return {'running_count': 0, 'pending_count': 0}
        return SimpleNamespace(get_queue=queue)
    async def generate(prod, directory, backend, progress):
        captured.append(prod)
        directory.mkdir(parents=True)
        target = directory / 'soundtrack.wav'
        production._run([production.ffmpeg_bin(), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         'anoisesrc=duration=120:sample_rate=48000:amplitude=0.2:seed=42', str(target)], 30)
        return target
    monkeypatch.setattr(music, 'check_engine', fake_engine)
    monkeypatch.setattr(soundtrack, 'generate_soundtrack', generate)
    monkeypatch.setattr(music.paths, 'works_area', lambda _: tmp_path)
    monkeypatch.setattr(music.paths, 'public_url', lambda p: '/works/' + Path(p).relative_to(tmp_path).as_posix())
    job = {'args': music.normalize({'genre': 'lofi_study', 'seed': 42}), 'id': 'test', 'cancel_event': threading.Event()}
    result = asyncio.run(music.compose(None, job))
    assert result['duration'] == 120
    assert result['quality']['ok'] is True
    assert Path(result['wav']).is_file() and Path(result['mp3']).is_file()
    assert result['mp3_url'].startswith('/works/lofi_study/test/')
    manifest = Path(result['wav']).parent / 'composition.json'
    assert json.loads(manifest.read_text())['recipe']['seed'] == 42
    assert 'no vocals' in captured[0]['soundtrack']['tags']
    assert 'subtle' in captured[0]['soundtrack']['development']


def test_motore_esterno_occupato_non_accoda_un_secondo_prompt(tmp_path, monkeypatch):
    async def check():
        async def queue():
            return {'running_count': 1, 'pending_count': 0}
        return SimpleNamespace(get_queue=queue)
    monkeypatch.setattr(music, 'check_engine', check)
    job = {'args': music.normalize({'seed': 42}), 'id': 'test', 'cancel_event': threading.Event()}
    with pytest.raises(RuntimeError, match='occupato'):
        asyncio.run(music.compose(None, job))
    assert not list(tmp_path.iterdir())
