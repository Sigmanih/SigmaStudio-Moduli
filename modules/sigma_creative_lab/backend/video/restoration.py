"""Restauro dei film muti: testi sullo schermo, narrazione per personaggi e colonna sonora.

Nato dal collaudo su Nosferatu (1922, versione USA 1947), 2026-10-22. Le scelte
che sembrano arbitrarie vengono da li':
- le didascalie (testo chiaro su nero) e le pagine scritte (lettere, libri,
  diari: testo scuro su carta chiara) si trovano con due regole di luminanza
  diverse; una sola regola perdeva tutte le pagine;
- una pagina lunga scorre o cambia: dal solo fotogramma centrale l'avviso del
  borgomastro e la profezia del libro restavano a meta'. Sulle pagine lunghe si
  leggono piu' fotogrammi e si uniscono i testi;
- la stessa didascalia viene rilevata due volte (sporco della pellicola,
  dissolvenze): le letture uguali consecutive si fondono;
- Kokoro pronuncia secondo la pipeline della lingua della voce: una voce
  inglese su testo italiano, o il contrario, si capisce male. Per le lingue
  senza abbastanza voci Kokoro, Chatterbox clona il timbro inglese del personaggio;
- descrivendo le sequenze per la musica, il modello visivo che sa il titolo
  coloriva tutto di "ominous": l'atmosfera si chiede a occhi chiusi sul titolo,
  e rispetto alla sequenza precedente;
- i tag con voci ("whispering vocals") facevano cantare ACE-Step: si tolgono.

Tutti i tempi sono in secondi del clip sorgente; la timeline li sposta.
"""

from __future__ import annotations

import difflib
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from core.logger import get_logger

log = get_logger("creative_restoration")

ANALYSIS_W, ANALYSIS_H = 224, 168
PAGE_MIN_S = 1.5
TITLE_MIN_S = 0.8
#: Pagine piu' lunghe di cosi' si leggono su piu' fotogrammi.
LONG_PAGE_S = 6.0
SEQUENCE_TARGET_S, SEQUENCE_MIN_S, SEQUENCE_MAX_S = 180.0, 120.0, 240.0
MUSIC_CROSSFADE_S = 2.0
DEFAULT_SCORE_STYLE = ("1920s silent film score, chamber orchestra, strings, piano, woodwinds, "
                       "expressive, cinematic, instrumental")
_VOCAL_WORDS = re.compile(r"\b(vocals?|voices?|singing|choir|whisper\w*|chant\w*|lyrics?|humming)\b", re.I)

AskImage = Callable[[bytes, str], str]
AskText = Callable[[str, int], str]
Progress = Callable[[str, float], None]


def _ff():
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, probe
    return ffmpeg_bin, probe


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _nop(_msg: str, _p: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Analisi: didascalie, pagine, stacchi
# ---------------------------------------------------------------------------

def is_page(l_work: np.ndarray) -> bool:
    """Pagina scritta su carta chiara: molti pixel chiari, pochi toni medi (una spiaggia ne ha di piu')."""
    return bool((l_work > 55).mean() > 0.45 and ((l_work >= 20) & (l_work <= 55)).mean() < 0.25)


def _runs(flags: list[bool], fps: float, min_s: float, join_gap: int = 6) -> list[list[float]]:
    runs, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if runs and start - runs[-1][1] <= join_gap:
                runs[-1][1] = i
            else:
                runs.append([start, i])
            start = None
    return [[round(a / fps, 3), round(b / fps, 3)] for a, b in runs if (b - a) / fps >= min_s]


def analyze(clip: Path, progress: Progress = _nop) -> dict:
    """Una passata a bassa risoluzione: didascalie, pagine scritte e stacchi di montaggio."""
    import cv2
    from core.modules.sigma_creative_lab.video.postprocess import _rate_and_frames
    from core.modules.sigma_creative_lab.video.recolor_worker import CUT_DIFF, is_title_card
    ffmpeg_bin, probe = _ff()
    fps, total = _rate_and_frames(clip, probe(clip))
    w, h = ANALYSIS_W, ANALYSIS_H
    proc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-i", str(clip), "-vf", f"scale={w}:{h}", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, creationflags=_flags())
    titles, pages, cuts, prev, n = [], [], [], None, 0
    try:
        while len(buf := proc.stdout.read(w * h * 3)) == w * h * 3:
            rgb = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            lum = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)[..., 0]
            titles.append(is_title_card(lum))
            pages.append(is_page(lum))
            small = cv2.GaussianBlur((lum * 2.55).astype(np.uint8), (5, 5), 0).astype(np.float32)
            if prev is not None and np.abs(small - prev).mean() > CUT_DIFF:
                cuts.append(round(n / fps, 3))
            prev = small
            n += 1
            if n % 2000 == 0:
                progress("Analisi del film", min(0.99, n / max(total, 1)))
    finally:
        proc.stdout.close()
        proc.wait(timeout=120)
    if n == 0:
        raise RuntimeError(f"nessun fotogramma letto da {clip.name}")
    return {"fps": fps, "frames": n, "duration": round(n / fps, 3), "cuts": cuts,
            "titles": _runs(titles, fps, TITLE_MIN_S), "pages": _runs(pages, fps, PAGE_MIN_S)}


