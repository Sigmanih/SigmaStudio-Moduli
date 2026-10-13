"""Operazioni AI dell'editor: rigenerare, estendere, inserire, dialoghi, voci, musica, export.

Ogni operazione e' un job in coda: le generazioni durano da secondi (una
battuta) a minuti (un tratto di video), e la UI resta libera intanto. I job
girano uno alla volta sulla GPU principale e aspettano se una produzione sta
renderizzando: due modelli video sulla stessa scheda andrebbero in OOM.

Un job che genera video crea un'inquadratura nuova (`origin: edit`) o una
nuova versione di una esistente, e solo alla fine modifica la timeline con una
normale operazione annullabile: se il job fallisce, la timeline non cambia.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import re
import threading
import time
import uuid
from pathlib import Path

from core.logger import get_logger
from core.modules.sigma_creative_lab.video import media_cache, timeline as T

log = get_logger("creative_editor_jobs")

FPS = 24
MAX_DIALOGUE_ATTEMPTS = 3
#: Somiglianza minima fra la battuta del copione e cio' che Whisper sente.
DIALOGUE_MATCH = 0.72


def _now() -> float:
    return round(time.time(), 3)


def _norm_words(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").lower()))


def speech_match(expected: str, heard: str) -> float:
    return difflib.SequenceMatcher(None, _norm_words(expected), _norm_words(heard)).ratio()


class EditorJobs:
    def __init__(self, production_store, production_manager):
        self.prods = production_store
        self.manager = production_manager
        self.timelines = T.TimelineStore(production_store)
        self.jobs: dict[str, dict] = {}
        self.queue: list[str] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="editor-jobs", daemon=True)
        self._thread.start()

    # --- coda ------------------------------------------------------------

    def busy(self) -> bool:
        with self._lock:
            return any(j["status"] in ("queued", "running") for j in self.jobs.values())

    def submit(self, pid: str, kind: str, args: dict) -> dict:
        if kind not in HANDLERS:
            raise ValueError(f"operazione sconosciuta: {kind}")
        if self.prods.get(pid) is None:
            raise ValueError("produzione inesistente")
        job = {"id": f"ej_{uuid.uuid4().hex[:8]}", "production": pid, "kind": kind, "args": args,
               "status": "queued", "message": "In coda", "progress": 0.0, "created": _now(), "result": None,
               "error": ""}
        with self._lock:
            self.jobs[job["id"]] = job
            self.queue.append(job["id"])
            # Si tengono gli ultimi 200 job: lo storico serve alla UI, non e' un archivio.
            for old in list(self.jobs)[:-200]:
                if self.jobs[old]["status"] not in ("queued", "running"):
                    self.jobs.pop(old, None)
        self._wake.set()
        return job

    def list(self, pid: str | None = None) -> list[dict]:
        with self._lock:
            return [j for j in reversed(self.jobs.values()) if pid is None or j["production"] == pid]

    def forget(self, pid: str) -> None:
        """Dimentica i job conclusi di una produzione eliminata (la UI non deve mostrarli piu')."""
        with self._lock:
            for jid in [j for j, job in self.jobs.items() if job["production"] == pid
                        and job["status"] not in ("queued", "running")]:
                self.jobs.pop(jid, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job["status"] != "queued":
                return False
            self.queue.remove(job_id)
            job.update(status="cancelled", message="Annullato")
            return True

    def _loop(self) -> None:
        while True:
            self._wake.wait(timeout=5)
            self._wake.clear()
            while True:
                busy_gpu = bool(self.manager.active())
                with self._lock:
                    # Importare un video o creare un titolo non usa la GPU: non deve
                    # aspettare la fine di una produzione in corso.
                    runnable = [j for j in self.queue if not busy_gpu or self.jobs[j]["kind"] in CPU_KINDS]
                    job = self.jobs.get(runnable[0]) if runnable else None
                    waiting = [self.jobs[j] for j in self.queue if j not in runnable]
                for w in waiting:
                    w["message"] = "In attesa: una produzione sta usando la GPU"
                if job is None:
                    if waiting:
                        time.sleep(10)
                        continue
                    break
                with self._lock:
                    self.queue.remove(job["id"])
                job.update(status="running", started=_now(), message="Avvio")
                try:
                    job["result"] = asyncio.run(HANDLERS[job["kind"]](self, job))
                    job.update(status="done", progress=1.0, message="Completato", finished=_now())
                except Exception as e:
                    log.error(f"job {job['kind']} fallito: {e}")
                    job.update(status="error", error=str(e), message="Errore", finished=_now())

    # --- supporto ----------------------------------------------------------

    def _note(self, job: dict, message: str, progress: float | None = None) -> None:
        job["message"] = message
        if progress is not None:
            job["progress"] = round(max(0.0, min(1.0, progress)), 3)

    def _engine(self, prod: dict):
        from core.modules.sigma_creative_lab.video.production import ComfyClipEngine, NativeClipEngine
        # La GPU principale fa i lavori interattivi: e' la piu' veloce.
        if prod["settings"].get("backend") == "sigma_native":
            engine = NativeClipEngine({})
            engine.placement = "gpu:0"
            return engine
        return ComfyClipEngine({"gpu": 0, "flags": prod["settings"].get("comfy_flags")})

    def _frame(self, pid: str, prod: dict, t: float, name: str) -> Path:
        """Fotogramma della timeline all'istante t (PNG nella cartella della produzione)."""
        tl = self.timelines.get(pid)
        hit = T.locate(tl, prod, t)
        if not hit:
            raise ValueError(f"nessun elemento della timeline a {t:.2f} s")
        i, src_t = hit
        item = T.layout(tl, prod)["items"][i]
        out = self.prods.path(pid) / "anchors" / f"{name}_{int(t * 1000)}.png"
        return media_cache.frame_at(Path(item["clip_path"]), src_t, out)

    def _new_edit_shot(self, prod: dict, prompt: str, **extra) -> dict:
        from core.modules.sigma_creative_lab.video.production import new_shot
        shot = new_shot(prompt, extra.pop("duration_s", 4.0), "cut", origin="edit", **extra)
        prod["shots"].append(shot)
        return shot

    async def _render(self, job: dict, prod: dict, shot: dict, prompt: str, seconds: float,
                      judge_attempts: int | None = None, **anchors) -> dict:
        """Genera un clip H3 e lo registra come nuova versione dell'inquadratura.

        Ogni tentativo passa dal giudice visivo; quelli scartati restano come
        versioni (si possono comunque scegliere) e il successivo parte dal
        prompt corretto. Se nessuno passa, resta attiva la versione migliore.
        """
        from core.modules.sigma_creative_lab.video.production import (
            add_prompt_fix, clip_frames, compose_prompt, judge_clip,
        )
        s = prod["settings"]
        frames = clip_frames(s, seconds)
        seed = int(anchors.pop("seed", None) or (int(time.time()) % 100000))
        clips = self.prods.path(prod["id"]) / "clips"
        attempts = max(1, int(judge_attempts or s.get("max_attempts", 3)))
        # Il giudice deve leggere l'azione, non i segnaposto dei riferimenti di H3.
        intent = re.sub(r"\s*<(?:Picture|Audio) \d+>", "", prompt.split("\nAudio:")[0]).strip()
        if prompt.strip() != (shot.get("prompt") or "").strip():
            # Descrizione nuova: le correzioni del giudice riguardavano quella vecchia.
            shot["prompt_fixes"] = []
        engine = self._engine(prod)
        tried: list[tuple[float, dict]] = []
        take = None
        for attempt in range(1, attempts + 1):
            n = len(T.ensure_takes(shot)) + 1
            request = {
                "prompt": compose_prompt(prod, {**shot, "prompt": prompt, "transition": "cut"},
                                         bool(anchors.get("ref_images"))),
                "negative_prompt": (prod.get("bible") or {}).get("negative", ""), "frames": frames, "seed": seed,
                "loras": (prod.get("bible") or {}).get("loras") or [], "continued": bool(anchors.get("init_image")),
                "output_path": str(clips / f"edit_{shot['id']}_t{n}.mp4"), **anchors,
            }
            last_progress = {"t": 0.0}
            label = f"Tentativo {attempt}/{attempts}: " if attempts > 1 else ""

            def on_progress(p, label=label):
                if p.get("progress") is not None and time.monotonic() - last_progress["t"] > 1:
                    last_progress["t"] = time.monotonic()
                    self._note(job, f"{label}generazione {p['progress']:.0f}%", 0.1 + 0.75 * float(p["progress"]) / 100)

            self._note(job, f"{label}generazione del video", 0.1)
            result = await engine.render(prod, shot, request, progress=on_progress)
            take = T.add_take(shot, result["clip_path"], last_frame=result.get("last_frame", ""), seed=seed,
                              prompt=prompt, frames=result.get("frames", frames), kind=job["kind"],
                              timings=result.get("timings", {}))
            self.prods.save(prod)
            self._note(job, f"{label}controllo del movimento", 0.88)
            verdict = await judge_clip(prod, shot, Path(result["clip_path"]), intent)
            if verdict is None or verdict["ok"]:
                if verdict:
                    take["judge"] = {k: verdict[k] for k in ("score", "seen", "issues")}
                break
            take["judge"] = {k: verdict[k] for k in ("score", "seen", "issues")}
            tried.append((verdict["score"], take))
            log.warning(f"versione {take['id']} di {shot['id']} scartata ({verdict['score']}): {verdict['issues']}")
            if attempt < attempts:
                add_prompt_fix(shot, verdict)
                seed += 7919
                self._note(job, f"Scartata ({'; '.join(verdict['issues'][:2]) or verdict['seen']}): nuovo tentativo")
        else:
            # Nessun tentativo promosso: si attiva il migliore, non l'ultimo.
            take = max(tried, key=lambda x: x[0])[1]
            shot["take"] = take["id"]
            shot.update(clip_path=take["clip_path"], last_frame=take.get("last_frame", ""),
                        frames=take.get("frames", frames))
            job["warning"] = f"nessun tentativo convincente: tenuta la versione {take['id']} ({take['judge']['score']})"
        shot.update(status="done", prompt=prompt)
        self.prods.save(prod)
        return take


# ---------------------------------------------------------------------------
# Operazioni
# ---------------------------------------------------------------------------

async def job_regen_range(self: EditorJobs, job: dict) -> dict:
    """Rigenera il tratto [a, b] con una descrizione, agganciato ai fotogrammi in a e in b."""
    pid, a = job["production"], job["args"]
    t_a, t_b = sorted((float(a["t_a"]), float(a["t_b"])))
    if t_b - t_a < 0.5:
        raise ValueError("il tratto deve durare almeno mezzo secondo")
    prod = self.prods.get(pid)
    self._note(job, "Estrazione dei fotogrammi di aggancio", 0.05)
    first = self._frame(pid, prod, t_a, "A")
    # B: l'ultimo fotogramma prima del punto scelto, se b coincide con la fine della timeline.
    end_t = min(t_b, T.layout(self.timelines.get(pid), prod)["duration"] - 1.0 / FPS)
    last = self._frame(pid, prod, end_t, "B") if a.get("anchor_end", True) else None
    shot = self._new_edit_shot(prod, a["prompt"], duration_s=t_b - t_a, anchors={"t_a": t_a, "t_b": t_b})
    take = await self._render(job, prod, shot, a["prompt"], t_b - t_a, init_image=str(first),
                              **({"end_image": str(last)} if last else {}))
    self._note(job, "Aggiornamento della timeline", 0.95)
    tl, res = self.timelines.apply(pid, "delete_range", {"t_a": t_a, "t_b": t_b})
    dur = T.take_duration(take)
    # L'ultimo fotogramma generato e' B, che e' anche il primo dell'elemento a destra.
    src_out = dur - (1.0 / FPS if last else 0.0)
    tl, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": take["id"],
                                                        "index": res["insert_at"], "src_out": src_out})
    return {"shot": shot["id"], "take": take["id"], "item": ins["item"], "duration": round(src_out, 3)}


