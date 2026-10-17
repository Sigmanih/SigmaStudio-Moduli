"""Libreria dei personaggi: schede riutilizzabili in qualsiasi storia.

Ogni personaggio vive in data/characters/<id>/ con character.json, l'immagine di
riferimento scelta fra alcune proposte, il model sheet (profilo, retro, primo
piano, espressioni) e il collegamento a una voce della libreria di Voice Studio.
Aggiunto a una produzione, la sua scheda viene copiata nella bibbia della storia:
le modifiche successive alla libreria non toccano i video gia' fatti.

I modelli d'immagine vedono solo il testo, non il riferimento: a parita' di
descrizione e seed le viste del model sheet a volte cambiano capelli o vestiti.
Il giudice visivo confronta ogni vista col riferimento e la rifa se ha cambiato
persona; per l'identita' esatta del volto servira' la LoRA del personaggio.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from core import paths
from core.logger import get_logger

log = get_logger("creative_characters")

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
MAX_IMAGE_BYTES = 20 * 1024 * 1024
VIEW_ATTEMPTS = 2

#: Viste del model sheet: (descrizione per il modello d'immagine, larghezza, altezza).
VIEWS = {
    # Inquadratura in testa e parole nette: con "side view" in coda il modello disegnava
    # comunque un tre quarti rivolto verso la camera.
    "profile": ("strict side view, full body profile facing left, only one side of the face visible, standing",
                832, 1216),
    "back": ("rear view from behind, full body, character turned away from the camera, back of the head visible, "
             "face not visible, standing", 832, 1216),
    "closeup": ("close-up portrait, head and shoulders, looking at the viewer", 1024, 1024),
    "happy": ("close-up portrait, happy smiling expression", 1024, 1024),
    "sad": ("close-up portrait, sad expression", 1024, 1024),
    "angry": ("close-up portrait, angry expression", 1024, 1024),
    "surprised": ("close-up portrait, surprised expression, open mouth", 1024, 1024),
}
VIEW_LABELS = {"front": "Fronte", "profile": "Profilo", "back": "Retro", "closeup": "Primo piano",
               "happy": "Felice", "sad": "Triste", "angry": "Arrabbiato", "surprised": "Sorpreso"}


def characters_dir() -> Path:
    return paths.works_area("creative/personaggi", legacy="characters")


def _folder(char_id: str) -> Path:
    # Solo id generati da noi: niente percorsi che escono dalla libreria.
    if not re.fullmatch(r"[a-z0-9_]{3,64}", char_id or ""):
        raise ValueError(f"id personaggio non valido: {char_id!r}")
    return characters_dir() / char_id


def _slug(name: str) -> str:
    import unicodedata
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    return (re.sub(r"[^a-z0-9]+", "_", folded).strip("_") or "personaggio")[:32]


def _read(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / "character.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("id") == folder.name else None


def _write(char: dict) -> dict:
    char["updated"] = round(time.time(), 3)
    folder = _folder(char["id"])
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "character.json.tmp"
    tmp.write_text(json.dumps(char, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(folder / "character.json")
    return char


def list_characters() -> list[dict]:
    root = characters_dir()
    if not root.is_dir():
        return []
    out = [c for c in (_read(f) for f in root.iterdir() if f.is_dir()) if c]
    return sorted(out, key=lambda c: c.get("updated", 0), reverse=True)


def get(char_id: str) -> dict | None:
    try:
        folder = _folder(char_id)
    except ValueError:
        return None
    return _read(folder) if folder.is_dir() else None


def _require(char_id: str) -> dict:
    char = get(char_id)
    if char is None:
        raise ValueError(f"personaggio inesistente: {char_id}")
    return char


def file_path(char: dict, name: str) -> Path | None:
    """Percorso di un'immagine della scheda, solo se e' davvero dentro la sua cartella."""
    if not name:
        return None
    folder = _folder(char["id"]).resolve()
    path = (folder / name).resolve()
    return path if path.is_file() and folder in path.parents else None


def create(name: str, description: str = "", genre: str = "realistic", voice_id: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("serve un nome")
    char_id = f"{_slug(name)}_{uuid.uuid4().hex[:6]}"
    return _write({"id": char_id, "name": name, "description": description.strip(), "genre": genre or "realistic",
                   "voice_id": voice_id, "seed": None, "front": "", "sheet": {}, "candidates": [],
                   "created": round(time.time(), 3)})


def update(char_id: str, **fields) -> dict:
    char = _require(char_id)
    for key in ("name", "description", "genre", "voice_id", "notes"):
        if key in fields and fields[key] is not None:
            char[key] = str(fields[key]).strip()
    if not char["name"]:
        raise ValueError("serve un nome")
    return _write(char)


def delete(char_id: str) -> bool:
    folder = _folder(char_id)
    if not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


def _genre(char: dict) -> dict:
    from core.modules.sigma_creative_lab.video import genres
    return genres.GENRES.get(char.get("genre") or "", genres.GENRES["realistic"])


def view_prompt(char: dict, view: str, fix: str = "", with_reference: bool = False) -> str:
    """Prompt di una vista: stile del genere + aspetto + inquadratura, su fondo neutro."""
    g = _genre(char)
    desc = char["description"].strip().rstrip(".")
    shot = VIEWS[view][0]
    extra = f", {fix.strip().rstrip('.')}" if fix else ""
    if with_reference:
        # klein vede il riferimento: la descrizione serve solo a non perdere i dettagli piccoli.
        return (f"{shot.capitalize()} of the character in image 1 ({desc}): keep exactly the same face, hair, body, "
                f"clothes and art style as image 1. Plain neutral background, soft even light{extra}")
    if g["image_model"] == "animagine":
        # Tag e niente nomi propri, come per i fotogrammi chiave (vedi genres.keyframe_prompt).
        return f"{shot}, {desc}, solo, simple background, white background{extra}"
    return f"{shot.capitalize()}. {g['style']}. Character reference of {desc}, plain neutral background, soft even light{extra}"


def _gpu_busy() -> bool:
    from core.modules.sigma_creative_lab.video.production import manager
    return bool(manager.active())


async def candidates(char_id: str, count: int = 4, gpu: int = 0) -> dict:
    """Proposte dell'immagine di riferimento: l'utente sceglie quella giusta."""
    from core.modules.sigma_creative_lab.video import genres, image_gen
    char = _require(char_id)
    if not char["description"]:
        raise ValueError("descrivi l'aspetto del personaggio (in inglese rende meglio)")
    if _gpu_busy():
        raise RuntimeError("un render occupa la GPU: riprova a render finito")
    model = _genre(char)["image_model"]
    if not image_gen.installed(model):
        raise RuntimeError(f"{image_gen.MODELS[model]['label']} non installato (Video Studio → Motori)")
    prompt = genres.portrait_prompt({"bible": {"genre": char["genre"]}}, char["description"])
    base = int(time.time()) % 100000
    folder = _folder(char_id) / "candidates"
    out = []
    for k in range(max(1, min(6, int(count)))):
        seed = base + k * 7919
        r = await image_gen.generate(model, prompt, folder / f"cand_{seed}.png", width=832, height=1216, seed=seed, gpu=gpu)
        out.append({"file": f"candidates/{Path(r['path']).name}", "seed": seed})
    char = _require(char_id)
    char["candidates"] = out + [c for c in char.get("candidates") or [] if c["file"] not in {o["file"] for o in out}][:12]
    return _write(char)


def _crop_region(image: Path, region, out: Path) -> Path:
    """Ritaglio [x0, y0, x1, y1] in pixel o in frazioni 0-1; senza regione, l'immagine intera."""
    from PIL import Image
    with Image.open(image) as img:
        img = img.convert("RGB")
        if region:
            vals = [float(v) for v in region]
            if len(vals) != 4:
                raise ValueError("region deve essere [x0, y0, x1, y1]")
            if all(0.0 <= v <= 1.0 for v in vals):
                vals = [vals[0] * img.width, vals[1] * img.height, vals[2] * img.width, vals[3] * img.height]
            x0, y0, x1, y1 = (int(round(v)) for v in vals)
            img = img.crop((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
    return out


def _persone_nel_ritaglio(immagine: Path) -> int | None:
    """1 se nel ritaglio si vede il volto di una persona, 0 se no, None se non si puo' dire.

    Si chiede del volto e non delle persone: davanti al ritaglio col solo logo
    e una mano il modello contava comunque «una persona».
    """
    try:
        from core.harness import vista
        dati, _info = vista.prepara(immagine)
        risposta, _ = vista.occhio.guarda(
            dati, "Is the FACE of a person or character (drawn or real) visible in this image? A hand, an arm or a "
                  "logo alone is not a face. Answer only yes or no.")
    except Exception as exc:
        log.warning(f"controllo del ritaglio non riuscito: {exc}")
        return None
    testo = (risposta or "").strip().lower()
    if testo.startswith(("yes", "si", "sì")):
        return 1
    if testo.startswith("no"):
        return 0
    return None


def _vestiti_nel_ritaglio(immagine: Path) -> bool | None:
    """Se nel ritaglio si vedono i vestiti (busto) del personaggio, o None se non si puo' dire.

    Da un primo piano klein disegna i vestiti dalla sola descrizione: nel
    collaudo Mx0 Aika e' uscita con una maglietta a righe che nel fumetto non
    porta, perche' la vignetta scelta mostrava solo il viso.
    """
    try:
        from core.harness import vista
        dati, _info = vista.prepara(immagine)
        risposta, _ = vista.occhio.guarda(
            dati, "Are the clothes on the torso of the main character clearly visible in this image (not only the "
                  "face and hair)? Answer only yes or no.")
    except Exception as exc:
        log.warning(f"controllo dei vestiti non riuscito: {exc}")
        return None
    testo = (risposta or "").strip().lower()
    return True if testo.startswith(("yes", "si", "sì")) else False if testo.startswith("no") else None


async def candidates_from_image(char_id: str, image: str, region=None, count: int = 2, gpu: int = 0) -> dict:
    """Proposte ridisegnate da un'immagine esistente: copertina, tavola a colori, vignetta.

    Per un personaggio che esiste gia' (un fumetto da trasporre) l'aspetto non
    si inventa da una descrizione: lo si prende dall'opera. klein riceve il
    ritaglio come immagine 1 e lo ridisegna a figura intera su fondo neutro,
    nello stile del genere; la descrizione del personaggio fissa i colori che
    il ritaglio non mostra (una vignetta in bianco e nero).
    """
    from core.modules.sigma_creative_lab.video import image_gen
    char = _require(char_id)
    src = Path(str(image or ""))
    if not src.is_file() or src.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"immagine non trovata o non supportata: {image}")
    if _gpu_busy():
        raise RuntimeError("un render occupa la GPU: riprova a render finito")
    if not image_gen.installed("klein"):
        raise RuntimeError("serve FLUX.2 klein (Video Studio -> Motori) per ridisegnare da un'immagine")
    if not region:
        # Collaudo Mx0: data la copertina intera (due personaggi, titolo, codice a
        # barre) klein non sapeva chi ridisegnare e ha seguito la sola descrizione,
        # vestendo il protagonista con un abito che nel fumetto non esiste.
        from PIL import Image
        with Image.open(src) as img:
            w, h = img.size
        raise ValueError(
            f"serve 'region' sul personaggio: l'immagine e' {w}x{h} px e puo' contenerne altri. Guardala con "
            "view_image (o view_image con una region di prova) e passa [x0, y0, x1, y1] in frazioni 0-1 del "
            "riquadro che contiene SOLO questo personaggio")
    folder = _folder(char_id)
    source = _crop_region(src, region, folder / "sources" / f"source_{int(time.time())}.png")
    persone = _persone_nel_ritaglio(source)
    if persone == 0:
        # Collaudo Mx0: la region di Aika inquadrava il logo del titolo e una mano,
        # e klein ha inventato una ragazza dalla sola descrizione.
        raise ValueError(
            f"nel ritaglio {source} non c'e' nessuna persona: la region non inquadra il personaggio. "
            "Guarda l'immagine intera con view_image, trova dove sta il personaggio e riprova con un'altra region")
    vestiti = _vestiti_nel_ritaglio(source)
    desc = (char.get("description") or "").strip().rstrip(".")
    # L'immagine vince sulla descrizione: la descrizione la scrive l'agente e puo'
    # sbagliare i colori, l'immagine viene dall'opera.
    # Con i vestiti visibili la descrizione non entra: anche scritta come "note
    # secondarie" klein la seguiva al posto dell'immagine (Hiragi-sensei col
    # cappotto chiaro nella vignetta, ridisegnato con una toga scura a bordi d'oro).
    note = "" if vestiti else (f" Where image 1 is black and white or does not show something, use these notes: "
                               f"{desc}." if desc else "")
    prompt = (f"Character reference sheet of the character in image 1: full body, front view, standing straight, "
              f"arms relaxed, neutral expression, plain white background. Copy exactly from image 1 the face, "
              f"hairstyle, hair color, eye color, clothes and clothes colors; if image 1 is black and white, choose "
              f"natural colors that fit it.{note} {_genre(char)['style']}. No text, no letters.")
    base = int(time.time()) % 100000
    out = []
    for k in range(max(1, min(4, int(count)))):
        seed = base + k * 7919
        r = await image_gen.generate("klein", prompt, folder / "candidates" / f"cand_{seed}.png", width=832,
                                     height=1216, seed=seed, gpu=gpu, refs=[str(source)])
        out.append({"file": f"candidates/{Path(r['path']).name}", "seed": seed,
                    "source": str(source.relative_to(folder)).replace("\\", "/"),
                    "clothes_visible": vestiti})
    char = _require(char_id)
    char["candidates"] = out + [c for c in char.get("candidates") or [] if c["file"] not in {o["file"] for o in out}][:12]
    return _write(char)


def pick(char_id: str, file: str) -> dict:
    """La proposta scelta diventa il riferimento: le viste del model sheet ripartono da lei."""
    char = _require(char_id)
    src = file_path(char, file)
    if src is None:
        raise ValueError("immagine inesistente")
    shutil.copy2(src, _folder(char_id) / "front.png")
    seed = next((c["seed"] for c in char.get("candidates") or [] if c["file"] == file), None)
    char.update(front="front.png", seed=seed, sheet={})
    return _write(char)


def import_image(char_id: str, data: bytes, filename: str, describe: bool = True) -> dict:
    """Foto o disegno caricato dall'utente come riferimento; l'aspetto lo descrive il giudice visivo."""
    from PIL import Image
    char = _require(char_id)
    if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("formato non supportato: usa PNG, JPG o WEBP")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("immagine troppo grande (massimo 20 MB)")
    import io
    folder = _folder(char_id)
    folder.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(data)).convert("RGB").save(folder / "front.png")
    char.update(front="front.png", seed=None, sheet={})
    if describe and not char["description"]:
        from core.modules.sigma_creative_lab.video.clip_judge import judge
        from core.modules.sigma_creative_lab.video.production import resolve_judge_device
        try:
            char["description"] = judge.describe_character(folder / "front.png", resolve_judge_device({}))
        except Exception as e:
            log.warning(f"descrizione automatica di {char['name']} non riuscita: {e}")
    return _write(char)


