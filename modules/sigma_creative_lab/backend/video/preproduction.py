"""Pre-produzione: storia sviluppata, luoghi e oggetti descritti prima delle inquadrature.

Prova "Il seme di Lia" (2026-10-13): dal soggetto si passava subito alle inquadrature e
ne usciva una storia piatta, con il vaso disegnato ogni volta in modo diverso (una volta
col becco dell'annaffiatoio). Qui l'agente scrive prima la storia completa (chi vuole
cosa, ostacolo, svolta, messaggio), poi descrive per filo e per segno ogni luogo e ogni
oggetto. L'utente rilegge e corregge tutto prima che si generi un solo fotogramma; le
descrizioni entrano poi in ogni prompt di immagine e di clip.

Il soggetto puo' essere scritto in qualsiasi lingua: le descrizioni per i modelli escono
in inglese, quello che legge l'utente nella sua lingua.
"""

from __future__ import annotations

import re
import threading
from typing import Callable

from core.logger import get_logger

log = get_logger("creative_preproduction")

STORY_PROMPT = """Sei uno sceneggiatore di film d'animazione. Sviluppa il soggetto in una storia completa per un
video di {minutes} minuti ({seconds} secondi). Il soggetto puo' essere in qualsiasi lingua o solo un'idea: capiscilo
e sviluppalo.
Stile visivo: {style}
Personaggi (usa questi nomi; altre figure solo se servono davvero, come comparse): {characters}
Soggetto: {treatment}

Cosa rende buona la storia:
- il protagonista VUOLE qualcosa di concreto e c'e' un ostacolo vero; almeno un tentativo fallisce prima della
  svolta; il finale e' guadagnato dalle scelte dei personaggi, non regalato da magia o coincidenze;
- il messaggio si capisce dalle azioni, senza prediche; se il tema e' educativo, le informazioni sono giuste e
  concrete (cosa, come, perche') e nulla accade per magia;
- ogni scena succede in un luogo preciso, ha un'emozione dominante e cambia qualcosa nella storia;
- dettagli originali e visivi: oggetti, gesti, piccoli imprevisti, momenti buffi; niente frasi generiche;
- ogni personaggio presente fa qualcosa e ha un modo di fare riconoscibile; i dialoghi sono brevi e naturali;
- pochi luoghi ben definiti (uno ogni due o tre scene) invece di tanti luoghi appena accennati;
- tutto deve essere filmabile: azioni visibili, niente pensieri o ricordi che non si possono mostrare.

Rispondi SOLO con JSON:
{{"title": "titolo", "logline": "la storia in una frase", "message": "il messaggio in una frase",
 "arc": {{"want": "cosa vuole il protagonista", "obstacle": "cosa glielo impedisce",
   "failed_attempt": "il tentativo che fallisce", "turning_point": "cosa cambia", "resolution": "come si risolve"}},
 "locations": ["nome breve di ogni luogo, es. il prato del parco"],
 "scenes": [{{"title": "...", "location": "uno dei nomi di locations, identico",
   "time": "momento del giorno e luce", "mood": "emozione dominante",
   "summary": "4-6 frasi: cosa succede in ordine, chi vuole cosa, gesti ed espressioni",
   "lines": [{{"character": "nome di chi parla", "line": "battuta breve, fino a 12 parole"}}],
   "seconds": numero}}]}}
Battute: al massimo una ogni 5 secondi di scena, nell'ordine in cui si dicono; dette solo dai personaggi della
lista; brevi e naturali, adatte al pubblico.
Scrivi tutto in {language}. La somma dei secondi e' circa {seconds}; fra {min_scenes} e {max_scenes} scene."""

REVIEW_PROMPT = """Sei un story editor esigente. Questa e' la prima stesura di una storia per un video di {seconds}
secondi (pubblico e tono dal soggetto: {treatment}).
{story}

Trova i punti deboli: buchi logici, cose che accadono per magia o per caso, informazioni sbagliate, scene in cui
non cambia niente, personaggi passivi, finale non guadagnato, battute lunghe o da adulti, cose non filmabili,
luoghi chiamati in modi diversi. Poi riscrivi la storia corretta e migliorata, stessi personaggi e durata.
Rispondi SOLO con JSON, stesso formato della stesura (title, logline, message, arc, locations, scenes), tutto
in {language}."""

