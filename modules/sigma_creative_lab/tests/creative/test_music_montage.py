"""Montaggi variati e rifiuto delle azioni non verificate."""
import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from core.modules.sigma_creative_lab.video import music_montage as montage,production,timeline


@pytest.mark.parametrize('activity',['study','workout'])
def test_piano_contiene_azioni_distinte_e_movimento_esplicito(activity):
    shots=montage.action_shots('Original adult anime character in a coherent room',activity)
    assert len(shots)==8
    assert len({s['required_action'] for s in shots})==8
    assert all(production.ltx_action(s)==s['prompt'] for s in shots)
    assert all('clearly visible' in s['prompt'] for s in shots)
    assert all('start_frame_prompt' in s for s in shots)
    assert all('no sequence of poses' in s['start_frame_prompt'] for s in shots)
    schedule=montage.plan(shots,1800,123)
    assert schedule==montage.plan(shots,1800,123)
    assert sum(item['duration'] for item in schedule)==1800
    assert len(schedule)==225
    assert all(a['shot_id']!=b['shot_id'] for a,b in zip(schedule,schedule[1:]))
    assert {item['shot_id'] for item in schedule}=={s['id'] for s in shots}
    assert len({tuple(x['shot_id'] for x in schedule[i:i+3]) for i in range(len(schedule)-2)})>150


def test_timeline_rispecchia_montaggio_vario(tmp_path):
    shots=montage.action_shots('Scene','study')
    for s in shots:s.update(status='done',frames=192,clip_path=str(tmp_path/(s['id']+'.mp4')))
    prod={'shots':shots,'settings':{'seed':42},'audio_project':{'mode':'varied','mix':{'duration':120}}}
    result=timeline.build_from_shots(prod)
    expected=montage.plan(shots,120,42)
    assert [s['shot_id'] for s in result['video']]==[s['shot_id'] for s in expected]
    assert timeline.layout(result,prod)['duration']==120
    assert result['music_plan_ready']


@pytest.mark.parametrize('verdict',[None,{'ok':False,'score':.1,'issues':['azione assente'],'seen':'personaggio immobile'}])
def test_clip_statica_o_non_verificata_non_viene_accettata(tmp_path,monkeypatch,verdict):
    runner=object.__new__(production.ProductionRunner)
    runner.cancelled=threading.Event();runner._wake=None
    runner.store=SimpleNamespace(save=lambda _:None)
    runner.on_event=None;runner.pid='test';runner.message=''
    async def judge(*args):return verdict
    async def finish(*args):pytest.fail('Una clip non verificata non deve essere completata')
    monkeypatch.setattr(production,'judge_clip',judge)
    monkeypatch.setattr(production,'_judge_retries',lambda *args:False)
    monkeypatch.setattr(runner,'_finish',finish)
    shot={'id':'shot','prompt':'Squats','required_action':'Squat','attempts':3,'clip_path':str(tmp_path/'clip.mp4')}
    asyncio.run(runner._review({'settings':{'max_attempts':3},'shots':[shot]},0,{}))
    assert shot['status']=='failed'


def test_montaggio_reale_non_congela_il_ultimo_fotogramma(tmp_path,monkeypatch):
    from core.modules.sigma_creative_lab.video import postprocess
    monkeypatch.setattr(postprocess,'video_encoder_args',lambda *args:['-c:v','libx264','-preset','ultrafast'])
    shots=[]
    for index,color in enumerate(('red','blue','green','yellow')):
        source=tmp_path/(str(index)+'.mp4')
        production._run([production.ffmpeg_bin(),'-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=160x96:r=24',
                         '-t','0.5','-c:v','libx264',str(source)],30)
        shots.append({'id':str(index),'clip_path':str(source),'status':'done','duration_s':.5,'required_action':color})
    prod={'shots':shots,'settings':{'seed':5},'audio_project':{'mode':'varied','mix':{'duration':3}}}
    out=montage.assemble(prod,tmp_path/'out.mp4',tmp_path/'work')
    assert production.probe(out)['duration']==pytest.approx(3,abs=.05)
    from core.store import JsonStore
    saved=JsonStore(tmp_path/'work'/'montage_plan.json',default={}).load()
    assert len(saved['items'])==6


