"""Architettura di DDColor (colorazione di immagini), copiata dal repository ufficiale.

Origine: https://github.com/piddnad/DDColor, commit 2adb63f, licenza Apache 2.0
(testo in LICENSE). File presi: ddcolor/model.py e
basicsr/archs/ddcolor_arch_utils/{unet,convnext,transformer_utils,position_encoding}.py.

Modifiche rispetto all'originale: solo gli import, resi relativi a questo
pacchetto, e timm sostituito da _timm_compat. Il codice serve unicamente a
recolor_worker.py, che gira in un processo a parte: il server non importa torch.
"""

from .model import DDColor  # noqa: F401