async def job_redo(self: EditorJobs, job: dict) -> dict:
    """Nuova versione di un elemento, con una descrizione nuova o la stessa."""
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    tl = self.timelines.get(pid)
    idx, item = T._find(tl["video"], a["item_id"], "elemento")
    shot = T.shot_by_id(prod, item["shot_id"])
    if shot is None:
        raise ValueError("inquadratura dell'elemento non trovata")
    prompt = a.get("prompt") or shot.get("prompt", "")
    anchors = {}
    if a.get("keep_start", shot.get("transition") == "continue") and idx > 0:
        lay = T.layout(tl, prod)["items"]
        anchors["init_image"] = str(self._frame(pid, prod, max(0.0, lay[idx - 1]["end"] - 1.0 / FPS), "prev"))
    else:
        # Come nelle produzioni: senza l'immagine di riferimento il personaggio
        # rifatto cambierebbe volto e vestiti rispetto al resto del video.
        chars = {c.get("name"): c for c in (prod.get("bible") or {}).get("characters") or []}
        refs = [chars[n]["ref_image"] for n in shot.get("refs") or []
                if n in chars and chars[n].get("ref_image") and Path(chars[n]["ref_image"]).is_file()]
        if refs:
            anchors["ref_images"] = refs
    take = await self._render(job, prod, shot, prompt, float(item["src_out"] - item["src_in"]) + 0.2, **anchors)
    self.timelines.apply(pid, "set_take", {"item_id": item["id"], "take_id": take["id"]})
    self.timelines.apply(pid, "trim", {"item_id": item["id"], "src_in": 1.0 / FPS if anchors else 0.0,
                                      "src_out": T.take_duration(take)})
    return {"shot": shot["id"], "take": take["id"]}


