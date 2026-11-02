"""Frasi e orchestrazioni distinte, mantenendo l'atmosfera della scena."""

import math

SCORE_REVISION = 3
MAX_CUE_SECONDS = 96.0
ARRANGEMENTS = (
    "expressive piano melody answered by warm strings, flowing harmonic development",
    "clarinet and bassoon dialogue with lyrical string counterpoint, changing musical phrases",
    "singing violins and cello countermelody, harp transitions, evolving orchestral dynamics",
    "woodwind melody with delicate piano responses, contrasting phrases and fresh harmonies",
    "warm French horn theme with strings and flute responses, melodic development",
    "solo cello and piano dialogue opening into chamber strings, expressive phrasing",
    "flute and oboe exchanges over warm strings, contrasting melodic sections",
    "chamber orchestra with piano flourishes and lyrical winds, varied melodic development",
)


def plan_cues(moods: list[dict]) -> list[dict]:
    cues = []
    previous_end = None
    for mood in moods:
        if mood.get("needs_review") and not mood.get("edited"):
            raise ValueError("Atmosfera musicale ripetitiva o incompleta: verificare le sequenze prima di comporre")
        start, end = float(mood["start"]), float(mood["end"])
        tags = str(mood.get("tags") or "").strip()
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end and tags):
            raise ValueError("Sequenza musicale priva di durata o atmosfera valide")
        if previous_end is not None and abs(start - previous_end) > 0.02:
            raise ValueError("Le sequenze musicali devono essere contigue")
        count = max(1, math.ceil((end - start) / MAX_CUE_SECONDS))
        for k in range(count):
            a = start + (end - start) * k / count
            b = start + (end - start) * (k + 1) / count
            cues.append({"start": a, "end": b, "tags": tags,
                         "arrangement": ARRANGEMENTS[len(cues) % len(ARRANGEMENTS)]})
        previous_end = end
    return cues
