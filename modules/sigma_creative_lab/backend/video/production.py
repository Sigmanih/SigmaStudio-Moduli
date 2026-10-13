"""Produzioni video lunghe: storyboard → clip → montaggio.

Un modello video genera al massimo qualche secondo per volta (MiniMax H3:
clip di 17k+5 frame, ~5 s a 24 fps). Un video di dieci minuti e' quindi una
produzione di un centinaio di inquadrature, e i problemi da risolvere sono di
regia piu' che di inferenza:

  - **continuita'**: un'inquadratura `continue` parte dall'ultimo fotogramma
    della precedente (image-to-video); una `cut` riparte da zero, eventualmente
    con le immagini di riferimento dei personaggi (Ref2VA). I tagli sono anche
    cio' che impedisce alla deriva di colore e di identita' di accumularsi:
    una catena di `continue` e' limitata a `max_chain` clip;
  - **ripresa**: il manifest su disco registra ogni clip finito, quindi un
    render di molte ore sopravvive a crash e riavvii e riparte dal primo clip
    mancante;
  - **montaggio**: i clip vengono normalizzati (il primo frame di un
    `continue` duplica l'ultimo del clip precedente e va scartato) e uniti
    senza ricodificare due volte.

Il motore che genera i clip e' intercambiabile (worker nativo o ComfyUI):
entrambi producono un file su disco, che e' tutto cio' che serve qui.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Callable

from core import paths
from core.modules.sigma_creative_lab.backends.base import BackendUnavailable
from core.logger import get_logger

log = get_logger("creative_production")

FPS = 24
#: Lunghezze ammesse da MiniMax H3: 17k + 5 frame.
H3_MAX_FRAMES = 124
SHOT_STATUSES = ("pending", "rendering", "done", "failed", "skipped")


def h3_frames(seconds: float, fps: int = FPS, max_frames: int = H3_MAX_FRAMES) -> int:
    n = max(5, round(seconds * fps))
    n = n + (5 - n % 17) % 17
    while n > max_frames:
        n -= 17
    return max(5, n)


#: Modelli video: H3 (MiniMax, licenza che esclude l'UE) e LTX-2.5 (Lightricks, nessuna esclusione).
VIDEO_MODELS = ("h3", "ltx25")
#: LTX regge clip piu' lunghi di H3 senza perdere coerenza: 10 s e' il default del blueprint.
LTX_MAX_SECONDS = 10.0


def lora_family(lora: dict) -> str:
    """Famiglia di una LoRA della bibbia, dalla scheda Civitai accanto al file ("" se sconosciuta)."""
    side = Path(str(lora.get("path", "")) + ".civitai.json")
    try:
        return str(json.loads(side.read_text(encoding="utf-8")).get("family", "")) if side.is_file() else ""
    except (OSError, ValueError):
        return ""


def is_ltx(settings: dict) -> bool:
    return settings.get("video_model") == "ltx25"


def uses_keyframes(settings: dict) -> bool:
    """LTX non ha la modalita' a riferimenti di H3: i personaggi restano riconoscibili solo se ogni
    inquadratura parte da un fotogramma chiave che li contiene gia'."""
    return bool(settings.get("keyframes")) or is_ltx(settings)


def clip_frames(settings: dict, seconds: float) -> int:
    """Fotogrammi di un clip per il modello della produzione (H3: 17k + 5, LTX: 8k + 1)."""
    fps = int(settings.get("fps", FPS))
    if is_ltx(settings):
        from core.modules.sigma_creative_lab.generators.adapters.comfy_ltx import ltx_frame_count
        limit = float(settings.get("max_clip_seconds") or LTX_MAX_SECONDS)
        return ltx_frame_count(min(float(seconds), max(limit, 2.0)), fps)
    return h3_frames(seconds, fps, max_frames=h3_frames(float(settings.get("max_clip_seconds", 5.2)), fps,
                                                         max_frames=362))


def ltx_dims(settings: dict) -> tuple[int, int]:
    """LTX rende bene da 704 righe in su: sotto, il primo passaggio (meta' risoluzione) perde i volti."""
    w, h = int(settings.get("width", 864)), int(settings.get("height", 480))
    target = max(704, h)
    return int(round(target * w / h / 64) * 64), int(round(target / 64) * 64)


def productions_dir() -> Path:
    return paths.creative_dir() / "productions"


def _now() -> float:
    return round(time.time(), 3)


def _slug(text: str, fallback: str = "video") -> str:
    s = re.sub(r"[^\w\-]+", "_", (text or "").strip().lower(), flags=re.UNICODE).strip("_")
    return (s or fallback)[:60]


def _id_slug(title: str) -> str:
    """Parte leggibile dell'id: solo [a-z0-9_] come vuole ProductionStore.path.

    _slug tiene trattini e lettere accentate: "LTX-2.5" o "La città" davano un id
    rifiutato e la produzione non si creava.
    """
    folded = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii").lower()
    return (re.sub(r"[^a-z0-9]+", "_", folded).strip("_") or "video")[:40]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    # Benchmark 2026-10-09 (H3, 864x480x124, 20 step): ComfyUI 5,8 s/step sulla
    # 5070 Ti e 13,9 sulla 5060; il nativo sd.cpp 10,4 e 24,6 anche con Sage.
    "backend": "comfyui",               # comfyui | hybrid | sigma_native (vedi default_lane_specs)
    "video_model": "h3",                # h3 | ltx25 (LTX solo con ComfyUI >= 0.32)
    "profile": "minimax-h3-q4",         # profilo del worker nativo
    "ref_profile": "minimax-h3-ref-q4", # usato solo per le inquadrature con riferimenti
    "placement": "offload",
    "width": 864,
    "height": 480,
    "fps": FPS,
    "steps": 20,
    "sample_method": "res_multistep",
    "scheduler": "simple",
    "cfg_scale": 1.0,
    # EasyCache 0.2: clip 104 -> 74 s sulla 5070 Ti, differenza non visibile a pari seed.
    "cache_mode": "easycache",
    "cache_option": "",
    "seed": 1000,
    "max_chain": 4,
    "clip_codec": "libx264",
    "final_codec": "libx264",
    "final_quality": 18,
    # Con il giudice attivo un tentativo in piu': il terzo parte dal prompt
    # corretto con i suggerimenti del giudice sui primi due.
    "max_attempts": 3,
    "weights": "int8",                  # int8 | fp8 | w6a8: variante del DiT (vedi comfy_h3.H3_UNETS)
    "comfy_flags": None,                # None = ottimizzazioni predefinite (SageAttention se installata)
    "easycache_threshold": 0.2,
    "max_clip_seconds": 5.2,            # H3 e' addestrato su 124-362 frame (5-15 s)
    "qa": True,                         # controllo tecnico dei clip con nuovo tentativo
    "judge": True,                      # giudice visivo (clip_judge): azione e movimento credibili
    # auto: con due o piu' GPU la piu' piccola fa solo da giudice (8B in VRAM, ~8 s a
    # clip) e non rende; con una sola GPU il giudice va sulla CPU (30B, ~85 s).
    "judge_device": "auto",             # auto | cpu | gpu:N
    "judge_threshold": 0.6,
    # severe: il giudice rifa' da solo una volta solo i difetti gravi (direzione, fisica, anatomia) e per il
    # resto consiglia; advise: solo consigli; strict: rifa' ogni bocciatura fino a max_attempts.
    # L'utente vede il giudizio di ogni clip e decide lui (prova "Il seme di Lia": clip accettabili
    # bocciate tre volte per un dettaglio, un minuto e mezzo di render buttato a tentativo).
    "judge_mode": "severe",
    # Modello che scrive storia, storyboard e correzioni ("" = quello della chat).
    "writer_model": "",
    "judge_passes": 2,                  # sguardi indipendenti per clip: vale il peggiore
    "motion_guard": True,               # chiede nel prompt un movimento fisicamente plausibile
    "keyframes": False,                 # primo fotogramma dal modello d'immagine del genere (vedi genres.py)
    "color_match": True,                # correzione colore lungo le catene di continue
    "color_strength": 0.7,
    "output_height": 0,                 # 0 = risoluzione di generazione; es. 1080 = upscale
    "upscaler": "esrgan",               # seedvr2 (diffusione, coerente nel tempo) | esrgan | lanczos
    # Motori Wan 2.2 per tipo di inquadratura ("" = quello della produzione): wan_s2v per le battute,
    # wan_i2v per le azioni. Si possono scegliere anche per singola inquadratura (shot["engine"]).
    "dialogue_engine": "",
    # Ambiente sonoro del luogo sotto le battute (generato con l'audio di LTX).
    "ambience": True,
    "motion_engine": "",
}


def _soundtrack_defaults() -> dict:
    from core.modules.sigma_creative_lab.video.soundtrack import DEFAULT_SOUNDTRACK
    return dict(DEFAULT_SOUNDTRACK)


def new_shot(prompt: str, duration_s: float = 5.0, transition: str = "cut", **extra) -> dict:
    return {
        "id": extra.pop("id", None) or uuid.uuid4().hex[:8],
        "scene": extra.pop("scene", ""),
        "prompt": prompt.strip(),
        "audio": extra.pop("audio", ""),
        "duration_s": float(duration_s),
        "transition": transition if transition in ("cut", "continue") else "cut",
        "refs": list(extra.pop("refs", []) or []),
        "status": "pending",
        "attempts": 0,
        "seed": extra.pop("seed", None),
        "clip_path": "",
        "last_frame": "",
        "frames": 0,
        "timings": {},
        "error": "",
        **extra,
    }


def _atomic_write_json(path: Path, data: dict, indent: int | None = 2) -> None:
    """Scrive un file JSON in modo atomico e sicuro su Windows.

    Su Windows os.replace() puo' sollevare WinError 5 (Accesso negato) se il file
    di destinazione e' momentaneamente aperto in lettura (antivirus, indicizzazione
    o richieste GET concorrenti). Si usa un file temporaneo univoco per evitare
    collisioni di thread/processi, si riprova con backoff esponenziale ed esegue
    un fallback a sovrascrittura diretta se necessario.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=indent)
    tmp = path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(content, encoding="utf-8")

    try:
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except (PermissionError, OSError) as exc:
                if attempt < 9:
                    time.sleep(0.04 * (attempt + 1))
                else:
                    log.warning(f"[ProductionStore] os.replace fallito su {path} ({exc}), fallback a sovrascrittura diretta.")
        # Fallback estremo se MoveFileEx continua a essere bloccato da handle di sola lettura
        path.write_text(content, encoding="utf-8")
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class ProductionStore:
    """Persistenza dei manifest: un JSON per produzione, scritto in modo atomico."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or productions_dir())
        self._lock = threading.RLock()

    def path(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_]{6,64}", pid or ""):
            raise ValueError(f"id produzione non valido: {pid!r}")
        return self.root / pid

    def create(self, title: str, settings: dict | None = None, bible: dict | None = None,
               shots: list | None = None, treatment: str = "", soundtrack: dict | None = None) -> dict:
        pid = f"{_id_slug(title)}_{uuid.uuid4().hex[:6]}"
        prod = {
            "id": pid,
            "title": title.strip() or "Senza titolo",
            "treatment": treatment,
            "created": _now(),
            "updated": _now(),
            "status": "draft",
            "settings": {**DEFAULT_SETTINGS, **(settings or {})},
            "bible": {"style": "", "audio_style": "", "negative": "", "characters": [], "loras": [], **(bible or {})},
            "shots": [s if "status" in s else new_shot(**s) for s in (shots or [])],
            "output_path": "",
            "error": "",
            "stats": {},
            "soundtrack": {**_soundtrack_defaults(), **(soundtrack or {})},
        }
        self.save(prod)
        return prod

    def save(self, prod: dict) -> None:
        with self._lock:
            d = self.path(prod["id"])
            d.mkdir(parents=True, exist_ok=True)
            prod["updated"] = _now()
            _atomic_write_json(d / "production.json", prod, indent=2)

    def get(self, pid: str) -> dict | None:
        with self._lock:
            f = self.path(pid) / "production.json"
            if not f.is_file():
                return None
            try:
                prod = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                log.warning(f"manifest illeggibile {f}: {e}")
                return None
            for shot in prod.get("shots") or []:
                # Le prime lezioni salvavano descrizione e narrazione in "scene", che invece e' il nome
                # della scena (testo): l'interfaccia andava in errore mostrando l'oggetto.
                if isinstance(shot.get("scene"), dict):
                    shot["teaching"] = shot.pop("scene")
                    shot["scene"] = "Lezione"
            return prod

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = []
        for f in self.root.glob("*/production.json"):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                log.warning(f"manifest illeggibile {f}: {e}")
                continue
            out.append(summary(p))
        return sorted(out, key=lambda p: p.get("updated", 0), reverse=True)

    def delete(self, pid: str) -> bool:
        d = self.path(pid)
        if not d.is_dir():
            return False
        shutil.rmtree(d)
        return True


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for f in path.rglob("*"):
        try:
            total += f.stat().st_size if f.is_file() else 0
        except OSError:
            continue
    return total


def purge_production(store: "ProductionStore", pid: str, with_exports: bool = False) -> dict:
    """Elimina una produzione e il suo contesto: cartella, file temporanei di ComfyUI, job dell'editor.

    Prima restavano in giro le uscite di ComfyUI (output/sigma/<id>/, centinaia di MB) e le immagini
    caricate in input/ con il prefisso dell'id. I video esportati restano, a meno di `with_exports`:
    sono il risultato finito, spesso gia' condiviso.
    """
    prod = store.get(pid)
    if prod is None:
        raise ValueError("produzione inesistente")
    from core.modules.sigma_creative_lab.video.editor_jobs import editor_jobs
    if any(j["status"] in ("queued", "running") for j in editor_jobs().list(pid)):
        raise RuntimeError("l'editor ha operazioni in corso su questa produzione: attendi o annullale")
    targets: list[Path] = [store.path(pid)]
    try:
        from core.modules.sigma_creative_lab.model_downloader import discover_models_root
        root = discover_models_root()
        shared = Path(root).parent if root else None
    except Exception:
        shared = None
    if shared:
        targets.append(shared / "output" / "sigma" / pid)
        inputs = shared / "input"
        if inputs.is_dir():
            targets += [f for f in inputs.iterdir() if f.is_file() and f.name.startswith(f"{pid}_")]
    exports = []
    if prod.get("output_path"):
        exports.append(Path(prod["output_path"]))
    out_dir = paths.creative_output_dir("video")
    if out_dir.is_dir():
        exports += [f for f in out_dir.glob(f"*_{pid[-6:]}*.mp4") if f not in exports]
    if with_exports:
        targets += exports
    freed = 0
    for t in targets:
        if not t.exists():
            continue
        freed += _size(t)
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
        else:
            t.unlink(missing_ok=True)
    editor_jobs().forget(pid)
    log.info(f"produzione {pid} eliminata: {freed / 1e6:.0f} MB liberati")
    return {"deleted": True, "freed_mb": round(freed / 1e6, 1),
            "kept_exports": [str(e) for e in exports if e.exists()]}


#: Cartelle di lavoro di una produzione dove si accumulano tentativi e versioni vecchie.
PRUNABLE_DIRS = ("clips", "keyframes", "voices")


