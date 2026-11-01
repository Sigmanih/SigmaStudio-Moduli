"""Compatibilita' del laboratorio con il valutatore posseduto dall'harness."""
import importlib
import sys
from core.harness import protocol as _protocol

__all__ = _protocol.__all__
for _name in __all__:
    globals()[_name] = getattr(_protocol, _name)
for _child in ("engine", "evaluator", "sandbox", "scenarios"):
    sys.modules[__name__ + "." + _child] = importlib.import_module("core.harness.protocol." + _child)