async def sheet(char_id: str, views: list[str] | None = None, gpu: int = 0, check: bool = True) -> dict:
    """Model sheet: ogni vista e' confrontata col riferimento e rifatta se ha cambiato persona."""
    import asyncio
    from core.modules.sigma_creative_lab.video import image_gen
    from core.modules.sigma_creative_lab.video.clip_judge import installed as judge_installed, judge
    from core.modules.sigma_creative_lab.video.production import resolve_judge_device
    char = _require(char_id)
    front = file_path(char, char.get("front", ""))
    if front is None:
        raise ValueError("scegli prima l'immagine di riferimento")
    if not char["description"]:
        raise ValueError("manca la descrizione dell'aspetto")
    if _gpu_busy():
        raise RuntimeError("un render occupa la GPU: riprova a render finito")
    # Con klein le viste partono dall'immagine di riferimento, non dal solo testo: stessa persona.
    use_ref = image_gen.installed("klein")
    model = "klein" if use_ref else _genre(char)["image_model"]
    wanted = [v for v in (views or list(VIEWS)) if v in VIEWS]
    device = resolve_judge_device({})
    check = check and judge_installed()
    seed = int(char.get("seed") or time.time() % 100000)
    folder = _folder(char_id)
    for view in wanted:
        _shot, w, h = VIEWS[view]
        fix, best = "", None
        for attempt in range(VIEW_ATTEMPTS):
            target = folder / "sheet" / f"{view}_{seed + attempt}.png"
            r = await image_gen.generate(model, view_prompt(char, view, fix, use_ref), target, width=w, height=h,
                                         seed=seed + attempt, gpu=gpu, refs=[front] if use_ref else None)
            verdict = {"ok": True, "score": None, "differences": []}
            if check:
                verdict = await asyncio.to_thread(judge.same_character, front, Path(r["path"]),
                                                  char["description"], VIEWS[view][0], device)
            entry = {"file": f"sheet/{Path(r['path']).name}", "score": verdict.get("score"),
                     "differences": verdict.get("differences") or []}
            if best is None or (entry["score"] or 0) > (best["score"] or 0):
                best = entry
            if verdict.get("ok"):
                break
            fix = verdict.get("fix") or ""
            log.info(f"{char['name']}, vista {view}: rifatta ({'; '.join(entry['differences'])[:160]})")
        char = _require(char_id)
        char.setdefault("sheet", {})[view] = best
        _write(char)
    return _require(char_id)


