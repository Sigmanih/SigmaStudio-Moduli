# ==============================================================================
# core/modules/sigma_training_lab/training/benchmark_store.py
# Proxy di retrocompatibilita' verso il modulo autonomo sigma_benchmark_lab
# ==============================================================================
from __future__ import annotations
import sys

try:
    import core.modules.sigma_benchmark_lab.benchmark_store as _real_store
    sys.modules[__name__] = _real_store
except ImportError:
    pass
