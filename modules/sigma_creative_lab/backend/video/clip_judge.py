"""Giudice delle clip: un modello di visione guarda la sequenza e dice se va rifatta.

Il controllo tecnico (postprocess.quality_check) trova clip nere, congelate o
rovinate, ma non vede che un personaggio "sale" le scale camminando
all'indietro o che la lanterna galleggia invece di essere tenuta in mano.
Per quello serve un modello che legga i fotogrammi *in ordine* e confronti
l'azione con la descrizione dell'inquadratura.

Qwen3-VL 8B (Apache 2.0) gira in un llama-server dedicato, per default sulla
CPU: le GPU restano alle corsie di render e il giudizio di una clip si
sovrappone al render della successiva invece di fermarlo.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests

from core import paths
from core.logger import get_logger

log = get_logger("creative_clip_judge")

PORT = 8096
IS_WINDOWS = sys.platform.startswith("win")
FRAMES = 8
FRAME_WIDTH = 640
#: Sotto questa soglia la clip si rifa'. Il modello e' prudente: 0.6 boccia gli
#: errori evidenti (azione assente, movimento invertito) senza inseguire i dettagli.
PASS_SCORE = 0.6
IDLE_UNLOAD_S = 600

# Tre passaggi invece di uno. Chiedendo direttamente "la clip mostra X?" il
# modello vede X anche quando non c'e' (una clip in cui il guardiano sale le
# scale all'indietro ha preso 1.0). Chi osserva non deve sapere cosa
# aspettarsi: prima si ricavano dall'intento domande neutre, poi si risponde
# guardando i fotogrammi, infine si confrontano le risposte con l'intento.

PLAN_PROMPT = """A short AI-generated video clip was supposed to show:
<<{intent}>>

A reviewer will look at its frames WITHOUT knowing this description. Write 3 to 5 neutral questions to answer for \
every frame that would reveal whether the clip is right and whether the motion is physically natural. \
Ask about observable facts: where the main subject is relative to the key objects, which way the body and face \
point (toward the camera, away, toward an object), what the feet and hands touch, what supports any held or \
hanging object. Never reveal the expected answer (ask "where is the person relative to the stairs?", \
not "is the person climbing the stairs?").
Also split the description in two: "action" = what the subjects and the scene do, with NO camera wording at all \
(no push-in, zoom, pan, closer, "the scene moves", "we see"); "camera" = the requested camera movement, or "" \
if none. Example: "A castle at dawn, slow zoom in" -> action "A castle at dawn", camera "slow zoom in".
Reply ONLY with JSON: {{"action": "...", "camera": "...", "questions": ["...", "..."]}}"""

OBSERVE_PROMPT = """These {n} images are consecutive frames of one short video clip, in time order \
(about {step:.1f} s apart).
For EACH frame answer every question below, literally, describing only what is visible:
{questions}
Format: one line per frame, "Frame 1: answer; answer; ...", at most 18 words per frame. Look at each frame on its own: if something changed from the previous frame, say what.
Then add:
FIRST VS LAST: compare frame 1 and frame {n}: is the main subject higher, lower or at the same height relative \
to the objects around it (stairs, ground, furniture)? closer or farther from them? facing the same way or turned?
CAMERA: how the camera moves (static, pans, pushes in, pulls back...).
SUBJECT MOTION: how the main subject moves relative to the scene, not to the frame (a camera pulling back is \
not the subject moving). Say explicitly if anyone moves backwards, slides without stepping, or if any object \
floats without support.
ODDITIES: anything physically impossible or deformed, or "none"."""

VERDICT_PROMPT = """An AI-generated video clip was supposed to show:
<<{intent}>>
Requested camera movement (judged separately, never part of the main action): <<{camera}>>

A reviewer who did NOT know that description watched the frames and wrote:
<<{observations}>>

Answer strictly from the observations, with true or false:
- main_action_happens: the subject really performs the requested main action (for a description with no acting \
subject: the requested scene content is there). Standing still, or doing a different action, is false. \
A missing or different camera movement never makes this false.
- wrong_direction: the subject moves the opposite way (down instead of up, away instead of toward, backwards).
- physically_impossible: objects float without support, bodies pass through things, limbs or faces deform.
- camera_as_requested: the camera moves as requested (true if no camera move was requested).
Reply ONLY with JSON:
{{"seen": "what actually happens, one sentence",
 "main_action_happens": true,
 "wrong_direction": false,
 "physically_impossible": false,
 "camera_as_requested": true,
 "anatomy_ok": true,
 "quality": 0.0,
 "issues": ["short description of each problem"],
 "prompt_fix": "one short English sentence to add to the generation prompt so the action comes out right, or empty"}}