def test_fotogramma_iniziale_usa_la_posa_non_la_sequenza_di_movimenti(tmp_path,monkeypatch):
    from core.modules.sigma_creative_lab.video import genres,image_gen
    store=production.ProductionStore(tmp_path/'prods')
    shot=montage.action_shots('Adult athlete in an empty gym','workout')[1]
    prod=store.create('Squat',shots=[shot])
    captured=[]
    monkeypatch.setattr(genres,'keyframe_plan',lambda p,s:('test',s['prompt'],[]))
    async def generate(model,prompt,out,**kwargs):
        captured.append(prompt);out.parent.mkdir(parents=True,exist_ok=True);out.touch()
        return {'path':str(out),'seed':kwargs['seed']}
    async def check(*args):return {'ok':True,'score':1}
    monkeypatch.setattr(image_gen,'generate',generate)
    monkeypatch.setattr(production,'_check_keyframe',check)
    asyncio.run(production.generate_keyframes(store,prod['id']))
    assert captured==[shot['start_frame_prompt']]
    assert 'standing upright' in captured[0]
    assert store.get(prod['id'])['shots'][0]['prompt']==shot['prompt']


def test_esercizi_sul_posto_non_ricevono_vincoli_di_camminare():
    shot=montage.action_shots('Adult athlete in gym','workout')[2]
    prompt=production.compose_prompt({'settings':{'video_model':'ltx25'},'bible':{}},shot,False)
    assert 'joint and hand motion' in prompt
    assert 'people move forward' not in prompt


def test_campionamento_non_blocca_sempre_la_stessa_fase_di_movimenti_periodici(tmp_path,monkeypatch):
    from core.modules.sigma_creative_lab.video import clip_judge
    times=[]
    monkeypatch.setattr(production,'probe',lambda _: {'duration':8})
    monkeypatch.setattr(production,'ffmpeg_bin',lambda:'ffmpeg')
    monkeypatch.setattr(production,'_run',lambda command,**kwargs:times.append(float(command[command.index('-ss')+1])))
    frames,span=clip_judge.sample_frames(tmp_path/'clip.mp4',tmp_path,n=8)
    assert len(frames)==8 and span==8
    assert times==sorted(times) and 0<min(times)<max(times)<8
    assert len({round(t%1,2) for t in times})>4


def test_ricontrollo_usa_la_clip_esistente_senza_render_ne_nuovo_tentativo(tmp_path,monkeypatch):
    source=tmp_path/'clip.mp4';source.touch()
    runner=object.__new__(production.ProductionRunner)
    runner.store=SimpleNamespace(save=lambda _:None)
    monkeypatch.setattr(runner,'_judge_enabled',lambda _:True)
    async def technical(*args):return True
    async def review(prod,i,lane):prod['shots'][i]['status']='done'
    monkeypatch.setattr(runner,'_technical_check',technical)
    monkeypatch.setattr(runner,'_review',review)
    shot={'id':'one','status':'pending','clip_path':str(source),'review_existing':True,'attempts':2}
    asyncio.run(runner._render_one({'shots':[shot]},0,{}))
    assert shot['status']=='done' and shot['attempts']==2
    assert 'review_existing' not in shot


def test_revisione_visiva_esplicita_conserva_dissenso_ai_e_identita_clip(tmp_path):
    from core.modules.sigma_creative_lab.video import manual_review
    source=tmp_path/'clip.mp4'
    production._run([production.ffmpeg_bin(),'-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x96:r=24',
                    '-t','0.5','-c:v','libx264',str(source)],30)
    store=production.ProductionStore(tmp_path/'prods')
    shot=production.new_shot('Punches',duration_s=.5,status='failed',clip_path=str(source),judge={'ok':False,'score':0})
    prod=store.create('Revisione',shots=[shot])
    with pytest.raises(ValueError):manual_review.accept(store,prod['id'],shot['id'],'ok')
    from core.modules.sigma_creative_lab.video.visual_integrity import VERSION
    digest=manual_review.fingerprint(source)
    shot['visual_integrity']={'status':'pass','sha256':digest,'version':VERSION}
    shot['integrity_review']={'verdict':'approve','sha256':digest}
    store.save(prod)
    accepted=manual_review.accept(store,prod['id'],shot['id'],'Verificata l’estensione delle braccia su tutti i fotogrammi.','agent_visual_review')
    item=accepted['shots'][0]
    assert item['status']=='done' and item['judge']['ok'] is False
    assert item['manual_review']['reviewer']=='agent_visual_review'
    assert manual_review.valid(item)
    with source.open('ab') as stream:stream.write(b'changed')
    assert not manual_review.valid(item)


@pytest.mark.parametrize('body',[{'id':'test','confirmed':False},None,[]])
def test_approvazione_senza_conferma_di_visione_e_rifiutata(monkeypatch,body):
    from core.modules.sigma_creative_lab.video import production_routes as routes
    answers=[]
    monkeypatch.setattr(routes,'manager',SimpleNamespace(active=lambda:None))
    handler=SimpleNamespace(read_json_body=lambda:body,
                            send_json_response=lambda body,status=200:answers.append((body,status)))
    routes.handle_production_manual_review(handler)
    assert answers[-1][1]==400 and not answers[-1][0]['success']
