"""Montaggio audio reale e trasferimento della colonna sonora approvata."""
import asyncio
import copy
import math
from pathlib import Path
import struct
import threading
from types import SimpleNamespace
import wave

import pytest

from core.modules.sigma_voice_studio import audio_editor as editor
from core.modules.sigma_creative_lab.video import production


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(editor, 'root', lambda: tmp_path / 'projects')
    monkeypatch.setattr(editor.paths, 'public_url', lambda p: '/test/' + Path(p).name)
    return tmp_path


def tone(path, seconds=1, frequency=220):
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        out.writeframes(b''.join(struct.pack('<h', int(5000*math.sin(i*frequency*2*math.pi/48000))) for i in range(round(seconds*48000))))
    return path


def project_with_audio(workspace):
    project=editor.create(None,None,'Progetto di prova')
    source=tone(workspace/'originale.wav')
    editor.add_clip(project,source,'Pianoforte')
    editor.save(project)
    return project,source


def test_forma_onda_e_sorgente_conservata(workspace):
    project,source=project_with_audio(workspace)
    clip=project['clips'][0]
    assert 1 <= len(clip['peaks']) <= 800
    assert max(clip['peaks']) > .1
    assert Path(clip['src']).read_bytes()==source.read_bytes()
    assert Path(clip['src'])!=source
    assert editor.load(project['id'])['title']=='Progetto di prova'


def test_creazione_ripetuta_non_duplica_progetto(workspace):
    first=editor.create(None,None,'Titolo',request_id='a'*32)
    second=editor.create(None,None,'Titolo',request_id='a'*32)
    assert first['id']==second['id']
    assert len(editor.listing())==1


def test_taglio_split_mix_reale_e_undo(workspace):
    project,source=project_with_audio(workspace)
    original=source.read_bytes()
    clip=project['clips'][0]['id']
    project=editor.edit(project['id'],1,'update',{'clip_id':clip,'start':.2,'in':.1,'out':.9,'gain':-4,'pan':.3,'fade_in':.1,'fade_out':.1})
    project=editor.edit(project['id'],2,'split',{'clip_id':clip,'at':.6})
    assert len(project['clips'])==2
    assert project['clips'][0]['out']==pytest.approx(.5)
    result=editor.mix(project)
    assert production.probe(Path(result['path']))['audio_duration']==pytest.approx(1,abs=.002)
    assert source.read_bytes()==original
    project['export']=result;editor.save(project)
    project=editor.edit(project['id'],3,'undo',{})
    assert len(project['clips'])==1
    assert project['export'] is None
    assert project['clips'][0]['out']==.9


@pytest.mark.parametrize('args',[{'gain':float('nan')},{'start':3600},{'in':.99,'out':1},{'mute':'false'},{'pan':2}])
def test_modifica_invalida_non_salva(workspace,args):
    project,_=project_with_audio(workspace)
    before=copy.deepcopy(project)
    with pytest.raises(ValueError):
        editor.edit(project['id'],1,'update',{'clip_id':project['clips'][0]['id'],**args})
    assert editor.load(project['id'])==before


def test_revisione_e_limiti_percorso(workspace):
    project,_=project_with_audio(workspace)
    with pytest.raises(ValueError,match='cambiato'):
        editor.edit(project['id'],0,'delete',{'clip_id':project['clips'][0]['id']})
    for value in ('../config','audio_../../',None):
        with pytest.raises(ValueError):
            editor.load(value)


def test_muto_esclude_traccia_e_sorgente_mancante_blocca(workspace):
    project,_=project_with_audio(workspace)
    editor.add_clip(project,tone(workspace/'seconda.wav',2),'Basso',start=2)
    project['clips'][1]['mute']=True
    assert editor.mix(project)['duration']==1
    Path(project['clips'][0]['src']).unlink()
    with pytest.raises(ValueError,match='sorgente'):
        editor.mix(project)


def test_impostazioni_annullabili(workspace):
    project,_=project_with_audio(workspace)
    result=editor.edit(project['id'],1,'settings',{'bpm':80,'key':'D minor'})
    assert result['recipe']['key']=='D minor'
    undone=editor.edit(project['id'],2,'undo',{})
    assert undone['recipe']['key']=='C major'


def test_handoff_copia_mix_e_durata_scene(workspace,monkeypatch):
    project,_=project_with_audio(workspace)
    project['export']=editor.mix(project);editor.save(project)
    store=production.ProductionStore(workspace/'productions')
    monkeypatch.setattr(production,'manager',SimpleNamespace(store=store))
    result=editor.video_project(project['id'],'Una foresta tranquilla')
    prod=store.get(result['production_id'])
    assert prod['soundtrack']['external_mix'] is True
    assert sum(s['duration_s'] for s in prod['shots'])==pytest.approx(1)
    snapshot=Path(prod['soundtrack_path'])
    assert snapshot.read_bytes()==Path(project['export']['path']).read_bytes()
    assert snapshot!=Path(project['export']['path'])
    Path(project['export']['path']).write_bytes(b'nuova versione')
    assert production.probe(snapshot)['duration']==pytest.approx(1)
    editor.edit(project['id'],1,'update',{'clip_id':project['clips'][0]['id'],'gain':-3})
    with pytest.raises(ValueError,match='Esporta'):
        editor.video_project(project['id'],'Una foresta tranquilla')