DESIGN_PROMPT = """You are the production designer of an animated film. Visual style: {style}
Characters (already designed, do not describe them or their clothes): {characters}
Scenes:
{scenes}

Describe precisely, in English, the LOCATIONS and the important OBJECTS of the story, so that an image model draws
each of them exactly the same way in every shot.
- Locations: describe exactly these, with these exact names: {locations}. 40-70 words each, no characters:
  layout, landscape or architecture, materials, colors, vegetation or furniture, where the light comes from, one
  recurring detail that makes it recognizable. No written signs or text.
- Objects (25-50 words each): only things that matter to the story or that a character handles (at most 8; no
  clothes, no buildings, no plants of the background). Shape, size compared to a hand or a person, material,
  color, distinctive details, and what it does NOT have when a model could confuse it (e.g. "a plain round
  terracotta pot with no spout and no handle"). "name": plain lowercase english words as a writer would use them
  in a sentence (e.g. "plastic bottle", "picnic blanket"). "states": how it looks at each stage of the story in one
  line ("only dark soil -> a tiny two-leaf sprout -> a small plant with five leaves"), or "" if it never changes.
Reply ONLY with JSON: {{"locations": [{{"name": "...", "description": "..."}}],
 "props": [{{"name": "...", "description": "...", "states": "..."}}]}}"""

TRANSLATE_PROMPT = """Translate into natural English for an image and video model. Keep names, objects, numbers and
camera directions exactly; do not add or remove anything. Reply ONLY with a JSON array of strings, same order.
{items}"""

#: Parole funzionali inglesi: un testo lungo che non ne ha nessuna non e' in inglese, in qualsiasi
#: lingua sia scritto (non solo italiano: l'utente puo' scrivere come vuole).
_ENGLISH_WORDS = {"the", "a", "an", "and", "of", "in", "on", "with", "to", "is", "are", "his", "her", "their",
                  "at", "from", "by", "as", "it", "its", "into", "while", "for", "she", "he", "they", "this"}


class PreproductionCancelled(Exception):
    """La pre-produzione e' stata fermata dall'utente."""


def needs_english(text: str) -> bool:
    """Il testo va tradotto prima di arrivare ai modelli di immagine e video?"""
    from core.modules.sigma_creative_lab.video.production import looks_italian
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    if looks_italian(text):
        return True
    return len(words) >= 5 and not any(w in _ENGLISH_WORDS for w in words)


def to_english(texts: list[str], generate: Callable | None = None) -> list[str]:
    """Traduce in inglese solo i testi che non lo sono; se la traduzione fallisce restano com'erano."""
    from core.modules.sigma_creative_lab.video.production import _default_generate, extract_json
    todo = [i for i, t in enumerate(texts) if isinstance(t, str) and t.strip() and needs_english(t)]
    if not todo:
        return list(texts)
    gen = generate or _default_generate
    import json
    try:
        out = extract_json(gen([{"role": "user", "content": TRANSLATE_PROMPT.format(
            items=json.dumps([texts[i] for i in todo], ensure_ascii=False))}], 3000), list)
    except Exception as e:
        log.warning(f"traduzione in inglese non riuscita: {e}")
        return list(texts)
    result = list(texts)
    if isinstance(out, list) and len(out) == len(todo):
        for i, t in zip(todo, out):
            if isinstance(t, str) and t.strip():
                result[i] = t.strip()
    return result


def _characters_text(characters: list) -> str:
    return "; ".join(f"{c.get('name')}: {c.get('description', '')}".strip() for c in characters if c.get("name")) \
        or "nessuno in particolare"


