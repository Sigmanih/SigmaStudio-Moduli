# ==============================================================================
# core/training/benchmark_store.py — Persistenza dei risultati di benchmark
# Sigma Studio v7 — Training Lab Sub-package
# ==============================================================================
"""Archivio su disco per gli esiti dei singoli quesiti di un run di benchmark.

I risultati stavano dentro l'indice dei job: ogni quesito completato riscriveva
l'intero file, quindi un run integrale (oltre 200.000 item) ricopiava un JSON che
cresceva a ogni passo, e la lista job restituiva alla UI megabyte di dettaglio a
ogni polling.

Qui il dettaglio vive per job in tre pezzi:

* ``<job>.jsonl``     — un esito per riga, scritto in append
* ``<job>.idx.json``  — offset in byte + verdetto + suite di ogni riga
* l'indice dei job    — solo metadati e metriche aggregate

L'indice laterale e' cio' che rende praticabile la UI: filtrare per verdetto o
suite e impaginare tocca solo il sidecar, poi si leggono le sole righe servite.
"""

from __future__ import annotations

import json
import os
import threading
import time

from core.logger import get_logger
from core.modules.sigma_benchmark_lab import paths as module_paths

log = get_logger(__name__)

RUNS_DIR = str(module_paths.BENCHMARK_RUNS_DIR)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(job_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(job_id, threading.Lock())


def _paths(job_id: str) -> tuple[str, str]:
    safe = "".join(c for c in job_id if c.isalnum() or c in "-_")
    return (
        os.path.join(RUNS_DIR, f"{safe}.jsonl"),
        os.path.join(RUNS_DIR, f"{safe}.idx.json"),
    )


def _ensure_dir() -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)


#: L'indice del run in corso, tenuto in memoria. Prima ogni quesito completato
#: rileggeva e riscriveva l'intero sidecar: costo quadratico sulla lunghezza del
#: run, e — su Windows — una collisione continua con la UI che lo sta leggendo
#: per il polling. `os.replace` vuole il permesso di cancellare la destinazione,
#: e un lettore aperto glielo nega: e' il `WinError 5` che interrompeva il run.
_index_cache: dict[str, list[list]] = {}
#: Da quanti esiti l'indice non viene scritto su disco, e da quanto tempo.
_index_dirty: dict[str, int] = {}
_index_written_at: dict[str, float] = {}

#: Ogni quanti esiti, e ogni quanti secondi, riversare l'indice. La UI puo'
#: leggerlo in ritardo di un secondo senza che nessuno se ne accorga; non puo'
#: leggerlo mentre viene sostituito.
_INDEX_FLUSH_EVERY = 25
_INDEX_FLUSH_SECONDS = 2.0

#: Tentativi di sostituzione del file indice prima di arrendersi. Su Windows il
#: fallimento e' transitorio quasi sempre: un lettore, l'antivirus o l'indicizza-
#: tore tiene il file per qualche millisecondo.
_REPLACE_TENTATIVI = 8
_REPLACE_ATTESA_S = 0.05


