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
