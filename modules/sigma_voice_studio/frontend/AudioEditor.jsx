import { useEffect, useState } from 'react';
import { Play, Square, Scissors, Copy, Trash2, Undo2, Download, Film, Layers, RefreshCw } from 'lucide-react';
import { useApp } from '../../contexts/AppContext';
import '../../styles/03-modules/audio-editor.css';

async function api(path, body) {
  const response = await fetch(path, body === undefined ? undefined : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok || !value.success) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

const clock = seconds => `${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;

export default function AudioEditor({ sourceJob, onOpened }) {
  const { openTab } = useApp();
  const [projects,setProjects] = useState([]), [project,setProject] = useState(null);
  const [selected,setSelected] = useState(''), [form,setForm] = useState({});
  const [cursor,setCursor] = useState(0), [playing,setPlaying] = useState(false), [drag,setDrag] = useState(null);
  const [error,setError] = useState(''), [pending,setPending] = useState(false);
  const [prompt,setPrompt] = useState(''), [start,setStart] = useState(0), [seconds,setSeconds] = useState(30);
  const [videoPrompt,setVideoPrompt] = useState('Una persona adulta studia alla scrivania in una stanza anime, pioggia alla finestra, movimenti minimi e camera fissa.');
  const [videoMode,setVideoMode]=useState('loop');
  const [videoStyle,setVideoStyle]=useState('anime');
  const [job,setJob] = useState(null), [sources,setSources] = useState([]), [source,setSource] = useState('');
  const [newTitle,setNewTitle]=useState('Nuovo progetto audio'),[bpm,setBpm]=useState(72),[key,setKey]=useState('C major');
  const [createToken]=useState(()=>window.crypto.randomUUID().replaceAll('-',''));
  const duration = Math.max(1,...(project?.clips || []).map(c=>c.start+c.out-c.in));
  const clip = project?.clips.find(c=>c.id===selected);
  const refreshList = async () => { try { const value=await api('/api/audio-studio/projects');setProjects(value.projects||[]); } catch(exc){setError(exc.message);} };
  useEffect(()=>{refreshList();api('/api/audio-studio/music/jobs').then(v=>setSources(v.jobs.filter(j=>j.status==='done'&&j.result?.wav))).catch(exc=>setError(exc.message));},[]);
  const action = async body => {
    setPending(true);setError('');setPlaying(false);
    try {const value=await api('/api/audio-studio/editor',body);if(value.project){setProject(value.project);refreshList();}if(value.job)setJob(value.job);return value;}
    catch(exc){setError(exc.message);return null;}finally{setPending(false);}
  };
  useEffect(()=>{
    if(sourceJob){action({action:'create',source_job:sourceJob,request_id:createToken}).then(value=>{if(value?.project)onOpened?.();});}
  },[sourceJob]);
  useEffect(()=>{setForm(clip?{...clip}:{});},[selected,project?.revision]);
  useEffect(()=>{if(project){setBpm(project.recipe.bpm||72);setKey(project.recipe.key||'C major');}},[project?.id,project?.revision]);
  const upload=async file=>{
    if(!file||!project)return;setPending(true);setError('');setPlaying(false);
    try{
      const uploadId=window.crypto.randomUUID().replaceAll('-','');
      for(let offset=0;offset<file.size;offset+=1024*1024){
        const response=await fetch(`/api/audio-studio/upload?id=${project.id}&upload=${uploadId}&offset=${offset}`,
          {method:'POST',body:file.slice(offset,offset+1024*1024)});
        const value=await response.json();if(!response.ok||!value.success)throw new Error(value.error||'Caricamento interrotto');
      }
      const value=await api('/api/audio-studio/editor',{action:'import',id:project.id,upload:uploadId,filename:file.name,start:cursor});setProject(value.project);
    }catch(exc){setError(exc.message);}finally{setPending(false);}
  };
  useEffect(()=>{
    if(!job || !['queued','running'].includes(job.status))return;
    const timer=window.setInterval(async()=>{
      try{const value=await api('/api/audio-studio/music/jobs');const found=value.jobs.find(j=>j.id===job.id);if(!found)return;setJob(found);
        if(found.status==='done'){if(found.args?.project_id===project?.id){const data=await api(`/api/audio-studio/projects?id=${project.id}`);setProject(data.project);}refreshList();}
        if(found.status==='error')setError(found.error);
      }catch(exc){setError(exc.message);}
    },2000);
    return()=>window.clearInterval(timer);
  },[job?.id,job?.status,project?.id]);
  useEffect(()=>{
    if(!playing || !project)return;
    const Context=window.AudioContext || window.webkitAudioContext;
    if(!Context){setError('Questo browser non supporta il mix audio dal vivo');setPlaying(false);return;}
    const context=new Context();const origin=cursor;const began=performance.now();let stopped=false;
    const players=project.clips.filter(c=>!c.mute).map(c=>{
      const audio=new Audio(c.url);audio.preload='auto';const source=context.createMediaElementSource(audio),gain=context.createGain(),pan=context.createStereoPanner();
      pan.pan.value=c.pan;source.connect(gain);gain.connect(pan);pan.connect(context.destination);return{clip:c,audio,gain};
    });
    const tick=()=>{
      const at=origin+(performance.now()-began)/1000;setCursor(Math.min(at,duration));
      for(const p of players){const local=at-p.clip.start,span=p.clip.out-p.clip.in;
        if(local<0||local>=span){p.audio.pause();continue;}
        const fade=Math.min(1,p.clip.fade_in?local/p.clip.fade_in:1,p.clip.fade_out?(span-local)/p.clip.fade_out:1);
        p.gain.gain.value=Math.pow(10,p.clip.gain/20)*Math.max(0,fade)*.7;
        if(Math.abs(p.audio.currentTime-(p.clip.in+local))>.25)p.audio.currentTime=p.clip.in+local;
        if(p.audio.paused)p.audio.play().catch(exc=>{if(!stopped){setError(exc.message);setPlaying(false);}});
      }
      if(at>=duration)setPlaying(false);
    };
    context.resume().catch(exc=>{setError(exc.message);setPlaying(false);});tick();const timer=window.setInterval(tick,100);
    return()=>{stopped=true;window.clearInterval(timer);players.forEach(p=>{p.audio.pause();p.audio.removeAttribute('src');p.audio.load();});context.close().catch(()=>{});};
  },[playing,project]);
  const edit=(operation,args={})=>action({action:'edit',id:project.id,revision:project.revision,operation,args:{clip_id:selected,...args}});
  const openProject=async id=>{setPlaying(false);setSelected('');setCursor(0);if(!id){setProject(null);return;}try{setProject((await api(`/api/audio-studio/projects?id=${id}`)).project);setError('');}catch(exc){setError(exc.message);}};
  return <div className="ae-editor">
    <header className="ae-toolbar"><label>Progetto audio<select disabled={pending} value={project?.id||''} onChange={event=>openProject(event.target.value)}><option value="">Scegli un progetto</option>
      {projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
      <label>Titolo nuovo progetto<input value={newTitle} maxLength={100} onChange={event=>setNewTitle(event.target.value)}/></label><button disabled={pending||!newTitle.trim()} onClick={()=>action({action:'create',title:newTitle})}>Nuovo progetto</button>
      {project&&<><strong>{project.title}</strong><button disabled={pending} onClick={()=>openProject(project.id)}><RefreshCw size={15}/> Ricarica progetto</button><button disabled={pending} onClick={()=>{if(cursor>=duration)setCursor(0);setPlaying(!playing);}}>{playing?<Square size={16}/>:<Play size={16}/>} {playing?'Ferma':'Ascolta mix'}</button>
      <span>{clock(cursor)} / {clock(duration)}</span><button disabled={pending||!project.can_undo} onClick={()=>edit('undo')}><Undo2 size={15}/> Annulla</button>
      <button disabled={pending} onClick={()=>action({action:'mix',id:project.id})}><Download size={15}/> Esporta mix</button></>}
      {project&&<label>Importa audio<input type="file" accept="audio/*,.wav,.mp3,.flac,.m4a,.ogg" disabled={pending} onChange={event=>upload(event.target.files?.[0])}/></label>}
    </header>
    {error&&<p className="as-error" role="alert">{error}</p>}
    {!project&&<p>Apri una composizione dalla libreria con «Modifica nell’editor», oppure riprendi un progetto salvato.</p>}
    {job&&<p role="status">{job.status}: {job.error||job.message}</p>}
    {project&&<>
      <div className="ae-workspace"><section className="ae-timeline" aria-label="Timeline audio multitraccia">
        <svg className="ae-ruler" viewBox="0 0 1000 30" preserveAspectRatio="none" onClick={event=>{setPlaying(false);setCursor((event.clientX-event.currentTarget.getBoundingClientRect().left)/event.currentTarget.getBoundingClientRect().width*duration);}}>
          {Array.from({length:11},(_,i)=><text key={i} x={i*98} y={20}>{clock(duration*i/10)}</text>)}</svg>
        {project.clips.map(c=>{
          const position=drag?.id===c.id?drag.to:c.start;
          const x=position/duration*1000,w=(c.out-c.in)/duration*1000;
          const values=c.peaks.slice(Math.floor(c.in/c.source_duration*c.peaks.length),Math.max(1,Math.ceil(c.out/c.source_duration*c.peaks.length)));
          const maximum=Math.max(.001,...values);
          const wave=values.map((value,index)=>`M${x+index/values.length*w},${35-value/maximum*25}v${value/maximum*50}`).join(' ');
          return <div className={`ae-track ${selected===c.id?'selected':''}`} key={c.id}>
            <button className="ae-track-label" onClick={()=>setSelected(c.id)}>{c.mute?'M · ':''}{c.label}</button>
            <svg viewBox="0 0 1000 70" preserveAspectRatio="none" aria-label={`Traccia ${c.label}`} role="img"
              onPointerDown={event=>{setSelected(c.id);setPlaying(false);event.currentTarget.setPointerCapture(event.pointerId);setDrag({id:c.id,at:event.clientX,start:c.start,to:c.start});}}
              onPointerMove={event=>{if(drag?.id===c.id){const value=Math.max(0,Math.min(3600,drag.start+(event.clientX-drag.at)/event.currentTarget.getBoundingClientRect().width*duration));setDrag({...drag,to:value});}}}
              onPointerCancel={()=>setDrag(null)} onPointerUp={()=>{if(drag){const value=drag.to;setDrag(null);if(Math.abs(value-c.start)>.01)edit('update',{clip_id:c.id,start:value});}}}>
              <rect className="ae-clip" x={x} y={3} width={Math.max(2,w)} height={64}/><path className="ae-wave" d={wave}/>
              <line className="ae-cursor" x1={cursor/duration*1000} x2={cursor/duration*1000} y1={0} y2={70}/>
            </svg></div>;
        })}
        {project.export&&<div className="ae-export"><strong>Mix aggiornato · revisione {project.export.revision}</strong><audio controls src={project.export.url}/><a href={project.export.url} download>Scarica WAV</a></div>}
      </section><aside className="ae-inspector">
        <h3>Clip selezionata</h3>{clip?<>
          <strong>{clip.label}</strong><div className="ae-fields">{[['start','Posizione (s)'],['in','Taglio iniziale (s)'],['out','Fine sorgente (s)'],['gain','Volume (dB)'],['pan','Pan (-1 / +1)'],['fade_in','Dissolvenza iniziale (s)'],['fade_out','Dissolvenza finale (s)']].map(([key,label])=><label key={key}>{label}<input type="number" step="0.1" value={form[key]??0} onChange={event=>setForm({...form,[key]:event.target.value})}/></label>)}</div>
          <label><input type="checkbox" checked={!!form.mute} onChange={event=>setForm({...form,mute:event.target.checked})}/> Muto</label>
          <button disabled={pending} onClick={()=>edit('update',Object.fromEntries(['start','in','out','gain','pan','fade_in','fade_out','mute'].map(key=>[key,key==='mute'?form[key]:Number(form[key])]))) }>Applica modifiche</button>
          <div className="ae-actions"><button disabled={pending} onClick={()=>edit('split',{at:cursor})}><Scissors size={14}/> Dividi al cursore</button><button disabled={pending} onClick={()=>edit('duplicate')}><Copy size={14}/> Duplica</button><button disabled={pending} onClick={()=>edit('delete')}><Trash2 size={14}/> Rimuovi</button></div>
        </>:<p>Seleziona una forma d’onda. Trascinala per cambiare posizione.</p>}
      </aside></div>
      <section className="ae-panels"><div><h3><Layers size={16}/> Aggiungi una base o uno strumento</h3>
        <p className="as-note">BPM e tonalità guidano le nuove generazioni; non cambiano le clip esistenti. Ascolta il WAV esportato per verificare il mix finale.</p>
        <div className="ae-fields"><label>BPM di riferimento<input type="number" min={40} max={140} value={bpm} onChange={event=>setBpm(event.target.value)}/></label><label>Tonalità di riferimento<select value={key} onChange={event=>setKey(event.target.value)}>{['C major','D major','E major','F major','G major','A minor','B minor','C minor','D minor','E minor','F minor','G minor'].map(value=><option key={value}>{value}</option>)}</select></label></div>
        <button disabled={pending} onClick={()=>edit('settings',{bpm:Number(bpm),key})}>Imposta riferimenti musicali</button>
        <select aria-label="Composizione da aggiungere" value={source} onChange={event=>setSource(event.target.value)}><option value="">Scegli dalla libreria</option>{sources.map(s=><option key={s.id} value={s.id}>{s.result.title} · {s.id.slice(-6)}</option>)}</select>
        <button disabled={pending||!source} onClick={()=>action({action:'add',id:project.id,revision:project.revision,source_job:source,start:Number(start)})}>Aggiungi traccia</button>
        <textarea aria-label="Prompt dello strumento" value={prompt} maxLength={1200} onChange={event=>setPrompt(event.target.value)} placeholder="Solo pianoforte jazz morbido, accordi semplici, senza batteria né voce"/>
        <div className="ae-fields"><label>Posizione (s)<input type="number" min={0} max={3480} value={start} onChange={event=>setStart(event.target.value)}/></label><label>Durata (5–120 s)<input type="number" min={5} max={120} value={seconds} onChange={event=>setSeconds(event.target.value)}/></label></div>
        <button disabled={pending||!prompt.trim()} onClick={()=>action({action:'layer',id:project.id,prompt,start:Number(start),seconds:Number(seconds)})}>Genera nuova traccia dal prompt</button>
        <p className="as-note">Il modello genera un livello musicale nuovo: può includere altri suoni. Le tracce già presenti non vengono separate o sovrascritte.</p>
      </div><div><h3><Film size={16}/> Dalla musica al video</h3><p>Esporta il mix, descrivi la scena e continua in Video Studio con la colonna sonora collegata.</p>
        <textarea aria-label="Scena video per la musica" maxLength={2000} value={videoPrompt} onChange={event=>setVideoPrompt(event.target.value)}/>
        <label>Stile visivo<select value={videoStyle} onChange={event=>setVideoStyle(event.target.value)}><option value="anime">Anime</option><option value="realistic">Realistico</option><option value="illustration">Illustrato</option><option value="cartoon3d">Cartone 3D</option></select></label>
        <label>Struttura del video<select value={videoMode} onChange={event=>setVideoMode(event.target.value)}><option value="loop">Una scena breve ripetuta sulla musica</option><option value="sequence">Scene successive lungo tutto il brano</option></select></label>
        <button disabled={pending||!project.export||!videoPrompt.trim()} onClick={async()=>{const value=await action({action:'video',id:project.id,prompt:videoPrompt,mode:videoMode,style:videoStyle});if(value?.video){window.sessionStorage.setItem('sigmaAudioVideoProduction',value.video.production_id);openTab({name:'Video Studio'},'video_studio');window.dispatchEvent(new CustomEvent('sigma_video_open_production',{detail:value.video.production_id}));}}}>Prepara il video da questa musica</button>
      </div></section>
    </>}
  </div>;
}