def frame_jpeg(clip: Path, t: float, max_side: int = 960) -> bytes:
    ffmpeg_bin, _probe = _ff()
    out = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(clip), "-frames:v", "1",
                          "-vf", f"scale='min({max_side},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"],
                         capture_output=True, timeout=120, creationflags=_flags())
    if not out.stdout:
        raise RuntimeError(f"fotogramma a {t:.2f} s non estraibile: {out.stderr.decode(errors='replace')[-200:]}")
    return out.stdout


def strip_jpeg(clip: Path, times: list[float], height: int = 240) -> bytes:
    """Piu' fotogrammi affiancati in un'immagine: il modello visivo ne accetta una sola."""
    from PIL import Image
    imgs = [Image.open(io.BytesIO(frame_jpeg(clip, t, 640))).convert("RGB") for t in times]
    imgs = [im.resize((max(1, int(im.width * height / im.height)), height)) for im in imgs]
    sheet = Image.new("RGB", (sum(im.width for im in imgs) + 8 * (len(imgs) - 1), height), "black")
    x = 0
    for im in imgs:
        sheet.paste(im, (x, 0))
        x += im.width + 8
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def contact_sheet(clip: Path, out: Path, every_s: float = 0.0, columns: int = 6, rows: int = 6) -> Path:
    """Provino del film (un fotogramma ogni `every_s`, di default 36 su tutta la durata), da guardare con view_image."""
    from core.modules.sigma_creative_lab.video.postprocess import _rate_and_frames
    ffmpeg_bin, probe = _ff()
    fps, total = _rate_and_frames(clip, probe(clip))
    step = every_s or max(1.0, total / fps / (columns * rows))
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-vf",
                    f"fps=1/{step:.3f},scale=320:-2,tile={columns}x{rows}", "-frames:v", "1", str(out)],
                   check=True, timeout=1800, creationflags=_flags())
    return out


# ---------------------------------------------------------------------------
# Lettura dei testi
# ---------------------------------------------------------------------------

READ_TITLE = ("This is an intertitle card from a silent film. Transcribe its text exactly, including quotation "
              "marks and punctuation, joining the lines with single spaces. Output only the text. "
              "If the image contains no readable text, output NONE.")
READ_PAGE = ("Is this frame from a silent film a close-up of written or printed text (a book page, a letter, a "
             "log, a newspaper, a notice)? If yes, transcribe the readable text exactly, in reading order, joining "
             "lines with single spaces, and output only the text. If it is not a page of text, output NONE.")


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text.strip("'\"‘’“” ").replace("–", "—")


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _join_readings(parts: list[str]) -> str:
    """Letture di piu' fotogrammi della stessa pagina: si aggiunge solo il testo nuovo."""
    out = ""
    for p in parts:
        if not p:
            continue
        if not out or _key(p) in _key(out):
            out = out or p
            continue
        if _key(out) in _key(p):
            out = p
            continue
        # Sovrapposizione fra la fine della lettura precedente e l'inizio della nuova.
        words_a, words_b = out.split(), p.split()
        best = 0
        for k in range(1, min(len(words_a), len(words_b)) + 1):
            if [_key(w) for w in words_a[-k:]] == [_key(w) for w in words_b[:k]]:
                best = k
        out = f"{out} {' '.join(words_b[best:])}".strip()
    return out


