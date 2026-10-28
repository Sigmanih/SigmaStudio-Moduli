"""Sceglie, tra le figure intere generate, quella che TRELLIS e il rig digeriscono meglio.

Gira nel venv di TRELLIS (serve rembg). Il criterio e' quello che decideva i
difetti dei personaggi: braccia staccate dai fianchi. Sulla sagoma ritagliata,
nelle righe tra il 38% e il 62% dell'altezza della figura, si contano i tratti
pieni: tre tratti (braccio, busto, braccio) vogliono dire braccia libere; il
punteggio premia le righe cosi' e la larghezza dello spazio vuoto.

    <venv>/python scegli_variante.py immagine1.png immagine2.png ...

Stampa su stdout una riga JSON: {"scelta": percorso, "punteggi": {...}}.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")


def punteggio(mask) -> float:
    import numpy as np

    righe = np.where(mask.any(axis=1))[0]
    colonne = np.where(mask.any(axis=0))[0]
    if len(righe) == 0:
        return 0.0
    alto, basso = righe[0], righe[-1]
    larghezza = max(1, colonne[-1] - colonne[0])
    staccate, vuoto = 0, 0.0
    fascia = range(int(alto + 0.38 * (basso - alto)), int(alto + 0.62 * (basso - alto)))
    for y in fascia:
        riga = mask[y].astype(np.int8)
        bordi = np.flatnonzero(np.diff(riga))
        tratti = (len(bordi) + (riga[0] == 1) + (riga[-1] == 1)) // 2
        if tratti >= 3:
            staccate += 1
            # Spazi interni: tra la fine di un tratto e l'inizio del successivo
            interni = np.diff(bordi)[1::2]
            vuoto += float(interni.min()) / larghezza if len(interni) else 0.0
    n = max(1, len(fascia))
    return staccate / n + vuoto / n


def main() -> int:
    import numpy as np
    import rembg
    from PIL import Image

    sessione = rembg.new_session("birefnet-general")
    punteggi = {}
    for percorso in sys.argv[1:]:
        ritaglio = rembg.remove(Image.open(percorso).convert("RGB"), session=sessione)
        mask = np.array(ritaglio)[:, :, 3] > 128
        punteggi[percorso] = round(punteggio(mask), 4)
    scelta = max(punteggi, key=punteggi.get) if punteggi else ""
    print(json.dumps({"scelta": scelta, "punteggi": punteggi}))
    return 0 if scelta else 1


if __name__ == "__main__":
    sys.exit(main())
