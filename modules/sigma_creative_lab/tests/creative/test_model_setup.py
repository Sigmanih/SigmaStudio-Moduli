"""Le ricette dipendono dai pesi, non dal nome dato al download."""
import json
import pytest

from core.modules.sigma_creative_lab.model_setup import recognize, scan_models
from core.modules.sigma_creative_lab import model_registry as registry
from core.modules.sigma_creative_lab.model_router import ModelRouter
from core.modules.sigma_creative_lab.generators.adapters.comfyui_adapter import ComfyUIAdapter


def tensor(shape):
    return {'dtype': 'F16', 'shape': shape, 'data_offsets': [0, 8]}


def weights(path, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(header).encode()
    path.write_bytes(len(payload).to_bytes(8, 'little') + payload + bytes(8))


def sdxl():
    return {'model.diffusion_model.input_blocks.0.0.weight': tensor([320, 4, 3, 3]),
            'model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight': tensor([640, 2048]),
            'conditioner.embedders.0.transformer.weight': tensor([1]),
            'first_stage_model.decoder.conv_out.weight': tensor([3, 128, 3, 3])}


def flux2():
    return {'double_stream_modulation_img.lin.weight': tensor([18432, 3072]),
            'img_in.weight': tensor([3072, 128]), 'txt_in.weight': tensor([3072, 7680])}


def test_checkpoint_rinominato_diventa_un_modello_pronto_senza_profilo(tmp_path, monkeypatch):
    weights(tmp_path / 'checkpoints/sub/il_mio_modello.safetensors', sdxl())
    records = scan_models(tmp_path)
    assert len(records) == 1 and records[0]['configured']
    monkeypatch.setattr(registry, '_LOCAL_MODELS', records)
    monkeypatch.setattr(registry, '_COMFY_INVENTORY', {'checkpoints': ['sub/il_mio_modello.safetensors']})
    monkeypatch.setattr(registry, 'available_vram_gb', lambda: 8)
    spec = registry.get_model(records[0]['id'])
    params = ModelRouter({}).apply_model({'prompt': 'Un gatto'}, spec, 'comfyui')
    assert params['ckpt'] == 'sub/il_mio_modello.safetensors'
    assert params['workflow'] == 'sdxl_txt2img'
    assert next(x for x in registry.catalog({'comfyui'}) if x['id'] == spec.id)['available']
    offline = next(x for x in registry.catalog(set()) if x['id'] == spec.id)
    assert offline['configured'] and not offline['available']
    assert 'Motore spento' in offline['setup_message']


def test_nome_sdxl_non_rende_compatibile_un_file_sconosciuto(tmp_path):
    weights(tmp_path / 'checkpoints/sdxl.safetensors', {'unrelated': tensor([4])})
    record = scan_models(tmp_path)[0]
    assert not record['configured'] and not record['workflow']


def test_flux2_non_viene_instradato_su_flux1_e_richiede_i_componenti_giusti(tmp_path):
    header = {**flux2(), 'double_blocks.0.img_attn.qkv.weight': tensor([9216, 3072])}
    assert recognize(header) == 'flux2-klein-4b'
    weights(tmp_path / 'diffusion_models/flux-2-klein-4b-fp8.safetensors', header)
    record = scan_models(tmp_path)[0]
    assert not record['configured'] and any('qwen_3_4b' in s for s in record['issues'])
    weights(tmp_path / 'text_encoders/qwen_3_4b_fp8_mixed.safetensors', {})
    weights(tmp_path / 'vae/flux2-vae.safetensors', {})
    record = next(r for r in scan_models(tmp_path) if r['kind'] == 'diffusion')
    assert record['configured'] and record['parameters']['steps'] == 4
    graph, ckpt = ComfyUIAdapter()._resolve('text_to_image', {**record['parameters'], 'workflow': record['workflow'], 'prompt': 'Un gatto'})
    assert graph['2']['inputs']['type'] == 'flux2'
    assert graph['2']['inputs']['clip_name'] == 'qwen_3_4b_fp8_mixed.safetensors'
    assert graph['6']['class_type'] == 'EmptyFlux2LatentImage'
    assert graph['9']['class_type'] == 'Flux2Scheduler'
    assert graph['3']['inputs']['vae_name'] == 'flux2-vae.safetensors'


def test_lora_e_download_parziale_non_diventano_generatori(tmp_path):
    weights(tmp_path / 'loras/style.safetensors', sdxl())
    weights(tmp_path / 'checkpoints/incomplete.safetensors.part', sdxl())
    records = scan_models(tmp_path)
    assert len(records) == 1 and not records[0]['workflow']
    assert 'Adattatore' in records[0]['tags']


@pytest.mark.parametrize('header', [{'model.diffusion_model.input_blocks.0.0.weight': []}, {'img_in.weight': None}, {}])
def test_header_non_compatibile_non_interrompe_il_catalogo(header):
    assert recognize(header) == ''


def test_download_completato_invalida_la_classificazione(tmp_path):
    path = tmp_path / 'checkpoints/model.safetensors'
    weights(path, {})
    assert not scan_models(tmp_path)[0]['configured']
    weights(path, sdxl())
    assert scan_models(tmp_path)[0]['configured']


def test_agente_scopre_i_modelli_senza_aprire_la_pagina(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from core.modules.sigma_creative_lab import model_downloader
    weights(tmp_path / 'checkpoints/nuovo.safetensors', sdxl())
    monkeypatch.setattr(registry, '_LOCAL_MODELS', [])
    monkeypatch.setattr(registry, '_COMFY_INVENTORY', None)
    monkeypatch.setattr(model_downloader, 'discover_models_root', lambda **kwargs: str(tmp_path))
    router = ModelRouter({})
    monkeypatch.setattr(router, 'get_available_backends', AsyncMock(return_value=[]))
    monkeypatch.setattr(router, '_ollama_available', AsyncMock(return_value=False))
    asyncio.run(router.available_backend_names())
    assert any(model.filename == 'nuovo.safetensors' for model in registry.all_models())
