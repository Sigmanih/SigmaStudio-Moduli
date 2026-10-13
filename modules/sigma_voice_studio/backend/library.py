"""Libreria delle voci personali: create da una descrizione, clonate da un campione o scelte fra le predefinite.

Ogni voce e' un campione WAV di qualche secondo piu' i suoi metadati: chi la usa
(la chat, i personaggi dei video) la ripete clonando il campione, quindi il
timbro resta lo stesso ovunque. Le voci sono lavoro dell'utente e stanno nello
spazio di lavoro (data/voices), non fra i file rigenerabili.

La sintesi passa dai motori del Creative Lab (Chatterbox, Qwen3-TTS, Kokoro nel
loro ambiente isolato). Il modulo e' facoltativo: senza, la libreria si vede ma
non sintetizza, e il motivo arriva all'interfaccia.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from core import paths
from core.logger import get_logger

log = get_logger("voice_library")

SAMPLE_TEXT = "Buongiorno. Questa e' la mia voce: la userai nei video e nelle conversazioni."
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
MAX_SAMPLE_BYTES = 20 * 1024 * 1024


def voices_dir() -> Path:
    return paths.works_area("voci", legacy="voices")


def _runtimes():
    """Motori vocali del Creative Lab, se il modulo c'e'."""
    try:
        from core.modules.sigma_creative_lab.voice.runtime import qwen_runtime, voice_runtime
    except ImportError as e:
        raise RuntimeError("serve il modulo Creative Lab con le voci installate (Video Studio → Motori)") from e
    return voice_runtime, qwen_runtime


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:32] or "voce"


def _read(folder: Path) -> dict | None:
    meta = folder / "voice.json"
    if not meta.is_file() or not (folder / "sample.wav").is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return {**data, "sample": str(folder / "sample.wav")}


def list_voices() -> list[dict]:
    root = voices_dir()
    if not root.is_dir():
        return []
    voices = [v for v in (_read(d) for d in sorted(root.iterdir()) if d.is_dir()) if v]
    return sorted(voices, key=lambda v: v.get("created", 0))


def get(voice_id: str) -> dict | None:
    if not re.fullmatch(r"[a-z0-9_]{3,64}", voice_id or ""):
        return None
    return _read(voices_dir() / voice_id)


def _new_folder(name: str) -> tuple[str, Path]:
    voice_id = f"{_slug(name)}_{uuid.uuid4().hex[:6]}"
    folder = voices_dir() / voice_id
    folder.mkdir(parents=True, exist_ok=True)
    return voice_id, folder


def _save(folder: Path, voice_id: str, name: str, kind: str, **extra) -> dict:
    meta = {"id": voice_id, "name": name.strip() or "Voce", "kind": kind, "created": time.time(), **extra}
    (folder / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**meta, "sample": str(folder / "sample.wav")}


#: Motori che creano una voce da una descrizione e poi la ripetono clonando il campione con la sua
#: trascrizione. Prova delle voci (2026-10-13): entrambi in italiano nativo, Whisper senza errori;
#: l'utente ha scelto Qwen3-TTS per Lia, e il motore resta una scelta per personaggio.
DESIGN_ENGINES = {
    "qwen": {"design": "qwen_design", "clone": "qwen_clone", "label": "Qwen3-TTS"},
    "voxcpm": {"design": "voxcpm_design", "clone": "voxcpm_clone", "label": "VoxCPM2"},
}

#: Tipi di personaggio: descrizione per Qwen (in italiano, rende l'accento italiano) e per VoxCPM2
#: (in inglese: la parentesi italiana la leggeva ad alta voce), con una frase di campione adatta.
VOICE_TYPES = {
    "bambina": ("Una bambina italiana di 7 anni, voce acuta e infantile, vivace e curiosa, accento italiano naturale",
                "A 7-year-old Italian girl, bright high childish voice, curious and lively, native Italian speaker",
                "Nonno, guarda! Ho trovato una coccinella sulla foglia, è rossa con i puntini neri!"),
    "bambino": ("Un bambino italiano di 7 anni, voce acuta da bambino, allegro e un po' sfacciato, accento italiano naturale",
                "A 7-year-old Italian boy, high childish voice, cheerful and cheeky, native Italian speaker",
                "Ciao a tutti! Oggi facciamo un picnic enorme, con i panini e la frutta!"),
    "donna": ("Una donna italiana di 35 anni, voce calda e chiara, gentile, accento italiano naturale",
              "A 35-year-old Italian woman, warm clear gentle voice, native Italian speaker",
              "Buongiorno a tutti, oggi vi racconto una cosa che mi è successa al mercato."),
    "uomo": ("Un uomo italiano di 40 anni, voce piena e cordiale, accento italiano naturale",
             "A 40-year-old Italian man, full friendly voice, native Italian speaker",
             "Allora, ragazzi, prendete gli zaini: si parte per la gita sul lago!"),
    "nonna": ("Una nonna italiana di 75 anni, voce dolce e un po' tremula, affettuosa, accento italiano naturale",
              "A 75-year-old Italian grandmother, sweet slightly shaky affectionate voice, native Italian speaker",
              "Vieni qui, tesoro mio, che ti preparo una bella merenda con la marmellata."),
    "nonno": ("Un nonno italiano di 75 anni, voce calda, gentile e calma, leggermente roca, italiano madrelingua",
              "A warm Italian grandfather, about 75 years old, kind, calm and slightly husky voice, native Italian speaker",
              "Vieni qui, piccola mia. Ti racconto una storia di quando ero bambino e andavo a pescare al lago."),
    "animaletto": ("Un piccolo animaletto buffo dei cartoni, voce acuta da bambino, giocherellone, italiano madrelingua",
                   "A small funny cartoon animal, young high playful voice, a bit cheeky, native Italian speaker",
                   "Ciao a tutti! Io sono piccolino, ma corro velocissimo, sapete?"),
    "saggio": ("Un vecchio saggio, voce maschile profonda e lenta, parla con calma e piccole pause, italiano madrelingua",
               "A very old wise character, deep slow gentle male voice, calm with pauses, native Italian speaker",
               "Ho vissuto cento anni vicino a questo stagno, e ne ho viste tante, ragazzi miei."),
    "narratrice": ("Una narratrice italiana calda ed espressiva che legge una fiaba ai bambini",
                   "A warm expressive Italian storyteller woman reading a fairy tale to children, native Italian speaker",
                   "C'era una volta, in un parco pieno di fiori, un piccolo riccio di nome Pepe."),
}


def create_from_description(name: str, description: str, seed: int = 7, text: str = "", language: str = "it",
                            engine: str = "qwen") -> dict:
    """Voce nuova da una descrizione, con il motore scelto (Qwen3-TTS o VoxCPM2)."""
    from core.modules.sigma_creative_lab.voice.runtime import runtime_for
    if not description.strip():
        raise ValueError("descrivi la voce: eta', timbro, ritmo, carattere")
    eng = DESIGN_ENGINES.get(engine)
    if eng is None:
        raise ValueError(f"motore sconosciuto: {engine} (qwen o voxcpm)")
    runtime = runtime_for(eng["design"])
    if not runtime.installed():
        raise RuntimeError(f"{eng['label']} non installato (Video Studio → Motori → Voci)")
    voice_id, folder = _new_folder(name)
    sample_text = text or SAMPLE_TEXT
    try:
        used = _design_checked(runtime, sample_text, folder / "sample.wav", description, int(seed), language,
                               eng["design"])
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return _save(folder, voice_id, name, "design", description=description.strip(), seed=used, engine=engine,
                 sample_text=sample_text)


def create_from_type(name: str, kind: str, engine: str = "qwen", description: str = "", seed: int = 7) -> dict:
    """Voce da un tipo di personaggio (bambina, nonno...), con descrizione e frase gia' pronte."""
    if kind not in VOICE_TYPES:
        raise ValueError(f"tipo sconosciuto: {kind}")
    it, en, sample = VOICE_TYPES[kind]
    return create_from_description(name, description or (en if engine == "voxcpm" else it), seed, sample,
                                   engine=engine)