def read_cards(clip: Path, analysis: dict, ask_image: AskImage, progress: Progress = _nop) -> list[dict]:
    spans = [("title", a, b) for a, b in analysis["titles"]] + [("page", a, b) for a, b in analysis["pages"]]
    spans.sort(key=lambda s: s[1])
    cards: list[dict] = []
    for k, (kind, a, b) in enumerate(spans):
        progress(f"Lettura dei testi ({k + 1}/{len(spans)})", k / max(1, len(spans)))
        fracs = (0.2, 0.5, 0.85) if kind == "page" and b - a > LONG_PAGE_S else (0.5,)
        question = READ_TITLE if kind == "title" else READ_PAGE
        readings, quoted = [], False
        for f in fracs:
            text = ask_image(frame_jpeg(clip, a + f * (b - a)), question).strip()
            if text and text.upper() != "NONE":
                # Le virgolette dicono "battuta di un personaggio": pulendo il testo si perdevano,
                # e il cast dava al narratore "Is this your wife? What a lovely throat!".
                quoted = quoted or text.lstrip()[:1] in "'\"‘“"
                readings.append(_clean(text))
        text = _join_readings(readings)
        if len(_key(text)) < 3:
            continue
        if cards and _key(cards[-1]["text"]) == _key(text) and a - cards[-1]["end"] < 30:
            cards[-1]["end"] = b
            continue
        cards.append({"start": a, "end": b, "kind": kind, "text": text, "quoted": quoted})
    return cards


# ---------------------------------------------------------------------------
# Chi parla
# ---------------------------------------------------------------------------

_SPOKEN = re.compile(r"\b(i|i'm|i'll|i've|me|my|mine|we|we'll|us|our|you|you're|your|yours)\b|[!?]", re.I)


def is_dialogue(card: dict, quotes_informative: bool) -> bool:
    """Battuta di un personaggio o narrazione.

    Le virgolette bastano quando il film le usa solo per i dialoghi; nella
    versione USA 1947 di Nosferatu sono attorno a ogni didascalia, e decide la
    grammatica: la narrazione e' in terza persona, senza "io/tu/noi" ne' esclamazioni.
    """
    if card["kind"] != "title":
        return False
    if quotes_informative:
        return bool(card.get("quoted"))
    return bool(_SPOKEN.search(card["text"]))


CHARACTERS_PROMPT = """These lines are the narration and documents of the silent film "{title}":

{lines}

List the characters of the film named in them, each with gender (male/female), age (young/adult/old) and
menacing=true only for the villain. Answer with JSON only:
[{{"name": "Harker", "gender": "male", "age": "young", "menacing": false}}, ...]"""


def _previous_narration(cards: list[dict], card: dict) -> dict | None:
    before = [c for c in cards if c["start"] < card["start"] and c.get("speaker") == "narrator"]
    return before[-1] if before and card["start"] - before[-1]["start"] < 300 else None


CAST_PROMPT = """These are the texts shown on screen in the silent film "{title}", in order. TITLE = intertitle
card, PAGE = a written document filmed in close-up (book, letter, log, newspaper, notice), DIALOGUE = an
intertitle in quotation marks, which is always spoken by a character, never by the narrator.

{lines}

For each text decide who reads it aloud in a narrated version of the film:
- DIALOGUE: the character who says it. A name inside the line is usually the person being ADDRESSED, not
  the speaker ("Don't worry, Nina" is said TO Nina). Use the description of the person seen on screen
  around the card, and the story so far; name the character if the film names them, otherwise a short role
  such as "innkeeper"; use the same name for the same character every time;
- PAGE: its writer when clear (a letter signed by someone, a captain's log), otherwise "document".
Give each speaker a gender (male/female), an age (young/adult/old) and menacing=true only for a villain.
Answer with JSON only, one object per text, in order:
[{{"i": 0, "speaker": "narrator", "gender": "male", "age": "adult", "menacing": false}}, ...]"""