def develop_story(treatment: str, minutes: float, characters: list, style: str = "",
                  generate: Callable | None = None, language: str = "italiano", revise: bool = True) -> dict:
    """La storia completa, scena per scena: e' cio' che l'utente rilegge prima di tutto il resto.

    Due passaggi: stesura e revisione critica. Prova del picnic (2026-10-13): alla prima stesura la
    bottiglia di plastica diventava un vaso "per magia" e nessun tentativo falliva.
    """
    from core.modules.sigma_creative_lab.video.production import _default_generate, extract_json
    import json
    gen = generate or _default_generate
    seconds = max(10.0, float(minutes) * 60.0)
    n = max(2, round(seconds / 30.0))
    raw = extract_json(gen([{"role": "user", "content": STORY_PROMPT.format(
        minutes=minutes, seconds=int(seconds), style=style or "libero", characters=_characters_text(characters),
        treatment=(treatment or "").strip(), language=language, min_scenes=max(1, n - 2), max_scenes=n + 2)}], 5000))
    if isinstance(raw, list):
        raw = {"scenes": raw}
    if not isinstance(raw, dict):
        raise ValueError("il modello non ha scritto la storia")
    if revise and raw.get("scenes"):
        try:
            better = extract_json(gen([{"role": "user", "content": REVIEW_PROMPT.format(
                seconds=int(seconds), treatment=(treatment or "").strip()[:600], language=language,
                story=json.dumps(raw, ensure_ascii=False))}], 6000))
            if isinstance(better, dict) and any(isinstance(x, dict) and x.get("summary") for x in better.get("scenes") or []):
                raw = better
        except Exception as e:
            # La prima stesura resta valida: la revisione e' un di piu'.
            log.warning(f"revisione della storia non riuscita: {e}")
    scenes = []
    for s in raw.get("scenes") or []:
        if not isinstance(s, dict) or not str(s.get("summary") or "").strip():
            continue
        scenes.append({"title": str(s.get("title") or f"Scena {len(scenes) + 1}").strip(),
                       "location": str(s.get("location") or "").strip(),
                       "time": str(s.get("time") or "").strip(), "mood": str(s.get("mood") or "").strip(),
                       "summary": str(s["summary"]).strip(), "lines": _lines(s.get("lines"), characters),
                       "seconds": max(1.0, float(s.get("seconds") or 0) or 1.0)})
    if not scenes:
        raise ValueError("il modello non ha scritto nessuna scena")
    # I modelli sbagliano le somme: si riporta la durata a quella chiesta.
    k = seconds / sum(s["seconds"] for s in scenes)
    for s in scenes:
        s["seconds"] = round(s["seconds"] * k, 1)
    arc = raw.get("arc") if isinstance(raw.get("arc"), dict) else {}
    return {"title": str(raw.get("title") or "").strip(), "logline": str(raw.get("logline") or "").strip(),
            "message": str(raw.get("message") or "").strip(),
            "arc": {k: str(arc.get(k) or "").strip() for k in ("want", "obstacle", "failed_attempt",
                                                               "turning_point", "resolution")},
            "scenes": scenes}


def design_world(story: dict, characters: list, style: str = "", generate: Callable | None = None) -> dict:
    """Luoghi e oggetti descritti in inglese; ogni luogo citato dalle scene ha la sua voce."""
    from core.modules.sigma_creative_lab.video.production import _default_generate, extract_json
    gen = generate or _default_generate
    listing = "\n".join(f"{i}. [{s.get('location') or '?'} · {s.get('time') or ''}] {s['title']}: {s['summary']}"
                        for i, s in enumerate(story.get("scenes") or [], 1))
    names = list(dict.fromkeys(s["location"] for s in story.get("scenes") or [] if s.get("location")))
    try:
        raw = extract_json(gen([{"role": "user", "content": DESIGN_PROMPT.format(
            style=style or "free", characters=_characters_text(characters), scenes=listing,
            locations="; ".join(names) or "(deduce them from the scenes)")}], 4000))
    except Exception as e:
        log.warning(f"luoghi e oggetti non descritti: {e}")
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    locations = [{"name": str(x.get("name") or "").strip(), "description": str(x.get("description") or "").strip()}
                 for x in raw.get("locations") or [] if isinstance(x, dict) and str(x.get("name") or "").strip()]
    props = [{"name": prop_name(x.get("name")), "description": str(x.get("description") or "").strip(),
              "states": _states(x.get("states"))}
             for x in raw.get("props") or [] if isinstance(x, dict) and prop_name(x.get("name"))][:10]
    # Vestiti e personaggi non sono oggetti di scena: la loro descrizione e' gia' nel personaggio, e un
    # secondo testo la contraddiceva (prova del picnic: "blue scarf" di Pepe).
    worn = " ".join(f"{c.get('name', '')} {c.get('description', '')}" for c in characters).lower()
    worn_words = set(re.findall(r"[a-z]+", worn))
    # Anche "knitted cap" contro "a knitted dark green wool cap": basta che ogni parola sia nella descrizione.
    props = [x for x in props if not set(re.findall(r"[a-z]+", x["name"])) <= worn_words]
    # Un luogo delle scene senza descrizione resterebbe senza vincoli: si aggiunge, da completare a mano.
    known = {_key(x["name"]) for x in locations}
    for s in story.get("scenes") or []:
        if s.get("location") and _key(s["location"]) not in known:
            locations.append({"name": s["location"], "description": ""})
            known.add(_key(s["location"]))
    texts = to_english([x["description"] for x in locations] + [x["description"] for x in props], gen)
    for x, t in zip(locations + props, texts):
        x["description"] = t
    return {"locations": locations, "props": props}