DESIGN_ATTEMPTS = 3
DESIGN_MATCH = 0.85


def _design_checked(qwen, text: str, out: Path, description: str, seed: int, language: str,
                    engine: str = "qwen_design") -> int:
    """Campione da descrizione verificato con Whisper; ritorna la seed usata.

    Con voci molto caratterizzate (un riccio dalla voce acuta) VoiceDesign a volte salta meta' frase:
    il campione e' poi il riferimento di tutte le battute, quindi conviene rifarlo subito.
    """
    voice, _q = _runtimes()
    best = None
    for k in range(DESIGN_ATTEMPTS):
        candidate = out.with_name(f"try{k}.wav")
        qwen.synthesize(text, candidate, engine=engine, instruct=description, seed=seed + k * 101,
                        language=language)
        try:
            from core.modules.sigma_creative_lab.video.editor_jobs import speech_match
            score = speech_match(text, voice.transcribe(candidate, language)["text"])
        except Exception as e:
            log.warning(f"controllo del campione non riuscito: {e}")
            score = 1.0                      # senza Whisper si tiene il primo campione
        if best is None or score > best[0]:
            best = (score, candidate, seed + k * 101)
        if score >= DESIGN_MATCH:
            break
    try:
        qwen.unload()
    except Exception as e:
        log.debug(f"Qwen non scaricato: {e}")
    _score, chosen, used = best
    chosen.replace(out)
    for left in out.parent.glob("try*.wav"):
        left.unlink(missing_ok=True)
    return used


