"""Testo da far leggere alla voce: simboli matematici e formule detti a parole.

"c² = a² + b²" letto cosi' com'e' manda in tilt la sintesi vocale (in una
lezione di prova e' diventato "CGGVGVG" seguito da 17 secondi di parole
inventate). Prima di sintetizzare, i simboli diventano italiano parlato: stesse
regole che la chat usa per leggere le risposte (audioSpeech.js).
"""

from __future__ import annotations

import re

_SUPERSCRIPTS = {"²": " al quadrato", "³": " al cubo", "⁴": " alla quarta", "¹": "", "⁰": " alla zero"}

_RULES = [
    (r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r" \1 fratto \2 "),
    (r"\\sqrt\s*\{([^{}]*)\}", r" radice quadrata di \1 "),
    (r"\\(?:cdot|times)", " per "),
    (r"\\pi\b", " pi greco "),
    (r"\\(?:theta|vartheta)\b", " theta "), (r"\\alpha\b", " alfa "), (r"\\beta\b", " beta "),
    (r"\\Delta\b", " delta "), (r"\\(?:leq|le)\b", " minore o uguale a "), (r"\\(?:geq|ge)\b", " maggiore o uguale a "),
    (r"\\[a-zA-Z]+", " "), (r"[{}$\\]", " "),
    (r"√\s*\(([^()]*)\)", r" radice quadrata di \1 "), (r"√\s*(\w+)", r" radice quadrata di \1 "),
    (r"(\w)\s*\^\s*2\b", r"\1 al quadrato"), (r"(\w)\s*\^\s*3\b", r"\1 al cubo"),
    (r"(\w)\s*\^\s*\(?(-?\w+)\)?", r"\1 elevato alla \2"),
    (r"×|·", " per "), (r"÷", " diviso "), (r"±", " più o meno "),
    (r"≤", " minore o uguale a "), (r"≥", " maggiore o uguale a "), (r"≠", " diverso da "), (r"≈", " circa "),
    (r"π", " pi greco "), (r"θ", " theta "), (r"α", " alfa "), (r"β", " beta "), (r"Δ", " delta "), (r"°", " gradi"),
    (r"(\d)\s*\+\s*(\d)", r"\1 più \2"), (r"(\w)\s*\+\s*(\w)", r"\1 più \2"),
    (r"(\d)\s*[-−]\s*(\d)", r"\1 meno \2"),
    (r"(\d)\s*\*\s*(\d)", r"\1 per \2"),
    (r"(\d)\s*/\s*(\d)", r"\1 fratto \2"),
    (r"\b(\w)\s*/\s*(\w)\b", r"\1 fratto \2"),
    # Il trattino fra due termini brevi e' un meno; quello fra parole lunghe resta un inciso.
    (r"\b(\w{1,3})\s+[-−]\s+(\w{1,3})\b", r"\1 meno \2"),
    (r"\s*=\s*", " uguale a "),
    (r"(\d),(\d)", r"\1 virgola \2"),
    (r"\s{2,}", " "),
]


def to_spoken(text: str) -> str:
    out = str(text)
    for sym, words in _SUPERSCRIPTS.items():
        out = out.replace(sym, words)
    for pattern, repl in _RULES:
        out = re.sub(pattern, repl, out)
    # Una lettera isolata davanti a "al quadrato" si legge meglio scandita: "c al quadrato".
    return out.strip()


def plausible_duration(text: str, seconds: float) -> bool:
    """Una voce italiana sta fra ~1,3 e ~4,5 parole al secondo: fuori, ha inventato o saltato parole."""
    words = max(1, len(text.split()))
    rate = words / max(0.1, seconds)
    return 1.3 <= rate <= 4.5