def voice_sample(char: dict) -> Path | None:
    if not char.get("voice_id"):
        return None
    try:
        from core.modules.sigma_voice_studio import library
    except ImportError:
        return None                      # Voice Studio non installato: il personaggio resta senza voce
    v = library.get(char["voice_id"])
    return Path(v["sample"]) if v and Path(v["sample"]).is_file() else None


def to_production(char_id: str, pid: str) -> dict:
    """Copia il personaggio nella bibbia della produzione (riferimento, aspetto, voce)."""
    from core.modules.sigma_creative_lab.video.production import manager
    char = _require(char_id)
    front = file_path(char, char.get("front", ""))
    if front is None:
        raise ValueError("il personaggio non ha ancora un'immagine di riferimento")
    store = manager.store
    prod = store.get(pid)
    if prod is None:
        raise ValueError("produzione inesistente")
    refs = store.path(pid) / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    ref = refs / f"library_{char['id']}.png"
    shutil.copy2(front, ref)
    entry = {"name": char["name"], "description": char["description"], "ref_image": str(ref), "library_id": char["id"],
             "voice_id": char.get("voice_id", "")}
    sample = voice_sample(char)
    if sample:
        voice = refs / f"voice_{char['id']}{sample.suffix}"
        shutil.copy2(sample, voice)
        entry.update(voice_sample=str(voice), voice_engine="chatterbox")
    bible = prod.setdefault("bible", {})
    chars = [c for c in bible.get("characters") or [] if c.get("name") != char["name"]]
    bible["characters"] = chars + [entry]
    store.save(prod)
    return entry


def from_production(pid: str, name: str, character: dict | None = None) -> dict:
    """Salva nella libreria un personaggio nato dentro una storia, per riusarlo nelle prossime.

    `character` arriva dalla bozza dell'editor della produzione, che puo' non essere ancora salvata.
    """
    from core.modules.sigma_creative_lab.video.production import manager
    prod = manager.store.get(pid)
    if prod is None:
        raise ValueError("produzione inesistente")
    ch = character or next((c for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name") == name), None)
    if not ch or not str(ch.get("name", "")).strip():
        raise ValueError(f"personaggio sconosciuto: {name}")
    char = create(str(ch["name"]), str(ch.get("description", "")), (prod.get("bible") or {}).get("genre") or "realistic")
    ref = Path(str(ch.get("ref_image") or ""))
    # Solo immagini dentro lo spazio di lavoro: il percorso arriva dal browser.
    try:
        inside = ref.is_file() and paths.is_user_path(ref)
    except OSError:
        inside = False
    if inside:
        shutil.copy2(ref, _folder(char["id"]) / "front.png")
        char["front"] = "front.png"
    return _write(char)