def create_from_sample(name: str, data: bytes, filename: str) -> dict:
    """Voce clonata da un campione caricato (5-15 s di parlato pulito)."""
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValueError("campione non valido: servono WAV, MP3, FLAC, OGG o M4A")
    if len(data) > MAX_SAMPLE_BYTES:
        raise ValueError("campione troppo grande: bastano 5-15 secondi di voce")
    voice_id, folder = _new_folder(name)
    try:
        from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / f"in{ext}"
            raw.write_bytes(data)
            # Mono 24 kHz, al massimo 20 s: il timbro si coglie in pochi secondi e un
            # campione lungo rallenta ogni sintesi successiva.
            _run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(raw), "-t", "20", "-ac", "1", "-ar", "24000",
                  str(folder / "sample.wav")])
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return _save(folder, voice_id, name, "clone", source=Path(filename).name)


#: Personaggi tipici: voce italiana di partenza, tono in semitoni, velocita'. Punti di partenza da
#: ritoccare a orecchio; Kokoro pronuncia l'italiano da madrelingua, i cambi di tono restano comprensibili.
VOICE_PRESETS = {
    "bambina": ("if_sara", 3.5, 1.05), "bambino": ("im_nicola", 5.0, 1.05),
    "donna": ("if_sara", 0.0, 1.0), "uomo": ("im_nicola", 0.0, 1.0),
    "nonno": ("im_nicola", -2.5, 0.92), "nonna": ("if_sara", -2.0, 0.92),
    "animaletto": ("im_nicola", 7.0, 1.1), "gigante": ("im_nicola", -5.0, 0.88),
}


def _pitch_shift(src: Path, dst: Path, semitones: float, speed: float) -> None:
    """Tono e formanti spostati insieme (voce "piu' piccola" o "piu' grande"), durata regolata dalla velocita'."""
    import subprocess
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin
    factor = 2 ** (float(semitones) / 12)
    tempo = max(0.5, min(2.0, float(speed) / factor))
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(src), "-af",
                    f"asetrate={24000 * factor:.0f},aresample=24000,atempo={tempo:.4f}", str(dst)],
                   check=True, capture_output=True, timeout=120)


def _say_italian(text: str, out: Path, base: str, semitones: float, speed: float) -> None:
    voice, _qwen = _runtimes()
    raw = out.with_name(out.stem + ".base.wav")
    voice.synthesize(text, raw, engine="kokoro", voice=base or "if_sara", speed=1.0)
    try:
        if abs(float(semitones)) < 0.05 and abs(float(speed) - 1.0) < 0.01:
            raw.replace(out)
        else:
            _pitch_shift(raw, out, semitones, speed)
    finally:
        raw.unlink(missing_ok=True)