async def job_extend(self: EditorJobs, job: dict) -> dict:
    """Continua dopo un elemento, ripartendo dal suo ultimo fotogramma."""
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    tl = self.timelines.get(pid)
    idx, item = T._find(tl["video"], a["item_id"], "elemento")
    lay = T.layout(tl, prod)["items"][idx]
    start = self._frame(pid, prod, lay["end"] - 1.0 / FPS, "ext")
    shot = self._new_edit_shot(prod, a["prompt"], duration_s=float(a.get("seconds", 4.0)))
    take = await self._render(job, prod, shot, a["prompt"], float(a.get("seconds", 4.0)), init_image=str(start))
    _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": take["id"],
                                                       "index": idx + 1, "src_in": 1.0 / FPS})
    return {"shot": shot["id"], "item": ins["item"]}


async def job_insert(self: EditorJobs, job: dict) -> dict:
    """Nuovo tratto fra due elementi, agganciato alla fine del primo e all'inizio del secondo."""
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    tl = self.timelines.get(pid)
    index = int(a["index"])
    lay = T.layout(tl, prod)["items"]
    anchors = {}
    if index > 0:
        anchors["init_image"] = str(self._frame(pid, prod, lay[index - 1]["end"] - 1.0 / FPS, "ins_a"))
    if index < len(lay) and a.get("anchor_end", True):
        anchors["end_image"] = str(self._frame(pid, prod, lay[index]["start"], "ins_b"))
    shot = self._new_edit_shot(prod, a["prompt"], duration_s=float(a.get("seconds", 4.0)))
    take = await self._render(job, prod, shot, a["prompt"], float(a.get("seconds", 4.0)), **anchors)
    dur = T.take_duration(take)
    _, ins = self.timelines.apply(pid, "insert_item", {
        "shot_id": shot["id"], "take_id": take["id"], "index": index,
        "src_in": 1.0 / FPS if "init_image" in anchors else 0.0,
        "src_out": dur - (1.0 / FPS if "end_image" in anchors else 0.0)})
    return {"shot": shot["id"], "item": ins["item"]}


