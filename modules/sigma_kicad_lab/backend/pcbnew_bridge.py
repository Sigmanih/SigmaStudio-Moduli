# ==============================================================================
# sigma_kicad_lab/pcbnew_bridge.py — L'API Python di KiCad, da Sigma Studio
# ==============================================================================
"""Creare schede e aggiungere componenti veri, usando KiCad invece di imitarlo.

`pcb_writer.py` modifica i file `.kicad_pcb` facendo chirurgia sul testo: va
bene per spostare un footprint o tracciare una pista, e non basta per aggiungere
un componente. Un footprint vero ha pad, forme, maschera e serigrafia che stanno
in una libreria — inventarli produce un file che KiCad apre e che nessuno puo'
fabbricare. Le 155 librerie sono li'; questo modulo le usa.

**Perche' un sottoprocesso.** `import pcbnew` funziona soltanto dentro
l'interprete che KiCad si porta dietro. Nel Python di Sigma Studio non esiste e
non si puo' installare. Ogni chiamata qui lancia `pcbnew_worker.py` con
quell'interprete, gli passa un comando in JSON e ne rilegge una riga JSON — la
stessa forma che `kicad_cli.py` usa gia' per la riga di comando.

**Perche' il lavoratore e' un file vero.** Il primo tentativo lo costruiva come
stringhe Python dentro Python, una riga per volta. Ogni riga andava quotata a
mano e una virgola mancante rompeva tutto: si sono persi turni su errori di
sintassi che non avevano niente a che fare con KiCad. Un file vero lo legge un
editor e lo controlla un linter.

Nessuna funzione solleva eccezioni: tornano sempre un dizionario con `ok`, e
`errore` quando qualcosa non va.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)

MARCATORE = "@@SIGMA_JSON@@"

#: Un KiCad che si pianta non deve appendere Sigma Studio. La ricerca su 155
#: librerie e' l'operazione piu' lenta e sta ampiamente dentro questo limite.
TIMEOUT = 120

#: Dove cercare l'interprete di KiCad, in ordine. Non si scrive a mano un
#: percorso solo: chi installa KiCad altrove deve poterlo usare lo stesso.
_CANDIDATI_PYTHON = (
    r"C:\Program Files\KiCad\10.0\bin\python.exe",
    r"C:\Program Files\KiCad\9.0\bin\python.exe",
    r"C:\Program Files\KiCad\8.0\bin\python.exe",
    "/usr/lib/kicad/bin/python3",
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
)

_CANDIDATI_LIBRERIE = (
    r"C:\Program Files\KiCad\10.0\share\kicad\footprints",
    r"C:\Program Files\KiCad\9.0\share\kicad\footprints",
    r"C:\Program Files\KiCad\8.0\share\kicad\footprints",
    "/usr/share/kicad/footprints",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
)

_cache: Dict[str, Optional[str]] = {"python": None, "librerie": None}


def _trova_python() -> Optional[Path]:
    """L'interprete di KiCad: variabile d'ambiente, poi i posti noti."""
    if _cache["python"]:
        return Path(_cache["python"])
    dalla_env = os.environ.get("KICAD_PYTHON")
    candidati = ([dalla_env] if dalla_env else []) + list(_CANDIDATI_PYTHON)
    for c in candidati:
        if c and Path(c).is_file():
            _cache["python"] = c
            return Path(c)
    return None


def _trova_librerie() -> Optional[Path]:
    """La cartella dei footprint di sistema.

    `pcbnew.GetFootprintLibraries()` restituisce zero in un interprete
    autonomo: la tabella delle librerie appartiene alla configurazione
    dell'utente e non viene caricata. Le `.pretty` si aprono per percorso, e
    quello si trova sul disco.
    """
    if _cache["librerie"]:
        return Path(_cache["librerie"])
    dalla_env = os.environ.get("KICAD_FOOTPRINTS")
    candidati = ([dalla_env] if dalla_env else []) + list(_CANDIDATI_LIBRERIE)
    for c in candidati:
        if c and Path(c).is_dir():
            _cache["librerie"] = c
            return Path(c)
    return None


def _worker() -> Path:
    return Path(__file__).with_name("pcbnew_worker.py")


def _esegui(comando: str, argomenti: Dict[str, Any] = None,
            timeout: int = TIMEOUT) -> Dict[str, Any]:
    """Lancia un comando nel Python di KiCad e ne rilegge il risultato."""
    interprete = _trova_python()
    if interprete is None:
        return {"ok": False,
                "errore": ("Interprete Python di KiCad non trovato. Installa KiCad "
                           "8 o successivo, oppure indica il percorso nella "
                           "variabile d'ambiente KICAD_PYTHON.")}
    worker = _worker()
    if not worker.is_file():
        return {"ok": False, "errore": f"Lavoratore mancante: {worker}"}

    richiesta = json.dumps({"comando": comando, "argomenti": argomenti or {}})
    try:
        esito = subprocess.run(
            [str(interprete), str(worker)],
            input=richiesta, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "errore": f"'{comando}' non ha risposto entro {timeout}s."}
    except OSError as exc:
        return {"ok": False, "errore": f"Avvio fallito: {exc}"}

    stdout = esito.stdout or ""
    indice = stdout.rfind(MARCATORE)
    if indice < 0:
        # Senza marcatore non c'e' risultato: quasi sempre il lavoratore e'
        # morto prima di stamparlo, e la ragione sta su stderr.
        return {"ok": False,
                "errore": ("Nessun risultato dal lavoratore KiCad "
                           f"(uscita {esito.returncode})."),
                "stderr": (esito.stderr or "")[-600:],
                "stdout": stdout[-400:]}

    try:
        corpo = json.loads(stdout[indice + len(MARCATORE):].strip())
    except ValueError as exc:
        return {"ok": False, "errore": f"Risposta non interpretabile: {exc}"}
    if not isinstance(corpo, dict):
        return {"ok": False, "errore": "Il lavoratore non ha restituito un oggetto."}
    return corpo


# --- l'interfaccia pubblica ----------------------------------------------------

def disponibile() -> Dict[str, Any]:
    """C'e' KiCad? Che versione di pcbnew? Dove sono le librerie?"""
    interprete = _trova_python()
    librerie = _trova_librerie()
    if interprete is None:
        return {"ok": False, "python_kicad": None, "cartella_librerie": None,
                "errore": ("Interprete Python di KiCad non trovato. Imposta "
                           "KICAD_PYTHON se KiCad e' installato altrove.")}
    esito = _esegui("versione")
    return {**esito,
            "python_kicad": str(interprete),
            "cartella_librerie": str(librerie) if librerie else None}


def elenca_librerie() -> Dict[str, Any]:
    """I nomi delle librerie di footprint installate."""
    librerie = _trova_librerie()
    if librerie is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    return _esegui("elenca_librerie", {"cartella_librerie": str(librerie)})


def cerca_footprint(query: str, limite: int = 20,
                    libreria: str = "") -> Dict[str, Any]:
    """Cerca un footprint per sottostringa, in una libreria o in tutte."""
    librerie = _trova_librerie()
    if librerie is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    argomenti = {"cartella_librerie": str(librerie),
                 "query": query, "limite": limite}
    if libreria:
        argomenti["libreria"] = libreria
    return _esegui("cerca_footprint", argomenti)


def crea_scheda(percorso: str, larghezza_mm: float, altezza_mm: float,
                net: Optional[List[str]] = None,
                sovrascrivi: bool = False) -> Dict[str, Any]:
    """Crea un `.kicad_pcb` nuovo, col contorno e le net dichiarate.

    Attenzione a `net`: KiCad non salva le net che nessun pad usa, quindi
    riaprendo il file quelle dichiarate qui e rimaste vuote non ci sono piu'.
    Non e' un difetto — una net senza connessioni non e' informazione di
    progetto. Il risultato riporta `net_nel_file` e `net_non_persistite` per
    non lasciare il chiamante a credere il contrario.
    """
    return _esegui("crea_scheda", {
        "percorso": str(percorso), "larghezza_mm": larghezza_mm,
        "altezza_mm": altezza_mm, "net": net or [],
        "sovrascrivi": bool(sovrascrivi)})


def aggiungi_componente(percorso: str, libreria: str, footprint: str,
                        riferimento: str, valore: str = "",
                        x_mm: float = 0.0, y_mm: float = 0.0,
                        rotazione: float = 0.0,
                        net_per_pad: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Piazza un componente VERO, preso dalla libreria, con le net sui pad.

    `net_per_pad` e' {"1": "GND", "2": "+3V3"}: le net che non esistono ancora
    sulla scheda vengono create, perche' rifiutare il componente per una net
    mancante costringerebbe a dichiararle tutte in anticipo.
    """
    librerie = _trova_librerie()
    if librerie is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    return _esegui("aggiungi_componente", {
        "cartella_librerie": str(librerie), "percorso": str(percorso),
        "libreria": libreria, "footprint": footprint,
        "riferimento": riferimento, "valore": valore,
        "x_mm": x_mm, "y_mm": y_mm, "rotazione": rotazione,
        "net_per_pad": net_per_pad or {}})


def leggi_scheda(percorso: str) -> Dict[str, Any]:
    """Contorno, componenti coi loro pad, piste, via e net."""
    return _esegui("leggi_scheda", {"percorso": str(percorso)})
