# KiCad Lab — Integrazione nativa con KiCad

Le stesse decisioni di EDA Lab, senza il ponte.

## Perché un modulo separato da EDA Lab

EDA Lab parla con EasyEDA Pro tramite un bridge MCP: un server esterno che
dev'essere collegato, una GUI che dev'essere aperta, un transport che tronca le
risposte, sessioni da scaldare, unità da indovinare. KiCad Lab non ha niente di
tutto questo: legge i file `.kicad_pcb` e `.kicad_sch` dal disco, e per le
operazioni che servono un motore di regole (DRC, ERC, Gerber) invoca `kicad-cli`
come subprocess.

## Come è diviso

```
kicad_parser.py   parser S-expression, lettura/scrittura file KiCad   ← zero dipendenze
kicad_cli.py      wrapper per kicad-cli: DRC, ERC, Gerber, BOM       ← richiede KiCad installato
bridge.py         traduzione KiCadBoardInfo ↔ Board                   ← usa il modello di sigma_eda_lab
mcp_server.py     i dieci tool esposti all'hub                        ← solo qui c'è la governance
handlers.py       registrazione nel kernel
```

Gli algoritmi (`placement.py`, `evaluate.py`, `rules.py`, `netlist.py`) vengono
da `sigma_eda_lab` e non vengono duplicati. Il modello `Board` / `Component` /
`Net` è lo stesso: cambia solo chi lo riempie e chi lo riscrive.

## I tool

| Tool | Classe | Cosa fa |
|:--|:--|:--|
| `kicad_status` | safe | KiCad trovato? Versione? |
| `kicad_board_read` | safe | Legge PCB: outline, componenti, net, in mm |
| `kicad_placement_optimize` | safe | Ricottura simulata, restituisce spostamenti |
| `kicad_placement_apply` | **sensitive** | Riscrive le posizioni nel .kicad_pcb |
| `kicad_board_evaluate` | safe | Voto, verdetto, elenco dei problemi |
| `kicad_trace_width` | safe | IPC-2221: larghezza pista per corrente data |
| `kicad_drc` | safe | DRC headless via kicad-cli |
| `kicad_erc` | safe | ERC headless via kicad-cli |
| `kicad_export_gerbers` | safe | Gerber + drill per la produzione |
| `kicad_export_bom` | safe | BOM in CSV |

## Cosa serve

- **KiCad 8+** installato (per `kicad-cli`). Il parser funziona anche senza,
  ma DRC, ERC e export richiedono l'eseguibile.
- Nessuna dipendenza Python aggiuntiva.

## Differenze rispetto a EDA Lab

| | EDA Lab (EasyEDA) | KiCad Lab |
|:--|:--|:--|
| **Comunicazione** | Bridge MCP → server esterno → GUI | File su disco + subprocess |
| **Unità** | mil, da indovinare con `detect_scale` | mm, sempre |
| **Identificativo componente** | `primitiveId` (uuid opaco) | Reference (U1, R3, C5) |
| **DRC** | Via bridge, fragile | `kicad-cli`, headless, report JSON |
| **Export Gerber** | Via bridge, lento | `kicad-cli`, headless |
| **GUI necessaria** | Sì, sempre | No, mai |
| **Dipendenze MCP esterne** | `easyeda_pro` | Nessuna |
| **Formato file** | Binario proprietario | S-expression, leggibile, versionabile |

## Il formato S-expression

Un file `.kicad_pcb` è una sequenza di espressioni S annidate:

```lisp
(kicad_pcb
  (version 20240108)
  (generator "pcbnew")
  (net 0 "")
  (net 1 "GND")
  (footprint "Resistor_SMD:R_0603_1608Metric"
    (at 100.0 50.0 90)
    (property "Reference" "R1")
    (pad "1" smd rect (at -0.825 0) (size 0.8 0.95)
      (net 1 "GND"))
    ...))
```

Il parser tokenizza (~60 righe), costruisce un albero di liste Python, e le
funzioni `read_*` / `write_*` navigano e modificano quell'albero. Le scritture
sono sostitutive e mirate: non riscrivono l'intero file, così commenti e
formattazione originale restano.