def _lines(raw, characters: list) -> list[dict]:
    """Battute della scena, solo di personaggi della bibbia (anche chiamati col loro ruolo)."""
    from core.modules.sigma_creative_lab.video.production import _dialogue_of
    out = []
    for x in raw if isinstance(raw, list) else []:
        d = _dialogue_of(x, characters) if characters else (
            {"character": str(x.get("character") or "").strip(), "text": str(x.get("line") or x.get("text") or "").strip()}
            if isinstance(x, dict) else None)
        if d and d.get("character") and d.get("text"):
            out.append({"character": d["character"], "line": d["text"]})
    return out


def prop_name(name) -> str:
    """Nome dell'oggetto come compare in una frase: "PlasticBottle" -> "plastic bottle"."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name or "")).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _states(value) -> str:
    """Gli stati dell'oggetto su una riga, anche quando il modello li scrive come lista."""
    if isinstance(value, list):
        return " -> ".join(str(x).strip() for x in value if str(x).strip())
    text = str(value or "").strip()
    if text.startswith("["):
        try:
            import ast
            items = ast.literal_eval(text)
            if isinstance(items, list):
                return " -> ".join(str(x).strip() for x in items if str(x).strip())
        except (ValueError, SyntaxError):
            pass
    return text


def preproduce(treatment: str, minutes: float, characters: list, style: str = "", generate: Callable | None = None,
               progress: Callable[[str], None] | None = None, cancel: threading.Event | None = None) -> dict:
    """Storia + mondo: il pacchetto che va nella bibbia della produzione (`bible["pre"]`)."""
    if progress:
        progress("Sviluppo della storia...")
    story = develop_story(treatment, minutes, characters, style, generate)
    if cancel is not None and cancel.is_set():
        raise PreproductionCancelled("fermata dopo la storia")
    if progress:
        progress(f"Luoghi e oggetti di {len(story['scenes'])} scene...")
    return {**story, **design_world(story, characters, style, generate)}


def _key(name: str) -> str:
    return re.sub(r"^(?:the|il|lo|la|l'|i|gli|le)\s+", "", re.sub(r"\s+", " ", str(name or "").strip().lower()))


def location_of(prod: dict, shot: dict) -> dict | None:
    """Il luogo dell'inquadratura: il suo, o quello della scena a cui appartiene."""
    pre = (prod.get("bible") or {}).get("pre") or {}
    places = {_key(x.get("name")): x for x in pre.get("locations") or [] if x.get("description")}
    name = shot.get("location") or next((s.get("location") for s in pre.get("scenes") or []
                                         if s.get("title") == shot.get("scene")), "")
    return places.get(_key(name)) if name else None


