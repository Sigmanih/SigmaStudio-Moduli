"""Azioni leggibili e montaggi musicali variati, senza riempimenti con immagini ferme."""
from pathlib import Path
import hashlib
import math
import random

from core.store import JsonStore

ACTIVITIES = {
    'study': (
        ('Lettura attiva', 'Over the shoulder view of the alert adult student reading one open textbook. Her right index finger slowly slides across a printed line from left to right, returns to the left edge and follows the next line. Focus on the visible continuous movement of her finger over the page. Her partial side profile stays attentive.'),
        ('Sottolineatura', 'The adult student uses a yellow highlighter to underline two separate lines in an open textbook. Her right hand visibly draws one horizontal stroke, lifts the highlighter, then underlines the next line. Her left hand holds the page flat.'),
        ('Cambio pagina', 'The adult student pinches the top right corner of one paper page with her right hand, lifts it, turns it from right to left and lays it flat. She then looks down at the newly revealed page. Show the complete page turning action.'),
        ('Appunti', 'The adult student writes several short notes with a pen in a notebook beside an open textbook. Her right hand visibly writes across the paper, pauses, then starts a new line. Her eyes alternate between the textbook and notebook.'),
        ('Schede di ripasso', 'The adult student reviews paper flashcards, reading one card, flipping it over with her fingers, placing it on the desk and picking up the next card. Show the cards actually changing position.'),
        ('Segnalibro', 'The adult student picks up a small bookmark, inserts it between two textbook pages, closes the book carefully and moves it onto a small stack of books. Both hands visibly perform these actions.'),
        ('Consultazione', 'The adult student reaches for a second reference book, opens it on the desk and compares a passage with her notebook. Show her hands opening the cover and pointing to a line in each book.'),
        ('Ripasso al computer', 'The alert adult student types several short notes on a laptop keyboard, then moves her hand to the notebook and points at a written note. Show visible finger and arm movements, with her eyes open and attentive.'),
    ),
    'workout': (
        ('Riscaldamento', 'The adult athlete performs a brisk high knee march in place, alternately lifting her left and right knee toward waist height while swinging the opposite arm. Show several clear alternating steps. Full body view, both feet visible.'),
        ('Squat', 'The adult athlete performs two controlled bodyweight squats. With feet planted shoulder width apart she bends her hips and knees to lower her body, then stands upright again. Show the complete down and up motion twice. Full body side three quarter view.'),
        ('Curl con manubri', 'The adult athlete performs alternating biceps curls with two light dumbbells. She bends her right elbow to lift one dumbbell toward her shoulder, lowers it, then curls the left dumbbell. Her torso stays steady and both weights remain held in her hands.'),
        ('Cyclette', 'The adult athlete pedals a stationary exercise bicycle continuously. Her feet remain attached to the pedals and her knees move in clear alternating circular cycles. Her hands hold the handlebars. Full bicycle and both legs visible in side view.'),
        ('Boxe', 'The adult athlete shadowboxes in a stable athletic stance, extending her left arm in a straight jab, retracting it to guard, then extending her right arm and returning to guard. Show several deliberate alternating punches. Medium wide view including both arms.'),
        ('Affondi', 'The adult athlete performs controlled alternating reverse lunges, stepping her right foot backward, bending both knees, returning upright, then repeating with the left foot. Show complete leg movements and both feet on the gym floor.'),
        ('Alzate laterali', 'The adult athlete performs two controlled lateral raises with light dumbbells, lifting both arms outward from her sides to shoulder height and lowering them again. Show both arms moving through the full range, hands holding the same weights throughout.'),
        ('Mobilità', 'The adult athlete performs standing side bends, sliding one hand down her thigh while lifting the other arm overhead, returning upright and switching sides. Show clear controlled torso and arm movements. Full body view.'),
    ),
}

START_POSES = {
 'study': (
  'Over the right shoulder medium close view looking down at one open textbook and the right hand of exactly one adult student. Her index finger touches the left edge of a printed line. Her single head is partially visible at the right edge, eyes open looking down. The book and hand fill most of the frame. No person or face in the foreground.',
  'One adult student seated at the desk, left hand holding an open textbook flat, right hand holding one yellow highlighter with its tip at the beginning of a line on the page.',
  'One adult student seated at the desk, right fingertips holding the top right corner of a single paper page, left hand holding the open book flat. Only one page is slightly lifted.',
  'One adult student seated at the desk, one pen held in her right hand with its tip touching a notebook, left hand resting beside an open reference book, eyes open and attentive.',
  'One adult student seated at the desk, holding a single paper flashcard between her fingers, other flashcards in a neat stack on the desk, attentive open eyes.',
  'One adult student seated at the desk, holding one small bookmark above one open textbook, her other hand steadying the book. A small stack of books is beside it.',
  'One adult student seated at the desk, right hand resting on a closed reference book beside an open notebook, left hand on the desk, eyes open and looking at the book.',
  'One alert adult student seated at the desk with both hands on a laptop keyboard, eyes open looking at the screen, a notebook lying beside the laptop.',
 ),
 'workout': (
  'Exactly one adult athlete standing upright alone in the gym, both feet planted on the floor, elbows bent ready to march. Full body, entire head and both shoes in frame.',
  'Exactly one adult athlete standing upright alone in the gym, feet shoulder width apart, knees straight, arms held forward, ready to squat. Side three quarter full body view, both shoes visible.',
  'Exactly one adult athlete standing upright alone in the gym, arms straight down at her sides, one light dumbbell held in each hand, palms facing forward. Medium wide view showing both arms and weights.',
  'Exactly one adult athlete seated on one stationary exercise bicycle, each foot on its corresponding pedal, hands holding handlebars. Side view showing the full bicycle and both legs.',
  'Exactly one adult athlete standing alone in a boxing stance in the gym, both fists raised near her face, elbows bent, feet shoulder width apart. Full body three quarter view.',
  'Exactly one adult athlete standing upright alone in the gym, feet hip width apart, hands on hips, knees straight. Full body side three quarter view including both feet.',
  'Exactly one adult athlete standing upright alone in the gym, arms straight down, one light dumbbell in each hand beside her thighs. Full body front view with clear space around both arms.',
  'Exactly one adult athlete standing upright alone in the gym, arms relaxed at her sides, feet planted apart. Full body front view with space above her head and on both sides.',
 ),
}


