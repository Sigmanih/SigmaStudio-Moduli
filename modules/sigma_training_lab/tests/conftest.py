# ==============================================================================
# tests/conftest.py — Contesto di esecuzione dei test del Training Lab
#
# Questi test vivono nel repository dei moduli ma esercitano il modulo cosi'
# com'e' *installato* dentro Sigma Studio: importano `core.modules.
# sigma_training_lab...`, cioe' i percorsi che esistono solo dopo
# l'installazione. Serve quindi che l'installazione di Sigma Studio sia su
# sys.path.
#
# Prima ogni file di test ci arrivava per conto suo con
#     sys.path.insert(0, str(Path(__file__).parent.parent))
# ripetuto in dieci file — e puntava alla cartella del modulo nel repository
# sorgente, dove `core` non esiste. Funzionava solo se pytest veniva lanciato
# con la directory di lavoro dentro Sigma Studio, e falliva in silenzio
# altrimenti: cinque file su undici erano fermi a un errore di collection, e
# nessuno se ne e' accorto per settimane. E' in quella finestra che il Training
# Lab ha smesso di vedere i propri job senza che un test lo segnalasse.
#
# La radice si cerca in tre modi, dal piu' esplicito al piu' tollerante:
#   1. la variabile d'ambiente SIGMA_HOME (la stessa che usa core/paths.py);
#   2. la directory di lavoro e i suoi genitori;
#   3. le installazioni adiacenti al repository dei moduli.
# ==============================================================================
import os
import sys
from pathlib import Path

import pytest

_MARKER = "sigma_server.py"


def _looks_like_sigma_home(candidate: Path) -> bool:
    return (candidate / _MARKER).is_file() and (candidate / "core").is_dir()


def _find_sigma_home() -> Path | None:
    env_home = os.environ.get("SIGMA_HOME", "").strip()
    if env_home:
        candidate = Path(env_home).expanduser().resolve()
        if _looks_like_sigma_home(candidate):
            return candidate

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _looks_like_sigma_home(candidate):
            return candidate

    # Il repository dei moduli sta di norma accanto all'installazione.
    repo_root = Path(__file__).resolve().parents[3]
    for sibling in sorted(repo_root.parent.iterdir()):
        if sibling.is_dir() and _looks_like_sigma_home(sibling):
            return sibling
    return None


SIGMA_HOME = _find_sigma_home()

if SIGMA_HOME is None:
    pytest.skip(
        "Installazione di Sigma Studio non trovata: imposta SIGMA_HOME oppure "
        "lancia pytest dalla cartella di Sigma Studio.",
        allow_module_level=True,
    )

if str(SIGMA_HOME) not in sys.path:
    sys.path.insert(0, str(SIGMA_HOME))

# `gradus` viene importato come package di primo livello, esattamente come fa
# training/fwe.py a runtime: la cartella che lo contiene e' quella del modulo
# installato.
_MODULE_DIR = SIGMA_HOME / "core" / "modules" / "sigma_training_lab"
if _MODULE_DIR.is_dir() and str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))


@pytest.fixture(scope="session")
def sigma_home() -> Path:
    """La radice dell'installazione contro cui gira la suite."""
    return SIGMA_HOME


# ==============================================================================
# ISOLAMENTO DAI DATI VERI
# ==============================================================================
# Senza questo, la suite scrive nell'installazione reale: `create_training_job`
# crea cartelle dentro training/jobs/ e riscrive training_jobs.json, che e'
# l'indice dei fine-tuning dell'utente. Un solo `pytest` bastava a riempire
# l'elenco di job finti e a sostituire il registro vero con quello sintetico.
# Solo test_training_handler.py aveva una fixture di isolamento, e copriva solo
# se stesso.
#
# Qui la deviazione e' di sessione e automatica: qualunque test, anche uno
# scritto domani senza pensarci, lavora su una directory temporanea.
@pytest.fixture(scope="session", autouse=True)
def _isolate_da_dati_reali(tmp_path_factory):
    """Devia le radici del Training Lab su una directory temporanea."""
    radice = tmp_path_factory.mktemp("sigma_training")
    training = radice / "training"
    lab = radice / "training_lab"

    percorsi = {
        "PROJECT_ROOT": radice,
        "TRAINING_DIR": training,
        "JOBS_DIR": training / "jobs",
        "SCRIPTS_DIR": training / "scripts",
        "DATASETS_DIR": training / "datasets",
        "IMPORTS_DIR": training / "imports",
        "JOBS_FILE": training / "training_jobs.json",
        "TRAINING_LAB_DIR": lab,
        "AUTOPILOT_DIR": lab / "autopilot",
        "AUTOPILOT_STATE_FILE": lab / "autopilot_state.json",
        "OFFICIAL_BENCHMARK_FILE": lab / "official_benchmark_results.json",
    }
    for d in (training, training / "jobs", training / "scripts",
              training / "datasets", training / "imports", lab, lab / "autopilot"):
        d.mkdir(parents=True, exist_ok=True)

    # I moduli importano le costanti per valore: vanno riscritte su ognuno di
    # quelli che le tiene, non solo sul modulo paths che le definisce.
    from core.modules.sigma_training_lab import paths as paths_mod
    from core.modules.sigma_training_lab.training import (
        autopilot, checkpoint_chat, datasets, fwe, jobs, model_catalog,
    )
    moduli = (paths_mod, jobs, datasets, autopilot, model_catalog,
              checkpoint_chat, fwe)

    with pytest.MonkeyPatch.context() as mp:
        for nome, valore in percorsi.items():
            for modulo in moduli:
                if hasattr(modulo, nome):
                    mp.setattr(modulo, nome, valore, raising=False)
        # autopilot espone le sue radici con nomi propri.
        mp.setattr(autopilot, "STATE_DIR", percorsi["AUTOPILOT_DIR"], raising=False)
        mp.setattr(autopilot, "STATE_FILE", percorsi["AUTOPILOT_STATE_FILE"], raising=False)
        mp.setattr(autopilot, "ACTIVE_FILE",
                   percorsi["AUTOPILOT_DIR"] / "_attivo.json", raising=False)
        yield radice