def props_of(prod: dict, shot: dict) -> list[dict]:
    """Gli oggetti del catalogo presenti nell'inquadratura (nominati nei suoi oggetti o nel prompt)."""
    pre = (prod.get("bible") or {}).get("pre") or {}
    text = " ".join([shot.get("prompt", "")] + [str(x) for x in shot.get("props") or []]).lower()
    out = []
    for p in pre.get("props") or []:
        k = _key(p.get("name"))
        if k and p.get("description") and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text):
            out.append(p)
    return out


def world_lines(prod: dict, shot: dict) -> list[str]:
    """Le frasi di luogo, oggetti ed espressioni che entrano nei prompt di immagine e clip."""
    lines = []
    loc = location_of(prod, shot)
    if loc:
        lines.append(f"Setting, {loc['name']}: {loc['description'].strip().rstrip('.')}.")
    for p in props_of(prod, shot):
        lines.append(f"The {_key(p['name'])}: {p['description'].strip().rstrip('.')}.")
    expr = shot.get("expressions") or {}
    if isinstance(expr, dict) and expr:
        lines.append("Facial expressions: " + "; ".join(f"{k}: {v}" for k, v in expr.items() if str(v).strip()) + ".")
    return lines


def scene_brief(pre: dict, scene: dict) -> str:
    """Il blocco "mondo" del prompt delle inquadrature di una scena."""
    if not pre:
        return ""
    lines = []
    places = {_key(x.get("name")): x for x in pre.get("locations") or []}
    loc = places.get(_key(scene.get("location")))
    if loc:
        lines.append(f"Luogo della scena: {loc['name']} - {loc.get('description') or '(da descrivere)'}")
    if scene.get("time") or scene.get("mood"):
        lines.append(f"Momento e atmosfera: {scene.get('time', '')}; {scene.get('mood', '')}".strip("; "))
    props = [f"{p['name']}: {p.get('description', '')}" + (f" (stati: {p['states']})" if p.get("states") else "")
             for p in pre.get("props") or []]
    if props:
        lines.append("Oggetti della storia (chiamali sempre con questo nome, aspetto fisso):\n- " + "\n- ".join(props))
    said = [f"{k}. {x['character']}: \"{x['line']}\"" for k, x in enumerate(scene.get("lines") or [], 1)]
    if said:
        lines.append("Battute della scena, da mettere TUTTE nel campo \"dialogue\", una per inquadratura e in questo "
                     "ordine:\n" + "\n".join(said))
    if pre.get("message"):
        lines.append(f"Messaggio della storia: {pre['message']}")
    return "\n".join(lines)


def _norm_line(text: str) -> str:
    return re.sub(r"[^\w]+", " ", str(text or "").lower()).strip()


def place_lines(shots: list, lines: list) -> int:
    """Le battute della scena che lo storyboard ha perso vanno sulle inquadrature giuste.

    Prova del picnic: l'ultima scena aveva dieci battute nella storia e nessuna nelle inquadrature.
    Ogni battuta mancante va sulla prima inquadratura successiva all'ultima battuta piazzata, senza
    battuta, dove chi parla e' in scena; se non c'e', su una senza battuta e chi parla entra in scena.
    Ritorna quante ne ha piazzate.
    """
    from difflib import SequenceMatcher
    placed, cursor = 0, -1
    for ln in lines or []:
        want = _norm_line(ln.get("line"))
        hit = next((k for k, sh in enumerate(shots) if (sh.get("dialogue") or {}).get("text")
                    and SequenceMatcher(None, _norm_line(sh["dialogue"]["text"]), want).ratio() > 0.6), None)
        if hit is not None:
            cursor = max(cursor, hit)
            continue
        free = [k for k in range(cursor + 1, len(shots)) if not shots[k].get("dialogue")]
        k = next((k for k in free if ln["character"] in (shots[k].get("refs") or [])), free[0] if free else None)
        if k is None:
            log.warning(f"battuta senza inquadratura libera: {ln['character']}: {ln['line']}")
            continue
        shots[k]["dialogue"] = {"character": ln["character"], "text": ln["line"]}
        if ln["character"] not in shots[k].setdefault("refs", []):
            shots[k]["refs"].append(ln["character"])
        if shots[k].get("transition") == "continue":
            shots[k]["transition"] = "cut"
        cursor, placed = k, placed + 1
    return placed