def _load_index(job_id: str) -> list[list]:
    cached = _index_cache.get(job_id)
    if cached is not None:
        return cached
    _, idx_path = _paths(job_id)
    if not os.path.exists(idx_path):
        return []
    try:
        with open(idx_path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("entries", [])
    except Exception as err:
        log.warning("Indice risultati di %s illeggibile: %s", job_id, err)
        return []


def _replace_with_retry(tmp: str, destination: str) -> None:
    """`os.replace`, con la pazienza che Windows richiede.

    Su NTFS la sostituzione fallisce con "Accesso negato" finche' qualcuno tiene
    aperto il file di destinazione — e qualcuno lo tiene aperto praticamente
    sempre, perche' la UI lo interroga durante il run. Non e' un errore di
    permessi: e' una condizione di corsa che si risolve da sola in millisecondi.
    """
    ultimo: Exception | None = None
    for tentativo in range(_REPLACE_TENTATIVI):
        try:
            os.replace(tmp, destination)
            return
        except PermissionError as err:
            ultimo = err
            time.sleep(_REPLACE_ATTESA_S * (tentativo + 1))
    raise ultimo if ultimo else OSError("sostituzione non riuscita")


def _save_index(job_id: str, entries: list[list], force: bool = True) -> None:
    """Scrive il sidecar, con un freno quando il run e' in corso."""
    _index_cache[job_id] = entries
    if not force:
        _index_dirty[job_id] = _index_dirty.get(job_id, 0) + 1
        scaduto = (time.time() - _index_written_at.get(job_id, 0.0)) >= _INDEX_FLUSH_SECONDS
        if _index_dirty[job_id] < _INDEX_FLUSH_EVERY and not scaduto:
            return

    _, idx_path = _paths(job_id)
    tmp = idx_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"entries": entries}, fh)
        _replace_with_retry(tmp, idx_path)
    except Exception as err:
        # Il sidecar si puo' ricostruire dal file degli esiti in una passata:
        # non scriverlo adesso e' un rallentamento, non una perdita, e non deve
        # fermare un run lungo ore.
        log.warning("Indice di %s non scritto (%s); si riprovera'.", job_id, err)
        return
    _index_dirty[job_id] = 0
    _index_written_at[job_id] = time.time()


def flush_index(job_id: str) -> None:
    """Forza la scrittura del sidecar e libera la copia in memoria."""
    entries = _index_cache.get(job_id)
    if entries is not None:
        with _lock_for(job_id):
            _save_index(job_id, entries, force=True)
            _index_cache.pop(job_id, None)
            _index_dirty.pop(job_id, None)
            _index_written_at.pop(job_id, None)


def append_results(job_id: str, results: list[dict]) -> None:
    """Aggiunge esiti in coda al run, aggiornando l'indice laterale.

    Scrive a blocchi: il worker accumula gli esiti completati e li versa qui,
    cosi' il costo per quesito e' un append e non una riscrittura.
    """
    if not results:
        return
    _ensure_dir()
    data_path, _ = _paths(job_id)
    with _lock_for(job_id):
        entries = _load_index(job_id)
        offset = os.path.getsize(data_path) if os.path.exists(data_path) else 0
        # newline="\n" e' obbligatorio: con la traduzione automatica di Windows
        # ogni \n diventa \r\n sul disco, mentre l'indice conta un byte solo, e
        # gli offset finirebbero fuori posto già dalla seconda riga.
        with open(data_path, "a", encoding="utf-8", newline="\n") as fh:
            for result in results:
                line = json.dumps(result, ensure_ascii=False)
                fh.write(line + "\n")
                entries.append([
                    offset,
                    result.get("verdict", "fail"),
                    result.get("suite", ""),
                ])
                offset += len(line.encode("utf-8")) + 1
        # Gli esiti sono gia' su disco: l'indice puo' seguire con calma, e in
        # caso di interruzione si ricostruisce da loro con una sola passata.
        _save_index(job_id, entries, force=False)


def count_results(job_id: str) -> int:
    return len(_load_index(job_id))


def verdict_counts(job_id: str) -> dict[str, int]:
    """Conteggio per verdetto letto dal solo indice laterale."""
    counts: dict[str, int] = {}
    for entry in _load_index(job_id):
        verdict = entry[1] if len(entry) > 1 else "fail"
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def suite_breakdown(job_id: str) -> dict[str, dict[str, int]]:
    """Passati/totali per suite, per il riepilogo in testa al pannello."""
    out: dict[str, dict[str, int]] = {}
    for entry in _load_index(job_id):
        verdict = entry[1] if len(entry) > 1 else "fail"
        suite = (entry[2] if len(entry) > 2 else "") or "generale"
        stats = out.setdefault(suite, {"passed": 0, "failed": 0, "review": 0, "total": 0})
        stats["total"] += 1
        if verdict == "pass":
            stats["passed"] += 1
        elif verdict == "fail":
            stats["failed"] += 1
        else:
            stats["review"] += 1
    return out