def _character(prod: dict, name: str) -> dict:
    ch = next((c for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name") == name), None)
    if ch is None:
        raise ValueError(f"personaggio sconosciuto: {name}")
    return ch


async def _dialogue_keyframe(self: EditorJobs, prod: dict, ch: dict, a: dict) -> Path:
    """Primo fotogramma del dialogo: il personaggio nell'inquadratura chiesta, nello stile del genere.

    Partire dall'immagine di riferimento non va: e' una scheda a figura intera su
    fondo neutro, che ritagliata in 16:9 mostrava solo il busto e il clip saltava
    dal bianco alla scena.
    """
    from core.modules.sigma_creative_lab.video import genres, image_gen
    action = a.get("action") or "close-up, speaking to camera"
    parts = [f"{ch['name']}, {action}", a.get("emotion") or "", "mouth slightly open, about to speak",
             a.get("setting") or "", a.get("ambience") or ""]
    shot = {"prompt": ", ".join(x for x in parts if x), "refs": [ch["name"]]}
    out = self.prods.path(prod["id"]) / "keyframes" / f"dialogue_{uuid.uuid4().hex[:8]}.png"
    model, prompt, refs = genres.keyframe_plan(prod, shot)
    r = await image_gen.generate(model, prompt, out, width=1344, height=768, seed=int(time.time()) % 100000,
                                 gpu=0, refs=refs)
    return Path(r["path"])


async def _dialogue_ltx(self: EditorJobs, job: dict, prod: dict, ch: dict, voice: Path) -> dict:
    """LTX-2.5: prima la voce, poi il video. La battuta si sintetizza con la voce del personaggio
    (controllata con Whisper) e LTX anima il personaggio su quell'audio, che resta intatto.

    Prova del 2026-10-11: battuta di 5,3 s con la voce "Narratrice calda", 24 s di sintesi e 57 s
    di video; Whisper sul clip finale rilegge la frase parola per parola e il labiale la segue.
    A differenza di H3 non serve la conversione vocale: l'audio e' gia' quello della voce scelta.
    """
    from core.modules.sigma_creative_lab.generators.adapters.comfy_ltx import ltx_frame_count
    from core.modules.sigma_creative_lab.video.production import probe
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    pid, a = job["production"], job["args"]
    text = a["text"].strip()
    clips = self.prods.path(pid) / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    line = clips / f"line_{uuid.uuid4().hex[:8]}.wav"
    self._note(job, f"Voce di {ch['name']}", 0.03)
    seconds = await asyncio.to_thread(_tts_checked, text, line, "chatterbox",
                                      {"voice_ref": str(voice), "exaggeration": 0.5, "cfg_weight": 0.5},
                                      int(time.time()) % 100000, a.get("language", "it"))
    await asyncio.to_thread(voice_runtime.unload)       # la GPU serve a LTX
    image = a.get("init_image")
    if not image or not Path(image).is_file():
        self._note(job, f"Primo fotogramma di {ch['name']}", 0.08)
        image = await _dialogue_keyframe(self, prod, ch, a)
    action = a.get("action") or "close-up, speaking to camera"
    emotion = a.get("emotion") or ""
    prompt = (f"{ch['name']}, {action}{', ' + emotion if emotion else ''}, says: \"{text}\" "
              f"Lips move clearly in sync with the words, natural facial expression and small head movements."
              f"{' Background: ' + a['ambience'] + '.' if a.get('ambience') else ''}")
    # Mezzo secondo d'aria dopo la battuta: il personaggio chiude la bocca prima del taglio.
    clip_s = seconds + 0.5
    shot = self._new_edit_shot(prod, prompt, duration_s=clip_s, refs=[ch["name"]],
                               dialogue={"character": ch["name"], "text": text, "audio": str(line)})
    take = await self._render(job, prod, shot, prompt, clip_s, judge_attempts=1, init_image=str(image),
                              audio=str(line), seed=int(time.time()) % 100000)
    take.update(frames=ltx_frame_count(clip_s))
    tr = await asyncio.to_thread(voice_runtime.transcribe, Path(take["clip_path"]), a.get("language", "it"))
    score = speech_match(text, tr["text"])
    take.update(heard=tr["text"], match=round(score, 3), kind="dialogue_voiced")
    real_frames = (await asyncio.to_thread(probe, Path(take["clip_path"])))["frames"] or take.get("frames")
    take["frames"] = real_frames
    self.prods.save(prod)
    index = int(a["index"]) if a.get("index") is not None else len(self.timelines.get(pid)["video"])
    _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": take["id"], "index": index})
    return {"shot": shot["id"], "item": ins["item"], "heard": tr["text"], "match": round(score, 3)}


async def job_dialogue(self: EditorJobs, job: dict) -> dict:
    """Inquadratura parlata: H3 dice la battuta col labiale, la conversione vocale fissa la voce.

    Prove del 2026-10-10: H3 pronuncia il testo esatto ma con un timbro solo
    simile al riferimento (0,81); la conversione Chatterbox porta a 0,93
    senza cambiare i tempi, quindi il labiale resta sincronizzato.
    """
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    ch = _character(prod, a["character"])
    text = a["text"].strip()
    voice = await asyncio.to_thread(_ensure_voice_sample, self, prod, ch)
    from core.modules.sigma_creative_lab.video.production import is_ltx
    if is_ltx(prod["settings"]):
        return await _dialogue_ltx(self, job, prod, ch, voice)
    if not ch.get("ref_image"):
        raise ValueError(f"{ch['name']} non ha un'immagine di riferimento: serve per il labiale (R2V)")
    action = a.get("action") or "close-up, speaking to camera"
    emotion = a.get("emotion") or ""
    prompt = (f"{ch['name']} from <Picture 1>, {action}{', ' + emotion if emotion else ''}, says with the voice of "
              f"<Audio 1>: \"{text}\" Lips clearly synchronized with the speech.\n"
              f"Audio: only {ch['name']}'s voice{', ' + a['ambience'] if a.get('ambience') else ''}, no music.")
    seconds = max(3.0, float(a.get("seconds") or (len(text.split()) / 2.6 + 1.2)))
    shot = self._new_edit_shot(prod, prompt, duration_s=seconds, refs=[ch["name"]], dialogue={"character": ch["name"],
                                                                                              "text": text})
    best = None
    for attempt in range(1, MAX_DIALOGUE_ATTEMPTS + 1):
        self._note(job, f"Tentativo {attempt}: generazione con labiale", 0.05)
        take = await self._render(job, prod, shot, prompt, seconds, judge_attempts=1, ref_images=[ch["ref_image"]],
                                  ref_audios=[str(voice)], seed=int(time.time()) % 100000 + attempt)
        clip = Path(take["clip_path"])
        speech = clip.with_suffix(".speech.wav")
        await asyncio.to_thread(_run, [ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-vn", "-ar", "24000",
                                       "-ac", "1", str(speech)])
        self._note(job, "Controllo della battuta (Whisper)", 0.92)
        tr = await asyncio.to_thread(voice_runtime.transcribe, speech, a.get("language", "it"))
        heard = tr["text"]
        score = speech_match(text, heard)
        take.update(heard=heard, match=round(score, 3))
        if best is None or score > best[0]:
            best = (score, take, speech, tr.get("words") or [])
        if score >= DIALOGUE_MATCH:
            break
        log.warning(f"battuta non riconosciuta ({score:.2f}): '{heard}'")
    score, take, speech, speech_words = best
    shot["take"] = take["id"]
    self._note(job, "Conversione nella voce del personaggio", 0.96)
    converted = speech.with_suffix(".voice.wav")
    report = await asyncio.to_thread(clean_conversion, speech, voice, converted, speech_words,
                                     a.get("language", "it"))
    take["voice_qa"] = report
    voiced = Path(take["clip_path"]).with_suffix(".voiced.mp4")
    # La voce convertita puo' uscire qualche centesimo piu' corta: con -shortest
    # da sola tagliava il video e la timeline aspettava frame che non esistono
    # (il player si bloccava). apad allunga l'audio col silenzio fino al video.
    await asyncio.to_thread(_run, [ffmpeg_bin(), "-v", "error", "-y", "-i", take["clip_path"], "-i", str(converted),
                                   "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "apad", "-c:a", "aac",
                                   "-b:a", "256k", "-shortest", str(voiced)])
    real_frames = (await asyncio.to_thread(probe, voiced))["frames"] or take.get("frames")
    final = T.add_take(shot, str(voiced), frames=real_frames, prompt=prompt, kind="dialogue_voiced",
                       heard=take.get("heard"), match=take.get("match"))
    self.prods.save(prod)
    await asyncio.to_thread(voice_runtime.unload)       # libera la GPU per il prossimo video
    index = int(a["index"]) if a.get("index") is not None else len(self.timelines.get(pid)["video"])
    _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": final["id"], "index": index})
    return {"shot": shot["id"], "item": ins["item"], "heard": take.get("heard"), "match": round(score, 3)}


MAX_VC_ATTEMPTS = 3
MAX_LINE_ATTEMPTS = 3
LINE_MATCH = 0.85


def clean_conversion(speech: Path, voice: Path, out: Path, speech_words: list[dict], language: str = "it") -> dict:
    """Conversione vocale senza parole rovinate.

    La conversione Chatterbox a volte spezza una parola (armoniche che saltano,
    tono che scivola): Whisper la riconosce ancora ma con molta meno sicurezza
    dell'originale. Si riprova con altri seed e si tiene il tentativo migliore;
    se una parola resta rovinata, in quel solo tratto torna il parlato originale
    di H3, che ha gli stessi tempi e quindi non sposta il labiale.
    """
    from core.modules.sigma_creative_lab.video import speech_qa
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    best = None
    for k in range(MAX_VC_ATTEMPTS):
        candidate = out.with_name(f"{out.stem}.try{k}{out.suffix}")
        voice_runtime.convert(speech, voice, candidate, seed=1000 + k)
        words = voice_runtime.transcribe(candidate, language).get("words") or []
        damaged = speech_qa.damaged_words(words, speech_words)
        if best is None or speech_qa.rank(words, damaged) > speech_qa.rank(best[1], best[2]):
            best = (candidate, words, damaged, k)
        if not damaged:
            break
        log.warning(f"conversione {k + 1}: parole rovinate {[w['word'] for w in damaged]}")
    candidate, words, damaged, k = best
    report = {"attempt": k + 1, "damaged": [{"word": w["word"], "p": w["p"], "ref_p": w.get("ref_p")}
                                            for w in damaged], "patched": []}
    if damaged:
        spans = speech_qa.regions(damaged)
        voice_runtime.splice(candidate, speech, spans, out)
        report["patched"] = spans
        log.warning(f"parole ancora rovinate dopo {MAX_VC_ATTEMPTS} conversioni: rimesso l'originale in {spans}")
    else:
        os.replace(candidate, out)
    for left in out.parent.glob(f"{out.stem}.try*{out.suffix}"):
        left.unlink(missing_ok=True)
    report["audio"] = voice_runtime.audio_check(out)
    return report


def _ensure_voice_sample(self: EditorJobs, prod: dict, ch: dict) -> Path:
    """Campione della voce del personaggio (vedi production.ensure_character_voice)."""
    from core.modules.sigma_creative_lab.video.production import ensure_character_voice
    return ensure_character_voice(self.prods, prod, ch)


async def job_voice_line(self: EditorJobs, job: dict) -> dict:
    """Battuta TTS (voce fuori campo o dialogo senza labiale) su una traccia audio."""
    from core.modules.sigma_creative_lab.voice.runtime import runtime_for, voice_runtime
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    text = a["text"].strip()
    opts = {"exaggeration": float(a.get("exaggeration", 0.5)), "cfg_weight": float(a.get("cfg_weight", 0.5))}
    if a.get("character"):
        ch = _character(prod, a["character"])
        sample = await asyncio.to_thread(_ensure_voice_sample, self, prod, ch)
        engine, opts["voice_ref"] = "chatterbox", str(sample)
    else:
        engine = a.get("engine") or "kokoro"
        opts["voice"] = a.get("voice") or "if_sara"
    out = self.prods.path(pid) / "voices" / f"line_{uuid.uuid4().hex[:8]}.wav"
    self._note(job, "Sintesi della voce", 0.3)
    if a.get("engine") == "qwen_clone" and a.get("character"):
        engine = "qwen_clone"                 # alternativa a Chatterbox, stessa voce del personaggio
    runtime = runtime_for(engine)
    from core.modules.sigma_creative_lab.video import speech_qa
    lang = a.get("language", "it")
    best = None
    for k in range(MAX_LINE_ATTEMPTS):
        self._note(job, f"Sintesi della voce{f' (tentativo {k + 1})' if k else ''}", 0.2 + 0.2 * k)
        candidate = out.with_name(f"{out.stem}.try{k}{out.suffix}")
        # Kokoro e' deterministico: un nuovo tentativo non cambierebbe nulla.
        seed_opts = {} if engine == "kokoro" else {"seed": 4242 + k * 7919}
        from core.modules.sigma_creative_lab.video.speech_text import to_spoken
        res = await asyncio.to_thread(runtime.synthesize, to_spoken(text), candidate, engine, **opts, **seed_opts)
        tr = await asyncio.to_thread(voice_runtime.transcribe, candidate, lang)
        words = tr.get("words") or []
        damaged = speech_qa.damaged_words(words)
        match = speech_match(text, tr["text"])
        issues = (await asyncio.to_thread(voice_runtime.audio_check, candidate)).get("issues") or []
        key = (match >= LINE_MATCH, not issues, *speech_qa.rank(words, damaged), match)
        if best is None or key > best[0]:
            best = (key, candidate, res, tr["text"], match, damaged, issues)
        if match >= LINE_MATCH and not damaged and not issues:
            break
        log.warning(f"battuta da rifare (corrispondenza {match:.2f}, parole {[w['word'] for w in damaged]}, {issues})")
        if engine == "kokoro":
            break
    _key, candidate, res, heard, match, damaged, issues = best
    os.replace(candidate, out)
    for left in out.parent.glob(f"{out.stem}.try*{out.suffix}"):
        left.unlink(missing_ok=True)
    kind = a.get("track", "voice")
    _, added = self.timelines.apply(pid, "audio_add", {
        "kind": kind, "src": str(out), "start": float(a.get("start", 0.0)), "label": (a.get("character") or "Voce") + ": " + text[:40],
        "meta": {"text": text, "character": a.get("character"), "engine": engine, "heard": heard,
                 "match": round(match, 3), "damaged": [w["word"] for w in damaged], "audio_issues": issues}})
    if damaged or issues:
        job["warning"] = f"battuta tenuta con difetti residui: {[w['word'] for w in damaged] or issues}"
    return {"clip": added["clip"], "duration": res["duration"], "heard": heard}


async def job_music_range(self: EditorJobs, job: dict) -> dict:
    """Musica per un tratto, sulla traccia musica."""
    from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
    from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
    from core.modules.sigma_creative_lab.video.soundtrack import DEFAULT_SOUNDTRACK, build_ace_step
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    t_a, t_b = sorted((float(a["t_a"]), float(a["t_b"])))
    cfg = {**DEFAULT_SOUNDTRACK, **(prod.get("soundtrack") or {})}
    tags = a.get("tags") or cfg["tags"] or (prod.get("bible") or {}).get("audio_style") or "cinematic score"
    url = await asyncio.to_thread(instances.ensure, 0)
    self._note(job, "Composizione", 0.3)
    graph = build_ace_step(tags, t_b - t_a, int(time.time()) % 100000, int(a.get("bpm") or cfg["bpm"]),
                           a.get("keyscale") or cfg["keyscale"], prefix=f"sigma/{pid}/music_edit")
    data, _ = await ComfyUIBackend(base_url=url, config={"timeout": 1800}).run({"workflow": graph}, timeout_s=1800)
    raw = self.prods.path(pid) / "music" / f"edit_{uuid.uuid4().hex[:8]}.raw"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(data)
    out = raw.with_suffix(".flac")
    await asyncio.to_thread(_run, [ffmpeg_bin(), "-v", "error", "-y", "-i", str(raw), "-t", f"{t_b - t_a:.3f}",
                                   "-ar", "48000", "-ac", "2", str(out)])
    raw.unlink(missing_ok=True)
    _, added = self.timelines.apply(pid, "audio_add", {"kind": "music", "src": str(out), "start": t_a,
                                                       "label": tags[:40]})
    return {"clip": added["clip"]}


async def job_export(self: EditorJobs, job: dict) -> dict:
    from core import paths
    from core.modules.sigma_creative_lab.video.export import export_timeline
    from core.modules.sigma_creative_lab.video.production import _slug
    pid = job["production"]
    prod = self.prods.get(pid)
    tl = self.timelines.get(pid)
    out = paths.creative_output_dir("video") / f"{_slug(prod['title'])}_{pid[-6:]}_v{tl.get('version', 0)}.mp4"
    await asyncio.to_thread(export_timeline, tl, prod, out, None, prod["settings"].get("final_codec", "libx264"),
                            int(prod["settings"].get("final_quality", 18)),
                            lambda m, p: self._note(job, m, p))
    prod = self.prods.get(pid)
    prod["output_path"] = str(out)
    self.prods.save(prod)
    return {"output_path": str(out)}


async def job_subtitles(self: EditorJobs, job: dict) -> dict:
    """Sottotitoli SRT dall'audio del video esportato."""
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    pid = job["production"]
    prod = self.prods.get(pid)
    video = Path(prod.get("output_path") or "")
    if not video.is_file():
        raise ValueError("esporta prima il video: i sottotitoli si ricavano dall'audio finale")
    self._note(job, "Trascrizione", 0.3)
    res = await asyncio.to_thread(voice_runtime.transcribe, video, job["args"].get("language", "it"))

    def ts(t: float) -> str:
        h, rem = divmod(t, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"

    lines = [f"{k}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}\n" for k, s in enumerate(res["segments"], 1)]
    out = video.with_suffix(".srt")
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"srt": str(out), "segments": len(lines)}


# ---------------------------------------------------------------------------
# Media dell'utente e cartelli
# ---------------------------------------------------------------------------

def _insert_index(tl: dict, prod: dict, t: float | None) -> int:
    """Dove inserire al cursore: dopo l'elemento sotto il cursore, prima se il cursore e' al suo inizio."""
    if t is None:
        return len(tl["video"])
    hit = T.locate(tl, prod, float(t))
    if not hit:
        return len(tl["video"])
    i, _src = hit
    item = T.layout(tl, prod)["items"][i]
    return i if float(t) - item["start"] < 0.15 else i + 1


def _media_shot(self: EditorJobs, prod: dict, label: str, origin: str, clip: dict, kind: str, **extra) -> dict:
    shot = self._new_edit_shot(prod, label, duration_s=clip["frames"] / FPS, **extra)
    shot["origin"] = origin
    T.add_take(shot, clip["clip_path"], frames=clip["frames"], prompt=label, kind=kind)
    shot["status"] = "done"
    return shot


def _export_size(prod: dict) -> tuple[int, int]:
    s = prod.get("settings") or {}
    h = max(int(s.get("output_height") or 0), 1080)
    w = int(round(h * int(s.get("width", 864)) / int(s.get("height", 480)) / 2) * 2)
    return w, h


async def job_import(self: EditorJobs, job: dict) -> dict:
    """File caricato dall'utente: video e immagini sulla traccia video, audio sulla sua traccia."""
    from core.modules.sigma_creative_lab.video import media_import as mi
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    src = Path(a["path"])
    imports = self.prods.path(pid) / "imports"
    if not src.is_file() or imports.resolve() not in src.resolve().parents:
        raise ValueError("file importato inesistente")
    kind = mi.kind_of(src)
    label = a.get("label") or src.stem.rsplit("_", 1)[0]
    if kind == "audio":
        track = a.get("track") if a.get("track") in ("voice", "dialogue", "music", "sfx") else "music"
        _, added = self.timelines.apply(pid, "audio_add", {"kind": track, "src": str(src),
                                                           "start": float(a.get("t") or 0.0), "label": label})
        return {"clip": added["clip"], "kind": kind}
    clips = self.prods.path(pid) / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    out = clips / f"import_{uuid.uuid4().hex[:8]}.mp4"
    if kind == "video":
        self._note(job, "Conversione del video", 0.2)
        clip = await asyncio.to_thread(mi.normalize_video, src, out)
    else:
        self._note(job, "Animazione dell'immagine", 0.2)
        clip = await asyncio.to_thread(mi.image_to_clip, src, out, float(a.get("seconds") or 4.0),
                                       _export_size(prod), a.get("motion") or "zoom_in")
    shot = _media_shot(self, prod, label, "import", clip, f"import_{kind}", source=str(src))
    self.prods.save(prod)
    tl = self.timelines.get(pid)
    _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": shot["take"],
                                                       "index": _insert_index(tl, prod, a.get("t"))})
    return {"shot": shot["id"], "item": ins["item"], "kind": kind}


