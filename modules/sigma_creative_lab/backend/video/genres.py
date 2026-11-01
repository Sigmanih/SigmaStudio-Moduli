"""Generi di video: un punto di partenza che imposta stile, modelli e musica in un colpo.

Chi apre Video Studio pensa "voglio un anime" o "una presentazione", non
"cfg 1, Animagine, fotogrammi chiave attivi". Il genere traduce l'intenzione
nelle impostazioni giuste; tutto resta modificabile dopo.

`keyframes`: il primo fotogramma di ogni inquadratura lo disegna il modello
d'immagine e H3 lo anima. Serve agli stili che H3 da solo non tiene (anime,
cartone 3D, illustrazione: prova del 2026-10-11, lo stile anime regge per
tutta la clip). Per il realismo H3 basta, e con i ritratti di riferimento
mantiene meglio l'identita' dei personaggi.
"""

from __future__ import annotations

from core.logger import get_logger

log = get_logger(__name__)

GENRES = {
    "realistic": {
        "label": "Film realistico",
        "hint": "Persone, luoghi e luce credibili: cortometraggi, spot, documentari ricostruiti.",
        "style": "Cinematic film still, photorealistic, natural lighting, 35mm lens, shallow depth of field",
        "image_model": "zimage", "keyframes": False,
        "portrait": "Cinematic photo, character reference portrait of {description}, full body, standing, "
                    "neutral grey studio background, soft even light",
        "keyframe": "Cinematic film still, photorealistic. {characters}{prompt}",
        "music": "cinematic orchestral score, strings, piano",
    },
    "anime": {
        "label": "Anime",
        "hint": "Animazione giapponese: personaggi disegnati, colori pieni, espressioni marcate.",
        "style": "anime style, cel shading, Japanese animation, vibrant colors, clean line art",
        "image_model": "animagine", "keyframes": True,
        "portrait": "{description}, solo, standing, full body, simple background, white background",
        "keyframe": "{characters}{prompt}, anime screenshot",
        "music": "emotional anime soundtrack, piano, strings, light drums",
    },
    "cartoon3d": {
        "label": "Cartone 3D",
        "hint": "Personaggi stilizzati come nei film d'animazione 3D, per famiglie e bambini.",
        "style": "3D animated movie style, stylized characters, big expressive eyes, soft global illumination, "
                 "vibrant colors",
        "image_model": "zimage", "keyframes": True,
        "portrait": "3D animated movie style character, {description}, stylized proportions, big expressive eyes, "
                    "full body, plain light background, soft cinematic lighting",
        "keyframe": "3D animated movie style, stylized characters, soft global illumination. {characters}{prompt}",
        "music": "playful orchestral score, pizzicato strings, woodwinds",
    },
    "illustration": {
        "label": "Illustrato / fumetto",
        "hint": "Disegno a mano, inchiostro, acquerello o incisione: racconti, fiabe, video poetici.",
        "style": "hand-drawn illustration, expressive ink lines, watercolor washes, textured paper",
        "image_model": "zimage", "keyframes": True,
        "portrait": "Hand-drawn illustration, character design sheet of {description}, full body, ink lines, "
                    "watercolor, plain paper background",
        "keyframe": "Hand-drawn illustration, ink lines and watercolor. {characters}{prompt}",
        "music": "gentle folk score, acoustic guitar, flute",
    },
    "lesson": {
        "label": "Lezione / spiegazione",
        "hint": "Matematica, fisica e altre materie: formule e grafici esatti, voce narrante. Si fa nell'editor con \"Lezione animata\".",
        "style": "clean educational slide, dark background, clear diagrams",
        "image_model": "zimage", "keyframes": False,
        "portrait": "Friendly teacher portrait of {description}, plain background, soft light",
        "keyframe": "Clean educational illustration. {prompt}",
        "music": "calm ambient piano, soft and unobtrusive",
        "editor_first": True,
    },
    "presentation": {
        "label": "Presentazione / demo",
        "hint": "Per presentare un progetto: i tuoi video e schermate, titoli, voce narrante e qualche scena generata.",
        "style": "clean modern tech aesthetic, soft gradients, minimal, studio lighting, high detail",
        "image_model": "zimage", "keyframes": True,
        "portrait": "Professional portrait of {description}, modern office background, soft light",
        "keyframe": "Clean modern tech visual, soft gradients, minimal, studio lighting. {prompt}",
        "music": "modern uplifting electronic, soft synths, steady beat",
        # Una presentazione si costruisce soprattutto nell'editor con materiale proprio.
        "editor_first": True,
    },
}