def _json_list(text: str) -> list:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


SEEN_PROMPT = ("Two frames of a silent film: the shot just before and just after an intertitle with a line of "
               "dialogue. Describe in under 15 words the person most likely speaking (gender, age, clothing, role), "
               "or 'nobody' if no person is visible.")


def cast_cards(cards: list[dict], title: str, ask_text: AskText, ask_image: AskImage | None = None,
               clip: Path | None = None, batch: int = 40) -> list[dict]:
    """Assegna chi legge ogni testo.

    Collaudo su Nosferatu, cast a mano come riferimento: chiedendo tutto al modello
    di testo coincideva su 31 righe di 72 (dava la narrazione a chi vi era
    nominato, le battute a chi veniva chiamato). Le didascalie senza virgolette
    sono del narratore per regola; per le battute il modello visivo descrive chi
    si vede accanto alla didascalia. A blocchi: con 70 righe l'8B perdeva il conto.
    """
    out = [dict(c) for c in cards]
    titles = [c for c in out if c["kind"] == "title"]
    quotes_informative = bool(titles) and sum(bool(c.get("quoted")) for c in titles) < 0.8 * len(titles)
    for c in out:
        if c["kind"] == "title" and not is_dialogue(c, quotes_informative):
            c.update(speaker="narrator", gender="male", age="adult", menacing=False)
    # I personaggi si ricavano dalla narrazione: scegliendo fra quelli il modello smette di inventare
    # ruoli ("comedian", "preacher") per ogni battuta.
    narration = [c["text"] for c in out if c.get("speaker") == "narrator" or c["kind"] == "page"]
    characters = [r for r in _json_list(ask_text(CHARACTERS_PROMPT.format(
        title=title, lines="\n".join(narration)[:6000]), 1500)) if isinstance(r, dict) and r.get("name")]
    for c in out:
        if "speaker" in c:
            continue
        if ask_image and clip and c["kind"] == "title":
            try:
                img = strip_jpeg(clip, [max(0.0, c["start"] - 1.0), c["end"] + 0.6])
                c["seen"] = _clean(ask_image(img, SEEN_PROMPT))[:120]
            except RuntimeError as e:
                log.warning(f"inquadratura attorno alla didascalia a {c['start']:.1f} s non letta: {e}")
    ask = [i for i, c in enumerate(out) if "speaker" not in c]
    for s in range(0, len(ask), batch):
        part = [out[i] for i in ask[s:s + batch]]
        # Le righe gia' assegnate fanno da contesto per i nomi usati.
        known = sorted({c["speaker"] for c in out if c.get("speaker") and c["speaker"] != "narrator"})
        lines = "\n".join(
            f"{i}. {'DIALOGUE' if c['kind'] == 'title' else 'PAGE'}: {c['text']}"
            + (f"  [on screen: {c['seen']}]" if c.get("seen") else "")
            # La narrazione che precede la battuta dice chi c'e' in scena.
            + (f"  [after narration: {prev['text'][:90]}]" if (prev := _previous_narration(out, c)) else "")
            for i, c in enumerate(part))
        prompt = CAST_PROMPT.format(title=title, lines=lines)
        if characters:
            prompt += ("\nCharacters of the film (choose among them whenever the line fits; invent a short role "
                       "only for a minor unnamed character): "
                       + "; ".join(f"{r['name']} ({r.get('gender', '?')}, {r.get('age', '?')})" for r in characters))
        if known:
            prompt += f"\nSpeakers already used: {', '.join(known)}."
        answer = _json_list(ask_text(prompt, 3000))
        for row in answer:
            try:
                c = part[int(row.get("i"))]
            except (TypeError, ValueError, IndexError):
                continue
            c["speaker"] = str(row.get("speaker") or "narrator").strip().lower().replace(" ", "_")[:40] or "narrator"
            c["gender"] = "female" if str(row.get("gender", "")).lower().startswith("f") else "male"
            c["age"] = str(row.get("age") or "adult").lower() if str(row.get("age") or "").lower() in (
                "young", "adult", "old") else "adult"
            c["menacing"] = bool(row.get("menacing"))
    names = {_key(r["name"]) for r in characters}
    for i in ask:
        c = out[i]
        c.setdefault("gender", "male")
        c.setdefault("age", "adult")
        c.setdefault("menacing", False)
        speaker = c.get("speaker") or ""
        # Una battuta non e' mai del narratore: l'8B ce la mandava anche con "you" ed esclamativi.
        if c["kind"] == "title" and speaker in ("", "narrator", "document"):
            c["speaker"] = "townswoman" if c["gender"] == "female" else "townsman"
            c["needs_review"] = True
        elif c["kind"] == "page" and not speaker:
            c["speaker"] = "document"
        elif speaker not in ("narrator", "document") and not any(n and n in _key(speaker) for n in names):
            # Ruolo inventato fuori dall'elenco dei personaggi: spesso giusto per le comparse, da guardare.
            c["needs_review"] = True
    for c in out:
        c.setdefault("speaker", "narrator")
        c.setdefault("gender", "male")
        c.setdefault("age", "adult")
        c.setdefault("menacing", False)
    return out


