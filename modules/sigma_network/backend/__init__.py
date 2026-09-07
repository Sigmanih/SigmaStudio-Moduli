"""Sigma Network — rete peer-to-peer per inferenza distribuita.

Espone il router HTTP del modulo. La registrazione MCP e' dichiarata ma non
ancora attiva: il server MCP richiede di collegare registry, wallet e broker
con le loro API reali, ed e' preferibile non esporre tool agli agenti finche'
non fanno quello che dichiarano di fare.
"""

from .handlers import router

__all__ = ["router", "register_mcp"]


def register_mcp(mcp_hub) -> None:
    """Registrerebbe il server MCP di Sigma Network. Non ancora implementato.

    Volutamente inerte invece che assente: il module loader la cerca, e una
    funzione che non fa nulla e lo dice e' meglio di un import che fallisce o,
    peggio, di tool registrati che restituiscono dati inventati.
    """
    return None