def create_from_preset(name: str, preset: str, semitones: float = 0.0, speed: float = 1.0, text: str = "") -> dict:
    """Voce italiana nativa: Kokoro (Sara o Nicola) con tono e velocita' propri.

    Le voci create da descrizione (Qwen3-TTS) in italiano hanno un accento straniero e Chatterbox lo
    copiava in ogni battuta: nella prova "Il seme di Lia" la bambina sembrava "una cinese che prova a
    parlare italiano" e Pepe aveva la sua stessa voce. Con questa voce le battute si dicono direttamente.
    `preset` puo' essere una voce di Kokoro (if_sara, im_nicola) o un personaggio tipico (bambina, nonno...).
    """
    voice, _qwen = _runtimes()
    if not voice.installed():
        raise RuntimeError("motori voce non installati (Video Studio → Motori → Voci)")
    if preset in VOICE_PRESETS:
        base, st, sp = VOICE_PRESETS[preset]
        semitones = semitones or st
        speed = speed if speed != 1.0 else sp
    else:
        base = preset or "if_sara"
    voice_id, folder = _new_folder(name)
    try:
        _say_italian(text or SAMPLE_TEXT, folder / "sample.wav", base, semitones, speed)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return _save(folder, voice_id, name, "preset", preset=base, semitones=float(semitones), speed=float(speed))


def update_tone(voice_id: str, semitones: float, speed: float, text: str = "") -> dict:
    """Ritocca tono e velocita' di una voce italiana e rifa' il campione."""
    v = get(voice_id)
    if v is None:
        raise ValueError(f"voce inesistente: {voice_id}")
    if v.get("kind") != "preset":
        raise ValueError("tono e velocita' si regolano solo sulle voci italiane (Sara/Nicola)")
    folder = voices_dir() / voice_id
    _say_italian(text or SAMPLE_TEXT, folder / "sample.wav", v.get("preset", "if_sara"), semitones, speed)
    meta = json.loads((folder / "voice.json").read_text(encoding="utf-8"))
    meta.update(semitones=float(semitones), speed=float(speed))
    (folder / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return get(voice_id)

def rename(voice_id: str, name: str) -> dict:
    v = get(voice_id)
    if v is None:
        raise ValueError("voce inesistente")
    folder = voices_dir() / voice_id
    meta = json.loads((folder / "voice.json").read_text(encoding="utf-8"))
    meta["name"] = name.strip() or meta["name"]
    (folder / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**meta, "sample": v["sample"]}


def delete(voice_id: str) -> bool:
    v = get(voice_id)
    if v is None:
        return False
    shutil.rmtree(voices_dir() / voice_id, ignore_errors=True)
    return True


def speak(voice_id: str, text: str, out: Path, engine: str = "", **opts) -> dict:
    """Dice `text` con la voce della libreria.

    Le voci italiane (Sara/Nicola con tono e velocita') parlano direttamente: clonarle con Chatterbox
    peggiorerebbe la pronuncia. Le altre (da descrizione o da campione) clonano il loro campione.
    """
    v = get(voice_id)
    if v is None:
        raise ValueError(f"voce inesistente: {voice_id}")
    if v.get("kind") == "preset":
        _say_italian(text, Path(out), v.get("preset", "if_sara"), float(v.get("semitones") or 0.0),
                     float(v.get("speed") or 1.0))
        return {"path": str(out)}
    from core.modules.sigma_creative_lab.voice.runtime import runtime_for
    if v.get("kind") == "design" and not engine:
        # La voce parla col motore che l'ha creata, clonando il campione con la sua trascrizione:
        # clonata da Chatterbox prendeva un accento straniero.
        eng = DESIGN_ENGINES.get(v.get("engine") or "qwen", DESIGN_ENGINES["qwen"])
        opts.setdefault("ref_text", v.get("sample_text") or (SAMPLE_TEXT if v.get("engine") else ""))
        if eng["clone"] != "voxcpm_clone":
            opts.pop("instruct", None)          # il tono per battuta lo segue solo VoxCPM2
        return runtime_for(eng["clone"]).synthesize(text, out, engine=eng["clone"], voice_ref=v["sample"], **opts)
    engine = engine or "chatterbox"
    engine = "qwen_clone" if engine == "qwen" else "voxcpm_clone" if engine == "voxcpm" else engine
    opts.pop("instruct", None) if engine != "voxcpm_clone" else None
    return runtime_for(engine).synthesize(text, out, engine=engine, voice_ref=v["sample"], **opts)