def translate_cards(cards: list[dict], language: str, ask_text: AskText, batch: int = 25) -> list[dict]:
    """Traduzione dei testi letti (le didascalie sullo schermo restano originali)."""
    names = {"it": "Italian", "en": "English", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese"}
    target = names.get(language, language)
    out = [dict(c) for c in cards]
    for s in range(0, len(out), batch):
        part = out[s:s + batch]
        lines = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(part))
        answer = _json_list(ask_text(
            f"Translate these lines of a silent film into natural spoken {target}, keeping names and tone. "
            f"Answer with a JSON array of strings, one per line, in order.\n\n{lines}", 3000))
        for i, c in enumerate(part):
            if i < len(answer) and isinstance(answer[i], str) and answer[i].strip():
                c["text_spoken"] = answer[i].strip()
    return out


# ---------------------------------------------------------------------------
# Voci
# ---------------------------------------------------------------------------

#: Voci inglesi di Kokoro per fascia. Il filtro ffmpeg da' il carattere (tono, eco).
NARRATOR = ("bm_george", 0.92, "aecho=0.8:0.5:40:0.12")
DOCUMENT = ("bm_fable", 0.85, "asetrate=24000*0.93,aresample=24000,aecho=0.8:0.6:60|120:0.3|0.15")
MENACING = ("am_onyx", 0.85, "asetrate=24000*0.86,aresample=24000,atempo=1.1,aecho=0.8:0.7:90|180:0.35|0.2")
POOLS = {
    ("male", "young"): ["am_michael", "am_liam", "am_puck"],
    ("male", "adult"): ["am_eric", "am_adam", "am_fenrir", "bm_lewis"],
    ("male", "old"): ["bm_daniel", "am_echo", "bm_fable"],
    ("female", "young"): ["bf_emma", "af_heart", "af_bella"],
    ("female", "adult"): ["bf_isabella", "af_sarah", "af_nicole"],
    ("female", "old"): ["bf_alice", "bf_lily"],
}


def voice_plan(cards: list[dict], existing: dict | None = None) -> dict:
    """Una voce per personaggio, la stessa per tutto il film; due personaggi non condividono una voce se si puo'."""
    plan = dict(existing or {})
    used = {v["voice"] for v in plan.values()}
    # Basta una battuta marcata "minacciosa" perche' tutto il personaggio abbia la voce scura.
    menacing = {c["speaker"] for c in cards if c.get("menacing")}
    for c in cards:
        sp = c["speaker"]
        if sp in plan:
            continue
        if sp == "narrator":
            voice, speed, filt = NARRATOR
        elif sp == "document":
            voice, speed, filt = DOCUMENT
        elif sp in menacing:
            voice, speed, filt = MENACING
        else:
            pool = POOLS.get((c.get("gender", "male"), c.get("age", "adult"))) or POOLS[("male", "adult")]
            free = [v for v in pool if v not in used] or pool
            voice, speed, filt = free[0], 1.0, ""
        plan[sp] = {"voice": voice, "speed": speed, "filter": filt}
        used.add(voice)
    return plan