def prune_production(store: "ProductionStore", pid: str, dry_run: bool = False) -> dict:
    """Toglie i file che la produzione non usa piu': tentativi scartati, fotogrammi e battute rifatti.

    Si tiene tutto cio' che il manifest nomina (clip, ultimi fotogrammi, fotogrammi chiave, riferimento di
    stile, battute, anche lo storico del giudice) e le anteprime ".scrub" delle clip tenute. Il picnic aveva
    tre tentativi per inquadratura che nessuno avrebbe piu' aperto.
    """
    prod = store.get(pid)
    if prod is None:
        raise ValueError("produzione inesistente")
    active = manager.active() if "manager" in globals() else None
    if active and active.get("production") == pid:
        raise RuntimeError("render in corso: libera spazio a render finito")
    named: set = set()

    def collect(x):
        if isinstance(x, dict):
            for v in x.values():
                collect(v)
        elif isinstance(x, list):
            for v in x:
                collect(v)
        elif isinstance(x, str) and ("/" in x or "\\" in x):
            named.add(Path(x).name)
    collect(prod)
    # Anche la timeline dell'editor e il suo storico (annulla/ripeti) citano clip e voci della cartella.
    for extra in store.path(pid).glob("*.json"):
        try:
            collect(json.loads(extra.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise RuntimeError(f"{extra.name} illeggibile: non tolgo niente finche' non so cosa usa ({e})")
    # I file compagni di uno usato hanno il suo stesso nome base: anteprima .scrub, forme d'onda .peaks.json,
    # miniature, ancore, e per le lezioni il sorgente .html/.scene.json che serve a rifare la scena.
    stems = {n.split(".")[0] for n in named}
    freed, removed = 0, []
    for sub in PRUNABLE_DIRS:
        folder = store.path(pid) / sub
        for f in folder.iterdir() if folder.is_dir() else []:
            if f.is_file() and f.name.split(".")[0] not in stems:
                freed += f.stat().st_size
                removed.append(f.name)
                if not dry_run:
                    f.unlink(missing_ok=True)
    log.info(f"produzione {pid}: {len(removed)} file inutili, {freed / 1e6:.0f} MB"
             + (" (prova)" if dry_run else " liberati"))
    return {"removed": len(removed), "freed_mb": round(freed / 1e6, 1), "dry_run": dry_run}


def summary(prod: dict) -> dict:
    # Le rigenerazioni dall'editor non sono inquadrature dello storyboard:
    # contarle gonfierebbe durata e avanzamento della produzione.
    shots = [s for s in (prod.get("shots") or []) if s.get("origin") not in ("edit", "import", "title", "scene")]
    done = [s for s in shots if s.get("status") == "done"]
    total_s = sum(float(s.get("duration_s") or 0) for s in shots)
    rendered_s = sum(float(s.get("timings", {}).get("total_s") or 0) for s in done)
    # Con piu' corsie i clip escono in parallelo: il tempo medio per clip
    # misurato su una corsia va diviso per quante lavorano insieme.
    per_clip = rendered_s / len(done) / max(1, len(prod.get("lanes") or [])) if done else 0.0
    return {
        "id": prod["id"], "title": prod.get("title"), "status": prod.get("status"),
        "updated": prod.get("updated"), "shots": len(shots), "shots_done": len(done),
        "shots_failed": sum(1 for s in shots if s.get("status") == "failed"),
        "duration_s": round(total_s, 1), "output_path": prod.get("output_path", ""),
        "backend": (prod.get("settings") or {}).get("backend"),
        "eta_s": round(per_clip * (len(shots) - len(done))) if done else None,
    }


# ---------------------------------------------------------------------------
# Storyboard
# ---------------------------------------------------------------------------

GenerateFn = Callable[[list, int], str]


def _default_generate(messages: list, max_tokens: int) -> str:
    from core.engine import sigma_engine
    chunks = sigma_engine.generate_stream(messages=messages, temperature=0.7, max_tokens=max_tokens)
    return "".join((c.get("token") or c.get("content") or "") for c in chunks if isinstance(c, dict))


def writer(settings: dict | None) -> GenerateFn:
    """Il modello che scrive storia e storyboard, se la produzione ne ha scelto uno diverso dalla chat.

    Prova della lucciola (2026-10-13): lo stesso 27B a 2 bit (quello della chat) scriveva parole
    inesistenti e una lucciola che fa luce con le ali; a Q4_K_M la storia regge, a 24 token/s.
    """
    model = str((settings or {}).get("writer_model") or "").strip()
    if not model:
        return _default_generate

    def gen(messages: list, max_tokens: int) -> str:
        from core.engine import sigma_engine
        chunks = sigma_engine.generate_stream(messages=messages, temperature=0.7, max_tokens=max_tokens,
                                              model_name=model)
        return "".join((c.get("token") or c.get("content") or "") for c in chunks
                       if isinstance(c, dict) and not c.get("notice"))
    return gen


def extract_json(text: str, want: type | None = None):
    """Primo blocco JSON nel testo: i modelli piccoli aggiungono spesso prosa o ```json.

    Con `want=list` una lista avvolta in un oggetto ({"shots": [...]}) torna come lista.
    """
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    # Prima la parentesi che apre per prima: un oggetto che contiene una lista ("scenes": [...])
    # tornava solo come la lista interna, e la storia perdeva titolo e messaggio.
    pairs = sorted((("[", "]"), ("{", "}")), key=lambda oc: (text.find(oc[0]) == -1, text.find(oc[0])))
    for opener, closer in pairs:
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                found = json.loads(text[start:end + 1])
            except ValueError:
                continue
            if want is list and isinstance(found, dict):
                found = next((v for v in found.values() if isinstance(v, list)), found)
            return found
    raise ValueError("nessun JSON valido nella risposta del modello")


LTX_REWRITE_PROMPT = """You rewrite video shot descriptions for the LTX-2 video model, which follows a short
story told in order much better than a list of tags. For EACH shot write one paragraph in English, present tense,
40-90 words:
- what happens, in chronological order, with concrete physical actions (who moves where, what the hands do);
- then exactly ONE explicit camera movement, chosen from: static shot, slow pan left, slow pan right, tilt up,
  tilt down, dolly in, dolly out, tracking shot following the subject from behind, tracking shot alongside the
  subject, crane up. Keep the camera the description asks for; if it asks none, pick the one that fits the action.
- keep every character name, object, place and any spoken line exactly as given. No quality tags, no lists.
Shots:
{shots}
Reply ONLY with JSON: [{{"index": 0, "prompt": "..."}}, ...]"""

#: Inquadrature per richiesta: abbastanza da non pagare il prompt di sistema ogni volta,
#: poche abbastanza da restare nella finestra dei modelli locali (vedi plan_storyboard).
LTX_REWRITE_BATCH = 6


#: Camera richiesta nel testo -> formula canonica che LTX riconosce. Regole fisse e non il modello:
#: l'8B, pur istruito, trasformava "follows from behind" in "dolly in".
CAMERA_RULES = (
    (r"follow\w*\s+(?:her|him|them|it|the \w+)?\s*from behind|from behind.{0,20}follow",
     "tracking shot following the subject from behind"),
    (r"track\w*\s+(?:alongside|beside|next to)|side tracking", "tracking shot alongside the subject"),
    (r"track\w*|follow\w* (?:her|him|them|the)", "tracking shot following the subject"),
    (r"dolly\s*in|push\s*in|zoom\s*in|moves? closer", "dolly in"),
    (r"dolly\s*out|pulls?\s*(?:back|out)|zoom\w*\s*out", "dolly out"),
    (r"pan\w*\s+left", "slow pan left"), (r"pan\w*\s+right", "slow pan right"), (r"\bpan\w*", "slow pan"),
    (r"tilt\w*\s+up", "tilt up"), (r"tilt\w*\s+down", "tilt down"),
    (r"crane|jib|rises? above", "crane up"), (r"orbit\w*|circles? around", "orbit around the subject"),
    (r"static|still camera|locked[- ]off|fixed camera", "static shot"),
)


def requested_camera(text: str) -> str:
    low = (text or "").lower()
    return next((cam for pattern, cam in CAMERA_RULES if re.search(pattern, low)), "")


def _with_camera(text: str, camera: str) -> str:
    """Se il modello ha cambiato la camera chiesta, si toglie la sua frase e si rimette quella giusta."""
    found = requested_camera(text)
    # Stessa famiglia di movimento basta: "the camera tracks behind her" e' un carrello che segue.
    if not camera or (found and found.split()[0] == camera.split()[0]):
        return text
    text = re.sub(r"[;,.]?\s*the camera[^.;]*[.;]?\s*$", "", text, flags=re.I).rstrip(" .;,")
    return f"{text}. The camera: {camera}."


def _prompt_hash(text: str) -> str:
    import hashlib
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:12]


def ltx_action(shot: dict) -> str:
    """Descrizione riscritta per LTX, solo se e' ancora quella del prompt attuale."""
    rewritten = shot.get("ltx_prompt") or {}
    if rewritten.get("text") and rewritten.get("source") == _prompt_hash(shot.get("prompt", "")):
        return rewritten["text"]
    return ""


def ensure_character_voice(store: "ProductionStore", prod: dict, ch: dict) -> Path:
    """Campione della voce del personaggio: dalla libreria, caricato, o creato una volta col TTS.

    Con una descrizione della voce lo crea Qwen3-TTS VoiceDesign (un timbro per personaggio);
    senza, Kokoro. Il campione poi vale per tutte le battute del personaggio.
    """
    from core.modules.sigma_creative_lab.voice.runtime import qwen_runtime, voice_runtime
    if ch.get("voice_sample") and Path(ch["voice_sample"]).is_file():
        return Path(ch["voice_sample"])
    out = store.path(prod["id"]) / "voices" / f"{re.sub(r'[^a-z0-9]+', '_', ch['name'].lower())}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = ch.get("voice_sample_text") or \
        "Buongiorno. Questa e' la mia voce, calma e chiara, per tutte le scene di questo film."
    if ch.get("voice_description") and qwen_runtime.installed():
        qwen_runtime.synthesize(text, out, engine="qwen_design", instruct=ch["voice_description"],
                                seed=int(ch.get("voice_seed") or 7))
        qwen_runtime.unload()                       # la VRAM serve subito dopo al video o a Chatterbox
    else:
        voice_runtime.synthesize(text, out, engine=ch.get("voice_engine") or "kokoro",
                                 voice=ch.get("voice") or "im_nicola")
    ch["voice_sample"] = str(out)
    store.save(prod)
    return out


#: Durata dei tappeti d'ambiente dei luoghi (vedi soundtrack.generate_ambience).
AMBIENCE_LOOP_S = 10.0

#: Silenzio prima della battuta: nel fotogramma chiave la bocca e' chiusa, il labiale parte dopo.
DIALOGUE_LEAD_S = 0.25


def _library_voice(ch: dict) -> dict | None:
    if not ch.get("voice_id"):
        return None
    try:
        from core.modules.sigma_voice_studio import library
    except ImportError:
        return None
    return library.get(ch["voice_id"])


def _voice_key(ch: dict) -> str:
    """Cosa determina la voce di un personaggio: se cambia, le battute vanno rifatte."""
    v = _library_voice(ch)
    if v:
        return f"{v['id']}:{v.get('semitones', 0)}:{v.get('speed', 1)}:{v.get('created', 0)}"
    return str(ch.get("voice_sample") or "")


def _speak_line(store, prod: dict, ch: dict, text: str, out: Path, seed: int) -> float:
    """Battuta con la voce del personaggio, controllata con Whisper; ritorna la durata del parlato."""
    from core.modules.sigma_creative_lab.video.editor_jobs import _tts_checked
    v = _library_voice(ch)
    if v and v.get("kind") in ("preset", "design"):
        # Voce della libreria col suo motore (Kokoro, Qwen3-TTS o VoxCPM2): la clonazione con Chatterbox
        # dava l'accento straniero. La battuta si ascolta con Whisper e si rifa' se ha perso parole.
        from core.modules.sigma_creative_lab.video.editor_jobs import speech_match
        from core.modules.sigma_creative_lab.video.speech_text import to_spoken
        from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
        from core.modules.sigma_voice_studio import library
        best = None
        for k in range(3):
            take = out.with_name(f"{out.stem}.try{k}.wav")
            library.speak(v["id"], to_spoken(text), take, **({} if v["kind"] == "preset" else {"seed": seed + k * 101}))
            try:
                score = speech_match(text, voice_runtime.transcribe(take, "it")["text"])
            except Exception as e:
                log.warning(f"controllo della battuta non riuscito: {e}")
                score = 1.0
            if best is None or score > best[0]:
                best = (score, take)
            if score >= 0.85 or v["kind"] == "preset":
                break
        best[1].replace(out)
        for left in out.parent.glob(f"{out.stem}.try*.wav"):
            left.unlink(missing_ok=True)
        return float(probe(out)["audio_duration"] or 0.0)
    sample = Path(v["sample"]) if v else ensure_character_voice(store, prod, ch)
    return _tts_checked(text, out, "chatterbox", {"voice_ref": str(sample), "exaggeration": 0.55, "cfg_weight": 0.5}, seed)


def _pad_start(path: Path, seconds: float) -> None:
    tmp = path.with_name(path.stem + ".pad.wav")
    _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(path), "-af", f"adelay={int(seconds * 1000)}:all=1", str(tmp)])
    tmp.replace(path)


def _padded_line(path: Path, seconds: float) -> bytes:
    """La battuta allungata col silenzio fino alla fine della clip.

    Senza, LTX riceve l'audio solo per la durata della battuta e il resto della clip non ha
    vincoli: la bocca continua a muoversi a vuoto dopo l'ultima parola.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "line.wav"
        _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(path), "-af", f"apad=whole_dur={seconds:.3f}",
              "-ar", "48000", str(out)])
        return out.read_bytes()


def prepare_dialogue(store: "ProductionStore", prod: dict, note=None) -> int:
    """Sintetizza le battute delle inquadrature da rendere, con la voce di chi parla.

    Prima del render e non durante: la voce (Chatterbox) e il giudice dividerebbero la GPU
    piccola e il video quella grande; a fine sintesi la voce viene scaricata.
    """
    from core.modules.sigma_creative_lab.voice.runtime import voice_runtime
    chars = {c.get("name"): c for c in (prod.get("bible") or {}).get("characters") or []}

    def source(sh):
        d = sh["dialogue"]
        return _prompt_hash(f"{d['text']}|{_voice_key(chars[d['character']])}")
    todo = [sh for sh in prod.get("shots") or [] if sh.get("status") != "done" and isinstance(sh.get("dialogue"), dict)
            and sh["dialogue"].get("text") and sh["dialogue"].get("character") in chars
            and not (sh["dialogue"].get("audio") and Path(sh["dialogue"]["audio"]).is_file()
                     and sh["dialogue"].get("source") == source(sh))]
    if not todo or not voice_runtime.installed():
        return 0
    done = 0
    try:
        for k, sh in enumerate(todo, 1):
            d = sh["dialogue"]
            if note:
                note(f"Voce delle battute {k}/{len(todo)}: {d['character']}")
            out = store.path(prod["id"]) / "voices" / f"line_{sh['id']}.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            seconds = _speak_line(store, prod, chars[d["character"]], d["text"], out,
                                  int(prod["settings"].get("seed", 1000)) + k)
            _pad_start(out, DIALOGUE_LEAD_S)
            seconds += DIALOGUE_LEAD_S
            d.update(audio=str(out), seconds=round(seconds, 2), source=source(sh))
            # L'inquadratura dura almeno quanto la battuta, piu' mezzo secondo per chiudere la bocca.
            sh["duration_s"] = max(float(sh.get("duration_s") or 0), round(seconds + 0.6, 1))
            done += 1
    finally:
        # Tutti i motori voce lasciano la GPU: subito dopo arriva il modello video.
        from core.modules.sigma_creative_lab.voice.runtime import qwen_runtime, voxcpm_runtime
        for rt in (voice_runtime, qwen_runtime, voxcpm_runtime):
            try:
                rt.unload()
            except Exception as e:
                log.debug(f"voce non scaricata: {e}")
    return done


def rewrite_for_ltx(prod: dict, generate: "GenerateFn | None" = None, note=None) -> int:
    """Riscrive in stile LTX le inquadrature da rendere; ritorna quante sono cambiate.

    Si fa prima del render e non durante: l'LLM e il modello video sulla stessa GPU si
    ricaricherebbero a vicenda a ogni clip. Prova del faro (2026-10-11): con le descrizioni
    brevi la camera non si e' mossa in nessuno dei 7 tentativi.
    """
    gen = generate or writer(prod.get("settings"))
    todo = [(i, sh) for i, sh in enumerate(prod.get("shots") or [])
            if sh.get("status") != "done" and sh.get("origin") not in ("edit", "import", "title", "scene")
            and sh.get("prompt", "").strip() and not ltx_action(sh)]
    changed = 0
    for start in range(0, len(todo), LTX_REWRITE_BATCH):
        batch = todo[start:start + LTX_REWRITE_BATCH]
        if note:
            note(f"Prompt per LTX {start + 1}-{start + len(batch)} di {len(todo)}")
        listing = "\n".join(
            f"{i}. ({sh.get('duration_s', 5)} s"
            + (f", camera MUST be: {requested_camera(sh['prompt'])}" if requested_camera(sh["prompt"]) else "")
            + f") {sh['prompt'].strip()}" for i, sh in batch)
        try:
            answer = extract_json(gen([{"role": "user", "content": LTX_REWRITE_PROMPT.format(shots=listing)}], 2500), list)
        except Exception as e:
            # Senza riscrittura il render parte lo stesso con la descrizione originale.
            log.warning(f"riscrittura dei prompt per LTX non riuscita: {e}")
            continue
        items = [x for x in answer if isinstance(x, dict)] if isinstance(answer, list) else []
        by_index = {int(x.get("index", -1)): str(x.get("prompt", "")).strip() for x in items}
        if set(by_index) != {i for i, _sh in batch} and len(items) == len(batch):
            # I modelli piccoli rinumerano da 0 o da 1: con lo stesso numero di risposte vale l'ordine.
            by_index = {i: str(x.get("prompt", "")).strip() for (i, _sh), x in zip(batch, items)}
        for i, sh in batch:
            text = _with_camera(by_index.get(i, ""), requested_camera(sh["prompt"])) if by_index.get(i) else ""
            if 20 <= len(text) <= 1200:
                sh["ltx_prompt"] = {"text": text, "source": _prompt_hash(sh["prompt"])}
                changed += 1
    return changed


SCENES_PROMPT = """Sei un regista. Dividi questo soggetto in scene per un video di {minutes} minuti.
Stile visivo: {style}

Soggetto:
{treatment}

Rispondi SOLO con un array JSON. Ogni elemento: {{"title": "...", "summary": "cosa accade, 2-3 frasi", "seconds": numero}}.
La somma dei secondi deve essere circa {seconds}. Fra {min_scenes} e {max_scenes} scene."""

SHOTS_PROMPT = """Scomponi la scena in inquadrature da {min_shot}-{max_shot} secondi per un generatore video.
Stile visivo: {style}
Personaggi (usa SEMPRE e solo questi nomi): {characters}
Scena {index}/{total}: {title} ({seconds} s)
{summary}
{world}
Scena precedente: {previous}
Scena successiva (NON anticiparla: quello che vi accade non succede qui): {next_scene}
Ultima inquadratura gia' scritta (solo per continuita': NON ripeterla, la scena riparte da dopo): {last_shot}
Oggetti gia' in scena (vanno chiamati sempre allo stesso modo): {props}