def public_list() -> list[dict]:
    from core.modules.sigma_creative_lab.video import image_gen
    out = []
    for gid, g in GENRES.items():
        out.append({"id": gid, "label": g["label"], "hint": g["hint"], "style": g["style"],
                    "image_model": g["image_model"], "keyframes": g["keyframes"], "music": g["music"],
                    "editor_first": bool(g.get("editor_first")),
                    "image_model_ready": image_gen.installed(g["image_model"])})
    return out


def genre_of(prod: dict) -> dict:
    return GENRES.get((prod.get("bible") or {}).get("genre") or "", GENRES["realistic"])


def portrait_prompt(prod: dict, description: str) -> str:
    return genre_of(prod)["portrait"].format(description=description.strip().rstrip("."))


# Indicazioni di inquadratura del prompt -> tag che i modelli anime capiscono. Con
# la frase lunga Animagine metteva la ragazza rivolta alla camera anche quando
# la ripresa era "da dietro", e H3 doveva poi girarla di 180 gradi.
_COMPOSITION_TAGS = (
    (("from behind", "back to the camera", "back to camera", "follows from behind", "seen from behind"), "from behind"),
    (("close-up", "close up", "closeup"), "close-up, portrait"),
    (("wide shot", "establishing", "aerial"), "wide shot"),
    (("from below", "low angle"), "from below"),
    (("from above", "high angle", "top-down"), "from above"),
    (("walks", "walking"), "walking"),
    (("runs", "running"), "running"),
    (("looking up", "looks up"), "looking up"),
    (("rain",), "rain"), (("storm",), "storm"), (("night",), "night"),
)


def _anime_tags(text: str) -> list[str]:
    low = text.lower()
    tags = [tag for keys, tag in _COMPOSITION_TAGS if any(k in low for k in keys)]
    from core.modules.sigma_creative_lab.video.clip_judge import held_objects
    tags += [f"holding {obj}" for obj in held_objects(text)]
    return tags


def shot_characters(prod: dict, shot: dict) -> list[dict]:
    """Personaggi presenti: quelli assegnati all'inquadratura piu' quelli nominati nel prompt.

    Il piano scritto dall'LLM a volte lascia vuota la lista anche quando il prompt dice
    "Mira walks...": il fotogramma chiave usciva senza la sua descrizione e il
    personaggio cambiava aspetto da un'inquadratura all'altra.
    """
    import re
    chars = [c for c in (prod.get("bible") or {}).get("characters") or [] if c.get("name")]
    listed = set(shot.get("refs") or [])
    text = shot.get("prompt") or ""
    return [c for c in chars if c["name"] in listed
            or re.search(rf"(?<!\w){re.escape(c['name'])}(?!\w)", text, flags=re.IGNORECASE)]


def style_reference(prod: dict) -> str:
    """Immagine che fissa lo stile della produzione (scelta dall'utente o il primo fotogramma chiave)."""
    from pathlib import Path
    ref = str((prod.get("bible") or {}).get("style_image") or "")
    return ref if ref and Path(ref).is_file() else ""


def keyframe_plan(prod: dict, shot: dict) -> tuple[str, str, list[str]]:
    """Modello, prompt e immagini di riferimento per il fotogramma chiave di un'inquadratura.

    Con FLUX.2 klein installato TUTTI i fotogrammi li disegna klein: prima solo quelli con
    personaggi, e le inquadrature senza (paesaggi, nemici) uscivano dal modello del genere con
    un altro stile (prova dei samurai). Riferimenti: i personaggi in scena e, se c'e', l'immagine
    di stile della produzione. Senza klein resta il modello del genere, che vede solo il testo.
    """
    from pathlib import Path
    from core.modules.sigma_creative_lab.video import image_gen
    if not image_gen.installed("klein"):
        return genre_of(prod)["image_model"], keyframe_prompt(prod, shot), []
    panel = str(shot.get("source_panel") or "")
    if panel and Path(panel).is_file():
        return "klein", *panel_keyframe(prod, shot, panel)
    style_ref = style_reference(prod)
    room = image_gen.MAX_REFS - (1 if style_ref else 0)
    present = [c for c in shot_characters(prod, shot) if c.get("ref_image") and Path(c["ref_image"]).is_file()][:room]
    g = genre_of(prod)
    style = ((prod.get("bible") or {}).get("style") or g["style"]).strip().rstrip(".")
    import re
    # Le parole dette non si disegnano: tolte le battute fra virgolette, restano azione ed espressione.
    prompt = re.sub(r"[\"“«][^\"”»]{2,}[\"”»]", "", shot["prompt"]).strip().rstrip(".")
    for fix in [f.get("text", "") for f in shot.get("fixes") or []] + list(shot.get("keyframe_fixes") or []):
        prompt += f". {str(fix).strip().rstrip('.')}"
    from core.modules.sigma_creative_lab.video.preproduction import world_lines
    parts = [f"{style}. {prompt}."] + world_lines(prod, shot)
    speaker = (shot.get("dialogue") or {}).get("character")
    if speaker:
        # Chi parla va in primo piano: con due volti grandi uguali il video muoveva la bocca sbagliata;
        # col viso piccolo o girato il labiale non si vede.
        parts.append(f"Medium close-up: {speaker} is in the foreground, face toward the viewer, mouth closed and "
                     f"clearly visible, about to speak.")
    refs = [c["ref_image"] for c in present]
    parts += [f"{c['name']} is the character in image {k}: keep exactly the same face, hair, body and clothes."
              for k, c in enumerate(present, 1)]
    if style_ref:
        refs.append(style_ref)
        parts.append(f"Match exactly the art style, colors, line work and lighting of image {len(refs)}; use it only "
                     f"as a style reference, do not copy its content or its people.")
    # Le battute nel prompt facevano disegnare a klein un fumetto con testo senza senso.
    parts.append("Single frame of the scene, each character appears once. No text, no letters, no speech bubbles, "
                 "no captions.")
    return "klein", " ".join(parts), refs