def _match(expected: str, heard: str) -> float:
    norm = lambda s: " ".join(re.findall(r"[\w']+", s.lower()))  # noqa: E731
    return round(difflib.SequenceMatcher(None, norm(expected), norm(heard)).ratio(), 3)


def synthesize(cards: list[dict], plan: dict, language: str, out_dir: Path, progress: Progress = _nop) -> list[dict]:
    """Legge ogni testo con la voce del suo personaggio e lo riascolta con Whisper.

    In inglese Kokoro direttamente; nelle altre lingue Chatterbox, con un
    campione Kokoro inglese del personaggio come timbro: cosi' ogni personaggio
    resta riconoscibile in tutte le lingue.
    """
    from core.modules.sigma_creative_lab.voice.runtime import runtime_for
    ffmpeg_bin, probe = _ff()
    out_dir.mkdir(parents=True, exist_ok=True)
    rt = runtime_for("kokoro")
    refs: dict[str, Path] = {}
    done = []
    try:
        for i, c in enumerate(cards):
            progress(f"Voci ({i + 1}/{len(cards)})", i / max(1, len(cards)))
            v = plan[c["speaker"]]
            text = c.get("text_spoken") or c["text"]
            raw = out_dir / f"{i:03d}_{c['speaker']}_raw.wav"
            final = out_dir / f"{i:03d}_{c['speaker']}.wav"
            if language == "en":
                rt.synthesize(text, raw, engine="kokoro", voice=v["voice"], speed=v["speed"])
            else:
                if c["speaker"] not in refs:
                    ref = out_dir / f"ref_{c['speaker']}.wav"
                    rt.synthesize("I have long sought the causes of that terrible epidemic, and now I know.",
                                  ref, engine="kokoro", voice=v["voice"], speed=v["speed"])
                    refs[c["speaker"]] = ref
                rt.synthesize(text, raw, engine="chatterbox", language=language, voice_ref=str(refs[c["speaker"]]),
                              seed=1922 + i)
            af = ",".join(x for x in (v["filter"], "loudnorm=I=-18:TP=-2:LRA=7") if x)
            subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(raw), "-af", af, "-ar", "48000", "-ac", "2",
                            str(final)], check=True, timeout=300, creationflags=_flags())
            raw.unlink(missing_ok=True)
            heard = " ".join(s["text"] for s in rt.transcribe(final, language)["segments"])
            info = probe(final)
            dur = float(info["audio_duration"] or info["duration"] or 0.0)
            done.append({**c, "wav": str(final), "duration": round(dur, 2), "heard": heard.strip(),
                         "match": _match(text, heard)})
    finally:
        rt.unload()
    return done


def place_lines(lines: list[dict], lead: float = 0.3, gap: float = 0.4) -> list[dict]:
    """Ogni voce poco dopo la comparsa del suo testo, mai sopra la precedente."""
    out, end = [], 0.0
    for line in sorted(lines, key=lambda x: x["start"]):
        t = max(line["start"] + lead, end + gap)
        out.append({**line, "at": round(t, 3)})
        end = t + float(line.get("duration") or 0.0)
    return out


# ---------------------------------------------------------------------------
# Musica
# ---------------------------------------------------------------------------

MOOD_PROMPT = ("Three frames from one sequence of a silent film, left to right. On-screen texts in this "
               "sequence: {texts}\nDescribe the mood a film score should have for what you SEE, as 5 to 8 short "
               "comma-separated English music tags (emotion, tempo, dynamics, instruments). The previous sequence "
               "was scored as: {previous}. If this sequence feels different (daylight, calm, tender, festive, "
               "agitated), make the tags clearly different. Instruments only, no voices. Output only the tags.")


