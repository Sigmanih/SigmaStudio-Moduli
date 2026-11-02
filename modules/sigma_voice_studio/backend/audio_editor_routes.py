"""API dei progetti audio: modifiche immediate, generazioni in coda."""
from urllib.parse import parse_qs, urlparse
from . import audio_editor as E
from .music import music_service


def view(project):
    return {**{k:v for k,v in project.items() if k!='history'},'can_undo':bool(project.get('history'))}


def handle_audio_upload(self):
    from core.modules.sigma_creative_lab.video import media_import as media
    try:
        query={key:value[0] for key,value in parse_qs(urlparse(self.path).query).items()}
        E.load(query.get('id'))
        offset=int(query.get('offset',0))
        if offset < 0 or offset + len(getattr(self,'_body_bytes',b'')) > 1024*1024*1024:
            raise ValueError('Il caricamento audio non può superare 1 GB')
        size=media.append_chunk(E.directory(query['id'])/'.uploads',query.get('upload',''),
                                offset,getattr(self,'_body_bytes',b''))
        self.send_json_response({'success':True,'size':size})
    except (ValueError,TypeError,KeyError,OSError) as exc:
        self.send_json_response({'success':False,'error':str(exc)},400)


def handle_audio_projects(self):
    query = parse_qs(urlparse(self.path).query)
    try:
        data = {'project': view(E.load(query['id'][0]))} if query.get('id') else {'projects': [
            {key:p[key] for key in ('id','title','revision')} for p in E.listing()]}
        self.send_json_response({'success':True, **data})
    except (ValueError, OSError) as exc:
        self.send_json_response({'success':False,'error':str(exc)},400)


def handle_audio_editor_action(self):
    try:
        data = self.read_json_body()
        if not isinstance(data,dict):
            raise ValueError('Parametri audio non validi')
        action = data.get('action')
        service = music_service()
        if action == 'create':
            result = {'project':E.create(service,data.get('source_job'),data.get('title'),data.get('request_id'))}
        elif action == 'edit':
            result = {'project':E.edit(data.get('id'),data.get('revision'),data.get('operation'),data.get('args') or {})}
        elif action == 'add':
            previous = service.worker.store.get(data.get('source_job'))
            if not previous or previous['status'] != 'done' or not (previous.get('result') or {}).get('wav'):
                raise ValueError('Sorgente audio non disponibile')
            with E._lock:
                project=E.load(data.get('id'))
                if project['revision'] != data.get('revision'):
                    raise ValueError('Il progetto è cambiato: ricaricalo')
                import copy
                project['history']=(project['history']+[copy.deepcopy(project['clips'])])[-40:]
                E.add_clip(project,previous['result']['wav'],previous['result']['title'],data.get('start',0))
                project['revision']+=1;project['export']=None;E.save(project)
            result={'project':project}
        elif action=='import':
            from core.modules.sigma_creative_lab.video import media_import as media
            from pathlib import Path
            import re,copy
            if not re.fullmatch(r'[a-z0-9]{8,32}',str(data.get('upload',''))):
                raise ValueError('Identificativo del caricamento non valido')
            if media.kind_of(Path(str(data.get('filename',''))))!='audio':
                raise ValueError('Importa un file audio supportato')
            with E._lock:
                project=E.load(data.get('id'))
                source=media.finish_upload(E.directory(project['id'])/'.uploads',data['upload'],data['filename'],E.directory(project['id'])/'imports')
                project['history']=(project['history']+[copy.deepcopy(project['clips'])])[-40:]
                E.add_clip(project,source,Path(data['filename']).stem,data.get('start',0))
                project['revision']+=1;project['export']=None;E.save(project)
                source.unlink()
            result={'project':project}
        elif action in ('mix','layer'):
            result={'job':E.submit(service,data.get('id'),action,data)}
        elif action=='video':
            result={'video':E.video_project(data.get('id'),data.get('prompt',''),data.get('mode','loop'))}
        else:
            raise ValueError('Azione audio non supportata')
        if result.get('project'):
            result['project']=view(result['project'])
        self.send_json_response({'success':True,**result})
    except (ValueError,TypeError,KeyError,OSError,RuntimeError,ImportError) as exc:
        self.send_json_response({'success':False,'error':str(exc)},400)
