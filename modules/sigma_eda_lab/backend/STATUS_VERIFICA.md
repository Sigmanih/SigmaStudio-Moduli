# Stato della verifica — 'Sigma AI Board v0.1'

Data: 2026-06-15

## Esito

Le operazioni richieste (fogli schematici VRM/sequencing, Jetson, FPGA ECP5,
MDAC/ADC; sync schematico→PCB a 4 layer 100×80 mm; ottimizzazione piazzamento
con vincoli AGND/DGND; apply dry_run=false; score ≥ 90; salvataggio) **non sono
e eseguibili in questa sessione**.

## Fattuali verificati (con prove)

| Verifica | Esito | Prova |
|:--|:--|:--|
| Tool `easyeda_schematic_sync_to_pcb` implementato? | No | `search_code` → 5 match, tutti in `var/dev_sessions/...json` (testo dell'obiettivo), nessun handler |
| Tool `easyeda_pcb_place_component` implementato? | No | `search_code` → 1 match solo in `README.md` (riferimento documentale) |
| File progetto `.eda` / `.brd` nel workspace? | No | `glob **/*.eda` e `glob **/*.brd` → risultato vuoto |
| Server MCP `easyeda_pro` connesso? | No | Comando Python su `MCPHub`: `easyeda_pro_configured=false`, `connection_status.connected=false`, `tools=0` |
| Tool EDA raggiungibili in questa sessione? | 0 | `list_all_tools()` filtrato per 'easyeda'/'eda' → lista vuota |

## Cosa serve per rendere possibili le operazioni

1. **Server MCP EasyEDA Pro configurato e connesso** — oggi è dichiarato ma non
   configurato (`is_configured()=false`). Serve il suo endpoint HTTP/stdio in
   `config/` e la connessione riuscita.
2. **Un progetto EDA reale aperto** — file `.eda` (schematico) e `.brd` (PCB)
   con contorno definito, componenti piazzati e netlist valida. Non esiste nel
   workspace.
3. **I tool `easyeda_*` esposti dal server** — `easyeda_schematic_sync_to_pcb`,
   `easyeda_pcb_place_component`, `easyeda_pcb_modify_component`, ecc. Sono
   dichiarati negli `inputSchema`/`outputSchema` del server ma non sono
   raggiungibili finché il server non è connesso.
4. **Il modulo `sigma_eda_lab`** — già presente e funzionante per gli algoritmi
   (86 test), ma il ponte in `bridge.py` richiede `primitive_id` esistenti nel
   progetto, che non ci sono.

## Nota di governance

Anche quando i prerequisiti saranno soddisfatti, la prima scrittura va fatta con
`dry_run=true` (valore predefinito di `eda_placement_apply`) per verificare unità
e riferimenti su una scheda vera. Il gate di approvazione (`ApprovalRequired`)
resta attivo per le operazioni SENSITIVE.
