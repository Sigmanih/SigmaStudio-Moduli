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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)

MARCATORE = "@@SIGMA_JSON@@"

#: Un KiCad che si pianta non deve appendere Sigma Studio. La ricerca su 155
#: librerie e' l'operazione piu' lenta e sta ampiamente dentro questo limite.
TIMEOUT = 120

#: Quanto vale l'indice dei footprint prima di essere ricostruito. Le librerie
#: di KiCad cambiano quando si aggiorna KiCad, non durante una sessione di
#: lavoro: un giorno e' una vita per la cache e un istante per il rischio di
#: proporre un componente che non c'e' piu'. Il file su disco porta con se' la
#: cartella da cui viene, quindi un KiCad aggiornato o spostato lo invalida da
#: solo invece di servire un elenco della versione precedente.
TTL_INDICE = 24 * 3600

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


# --- l'indice dei footprint ----------------------------------------------------
#
# Cercare un footprint costava 5,6 secondi: ogni ricerca riapriva le 155 librerie
# dentro l'interprete di KiCad. L'indice le legge una volta sola, e da li' in poi
# cercare e' un filtro in memoria. Sta in `var/` perche' e' stato ricreabile:
# cancellarlo non perde lavoro, costa una ricostruzione.

#: L'indice tenuto in memoria, con la cartella da cui viene e quando e' stato
#: letto. Tenerne uno solo e' voluto: la cartella delle librerie non cambia
#: dentro un processo, e due indici diversi a confronto sono un bug in attesa.
_indice: Dict[str, Any] = {"cartella": None, "letto_il": 0.0, "dati": None}


def _file_indice() -> Path:
    """Dove l'indice sopravvive al riavvio del server."""
    from core.paths import var_dir
    return var_dir() / "cache" / "kicad" / "indice_footprint.json"


def _indice_da_disco(cartella: str) -> Optional[Dict[str, Any]]:
    """L'indice salvato, se e' della stessa cartella e non e' scaduto."""
    percorso = _file_indice()
    try:
        if not percorso.is_file():
            return None
        with percorso.open("r", encoding="utf-8") as f:
            salvato = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("[KiCad] Indice su disco illeggibile: %s", exc)
        return None
    if not isinstance(salvato, dict) or salvato.get("cartella") != cartella:
        return None
    if time.time() - float(salvato.get("letto_il") or 0) > TTL_INDICE:
        return None
    dati = salvato.get("indice")
    return dati if isinstance(dati, dict) and dati else None


def _salva_indice(cartella: str, dati: Dict[str, Any]) -> None:
    """Scrive l'indice per il prossimo avvio. Non solleva mai.

    Un indice che non si riesce a salvare e' un indice che si ricostruira': non
    e' una ragione per far fallire la ricerca che l'ha appena prodotto. La
    scrittura passa da un file temporaneo e da `os.replace`, che e' atomico:
    due processi che costruiscono l'indice insieme scrivevano lo stesso file
    a pezzi alterni, e il risultato erano due JSON incollati che nessuno
    riusciva piu' a leggere.
    """
    percorso = _file_indice()
    temporaneo = percorso.parent / (percorso.name + ".tmp")
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        with temporaneo.open("w", encoding="utf-8") as f:
            json.dump({"cartella": cartella, "letto_il": time.time(),
                       "indice": dati}, f, ensure_ascii=False)
        os.replace(temporaneo, percorso)
    except OSError as exc:
        log.warning("[KiCad] Indice non salvato in %s: %s", percorso, exc)
        try:
            temporaneo.unlink(missing_ok=True)
        except OSError:
            pass


def _indice_in_memoria(cartella: str) -> Optional[Dict[str, Any]]:
    if _indice["dati"] and _indice["cartella"] == cartella:
        if time.time() - float(_indice["letto_il"]) <= TTL_INDICE:
            return _indice["dati"]
    return None


def indice_footprint(forza: bool = False, costruisci: bool = True) -> Dict[str, Any]:
    """L'elenco completo dei footprint, dalla memoria, dal disco o da KiCad.

    L'ordine e' quello dei costi: memoria (microsecondi), disco (millisecondi),
    KiCad (decine di secondi). `costruisci=False` serve a chi vuole solo sapere
    se un indice c'e' gia' — l'elenco delle librerie per una tendina, per
    esempio, che non deve far partire una scansione completa.
    """
    cartella = _trova_librerie()
    if cartella is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    chiave = str(cartella)

    if not forza:
        dati = (_indice_in_memoria(chiave) or _indice_da_disco(chiave))
        if dati:
            _indice.update({"cartella": chiave, "letto_il": time.time(),
                            "dati": dati})
            return _risposta_indice(dati, da_cache=True)

    if not costruisci:
        return {"ok": False, "errore": "Nessun indice dei footprint disponibile."}

    esito = _esegui("indice_footprint", {"cartella_librerie": chiave})
    if not esito.get("ok"):
        return esito

    dati = esito.get("indice") or {}
    _indice.update({"cartella": chiave, "letto_il": time.time(), "dati": dati})
    _salva_indice(chiave, dati)
    log.info("[KiCad] Indice dei footprint costruito: %d voci in %d librerie.",
             esito.get("totale") or 0, esito.get("librerie") or 0)
    return {**_risposta_indice(dati, da_cache=False),
            "librerie_lette": esito.get("librerie")}


