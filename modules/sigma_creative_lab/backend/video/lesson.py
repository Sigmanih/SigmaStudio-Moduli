"""Lezioni animate: da un argomento a un video con scene esatte, voce narrante e sottotitoli.

Il modello scrive il copione a capitoli (cosa dire e cosa mostrare); ogni
capitolo diventa una narrazione TTS e una scena a blocchi (scene_kit) lunga
quanto la sua narrazione, cosi' immagini e parole restano allineate senza
ritocchi a mano.
"""

from __future__ import annotations

from typing import Callable

LESSON_SYSTEM = """You are a teacher writing the script of a short explainer video in Italian.
Reply with JSON only (no markdown):
{"title": "...", "chapters": [{"narration": "what the narrator says, 1-3 short Italian sentences",
                               "visual": "what the slide must show: formulas (in LaTeX words), plots, trajectories or
                                          bullet points, consistent with the narration"}]}
Rules: {chapters} chapters; each narration 15-40 words, simple and correct, written as it is spoken: numbers and
symbols in words ("c al quadrato uguale a a al quadrato più b al quadrato", "radice quadrata di 25"), never "²",
"√", "=" or LaTeX in the narration. Build the explanation step by step
(definition, formula, example with numbers, visual intuition, recap). The visual must be drawable with formulas,
function plots, motion trajectories, geometric figures (polygons, segments, circles, labels) or bullet lists.
Only ask for a plot when the narration is about a function or data, a trajectory only for motion."""

LESSON_USER = """Topic: {topic}
Audience: {audience}
Total length: about {seconds} seconds."""


def plan_lesson(topic: str, minutes: float, audience: str = "studenti delle superiori",
                generate: Callable | None = None) -> dict:
    from core.modules.sigma_creative_lab.video.production import _default_generate
    from core.modules.sigma_creative_lab.video.scene_kit import json_from
    gen = generate or _default_generate
    seconds = max(20, int(minutes * 60))
    chapters = max(2, min(12, round(seconds / 12)))
    answer = gen([{"role": "system", "content": LESSON_SYSTEM.replace("{chapters}", str(chapters))},
                  {"role": "user", "content": LESSON_USER.format(topic=topic.strip(), audience=audience,
                                                                 seconds=seconds)}], 4000)
    plan = json_from(answer)
    items = [c for c in plan.get("chapters") or [] if isinstance(c, dict) and str(c.get("narration", "")).strip()]
    if not items:
        raise ValueError("il modello non ha scritto capitoli validi")
    return {"title": str(plan.get("title") or topic), "chapters": items}