quality: overall match with the description, from 0.0 to 1.0."""

#: Modelli in ordine di preferenza sulla CPU: il 30B-A3B ha 3B parametri attivi
#: e costa poco piu' dell'8B. Su GPU si preferisce l'8B (vedi model_files).
MODELS = (
    ("Qwen--Qwen3-VL-30B-A3B-Instruct-GGUF", "Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf",
     "mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf"),
    ("Qwen--Qwen3-VL-8B-Instruct-GGUF", "Qwen3VL-8B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-8B-Instruct-F16.gguf"),
)


HELD_PROMPT = """These {n} images are frames from one video clip (start, middle, end).
For EACH image answer: is a {obj} visible in a person's hand?
Reply ONLY with JSON: {{"frames": [true, false, ...]}} with one value per image, in order."""

_DETERMINERS = re.compile(r"(?:^|\s)(?:the|a|an|his|her|their|its)\s|,|;|\band\b", re.I)


IMAGE_PROMPT = """This image is the FIRST frame of a video shot that should show:
<<{intent}>>
Answer with true or false, strictly from what you see:
- start_ok: the image shows the scene and subject as the shot begins (right place, right subject, facing and \
framing compatible with the action and camera described).
- one_each: each character appears only once (no duplicated person, no giant face floating in the sky).
- objects_ok: every object the description puts in someone's hand is actually held in a hand.
- clean: no deformed hands, faces or limbs, no garbled text.
Reply ONLY with JSON: {{"seen": "one sentence", "start_ok": true, "one_each": true, "objects_ok": true, "clean": true, \
"fix": "short English phrase to add to the image prompt to fix the problems, or empty"}}"""


COUNT_PROMPT = """Look carefully at the WHOLE image, foreground and background. Count how many of each of these are
visible (0 if none). Count each figure once, in the list item it fits best.
{items}
Reply ONLY with JSON: {{"counts": [numbers in the same order]}}"""


DESCRIBE_CHARACTER_PROMPT = """Describe the main character in this image for an artist who must draw them again in
other scenes. One English line of comma-separated visual traits only: apparent age and gender, body type, face,
hair (color, length, style), eye color, clothing with colors, distinctive accessories or marks. No names, no story,
no background, no art-style words. Reply ONLY with JSON: {"description": "..."}"""

SAME_CHARACTER_PROMPT = """The image has two panels. LEFT panel: the reference of a character: <<{description}>>.
RIGHT panel: it should show the SAME character, drawn as: <<{view}>>.
Compare identity: hair color and style, face, clothing and its colors, accessories. Facial expression, pose and camera angle are NOT identity differences.
view_ok: true only if the RIGHT panel really shows the requested view (a side view shows the character in profile,
a rear view shows their back and hides the face; a front or three-quarter view is NOT a side or rear view).
Reply ONLY with JSON: {{"same": true, "view_ok": true, "differences": ["short English phrase for each visible identity difference"], "fix": "short English phrase to add to the prompt to fix them, or empty"}}"""


SCENE_REVIEW_PROMPT = """These {n} images are frames (start to end) of an animated teaching slide that should show:
<<{intent}>>
Review them like a strict teacher preparing a lesson video. Report only real, visible problems:
plots or diagrams missing, wrong or invisible (e.g. a straight line where a curve is expected, white boxes on the
dark page), text overlapping or cut off by the frame edge, unreadable contrast, formulas shown as raw code.
Reply ONLY with JSON: {{"ok": true, "problems": ["short English description of each problem"]}}"""


def held_objects(intent: str) -> list[str]:
    """Oggetti che il prompt mette in mano a qualcuno ("the oil lamp held in his right hand", "holding a cloth").

    Regole fisse e non il modello: chiedere al modello di elencarli cambiava anche
    le altre sue risposte e rendeva instabile il giudizio.
    """
    found = []
    for m in re.finditer(r"\bheld in (?:his|her|their|the)\b", intent, re.I):
        before = intent[:m.start()].rstrip()
        cut = [x.end() for x in _DETERMINERS.finditer(before)]
        found.append(before[cut[-1] if cut else 0:].strip())
    for m in re.finditer(r"\bholding (?:a|an|the|his|her|their)\s+([a-z-]+(?:\s+[a-z-]+){0,2}?)"
                         r"(?=\s+(?:in|while|and|with|as|up|over|toward|towards)\b|[,.;]|$)", intent, re.I):
        found.append(m.group(1))
    out = []
    for obj in found:
        words = obj.split()[-3:]
        obj = " ".join(words).strip(" ,.;")
        if obj and len(obj) < 40 and obj.lower() not in (o.lower() for o in out):
            out.append(obj)
    return out


def model_files(device: str = "cpu") -> tuple[Path, Path] | None:
    # Prova del 2026-10-11 col protocollo in tre passaggi: l'8B interamente in
    # VRAM giudica una clip in ~8 s e boccia la salita delle scale all'indietro
    # che il 30B su CPU (~85 s) promuoveva. Il 30B non entra in una GPU da 8-16 GB.
    order = sorted(MODELS, key=lambda m: "8B" not in m[0]) if device.startswith("gpu:") else MODELS
    for folder, model, mmproj in order:
        base = paths.models_dir() / folder
        if (base / model).is_file() and (base / mmproj).is_file():
            return base / model, base / mmproj
    return None


def installed() -> bool:
    return model_files() is not None


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("il giudice non ha risposto in JSON")
    return json.loads(text[start:end + 1])


def _flag(raw: dict, key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "si", "1")
    return bool(value)


def verdict_from(raw: dict, threshold: float = PASS_SCORE) -> dict:
    """Riduce la risposta del modello a un punteggio e a un esito.

    Le bocciature si decidono qui con regole fisse sulle risposte si'/no: con
    un voto numerico libero il modello finiva per dare 0.7 a una clip che lui
    stesso descriveva come "scende le scale" invece di salirle.
    """
    def num(key: str, default: float = 0.0) -> float:
        try:
            return max(0.0, min(1.0, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default
    if "main_action_happens" in raw:
        action = _flag(raw, "main_action_happens", True)
        wrong_dir = _flag(raw, "wrong_direction", False)
        impossible = _flag(raw, "physically_impossible", False)
        camera_ok = _flag(raw, "camera_as_requested", True)
        # Con azione presente e nessun difetto grave la clip passa: quality serve
        # solo a ordinare i tentativi, non a bocciare per sfumature.
        score = num("quality", 0.8)
        floor = action and not (wrong_dir or impossible)
        if not action:
            score = min(score, 0.3)
        if wrong_dir or impossible:
            score = min(score, 0.2)
        intent, motion = (score if action else 0.3), (0.2 if (wrong_dir or impossible) else 1.0)
    else:
        # Formato con soli voti numerici (giudizi salvati prima di questa versione).
        intent, motion = num("intent_match"), num("motion_natural")
        camera_ok, score, floor = True, min(intent, motion), False
    anatomy = _flag(raw, "anatomy_ok", True)
    # La camera pesa poco: una carrellata mancata non rende la clip sbagliata, e
    # bocciarla per quello brucerebbe minuti di render senza migliorare nulla.
    score *= (1.0 if anatomy else 0.7) * (1.0 if camera_ok else 0.85)
    if "main_action_happens" in raw and floor and anatomy:
        score = max(score, threshold + 0.05)
    issues = [str(x) for x in raw.get("issues") or [] if str(x).strip()]
    # Grave = da rifare comunque: direzione sbagliata, fisica impossibile (oggetti che spariscono),
    # corpi deformi. Un'azione appena accennata non lo e': decide l'utente.
    severe = motion <= 0.2 or not anatomy
    return {"ok": score >= threshold, "score": round(score, 3), "intent_match": intent, "motion_natural": motion,
            "camera_ok": camera_ok, "anatomy_ok": anatomy, "severe": severe, "seen": str(raw.get("seen", "")),
            "issues": issues, "prompt_fix": str(raw.get("prompt_fix", "")).strip()}


def sample_frames(clip: Path, out_dir: Path, n: int = FRAMES, src_in: float = 0.0,
                  src_out: float | None = None, phase: float = 0.5) -> tuple[list[Path], float]:
    """n fotogrammi equidistanti nel tratto [src_in, src_out] del clip, e la durata del tratto."""
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    end = src_out if src_out is not None else probe(clip)["duration"]
    span = max(0.1, end - src_in)
    frames = []
    for k in range(n):
        # Centro di ciascuno degli n intervalli: evita il primo e l'ultimo frame
        # esatti, che nei clip H3 possono essere frame di raccordo.
        t = src_in + span * (k + phase) / n
        out = out_dir / f"f{int(phase * 100):02d}_{k:02d}.jpg"
        _run([ffmpeg_bin(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1",
              "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "3", str(out)], timeout=60)
        frames.append(out)
    return frames, span


class ClipJudge:
    def __init__(self):
        self.url = f"http://127.0.0.1:{PORT}"
        self._proc: subprocess.Popen | None = None
        self._device = ""
        self._model = ""
        self._lock = threading.Lock()          # un giudizio alla volta: un solo slot nel server
        self._last_use = 0.0
        self._reaper: threading.Thread | None = None

    # --- processo ---------------------------------------------------------

    def _alive(self) -> bool:
        try:
            return requests.get(f"{self.url}/health", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def _start(self, device: str) -> None:
        from core.engine.backends.llamaserver_backend import _assign_kill_on_close
        from core.engine.llama_runtime import installed_server
        server = installed_server()
        if server is None:
            raise RuntimeError("llama-server non installato (Model Hub → runtime GGUF)")
        model, mmproj = model_files(device)
        self._model = model.name
        cmd = [str(server), "-m", str(model), "--mmproj", str(mmproj), "--host", "127.0.0.1", "--port", str(PORT),
               "-c", "8192", "-np", "1", "--temp", "0", "--no-webui"]
        env = dict(os.environ)
        if device.startswith("gpu:"):
            # Il processo vede solo la sua GPU: vedendole entrambe, l'allocatore VMM di CUDA
            # falliva ("device not ready") mentre ComfyUI lavorava sull'altra scheda.
            env["CUDA_VISIBLE_DEVICES"] = device.split(":", 1)[1]
            cmd += ["--device", "CUDA0", "-ngl", "99"]
            if "A3B" in model.name:
                # Gli esperti MoE restano in RAM: in VRAM vanno solo attenzione,
                # cache e proiettore visivo (pochi GB), cosi' il giudice entra
                # anche nella 5060 da 8 GB accanto a nient'altro.
                cmd += ["--cpu-moe"]
        else:
            # Su CPU anche il proiettore visivo: senza --no-mmproj-offload
            # llama-server lo metterebbe comunque sulla GPU 0, quella dei render.
            cmd += ["--device", "none", "-ngl", "0", "--no-mmproj-offload"]
        log_path = paths.var_dir() / "logs" / "sigma_clip_judge.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        with open(log_path, "ab") as out:
            self._proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, creationflags=flags,
                                          cwd=str(server.parent), env=env)
        _assign_kill_on_close(self._proc)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"il giudice delle clip e' terminato all'avvio; vedi {log_path}")
            if self._alive():
                self._device = device
                # Senza questo il reaper vedrebbe un server "inattivo da sempre" e lo
                # spegnerebbe fra l'avvio e la prima richiesta.
                self._last_use = time.monotonic()
                log.info(f"giudice delle clip pronto su {device}")
                return
            time.sleep(1)
        self.stop()
        raise TimeoutError("il giudice delle clip non risponde")

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _ensure(self, device: str) -> None:
        files = model_files(device)
        if (self._proc and self._proc.poll() is None and self._device == device and files
                and files[0].name == self._model and self._alive()):
            return
        if self._alive() and not self._proc:
            # Un altro processo Sigma (es. una seconda istanza) ha gia' un giudice su
            # questa porta: se e' il nostro llama-server lo si sostituisce, altrimenti no.
            if not self._kill_foreign_judge():
                raise RuntimeError(f"la porta {PORT} e' occupata da un altro servizio")
        self.stop()
        self._start(device)
        if not self._reaper or not self._reaper.is_alive():
            self._reaper = threading.Thread(target=self._reap_idle, name="clip-judge-idle", daemon=True)
            self._reaper.start()

    @staticmethod
    def _kill_foreign_judge() -> bool:
        try:
            import psutil
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == PORT and conn.status == psutil.CONN_LISTEN and conn.pid:
                    proc = psutil.Process(conn.pid)
                    cmd = " ".join(proc.cmdline()).lower()
                    if "llama-server" in cmd and "qwen3vl" in cmd and f"--port {PORT}" in cmd:
                        proc.kill()
                        proc.wait(timeout=10)
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            try:
                                requests.get(f"http://127.0.0.1:{PORT}/health", timeout=1)
                            except requests.RequestException:
                                return True
                            time.sleep(0.5)
                        return True
        except Exception as e:
            log.warning(f"giudice sulla porta {PORT} non sostituito: {e}")
        return False

    def _reap_idle(self) -> None:
        # Fra una produzione e l'altra il modello occuperebbe ~7 GB di RAM per niente.
        while self._proc is not None:
            time.sleep(30)
            if self._lock.acquire(blocking=False):
                try:
                    if self._proc and time.monotonic() - self._last_use > IDLE_UNLOAD_S:
                        log.info("giudice delle clip inattivo: scaricato")
                        self.stop()
                finally:
                    self._lock.release()

    # --- giudizio ---------------------------------------------------------

    def _chat(self, content, max_tokens: int) -> str:
        # Seed fisso e niente cache del prompt: con la cache lo stesso input dava
        # a volte risposte diverse, e un giudizio deve essere ripetibile.
        body = {"messages": [{"role": "user", "content": content}], "temperature": 0, "seed": 1234,
                "cache_prompt": False, "max_tokens": max_tokens}
        try:
            resp = requests.post(f"{self.url}/v1/chat/completions", timeout=600, json=body)
        except requests.ConnectionError:
            # Server caduto a meta' richiesta: un riavvio e un secondo tentativo, poi l'errore sale.
            log.warning("giudice caduto durante una richiesta: riavvio")
            device = self._device or "cpu"
            self.stop()
            self._ensure(device)
            resp = requests.post(f"{self.url}/v1/chat/completions", timeout=600, json=body)
        resp.raise_for_status()
        return re.sub(r"<think>.*?</think>", "", resp.json()["choices"][0]["message"]["content"], flags=re.S).strip()

    def judge(self, clip: Path, intent: str, device: str = "cpu", threshold: float = PASS_SCORE,
              src_in: float = 0.0, src_out: float | None = None, passes: int = 2) -> dict:
        """Giudizio prudente: piu' sguardi su fotogrammi sfalsati, vale il peggiore.

        Lo stesso modello, sulla stessa clip, a volte vede il difetto e a volte
        no (le scale salite all'indietro: 0.9 in un'esecuzione, 0.17 nella
        successiva). Basta che uno sguardo veda un errore grave per rifarla.
        """
        if not installed():
            raise RuntimeError("giudice non installato (Video Studio → Motori → Qwen3-VL)")
        phases = (0.5, 0.15, 0.85)[:max(1, min(3, int(passes)))]
        with tempfile.TemporaryDirectory(prefix="sigma_judge_") as tmp:
            looks = []
            for phase in phases:
                frames, span = sample_frames(Path(clip), Path(tmp), FRAMES, src_in, src_out, phase)
                looks.append(([{"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()}} for f in frames],
                    span / len(frames)))
            with self._lock:
                self._ensure(device)
                t0 = time.monotonic()
                action, camera, questions = self._plan(intent)
                verdicts = []
                for images, step in looks:
                    observations = self._chat(images + [{"type": "text", "text": OBSERVE_PROMPT.format(
                        n=len(images), step=step, questions="\n".join(f"- {q}" for q in questions))}], 600)
                    text = self._chat(VERDICT_PROMPT.format(intent=action, camera=camera,
                                                            observations=observations), 400)
                    try:
                        v = verdict_from(_extract_json(text), threshold)
                    except ValueError as e:
                        log.warning(f"giudizio illeggibile per {Path(clip).name}: {e}: {text[:200]}")
                        continue
                    v["observations"] = observations
                    verdicts.append(v)
                    if not v["ok"]:
                        break                     # un errore grave basta: inutile guardare ancora
                self._last_use = time.monotonic()
            if verdicts and verdicts[-1]["ok"]:
                vanished = self._vanished_objects(intent, Path(clip), src_in, src_out, tmp, device)
                if vanished:
                    v = verdicts[-1]
                    v.update(ok=False, score=min(v["score"], 0.2), issues=v["issues"] + [
                        f"the {o} disappears from the hand during the shot" for o in vanished],
                        prompt_fix=f"The {vanished[0]} stays in his hand for the whole shot.")
        if not verdicts:
            # Risposte illeggibili non devono bocciare la clip: il giudice e' un
            # aiuto, non un cancello che blocca la produzione.
            return {"ok": True, "score": None, "issues": [], "seen": "", "prompt_fix": "", "error": "illeggibile"}
        verdict = min(verdicts, key=lambda v: v["score"])
        verdict.update(seconds=round(time.monotonic() - t0, 1), questions=questions, model=self._model,
                       looks=[round(v["score"], 3) for v in verdicts])
        log.info(f"giudizio {Path(clip).name}: {verdict['score']} {verdict['looks']} ({verdict['seen'][:120]})")
        return verdict

    def judge_image(self, image: Path, intent: str, device: str = "cpu") -> dict:
        """Controllo di un fotogramma chiave prima che H3 lo animi.

        Un primo fotogramma sbagliato (personaggio rivolto dalla parte opposta
        all'azione, lanterna che fluttua, persona duplicata) obbliga il video a
        un movimento innaturale per rimediare: conviene ridisegnarlo, costa pochi secondi.
        """
        if not installed():
            raise RuntimeError("giudice non installato")
        # Ridotta come i fotogrammi dei video: a 1344x768 il codificatore visivo
        # esauriva la memoria della GPU da 8 GB ("failed to allocate graph").
        import io
        from PIL import Image
        img = Image.open(image).convert("RGB")
        img.thumbnail((FRAME_WIDTH, FRAME_WIDTH))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        content = [{"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": IMAGE_PROMPT.format(intent=intent.strip())}]
        with self._lock:
            self._ensure(device)
            text = self._chat(content, 200)
            self._last_use = time.monotonic()
        try:
            raw = _extract_json(text)
        except ValueError:
            return {"ok": True, "score": None, "issues": [], "fix": ""}
        checks = {k: _flag(raw, k, True) for k in ("start_ok", "one_each", "objects_ok", "clean")}
        names = {"start_ok": "start of the action does not match", "one_each": "character duplicated",
                 "objects_ok": "held object not in the hand", "clean": "deformations"}
        issues = [names[k] for k, v in checks.items() if not v]
        return {"ok": not issues, "score": round(sum(checks.values()) / 4, 2), "issues": issues,
                "seen": str(raw.get("seen", "")), "fix": str(raw.get("fix", "")).strip()}

    def count_kinds(self, image: Path, kinds: list[str], device: str = "cpu") -> list[int] | None:
        """Quante figure di ogni tipo ci sono nell'immagine.

        La domanda "ogni personaggio compare una volta?" l'8B la passava sempre (prova del picnic:
        due Lia in cinque fotogrammi su ventidue); contare per tipo e' una domanda che sa fare.
        """
        if not installed() or not kinds:
            return None
        items = "\n".join(f"{k}. {kind}" for k, kind in enumerate(kinds, 1))
        with self._lock:
            self._ensure(device)
            text = self._chat([self._image_part(image), {"type": "text", "text": COUNT_PROMPT.format(items=items)}], 80)
            self._last_use = time.monotonic()
        try:
            counts = _extract_json(text).get("counts")
        except (ValueError, AttributeError):
            return None
        if not isinstance(counts, list) or len(counts) != len(kinds):
            return None
        try:
            return [max(0, int(c)) for c in counts]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _image_part(image, max_side: int = FRAME_WIDTH) -> dict:
        import io
        from PIL import Image
        img = image if isinstance(image, Image.Image) else Image.open(image).convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}

    def describe_character(self, image: Path, device: str = "cpu") -> str:
        """Aspetto di un personaggio da una foto o un disegno, come prompt per ridisegnarlo."""
        if not installed():
            raise RuntimeError("giudice non installato")
        content = [self._image_part(image), {"type": "text", "text": DESCRIBE_CHARACTER_PROMPT}]
        with self._lock:
            self._ensure(device)
            text = self._chat(content, 200)
            self._last_use = time.monotonic()
        try:
            return str(_extract_json(text).get("description", "")).strip()
        except ValueError:
            return text.strip().splitlines()[0] if text.strip() else ""

    def same_character(self, reference: Path, image: Path, description: str, view: str,
                       device: str = "cpu") -> dict:
        """La vista di un model sheet mostra la stessa persona del riferimento?

        I modelli d'immagine non vedono il riferimento, solo il testo: a parita' di
        descrizione e seed cambiano spesso capelli o vestiti. Qui si scartano le viste
        che hanno cambiato persona.
        """
        if not installed():
            raise RuntimeError("giudice non installato")
        # Un'immagine sola con i due pannelli affiancati: due immagini nella stessa richiesta
        # mandavano in errore CUDA il server (allocazione VMM, "device not ready") sulla 5060.
        from PIL import Image
        left, right = (Image.open(x).convert("RGB") for x in (reference, image))
        h = 480
        left, right = (im.resize((max(1, round(im.width * h / im.height)), h)) for im in (left, right))
        panel = Image.new("RGB", (left.width + right.width + 16, h), "white")
        panel.paste(left, (0, 0))
        panel.paste(right, (left.width + 16, 0))
        content = [self._image_part(panel, 896),
                   {"type": "text", "text": SAME_CHARACTER_PROMPT.format(description=description.strip(), view=view)}]
        with self._lock:
            self._ensure(device)
            text = self._chat(content, 250)
            self._last_use = time.monotonic()
        try:
            raw = _extract_json(text)
        except ValueError:
            return {"ok": True, "score": None, "differences": [], "fix": ""}
        same, view_ok = _flag(raw, "same", True), _flag(raw, "view_ok", True)
        diffs = [str(d) for d in raw.get("differences") or [] if str(d).strip()]
        return {"ok": same and view_ok, "score": round((same + view_ok) / 2, 2), "differences": diffs,
                "fix": str(raw.get("fix", "")).strip()}

    def review_scene(self, clip: Path, intent: str, device: str = "cpu") -> list[str]:
        """Problemi visibili di una scena didattica resa (grafici sbagliati, testi tagliati); [] = va bene."""
        if not installed():
            return []
        with tempfile.TemporaryDirectory(prefix="sigma_scene_review_") as tmp:
            frames, _span = sample_frames(Path(clip), Path(tmp), 3, phase=0.8)
            images = [{"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()}} for f in frames]
            with self._lock:
                self._ensure(device)
                text = self._chat(images + [{"type": "text", "text": SCENE_REVIEW_PROMPT.format(
                    n=len(images), intent=intent.strip())}], 300)
                self._last_use = time.monotonic()
        try:
            raw = _extract_json(text)
        except ValueError:
            return []
        problems = [str(p) for p in raw.get("problems") or [] if str(p).strip()]
        return [] if _flag(raw, "ok", not problems) and not problems else problems

    def _vanished_objects(self, intent: str, clip: Path, src_in: float, src_out: float | None, tmp: str,
                          device: str) -> list[str]:
        """Oggetti in mano all'inizio e spariti alla fine: domanda mirata su tre fotogrammi.

        Il protocollo generale non li vedeva (una lanterna sparita a meta' salita
        ha preso 1.0); una domanda si'/no per oggetto e fotogramma invece si'.
        """
        objects = held_objects(intent)
        if not objects:
            return []
        out_dir = Path(tmp) / "held"
        out_dir.mkdir(exist_ok=True)
        frames, _span = sample_frames(clip, out_dir, 3, src_in, src_out, 0.5)
        images = [{"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()}} for f in frames]
        vanished = []
        with self._lock:
            self._ensure(device)
            for obj in objects:
                try:
                    seen = _extract_json(self._chat(images + [{"type": "text", "text": HELD_PROMPT.format(
                        n=len(images), obj=obj)}], 60)).get("frames") or []
                except ValueError:
                    continue
                flags = [v is True or str(v).lower() == "true" for v in seen]
                if len(flags) == len(images) and flags[0] and not flags[-1]:
                    vanished.append(obj)
            self._last_use = time.monotonic()
        return vanished

    def _plan(self, intent: str) -> tuple[str, str, list[str]]:
        action, camera, questions = intent.strip(), "none", []
        try:
            plan = _extract_json(self._chat(PLAN_PROMPT.format(intent=intent.strip()), 400))
            questions = [str(q) for q in plan.get("questions") or [] if str(q).strip()][:5]
            # Senza questa separazione una carrellata mancata contava come
            # "azione principale assente" e bocciava clip giuste.
            action = str(plan.get("action") or "").strip() or action
            camera = str(plan.get("camera") or "").strip() or "none"
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        if not questions:
            questions = ["Where is the main subject relative to the key objects?",
                         "Which way do the body and face point?",
                         "What do the feet and hands touch, and what supports any held object?"]
        return action, camera, questions


judge = ClipJudge()
