# ==============================================================================
# core/modules/sigma_benchmark_lab/paths.py — Percorsi del Benchmark Lab
# ==============================================================================
from pathlib import Path

from core import paths as _paths
from core.model_paths import project_root

#: Radice dell'installazione di Sigma Studio.
PROJECT_ROOT = Path(project_root())

#: Radice del modulo Benchmark Lab.
MODULE_DIR = Path(__file__).resolve().parent

# ----------------------------------------------------------------- dati utente
# I risultati e le cache risiedono in store/training_lab/ per garantire
# piena continuita' storica con le valutazioni pregresse.
BENCHMARKS_DATA_DIR = _paths.training_lab_dir()
TRAINING_LAB_DIR = BENCHMARKS_DATA_DIR
OFFICIAL_BENCHMARK_FILE = BENCHMARKS_DATA_DIR / "official_benchmark_results.json"
BENCHMARK_RUNS_DIR = BENCHMARKS_DATA_DIR / "benchmark_runs"
BENCHMARK_CACHE_DIR = BENCHMARKS_DATA_DIR / "benchmark_cache"


def ensure_runtime_dirs() -> None:
    """Assicura la presenza delle cartelle dei referti e della cache."""
    for directory in (BENCHMARKS_DATA_DIR, BENCHMARK_RUNS_DIR, BENCHMARK_CACHE_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


ensure_runtime_dirs()
