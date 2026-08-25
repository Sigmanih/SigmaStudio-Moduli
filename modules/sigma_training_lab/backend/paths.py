# ==============================================================================
# core/modules/sigma_training_lab/paths.py — Dove il Training Lab tiene le sue cose
#
# Questo file nasce da un incidente preciso. Ognuno dei sette file di training/
# ricavava la radice del progetto per conto proprio, con:
#
#     BASE_DIR = Path(__file__).parent.parent.parent
#
# Quando il codice stava in core/training/ quella risalita arrivava davvero alla
# radice. Spostando il pacchetto in core/modules/sigma_training_lab/training/ i
# .parent sono rimasti tre mentre i livelli da risalire erano diventati cinque:
# da quel momento BASE_DIR ha puntato a core/modules/, e il modulo ha letto e
# scritto job, dataset e stato dell'autopilota in un albero vuoto che creava lui
# stesso con mkdir(parents=True). Nessun errore e' mai stato sollevato, e i 103
# job reali sono rimasti sul disco invisibili al Training Lab.
#
# Da qui in avanti la radice si chiede al kernel — project_root() e' ancorato
# alla posizione del kernel, non alla directory da cui si lancia il server — e
# le cartelle del modulo si dichiarano una volta sola. Nessun altro file del
# modulo ricostruisce un percorso risalendo da __file__.
#
# Due radici distinte, con nomi che non si possono confondere:
#   PROJECT_ROOT  la radice dell'installazione: qui stanno training/ e
#                 training_lab/, che restano fuori dal modulo perche' sono dati
#                 dell'utente e sopravvivono a una disinstallazione.
#   MODULE_DIR    questa cartella: qui sta gradus/, che e' codice del modulo e
#                 se ne va con lui.
# ==============================================================================
from pathlib import Path

from core.model_paths import project_root

#: Radice dell'installazione di Sigma Studio.
PROJECT_ROOT = Path(project_root())

#: Radice del modulo Training Lab (contiene gradus/, training/, i manifest).
MODULE_DIR = Path(__file__).resolve().parent

# ----------------------------------------------------------------- dati utente
# Fuori dal modulo: un fine-tuning costa ore di GPU e non deve sparire se il
# modulo viene disinstallato o reinstallato dal marketplace.

TRAINING_DIR = PROJECT_ROOT / "training"
JOBS_DIR = TRAINING_DIR / "jobs"
SCRIPTS_DIR = TRAINING_DIR / "scripts"
DATASETS_DIR = TRAINING_DIR / "datasets"
IMPORTS_DIR = TRAINING_DIR / "imports"
JOBS_FILE = TRAINING_DIR / "training_jobs.json"

TRAINING_LAB_DIR = PROJECT_ROOT / "training_lab"
AUTOPILOT_DIR = TRAINING_LAB_DIR / "autopilot"
AUTOPILOT_STATE_FILE = TRAINING_LAB_DIR / "autopilot_state.json"
OFFICIAL_BENCHMARK_FILE = TRAINING_LAB_DIR / "official_benchmark_results.json"

# ----------------------------------------------------------------- codice modulo

#: Il generatore di pesi Gradus, importato come package `gradus` con MODULE_DIR
#: in sys.path (o come cwd per `python -m gradus`).
GRADUS_DIR = MODULE_DIR / "gradus"

#: Checkout di llama.cpp usato per la conversione in GGUF, se presente.
LLAMA_CPP_DIR = PROJECT_ROOT / "llama.cpp"


def ensure_runtime_dirs() -> None:
    """Crea le cartelle di lavoro mancanti.

    Chiamata una volta all'import di questo modulo: prima la creazione era
    duplicata in jobs.py e datasets.py, ed e' esattamente il mkdir silenzioso
    che ha nascosto per settimane l'ancoraggio sbagliato.
    """
    for directory in (TRAINING_DIR, JOBS_DIR, SCRIPTS_DIR, DATASETS_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Un disco pieno o un percorso non scrivibile non deve impedire
            # l'import del modulo: chi usa la cartella riportera' l'errore.
            pass


ensure_runtime_dirs()