def _read_at(data_path: str, offsets: list[int]) -> list[dict]:
    """Legge solo le righe richieste, saltando direttamente ai loro offset.

    Apertura binaria: `seek` in modalita' testo non lavora in byte, quindi con
    un offset calcolato in byte atterrerebbe a metà riga.
    """
    out: list[dict] = []
    if not os.path.exists(data_path):
        return out
    with open(data_path, "rb") as fh:
        for offset in offsets:
            try:
                fh.seek(offset)
                line = fh.readline().decode("utf-8", errors="replace")
                if line.strip():
                    out.append(json.loads(line))
            except Exception as err:
                log.debug("Riga a offset %s non leggibile: %s", offset, err)
    return out


def read_all_results(job_id: str) -> list[dict]:
    """Legge tutti gli esiti memorizzati per un dato job."""
    data_path, _ = _paths(job_id)
    if not os.path.exists(data_path):
        return []
    out = []
    with _lock_for(job_id):
        with open(data_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    return out


def replace_job_results(job_id: str, results: list[dict]) -> None:
    """Sostituisce interamente gli esiti di un job riscrivendo il file e l'indice laterale."""
    _ensure_dir()
    data_path, _ = _paths(job_id)
    with _lock_for(job_id):
        entries: list[list] = []
        offset = 0
        with open(data_path, "w", encoding="utf-8", newline="\n") as fh:
            for idx, res in enumerate(results):
                res["index"] = idx
                line = json.dumps(res, ensure_ascii=False)
                fh.write(line + "\n")
                verdict = res.get("verdict", "pass" if res.get("passed") else "fail")
                suite = res.get("suite", "")
                entries.append([offset, verdict, suite])
                offset += len(line.encode("utf-8")) + 1
        _save_index(job_id, entries, force=True)
        _index_cache[job_id] = entries
        _index_dirty[job_id] = 0
        _index_written_at[job_id] = time.time()


def rebuild_index(job_id: str) -> int:
    """Ricostruisce l'indice laterale scorrendo il file degli esiti.

    Rete di sicurezza: se gli offset non combaciano piu' col contenuto (indice
    scritto da una versione precedente, scrittura interrotta a metà), il
    dettaglio resta comunque recuperabile con una singola passata sequenziale.
    """
    data_path, _ = _paths(job_id)
    if not os.path.exists(data_path):
        return 0
    entries: list[list] = []
    with _lock_for(job_id):
        with open(data_path, "rb") as fh:
            offset = 0
            for raw in fh:
                text = raw.decode("utf-8", errors="replace")
                if text.strip():
                    try:
                        item = json.loads(text)
                        entries.append([offset, item.get("verdict", "fail"), item.get("suite", "")])
                    except json.JSONDecodeError:
                        log.debug("Riga non valida a offset %s in %s", offset, job_id)
                offset += len(raw)
        _save_index(job_id, entries)
    log.info("Indice risultati di %s ricostruito: %d esiti.", job_id, len(entries))
    return len(entries)


def _index_is_sound(job_id: str, entries: list[list]) -> bool:
    """Controlla a campione che gli offset dell'indice puntino a righe valide."""
    if not entries:
        return True
    data_path, _ = _paths(job_id)
    probes = {0, len(entries) // 2, len(entries) - 1}
    sample = [entries[i][0] for i in sorted(probes) if 0 <= i < len(entries)]
    return len(_read_at(data_path, sample)) == len(sample)


def _sound_index(job_id: str) -> list[list]:
    """Indice del job, ricostruito al volo se risulta incoerente."""
    entries = _load_index(job_id)
    if _index_is_sound(job_id, entries):
        return entries
    rebuild_index(job_id)
    return _load_index(job_id)


def read_page(
    job_id: str,
    page: int = 1,
    page_size: int = 15,
    verdict: str = "all",
    suite: str = "all",
    query: str = "",
) -> dict:
    """Restituisce una pagina di esiti filtrata per verdetto, suite e testo.

    `verdict` accetta anche il gruppo ``review``, che raccoglie i quesiti da
    valutare a parte (risposta duplice, non interpretabile o in errore).
    """
    from core.modules.sigma_benchmark_lab.answer_parser import REVIEW_VERDICTS

    data_path, _ = _paths(job_id)
    entries = _sound_index(job_id)

    selected: list[int] = []
    for entry in entries:
        entry_verdict = entry[1] if len(entry) > 1 else "fail"
        entry_suite = (entry[2] if len(entry) > 2 else "") or ""
        if verdict == "review":
            if entry_verdict not in REVIEW_VERDICTS:
                continue
        elif verdict not in ("all", ""):
            if entry_verdict != verdict:
                continue
        if suite not in ("all", ""):
            norm_target = suite.lower().replace("-", "_").replace(" ", "_")
            norm_entry = str(entry_suite or "").lower().replace("-", "_").replace(" ", "_")
            if norm_target != norm_entry:
                continue
        selected.append(entry[0])

    if query.strip():
        # La ricerca testuale non e' indicizzabile: si scorre l'insieme già
        # ristretto dai filtri, con un tetto per non bloccare la richiesta.
        needle = query.strip().lower()
        matched: list[int] = []
        for item, offset in zip(_read_at(data_path, selected[:20000]), selected[:20000]):
            haystack = " ".join(str(item.get(k, "")) for k in
                                ("prompt", "category", "given_answer", "correct_answer", "suite_name"))
            if needle in haystack.lower():
                matched.append(offset)
        selected = matched

    total = len(selected)
    page_size = max(1, min(int(page_size or 15), 200))
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), pages))
    window = selected[(page - 1) * page_size: page * page_size]

    return {
        "success": True,
        "job_id": job_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
        "results": _read_at(data_path, window),
    }


