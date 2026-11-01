# ==============================================================================
# core/modules/sigma_training_lab/training/benchmarks.py
# Proxy di retrocompatibilita' verso il modulo autonomo sigma_benchmark_lab
# ==============================================================================
from __future__ import annotations
import sys

try:
    import core.modules.sigma_benchmark_lab.benchmarks as _real_benchmarks
    # Inietta il modulo reale in sys.modules per garantire trasparenza
    # assoluta sia per gli import che per mock.patch nei test unitari.
    sys.modules[__name__] = _real_benchmarks
except ImportError:
    pass