def _vignetta_pulita(panel: str) -> str:
    """La vignetta con battute e didascalie cancellate (inpainting), per non farle ridisegnare.

    Detto solo a parole, klein lasciava i balloon (vuoti o con lettere a caso);
    imbiancati, restavano cerchi bianchi. Con l'inpainting di OpenCV al loro
    posto c'e' una sfumatura dei bordi, che klein ridisegna come sfondo. I
    riquadri vengono dalla lettura (vignette.json, scala 0-1000 sul ritaglio).
    """
    import json
    from pathlib import Path
    src = Path(panel)
    stato = src.parent.parent / "vignette.json"
    try:
        import cv2
        import numpy as np
        from core import paths
        dati = json.loads(stato.read_text(encoding="utf-8"))
        v = next((x for pg in dati["pagine"] for x in pg.get("vignette") or [] if x["id"] == src.stem), None)
        boxes = [t["box"] for t in (v or {}).get("testi") or [] if t.get("box")]
        if not boxes:
            return panel
        out = paths.var_dir() / "cache" / "vignette_pulite" / f"{src.stem}_{int(src.stat().st_mtime)}.png"
        if out.is_file():
            return str(out)
        img = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        mask = np.zeros((h, w), np.uint8)
        for x0, y0, x1, y1 in boxes:
            cx, cy = (x0 + x1) / 2000 * w, (y0 + y1) / 2000 * h
            ax, ay = (x1 - x0) / 2000 * w * 1.12, (y1 - y0) / 2000 * h * 1.12
            cv2.ellipse(mask, (int(cx), int(cy)), (int(ax), int(ay)), 0, 0, 360, 255, -1)
        pulita = cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA)
        out.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", pulita)
        if not ok:
            return panel
        buf.tofile(str(out))
        return str(out)
    except Exception as exc:
        log.debug(f"vignetta non ripulita, uso l'originale: {exc}")
        return panel


