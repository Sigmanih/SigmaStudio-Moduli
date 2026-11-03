"""Un voto positivo del modello non autorizza da solo la consegna di una clip."""
import json
import pytest
from core.modules.sigma_creative_lab.video import visual_integrity as V
from core.modules.sigma_creative_lab.video.production import ProductionStore, new_shot
from core.modules.sigma_creative_lab.video.clip_judge import verdict_from


def test_anatomia_errata_blocca_anche_con_qualita_alta():
    result=verdict_from({'main_action_happens':True,'anatomy_ok':False,'quality':1,
                         'wrong_direction':False,'physically_impossible':False},.6)
    assert result['severe'] and not result['ok']


@pytest.mark.parametrize('raw',[{}, {'status':'pass'}, {'status':'unknown','issues':[],'observations':'x'}])
def test_risposta_incompleta_non_promuove(raw):
    with pytest.raises(ValueError): V.parse(json.dumps(raw))


def test_difetti_espliciti_prevalgono_sul_pass():
    r=V.parse(json.dumps({'status':'pass','visible_arms':3,'visible_hands':3,'observations':'Tre mani','issues':['Braccio aggiuntivo']}))
    assert r['status']=='fail'


def test_falso_positivo_reale_del_modello_non_basta_a_consegnare(tmp_path):
    source=tmp_path/'clip.mp4'; source.write_bytes(b'clip')
    shot=new_shot('Study',clip_path=str(source))
    # Il modello locale ha contato due mani nel fotogramma che ne mostrava tre.
    shot['visual_integrity']={'status':'pass','version':V.VERSION,'sha256':V.fingerprint(source),
                              'frames':[{'visible_hands':2,'observations':'Both hands correct'}]}
    with pytest.raises(ValueError,match='revisione di dettaglio'): V.require(shot)


def test_revisione_anatomica_non_riusa_identita_vecchia(tmp_path):
    source=tmp_path/'clip.mp4';source.write_bytes(b'clip')
    store=ProductionStore(tmp_path/'productions')
    sh=new_shot('Study',clip_path=str(source),judge={'ok':True})
    digest=V.fingerprint(source)
    sh['visual_integrity']={'status':'pass','sha256':digest,'version':V.VERSION}
    p=store.create('Studio',shots=[sh]); reason='Verificate anatomia, mani e contatti con il libro nella clip completa.'
    with pytest.raises(ValueError):V.review(store,p['id'],sh['id'],'approve',reason,digest,['hands'])
    p=V.review(store,p['id'],sh['id'],'approve',reason,digest,['anatomy','hands','objects','continuity'])
    V.require(p['shots'][0])
    source.write_bytes(b'clip cambiata')
    with pytest.raises(ValueError):V.require(p['shots'][0])


def test_rifiuto_esplicito_invalida_materiali_e_stato(tmp_path):
    source=tmp_path/'clip.mp4';source.write_bytes(b'clip')
    store=ProductionStore(tmp_path/'productions');sh=new_shot('Study',clip_path=str(source),status='done')
    p=store.create('Studio',shots=[sh]);p['publication']={'publication_ready':True};store.save(p)
    p=V.review(store,p['id'],sh['id'],'reject','Sono visibili tre mani e due penne con un braccio duplicato.',V.fingerprint(source),[])
    assert p['shots'][0]['status']=='failed' and not p['publication']['publication_ready']


def test_fotogramma_respinto_non_diventa_migliore_da_tenere(tmp_path,monkeypatch):
    import asyncio
    from core.modules.sigma_creative_lab.video import production as P,genres,image_gen
    store=ProductionStore(tmp_path/'prods'); p=store.create('Studio',shots=[new_shot('Una persona legge')])
    async def generate(model,prompt,out,**kwargs):
        out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(b'immagine difettosa')
        return {'path':str(out),'seed':kwargs['seed']}
    async def check(*args):return {'ok':False,'score':.9,'issues':['Tre mani'],'fix':'Two connected arms'}
    monkeypatch.setattr(genres,'keyframe_plan',lambda *args:('test','prompt',[]))
    monkeypatch.setattr(image_gen,'generate',generate)
    monkeypatch.setattr(P,'_check_keyframe',check)
    with pytest.raises(ValueError,match='Fotogramma respinto'):asyncio.run(P.generate_keyframes(store,p['id']))
    assert not store.get(p['id'])['shots'][0].get('keyframe')


def test_difetto_tecnico_non_viene_tenuto_dopo_ultimo_tentativo(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from core.modules.sigma_creative_lab.video import production as P,postprocess
    runner=object.__new__(P.ProductionRunner)
    monkeypatch.setattr(postprocess,'quality_check',lambda *args:['fotogrammi neri'])
    sh={'id':'shot','clip_path':str(tmp_path/'clip.mp4'),'attempts':3}
    assert not asyncio.run(runner._technical_check({'settings':{'qa':False,'max_attempts':3},'shots':[sh]},0))
    assert sh['status']=='failed'


def test_nessuna_clip_approvata_non_avvia_upscale_o_montaggio(monkeypatch):
    from core.modules.sigma_creative_lab.video import production as P
    runner=object.__new__(P.ProductionRunner)
    monkeypatch.setattr(runner,'_upscale_all',lambda _:pytest.fail('Non deve caricare modelli'))
    with pytest.raises(ValueError,match='Nessuna clip approvata'):
        runner.assemble({'shots':[{'id':'clip','status':'review_required'}]})


def test_controllo_automatico_positivo_non_emette_clip_pronta(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from core.modules.sigma_creative_lab.video import production as P
    source=tmp_path/'clip.mp4';source.write_bytes(b'clip')
    sh={'id':'shot','clip_path':str(source),'attempts':1}
    runner=object.__new__(P.ProductionRunner);events=[]
    runner.store=SimpleNamespace(path=lambda _:tmp_path)
    monkeypatch.setattr(runner,'_emit',lambda **event:events.append(event))
    monkeypatch.setattr(P,'extract_last_frame',lambda _:None)
    monkeypatch.setattr(P,'resolve_judge_device',lambda _:'cpu')
    monkeypatch.setattr(V,'inspect_clip',lambda *args:{'status':'pass','version':V.VERSION,'sha256':V.fingerprint(source)})
    asyncio.run(runner._finish({'id':'prod_test','settings':{},'shots':[sh]},0,{'label':'CPU'}))
    assert sh['status']=='review_required'
    assert events[-1]['type']=='shot_review_required' and all(e['type']!='shot_done' for e in events)