def sequences(analysis: dict) -> list[list[float]]:
    """Sequenze di ~3 minuti tagliate sullo stacco piu' vicino: un brano che cambia a meta' ripresa stona."""
    dur, cuts = analysis["duration"], analysis["cuts"]
    out, t = [], 0.0
    while dur - t > SEQUENCE_MAX_S:
        near = [c for c in cuts if t + SEQUENCE_MIN_S <= c <= t + SEQUENCE_MAX_S]
        end = min(near, key=lambda c: abs(c - (t + SEQUENCE_TARGET_S))) if near else t + SEQUENCE_MAX_S
        out.append([round(t, 3), round(end, 3)])
        t = end
    out.append([round(t, 3), round(dur, 3)])
    return out


def describe_moods(clip: Path, seqs: list[list[float]], cards: list[dict], ask_image: AskImage,
                   progress: Progress = _nop) -> list[dict]:
    out, previous = [], "nothing yet (opening of the film)"
    for k, (a, b) in enumerate(seqs):
        progress(f"Atmosfera delle sequenze ({k + 1}/{len(seqs)})", k / max(1, len(seqs)))
        texts = " / ".join(c["text"] for c in cards if a <= c["start"] < b)[:500] or "none"
        img = strip_jpeg(clip, [a + f * (b - a) for f in (0.2, 0.5, 0.8)])
        tags = ask_image(img, MOOD_PROMPT.format(texts=texts, previous=previous))
        tags = ", ".join(t.strip() for t in re.split(r"[,\n]", tags) if t.strip() and not _VOCAL_WORDS.search(t))
        tags = tags.strip(" .") or "calm, sparse, strings, piano"
        out.append({"start": a, "end": b, "tags": tags})
        previous = tags
    return out


async def compose(moods: list[dict], out_dir: Path, gpu: int, style: str = "", bpm: int = 76,
                  keyscale: str = "D minor", seed: int = 1922, progress: Progress = _nop) -> list[dict]:
    """Un brano ACE-Step per sequenza, lungo quanto lei piu' la dissolvenza nella successiva."""
    from core.modules.sigma_creative_lab.backends.comfy_launcher import instances
    from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
    from core.modules.sigma_creative_lab.video.soundtrack import build_ace_step
    import asyncio
    ffmpeg_bin, _probe = _ff()
    out_dir.mkdir(parents=True, exist_ok=True)
    url = await asyncio.to_thread(instances.ensure, gpu)
    backend = ComfyUIBackend(base_url=url, config={"timeout": 1800})
    base = (style or DEFAULT_SCORE_STYLE).strip().rstrip(",")
    cues = []
    for k, m in enumerate(moods):
        progress(f"Musica ({k + 1}/{len(moods)})", k / max(1, len(moods)))
        last = k == len(moods) - 1
        seconds = m["end"] - m["start"] + (0.0 if last else MUSIC_CROSSFADE_S)
        target = out_dir / f"cue_{k:03d}.flac"
        if not target.is_file():
            graph = build_ace_step(f"{base}, {m['tags']}", seconds, seed + 101 * k, bpm, keyscale,
                                   prefix=f"sigma/restore/cue_{k:03d}")
            data, _name = await backend.run({"workflow": graph}, timeout_s=1800)
            raw = out_dir / f"cue_{k:03d}.raw"
            raw.write_bytes(data)
            subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(raw), "-t", f"{seconds:.3f}", "-ar", "48000",
                            "-ac", "2", str(target)], check=True, timeout=600, creationflags=_flags())
            raw.unlink(missing_ok=True)
        cues.append({"start": m["start"], "seconds": round(seconds, 3), "path": str(target), "tags": m["tags"],
                     "fade_in": 0.0 if k == 0 else MUSIC_CROSSFADE_S, "fade_out": 3.0 if last else MUSIC_CROSSFADE_S})
    return cues


# ---------------------------------------------------------------------------
# Stato del restauro di un'inquadratura (file accanto al manifest della produzione)
# ---------------------------------------------------------------------------

def state_path(prod_dir: Path, shot_id: str) -> Path:
    return prod_dir / "restoration" / f"{shot_id}.json"


def load_state(prod_dir: Path, shot_id: str) -> dict:
    p = state_path(prod_dir, shot_id)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"stato del restauro di {shot_id} illeggibile: {e}")
        return {}