Rispondi SOLO con un array JSON. Ogni elemento:
{{"prompt": "descrizione visiva ricca e concreta in inglese, 50-90 parole: tipo di inquadratura, dove sta ogni \
personaggio (sinistra, destra, primo piano, sfondo) e verso dove guarda, l'azione, cosa fanno le mani, gli oggetti \
nel loro stato di quel momento, il luogo, la luce, il movimento di camera (lo stile visivo viene aggiunto dopo: non \
ripeterlo)",
 "location": "nome del luogo, come nella descrizione della scena",
 "expressions": {{"Nome": "espressione del viso in inglese, es. wide-eyed wonder, open smile"}},
 "audio": "suoni, musica o dialogo in inglese",
 "seconds": numero,
 "transition": "cut" oppure "continue" (continue = stessa ripresa che prosegue dall'ultimo fotogramma),
 "characters": ["solo i personaggi VISIBILI nell'inquadratura"],
 "props": ["oggetti importanti in scena, es. oil lamp"],
 "dialogue": {{"character": "nome del personaggio che parla", "line": "battuta in italiano"}} oppure null}}
Dialoghi: quando la storia lo chiede, al massimo UNA battuta per inquadratura, in italiano, breve (fino a 15
parole), detta da un personaggio VISIBILE e presente fra "characters"; in una scena dove i personaggi si incontrano
o reagiscono a qualcosa scrivi almeno una battuta (i dialoghi rendono viva la storia). Un'inquadratura con battuta
e' fatta per il labiale: chi parla e' a mezza figura o in primo piano, col viso verso la camera o di tre quarti e
la bocca ben visibile, fermo o con un gesto semplice (mai di spalle, mai mentre corre o si volta); chi ascolta,
se c'e', sta a lato e piu' piccolo. La battuta dura 2-4 secondi: l'inquadratura non ha altre azioni lunghe.
Usa "continue" solo quando la ripresa prosegue nello stesso luogo con la stessa camera (parte dall'ultimo
fotogramma della precedente): mai per passare da esterno a interno o fra luoghi diversi. Altrimenti "cut".
Somma dei secondi: circa {seconds}. La scena comincia dove finisce la precedente: non ripetere azioni gia' fatte.
Racconta SOLO quello che dice la descrizione di questa scena, nell'ordine; ogni battuta fra virgolette nella
descrizione diventa il "dialogue" di un'inquadratura, tutte e nello stesso ordine (puoi accorciarle, non toglierle).
Regole per il prompt (il generatore sbaglia le azioni vaghe, per esempio fa salire le scale all'indietro):
- grammatica del cinema: se la scena si apre in un luogo nuovo, la prima inquadratura e' un campo largo del luogo
  (3-5 s) che fa capire dove siamo; nei dialoghi alterna chi parla (campo e controcampo) invece di tenere tutti
  nella stessa inquadratura; quando un oggetto conta per la storia, un dettaglio ravvicinato (insert) lo mostra;
  varia i piani (campo largo, mezza figura, primo piano): mai tre inquadrature uguali di fila;
- al massimo DUE personaggi ben visibili per inquadratura: con tre o piu' il generatore d'immagini confonde le
  identita' (sdoppia un personaggio, ne trasforma uno in un altro); gli altri restano fuori campo o si vedono in
  un'inquadratura successiva; un'inquadratura di gruppo solo dove la storia la chiede davvero (es. il finale);
- una sola azione principale per inquadratura, che si compie nei secondi indicati (al massimo due verbi:
  "walks to the door and opens it" si', "turns, crosses the room, picks up the lamp and opens the door" no);
- descrivi il movimento in modo fisico: chi si muove, verso dove, come e in che direzione guarda
  (es. "walks up the spiral stairs step by step, facing the steps, one hand on the railing");
- gli oggetti tenuti in mano vanno detti "held in his right hand", non solo "with a lamp", e restano gli
  stessi oggetti per tutta la storia (la lanterna non diventa una torcia);
- il movimento di camera in una frase separata e semplice (static, slow push-in, follows from behind);
- "prompt" e "audio" SEMPRE in inglese, anche se il soggetto e' in italiano;
- ogni oggetto e' mostrato nello stato in cui e' IN QUEL MOMENTO della storia: un seme appena piantato e' solo
  terra nel vaso (niente fiore, niente piantina), il germoglio compare solo quando la storia lo dice; nessun
  oggetto della fine compare prima;
- niente testo, scritte o fumetti nell'immagine: la battuta sta solo nel campo "dialogue";
- un personaggio della lista chiamato nel soggetto con un ruolo ("lo shogun", "il difensore", "the hero") E'
  quel personaggio: scrivi il suo nome, mai il ruolo, e non mostrare mai due persone per lo stesso personaggio.{notes}"""

ALIASES_PROMPT = """Characters of a story: {characters}
Story: {treatment}
Which words or roles in the story refer to each listed character (e.g. "the shogun", "lo shonen", "the old man")?
Only words that clearly mean THAT character. Reply ONLY with JSON: {{"Name": ["role", "other role"], ...}}"""

TRANSLATE_PROMPT = """Translate these video shot descriptions into natural English. Keep names, objects and camera
directions exactly; do not add anything. Reply ONLY with a JSON array of strings in the same order.
{items}"""

#: Parole funzionali italiane: due o piu' in un prompt vogliono dire che il modello ha scritto in italiano.
_ITALIAN_WORDS = {"il", "lo", "la", "gli", "le", "i", "della", "dello", "delle", "degli", "del", "dei", "al", "alla",
                  "sul", "sullo", "sulla", "sui", "nel", "nella", "di", "da", "ed", "mentre", "sua", "suo", "suoi",
                  "sue", "che", "una", "uno", "con", "verso", "per", "si", "sono", "non", "come", "sembra"}


class PlanningCancelled(Exception):
    """Lo storyboard o i fotogrammi chiave sono stati fermati dall'utente."""


def shot_bounds(settings: dict) -> tuple:
    """Durata minima e massima di un'inquadratura per il motore della produzione.

    Prima era 3-5 s per tutti, il limite di H3: con LTX ne uscivano clip da 3 s a raffica.
    """
    if is_ltx(settings):
        return 4.0, max(5.0, min(10.0, float(settings.get("max_clip_seconds") or 10.0)))
    return 3.0, min(5.2, float(settings.get("max_clip_seconds") or 5.2))


def looks_italian(text: str) -> bool:
    words = re.findall(r"[a-zàèéìòù']+", (text or "").lower())
    return sum(1 for w in words if w in _ITALIAN_WORDS) >= 2


def apply_aliases(text: str, characters: list) -> str:
    """Sostituisce i ruoli con il nome del personaggio ("the shonen" -> "Mimoki")."""
    out = text or ""
    for c in characters:
        name = str(c.get("name") or "").strip()
        for alias in sorted((a for a in c.get("aliases") or [] if str(a).strip()), key=len, reverse=True):
            a = re.escape(str(alias).strip())
            # L'articolo va via insieme al ruolo, ma lo spazio prima resta: "of the shonen" -> "of Mimoki".
            out = re.sub(rf"\b(?:(?:the|a|an|il|lo|la|l')\s+)?{a}\b", name, out, flags=re.I) if name else out
        if name:
            # "Mimoki and Mimoki" nasceva da "the shonen and Mimoki": e' la stessa persona.
            # Anche "Pepe Pepe emerges", da "The little hedgehog Pepe emerges".
            out = re.sub(rf"\b{re.escape(name)}(?:\s*(?:,|and|e|with|con)?\s+{re.escape(name)}|,\s*{re.escape(name)})+\b",
                         name, out)
    return re.sub(r"\s{2,}", " ", out).strip()


def detect_aliases(treatment: str, characters: list, generate: "GenerateFn | None" = None) -> dict:
    """Ruoli con cui il soggetto chiama i personaggi: una richiesta sola all'inizio dello storyboard."""
    if not characters or not (treatment or "").strip():
        return {}
    gen = generate or _default_generate
    listing = "; ".join(f"{c.get('name')}: {c.get('description', '')}" for c in characters)
    try:
        raw = extract_json(gen([{"role": "user", "content": ALIASES_PROMPT.format(characters=listing,
                                                                                   treatment=treatment.strip())}], 600))
    except Exception as e:
        log.warning(f"ruoli dei personaggi non riconosciuti: {e}")
        return {}
    names = {str(c.get("name")).lower(): c.get("name") for c in characters}
    out = {}
    for k, v in (raw.items() if isinstance(raw, dict) else []):
        name = names.get(str(k).lower())
        if name and isinstance(v, list):
            out[name] = [str(x).strip() for x in v if str(x).strip() and str(x).strip().lower() != name.lower()][:6]
    return out


def _to_english(shots: list, generate: "GenerateFn") -> None:
    """Traduce i prompt che il modello ha scritto in italiano (successo nella prova dei samurai)."""
    todo = [s for s in shots if looks_italian(s["prompt"])]
    if not todo:
        return
    try:
        out = extract_json(generate([{"role": "user", "content": TRANSLATE_PROMPT.format(
            items=json.dumps([s["prompt"] for s in todo], ensure_ascii=False))}], 3000), list)
    except Exception as e:
        log.warning(f"traduzione dei prompt non riuscita: {e}")
        return
    if isinstance(out, list) and len(out) == len(todo):
        for shot, text in zip(todo, out):
            if isinstance(text, str) and text.strip() and not looks_italian(text):
                shot["prompt"] = text.strip()


def plan_storyboard(treatment: str, minutes: float, style: str = "", characters: list | None = None,
                    generate: GenerateFn | None = None, shot_seconds: tuple = (3.0, 5.0),
                    progress: Callable[[str], None] | None = None, cancel: "threading.Event | None" = None,
                    on_scene: Callable[[list], None] | None = None, pre: dict | None = None) -> list[dict]:
    """Storyboard gerarchico: prima le scene, poi le inquadrature di ciascuna.

    Con la pre-produzione (`pre`, vedi preproduction.py) le scene sono gia' scritte e approvate
    dall'utente, e ogni scena riceve il suo luogo e gli oggetti descritti.

    Una sola richiesta per cento inquadrature supererebbe la finestra di
    contesto dei modelli locali e li farebbe perdere il filo; scena per scena
    ogni risposta resta breve e verificabile.
    """
    from core.modules.sigma_creative_lab.video.preproduction import scene_brief
    gen = generate or _default_generate
    seconds = max(5.0, float(minutes) * 60.0)
    chars = characters or []
    char_text = "; ".join(
        f"{c.get('name')}: {c.get('description', '')}"
        + (f" (nel soggetto anche: {', '.join(c['aliases'])})" if c.get("aliases") else "")
        for c in chars) or "nessuno in particolare"
    n_scenes = max(1, round(seconds / 45.0))
    if pre and pre.get("scenes"):
        scenes = [dict(x) for x in pre["scenes"]]
    else:
        msg = SCENES_PROMPT.format(minutes=minutes, style=style or "libero", treatment=treatment.strip(),
                                   seconds=int(seconds), min_scenes=max(1, n_scenes - 2), max_scenes=n_scenes + 3)
        scenes = extract_json(gen([{"role": "user", "content": msg}], 3000), list)
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("il modello non ha restituito un elenco di scene")
    # Riporta la durata totale a quella chiesta: i modelli sbagliano spesso le somme.
    declared = sum(max(1.0, float(s.get("seconds") or 0)) for s in scenes)
    scale = seconds / declared if declared else 1.0

    shots: list[dict] = []
    previous = "nessuna (inizio)"
    props: list[str] = []
    for i, scene in enumerate(scenes, 1):
        if cancel is not None and cancel.is_set():
            raise PlanningCancelled(f"fermato dopo {i - 1} scene su {len(scenes)}")
        scene_s = max(shot_seconds[0], float(scene.get("seconds") or 0) * scale)
        if progress:
            progress(f"Scena {i}/{len(scenes)}: {scene.get('title', '')}")
        msg = SHOTS_PROMPT.format(min_shot=shot_seconds[0], max_shot=shot_seconds[1], style=style or "libero",
                                  characters=char_text, index=i, total=len(scenes), title=scene.get("title", ""),
                                  seconds=round(scene_s), summary=scene.get("summary", ""), previous=previous,
                                  # Senza l'ultima inquadratura e gli oggetti gia' visti il modello
                                  # ripartiva da capo a ogni scena e cambiava la lanterna in una torcia.
                                  last_shot=shots[-1]["prompt"] if shots else "nessuna",
                                  props=", ".join(props) or "nessuno", notes="", world=scene_brief(pre or {}, scene),
                                  next_scene=(f"{scenes[i].get('title', '')}: {scenes[i].get('summary', '')}"
                                              if i < len(scenes) else "nessuna (e' la fine)"))
        try:
            items = extract_json(gen([{"role": "user", "content": msg}], 4000), list)
        except ValueError as e:
            log.warning(f"scena {i}: risposta non valida ({e}), uso il riassunto come inquadratura unica")
            items = [{"prompt": scene.get("summary", ""), "seconds": scene_s, "transition": "cut"}]
        scene_shots = _normalize_shots(items, scene_s, shot_seconds, chars, scene.get("title", f"Scena {i}"),
                                       style=style, location=str(scene.get("location") or ""))
        for it in items if isinstance(items, list) else []:
            for prop in (it.get("props") or []) if isinstance(it, dict) else []:
                if isinstance(prop, str) and prop.strip() and prop.strip().lower() not in (x.lower() for x in props):
                    props.append(prop.strip())
        scene_shots = _drop_repeats(scene_shots, shots)
        if scene.get("lines"):
            from core.modules.sigma_creative_lab.video.preproduction import place_lines
            place_lines(scene_shots, scene["lines"])
        if scene_shots:
            scene_shots[0]["transition"] = "cut"   # una scena nuova comincia sempre con un taglio
        _to_english(scene_shots, gen)
        shots.extend(scene_shots)
        if on_scene:
            on_scene(shots)                        # salvataggio parziale: fermare non butta il lavoro fatto
        previous = f"{scene.get('title', '')}: {scene.get('summary', '')}"
    return shots


def _dialogue_of(raw, characters: list) -> dict | None:
    """Battuta dello storyboard, solo se detta da un personaggio della bibbia (anche chiamato col suo ruolo)."""
    if not isinstance(raw, dict):
        return None
    line = str(raw.get("line") or raw.get("text") or "").strip().strip('"')
    who = str(raw.get("character") or "").strip()
    if not line or not who:
        return None
    def bare(x: str) -> str:
        return re.sub(r"^(?:the|il|lo|la|l')\s+", "", str(x).strip().lower())
    for c in characters:
        names = {bare(c.get("name", ""))} | {bare(a) for a in c.get("aliases") or []}
        if bare(who) in names:
            return {"character": c["name"], "text": line}
    return None


FIX_PROMPT = """A director watched a generated video shot and complains (in Italian or English):
<<{problem}>>
The shot shows: {prompt}
1. "literal": translate the complaint into English, literally, keeping every negation ("no", "not", "nothing").
2. "instruction": 1-2 short POSITIVE instructions in English for an image/video model that ignores negative
prompts: describe what MUST be seen so the problem disappears (e.g. "the pot has a spout" -> "the terracotta pot
is a plain round pot with no spout; only the watering can has a spout"; "she holds a flower but should hold
nothing" -> "her hands are empty"). Never name the unwanted object in the instruction (an image model draws
every object it reads, even after "no"). Never add elements the director did not ask for.
Reply ONLY with JSON: {{"literal": "...", "instruction": "..."}}"""

FIX_CHECK_PROMPT = """Complaint about a video shot: <<{literal}>>
Proposed instruction for the next render: <<{instruction}>>
Does following the instruction REMOVE the problem, without asking for the thing the complaint rejects?
Answer only "yes" or "no"."""

#: Correzioni dell'utente tenute per un'inquadratura: oltre, si annacqua la descrizione.
MAX_USER_FIXES = 4


def rewrite_fix(problem: str, shot_prompt: str, generate: GenerateFn | None = None) -> str:
    """Il problema detto dall'utente come vincolo positivo in inglese, verificato.

    Caso reale: "Lia non tiene niente in mano, nessun girasole" e' diventato "Lia holds a sunflower in her
    hand... clearly visible". Un secondo sguardo controlla che l'istruzione risolva il problema; se no, si
    usa la traduzione letterale, che almeno dice la cosa giusta.
    """
    gen = generate or _default_generate
    try:
        raw = extract_json(gen([{"role": "user", "content": FIX_PROMPT.format(problem=problem,
                                                                           prompt=shot_prompt[:500])}], 300))
    except Exception as e:
        log.warning(f"correzione non riscritta: {e}")
        return problem
    literal = " ".join(str((raw or {}).get("literal") or "").split()) if isinstance(raw, dict) else ""
    instruction = " ".join(str((raw or {}).get("instruction") or "").split()) if isinstance(raw, dict) else ""
    if not instruction or looks_italian(instruction):
        return literal or problem
    try:
        verdict = gen([{"role": "user", "content": FIX_CHECK_PROMPT.format(literal=literal or problem,
                                                                          instruction=instruction)}], 10)
        ok = re.sub(r"<think>.*?</think>", "", verdict, flags=re.S).strip().lower().startswith("yes")
    except Exception as e:
        log.warning(f"verifica della correzione non riuscita: {e}")
        ok = True
    if not ok:
        log.warning(f"istruzione scartata (non risolve '{literal}'): {instruction}")
        return literal or problem
    return instruction[:300]


def user_fix(prod: dict, shot_id: str, problem: str, generate: GenerateFn | None = None) -> dict:
    """Aggiunge all'inquadratura una correzione dell'utente, gia' in forma positiva e in inglese.

    Il prompt negativo non serve: LTX distillato e klein lavorano con cfg 1 e lo ignorano. Il vincolo resta
    nell'inquadratura (campo `fixes`) e vale per fotogramma chiave e clip finche' l'utente non lo toglie.
    """
    shot = next((x for x in prod.get("shots") or [] if x["id"] == shot_id), None)
    if shot is None:
        raise ValueError("inquadratura inesistente")
    problem = str(problem or "").strip()
    if not problem:
        raise ValueError("scrivi cosa non va")
    text = rewrite_fix(problem, shot["prompt"], generate or writer(prod.get("settings")))
    fixes = [f for f in shot.get("fixes") or [] if f.get("text") != text]
    shot["fixes"] = (fixes + [{"problem": problem, "text": text}])[-MAX_USER_FIXES:]
    return shot


def replan_scene(prod: dict, scene: str, notes: str, generate: GenerateFn | None = None) -> list[dict]:
    """Riscrive le inquadrature di una scena seguendo le indicazioni dell'utente; le altre scene restano.

    Ritorna le nuove inquadrature, gia' messe al posto delle vecchie in `prod`.
    """
    gen = generate or writer(prod.get("settings"))
    shots = prod.get("shots") or []
    idx = [i for i, sh in enumerate(shots) if sh.get("scene") == scene]
    if not idx:
        raise ValueError(f"scena inesistente: {scene}")
    old = [shots[i] for i in idx]
    chars = (prod.get("bible") or {}).get("characters") or []
    style = (prod.get("bible") or {}).get("style", "")
    bounds = shot_bounds(prod.get("settings") or {})
    seconds = sum(float(sh.get("duration_s") or 0) for sh in old)
    before = shots[idx[0] - 1]["prompt"] if idx[0] > 0 else "nessuna"
    char_text = "; ".join(f"{c.get('name')}: {c.get('description', '')}" for c in chars) or "nessuno in particolare"
    from core.modules.sigma_creative_lab.video.preproduction import scene_brief
    pre = (prod.get("bible") or {}).get("pre") or {}
    scene_info = next((x for x in pre.get("scenes") or [] if x.get("title") == scene), {})
    titles = [x.get("title") for x in pre.get("scenes") or []]
    after = (pre.get("scenes") or [])[titles.index(scene) + 1] if scene in titles[:-1] else {}
    msg = SHOTS_PROMPT.format(world=scene_brief(pre, scene_info),
                              next_scene=f"{after.get('title', '')}: {after.get('summary', '')}" if after else "non indicata",min_shot=bounds[0], max_shot=bounds[1], style=style or "libero", characters=char_text,
                              index=1, total=1, title=scene, seconds=round(seconds),
                              # Le indicazioni sono la scena; la versione vecchia e' solo materiale da correggere.
                              # Passata come riassunto, il modello la seguiva e ignorava le indicazioni (Pepe
                              # restava in una scena dove non doveva esserci).
                              # Con la pre-produzione la scena com'e' scritta (e corretta dall'utente) viene prima.
                              summary=(f"{scene_info['summary']}\nIndicazioni del regista: " if scene_info.get("summary") else "")
                                      + f"{notes.strip()}\n(Versione precedente, da correggere secondo le indicazioni: "
                                      + " ".join(sh["prompt"] for sh in old)[:1500] + ")",
                              previous="(vedi ultima inquadratura)", last_shot=before, props="nessuno",
                              notes="\n- le indicazioni del regista PREVALGONO sulla versione precedente: chi non deve "
                                    "comparire non compare, cio' che chiedono avviene;\n- mantieni o aggiungi le battute "
                                    "di dialogo che la storia richiede (chi parla deve essere visibile).")
    items = extract_json(gen([{"role": "user", "content": msg}], 4000), list)
    new = _normalize_shots(items, seconds, bounds, chars, scene, style=style,
                           location=str(scene_info.get("location") or old[0].get("location") or ""))
    if scene_info.get("lines"):
        from core.modules.sigma_creative_lab.video.preproduction import place_lines
        place_lines(new, scene_info["lines"])
    if not new:
        raise ValueError("il modello non ha scritto inquadrature valide")
    new[0]["transition"] = old[0].get("transition", "cut") if idx[0] > 0 else "cut"
    _to_english(new, gen)
    prod["shots"] = shots[:idx[0]] + new + shots[idx[-1] + 1:]
    return new


#: Parole con cui un prompt annuncia un'inquadratura nuova: dopo di loro un
#: "continue" non puo' esserlo davvero (si ripartirebbe dall'ultimo fotogramma
#: di un'altra ripresa e il generatore trasformerebbe un'immagine nell'altra).
NEW_FRAMING = ("close-up", "close up", "wide shot", "medium shot", "long shot", "aerial", "establishing",
               "over-the-shoulder", "low angle", "high angle", "top-down", "extreme close", "insert shot",
               "cut to", "from below", "from above")


def _strip_style(prompt: str, style: str) -> str:
    """Toglie lo stile ripetuto dal modello: compose_prompt lo aggiunge gia' una volta."""
    text = prompt
    if style.strip():
        low, target = text.lower(), style.strip().rstrip(".").lower()
        k = low.find(target)
        while k != -1:
            # Via tutta la frase di stile ("... illustration with high contrast lines"), non solo le parole.
            end = min([j for j in (text.find(".", k), text.find(";", k)) if j != -1] or [len(text)])
            text = text[:k] + text[end:]
            low = text.lower()
            k = low.find(target)
    text = re.sub(r"\s*[,;]\s*([,;.]|$)", r"\1", re.sub(r"\s{2,}", " ", text))
    return re.sub(r"\.(\s*\.)+", ".", text).strip(" ,;")


def _continue_is_plausible(prev: dict, shot: dict) -> bool:
    head = shot["prompt"].lower()[:60]
    if any(w in head for w in NEW_FRAMING):
        return False
    # Si prosegue la ripresa solo con personaggi gia' inquadrati: chi entra in scena in una "continue"
    # non ha fotogramma chiave ne' riferimento, e il modello video lo inventa (Lia coi capelli ricci
    # nella prova "Il seme di Lia"). Chi esce di scena invece va bene.
    a, b = set(prev.get("refs") or []), set(shot.get("refs") or [])
    return b <= a


def continues(prod: dict, index: int) -> bool:
    """L'inquadratura prosegue davvero dalla precedente (stessa ripresa, nessun personaggio nuovo)?"""
    shots = prod.get("shots") or []
    if index <= 0 or index >= len(shots) or shots[index].get("transition") != "continue":
        return False
    return set(shots[index].get("refs") or []) <= set(shots[index - 1].get("refs") or [])


def _drop_repeats(new: list, before: list, threshold: float = 0.8) -> list:
    """Toglie le inquadrature che ricopiano una gia' scritta.

    Prova del picnic: il modello riceve l'ultima inquadratura per continuita' e la ricopiava
    quasi identica in testa a ogni scena nuova (Pepe correva verso i fiori quattro volte).
    """
    from difflib import SequenceMatcher
    seen = [sh["prompt"].lower() for sh in before[-6:]]
    kept = []
    for sh in new:
        text = sh["prompt"].lower()
        # Fra frasi brevi la somiglianza e' alta anche quando dicono cose diverse: li' conta solo l'identita'.
        if any(text == old or (min(len(text), len(old)) >= 120 and SequenceMatcher(None, text, old).ratio() >= threshold)
               for old in seen):
            log.info(f"inquadratura ripetuta tolta: {sh['prompt'][:80]}")
            continue
        kept.append(sh)
        seen.append(text)
    return kept or new[:1]


def _normalize_shots(items, scene_s: float, bounds: tuple, characters: list, scene_title: str,
                     style: str = "", location: str = "") -> list[dict]:
    lo, hi = bounds
    if isinstance(items, dict):
        items = items.get("shots") or [items]
    names = {c.get("name", "").lower(): c for c in characters if c.get("name")}
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not str(it.get("prompt", "")).strip():
            continue
        dur = min(hi, max(lo, float(it.get("seconds") or lo)))
        prompt = apply_aliases(_strip_style(str(it["prompt"]), style), characters)
        # Il nome canonico della bibbia, non come l'ha scritto il modello ("keeper" -> "Keeper"); anche
        # i ruoli ("the shonen") valgono come il personaggio, e chi e' nominato nel prompt e' in scena.
        aliases = {str(a).lower(): c["name"] for c in characters for a in c.get("aliases") or []}
        refs = []
        for n in it.get("characters") or []:
            key = str(n).lower().replace("the ", "").strip()
            name = names.get(key, {}).get("name") or aliases.get(key)
            if name and name not in refs:
                refs.append(name)
        for c in characters:
            if c.get("name") and c["name"] not in refs and re.search(rf"\b{re.escape(c['name'])}\b", prompt, re.I):
                refs.append(c["name"])
        dialogue = _dialogue_of(it.get("dialogue"), characters)
        if dialogue and dialogue["character"] not in refs:
            refs.append(dialogue["character"])           # chi parla e' in scena
        extra = {"dialogue": dialogue} if dialogue else {}
        expressions = {}
        for k, v in (it.get("expressions") or {}).items() if isinstance(it.get("expressions"), dict) else []:
            who = names.get(str(k).lower(), {}).get("name") or aliases.get(str(k).lower())
            if who and str(v).strip():
                expressions[who] = str(v).strip()[:120]
        if expressions:
            extra["expressions"] = expressions
        # Il luogo e' quello della scena, col nome della pre-produzione: il modello lo traduceva
        # ("il prato" -> "the meadow") e la descrizione del luogo non si agganciava piu'.
        if str(location or it.get("location") or "").strip():
            extra["location"] = str(location or it.get("location")).strip()
        shot = new_shot(prompt, dur, str(it.get("transition", "cut")),
                        audio=str(it.get("audio", "")), refs=refs, scene=scene_title,
                        props=[str(x).strip() for x in it.get("props") or [] if str(x).strip()], **extra)
        if shot["transition"] == "continue" and (not out or not _continue_is_plausible(out[-1], shot) or dialogue):
            # Una battuta parte dal suo fotogramma chiave, inquadrato sul viso di chi parla: l'ultimo
            # fotogramma della ripresa precedente puo' averlo piccolo o di spalle.
            shot["transition"] = "cut"
        out.append(shot)
    # Se la scena e' piu' lunga di quanto coprono le inquadrature, si allungano
    # proporzionalmente entro il massimo per clip, senza inventare contenuto.
    covered = sum(s["duration_s"] for s in out)
    if out and covered < scene_s * 0.8:
        k = min(hi / max(s["duration_s"] for s in out), scene_s / covered)
        for s in out:
            s["duration_s"] = round(min(hi, s["duration_s"] * k), 2)
    elif out and covered > scene_s * 1.15:
        # Troppe inquadrature per la durata della scena: prima si accorciano fino
        # al minimo, poi si tolgono le ultime (un video da 10 minuti non deve
        # uscire da 12 perche' il modello si e' dilungato).
        k = max(lo / min(s["duration_s"] for s in out), scene_s / covered)
        for s in out:
            s["duration_s"] = round(max(lo, s["duration_s"] * k), 2)
        while len(out) > 1 and sum(s["duration_s"] for s in out) > scene_s * 1.15:
            out.pop()
    return out


# ---------------------------------------------------------------------------
# Composizione del prompt di un'inquadratura
# ---------------------------------------------------------------------------

MOTION_GUARD = ("Natural, physically plausible motion: people move forward in the direction they face, "
                "feet step on the ground, held objects stay in the hands.")


def compose_prompt(prod: dict, shot: dict, use_refs: bool) -> str:
    bible = prod.get("bible") or {}
    parts = []
    # Le LoRA di stile si attivano con le loro parole chiave: senza, il peso
    # della LoRA c'e' ma lo stile resta quasi spento.
    words = [w.strip().rstrip(",") for l in bible.get("loras") or [] for w in (l.get("trained_words") or []) if w.strip()]
    if words:
        parts.append(", ".join(dict.fromkeys(words)) + ".")
    if bible.get("style"):
        parts.append(bible["style"].strip().rstrip(".") + ".")
    from core.modules.sigma_creative_lab.video.genres import shot_characters
    in_shot = shot_characters(prod, shot)
    if use_refs:
        refs_with_img = [c for c in in_shot if c.get("ref_image")]
        for i, c in enumerate(refs_with_img, 1):
            parts.append(f"{c['name']} is the character from <Picture {i}>; keep identity, face and outfit consistent.")
    for c in in_shot:
        if c.get("description"):
            parts.append(f"{c['name']}: {c['description'].strip().rstrip('.')}.")
    if shot.get("transition") == "continue":
        parts.append("Continue the same shot seamlessly from the first frame, same lighting and color grading.")
    action = ltx_action(shot) if is_ltx(prod.get("settings") or {}) else ""
    parts.append(action or shot["prompt"].strip())
    for fix in shot.get("fixes") or []:
        # Correzioni dell'utente: vincoli espliciti, prima dei suggerimenti automatici del giudice.
        parts.append(str(fix.get("text", "")).strip().rstrip(".") + ".")
    props = [str(x).strip() for x in shot.get("props") or [] if str(x).strip()]
    if props:
        # Il continuity li registra per inquadratura: nel prompt diventano un vincolo per il modello
        # e un testo che il giudice legge (gli oggetti in mano li ricava dal prompt, vedi held_objects).
        parts.append(f"Objects in the scene, same shape, color and material in every shot: {', '.join(props)}.")
    # Correzioni suggerite dal giudice sui tentativi scartati di questa inquadratura.
    for fix in shot.get("prompt_fixes") or []:
        parts.append(fix.strip().rstrip(".") + ".")
    from core.modules.sigma_creative_lab.video.preproduction import world_lines
    # Luogo e oggetti come li ha descritti la pre-produzione: lo stesso vaso in ogni inquadratura.
    parts += world_lines(prod, shot)
    if (prod.get("settings") or {}).get("motion_guard", True):
        # Con cfg 1 H3 ignora il prompt negativo: il movimento corretto va chiesto in positivo.
        parts.append(MOTION_GUARD)
    if shot.get("dialogue"):
        d = shot["dialogue"]
        if is_ltx(prod.get("settings") or {}) and d.get("text"):
            # L'audio della battuta e' gia' dato (voce del personaggio): LTX deve solo muovere le labbra a tempo.
            who = d.get("character", "")
            others = [n for n in shot.get("refs") or [] if n != who]
            # Con il viso piccolo o di spalle il labiale non si vede: "Il seme di Lia" aveva Lia che parlava
            # correndo verso la porta, e il nonno in campo largo con la bocca nascosta dalla barba.
            parts.append(f"Medium close-up of {who}, face toward the camera, mouth clearly visible. "
                         f"{who} is talking, saying: \"{d['text']}\". Only {who}'s lips move, clearly in sync with "
                         f"the words, with natural facial expression and small head movements; after the last word "
                         f"{who}'s mouth closes."
                         + (f" {', '.join(others)} listen{'s' if len(others) == 1 else ''} in silence with "
                            f"closed mouth{'s' if len(others) > 1 else ''}." if others else ""))
        # Il prompt di un dialogo descrive gia' il suo audio (solo la voce):
        # aggiungere lo stile musicale coprirebbe la battuta.
        return "\n".join(parts)
    if (prod.get("soundtrack") or {}).get("enabled"):
        # La musica arriva dalla colonna sonora: dai clip servono solo suoni e voci.
        audio = shot.get("audio", "").strip()
        parts.append(f"Audio: {audio + '. ' if audio else ''}No background music, only diegetic sound.")
    else:
        audio = " ".join(x for x in (bible.get("audio_style", ""), shot.get("audio", "")) if x).strip()
        if audio:
            parts.append(f"Audio: {audio}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Motori dei clip
# ---------------------------------------------------------------------------

class EngineError(RuntimeError):
    """Guasto del motore (avvio, blocco, connessione), non difetto del clip.

    Non consuma i tentativi dell'inquadratura: lo stesso clip su un motore
    sano riuscirebbe. La corsia aspetta e riprova; dopo guasti ripetuti si ritira.
    """


#: Nessun avanzamento per tanto tempo = motore bloccato. Uno step di H3 dura
#: 3-25 s, il caricamento a freddo dei pesi qualche minuto.
STALL_TIMEOUT_S = 600
MAX_LANE_FAILURES = 3


class ClipEngine:
    """Interfaccia: genera un clip su disco e ritorna i suoi metadati."""
    name = ""

    async def render(self, prod: dict, shot: dict, request: dict, progress=None) -> dict:
        raise NotImplementedError

    async def release(self) -> None:
        """Libera la VRAM a fine produzione: dopo il lease la GPU torna all'LLM."""

    async def cancel_running(self) -> None:
        """Interrompe il clip in corso, che altrimenti durerebbe minuti."""
        queue = await self.backend.get_queue()
        for job_id in queue.get("running", []) + queue.get("pending", []):
            await self.backend.cancel_job(job_id)


class NativeClipEngine(ClipEngine):
    name = "sigma_native"

    def __init__(self, config: dict | None = None):
        from core.modules.sigma_creative_lab.backends.sigma_native_backend import SigmaNativeBackend
        self.backend = SigmaNativeBackend(config=config or {})
        self.placement = ""

    async def release(self) -> None:
        try:
            await asyncio.to_thread(self.backend.runtime.post, "/v1/unload", {}, 300)
        except Exception as e:
            log.debug(f"unload del worker non riuscito: {e}")

    async def render(self, prod: dict, shot: dict, request: dict, progress=None) -> dict:
        s = prod["settings"]
        if is_ltx(s):
            raise EngineError("LTX-2.5 gira solo con ComfyUI: imposta il backend 'comfyui' nella produzione")
        profile = s["ref_profile"] if request.get("ref_images") else s["profile"]
        job = {
            "prompt": request["prompt"], "negative_prompt": request.get("negative_prompt", ""),
            "width": s["width"], "height": s["height"], "fps": s["fps"], "video_frames": request["frames"],
            "seed": request["seed"], "steps": s["steps"], "sample_method": s["sample_method"],
            "scheduler": s["scheduler"], "cfg_scale": s["cfg_scale"],
            "cache_mode": s.get("cache_mode", ""), "cache_option": s.get("cache_option", ""),
            "init_image": request.get("init_image", ""), "ref_images": request.get("ref_images", []),
            "loras": request.get("loras", []), "output_path": request["output_path"],
            "save_last_frame": True, "video_codec": s.get("clip_codec", "libx264"),
        }
        try:
            record = await self.backend.run_job({"profile": profile, "placement": self.placement or s.get("placement", ""),
                                                 "job": job},
                                                progress_cb=progress)
        except (BackendUnavailable, ConnectionError, OSError) as e:
            # Worker morto o irraggiungibile: al prossimo job il runtime lo riavvia.
            raise EngineError(f"worker nativo non raggiungibile: {e}") from e
        result = record.get("result") or {}
        return {"clip_path": result.get("output_path", ""), "last_frame": result.get("last_frame_path", ""),
                "frames": result.get("frame_count", 0), "seed": result.get("seed"), "has_audio": result.get("has_audio"),
                "timings": record.get("timings") or {}}


class ComfyClipEngine(ClipEngine):
    name = "comfyui"

    def __init__(self, config: dict | None = None):
        from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
        cfg = config or {}
        self.config = cfg
        self.gpu = cfg.get("gpu")
        self.backend = ComfyUIBackend(base_url=cfg.get("url", "http://127.0.0.1:8188"), config=cfg)
        self._ready = False

    async def _ensure(self) -> None:
        """Con una GPU assegnata usa (o avvia) l'istanza ComfyUI di quella scheda."""
        if self._ready or self.gpu is None:
            return
        from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
        try:
            url = await asyncio.to_thread(instances.ensure, int(self.gpu), None, self.config.get("install_dir", ""),
                                          180.0, self.config.get("flags"))
        except Exception as e:
            raise EngineError(f"ComfyUI su GPU {self.gpu} non disponibile: {e}") from e
        self.backend.base_url = url
        self._ready = True

    async def _run_watched(self, graph: dict, progress, timeout_s: int):
        """Esegue il grafo; se ComfyUI smette di dare segni di vita, lo riavvia."""
        last = {"t": time.monotonic()}

        def beat(p):
            last["t"] = time.monotonic()
            if progress:
                progress(p)

        task = asyncio.create_task(self.backend.run({"workflow": graph}, progress_cb=beat, timeout_s=timeout_s))
        while not task.done():
            await asyncio.wait({task}, timeout=15)
            if not task.done() and time.monotonic() - last["t"] > STALL_TIMEOUT_S:
                task.cancel()
                log.error(f"ComfyUI su GPU {self.gpu}: nessun avanzamento da {STALL_TIMEOUT_S} s, riavvio")
                if self.gpu is not None:
                    from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
                    try:
                        self.backend.base_url = await asyncio.to_thread(instances.restart, int(self.gpu))
                    except Exception as e:
                        log.error(f"riavvio di ComfyUI su GPU {self.gpu} fallito: {e}")
                        self._ready = False
                raise EngineError(f"ComfyUI su GPU {self.gpu} bloccato: riavviato")
        try:
            return task.result()
        except (BackendUnavailable, ConnectionError, OSError) as e:
            self._ready = False
            raise EngineError(f"ComfyUI su GPU {self.gpu} non raggiungibile: {e}") from e

    async def release(self) -> None:
        if self.gpu is None:
            return
        from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
        port = int(self.backend.base_url.rsplit(":", 1)[1])
        await asyncio.to_thread(instances.free, port)

    async def _render_wan(self, prod: dict, shot: dict, request: dict, progress, mode: str) -> dict:
        """Wan 2.2: S2V per le battute (labiale e gesti dalla voce), I2V per le azioni."""
        from core.modules.sigma_creative_lab.generators.adapters.comfy_wan import (
            WAN_FPS, build_wan_i2v, build_wan_s2v,
        )
        s = prod["settings"]
        seconds = (request["frames"] - 1) / float(s.get("fps", FPS))
        params = {"prompt": request["prompt"], "width": 832, "height": 480, "seconds": seconds,
                  "seed": request["seed"], "filename_prefix": f"sigma/{prod['id']}/{shot['id']}"}
        params["image"] = await self.backend.upload_image(Path(request["init_image"]).read_bytes(),
                                                          f"{prod['id']}_{shot['id']}_wan.png")
        if mode == "s2v":
            params["audio"] = await self.backend.upload_image(_padded_line(Path(request["audio"]), seconds),
                                                              f"{prod['id']}_{shot['id']}_wanline.wav")
        graph = build_wan_s2v(params) if mode == "s2v" else build_wan_i2v(params)
        t0 = time.monotonic()
        data, _name = await self._run_watched(graph, progress, int(s.get("timeout", 7200)))
        elapsed = time.monotonic() - t0
        out = Path(request["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        last = extract_last_frame(out)
        # "frames" conta in fotogrammi del film (24 fps): la colonna sonora misura le scene cosi'.
        return {"clip_path": str(out), "last_frame": str(last) if last else "",
                "frames": int(round(seconds * float(s.get("fps", FPS)))) + 1, "seed": request["seed"],
                "has_audio": mode == "s2v", "engine_used": f"wan_{mode}",
                "timings": {"total_s": elapsed, "s_per_step": elapsed / 4, "native_fps": WAN_FPS}}

    async def _render_ltx(self, prod: dict, shot: dict, request: dict, progress=None) -> dict:
        """LTX-2.5: niente riferimenti R2V ne' LoRA di H3; il personaggio arriva dal primo fotogramma."""
        from core.modules.sigma_creative_lab.generators.adapters.comfy_ltx import build_ltx_video
        s = prod["settings"]
        width, height = ltx_dims(s)
        params = {"prompt": request["prompt"], "negative": request.get("negative_prompt") or "",
                  "width": width, "height": height, "length": request["frames"], "fps": s["fps"],
                  "seed": request["seed"], "filename_prefix": f"sigma/{prod['id']}/{shot['id']}",
                  "loras": [{"name": Path(l["path"]).name, "strength": l.get("multiplier", 1.0)}
                            for l in request.get("loras", []) if lora_family(l) in ("ltx", "")]}
        for key, src in (("first_frame", "init_image"), ("last_frame", "end_image")):
            if request.get(src):
                params[key] = await self.backend.upload_image(Path(request[src]).read_bytes(),
                                                              f"{prod['id']}_{shot['id']}_{key}.png")
        if request.get("audio"):
            # Battuta gia' sintetizzata: LTX la tiene ferma e anima il labiale su di essa.
            params["audio"] = await self.backend.upload_image(
                _padded_line(Path(request["audio"]), (request["frames"] - 1) / float(s["fps"])),
                f"{prod['id']}_{shot['id']}_line.wav")
        if request.get("ref_images") and not request.get("init_image"):
            log.warning(f"{shot['id']}: LTX non ha la modalita' a riferimenti, il personaggio non e' vincolato "
                        "(attiva i fotogrammi chiave)")
        t0 = time.monotonic()
        data, _name = await self._run_watched(build_ltx_video(params), progress, int(s.get("timeout", 7200)))
        elapsed = time.monotonic() - t0
        out = Path(request["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        last = extract_last_frame(out)
        return {"clip_path": str(out), "last_frame": str(last) if last else "", "frames": request["frames"],
                "seed": request["seed"], "has_audio": True,
                "timings": {"total_s": elapsed, "s_per_step": elapsed / 11}}   # 8 + 3 passi distillati

    async def render(self, prod: dict, shot: dict, request: dict, progress=None) -> dict:
        from core.modules.sigma_creative_lab.generators.adapters.comfy_h3 import build_h3_video
        await self._ensure()
        s = prod["settings"]
        wan = wan_mode(s, shot, request)
        if wan:
            return await self._render_wan(prod, shot, request, progress, wan)
        if is_ltx(s):
            return await self._render_ltx(prod, shot, request, progress)
        params = {"prompt": request["prompt"], "width": s["width"], "height": s["height"],
                  "length": request["frames"], "seed": request["seed"], "steps": s["steps"],
                  "sampler": s["sample_method"], "scheduler": s["scheduler"], "fps": s["fps"],
                  "filename_prefix": f"sigma/{prod['id']}/{shot['id']}",
                  "weights": s.get("weights", "int8"),
                  "easycache": s.get("cache_mode") in ("easycache", "comfy_easycache"),
                  "easycache_threshold": float(s.get("easycache_threshold", 0.2)),
                  "loras": [{"name": Path(l["path"]).name, "strength": l.get("multiplier", 1.0)}
                            for l in request.get("loras", []) if lora_family(l) in ("minimax_h3", "")]}
        if request.get("ref_images"):
            params["ref_images"] = [
                await self.backend.upload_image(Path(r).read_bytes(), f"{prod['id']}_ref_{Path(r).stem}.png")
                for r in request["ref_images"]]
        if request.get("init_image"):
            params["first_frame"] = await self.backend.upload_image(Path(request["init_image"]).read_bytes(),
                                                                    f"{prod['id']}_{shot['id']}_first.png")
        if request.get("end_image"):
            params["last_frame"] = await self.backend.upload_image(Path(request["end_image"]).read_bytes(),
                                                                   f"{prod['id']}_{shot['id']}_last.png")
        if request.get("ref_audios"):
            params["ref_audios"] = [
                await self.backend.upload_image(Path(a).read_bytes(), f"{prod['id']}_voice_{Path(a).stem}{Path(a).suffix}")
                for a in request["ref_audios"]]
        t0 = time.monotonic()
        data, _name = await self._run_watched(build_h3_video(params), progress, int(s.get("timeout", 7200)))
        elapsed = time.monotonic() - t0
        out = Path(request["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        last = extract_last_frame(out)
        return {"clip_path": str(out), "last_frame": str(last) if last else "", "frames": request["frames"],
                "seed": request["seed"], "has_audio": True,
                "timings": {"total_s": elapsed, "s_per_step": elapsed / max(1, s["steps"])}}


def default_lane_specs(backend: str) -> list[dict]:
    """Una corsia per GPU con il motore richiesto (vedi ProductionRunner.lanes)."""
    from core.modules.sigma_creative_lab.native.runtime import DEFAULT_PORT, auto_lanes
    gpus = auto_lanes()                  # dalla GPU con piu' VRAM
    if not gpus:
        return [{"engine": "sigma_native", "placement": "cpu", "port": DEFAULT_PORT, "label": "CPU"}]
    specs = []
    for k, g in enumerate(gpus):
        engine = backend
        if backend == "hybrid":
            engine = "comfyui" if k == 0 else "sigma_native"
        ordinal = int(g["placement"].split(":", 1)[1])
        # Rapporto di velocita' iniziale rispetto alla GPU principale, finche'
        # lo scheduler non lo misura sui clip: in prima approssimazione la VRAM.
        # Con la VRAM come stima: 16 contro 8 GB da' 2,0, come misurato dal benchmark
        # (5060 150 s contro 74 della 5070 Ti, entrambe con EasyCache).
        ratio = max(1.0, gpus[0]["vram_gb"] / max(1.0, g["vram_gb"])) if k else 1.0
        specs.append({"engine": engine, "gpu": g["device_index"], "ordinal": ordinal,
                      "port": g["port"], "label": g["label"], "assumed_ratio": round(ratio, 2)})
    return specs


def wan_installed(mode: str) -> bool:
    """Pesi di Wan 2.2 per S2V o I2V nella cartella dei modelli di ComfyUI."""
    from core.modules.sigma_creative_lab.generators.adapters.comfy_wan import WAN_FILES
    try:
        from core.modules.sigma_creative_lab.model_downloader import discover_models_root
        root = Path(discover_models_root())
    except Exception:
        return False
    need = {"s2v": [("diffusion_models", "s2v"), ("loras", "s2v_lora"), ("audio_encoders", "audio_encoder")],
            "i2v": [("diffusion_models", "i2v_high"), ("diffusion_models", "i2v_low"), ("loras", "i2v_lora_high"),
                    ("loras", "i2v_lora_low")]}[mode] + [("text_encoders", "clip"), ("vae", "vae")]
    return all((root / sub / WAN_FILES[key]).is_file() for sub, key in need)


def wan_mode(settings: dict, shot: dict, request: dict) -> str:
    """"s2v", "i2v" o "" (LTX/H3) per questa inquadratura.

    Scelta per inquadratura (`shot["engine"]`) o per tipo nelle impostazioni: `dialogue_engine` per le
    battute, `motion_engine` per le altre. Wan parte sempre da un fotogramma chiave.
    """
    if not request.get("init_image"):
        return ""
    choice = str(shot.get("engine") or "")
    if request.get("audio"):
        choice = choice or str(settings.get("dialogue_engine") or "")
        return "s2v" if choice == "wan_s2v" and wan_installed("s2v") else ""
    choice = choice or str(settings.get("motion_engine") or "")
    return "i2v" if choice == "wan_i2v" and wan_installed("i2v") else ""


def wants_ambience(prod: dict) -> bool:
    """Ambienti sotto le battute: con LTX (l'audio delle battute e' solo voce) e i luoghi descritti."""
    s = prod.get("settings") or {}
    pre = (prod.get("bible") or {}).get("pre") or {}
    return bool(s.get("ambience", True)) and is_ltx(s) and bool(pre.get("locations")) and \
        any(sh.get("dialogue") for sh in prod.get("shots") or [])


def clip_engine_for(backend: str, config: dict | None = None) -> ClipEngine:
    if backend == "comfyui":
        return ComfyClipEngine(config)
    return NativeClipEngine(config)


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------

def ffmpeg_bin(tool: str = "ffmpeg") -> str:
    from core.modules.sigma_creative_lab.native.runtime import locate_ffmpeg
    d = locate_ffmpeg()
    if not d:
        raise RuntimeError("ffmpeg non trovato: serve per montare il video")
    exe = d / (f"{tool}.exe" if os.name == "nt" else tool)
    return str(exe if exe.exists() else tool)


def _run(cmd: list, timeout: int = 3600) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} fallito: {proc.stderr.strip()[-800:]}")
    return proc


def probe(path: Path) -> dict:
    out = _run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries",
                "stream=codec_type,width,height,nb_frames,duration,sample_rate:format=duration", "-of", "json",
                str(path)]).stdout
    doc = json.loads(out)
    streams = doc.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    container = float((doc.get("format") or {}).get("duration") or 0)
    # Un file solo audio non ha stream video, e FLAC/WAV non sempre dichiarano la
    # durata dello stream: si ripiega su quella del contenitore.
    return {"width": v.get("width"), "height": v.get("height"), "frames": int(v.get("nb_frames") or 0),
            "duration": float(v.get("duration") or 0) or (0.0 if v else container), "has_audio": bool(a),
            "audio_duration": float(a.get("duration") or 0) or container,
            "sample_rate": int(a.get("sample_rate") or 0)}


def extract_last_frame(video: Path) -> Path | None:
    out = video.with_suffix(".last.png")
    try:
        _run([ffmpeg_bin(), "-v", "error", "-y", "-sseof", "-0.2", "-i", str(video), "-update", "1", "-q:v", "1", str(out)])
        return out
    except RuntimeError as e:
        log.warning(f"ultimo fotogramma non estratto da {video}: {e}")
        return None


def assemble(prod: dict, out_path: Path, fps: int = FPS, codec: str = "libx264", quality: int = 18,
             progress: Callable[[str], None] | None = None, output_height: int = 0,
             settings: dict | None = None) -> Path:
    """Unisce i clip in ordine.

    Due passaggi: ogni clip viene normalizzato in un segmento (taglio del
    frame duplicato nei `continue`, audio a 48 kHz con micro-dissolvenze che
    evitano i click ai tagli), poi i segmenti si concatenano senza ricodifica.
    Ricodificare tutto in un solo grafo con cento ingressi sarebbe fragile e
    non riprendibile.
    """
    shots = [s for s in prod["shots"] if s.get("status") == "done" and s.get("clip_path")]
    if not shots:
        raise RuntimeError("nessun clip completato da montare")
    lock = _assembly_lock(prod.get("id", str(out_path)))
    if not lock.acquire(blocking=False):
        raise RuntimeError("un montaggio di questa produzione e' gia' in corso")
    ambience = {k: v for k, v in (prod.get("ambience") or {}).items() if Path(v).is_file()} \
        if (settings or prod.get("settings") or {}).get("ambience", True) else {}
    if ambience:
        shots = [{**sh, "_ambience": ambience.get(str(sh.get("location") or "").strip().lower(), "")}
                 if sh.get("dialogue") else sh for sh in shots]
    try:
        return _assemble_locked(shots, out_path, fps, codec, quality, progress, output_height, settings)
    finally:
        lock.release()


_assembly_locks: dict = {}
_assembly_guard = threading.Lock()


def _assembly_lock(key: str) -> threading.Lock:
    with _assembly_guard:
        return _assembly_locks.setdefault(key, threading.Lock())


def _assemble_locked(shots: list, out_path: Path, fps: int, codec: str, quality: int,
                     progress, output_height: int, settings: dict | None) -> Path:
    # Cartella di lavoro propria di questo montaggio: con una sola cartella per produzione, il montaggio
    # di fine render e "Monta i clip pronti" si cancellavano i segmenti a vicenda (prova dei samurai).
    import tempfile
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{out_path.stem}_", dir=out_path.parent))
    ff = ffmpeg_bin()
    list_lines = []
    # La misura del film e' quella della prima clip: Wan genera a 832x480, LTX a 1280x704, e la
    # concatenazione senza ricodifica vuole segmenti tutti uguali.
    first = probe(Path(shots[0]["clip_path"]))
    base_w, base_h = int(first["width"] or 0), int(first["height"] or 0)
    timeline = []                                   # (inizio nel film, durata del segmento, inquadratura)
    t = 0.0
    for i, shot in enumerate(shots):
        src = Path(shot["clip_path"])
        if not src.is_file():
            raise RuntimeError(f"clip mancante: {src}")
        if output_height:
            from core.modules.sigma_creative_lab.video import postprocess as pp
            src = pp.upscaled_source(src, output_height, settings or {})
        # Audio PCM nei segmenti e AAC una volta sola alla fine: ogni AAC aggiunge il suo ritardo di
        # codifica (~20-30 ms) e su venti clip le voci finivano mezzo secondo avanti alle labbra.
        seg = work / f"{i:05d}_{shot['id']}.mkv"
        drop_first = shot.get("transition") == "continue" and i > 0
        info = probe(src)
        dur = info["duration"] or (info["frames"] / fps)
        start = 1.0 / fps if drop_first else 0.0
        vf = f"trim=start_frame={1 if drop_first else 0},setpts=PTS-STARTPTS,fps={fps}"
        if base_w and base_h and not output_height and (info["width"], info["height"]) != (base_w, base_h):
            vf += f",scale={base_w}:{base_h}:flags=lanczos:force_original_aspect_ratio=increase,crop={base_w}:{base_h}"
        if output_height and info["height"] and output_height > info["height"]:
            # Upscale Lanczos con nitidezza leggera: costa pochi secondi per clip.
            vf += f",scale=-2:{output_height}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0"
        if output_height and base_w and base_h:
            # Anche con l'upscale tutte le clip escono alla stessa misura (16:9 della prima clip).
            ow = int(round(base_w * output_height / base_h / 2) * 2)
            vf += f",scale={ow}:{output_height}:flags=lanczos:force_original_aspect_ratio=increase,crop={ow}:{output_height}"
        vf += ",format=yuv420p"
        cmd = [ff, "-v", "error", "-y", "-i", str(src)]
        amb = shot.get("_ambience") or ""
        if info["has_audio"] and amb:
            # Battuta: la voce sopra, l'ambiente del luogo sotto (-14 dB), da un punto diverso per ogni
            # inquadratura cosi' il giro di 10 secondi non si riconosce.
            fade = 0.012
            seg_s = max(0.0, dur - start)
            offset = (i * 3.7) % AMBIENCE_LOOP_S
            cmd += ["-stream_loop", "-1", "-i", amb]
            af = (f"[0:a]atrim=start={start:.5f},asetpts=PTS-STARTPTS,aresample=48000,apad,atrim=end={seg_s:.5f}[voice];"
                  f"[1:a]atrim=start={offset:.3f},asetpts=PTS-STARTPTS,aresample=48000,atrim=end={seg_s:.5f},"
                  f"volume=-14dB,afade=t=in:d=0.3,afade=t=out:st={max(0.0, seg_s - 0.3):.5f}:d=0.3[amb];"
                  f"[voice][amb]amix=inputs=2:duration=first:normalize=0,"
                  f"afade=t=in:d={fade},afade=t=out:st={max(0.0, seg_s - fade):.5f}:d={fade}[a]")
            cmd += ["-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]", "-map", "[a]"]
        elif info["has_audio"]:
            fade = 0.012
            # L'audio va portato alla durata esatta del video: le clip con battuta hanno la traccia lunga
            # quanto la battuta (2,7 s su 6), e con la concatenazione senza ricodifica tutto l'audio
            # successivo anticipava; a fine "Il seme di Lia" le voci erano 6 s avanti alle labbra.
            af = (f"atrim=start={start:.5f},asetpts=PTS-STARTPTS,aresample=48000,"
                  f"apad,atrim=end={max(0.0, dur - start):.5f},"
                  f"afade=t=in:d={fade},afade=t=out:st={max(0.0, dur - start - fade):.5f}:d={fade}")
            cmd += ["-filter_complex", f"[0:v]{vf}[v];[0:a]{af}[a]", "-map", "[v]", "-map", "[a]"]
        else:
            # Traccia muta: la concatenazione senza ricodifica richiede che tutti i segmenti abbiano audio.
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", f"[0:v]{vf}[v]",
                    "-map", "[v]", "-map", "1:a", "-shortest"]
        cmd += _video_codec_args(codec, quality) + ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(seg)]
        _run(cmd)
        timeline.append((t, dur - start, shot))
        t += dur - start
        list_lines.append(f"file '{seg.resolve().as_posix()}'")
        if progress:
            progress(f"Montaggio {i + 1}/{len(shots)}")
    concat_list = work / "concat.txt"
    concat_list.write_text("\n".join(list_lines) + "\n", encoding="utf-8")
    partial = work / f"montato{out_path.suffix}"
    try:
        _run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
              "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(partial)], timeout=7200)
        # Il video precedente resta intatto finche' il nuovo non e' completo.
        os.replace(partial, out_path)
        write_subtitles(timeline, out_path.with_suffix(".srt"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out_path


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_subtitles(timeline: list, path: Path) -> Path | None:
    """Sottotitoli delle battute, accanto al video: per chi impara a leggere e per guardare senza audio."""
    entries = []
    for start, seg_s, shot in timeline:
        d = shot.get("dialogue") or {}
        if not str(d.get("text") or "").strip():
            continue
        lead = DIALOGUE_LEAD_S if d.get("audio") else 0.0
        end = start + min(seg_s, max(float(d.get("seconds") or 0), lead + 1.5))
        entries.append(f"{len(entries) + 1}\n{_srt_time(start + lead)} --> {_srt_time(end)}\n{d['text'].strip()}\n")
    vtt = path.with_suffix(".vtt")
    if not entries:
        path.unlink(missing_ok=True)
        vtt.unlink(missing_ok=True)
        return None
    path.write_text("\n".join(entries), encoding="utf-8")
    # Il lettore del browser legge solo WebVTT: stesso contenuto, millisecondi col punto.
    vtt.write_text("WEBVTT\n\n" + "\n".join(re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", e) for e in entries),
                   encoding="utf-8")
    return path


def animatic(prod: dict, out_path: Path, width: int = 960, fps: int = FPS) -> Path:
    """Anteprima animatica: i fotogrammi chiave con le voci e i tempi del film, in un minuto.

    Si guarda la storia (ritmo, battute, ordine) prima delle ore di render: un errore visto qui
    costa un fotogramma, visto a fine render costa le clip.
    """
    shots = [sh for sh in prod.get("shots") or [] if sh.get("status") != "skipped"
             and sh.get("keyframe") and Path(sh["keyframe"]).is_file()]
    if not shots:
        raise RuntimeError("servono i fotogrammi chiave (storyboard illustrato)")
    lw, lh = ltx_dims(prod.get("settings") or {})
    height = int(round(width * lh / lw / 2)) * 2
    import tempfile
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{out_path.stem}_", dir=out_path.parent))
    ff = ffmpeg_bin()
    lines, timeline, t = [], [], 0.0
    try:
        for i, sh in enumerate(shots):
            d = sh.get("dialogue") or {}
            line = Path(d["audio"]) if d.get("audio") and Path(d["audio"]).is_file() else None
            dur = max(float(sh.get("duration_s") or 4.0), (float(d.get("seconds") or 0) + 0.6) if line else 0.0)
            frames = max(1, int(round(dur * fps)))
            # Leggero avvicinamento: un'immagine ferma per cinque secondi sembra un errore.
            vf = (f"scale={width * 2}:-2,zoompan=z='min(zoom+0.0006,1.06)':x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},format=yuv420p")
            seg = work / f"{i:05d}.mkv"
            cmd = [ff, "-v", "error", "-y", "-i", str(sh["keyframe"])]
            if line:
                cmd += ["-i", str(line), "-filter_complex",
                        f"[0:v]{vf}[v];[1:a]aresample=48000,apad,atrim=end={frames / fps:.4f}[a]",
                        "-map", "[v]", "-map", "[a]"]
            else:
                cmd += ["-f", "lavfi", "-t", f"{frames / fps:.4f}", "-i", "anullsrc=r=48000:cl=stereo",
                        "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a"]
            cmd += ["-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(seg)]
            _run(cmd)
            lines.append(f"file '{seg.resolve().as_posix()}'")
            timeline.append((t, frames / fps, sh))
            t += frames / fps
        (work / "concat.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        partial = work / "animatic.mp4"
        _run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"),
              "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(partial)])
        os.replace(partial, out_path)
        write_subtitles(timeline, out_path.with_suffix(".srt"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out_path


def _video_codec_args(codec: str, quality: int) -> list:
    if "nvenc" in codec:
        return ["-c:v", codec, "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", codec, "-preset", "medium", "-crf", str(quality), "-pix_fmt", "yuv420p"]


# ---------------------------------------------------------------------------
# Esecuzione
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fotogrammi chiave
# ---------------------------------------------------------------------------

def keyframe_targets(prod: dict, shot_ids: list | None = None, missing_only: bool = False) -> list[int]:
    """Inquadrature che partono da un fotogramma chiave: le `continue` partono dal clip precedente."""
    out = []
    for i, s in enumerate(prod["shots"]):
        if continues(prod, i):
            continue
        if s.get("origin") in ("edit", "import", "title", "scene"):
            continue
        if shot_ids and s["id"] not in shot_ids:
            continue
        if missing_only and s.get("keyframe") and Path(s["keyframe"]).is_file():
            continue
        out.append(i)
    return out


KEYFRAME_ATTEMPTS = 3


async def _check_keyframe(prod: dict, shot: dict, image: Path) -> dict:
    """Giudizio del fotogramma col giudice visivo, se c'e'; senza giudice il fotogramma passa."""
    from core.modules.sigma_creative_lab.video import clip_judge
    s = prod.get("settings") or {}
    if not s.get("judge", True) or not clip_judge.installed():
        return {"ok": True, "score": None}
    try:
        verdict = await asyncio.to_thread(clip_judge.judge.judge_image, image, shot.get("prompt", ""),
                                          resolve_judge_device(s))
    except Exception as e:
        log.warning(f"controllo del fotogramma non disponibile: {e}")
        return {"ok": True, "score": None}
    try:
        wrong = await asyncio.to_thread(_cast_errors, prod, shot, image, resolve_judge_device(s))
    except Exception as e:
        log.warning(f"conteggio dei personaggi non disponibile: {e}")
        wrong = []
    if wrong:
        verdict = {**verdict, "ok": False, "issues": list(verdict.get("issues") or []) + wrong,
                   "score": round(min(verdict.get("score") or 1.0, 0.5), 2)}
        present = [c["name"] for c in _cast(prod, shot)[1]]
        verdict["fix"] = (f"Exactly {len(present)} character{'s' if len(present) != 1 else ''}: "
                          + ", ".join(f"one {n}" for n in present) + "; nobody appears twice.")
    return verdict


def character_kind(ch: dict) -> str:
    """Il tipo di figura del personaggio, per contarlo: la prima frase della sua descrizione."""
    first = re.split(r"[,.;]", str(ch.get("kind") or ch.get("description") or ""), maxsplit=1)[0]
    words = re.sub(r"^(?:a|an|the)\s+", "", first.strip(), flags=re.I).split()
    return " ".join(words[:6]) or str(ch.get("name") or "")


def _cast(prod: dict, shot: dict) -> tuple[list, list]:
    from core.modules.sigma_creative_lab.video.genres import shot_characters
    chars = [c for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name") and c.get("description")]
    return chars, [c for c in shot_characters(prod, shot) if c.get("description")]


def _cast_errors(prod: dict, shot: dict, image: Path, device: str) -> list[str]:
    """Personaggi sdoppiati, mancanti o di troppo, contati per tipo di figura."""
    from core.modules.sigma_creative_lab.video import clip_judge
    chars, present = _cast(prod, shot)
    if not chars:
        return []
    kinds = list(dict.fromkeys(character_kind(c) for c in chars))
    counts = clip_judge.judge.count_kinds(image, kinds, device)
    if counts is None:
        return []
    want = {k: sum(1 for c in present if character_kind(c) == k) for k in kinds}
    issues = []
    for kind, n in zip(kinds, counts):
        if n != want[kind]:
            names = [c["name"] for c in chars if character_kind(c) == kind]
            issues.append(f"{' / '.join(names)}: {n} nell'immagine invece di {want[kind]}")
    return issues


async def generate_keyframes(store: ProductionStore, pid: str, shot_ids: list | None = None,
                             missing_only: bool = False, gpu: int = 0, note: Callable[[str], None] | None = None,
                             cancel: "threading.Event | None" = None) -> int:
    """Disegna il primo fotogramma delle inquadrature col modello d'immagine del genere.

    Tutti insieme e non clip per clip: alternare il modello d'immagine e H3
    sulla stessa GPU li ricaricherebbe entrambi a ogni inquadratura.
    """
    from core.modules.sigma_creative_lab.video import genres, image_gen
    prod = store.get(pid)
    targets = keyframe_targets(prod, shot_ids, missing_only)
    s = prod["settings"]
    # Il fotogramma va generato nella forma del video: il modello d'immagine lavora
    # a blocchi di 64 px, si genera grande e H3 lo riduce alla sua risoluzione.
    w = 1344
    h = max(512, round(w * int(s.get("height", 480)) / int(s.get("width", 864)) / 64) * 64)
    done = 0
    for k, i in enumerate(targets, 1):
        if cancel is not None and cancel.is_set():
            raise PlanningCancelled(f"fermato dopo {done} fotogrammi su {len(targets)}")
        shot = prod["shots"][i]
        if note:
            note(f"Fotogramma chiave {k}/{len(targets)}")
        seed = int(shot.get("keyframe_seed") or 0) + (7919 if shot.get("keyframe") and not missing_only else 0) \
            or int(s.get("seed", 1000)) + i * 7919
        best, attempt_shot = None, dict(shot)
        for attempt in range(KEYFRAME_ATTEMPTS):
            out = store.path(pid) / "keyframes" / f"{i:04d}_{shot['id']}_{seed}.png"
            shot_model, prompt, refs = genres.keyframe_plan(prod, attempt_shot)
            r = await image_gen.generate(shot_model, prompt, out, width=w, height=h, seed=seed, gpu=gpu, refs=refs)
            check = await _check_keyframe(prod, attempt_shot, Path(r["path"]))
            r["check"] = check
            if best is None or (check.get("score") or 0) > (best["check"].get("score") or 0):
                best = r
            if check.get("ok", True):
                break
            log.warning(f"fotogramma di {shot['id']} da rifare: {check.get('issues')}")
            if note:
                note(f"Fotogramma chiave {k}/{len(targets)}: ridisegno ({', '.join(check.get('issues') or [])})")
            if check.get("fix"):
                attempt_shot["keyframe_fixes"] = (attempt_shot.get("keyframe_fixes") or [])[-1:] + [check["fix"]]
            seed += 7919
        r = best
        fresh = store.get(pid)
        target = next((x for x in fresh["shots"] if x["id"] == shot["id"]), None)
        if target is not None:
            target.update(keyframe=r["path"], keyframe_seed=r["seed"], keyframe_check=r.get("check"))
            # Un fotogramma nuovo rende vecchio il clip che partiva dal precedente.
            if target.get("status") == "done":
                target.update(status="pending", attempts=0)
            store.save(fresh)
        prod = fresh
        done += 1
    return done


# ---------------------------------------------------------------------------
# Giudice visivo
# ---------------------------------------------------------------------------

def resolve_judge_device(settings: dict) -> str:
    """Dove gira il giudice: un valore esplicito vince, altrimenti la GPU piu' piccola se ce ne sono due."""
    wanted = str(settings.get("judge_device") or "auto")
    if wanted != "auto":
        return wanted
    try:
        from core.modules.sigma_creative_lab.native.runtime import gpu_inventory
        gpus = gpu_inventory()
    except Exception:
        gpus = []
    if len(gpus) >= 2:
        smallest = min(gpus, key=lambda g: (g["vram_gb"], -g["index"]))
        if smallest["vram_gb"] >= 7.0:                 # l'8B col proiettore visivo occupa ~6,5 GB
            return f"gpu:{smallest['index']}"
    return "cpu"


async def judge_clip(prod: dict, shot: dict, clip: Path, intent: str, src_in: float = 0.0,
                     src_out: float | None = None) -> dict | None:
    """Giudizio del modello di visione, registrato nella storia dell'inquadratura.

    None quando il giudice e' spento, non installato o in errore: la produzione
    prosegue col solo controllo tecnico invece di fermarsi.
    """
    from core.modules.sigma_creative_lab.video import clip_judge
    s = prod.get("settings") or {}
    if not s.get("judge", True) or not intent.strip() or not clip_judge.installed():
        return None
    try:
        verdict = await asyncio.to_thread(clip_judge.judge.judge, clip, intent, resolve_judge_device(s),
                                          float(s.get("judge_threshold", clip_judge.PASS_SCORE)), src_in, src_out,
                                          int(s.get("judge_passes", 2)))
    except Exception as e:
        log.warning(f"giudice non disponibile per {shot.get('id')}: {e}")
        return None
    if verdict.get("score") is None:
        return None
    shot["judge"] = verdict
    shot.setdefault("judge_history", []).append({"clip_path": str(clip), "seed": shot.get("seed"), "take": take_key(shot),
                                                 **{k: verdict[k] for k in ("score", "seen", "issues", "prompt_fix")}})
    return verdict


def add_prompt_fix(shot: dict, verdict: dict, limit: int = 2) -> None:
    fix = verdict.get("prompt_fix", "").strip()
    fixes = shot.setdefault("prompt_fixes", [])
    if fix and fix not in fixes:
        fixes.append(fix)
        # Solo le ultime: troppe correzioni annacquano la descrizione originale.
        del fixes[:-limit]


def _judge_retries(settings: dict, shot: dict, verdict: dict) -> bool:
    """Il giudice rifa' la clip da solo? Solo per quello che l'utente non accetterebbe comunque."""
    mode = settings.get("judge_mode", "severe")
    if mode == "advise":
        return False
    if mode == "strict":
        return shot["attempts"] < int(settings.get("max_attempts", 3))
    return bool(verdict.get("severe")) and shot["attempts"] < 2


def take_key(shot: dict) -> str:
    """Cosa definisce una ripresa: prompt, correzioni, fotogramma di partenza e battuta."""
    d = shot.get("dialogue") or {}
    return _prompt_hash("|".join([shot.get("prompt", ""), json.dumps(shot.get("fixes") or [], sort_keys=True),
                                  str(shot.get("keyframe") or ""), str(d.get("source") or d.get("text") or "")]))


def best_judged(shot: dict) -> dict | None:
    # Solo i tentativi della ripresa attuale: "Il seme di Lia" ha montato una clip di Pepe fatta
    # prima del cambio di voce, perche' il giudice l'aveva preferita alle nuove.
    key = take_key(shot)
    history = [h for h in shot.get("judge_history") or [] if h.get("score") is not None and h.get("take") == key]
    return max(history, key=lambda h: h["score"]) if history else None


class ProductionRunner:
    """Rende le inquadrature mancanti di una produzione e la monta."""

    def __init__(self, store: ProductionStore, pid: str, engine: ClipEngine | None = None,
                 config: dict | None = None, on_event: Callable[[dict], None] | None = None):
        self.store = store
        self.pid = pid
        self.config = config or {}
        self._engine = engine
        self.on_event = on_event
        self.cancelled = threading.Event()
        self.current_shot = ""
        self.message = ""
        # Giudizi in corso: girano accanto ai render, la corsia non li aspetta.
        self._reviews: set[asyncio.Task] = set()
        self._wake: asyncio.Event | None = None

    def _emit(self, **event):
        self.message = event.get("message", self.message)
        if self.on_event:
            try:
                self.on_event({"production": self.pid, **event})
            except Exception as e:
                log.debug(f"listener evento fallito: {e}")

    def cancel(self):
        self.cancelled.set()

    def build_request(self, prod: dict, index: int) -> dict:
        s = prod["settings"]
        shot = prod["shots"][index]
        prev = prod["shots"][index - 1] if index > 0 else None
        chain = 0
        for j in range(index, 0, -1):
            if prod["shots"][j].get("transition") != "continue":
                break
            chain += 1
        # Una catena troppo lunga accumula deriva: oltre max_chain la ripresa si
        # spezza con un taglio, che il pubblico legge come un normale stacco.
        can_continue = (continues(prod, index) and prev is not None
                        and prev.get("status") == "done" and prev.get("last_frame")
                        and Path(prev["last_frame"]).is_file() and chain <= int(s.get("max_chain", 4)))
        from core.modules.sigma_creative_lab.video.genres import shot_characters
        ref_images = [] if can_continue or is_ltx(s) else [
            c["ref_image"] for c in shot_characters(prod, shot)
            if c.get("ref_image") and Path(c["ref_image"]).is_file()
        ]
        keyframe = ""
        if uses_keyframes(s) and not can_continue and shot.get("keyframe") and Path(shot["keyframe"]).is_file():
            # Il primo fotogramma e' gia' disegnato nello stile giusto: H3 lo anima (FL2V)
            # e non serve il riferimento del personaggio, che e' gia' nell'immagine.
            keyframe, ref_images = shot["keyframe"], []
        seed = shot.get("seed")
        if seed is None:
            seed = int(s.get("seed", 1000)) + index * 7919
        clips_dir = self.store.path(prod["id"]) / "clips"
        frames = clip_frames(s, float(shot.get("duration_s") or 5.0))
        speech = {}
        d = shot.get("dialogue") or {}
        if is_ltx(s) and d.get("audio") and Path(d["audio"]).is_file():
            from core.modules.sigma_creative_lab.generators.adapters.comfy_ltx import ltx_frame_count
            speech = {"audio": d["audio"]}
            frames = max(frames, ltx_frame_count(float(d.get("seconds") or 0) + 0.6, int(s.get("fps", FPS))))
        return {
            **speech,
            "prompt": compose_prompt(prod, {**shot, "transition": "continue" if (can_continue or keyframe) else "cut"},
                                     bool(ref_images)),
            "negative_prompt": (prod.get("bible") or {}).get("negative", ""),
            "frames": frames,
            "seed": int(seed),
            "init_image": prev["last_frame"] if can_continue else keyframe,
            "ref_images": ref_images,
            "loras": (prod.get("bible") or {}).get("loras") or [],
            # Ogni tentativo ha il suo file: se tutti vengono scartati si tiene il
            # migliore, che altrimenti sarebbe gia' stato sovrascritto.
            "output_path": str(clips_dir / (f"{index:04d}_{shot['id']}.mp4" if not shot.get("attempts")
                                            else f"{index:04d}_{shot['id']}_a{int(shot['attempts']) + 1}.mp4")),
            "continued": bool(can_continue),
        }

    # --- corsie ----------------------------------------------------------

    def lanes(self, prod: dict) -> list[dict]:
        """Motori su cui distribuire le inquadrature, dal piu' veloce.

        Una corsia per GPU. `backend` sceglie il motore di ogni corsia:
        `comfyui` e `sigma_native` lo usano su tutte le schede, `hybrid` mette
        ComfyUI sulla GPU principale e il worker nativo sulle altre. Le
        inquadrature `cut` sono indipendenti e si generano in parallelo.
        """
        if self._engine is not None:
            return [{"engine": self._engine, "label": self._engine.name, "devices": []}]
        s = prod["settings"]
        backends_cfg = self.config.get("backends") or {}
        specs = s.get("lanes")
        if not isinstance(specs, list) or not specs:
            specs = default_lane_specs(s.get("backend", "hybrid"))
        if s.get("max_lanes"):
            specs = specs[: int(s["max_lanes"])]
        if self._judge_enabled(prod) and len(specs) > 1:
            device = resolve_judge_device(s)
            if device.startswith("gpu:"):
                # La GPU del giudice non rende: H3 e il giudice insieme non entrano in 8 GB.
                judge_gpu = int(device.split(":", 1)[1])
                specs = [sp for sp in specs if sp.get("gpu") != judge_gpu] or specs
        lanes = []
        for spec in specs:
            gpu = spec.get("gpu")
            if spec["engine"] == "comfyui":
                engine = ComfyClipEngine({**backends_cfg.get("comfyui", {}), "gpu": gpu,
                                          "flags": s.get("comfy_flags")})
            else:
                engine = NativeClipEngine({**backends_cfg.get("sigma_native", {}), "port": spec.get("port")})
                engine.placement = spec.get("placement") or (f"gpu:{spec['ordinal']}" if "ordinal" in spec else "offload")
            label = f"{spec.get('label') or 'GPU'} · {'ComfyUI' if spec['engine'] == 'comfyui' else 'nativo'}"
            lanes.append({"engine": engine, "label": label, "devices": [gpu] if gpu is not None else [],
                          "assumed_ratio": spec.get("assumed_ratio", 2.0)})
        return lanes

    def _needs_previous(self, prod: dict, i: int) -> bool:
        """Vero se l'inquadratura deve aspettare l'ultimo fotogramma della precedente."""
        shot = prod["shots"][i]
        if i == 0 or shot.get("transition") != "continue":
            return False
        prev = prod["shots"][i - 1]
        if prev.get("status") in ("failed", "skipped"):
            return False                       # catena spezzata: si rende come taglio
        chain = 0
        for j in range(i, 0, -1):
            if prod["shots"][j].get("transition") != "continue":
                break
            chain += 1
        return chain <= int(prod["settings"].get("max_chain", 4))

    def _ready(self, prod: dict, i: int) -> bool:
        if prod["shots"][i].get("status") != "pending":
            return False
        if self._needs_previous(prod, i):
            return prod["shots"][i - 1].get("status") == "done"
        return True

    def _pick(self, prod: dict, lane: dict, fastest: dict) -> int | None:
        """Prossima inquadratura per una corsia.

        La corsia piu' veloce prende la prima pronta in ordine: e' quella che
        sblocca le catene. Le altre seguono due regole, senza le quali una GPU
        lenta allunga la produzione invece di accorciarla:

          - non aprono mai una catena di `continue`, perche' tutta la catena
            aspetterebbe il loro clip;
          - prendono lavoro solo se ne resta abbastanza: se la corsia veloce
            finirebbe da sola tutto il rimanente prima che la lenta chiuda un
            clip, quel clip lento sarebbe l'ultimo a uscire.
        """
        shots = prod["shots"]
        ready = [i for i in range(len(shots)) if self._ready(prod, i)]
        if not ready:
            return None
        if lane is fastest:
            return ready[0]
        pending = sum(1 for s in shots if s.get("status") == "pending")
        # Anche il clip che la corsia veloce sta gia' rendendo e' lavoro suo da
        # finire: contarlo a meta' evita che una GPU lenta resti ferma quando,
        # con due clip in coda e uno in corso, prenderne uno accorcerebbe il totale.
        busy = sum(0.5 for s in shots if s.get("status") == "rendering" and s.get("lane") == fastest.get("label"))
        ratio = self._speed_ratio(lane, fastest)
        if pending + busy <= ratio:
            return None
        front = ready[0]
        # Dalla coda: la corsia veloce avanza dalla testa e le due si incontrano
        # nel mezzo. Una testa di catena va bene solo se e' cosi' lontana dal
        # fronte che la corsia veloce non la raggiungera' prima che l'intera
        # catena sia finita.
        for i in reversed(ready):
            chain = 0
            while i + chain + 1 < len(shots) and shots[i + chain + 1].get("transition") == "continue":
                chain += 1
            if chain == 0 or (i - front) > ratio * (chain + 1):
                return i
        return None

    @staticmethod
    def _speed_ratio(lane: dict, fastest: dict) -> float:
        """Quante volte la corsia e' piu' lenta della piu' veloce (misurato sui clip fatti)."""
        slow, fast = lane.get("avg_s"), fastest.get("avg_s")
        if slow and fast:
            return max(1.0, slow / fast)
        # Prima di avere misure si assume una scheda di fascia inferiore: meglio
        # lasciarle qualche clip in meno che farle chiudere l'ultimo.
        return float(lane.get("assumed_ratio", 2.0))

    async def _render_one(self, prod: dict, i: int, lane: dict) -> None:
        shot = prod["shots"][i]
        engine = lane["engine"]
        request = self.build_request(prod, i)
        shot.update(status="rendering", error="", lane=lane["label"])
        shot["attempts"] = int(shot.get("attempts", 0)) + 1
        self.current_shot = shot["id"]
        self.store.save(prod)
        self._emit(type="shot_start", shot=shot["id"], index=i, total=len(prod["shots"]), lane=lane["label"],
                   message=f"Inquadratura {i + 1}/{len(prod['shots'])} su {lane['label']}")

        def on_progress(p):
            self._emit(type="shot_progress", shot=shot["id"], index=i, lane=lane["label"],
                       progress=p.get("progress"), step=p.get("step"), steps=p.get("steps"))
        t0 = time.monotonic()
        try:
            result = await engine.render(prod, shot, request, progress=on_progress)
            elapsed = time.monotonic() - t0
            # Media mobile per corsia: guida lo scheduler (vedi _pick) e la stima di fine.
            lane["avg_s"] = elapsed if not lane.get("avg_s") else 0.7 * lane["avg_s"] + 0.3 * elapsed
            shot.update(clip_path=result["clip_path"], last_frame=result.get("last_frame", ""),
                        frames=result.get("frames", request["frames"]), seed=result.get("seed", request["seed"]),
                        timings=result.get("timings", {}), continued=request["continued"],
                        engine=engine.name, rendered_at=_now())
            if await self._technical_check(prod, i):
                if self._judge_enabled(prod):
                    # Il giudice impiega 1-2 minuti di CPU: se la corsia lo aspettasse,
                    # la GPU resterebbe ferma per tutto quel tempo.
                    shot["status"] = "reviewing"
                    task = asyncio.create_task(self._review(prod, i, lane))
                    self._reviews.add(task)
                    task.add_done_callback(self._reviews.discard)
                else:
                    await self._finish(prod, i, lane)
        except EngineError as e:
            # Colpa del motore, non del clip: il tentativo non conta e la corsia
            # si prende una pausa crescente prima di riprovare.
            shot["attempts"] = max(0, int(shot.get("attempts", 1)) - 1)
            shot.update(status="pending", error=str(e))
            lane["failures"] = int(lane.get("failures", 0)) + 1
            log.error(f"corsia {lane['label']}: {e} (guasto {lane['failures']})")
            self._emit(type="lane_failure", lane=lane["label"], error=str(e), failures=lane["failures"])
        except Exception as e:
            if self.cancelled.is_set():
                shot["status"] = "pending"
            else:
                log.error(f"inquadratura {shot['id']} fallita su {lane['label']}: {e}")
                max_attempts = int(prod["settings"].get("max_attempts", 2))
                shot.update(status="failed" if shot["attempts"] >= max_attempts else "pending", error=str(e))
                self._emit(type="shot_failed", shot=shot["id"], index=i, lane=lane["label"], error=str(e))
        finally:
            self.store.save(prod)

    async def _technical_check(self, prod: dict, i: int) -> bool:
        """Controllo tecnico (nero, congelato, salti): pochi secondi. False = il clip va rifatto."""
        from core.modules.sigma_creative_lab.video import postprocess as pp
        s = prod["settings"]
        shot = prod["shots"][i]
        if not s.get("qa", True):
            return True
        issues = await asyncio.to_thread(pp.quality_check, Path(shot["clip_path"]), True)
        shot["qa_issues"] = issues
        if issues:
            if shot["attempts"] < int(s.get("max_attempts", 2)):
                # Un altro seed cambia il rumore iniziale: lo stesso prompt di
                # solito non ripete lo stesso difetto.
                shot.update(status="pending", seed=int(shot.get("seed") or 0) + 7919,
                            error="scartato dal controllo qualita': " + "; ".join(issues))
                self._emit(type="shot_retry", shot=shot["id"], index=i, issues=issues)
                return False
            log.warning(f"inquadratura {shot['id']} tenuta nonostante: {issues}")
        return True

    @staticmethod
    def _judge_enabled(prod: dict) -> bool:
        from core.modules.sigma_creative_lab.video import clip_judge
        return bool((prod.get("settings") or {}).get("judge", True)) and clip_judge.installed()

    async def _review(self, prod: dict, i: int, lane: dict) -> None:
        """Giudizio visivo in parallelo ai render; poi la chiusura dell'inquadratura."""
        s = prod["settings"]
        shot = prod["shots"][i]
        try:
            clip = Path(shot["clip_path"])
            self._emit(type="shot_review", shot=shot["id"], index=i, message=f"Controllo del movimento {i + 1}")
            verdict = await judge_clip(prod, shot, clip, shot.get("prompt", ""))
            if self.cancelled.is_set():
                shot["status"] = "pending"
                return
            if verdict is not None and not verdict["ok"]:
                if _judge_retries(s, shot, verdict):
                    add_prompt_fix(shot, verdict)
                    shot.update(status="pending", seed=int(shot.get("seed") or 0) + 7919,
                                error="scartato dal giudice: " + "; ".join(verdict["issues"] or [verdict["seen"]]))
                    self._emit(type="shot_retry", shot=shot["id"], index=i, issues=verdict["issues"],
                               score=verdict["score"])
                    return
                best = best_judged(shot)
                if best and best["clip_path"] != str(clip) and Path(best["clip_path"]).is_file():
                    log.warning(f"inquadratura {shot['id']}: nessun tentativo promosso, tengo il migliore "
                                f"({best['score']})")
                    shot.update(clip_path=best["clip_path"], seed=best.get("seed", shot.get("seed")))
            await self._finish(prod, i, lane)
        except Exception as e:
            log.error(f"chiusura dell'inquadratura {shot['id']} fallita: {e}")
            shot.update(status="pending", error=f"controllo: {e}")
        finally:
            self.store.save(prod)
            if self._wake:
                self._wake.set()          # le corsie in attesa rivalutano cosa e' pronto

    async def _finish(self, prod: dict, i: int, lane: dict) -> None:
        """Correzione colore lungo le catene, ultimo fotogramma, stato done."""
        from core.modules.sigma_creative_lab.video import postprocess as pp
        s = prod["settings"]
        shot = prod["shots"][i]
        clip = Path(shot["clip_path"])
        if shot.get("continued") and s.get("color_match", True):
            head = i
            while head > 0 and prod["shots"][head].get("transition") == "continue":
                head -= 1
            head_clip = Path(prod["shots"][head].get("clip_path") or "")
            if head != i and head_clip.is_file():
                anchor = head_clip.with_suffix(".anchor.png")
                try:
                    if not anchor.is_file():
                        await asyncio.to_thread(_run, [ffmpeg_bin(), "-v", "error", "-y", "-i", str(head_clip),
                                                       "-frames:v", "1", str(anchor)])
                    tmp = clip.with_suffix(".cm.mp4")
                    info = await asyncio.to_thread(pp.color_match, clip, anchor, tmp,
                                                   float(s.get("color_strength", 0.7)))
                    if info.get("applied"):
                        os.replace(tmp, clip)
                    shot["color_match"] = info
                except Exception as e:
                    log.warning(f"correzione colore di {shot['id']} non applicata: {e}")
        # L'ultimo fotogramma si rilegge dal clip definitivo: e' quello da cui parte il successivo.
        last = await asyncio.to_thread(extract_last_frame, clip)
        if last:
            shot["last_frame"] = str(last)
        shot["status"] = "done"
        self._emit(type="shot_done", shot=shot["id"], index=i, lane=lane["label"], timings=shot.get("timings", {}))

    async def _lane_loop(self, prod: dict, lane: dict, lanes: list, wake: asyncio.Event) -> None:
        while not self.cancelled.is_set():
            # La "piu' veloce" e' la prima corsia ancora in servizio: se quella
            # principale si ritira, un'altra deve prendersi le catene e l'ultimo clip.
            fastest = next((l for l in lanes if not l.get("retired")), lane)
            i = self._pick(prod, lane, fastest)
            if i is None:
                # "reviewing" tiene viva la corsia: il giudice puo' rimandare il clip in coda.
                if not any(s.get("status") in ("pending", "rendering", "reviewing") for s in prod["shots"]):
                    return                     # non resta niente da fare
                wake.clear()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                continue
            # Prenotazione prima di qualunque await: un'altra corsia non la prende.
            prod["shots"][i]["status"] = "rendering"
            failures_before = int(lane.get("failures", 0))
            await self._render_one(prod, i, lane)
            wake.set()
            if int(lane.get("failures", 0)) > failures_before:
                if lane["failures"] >= MAX_LANE_FAILURES:
                    log.error(f"corsia {lane['label']} ritirata dopo {lane['failures']} guasti")
                    lane["retired"] = True
                    self._emit(type="lane_retired", lane=lane["label"])
                    return
                await asyncio.sleep(30 * lane["failures"])
            else:
                lane["failures"] = 0

    async def run(self, assemble_at_end: bool = True) -> dict:
        prod = self.store.get(self.pid)
        if prod is None:
            raise ValueError(f"produzione inesistente: {self.pid}")
        prod["status"] = "rendering"
        prod["error"] = ""
        # Un'inquadratura rimasta 'rendering' o 'reviewing' viene da un crash: si riprende da li'.
        for s in prod["shots"]:
            if s.get("status") in ("rendering", "reviewing"):
                s["status"] = "pending"
            if s.get("status") == "done" and not (s.get("clip_path") and Path(s["clip_path"]).is_file()):
                s["status"] = "pending"
        # Se non ci sono inquadrature pendenti ma ce ne sono di fallite (es. modello errato corretto dall'utente),
        # si ripristinano a pending consentendo il nuovo tentativo.
        has_pending = any(s.get("status") in ("pending", "rendering", "reviewing") for s in prod["shots"])
        if not has_pending and any(s.get("status") == "failed" for s in prod["shots"]):
            for s in prod["shots"]:
                if s.get("status") == "failed":
                    s["status"] = "pending"
                    s["attempts"] = 0
                    s["error"] = ""
        self.store.save(prod)
        if is_ltx(prod["settings"]) and self._engine is None:
            # Prima del lease: dopo, la VRAM dell'LLM viene liberata per il render e chiamarlo la ricaricherebbe.
            try:
                changed = await asyncio.to_thread(rewrite_for_ltx, prod, None,
                                                  lambda m: self._emit(type="prompts", message=m))
                if changed:
                    self.store.save(prod)
            except Exception as e:
                log.warning(f"prompt per LTX non riscritti: {e}")
            try:
                if await asyncio.to_thread(prepare_dialogue, self.store, prod,
                                           lambda m: self._emit(type="dialogue", message=m)):
                    self.store.save(prod)
            except Exception as e:
                # Senza voce la battuta si perde ma l'inquadratura si rende lo stesso.
                log.error(f"battute non sintetizzate: {e}")
        lanes = self.lanes(prod)
        self._lanes = lanes
        started = time.monotonic()

        from core.engine.gpu_lease import leases
        devices = {d for lane in lanes for d in lane["devices"]}
        judge_device = resolve_judge_device(prod["settings"]) if self._judge_enabled(prod) else "cpu"
        if devices and judge_device.startswith("gpu:"):
            # Riservata anche la GPU del giudice: l'LLM della chat non deve caricarsi li'.
            devices.add(int(judge_device.split(":", 1)[1]))
        devices = sorted(devices)
        lease_id = None
        if devices:
            try:
                lease_id = leases.acquire(f"produzione:{self.pid}", devices,
                                          f"render di {len(prod['shots'])} inquadrature")
            except RuntimeError as e:
                prod["status"], prod["error"] = "failed", str(e)
                self.store.save(prod)
                raise
            from core.modules.sigma_creative_lab.native.runtime import release_llm_vram
            release_llm_vram()
        prod["lanes"] = [l["label"] for l in lanes]
        if uses_keyframes(prod["settings"]) and keyframe_targets(prod, missing_only=True) and self._engine is None:
            self._emit(type="keyframes", message="Fotogrammi chiave mancanti")
            first_gpu = next((l["devices"][0] for l in lanes if l["devices"]), 0)
            try:
                await generate_keyframes(self.store, self.pid, missing_only=True, gpu=first_gpu,
                                         note=lambda m: self._emit(type="keyframes", message=m))
            except Exception as e:
                # Senza fotogrammi si genera comunque: lo stile sara' quello di H3.
                log.error(f"fotogrammi chiave non generati: {e}")
            prod = self.store.get(self.pid)
            prod["lanes"] = [l["label"] for l in lanes]
        self._emit(type="production_start", lanes=prod["lanes"], message=f"Render su {len(lanes)} corsie")

        async def keep_lease():
            while lease_id and not self.cancelled.is_set():
                await asyncio.sleep(60)
                leases.renew(lease_id)

        renewer = asyncio.create_task(keep_lease())
        wake = asyncio.Event()
        self._wake = wake
        try:
            await asyncio.gather(*(self._lane_loop(prod, lane, lanes, wake) for lane in lanes))
            if self._reviews:
                # Annullata a meta': i giudizi in corso finiscono prima di chiudere i motori.
                await asyncio.gather(*list(self._reviews), return_exceptions=True)
            all_done = all(s.get("status") in ("done", "skipped") for s in prod["shots"])
            if all_done and not self.cancelled.is_set() and (prod.get("soundtrack") or {}).get("enabled"):
                await self._soundtrack(prod)
            if all_done and not self.cancelled.is_set() and wants_ambience(prod):
                await self._ambience(prod)
        finally:
            renewer.cancel()
            for lane in lanes:
                await lane["engine"].release()
            if lease_id:
                leases.release(lease_id)

        prod["stats"] = {**summary(prod), "render_wall_s": round(time.monotonic() - started, 1),
                         "lanes": prod["lanes"]}
        if self.cancelled.is_set():
            prod["status"] = "cancelled"
        elif any(s.get("status") in ("pending", "failed") for s in prod["shots"]):
            # Clip falliti ancora riprovabili: la produzione resta riprendibile.
            prod["status"] = "partial"
        elif assemble_at_end:
            prod["status"] = "assembling"
            self.store.save(prod)
            try:
                prod["output_path"] = str(self.assemble(prod))
                prod["status"] = "done"
            except Exception as e:
                log.error(f"montaggio fallito: {e}")
                prod["status"] = "failed"
                prod["error"] = f"montaggio: {e}"
        else:
            prod["status"] = "rendered"
        prod["stats"]["status"] = prod["status"]    # le statistiche erano state prese prima dell'esito
        self.store.save(prod)
        self._emit(type="production_end", status=prod["status"], output=prod.get("output_path", ""),
                   message=f"Produzione {prod['status']}")
        return prod

    async def _soundtrack(self, prod: dict) -> None:
        """Compone la musica sulla GPU principale, prima di liberarla."""
        from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
        from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
        from core.modules.sigma_creative_lab.video.soundtrack import generate_soundtrack
        work = self.store.path(prod["id"]) / "music"
        try:
            gpu = next((d for lane in getattr(self, "_lanes", []) for d in lane["devices"]), 0)
            url = await asyncio.to_thread(instances.ensure, int(gpu))
            path = await generate_soundtrack(prod, work, ComfyUIBackend(base_url=url, config={"timeout": 1800}),
                                             progress=lambda m: self._emit(type="soundtrack", message=m))
            prod["soundtrack_path"] = str(path)
        except Exception as e:
            # La musica e' un livello in piu': senza, il video resta montabile.
            log.error(f"colonna sonora non generata: {e}")
            prod["soundtrack_error"] = str(e)
        self.store.save(prod)

    async def _ambience(self, prod: dict) -> None:
        """Ambienti sonori dei luoghi con battute (vedi soundtrack.generate_ambience)."""
        from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
        from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
        from core.modules.sigma_creative_lab.video.soundtrack import generate_ambience
        try:
            gpu = next((d for lane in getattr(self, "_lanes", []) for d in lane["devices"]), 0)
            url = await asyncio.to_thread(instances.ensure, int(gpu))
            prod["ambience"] = await generate_ambience(
                prod, self.store.path(prod["id"]) / "ambience", ComfyUIBackend(base_url=url, config={"timeout": 1800}),
                progress=lambda m: self._emit(type="soundtrack", message=m))
        except Exception as e:
            # Un livello in piu': senza, le battute restano come prima.
            log.error(f"ambienti sonori non generati: {e}")
        self.store.save(prod)

    def _upscale_all(self, prod: dict) -> None:
        """SeedVR2 su tutte le clip prima del montaggio, in parallelo sulle schede (circa 1 min per secondo)."""
        from concurrent.futures import ThreadPoolExecutor
        from core.modules.sigma_creative_lab.video import postprocess as pp
        s = prod["settings"]
        height = int(s.get("output_height") or 0)
        if s.get("upscaler") != "seedvr2" or not height or not pp.seedvr2_ready():
            return
        clips = [Path(sh["clip_path"]) for sh in prod["shots"] if sh.get("status") == "done" and sh.get("clip_path")]
        todo = [c for c in clips if not (c.with_suffix(f".svr{height}.mp4").is_file()
                                         and c.with_suffix(f".svr{height}.mp4").stat().st_mtime >= c.stat().st_mtime)]
        if not todo:
            return
        gpus = sorted({int(l.get("gpu", 0)) for l in default_lane_specs("comfyui") if l.get("gpu") is not None}) or [0]
        done = {"n": 0}

        def work(item):
            k, clip = item
            try:
                pp.upscale_seedvr2(clip, height, gpus[k % len(gpus)])
            except Exception as e:
                log.warning(f"SeedVR2 su {clip.name} non riuscito, il montaggio usera' Lanczos: {e}")
            done["n"] += 1
            self._emit(type="assemble", message=f"Dettaglio 1080p (SeedVR2) {done['n']}/{len(todo)}")
        with ThreadPoolExecutor(max_workers=len(gpus)) as pool:
            list(pool.map(work, enumerate(todo)))

    def assemble(self, prod: dict) -> Path:
        s = prod["settings"]
        self._upscale_all(prod)
        out = paths.creative_output_dir("video") / f"{_slug(prod['title'])}_{prod['id'][-6:]}.mp4"
        music = Path(prod.get("soundtrack_path") or "")
        if (prod.get("soundtrack") or {}).get("enabled") and music.is_file():
            from core.modules.sigma_creative_lab.video.soundtrack import DEFAULT_SOUNDTRACK, mix_soundtrack
            cfg = {**DEFAULT_SOUNDTRACK, **prod["soundtrack"]}
            dry = out.with_name(out.stem + "_senza_musica.mp4")
            assemble(prod, dry, fps=int(s.get("fps", FPS)), codec=s.get("final_codec", "libx264"),
                     quality=int(s.get("final_quality", 18)), output_height=int(s.get("output_height") or 0), settings=s,
                     progress=lambda m: self._emit(type="assemble", message=m))
            self._emit(type="assemble", message="Mix della colonna sonora")
            mix_soundtrack(dry, music, out, float(cfg["music_db"]), float(cfg["clip_db"]), bool(cfg["duck"]))
            for ext in (".srt", ".vtt"):
                if dry.with_suffix(ext).is_file():
                    os.replace(dry.with_suffix(ext), out.with_suffix(ext))
            return out
        return assemble(prod, out, fps=int(s.get("fps", FPS)), codec=s.get("final_codec", "libx264"),
                        quality=int(s.get("final_quality", 18)), output_height=int(s.get("output_height") or 0), settings=s,
                        progress=lambda m: self._emit(type="assemble", message=m))


# ---------------------------------------------------------------------------
# Registro dei render in corso (uno per volta: la GPU e' una sola risorsa)
# ---------------------------------------------------------------------------

class ProductionManager:
    def __init__(self, store: ProductionStore | None = None):
        self.store = store or ProductionStore()
        self._runner: ProductionRunner | None = None
        self._thread: threading.Thread | None = None
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def _record(self, event: dict):
        with self._lock:
            self._events.append({**event, "t": _now()})
            del self._events[:-200]

    def events(self, since: float = 0.0) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["t"] > since]

    def active(self) -> dict | None:
        r = self._runner
        if r and self._thread and self._thread.is_alive():
            return {"production": r.pid, "shot": r.current_shot, "message": r.message}
        return None

    def start(self, pid: str, config: dict | None = None, engine: ClipEngine | None = None) -> dict:
        if self.active():
            raise RuntimeError(f"e' gia' in corso la produzione {self._runner.pid}: la GPU e' una sola")
        if self.store.get(pid) is None:
            raise ValueError(f"produzione inesistente: {pid}")
        runner = ProductionRunner(self.store, pid, engine=engine, config=config, on_event=self._record)

        def _target():
            try:
                asyncio.run(runner.run())
            except Exception as e:
                log.error(f"produzione {pid} interrotta: {e}")
                prod = self.store.get(pid)
                if prod:
                    prod["status"], prod["error"] = "failed", str(e)
                    self.store.save(prod)
                self._record({"production": pid, "type": "production_end", "status": "failed", "message": str(e)})

        self._runner = runner
        self._thread = threading.Thread(target=_target, name=f"production-{pid}", daemon=True)
        self._thread.start()
        return {"started": pid}

    def cancel(self, pid: str) -> bool:
        r = self._runner
        if not r or r.pid != pid or not self.active():
            return False
        r.cancel()

        async def _stop_all():
            for lane in getattr(r, "_lanes", []):
                try:
                    await lane["engine"].cancel_running()
                except Exception as e:
                    log.warning(f"annullamento su {lane['label']} non riuscito: {e}")
        asyncio.run(_stop_all())
        return True


manager = ProductionManager()