def _risposta_indice(dati: Dict[str, Any], da_cache: bool) -> Dict[str, Any]:
    return {"ok": True,
            "totale": sum(len(v) for v in dati.values()),
            "librerie": len(dati),
            "indice": dati,
            "da_cache": da_cache}


def _filtra_indice(indice: Dict[str, Any], query: str, limite: int,
                   libreria: str = "") -> Dict[str, Any]:
    """Cerca nell'indice, e ordina per pertinenza invece che per alfabeto.

    Chi scrive `R_0805` vuole `R_0805_2012Metric`, non una variante HandSolder
    che comincia per le stesse lettere e continua per altre trenta: a pari
    merito vince il nome piu' corto.
    """
    cercato = (query or "").strip().lower()
    voci = []
    for nome_lib, nomi in indice.items():
        if libreria and nome_lib != libreria:
            continue
        for nome in nomi:
            basso = nome.lower()
            if cercato and cercato not in basso:
                continue
            if not cercato:
                rilevanza = 3
            elif basso == cercato:
                rilevanza = 0
            elif basso.startswith(cercato):
                rilevanza = 1
            elif basso.split("_")[0] == cercato:
                rilevanza = 2
            else:
                rilevanza = 3
            voci.append((rilevanza, len(nome), nome_lib, nome))

    voci.sort()
    limite = max(1, min(int(limite or 20), 500))
    trovati = [{"libreria": nome_lib, "footprint": nome}
               for _, _, nome_lib, nome in voci]
    return {"ok": True, "totale": len(trovati), "risultati": trovati[:limite],
            "troncato": len(trovati) > limite, "da_indice": True}


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
    """I nomi delle librerie di footprint installate.

    Se l'indice esiste gia' le librerie sono le sue chiavi, e non serve far
    parlare KiCad per rileggerle. Non lo costruisce: una tendina non deve far
    partire una scansione di decine di secondi.
    """
    letto = indice_footprint(costruisci=False)
    if letto.get("ok"):
        nomi = sorted(letto["indice"])
        return {"ok": True, "totale": len(nomi), "librerie": nomi,
                "da_indice": True}

    librerie = _trova_librerie()
    if librerie is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    return _esegui("elenca_librerie", {"cartella_librerie": str(librerie)})


def cerca_footprint(query: str, limite: int = 20,
                    libreria: str = "") -> Dict[str, Any]:
    """Cerca un footprint per sottostringa, in una libreria o in tutte.

    Passa dall'indice: la ricerca diretta riapre le 155 librerie a ogni
    chiamata (5,6 s misurati su KiCad 10) e la differenza fra le due strade e'
    quella fra una risposta e un'attesa. Se l'indice non si riesce a costruire
    la ricerca diretta resta disponibile: lenta e corretta batte veloce e
    muta.
    """
    indice = indice_footprint()
    if indice.get("ok"):
        trovato = _filtra_indice(indice["indice"], query, limite, libreria)
        trovato["da_cache"] = bool(indice.get("da_cache"))
        return trovato
    if not indice.get("errore"):
        return {"ok": False, "errore": "Indice dei footprint non disponibile."}

    librerie = _trova_librerie()
    if librerie is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    argomenti = {"cartella_librerie": str(librerie),
                 "query": query, "limite": limite}
    if libreria:
        argomenti["libreria"] = libreria
    esito = _esegui("cerca_footprint", argomenti)
    esito["da_indice"] = False
    return esito


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
                        net_per_pad: Optional[Dict[str, str]] = None,
                        lato: str = "") -> Dict[str, Any]:
    """Piazza un componente VERO, preso dalla libreria, con le net sui pad.

    `net_per_pad` e' {"1": "GND", "2": "+3V3"}: le net che non esistono ancora
    sulla scheda vengono create, perche' rifiutare il componente per una net
    mancante costringerebbe a dichiararle tutte in anticipo.

    `lato` vale "top" (predefinito) o "bottom", e sta **in fondo** all'elenco
    dei parametri apposta: chi chiama passa le net per posizione, e infilare un
    parametro nuovo in mezzo manda il dizionario delle net dentro il lato —
    senza un errore, con i pad che restano scollegati.
    """
    librerie = _trova_librerie()
    if librerie is None:
        return {"ok": False, "errore": "Cartella dei footprint non trovata."}
    return _esegui("aggiungi_componente", {
        "cartella_librerie": str(librerie), "percorso": str(percorso),
        "libreria": libreria, "footprint": footprint,
        "riferimento": riferimento, "valore": valore,
        "x_mm": x_mm, "y_mm": y_mm, "rotazione": rotazione,
        "lato": lato,
        "net_per_pad": net_per_pad or {}})


def leggi_scheda(percorso: str) -> Dict[str, Any]:
    """Contorno, componenti coi loro pad, piste, via e net."""
    return _esegui("leggi_scheda", {"percorso": str(percorso)})