def save_state(prod_dir: Path, shot_id: str, state: dict) -> None:
    p = state_path(prod_dir, shot_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def update_cards(prod_dir: Path, shot_id: str, edits: list[dict]) -> list[dict]:
    """Correzioni a mano: testo, chi parla, eliminazione. Le voci si rifanno con la narrazione."""
    state = load_state(prod_dir, shot_id)
    cards = state.get("cards") or []
    voices = state.get("voices") or {}
    for e in edits:
        try:
            i = int(e["index"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("ogni correzione ha bisogno di 'index'")
        if not 0 <= i < len(cards):
            raise ValueError(f"testo {i} inesistente (sono {len(cards)})")
        # La voce di un personaggio si sceglie dalle sue caratteristiche: se cambiano, va rifatta
        # (nel collaudo il Conte corretto a mano restava con la voce del "lawyer").
        if any(e.get(k) not in (None, "") for k in ("speaker", "gender", "age", "menacing")):
            voices.pop(cards[i].get("speaker"), None)
            if e.get("speaker"):
                voices.pop(str(e["speaker"]).strip().lower().replace(" ", "_")[:40], None)
        if e.get("delete"):
            cards[i]["deleted"] = True
            continue
        if e.get("text") is not None:
            cards[i]["text"] = _clean(str(e["text"]))
            cards[i].pop("text_spoken", None)
        if e.get("speaker"):
            cards[i]["speaker"] = str(e["speaker"]).strip().lower().replace(" ", "_")[:40]
        # Qualunque correzione a mano vale come revisione.
        cards[i].pop("needs_review", None)
        for k in ("gender", "age"):
            if e.get(k):
                cards[i][k] = str(e[k]).lower()
        if e.get("menacing") is not None:
            cards[i]["menacing"] = bool(e["menacing"])
    state["cards"] = cards
    state["voices"] = voices
    save_state(prod_dir, shot_id, state)
    return cards


# ---------------------------------------------------------------------------
# Sorgenti interlacciate (riversamenti video di pellicola)
# ---------------------------------------------------------------------------

def interlaced(src: Path, samples: int = 5, sample_s: float = 20.0) -> bool:
    """Riversamento con pulldown: fotogrammi interlacciati in piu' punti del film.

    Il pettine si vede solo dove c'e' movimento: in Nosferatu 1947 i campioni da
    20 s andavano dal 2% (scena quasi ferma a meta' film, che da sola diceva
    "progressivo") al 48%, con il 24% in tutto. Una sorgente progressiva sta
    sullo 0-2%. Senza ricomporre i fotogrammi i contorni in movimento restano a
    pettine, e l'upscale li ingrandisce.
    """
    from core.modules.sigma_creative_lab.video.postprocess import _rate_and_frames
    ffmpeg_bin, probe = _ff()
    fps, total = _rate_and_frames(src, probe(src))
    duration = total / fps if fps else 0.0
    combed = frames = 0
    worst = 0.0
    for k in range(samples):
        at = max(0.0, duration * (k + 1) / (samples + 1) - sample_s / 2)
        res = subprocess.run([ffmpeg_bin(), "-hide_banner", "-ss", f"{at:.1f}", "-t", f"{sample_s:.0f}", "-i", str(src),
                              "-an", "-vf", "idet", "-f", "null", "-"], capture_output=True, text=True, timeout=600,
                             creationflags=_flags())
        m = re.findall(r"Multi frame detection: TFF:\s*(\d+)\s+BFF:\s*(\d+)\s+Progressive:\s*(\d+)", res.stderr)
        if not m:
            continue
        tff, bff, prog = (int(x) for x in m[-1])
        n = tff + bff + prog
        if n:
            combed += tff + bff
            frames += n
            worst = max(worst, (tff + bff) / n)
    return bool(frames) and (combed / frames > 0.10 or worst > 0.30)


def ivtc_filter(src: Path) -> str:
    """Filtro che ricompone i fotogrammi della pellicola (o stringa vuota se la sorgente e' progressiva)."""
    return "fieldmatch=order=auto:combmatch=full,yadif=deint=interlaced,decimate," if interlaced(src) else ""
