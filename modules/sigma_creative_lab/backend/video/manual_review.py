"""Revisione visiva esplicita: conserva il dissenso del giudice e la motivazione dell'operatore."""
import hashlib
import math
from pathlib import Path
import time


def fingerprint(source):
    digest=hashlib.sha256()
    with Path(source).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def valid(shot):
    from .production import _prompt_hash
    from .visual_integrity import valid as integrity_valid
    review=shot.get('manual_review') or {}
    source=Path(shot.get('clip_path') or '')
    return (integrity_valid(shot) and source.is_file() and review.get('sha256')==fingerprint(source)
            and review.get('prompt_hash')==_prompt_hash(shot.get('prompt','')))


def accept(store,pid,shot_id,reason,reviewer='operator'):
    from .production import probe,_prompt_hash
    if not isinstance(reason,str) or not 20<=len(reason.strip())<=1000:
        raise ValueError('Descrivi la verifica effettuata (20–1000 caratteri)')
    if reviewer not in ('operator','agent_visual_review'):
        raise ValueError('Autore della revisione non valido')
    prod=store.get(pid)
    if not prod:raise ValueError('Produzione non trovata')
    shot=next((s for s in prod['shots'] if s['id']==shot_id),None)
    if not shot:raise ValueError('Clip non trovata')
    source=Path(shot.get('clip_path') or '')
    if not source.is_file() or shot.get('qa_issues'):
        raise ValueError('La clip deve esistere e superare i controlli tecnici')
    from .visual_integrity import require
    require(shot)
    info=probe(source)
    duration=float(info['duration']);expected=float(shot['duration_s'])
    if not info.get('width') or not math.isfinite(duration) or not math.isfinite(expected) or expected<=0 or duration<expected-.1:
        raise ValueError('Clip incompleta o priva di video')
    shot['manual_review']={'accepted':True,'reason':reason.strip(),'reviewer':reviewer,'time':time.time(),
                           'sha256':fingerprint(source),'prompt_hash':_prompt_hash(shot['prompt'])}
    shot.update(status='done',error='')
    shot.pop('review_existing',None)
    store.save(prod)
    return prod
