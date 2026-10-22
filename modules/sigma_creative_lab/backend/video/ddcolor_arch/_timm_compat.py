"""I due nomi di timm che usa ConvNeXt, senza dipendere da timm.

In inferenza lo stochastic depth e' l'identita': installare timm solo per
DropPath sarebbe una dipendenza in piu' per nessun effetto.
"""

from torch import nn
from torch.nn.init import trunc_normal_  # noqa: F401


class DropPath(nn.Module):
    def __init__(self, drop_prob: float = 0.0):
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, x):
        return x
