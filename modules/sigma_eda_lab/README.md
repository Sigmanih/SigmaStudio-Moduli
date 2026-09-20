# EDA Lab & PCB Placement

Le decisioni che EasyEDA non prende.

Il server MCP di EasyEDA Pro espone le mani: legge cosa c'è sulla scheda, sposta
un pezzo, traccia una pista, esporta i Gerber. Non espone nessun *giudizio* —
dove vada messo un componente, quanto larga debba essere una pista, se il
risultato regga. Questo modulo è quei giudizi. Duplicare ciò che EasyEDA già fa
sarebbe solo un altro strato da mantenere.

## Come è diviso, e perché

```
netlist.py    il modello: componenti, pin, net, misure     ← non sa che EasyEDA esiste
placement.py  ricottura simulata sul piazzamento           ← non sa che EasyEDA esiste
evaluate.py   i controlli e il voto                        ← non sa che EasyEDA esiste
rules.py      larghezza delle piste secondo IPC-2221       ← non sa che EasyEDA esiste
bridge.py     unità, primitiveId, layer, gate di approvazione
mcp_server.py i sei tool esposti all'hub
```

Il confine è netto di proposito: gli algoritmi si provano senza aprire niente, e
la traduzione verso EasyEDA vive in un file solo. Quando EasyEDA cambia una
convenzione c'è un posto da correggere invece di sei.

## I tool

| Tool | Classe | Cosa fa |
|:--|:--|:--|
| `eda_trace_width` | safe | Larghezza minima IPC-2221 per una corrente, più quella consigliata |
| `eda_board_read` | safe | Contorno, componenti e net del progetto aperto, in millimetri |
| `eda_placement_optimize` | safe | Calcola un piazzamento migliore. **Non scrive** |
| `eda_placement_apply` | **sensitive** | Scrive le posizioni. `dry_run` di serie |
| `eda_board_evaluate` | safe | Voto, verdetto e responsabili di ogni controllo fallito |
| `eda_bridge_status` | safe | Stato del collegamento con EasyEDA |

Uno solo tocca il progetto, ed è l'unico che si ferma al gate di governance.

## Il piazzamento

Ricottura simulata, perché la funzione di costo è piena di minimi locali e una
discesa che non accetta mai un peggioramento ci si siede dentro al primo. Tre
proprietà la rendono utilizzabile invece che soltanto corretta:

- **deterministica** — stesso seme, stesso risultato, altrimenti non è verificabile;
- **rispetta `locked`** — connettori sul bordo e fori di fissaggio non si muovono;
- **non peggiora mai** — se non batte il piazzamento di partenza, restituisce quello.

Il costo misura le stesse quattro cose che `evaluate` poi controlla: lunghezza
dei collegamenti, sovrapposizioni, contorno, anello di disaccoppiamento. Non è
eleganza — un costo cieco a un criterio produce schede che lo violano e le
consegna convinto di aver migliorato. È successo durante lo sviluppo, e i due
test `test_il_costo_misura_cio_che_il_valutatore_giudica` e
`test_inflate_trasforma_la_vicinanza_in_sovrapposizione` esistono per impedire
che succeda di nuovo.

### L'anello di disaccoppiamento

La distanza fra un condensatore e il suo integrato si misura **da pin a pin**,
non da centro a centro. Su un QFN da 10 mm nessun condensatore potrebbe mai
scendere sotto i 5 mm dal centro: un criterio fissato più in basso boccerebbe
ogni piazzamento possibile, punendo il chip per le proprie dimensioni. Fra i pin
si misura ciò che conta davvero — il percorso della corrente impulsiva, e quindi
l'induttanza che vanifica o no il condensatore.

## Le unità

EasyEDA restituisce le posizioni dei componenti senza dichiarare in che unità, e
accetta le scritture in mil. Invece di scegliere per fede, `detect_scale`
confronta l'escursione dei componenti letti con le dimensioni della scheda — che
quelle arrivano in millimetri dichiarati — e ricava il fattore vero fra
millimetro, mil e decimo di mil. Se i numeri non tornano con nessuna delle tre
lo dice, e `eda_placement_optimize` si rifiuta di procedere: ottimizzare su una
scala sbagliata produce spostamenti di quaranta volte.

## Quello che questo modulo non fa

- **Non crea componenti sul PCB.** EasyEDA non lo permette: `PCB_PrimitiveComponent.create()`
  non arriva a termine, e il suo stesso `easyeda_pcb_place_component` fallisce di
  proposito. Il passaggio schematico → PCB resta un'azione manuale nella GUI. Da
  lì in poi i pezzi esistono e questo modulo può spostarli.
- **Non instrada.** L'autorouter è quello di EasyEDA (`easyeda_pcb_autoroute`).
  Qui si prepara il terreno su cui lavora, che è dove si decide la qualità del
  risultato.
- **Non sceglie i componenti.** Quello è compito dell'agente che usa i tool.

## Stato della verifica

Gli algoritmi sono coperti da 86 test che girano senza EasyEDA aperto.

Il ponte no, e va detto chiaramente: le chiamate in `bridge.py` sono scritte
sugli `inputSchema` e `outputSchema` che il server MCP di EasyEDA dichiara, non
su risposte osservate su un progetto vero. Gli schemi fissano i nomi dei campi,
non i loro valori. **Il primo giro su un progetto reale va fatto con
`dry_run=true`**, ed è per questo che è il valore predefinito di
`eda_placement_apply`.