def get_evaluated_item_ids(job_id: str) -> set[str]:
    """Restituisce l'insieme degli ID o prompt dei quesiti già registrati in questo job."""
    data_path, _ = _paths(job_id)
    if not os.path.exists(data_path):
        return set()
    ids = set()
    with _lock_for(job_id):
        try:
            with open(data_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        try:
                            obj = json.loads(line)
                            if "id" in obj:
                                ids.add(str(obj["id"]))
                            elif "prompt" in obj:
                                ids.add(str(obj["prompt"]))
                        except Exception:
                            pass
        except Exception as err:
            log.warning("Lettura item_ids di %s non riuscita: %s", job_id, err)
    return ids


def read_review_queue(job_id: str, limit: int = 5000) -> list[dict]:
    """Tutti i quesiti in attesa di giudizio umano, per l'export dedicato."""
    from core.modules.sigma_benchmark_lab.answer_parser import REVIEW_VERDICTS

    data_path, _ = _paths(job_id)
    offsets = [
        entry[0] for entry in _sound_index(job_id)
        if (entry[1] if len(entry) > 1 else "fail") in REVIEW_VERDICTS
    ]
    return _read_at(data_path, offsets[:limit])


def delete_results(job_id: str) -> None:
    """Cancella dettaglio e indice di un job eliminato."""
    _index_cache.pop(job_id, None)
    _index_dirty.pop(job_id, None)
    _index_written_at.pop(job_id, None)
    for path in _paths(job_id):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as err:
            log.warning("Impossibile rimuovere %s: %s", path, err)
    with _locks_guard:
        _locks.pop(job_id, None)


def migrate_inline_results(job: dict) -> bool:
    """Sposta nello store i `test_results` ancora annidati in un vecchio job.

    I run salvati prima di questa separazione restano visibili senza conversioni
    manuali: al primo caricamento il dettaglio esce dall'indice e finisce nel
    file per job.
    """
    inline = job.get("test_results")
    if not inline:
        return False
    job_id = job.get("id", "")
    if not job_id:
        return False
    if count_results(job_id) == 0:
        from core.modules.sigma_benchmark_lab.answer_parser import grade_answer
        normalized = []
        for item in inline:
            if "verdict" not in item:
                # Gli esiti storici hanno solo un booleano: si rigiudicano col
                # parser attuale per allinearli alle nuove categorie.
                graded = grade_answer(item, item.get("given_answer", ""))
                item = {**item, **{k: graded[k] for k in ("verdict", "passed", "needs_review")},
                        "parsed": graded.get("parsed", {})}
            normalized.append(item)
        append_results(job_id, normalized)
        log.info("Migrati %d esiti del job %s nello store dedicato.", len(normalized), job_id)
    job.pop("test_results", None)
    return True
