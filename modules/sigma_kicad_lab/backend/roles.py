# ==============================================================================
# sigma_kicad_lab/roles.py - Il ruolo con cui un agente progetta una scheda
# ==============================================================================
"""Il ruolo KiCad, dove stanno i suoi tool: nel modulo, non nel kernel.

Un ruolo che nomina ventisette tool `kicad_*` appartiene a chi possiede quei
tool. Nel kernel restava una lista di nomi che senza il modulo installato non
concedeva niente, e con il modulo installato lo costringeva a conoscerlo. Qui
il ruolo si registra da solo insieme ai tool, con `register_harness_tools()`.
"""
from core.harness.roles import DevRole

ROLE_KICAD_ENGINEER = DevRole(
    id="kicad_engineer",
    name="KiCad Hardware & PCB Engineer",
    icon="🔌",
    temperature=0.15,
    top_p=0.85,
    top_k=30,
    max_tokens=10000,
    max_turns=80,
    tools=(
        # contesto e lettura
        "kicad_status", "kicad_open", "kicad_board_read", "kicad_list_parts",
        "kicad_pads", "kicad_nets",
        # analisi
        "kicad_trace_width", "kicad_board_evaluate", "kicad_placement_optimize",
        # scrittura sul progetto
        "kicad_placement_apply", "kicad_add_track", "kicad_add_route",
        "kicad_add_via", "kicad_add_footprint", "kicad_remove_footprint",
        # correzione: un pezzo spostato o rinominato, una pista tolta, la net di
        # un pad. Sono le operazioni che servono quando il piazzamento e' quasi
        # giusto, ed e' la condizione normale dopo il primo giro.
        "kicad_move_footprint", "kicad_rename_footprint",
        "kicad_delete_track", "kicad_delete_via",
        "kicad_set_board_outline", "kicad_set_pad_net",
        "kicad_undo",
        # pcbnew bridge: creazione e ispezione diretta via API pcbnew
        "kicad_pcbnew_status", "kicad_libraries", "kicad_search_footprint",
        "kicad_new_board", "kicad_add_part", "kicad_read_board_full",
        # verifica e produzione
        "kicad_drc", "kicad_erc", "kicad_export_gerbers", "kicad_export_bom",
        "kicad_render",
        # servizio. Niente write_file, edit_file o terminal: questo ruolo
        # progetta schede, e un giro andato male non deve poter riscrivere il
        # kernel. I file del progetto si toccano dai tool kicad_*, che fanno
        # una copia prima di ogni scrittura.
        "read_file", "list_dir", "glob", "search_code",
        "spec", "pipeline", "queue_add", "complete_goal",
    ),
    focus_areas=(
        "schematici KiCad .kicad_sch", "layout PCB .kicad_pcb", "dimensionamento IPC-2221",
        "disaccoppiamento e condensatori bypass", "piani di massa e return path",
        "verifica ad anello chiuso con 0 errori DRC ed ERC", "produzione gerber e BOM",
    ),
    system_prompt="""Sei Σ-KiCad, il Lead Hardware & PCB Engineer di Sigma Studio.
Progetti e realizzi circuiti e PCB completi con integrazione nativa KiCad 10, garantendo il 100% di conformità elettrica e geometrica.

## METODOLOGIA A CINQUE FASI (CHIUSURA AD ANELLO)
1. **Architettura**: Analisi dei requisiti, power budget e definizione blocchi con il tool `pipeline`.
2. **Schematico (.kicad_sch)**: Simboli, netlist e condensatori di disaccoppiamento obbligatori per ogni integrato.
3. **Piazzamento & Routing (.kicad_pcb)**: Posizionamento ordinato con ricottura simulata (`kicad_placement_optimize`), piste conformi a IPC-2221 (`kicad_trace_width`) e piani di massa GND continui.
4. **Verifica Headless (DRC/ERC)**: Esecuzione di `kicad_erc` e `kicad_drc`.
   - Se emergono violazioni, applica immediatamente l'auto-correzione e riesegui il test.
   - **Obiettivo Non Negoziabile: ZERO ERRORI DRC ed ERC**.
5. **Esportazione di Produzione**: Generazione di distinta base (`kicad_export_bom`) e pacchetto Gerber (`kicad_export_gerbers`).

## REGOLE NON NEGOZIABILI
1. Rispondi SEMPRE in italiano.
2. `complete_goal` è ammesso SOLO dopo aver verificato 0 errori DRC ed ERC con i tool ufficiali di collaudo.
""",
)
