# ==============================================================================
# sigma_kicad_lab/orchestrator.py — Il team hardware: un agente, gli stessi tool
# ==============================================================================
"""Chi progetta la scheda, e con che cosa.

Fino al 25 settembre 2026 questo file conteneva cinque personaggi — Architect,
Schematic, Layout, Verifier, Manufacturing — che si passavano il turno emettendo
eventi. Nessuno dei cinque chiamava un modello: il workflow faceva passi
meccanici (risolvi i percorsi, crea un progetto vuoto, lancia il piazzamento,
lancia il DRC, esporta) e intorno scriveva la cronaca di un lavoro che nessuno
stava facendo. La scheda diceva «Fase 3 completata» e il rame non si era mosso di
un millimetro.

Adesso c'e' un agente solo, quello vero: il ruolo `kicad_engineer` dell'harness,
con i suoi tool, che apre il progetto, lo modifica e verifica quello che ha
fatto. Le cinque fasi restano nel prompt del ruolo — sono il metodo con cui
lavora — non cinque voci in un log.

**La verifica la fa chi deve.** Alla fine del run il DRC (e l'ERC, dove c'e' uno
schematico) viene eseguito davvero, con `kicad-cli`, e il numero che arriva
all'interfaccia e' quello che ha risposto l'eseguibile. Uno "0 errori" scritto a
mano in un `emit()` non e' una verifica, e' una didascalia.

**Il vocabolario degli eventi e' corto e sta in due posti soli** — qui e in
`PcbLab.jsx`, che li consuma. Allungarlo da un lato solo produce eventi che
nessuno disegna.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from core.logger import get_logger

log = get_logger("kicad_orchestrator")


#: Come si presenta il ruolo nell'interfaccia. Uno solo: cinque facce per un
#: agente solo sono il modo di far sembrare una squadra quello che e' un turno.
RUOLO_SCHEDA = {
    "id": "kicad_engineer",
    "name": "KiCad Hardware & PCB Engineer",
    "icon": "🔌",
    "color": "#10b981",
    "description": ("Legge e modifica la scheda con i tool KiCad, e verifica "
                    "cio' che ha fatto con DRC ed ERC."),
}


class HardwareTeamOrchestrator:
    """Un task hardware eseguito dall'agente KiCad, con gli eventi in streaming."""

    def __init__(self, task: str, project_dir: str, pcb_path: Optional[str] = None,
                 sch_path: Optional[str] = None, session_id: Optional[str] = None):
        self.task = str(task or "").strip()
        self.project_dir = Path(project_dir)
        self.session_id = session_id or f"kicad_{int(time.time())}"
        self.event_queue: queue.Queue = queue.Queue()
        self._stopped = False

        self.pcb_path = Path(pcb_path) if pcb_path else None
        self.sch_path = Path(sch_path) if sch_path else None
        self._resolve_paths()

    # --- contesto -------------------------------------------------------------

    def _resolve_paths(self) -> None:
        """Individua i file del progetto, senza crearne di nuovi.

        Creare una scheda vuota quando non ce n'e' una era il comportamento
        vecchio, ed era una bugia comoda: l'agente riceveva un progetto che
        nessuno aveva chiesto e il task proseguiva su quello. Se il progetto non
        c'e', lo dice l'errore.
        """
        if not self.pcb_path or not self.pcb_path.is_file():
            trovate = sorted(self.project_dir.glob("*.kicad_pcb"))
            self.pcb_path = trovate[0] if trovate else None
        if not self.sch_path or not self.sch_path.is_file():
            trovate = sorted(self.project_dir.glob("*.kicad_sch"))
            self.sch_path = trovate[0] if trovate else None

    def emit(self, tipo: str, **dati: Any) -> None:
        """Mette un evento nella coda che lo stream legge."""
        self.event_queue.put({"type": tipo, "timestamp": time.time(), **dati})

    def stop(self) -> None:
        self._stopped = True

    def _fermo(self) -> bool:
        return self._stopped

    # --- stream ---------------------------------------------------------------

    def run_stream(self) -> Generator[str, None, None]:
        """Esegue il lavoro in un thread e restituisce il generatore SSE."""
        worker = threading.Thread(target=self._esegui, daemon=True)
        worker.start()

        while True:
            try:
                evento = self.event_queue.get(timeout=0.5)
            except queue.Empty:
                if not worker.is_alive():
                    # Il thread e' finito senza dire perche': meglio dirlo che
                    # lasciare l'interfaccia ad aspettare per sempre.
                    if not self._stopped:
                        yield self._sse({"type": "error",
                                         "message": "Il run e' terminato senza esito."})
                    break
                continue
            if evento is None:
                break
            yield self._sse(evento)
            if evento.get("type") in ("completed", "error"):
                break

    @staticmethod
    def _sse(evento: Dict[str, Any]) -> str:
        return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"

    # --- contesto del run -----------------------------------------------------

    def _richiesta(self) -> str:
        """Il compito, con i percorsi del progetto davanti.

        L'agente ha i tool ma non sa dove sia il progetto: `kicad_open` vuole un
        percorso, e ricavarlo dal nulla non e' compito suo.
        """
        righe = [self.task, "", "## Progetto su cui lavorare", ""]
        righe.append(f"- scheda: `{self.pcb_path}`" if self.pcb_path
                     else "- scheda: nessun file .kicad_pcb in questa cartella")
        if self.sch_path:
            righe.append(f"- schematico: `{self.sch_path}`")
        righe.append(f"- cartella del progetto: `{self.project_dir}`")
        righe.append("")
        righe.append("Apri il progetto con `kicad_open` prima di ogni altra cosa, "
                     "e verifica con `kicad_drc` (ed `kicad_erc` se c'e' lo "
                     "schematico) prima di dichiarare finito.")
        return "\n".join(righe)

    def _ruolo(self):
        """Il ruolo KiCad, coi suoi tool. Senza, il run non parte."""
        from core.harness.roles import DEV_ROLES

        ruolo = DEV_ROLES.get("kicad_engineer")
        if ruolo is None:
            # Succede se il modulo e' installato ma l'aggancio all'harness non e'
            # avvenuto: un agente senza tool proverebbe comunque, e fallirebbe
            # una chiamata per volta.
            from . import tools
            tools.registra()
            ruolo = DEV_ROLES.get("kicad_engineer")
        return ruolo

    # --- esecuzione -----------------------------------------------------------

    def _esegui(self) -> None:
        """Il turno dell'agente, poi la verifica. Gli errori diventano eventi."""
        try:
            ruolo = self._ruolo()
            if ruolo is None:
                self.emit("error", message=(
                    "Il ruolo kicad_engineer non e' registrato: il modulo non ha "
                    "agganciato i suoi tool all'harness."))
                return
            if self.pcb_path is None:
                self.emit("error", message=(
                    f"In {self.project_dir} non c'e' nessun file .kicad_pcb da "
                    "modificare."))
                return

            self.emit("role_changed", role=RUOLO_SCHEDA)
            self.emit("status", message=f"Agente {ruolo.name} al lavoro.")

            # L'import sta qui e non in cima al file perche' `core.harness.loop`
            # tira dietro il motore di inferenza: il modulo si carica all'avvio
            # del server, e pagare quel costo per una scheda che nessuno aprira'
            # e' un costo che si paga sempre per un lavoro che si fa a volte.
            from core.harness.loop import stream_admin_agent_turn

            for evento in stream_admin_agent_turn(
                messages=[{"role": "user", "content": self._richiesta()}],
                workspace_root=str(self.project_dir),
                system_prompt_override=ruolo.system_prompt,
                allowed_tools=list(ruolo.tools),
                policy_label=ruolo.id,
                temperature=ruolo.temperature,
                max_turns=ruolo.max_turns,
                max_tokens=ruolo.max_tokens,
                auto_execute_tools=True,
                should_cancel=self._fermo,
                session_id=self.session_id,
            ):
                self._inoltra(evento)
                if self._stopped:
                    self.emit("status", message="Run interrotto dall'utente.")
                    break

            self._verifica()
        except Exception as exc:
            log.exception("[kicad_orchestrator] run fallito")
            self.emit("error", message=f"{type(exc).__name__}: {exc}")

    def _inoltra(self, evento: Dict[str, Any]) -> None:
        """Traduce un evento dell'harness in un evento che la scheda disegna.

        I `thought` non si inoltrano. Sono il canale in cui il modello si parla
        addosso — migliaia di token che nessuno legge — e l'interfaccia non li
        disegnerebbe comunque: mandarli sarebbe traffico per un consumatore che
        non esiste.
        """
        tipo = str((evento or {}).get("type") or "")
        if tipo == "token":
            pezzo = evento.get("token") or ""
            if pezzo:
                self.emit("token", text=pezzo)
        elif tipo == "tool_start":
            self.emit("tool", tool=evento.get("tool"), params=evento.get("params"))
        elif tipo == "tool_result":
            esito = evento.get("result") or {}
            self.emit("tool_result", tool=evento.get("tool"),
                      success=bool(esito.get("success")),
                      error=str(esito.get("error") or ""))
        elif tipo == "goal_complete":
            self.emit("status", message=str(
                evento.get("summary") or "L'agente ha dichiarato il lavoro completo."))
        elif tipo == "cancelled":
            self.emit("status", message="Run annullato.")
        elif tipo == "error":
            self.emit("error", message=str(evento.get("message")
                                           or evento.get("error")
                                           or "Errore dell'agente."))
        elif tipo == "run_metrics":
            self.emit("metrics", **{k: v for k, v in evento.items()
                                    if k not in ("type", "timestamp")})

    # --- verifica -------------------------------------------------------------

    def _verifica(self) -> None:
        """DRC ed ERC veri, sul file appena scritto.

        Il progetto si riapre perche' l'agente puo' aver lavorato su un altro
        file, o averlo aperto e chiuso: la verifica deve guardare quello che e'
        finito sul disco adesso.
        """
        from . import tools

        apertura = tools.kicad_open(str(self.pcb_path))
        if not apertura.get("success"):
            self.emit("status", message=("Il progetto non si e' riaperto: "
                                         "verifica non eseguita."))
            self._chiudi(0, "Verifica non eseguita: il progetto non si e' "
                            "riaperto.")
            return

        drc_errori = self._conteggio(tools.kicad_drc, "DRC")
        erc_errori = None
        if self.sch_path:
            erc_errori = self._conteggio(tools.kicad_erc, "ERC")

        if drc_errori is None and erc_errori is None:
            self.emit("status", message=("Verifica non eseguita: kicad-cli non "
                                         "ha risposto."))
            self._chiudi(0, "Verifica non eseguita: kicad-cli non ha risposto.")
            return

        pulito = (drc_errori in (None, 0)) and (erc_errori in (None, 0))
        garanzia = ("La scheda non ha violazioni rilevate da kicad-cli." if pulito
                    else "Restano violazioni: vanno corrette prima di mandare "
                         "la scheda in produzione.")
        self.emit("closed_loop_verification",
                  drc_errors=drc_errori if drc_errori is not None else -1,
                  erc_errors=erc_errori if erc_errori is not None else -1,
                  guarantee=garanzia)
        self._chiudi(
            100 if pulito else 60,
            f"Verifica conclusa — DRC {self._mostra(drc_errori)}, "
            f"ERC {self._mostra(erc_errori)}.")

    def _chiudi(self, punteggio: int, messaggio: str) -> None:
        """L'ultimo evento di ogni run.

        Sempre, anche quando la verifica non si e' potuta fare: uno stream che
        finisce senza verdetto lascia l'interfaccia ad aspettare, e chi legge
        crede che il lavoro stia ancora andando avanti.
        """
        self.emit("completed", message=messaggio, score_percent=punteggio)

    @staticmethod
    def _conteggio(esecutore, etichetta: str) -> Optional[int]:
        """Gli errori riportati da un controllo, o None se non ha risposto."""
        try:
            rapporto = esecutore()
        except Exception as exc:
            log.warning("[kicad_orchestrator] %s non eseguito: %s", etichetta, exc)
            return None
        if not rapporto.get("success"):
            log.warning("[kicad_orchestrator] %s fallito: %s", etichetta,
                        rapporto.get("error"))
            return None
        try:
            return int(rapporto.get("total_errors") or 0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _mostra(valore: Optional[int]) -> str:
        return "non eseguito" if valore is None else str(valore)