async def job_title(self: EditorJobs, job: dict) -> dict:
    """Cartello a tutto schermo; sullo sfondo, se richiesto, la scena al cursore sfocata."""
    from core.modules.sigma_creative_lab.video import media_import as mi
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    title = str(a.get("title", "")).strip()
    if not title:
        raise ValueError("il titolo e' vuoto")
    clips = self.prods.path(pid) / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    out = clips / f"title_{uuid.uuid4().hex[:8]}.mp4"
    background_image = None
    if a.get("background") == "scene" and a.get("t") is not None:
        try:
            background_image = self._frame(pid, prod, float(a["t"]), "title_bg")
        except Exception as e:
            log.warning(f"sfondo del titolo dalla scena non disponibile: {e}")
    clip = await asyncio.to_thread(mi.title_card, out, title, str(a.get("sub", "")), float(a.get("seconds") or 3.5),
                                   _export_size(prod), a.get("color") or "#101418", background_image)
    shot = _media_shot(self, prod, title, "title", clip, "title", title={"title": title, "sub": a.get("sub", "")})
    self.prods.save(prod)
    tl = self.timelines.get(pid)
    _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": shot["take"],
                                                       "index": _insert_index(tl, prod, a.get("t"))})
    return {"shot": shot["id"], "item": ins["item"]}