def panel_keyframe(prod: dict, shot: dict, panel: str) -> tuple[str, list[str]]:
    """Fotogramma chiave ridisegnato da una vignetta di fumetto: stessa inquadratura, a colori.

    Nella trasposizione di un manga l'inquadratura e' gia' decisa dall'autore:
    descriverla a parole e farla ridisegnare da zero la perde (prova Mx0: dal
    testo usciva un'altra scena). Data la vignetta come immagine 1, klein ne
    tiene composizione, pose ed espressioni e aggiunge solo colore e i lati
    del 16:9. I colori dei personaggi, che il bianco e nero non dice, vanno a
    parole (`panel_colors` della bibbia) legati a chi fa cosa nella regia.
    """
    from pathlib import Path
    from core.modules.sigma_creative_lab.video import image_gen
    # Le comparse non hanno un aspetto fisso: dato il loro ritratto, klein lo
    # disegnava in primo piano (collaudo Mx0, 005_03: una ragazza dai capelli
    # grigi al posto della figurina lontana sul ponte). La vignetta basta.
    present = [c for c in shot_characters(prod, shot)
               if not any(w in c.get("name", "").lower() for w in ("compars", "extra"))]
    a_colori = False
    try:
        from .manga import classifica_pagina
        a_colori = Path(panel).is_file() and classifica_pagina(Path(panel)) == "colore"
    except Exception as exc:
        log.debug(f"colore della vignetta non stimato: {exc}")
    # I fogli dei personaggi come immagini: a colori klein li incollava come
    # persona in piu' (005_03, un secondo Kuzumi in giacca bianca); in bianco e
    # nero mescolava le identita' (008_04, a Kuzumi i capelli e gli occhi di
    # Aika). Restano solo per chi non ha i colori scritti nella bibbia.
    da_foglio = [] if a_colori else [
        c for c in present if not c.get("panel_colors") and c.get("ref_image") and Path(c["ref_image"]).is_file()
    ][:image_gen.MAX_REFS - 1]
    g = genre_of(prod)
    style = ((prod.get("bible") or {}).get("style") or g["style"]).strip().rstrip(".")
    sorgente = panel if a_colori else _vignetta_pulita(panel)
    parts = [
        f"Image 1 is a {'color' if a_colori else 'black-and-white'} manga panel. Redraw exactly this panel as one "
        f"fully colored anime frame: {style}. Keep the same camera framing and angle, the same composition, the "
        "same poses, gestures and facial expressions, the same background elements.",
        "Widescreen frame: extend the background naturally at the sides, do not add new characters.",
    ]
    if not a_colori:
        parts.append("Color everything: skin, hair, eyes, clothes and the whole background. No black-and-white or "
                     "gray areas, no screentone, no halftone dots.")
    # La regia lega i colori alle persone ("Kuzumi stringe la ringhiera, Aika lo
    # guarda"), ma klein la segue anche contro la vignetta: per 008_01 diceva
    # "tra le macerie" e la scena e' uscita reinventata. Serve solo a chi e' chi.
    azione = str(shot.get("prompt") or "").strip().rstrip(".")
    if azione and not a_colori and len(present) >= 2:
        parts.append(f"In this panel: {azione}.")
    color = str(shot.get("panel_colors") or "").strip().rstrip(".")
    # La regia descrive la scansione: "the scene is black and white" nel prompt
    # chiedeva a klein proprio di non colorare (collaudo Mx0, 008_04).
    if color and not any(w in color.lower() for w in ("black and white", "black-and-white", "grayscale",
                                                      "greyscale", "monochrome")):
        parts.append(f"Colors: {color}.")
    colorati = [c for c in present if c.get("panel_colors")] if not a_colori else []
    if colorati:
        # Scritto come scheda ("Kuzumi: felpa arancione") klein lo prendeva per un
        # personaggio da aggiungere: un secondo Kuzumi davanti al cancello (008_02).
        # Detto come colori di chi e' gia' disegnato, colora e basta.
        parts.append("Color the people already drawn in image 1, without adding anyone: " + "; ".join(
            f"{c['name']} has {str(c['panel_colors']).strip().rstrip('.')}" for c in colorati) + ".")
    parts += [f"Image {k} is only a color reference for {c['name']}, who is already drawn in image 1: use its "
              "hair and eye colors; do not copy its figure, pose or outfit into the frame."
              for k, c in enumerate(da_foglio, 2)]
    if present:
        # Coi vestiti descritti klein tendeva al ritratto in posa (008_02: Kuzumi in
        # piedi davanti al cancello che nella vignetta sta scavalcando, piccolo).
        parts.append("Draw exactly the people that image 1 shows, each once, where image 1 shows them, with the "
                     "same size in the frame, the same pose and the same action; this is a scene, not a portrait"
                     + ("; keep the clothes colors of image 1." if a_colori else "."))
    for fix in [f.get("text", "") for f in shot.get("fixes") or []] + list(shot.get("keyframe_fixes") or []):
        parts.append(f"{str(fix).strip().rstrip('.')}.")
    parts.append("Remove all text, speech bubbles, caption boxes, sound-effect lettering (also Japanese characters), "
                 "screentone and the panel borders: the drawing fills the whole frame edge to edge, no letters "
                 "anywhere. Where a caption box covered the drawing, continue the background; do not put a "
                 "character there.")
    return " ".join(parts), [sorgente] + [c["ref_image"] for c in da_foglio]


def keyframe_prompt(prod: dict, shot: dict) -> str:
    """Prompt del fotogramma chiave: l'istante iniziale dell'inquadratura, con l'aspetto dei personaggi."""
    genre = genre_of(prod)
    present = [c for c in shot_characters(prod, shot) if c.get("description")]
    prompt = shot["prompt"].strip().rstrip(".")
    for fix in shot.get("keyframe_fixes") or []:
        prompt += f". {fix.strip().rstrip('.')}"
    if genre["image_model"] == "animagine":
        # Tag prima della frase, senza nomi propri (che il modello non conosce): "solo"
        # evita la seconda copia del personaggio, frequente nei primi piani.
        tags = [c["description"].strip().rstrip(".") for c in present]
        if len(present) == 1:
            tags.append("solo")
        tags += _anime_tags(prompt)
        return genre["keyframe"].format(characters=", ".join(tags) + (", " if tags else ""), prompt=prompt)
    who = [f"{c['name']}: {c['description'].strip().rstrip('.')}. " for c in present]
    return genre["keyframe"].format(characters="".join(who), prompt=prompt)
