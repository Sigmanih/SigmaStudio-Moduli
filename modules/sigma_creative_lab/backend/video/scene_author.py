"""Scene didattiche scritte dal modello linguistico: dalla descrizione alla pagina HTML animata.

Il modello scrive una pagina che rispetta il contratto di html_scene (window.seek(t),
nessun timer); la pagina si rende e, se il browser segnala errori o il contratto
manca, il modello riceve l'errore e la corregge. Le formule passano da KaTeX, i
grafici da canvas o SVG: esatti, a differenza di un modello video.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger("creative_scene_author")

MAX_FIX_ATTEMPTS = 2

SYSTEM = r"""You write ONE self-contained HTML fragment that is rendered to video frame by frame (1920x1080).
Rules, all mandatory:
- Output only the HTML fragment (elements + one <script>), no markdown fences, no explanations.
- Define window.sceneDuration (seconds) and window.seek = function (t) { ... } that sets the WHOLE visual state
  for time t. No setTimeout, setInterval, requestAnimationFrame, Date or Math.random: the renderer jumps in time.
- Helpers already available: progress(t, start, duration) -> eased 0..1; clamp(x); ease(x);
  tex(element, latexSource, displayMode) renders a formula with KaTeX.
- Write LaTeX with String.raw, e.g. tex(el, String.raw`v = \frac{\Delta s}{\Delta t}`).
- Use absolute positioning in a 1920x1080 page, dark background (#0f141c) is already set, text #eef2f7,
  accent colors #4fc3f7 and #ffb74d. Font sizes: titles 64px, formulas 56px, labels 32-40px: readable on a phone.
- Draw plots and diagrams with <canvas> or inline <svg>, redrawn inside seek(t). Axis labels in Italian.
- Reveal content progressively (fade/draw with progress()), keep each step on screen long enough to read.
- No external resources, no images, no fonts to download.
Example of the expected shape:
<div id="title" style="position:absolute;top:80px;width:100%;text-align:center;font-size:64px">Titolo</div>
<div id="f" style="position:absolute;top:220px;width:100%;text-align:center;font-size:56px"></div>
<script>
window.sceneDuration = 6;
tex(document.getElementById('f'), String.raw`s(t) = \tfrac{1}{2} a t^2`);
window.seek = function (t) {
  document.getElementById('title').style.opacity = progress(t, 0, 0.8);
  document.getElementById('f').style.opacity = progress(t, 1, 0.8);
};
</script>"""

USER = """Scene to create (language of all on-screen text: Italian): {description}
Target duration: about {seconds} seconds."""

FIX = """The renderer reported these problems:
{errors}
Rewrite the complete fragment fixing them, same rules."""


def extract_html(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    fenced = re.search(r"```(?:html)?\s*(.*?)```", text, flags=re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("<")
    return text[start:].strip() if start >= 0 else ""


def check_contract(html: str) -> list[str]:
    """Errori evidenti prima ancora di aprire il browser."""
    problems = []
    if "window.seek" not in html:
        problems.append("window.seek(t) is missing")
    for banned in ("setTimeout", "setInterval", "requestAnimationFrame", "Math.random", "Date.now"):
        if banned in html:
            problems.append(f"{banned} is not allowed: the state must depend only on t")
    if re.search(r"<(img|link)\b[^>]*(src|href)=[\"']https?://", html, re.I):
        problems.append("external resources are not allowed")
    return problems


def _default_review(clip: Path, description: str) -> list[str]:
    from core.modules.sigma_creative_lab.video import clip_judge
    from core.modules.sigma_creative_lab.video.production import resolve_judge_device
    if not clip_judge.installed():
        return []
    try:
        return clip_judge.judge.review_scene(clip, description, resolve_judge_device({}))
    except Exception as e:
        log.warning(f"controllo visivo della scena non disponibile: {e}")
        return []


def author_scene(description: str, out: Path, seconds: float = 8.0, generate: Callable | None = None,
                 note: Callable[[str, float], None] | None = None,
                 review: Callable[[Path, str], list[str]] | None = _default_review) -> dict:
    """Scrive e rende la scena; ritorna il clip e la pagina usata."""
    from core.modules.sigma_creative_lab.video.html_scene import render_scene
    from core.modules.sigma_creative_lab.video.production import _default_generate
    gen = generate or _default_generate
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER.format(description=description.strip(), seconds=round(seconds))}]
    last_error = ""
    for attempt in range(MAX_FIX_ATTEMPTS + 1):
        if note:
            note("Scrittura della scena" if attempt == 0 else f"Correzione della scena ({attempt})", 0.1 + 0.2 * attempt)
        html = extract_html(gen(messages, 6000))
        problems = check_contract(html) if html else ["empty answer"]
        result = None
        if not problems:
            if note:
                note("Resa della scena", 0.7)
            try:
                result = render_scene(html, out, seconds)
                problems = result.get("errors") or []
            except RuntimeError as e:
                problems = [str(e)]
            if not problems and review:
                # Il browser non vede un grafico sbagliato o un testo tagliato: lo vede il giudice visivo.
                if note:
                    note("Controllo visivo della scena", 0.85)
                problems = review(out, description)
        if not problems:
            return {**result, "html": html, "attempts": attempt + 1}
        last_error = "; ".join(problems)[:600]
        log.warning(f"scena da correggere ({attempt + 1}): {last_error}")
        messages += [{"role": "assistant", "content": html or "(empty)"},
                     {"role": "user", "content": FIX.format(errors="\n".join(f"- {p}" for p in problems))}]
    raise RuntimeError(f"la scena non e' riuscita dopo {MAX_FIX_ATTEMPTS + 1} tentativi: {last_error}")


def author_kit_scene(description: str, out: Path, seconds: float = 10.0, generate: Callable | None = None,
                     note: Callable[[str, float], None] | None = None) -> dict:
    """Scena a blocchi (scene_kit): il modello compila la spec, il disegno e' esatto per costruzione.

    E' la modalita' predefinita: con l'HTML libero il modello disegnava una retta
    al posto della parabola e sovrapponeva il grafico alla formula.
    """
    from core.modules.sigma_creative_lab.video import scene_kit
    from core.modules.sigma_creative_lab.video.html_scene import render_scene
    from core.modules.sigma_creative_lab.video.production import _default_generate
    gen = generate or _default_generate
    messages = [{"role": "system", "content": scene_kit.AUTHOR_SYSTEM},
                {"role": "user", "content": USER.format(description=description.strip(), seconds=round(seconds))}]
    last_error = ""
    for attempt in range(MAX_FIX_ATTEMPTS + 1):
        if note:
            note("Progetto della scena" if attempt == 0 else f"Correzione della scena ({attempt})", 0.1 + 0.2 * attempt)
        answer = gen(messages, 3000)
        try:
            spec = scene_kit.normalize(scene_kit.json_from(answer))
            problems = scene_kit.validate(spec)
        except ValueError as e:
            spec, problems = None, [f"invalid JSON: {e}"]
        if not problems:
            spec["duration"] = float(spec.get("duration") or seconds)
            if note:
                note("Resa della scena", 0.7)
            try:
                result = render_scene(scene_kit.to_html(spec), out, spec["duration"])
                problems = result.get("errors") or []
            except RuntimeError as e:
                problems = [str(e)]
            if not problems:
                out.with_suffix(".scene.json").write_text(__import__("json").dumps(spec, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
                return {**result, "spec": spec, "attempts": attempt + 1}
        last_error = "; ".join(problems)[:600]
        log.warning(f"scena da correggere ({attempt + 1}): {last_error}")
        messages += [{"role": "assistant", "content": answer or "(empty)"},
                     {"role": "user", "content": FIX.format(errors="\n".join(f"- {p}" for p in problems))}]
    raise RuntimeError(f"la scena non e' riuscita dopo {MAX_FIX_ATTEMPTS + 1} tentativi: {last_error}")
