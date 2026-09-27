# ==============================================================================
# sigma_kicad_lab/tool_schemas.py - Gli schemi dei tool KiCad, per il modello
# ==============================================================================
"""Il catalogo che un agente legge: ogni tool con i suoi parametri.

Vive nel modulo perche' e' il modulo a possedere questi tool. Il kernel
(`core/harness/`) sa smistare una chiamata e applicare i permessi, non sa cosa
sia una pista: gli schemi arrivano al kernel dal provider, che si registra da
solo con `register_harness_tools()`.

I pad si indicano per riferimento e numero, le net per nome: un modello non
deve tenere a mente indici interni fra una chiamata e l'altra.
"""
from core.harness.tool_schema import function_schema as _f, STRINGA, INTERO

# --- KiCad: progettare una scheda vera ---------------------------------------
#: I pad si indicano per riferimento e numero, le net per nome: un agente non
#: deve tenere a mente indici interni fra una chiamata e l'altra.
_XY = {"type": "number"}
_PUNTI_MM = {"type": "array", "items": {
    "type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}}

SCHEMI = [
    _f("kicad_status", "KiCad e' installato? Che versione? Che progetto e' aperto? Chiamalo per primo.", {}, []),
    _f("kicad_open", "Apre un progetto KiCad (cartella, .kicad_pro o .kicad_pcb) e lo rende quello corrente.",
       {"path": STRINGA}, ["path"]),
    _f("kicad_board_read", "Contorno, numero di pezzi e di net della scheda aperta.", {}, []),
    _f("kicad_list_parts", "I footprint sulla scheda: riferimento, valore, posizione, lato, numero di pad.", {}, []),
    _f("kicad_pads", "I pad di un footprint con net e posizione assoluta. Chiamalo PRIMA di instradare.",
       {"part": STRINGA}, ["part"]),
    _f("kicad_nets", "Le net della scheda, con quanti pad tocca ciascuna.", {}, []),
    _f("kicad_trace_width", "Larghezza minima di una pista per una corrente, secondo IPC-2221.",
       {"current_a": {"type": "number"}, "delta_t_c": {"type": "number"},
        "thickness_oz": {"type": "number"},
        "layer": {"type": "string", "enum": ["external", "internal"]}}, ["current_a"]),
    _f("kicad_board_evaluate", "Giudica il piazzamento: sovrapposizioni, contorno, distanze, disaccoppiamento.", {}, []),
    _f("kicad_placement_optimize", "Calcola un piazzamento migliore. NON scrive: restituisce gli spostamenti proposti.",
       {"iterations": INTERO, "seed": INTERO,
        "lock": {"type": "array", "items": STRINGA}}, []),
    _f("kicad_placement_apply", "Riscrive le posizioni nel .kicad_pcb. Con dry_run non tocca il file.",
       {"moves": {"type": "array", "items": {"type": "object", "properties": {
           "reference": STRINGA, "x_mm": _XY, "y_mm": _XY, "rotation": INTERO},
           "required": ["reference", "x_mm", "y_mm"]}},
        "dry_run": {"type": "boolean"}}, ["moves"]),
    _f("kicad_add_track", "Traccia un segmento di pista fra due punti, in millimetri.",
       {"start": {"type": "array", "items": _XY}, "end": {"type": "array", "items": _XY},
        "width_mm": _XY, "layer": STRINGA, "net": STRINGA},
       ["start", "end", "width_mm"]),
    _f("kicad_add_route", "Instrada una spezzata fra piu' punti: il modo normale di collegare due pad.",
       {"points": _PUNTI_MM, "width_mm": _XY, "layer": STRINGA, "net": STRINGA},
       ["points", "width_mm"]),
    _f("kicad_add_via", "Mette un via passante fra due layer di rame.",
       {"at": {"type": "array", "items": _XY}, "size_mm": _XY, "drill_mm": _XY,
        "net": STRINGA, "layers": {"type": "array", "items": STRINGA}}, ["at"]),
    _f("kicad_add_footprint", "Mette un footprint sulla scheda: fori di fissaggio, fiducial, schermature.",
       {"library_id": STRINGA, "reference": STRINGA, "value": STRINGA,
        "x_mm": _XY, "y_mm": _XY, "rotation": _XY, "layer": STRINGA,
        "pads": {"type": "array", "items": {"type": "object"}}},
       ["library_id", "reference", "value", "x_mm", "y_mm"]),
    _f("kicad_remove_footprint", "Toglie un footprint dalla scheda. Il rame che lo raggiungeva resta.",
       {"reference": STRINGA}, ["reference"]),
    _f("kicad_undo", "Annulla l'ultima scrittura sul PCB, dalla copia fatta prima di applicarla.", {}, []),
    _f("kicad_redo",
       "Riapplica l'ultima scrittura annullata con `kicad_undo`. L'annullamento si "
       "fa per passi, e senza il passo che torna avanti un errore si corregge una "
       "volta sola.", {}, []),
    _f("kicad_drc", "Design Rule Check di KiCad sul PCB: la prova che il rame sta in piedi. Obbligatorio prima di complete_goal.", {}, []),
    _f("kicad_erc", "Electrical Rule Check sullo schematico.", {}, []),
    _f("kicad_export_gerbers", "Gerber e file di foratura: il pacchetto che si manda in fabbrica.",
       {"output_dir": STRINGA}, []),
    _f("kicad_export_bom", "La distinta base, dallo schematico.", {"output_path": STRINGA}, []),
    _f("kicad_render", "Un immagine della scheda (3d o svg), cosi il lavoro si puo guardare.",
       {"output_path": STRINGA, "mode": {"type": "string", "enum": ["3d", "svg"]}}, []),
    # pcbnew bridge: creazione e ispezione diretta via API pcbnew
    _f("kicad_pcbnew_status",
       "Verifica che il ponte pcbnew sia disponibile prima di creare o leggere schede: restituisce versione di KiCad e percorsi trovati. Usalo come primo passo quando non sai se l'ambiente e pronto.",
       {}, []),
    _f("kicad_libraries",
       "Elenco delle librerie di footprint installate. Usalo per scegliere la libreria giusta prima di cercare un footprint o aggiungerlo alla scheda.",
       {}, []),
    _f("kicad_search_footprint",
       "Cerca footprint nelle librerie KiCad per nome o parola chiave. Usalo quando conosci il tipo di componente (es. C_0805, R_0402) ma non la libreria esatta.",
       {"query": STRINGA,
        "limite": {"type": "integer", "default": 20},
        "libreria": STRINGA}, ["query"]),
    _f("kicad_new_board",
       "Crea una nuova scheda KiCad vuota con le dimensioni date. Usalo per iniziare un progetto PCB da zero, prima di aggiungere componenti.",
       {"percorso": STRINGA,
        "larghezza_mm": _XY,
        "altezza_mm": _XY,
        "net": {"type": "array", "items": STRINGA},
        "sovrascrivi": {"type": "boolean", "default": False}}, ["percorso"]),
    _f("kicad_add_part",
       "Aggiunge un componente (footprint) a una scheda esistente, con posizione, rotazione e net per pad. Usalo dopo kicad_new_board per popolare la scheda.",
       {"percorso": STRINGA,
        "libreria": STRINGA,
        "footprint": STRINGA,
        "riferimento": STRINGA,
        "valore": STRINGA,
        "x_mm": _XY, "y_mm": _XY,
        "rotazione": _XY,
        "lato": {"type": "string", "enum": ["top", "bottom"],
                  "default": "top"},
        "net_per_pad": {"type": "object"}},
       ["percorso", "libreria", "footprint", "riferimento"]),
    _f("kicad_read_board_full",
       "Legge lo stato completo di una scheda KiCad: dimensioni, componenti, net. Usalo per verificare che kicad_new_board e kicad_add_part abbiano prodotto il risultato atteso.",
       {"percorso": STRINGA}, ["percorso"]),
]



# --- correzione di una scheda che c'e' gia' -----------------------------------

SCHEMI += [
    _f("kicad_move_footprint",
       "Sposta un footprint, e se serve lo ruota. E' il tool con cui si corregge "
       "un piazzamento sbagliato: senza, l'unico rimedio era togliere il pezzo e "
       "rimetterlo. Se `rotation` non c'e', l'orientamento resta quello che "
       "c'era — un trascinamento non deve raddrizzare un pezzo ruotato apposta.",
       {"reference": STRINGA, "x_mm": _XY, "y_mm": _XY,
        "rotation": {"type": "number"}}, ["reference", "x_mm", "y_mm"]),
    _f("kicad_rename_footprint",
       "Cambia il riferimento e/o il valore di un footprint. Il riferimento nuovo "
       "dev'essere libero: due pezzi con lo stesso nome non si distinguono piu'.",
       {"reference": STRINGA, "new_reference": STRINGA, "value": STRINGA},
       ["reference"]),
    _f("kicad_delete_track",
       "Toglie la pista che unisce due punti: sono gli estremi a identificarla, e "
       "l'ordine non conta. Se non sei sicuro di dove sia, guarda prima le piste "
       "con `kicad_board_read`.",
       {"start": {"type": "array", "items": _XY},
        "end": {"type": "array", "items": _XY},
        "layer": STRINGA}, ["start", "end"]),
    _f("kicad_delete_via",
       "Toglie il via che sta in un punto, in millimetri.",
       {"at": {"type": "array", "items": _XY}}, ["at"]),
    _f("kicad_set_board_outline",
       "Sostituisce il contorno della scheda con un rettangolo con un angolo in "
       "(0, 0). E' una sostituzione: i segmenti Edge.Cuts che c'erano vengono "
       "rimossi, perche' due contorni sono una scheda che KiCad non sa tagliare.",
       {"width_mm": _XY, "height_mm": _XY}, ["width_mm", "height_mm"]),
    _f("kicad_set_pad_net",
       "Assegna una net al pad di un footprint, creando la net se non esiste. E' "
       "l'unico modo di dire a cosa serve un pad: la net non si vede dal disegno, "
       "e un pad senza net e' un collegamento che nessuno puo' verificare.",
       {"reference": STRINGA, "pad": STRINGA, "net": STRINGA},
       ["reference", "pad", "net"]),
]