async def job_scene(self: EditorJobs, job: dict) -> dict:
    """Scena didattica (formule, grafici, traiettorie, elenchi) scritta dal modello e resa dal browser."""
    from core.modules.sigma_creative_lab.video import scene_author
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    description = str(a.get("description", "")).strip()
    if not description:
        raise ValueError("descrivi cosa deve mostrare la scena")
    clips = self.prods.path(pid) / "clips"
    out = clips / f"scene_{uuid.uuid4().hex[:8]}.mp4"
    note = lambda msg, prog: self._note(job, msg, prog)  # noqa: E731
    author = scene_author.author_scene if a.get("mode") == "html" else scene_author.author_kit_scene
    res = await asyncio.to_thread(author, description, out, float(a.get("seconds") or 10.0), None, note)
    clip = {"clip_path": res["clip_path"], "frames": res["frames"]}
    shot = _media_shot(self, prod, description[:80], "scene", clip, "scene", scene="Scena didattica",
                       teaching={"description": description})
    self.prods.save(prod)
    tl = self.timelines.get(pid)
    _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": shot["take"],
                                                       "index": _insert_index(tl, prod, a.get("t"))})
    return {"shot": shot["id"], "item": ins["item"], "attempts": res.get("attempts")}


async def job_scene_redo(self: EditorJobs, job: dict) -> dict:
    """Nuova versione di una scena didattica, stessa durata dell'elemento (la voce resta allineata)."""
    from core.modules.sigma_creative_lab.video import scene_author
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    tl = self.timelines.get(pid)
    _idx, item = T._find(tl["video"], a["item_id"], "elemento")
    shot = T.shot_by_id(prod, item["shot_id"])
    if shot is None or shot.get("origin") != "scene":
        raise ValueError("l'elemento non e' una scena didattica")
    scene = shot.get("teaching") or {}
    description = str(a.get("description") or scene.get("description") or "").strip()
    context = f"\n(Context, the narrator says: \"{scene['narration']}\")" if scene.get("narration") else ""
    out = self.prods.path(pid) / "clips" / f"scene_{uuid.uuid4().hex[:8]}.mp4"
    note = lambda msg, prog: self._note(job, msg, prog)  # noqa: E731
    res = await asyncio.to_thread(scene_author.author_kit_scene, description + context, out,
                                  float(item["src_out"] - item["src_in"]), None, note)
    take = T.add_take(shot, res["clip_path"], frames=res["frames"], prompt=description, kind="scene")
    shot["teaching"] = {**scene, "description": description}
    self.prods.save(prod)
    self.timelines.apply(pid, "set_take", {"item_id": item["id"], "take_id": take["id"]})
    self.timelines.apply(pid, "trim", {"item_id": item["id"], "src_in": 0.0, "src_out": res["frames"] / FPS})
    return {"shot": shot["id"], "take": take["id"]}


