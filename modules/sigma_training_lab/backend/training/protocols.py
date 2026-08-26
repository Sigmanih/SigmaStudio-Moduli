# ==============================================================================
# core/modules/sigma_training_lab/training/protocols.py
# Come si misura ogni suite, e perche' non c'e' un modo solo
# ==============================================================================
"""Il protocollo di valutazione, dichiarato per suite invece che scelto una volta.

Il tentativo precedente applicava un unico metodo a tutto: leggere la
distribuzione sul primo token di risposta, senza esempi e senza ragionamento.
E' il metodo giusto per MMLU e sbagliato per quasi tutto il resto, e il
punteggio che ne usciva era basso per ragioni che non riguardavano il modello.
Tre errori distinti, che vale la pena tenere separati perche' hanno rimedi
diversi:

1. **Suite che non si misurano su una lettera.** HellaSwag e ARC non chiedono
   "quale lettera": chiedono quale delle quattro continuazioni e' quella vera.
   Il metodo ufficiale confronta la verosimiglianza del *testo* di ogni opzione,
   normalizzata sulla lunghezza. Farlo scegliere una lettera misura in piu' la
   capacita' di gestire un formato a scelta multipla, che su HellaSwag non e'
   cio' che il benchmark dichiara di misurare — e i modelli piccoli ci perdono
   molto.

2. **Suite che esistono per far ragionare.** MMLU-Pro, GPQA, BBH, GSM8K e MATH
   sono pensati e pubblicati con catena di ragionamento. Leggere il primo token
   dopo "Answer:" misura la risposta d'istinto, cioe' esattamente cio' che
   quelle suite sono state costruite per non premiare. Spegnere il blocco di
   ragionamento su un modello che ragiona e' un handicap imposto dallo
   strumento, non una proprieta' del modello.

3. **Zero esempi ovunque.** MMLU si pubblica a 5 esempi. A zero, un modello
   perde punti sul formato prima ancora di rispondere.

Ogni voce di questa tabella dice quale dei quattro metodi usare, quanti esempi
mettere davanti, se lasciar ragionare il modello e con che budget. Il tutto
finisce nel certificato: due run con protocolli diversi non sono confrontabili,
e l'unico modo per accorgersene e' che il protocollo sia scritto accanto al
punteggio.

Riferimento: lm-evaluation-harness di EleutherAI, che e' cio' che gira dietro
Open LLM Leaderboard e dietro la maggior parte dei numeri nelle schede modello.
"""

from dataclasses import dataclass
from typing import Dict, Optional

# ---------------------------------------------------------------- i quattro modi

#: Si confronta la verosimiglianza delle sole etichette (" A", " B", ...) nella
#: posizione di risposta. Una passata in avanti, esito sempre univoco.
MODE_LETTER = "letter_logprob"

#: Si confronta la verosimiglianza del *testo* di ogni opzione, come
#: continuazione del contesto, normalizzata sulla lunghezza. Una passata per
#: opzione, tutte in lotto. E' `acc_norm` nell'harness.
MODE_CONTINUATION = "continuation_logprob"

#: Il modello scrive il ragionamento e poi la risposta, che viene estratta dal
#: testo. E' l'unico modo per le suite costruite attorno al ragionamento.
MODE_COT = "cot_generation"

#: Il modello scrive codice, e il verdetto lo danno i test ufficiali eseguiti.
MODE_CODE = "code_execution"


@dataclass(frozen=True)
class Protocol:
    """Come si interroga e si giudica una suite."""

    mode: str
    #: Esempi risolti messi davanti al quesito. Zero e' corretto per un modello
    #: istruito su suite che si pubblicano a zero; per MMLU non lo e'.
    shots: int = 0
    #: None lascia al checkpoint il suo default. True serve dove la suite e'
    #: costruita sul ragionamento, False dove si legge una distribuzione e il
    #: ragionamento sarebbe solo budget speso e poi buttato.
    thinking: Optional[bool] = False
    #: Budget di generazione. Irrilevante per i due modi a verosimiglianza.
    max_tokens: int = 0
    #: Come si normalizza il confronto fra continuazioni di lunghezza diversa.
    #: "char" e' la lunghezza in caratteri, come `acc_norm`.
    normalize: str = ""
    #: Il nome pubblico della metrica, per il certificato.
    metric: str = "acc"
    #: Nota sul perche' di questa scelta, mostrata accanto al punteggio.
    note: str = ""
    #: Come si compone il contesto quando si confrontano le continuazioni.
    #: `{q}` e' il testo del quesito. Non e' cosmetica: la verosimiglianza di
    #: " Paris" dopo "What is the capital of France?" e dopo "Question: What is
    #: the capital of France?" seguito da "Answer:" sono due numeri diversi, e i
    #: punteggi pubblicati sono quelli della seconda forma. Senza il richiamo un
    #: modello da 12B su ARC scendeva al 30% — il livello del caso.
    context: str = "{q}"