def test_mix_annullato_non_pubblica_export(workspace):
    project,_=project_with_audio(workspace)
    event=threading.Event();event.set()
    from core.job_worker import JobCancelled
    with pytest.raises(JobCancelled):
        asyncio.run(editor.export_job(None,{'args':{'project_id':project['id']},'cancel_event':event}))
    assert editor.load(project['id'])['export'] is None


def test_layer_prompt_bpm_tonalita_e_audio_reale(workspace,monkeypatch):
    from core.modules.sigma_voice_studio import music
    from core.modules.sigma_creative_lab.video import soundtrack
    project,_=project_with_audio(workspace)
    editor.edit(project['id'],1,'settings',{'bpm':84,'key':'D minor'})
    captured={}
    original=soundtrack.build_ace_step
    def workflow(*args,**kwargs):
        captured.update(args=args,kwargs=kwargs)
        return original(*args,**kwargs)
    async def validate(_):return {'ok':True}
    async def run(self,_):return tone(workspace/'generated.wav',5).read_bytes(),{}
    monkeypatch.setattr(music,'backend',lambda:SimpleNamespace(validate_workflow=validate))
    monkeypatch.setattr(music.CheckedBackend,'run',run)
    monkeypatch.setattr(soundtrack,'build_ace_step',workflow)
    result=asyncio.run(editor.layer_job(None,{'id':'music_test','args':{'project_id':project['id'],'prompt':'Solo basso caldo','seconds':5,'start':.5},'cancel_event':threading.Event()}))
    assert captured['args'][3]==84
    assert captured['kwargs']['keyscale']=='D minor'
    assert 'Solo basso caldo' in captured['args'][0]
    current=editor.load(project['id'])
    assert current['clips'][-1]['id']==result['clip']
    assert current['clips'][-1]['start']==.5
    assert current['clips'][-1]['out']==pytest.approx(5)


def test_soundtrack_approvata_non_viene_rigenerata(workspace):
    runner=object.__new__(production.ProductionRunner)
    source=tone(workspace/'approved.wav')
    asyncio.run(runner._soundtrack({'soundtrack':{'external_mix':True},'soundtrack_path':str(source)}))
    with pytest.raises(ValueError,match='non è più disponibile'):
        asyncio.run(runner._soundtrack({'soundtrack':{'external_mix':True},'soundtrack_path':str(workspace/'missing.wav')}))


@pytest.mark.parametrize('mode',['loop','sequence'])
def test_assemblaggio_video_preserva_durata_mix(workspace,monkeypatch,mode):
    from core.modules.sigma_creative_lab.video import postprocess
    monkeypatch.setattr(production.paths,'creative_output_dir',lambda _:workspace)
    monkeypatch.setattr(postprocess,'video_encoder_args',lambda *args:['-c:v','libx264','-preset','ultrafast'])
    def visual(prod,out,**kwargs):
        production._run([production.ffmpeg_bin(),'-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x96:r=24','-t','0.5','-c:v','libx264',str(out)],30)
    monkeypatch.setattr(production,'assemble',visual)
    runner=object.__new__(production.ProductionRunner)
    monkeypatch.setattr(runner,'_upscale_all',lambda _:None)
    monkeypatch.setattr(runner,'_emit',lambda **kwargs:None)
    source=tone(workspace/'music.wav',1.2)
    prod={'id':'prod_test','title':'Video musicale','settings':{},'audio_project':{'mode':mode,'mix':{'duration':1.2}},'soundtrack_path':str(source)}
    out=runner.assemble(prod)
    info=production.probe(out)
    assert info['duration']==pytest.approx(1.2,abs=.05)
    assert info['audio_duration']==pytest.approx(1.2,abs=.05)


def test_timeline_si_popola_dopo_render_e_conserva_mix(workspace):
    from core.modules.sigma_creative_lab.video.timeline import TimelineStore,audio_track,layout
    store=production.ProductionStore(workspace/'productions')
    music=tone(workspace/'music.wav',1.2)
    shot=production.new_shot('Scena tranquilla',duration_s=.5)
    prod=store.create('Prova editor',shots=[shot])
    prod.update(audio_project={'mode':'loop','mix':{'duration':1.2}},soundtrack_path=str(music))
    store.save(prod)
    ts=TimelineStore(store)
    assert ts.get(prod['id'])['video']==[]
    prod['shots'][0].update(status='done',clip_path=str(workspace/'scene.mp4'),frames=12)
    store.save(prod)
    tl=ts.get(prod['id'])
    assert len(tl['video'])==3
    assert layout(tl,prod)['duration']==pytest.approx(1.2)
    assert audio_track(tl,'music')['gain_db']==0
    assert audio_track(tl,'music')['clips'][0]['src_out']==1.2
    assert audio_track(tl,'clip')['mute'] is True
    assert ts.get(prod['id'])==tl