def _tts_checked(text: str, out: Path, engine: str, opts: dict, seed: int, language: str = "it") -> float:
    """Narrazione senza parole inventate: simboli detti a parole, velocita' plausibile, trascrizione fedele.

    In una lezione di prova "c² = a² + b²" letto alla lettera ha prodotto 25 s di
    parlato senza senso per una frase di 13 parole. Ritorna la durata del parlato.
    """
    from core.modules.sigma_creative_lab.video.production import probe
    from core.modules.sigma_creative_lab.video.speech_text import plausible_duration, to_spoken
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    spoken = to_spoken(text)
    best = None
    for k in range(MAX_LINE_ATTEMPTS):
        candidate = out.with_name(f"{out.stem}.try{k}{out.suffix}")
        extra = {} if engine == "kokoro" else {"seed": seed + k * 7919}
        voice_runtime.synthesize(spoken, candidate, engine, **opts, **extra)
        seconds = probe(candidate)["audio_duration"]
        heard = voice_runtime.transcribe(candidate, language)["text"]
        match = speech_match(spoken, heard)
        ok = match >= LINE_MATCH and plausible_duration(spoken, seconds)
        key = (ok, match)
        if best is None or key > best[0]:
            best = (key, candidate, seconds)
        if ok or engine == "kokoro":
            break
        log.warning(f"narrazione da rifare ({match:.2f}, {seconds:.1f} s): {heard[:120]}")
    _key, candidate, seconds = best
    os.replace(candidate, out)
    for left in out.parent.glob(f"{out.stem}.try*{out.suffix}"):
        left.unlink(missing_ok=True)
    return seconds