#: Budget generoso di proposito. Un modello che ragiona spende centinaia di
#: token prima di arrivare alla risposta, e troncarlo a meta' ragionamento non
#: produce una risposta sbagliata: produce nessuna risposta, che nel conteggio
#: pesa come un errore e non lo e'.
_COT_BUDGET = 2048
_COT_BUDGET_LONG = 3072


PROTOCOLS: Dict[str, Protocol] = {
    # ---- verosimiglianza sull'etichetta -----------------------------------
    "mmlu": Protocol(
        mode=MODE_LETTER, shots=5, thinking=False, metric="acc",
        note="5 esempi, verosimiglianza sulle lettere: il protocollo con cui "
             "MMLU e' pubblicato dal 2021.",
    ),

    # ---- verosimiglianza sulla continuazione ------------------------------
    "hellaswag": Protocol(
        mode=MODE_CONTINUATION, shots=0, thinking=False,
        normalize="char", metric="acc_norm",
        # Il contesto e' gia' una frase da completare: qualunque cornice
        # aggiunta cambierebbe cio' che si sta misurando.
        context="{q}",
        note="Si confrontano le quattro continuazioni, normalizzate sulla "
             "lunghezza. HellaSwag non chiede una lettera, chiede quale finale "
             "e' quello vero.",
    ),
    "arc": Protocol(
        mode=MODE_CONTINUATION, shots=0, thinking=False,
        normalize="char", metric="acc_norm",
        context="Question: {q}" + chr(10) + "Answer:",
        note="Verosimiglianza sul testo delle risposte, normalizzata: e' "
             "`acc_norm`, il numero riportato sulle classifiche.",
    ),
    "truthfulqa": Protocol(
        mode=MODE_CONTINUATION, shots=0, thinking=False,
        normalize="char", metric="acc_norm",
        context="Q: {q}" + chr(10) + "A:",
        note="Zero esempi di proposito: mostrare risposte corrette insegna a "
             "riconoscerne il tono, e TruthfulQA misura proprio quello.",
    ),

    # ---- ragionamento poi risposta ----------------------------------------
    "mmlu_pro": Protocol(
        mode=MODE_COT, shots=0, thinking=True, max_tokens=_COT_BUDGET,
        metric="acc",
        note="MMLU-Pro nasce per essere fatto ragionando: e' la differenza "
             "dichiarata rispetto a MMLU, e misurarlo d'istinto lo annulla.",
    ),
    "gpqa": Protocol(
        mode=MODE_COT, shots=0, thinking=True, max_tokens=_COT_BUDGET,
        metric="acc",
        note="Domande di livello dottorale: senza ragionamento anche un modello "
             "forte resta al caso.",
    ),
    "bbh": Protocol(
        mode=MODE_COT, shots=0, thinking=True, max_tokens=_COT_BUDGET,
        metric="exact_match",
        note="BIG-Bench Hard e' la selezione dei task dove il ragionamento "
             "passo passo faceva la differenza; si pubblica cosi'.",
    ),
    "gsm8k": Protocol(
        mode=MODE_COT, shots=0, thinking=True, max_tokens=_COT_BUDGET,
        metric="exact_match",
        note="Risposta finale dopo il ragionamento, confrontata come numero.",
    ),
    "math": Protocol(
        mode=MODE_COT, shots=0, thinking=True, max_tokens=_COT_BUDGET_LONG,
        metric="exact_match",
        note="Problemi da competizione: il budget e' piu' alto perche' la "
             "soluzione e' lunga prima ancora di essere difficile.",
    ),

    # ---- codice eseguito ---------------------------------------------------
    "humaneval": Protocol(
        mode=MODE_CODE, shots=0, thinking=False, max_tokens=1024,
        metric="pass@1",
        note="Il verdetto lo danno i test ufficiali eseguiti, non un parser.",
    ),
    "mbpp": Protocol(
        mode=MODE_CODE, shots=0, thinking=False, max_tokens=1024,
        metric="pass@1",
        note="Come HumanEval: si esegue.",
    ),
}


#: Per una suite che non e' in tabella. Genera e legge la risposta dal testo,
#: che e' il comportamento piu' prudente: non assume una forma che l'item
#: potrebbe non avere.
FALLBACK = Protocol(
    mode=MODE_COT, shots=0, thinking=None, max_tokens=1024, metric="acc",
    note="Suite non in tabella: generazione libera e lettura della risposta.",
)


def protocol_for(suite_id: str) -> Protocol:
    """Il protocollo di una suite, o il ripiego prudente."""
    return PROTOCOLS.get((suite_id or "").lower(), FALLBACK)


def describe(suite_id: str) -> Dict[str, object]:
    """La riga di certificato per una suite."""
    protocol = protocol_for(suite_id)
    return {
        "suite": suite_id,
        "mode": protocol.mode,
        "shots": protocol.shots,
        "thinking": protocol.thinking,
        "metric": protocol.metric,
        "normalize": protocol.normalize or None,
        "note": protocol.note,
    }