def test_tool_agente_modifica_progetto_e_rifiuta_revisione_vecchia(workspace):
    from core.modules.sigma_voice_studio.mcp_server import VoiceMCPServer
    project,_=project_with_audio(workspace)
    server=VoiceMCPServer()
    assert {'audio_projects','create_audio_project','edit_audio_project','render_audio_project','audio_to_video'} <= {tool['name'] for tool in server.list_tools()}
    result=server._handle_audio_edit({'id':project['id'],'revision':1,'operation':'update','args':{'clip_id':project['clips'][0]['id'],'gain':-6}})
    assert result['success']
    assert result['project']['clips'][0]['gain']==-6
    assert 'history' not in result['project']
    assert not server._handle_audio_edit({'id':project['id'],'revision':1,'operation':'undo'})['success']


def test_upload_a_blocchi_importazione_e_offset_duplicato(workspace,monkeypatch):
    from core.modules.sigma_voice_studio import audio_editor_routes as routes
    monkeypatch.setattr(routes,'music_service',lambda:None)
    project=editor.create(None,None,'Audio importato')
    source=tone(workspace/'upload.wav')
    answers=[]
    handler=SimpleNamespace(path=f"/api/audio-studio/upload?id={project['id']}&upload=abcdefgh&offset=0",
        _body_bytes=source.read_bytes(),send_json_response=lambda body,status=200:answers.append((body,status)))
    routes.handle_audio_upload(handler)
    assert answers[-1][0]['success']
    routes.handle_audio_upload(handler)
    assert answers[-1][1]==400
    handler.read_json_body=lambda:{'action':'import','id':project['id'],'upload':'abcdefgh','filename':'piano.wav'}
    routes.handle_audio_editor_action(handler)
    assert answers[-1][0]['success']
    assert len(answers[-1][0]['project']['clips'])==1
    assert 'history' not in answers[-1][0]['project']
    assert not (editor.directory(project['id'])/'.uploads'/'abcdefgh.part').exists()


def test_durata_produzione_usa_il_mix_anziche_la_sola_scena(workspace,monkeypatch):
    project=editor.create(None,None,'Nove secondi')
    editor.add_clip(project,tone(workspace/'musica.wav',9),'Musica')
    project['export']=editor.mix(project);editor.save(project)
    store=production.ProductionStore(workspace/'productions')
    monkeypatch.setattr(production,'manager',SimpleNamespace(store=store))
    result=editor.video_project(project['id'],'Foresta')
    prod=store.get(result['production_id'])
    assert len(prod['shots'])==1
    assert prod['shots'][0]['duration_s']==8
    assert prod['settings']['max_clip_seconds']==10
    assert production.summary(prod)['duration_s']==9


def test_libreria_riprende_progetto_collegato_senza_duplicarlo(workspace):
    source=tone(workspace/'brano.wav')
    service=SimpleNamespace(worker=SimpleNamespace(store=SimpleNamespace(get=lambda _: {
        'status':'done','result':{'title':'Musica','wav':str(source),'recipe':{'genre':'lofi_study','bpm':72}}})))
    project=editor.create(service,'music_originale','Sessione completa')
    reopened=editor.create(service,'music_originale')
    assert project['id']==reopened['id']
    assert editor.library_links()['music_originale']['project_id']==project['id']


def test_libreria_mostra_video_generato(workspace,monkeypatch):
    from core.modules.sigma_voice_studio.music import MusicService
    project=editor.create(None,None,'Titolo')
    project['source_job']='music_originale'
    editor.remember_project(project,'produzione_test')
    monkeypatch.setattr(production,'manager',SimpleNamespace(store=SimpleNamespace(get=lambda _: {
        'id':'produzione_test','title':'Video associato','status':'done','output_path':str(workspace/'video.mp4')})))
    service=object.__new__(MusicService)
    service.worker=SimpleNamespace(list=lambda:[{'id':'music_originale','status':'done'}])
    value=service.list()[0]
    assert value['audio_project']==project['id']
    assert value['video']['status']=='done'
    assert value['video']['url'].endswith('video.mp4')


@pytest.mark.parametrize('style',['anime','realistic','illustration','cartoon3d'])
def test_stile_scelto_dall_utente_configura_il_modello_video(workspace,monkeypatch,style):
    from core.modules.sigma_creative_lab.video.genres import GENRES
    project,_=project_with_audio(workspace)
    project['export']=editor.mix(project);editor.save(project)
    store=production.ProductionStore(workspace/'productions')
    monkeypatch.setattr(production,'manager',SimpleNamespace(store=store))
    result=editor.video_project(project['id'],'Scena tranquilla',style=style)
    prod=store.get(result['production_id'])
    assert prod['bible']['genre']==style
    assert prod['bible']['style']==GENRES[style]['style']
    with pytest.raises(ValueError,match='Stile'):
        editor.video_project(project['id'],'Scena',style='inesistente')
