"""Controllo del parlato parola per parola.

Una parola rovinata dalla sintesi o dalla conversione vocale resta spesso
"giusta" per il testo trascritto, ma Whisper la riconosce con meno sicurezza:
nel dialogo del faro "guiderà" e' sceso da 0,99 a 0,66 dopo la conversione,
mentre le altre parole restavano a 1,00. Confrontare la confidenza prima e dopo
individua il tratto difettoso senza che nessuno debba ascoltarlo.
"""

from __future__ import annotations

import re
import unicodedata

#: Sotto questa confidenza una parola e' sospetta anche senza un riferimento.
MIN_P = 0.85
#: Calo rispetto al parlato di partenza oltre il quale la parola e' stata rovinata.
MAX_DROP = 0.10


def _norm(word: str) -> str:
    text = unicodedata.normalize("NFKD", word.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)))


def _overlap(a: dict, b: dict) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def damaged_words(words: list[dict], reference: list[dict] | None = None, min_p: float = MIN_P,
                  max_drop: float = MAX_DROP) -> list[dict]:
    """Parole sospette di `words`; con `reference` conta il calo rispetto all'originale.

    Con un riferimento una parola gia' incerta all'origine (un nome proprio, una
    parola poco comune) non viene segnalata: non e' colpa della conversione.
    """
    out = []
    for w in words:
        if not _norm(w.get("word", "")):
            continue
        p = float(w.get("p", 1.0))
        ref = None
        if reference:
            ref = max(reference, key=lambda r: _overlap(r, w), default=None)
            if ref is not None and _overlap(ref, w) <= 0:
                ref = None
        if ref is not None:
            bad = p < min_p and float(ref.get("p", 1.0)) - p > max_drop
        else:
            bad = p < min_p
        if bad:
            out.append({**w, "ref_p": None if ref is None else float(ref.get("p", 1.0))})
    return out


def regions(damaged: list[dict], pad: float = 0.06, merge_gap: float = 0.12) -> list[list[float]]:
    """Tratti da sostituire: le parole rovinate con un po' di margine, unite se vicine."""
    spans = sorted([max(0.0, w["start"] - pad), w["end"] + pad] for w in damaged)
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in merged]


def rank(words: list[dict], damaged: list[dict]) -> tuple:
    """Ordine fra tentativi: meno parole rovinate, poi la parola peggiore piu' alta."""
    worst = min((float(w.get("p", 1.0)) for w in words), default=0.0)
    return (-len(damaged), worst)