def action_shots(prompt, activity):
    from .production import new_shot, _prompt_hash
    if activity not in ACTIVITIES:
        raise ValueError('Scegli studio oppure allenamento per il montaggio variato')
    shots=[]
    for index,(name,action) in enumerate(ACTIVITIES[activity]):
        lighting=('soft daylight and neutral colors','warm late afternoon light','cool evening light with warm lamps')[index//3]
        text=(f'{prompt.rstrip(".")}. {action} Lighting: {lighting}. '
              'One original adult character, coherent anatomy and objects. Continuous clearly visible joint and hand movement follows the described action. '
              'Keep the camera steady and frame all limbs and objects involved. No dialogue, no music, no logos.')
        shots.append(new_shot(text,duration_s=8,scene=name,required_action=name,
            start_frame_prompt=f'{prompt.rstrip(".")}. {START_POSES[activity][index]} Lighting: {lighting}. Single image, one person only, coherent anatomy, no duplicated figure, no sequence of poses, no text or logos.',
            ltx_prompt={'text':text,'source':_prompt_hash(text)}))
    return shots


def plan(shots,duration,seed=1000):
    if len(shots)<4 or not math.isfinite(duration) or duration<=0:
        raise ValueError('Il montaggio variato richiede almeno quattro azioni completate')
    rng=random.Random(seed); result=[]; used=set(); position=0.0
    while position<duration-.001:
        choices=[s for s in shots if not result or s['id']!=result[-1]['shot_id']]
        fresh=[s for s in choices if tuple([x['shot_id'] for x in result[-2:]]+[s['id']]) not in used]
        shot=rng.choice(fresh or choices)
        span=min(float(shot['duration_s']),duration-position)
        if span<=0:
            raise ValueError('Una clip del montaggio non ha durata valida')
        result.append({'shot_id':shot['id'],'action':shot.get('required_action') or shot.get('scene',''),
                       'start':round(position,6),'duration':span})
        if len(result)>=3: used.add(tuple(x['shot_id'] for x in result[-3:]))
        position+=span
    return result


def assemble(prod,out,work):
    from .production import _run,ffmpeg_bin,probe
    from .postprocess import video_encoder_args
    shots=[s for s in prod['shots'] if s.get('status')=='done' and Path(s.get('clip_path','')).is_file()]
    if len(shots)!=len(prod['shots']):
        raise ValueError('Completa e verifica tutte le azioni prima di montare il video musicale')
    duration=float(prod['audio_project']['mix']['duration'])
    schedule=plan(shots,duration,int(prod['settings'].get('seed',1000)))
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    first=probe(Path(shots[0]['clip_path'])); width,height=first['width'],first['height']
    normalized={}
    for shot in shots:
        source=Path(shot['clip_path'])
        signature=f"{shot['id']}|{source.stat().st_mtime_ns}|{source.stat().st_size}|{width}|{height}|{shot['duration_s']}|{prod['settings'].get('final_quality',18)}"
        target=work/(hashlib.sha256(signature.encode()).hexdigest()[:20]+'.mp4')
        if float(probe(source)['duration'])<float(shot['duration_s'])-.1:
            raise ValueError('Una clip è più corta dell’azione richiesta')
        if not target.is_file() or target.stat().st_mtime<source.stat().st_mtime:
            candidate=target.with_suffix('.part.mp4')
            _run([ffmpeg_bin(),'-v','error','-y','-i',str(source),'-t',str(shot['duration_s']),
                  '-vf',f'fps=24,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1',
                  '-an',*video_encoder_args(int(prod['settings'].get('final_quality',18)),0),str(candidate)],600)
            if abs(float(probe(candidate)['duration'])-float(shot['duration_s']))>.1:
                raise ValueError('La normalizzazione della clip non ha conservato la durata')
            candidate.replace(target)
        normalized[shot['id']]=target
    JsonStore(work/'montage_plan.json').save({'duration':duration,'items':schedule})
    listing=work/'concat.txt'
    listing.write_text(''.join("file '"+normalized[item['shot_id']].resolve().as_posix().replace("'","'\\''")+"'\n" for item in schedule),encoding='utf-8')
    _run([ffmpeg_bin(),'-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-t',str(duration),'-an','-c:v','copy',str(out)],1200)
    if abs(float(probe(out)['duration'])-duration)>.1:
        raise ValueError('Il montaggio variato non copre la durata della musica')
    return out