async def job_lesson(self: EditorJobs, job: dict) -> dict:
    """Lezione intera: copione, narrazione per capitolo, scena lunga quanto la narrazione, montaggio.

    Ogni capitolo entra in coda alla timeline con la sua voce sulla traccia
    "Voce fuori campo"; alla fine i sottotitoli si possono generare come sempre.
    """
    from core.modules.sigma_creative_lab.video import lesson, scene_author
    from core.modules.sigma_creative_lab.video.production import probe
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    pid, a = job["production"], job["args"]
    prod = self.prods.get(pid)
    topic = str(a.get("topic", "")).strip()
    if not topic:
        raise ValueError("indica l'argomento della lezione")
    self._note(job, "Scrittura del copione", 0.03)
    plan = await asyncio.to_thread(lesson.plan_lesson, topic, float(a.get("minutes") or 1.0),
                                   str(a.get("audience") or "studenti delle superiori"))
    voice_sample = ""
    if a.get("voice_id"):
        try:
            from core.modules.sigma_voice_studio import library
            v = library.get(str(a["voice_id"]))
            voice_sample = v["sample"] if v else ""
        except ImportError:
            voice_sample = ""
    clips = self.prods.path(pid) / "clips"
    voices = self.prods.path(pid) / "voices"
    voices.mkdir(parents=True, exist_ok=True)
    n = len(plan["chapters"])
    done = []
    for k, ch in enumerate(plan["chapters"], 1):
        base = 0.05 + 0.9 * (k - 1) / n
        self._note(job, f"Capitolo {k}/{n}: voce", base)
        line = voices / f"lesson_{uuid.uuid4().hex[:8]}.wav"
        if voice_sample:
            engine, opts = "chatterbox", {"voice_ref": voice_sample, "exaggeration": 0.4}
        else:
            engine, opts = "kokoro", {"voice": str(a.get("kokoro_voice") or "if_sara")}
        speech_s = await asyncio.to_thread(_tts_checked, ch["narration"], line, engine, opts, 4242 + k)
        self._note(job, f"Capitolo {k}/{n}: scena", base + 0.3 / n)
        out = clips / f"lesson_{uuid.uuid4().hex[:8]}.mp4"
        # La scena dura quanto la voce, con un respiro in fondo prima del capitolo dopo.
        desc = (f"{ch['visual']}\n(Context, the narrator says: \"{ch['narration']}\". "
                f"Title of the lesson: {plan['title']})")
        try:
            res = await asyncio.to_thread(scene_author.author_kit_scene, desc, out, speech_s + 0.8)
        except RuntimeError as e:
            # Un capitolo non riuscito non deve buttare la lezione: il suo testo in elenco,
            # e l'avviso nel lavoro per rifarlo dall'editor.
            from core.modules.sigma_creative_lab.video import scene_kit
            from core.modules.sigma_creative_lab.video.html_scene import render_scene
            log.warning(f"capitolo {k}: scena di ripiego ({e})")
            spec = {"title": plan["title"], "duration": speech_s + 0.8,
                    "blocks": [{"type": "bullets", "items": [ch["narration"]], "start": 0.3}]}
            res = await asyncio.to_thread(render_scene, scene_kit.to_html(spec), out, speech_s + 0.8)
            job["warning"] = (job.get("warning", "") + f" capitolo {k}: scena semplificata;").strip()
        clip = {"clip_path": res["clip_path"], "frames": res["frames"]}
        shot = _media_shot(self, prod, ch["visual"][:80], "scene", clip, "scene",
                           scene=f"Capitolo {k}",
                           teaching={"description": ch["visual"], "narration": ch["narration"]})
        self.prods.save(prod)
        tl = self.timelines.get(pid)
        index = len(tl["video"])
        _, ins = self.timelines.apply(pid, "insert_item", {"shot_id": shot["id"], "take_id": shot["take"], "index": index})
        start = T.layout(self.timelines.get(pid), self.prods.get(pid))["items"][index]["start"]
        self.timelines.apply(pid, "audio_add", {"kind": "voice", "src": str(line), "start": start + 0.3,
                                                "label": f"Narrazione {k}", "meta": {"text": ch["narration"]}})
        done.append(ins["item"])
        prod = self.prods.get(pid)
    await asyncio.to_thread(voice_runtime.unload)
    return {"title": plan["title"], "chapters": n, "items": done}


CPU_KINDS = {"import", "title"}

HANDLERS = {
    "regen_range": job_regen_range, "redo": job_redo, "extend": job_extend, "insert": job_insert,
    "dialogue": job_dialogue, "voice_line": job_voice_line, "music_range": job_music_range,
    "export": job_export, "subtitles": job_subtitles, "import": job_import, "title": job_title,
    "scene": job_scene, "lesson": job_lesson, "scene_redo": job_scene_redo,
}

_editor: EditorJobs | None = None
_editor_lock = threading.Lock()


def editor_jobs() -> EditorJobs:
    global _editor
    with _editor_lock:
        if _editor is None:
            from core.modules.sigma_creative_lab.video.production import manager
            _editor = EditorJobs(manager.store, manager)
        return _editor
