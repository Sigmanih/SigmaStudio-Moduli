# ==============================================================================
# sigma_kicad_lab/pcbnew_worker.py — Il lavoratore che gira DENTRO KiCad
# ==============================================================================
"""Questo file non viene mai importato da Sigma Studio.

Lo esegue l'interprete di KiCad — `C:\\Program Files\\KiCad\\10.0\\bin\\python.exe`
— che e' l'unico posto dove `import pcbnew` funziona. Riceve un comando e i
suoi argomenti come JSON sullo standard input, e stampa una riga JSON sola.

**Perche' un file vero e non una stringa.** Il primo tentativo costruiva questo
codice come lista di stringhe Python dentro Python: ogni riga andava quotata a
mano, e una virgola mancante rompeva tutto. Ci si e' persa mezz'ora su errori
di sintassi che non c'entravano niente con KiCad. Qui e' codice normale: lo
legge un editor, lo controlla un linter, e un errore di battitura si vede.

L'output e' preceduto da un marcatore perche' pcbnew scrive avvisi suoi sullo
stdout: senza, il JSON arriverebbe mescolato a quelli e il parsing salterebbe.
"""
import json
import os
import sys
import traceback

MARCATORE = "@@SIGMA_JSON@@"

try:
    import pcbnew
except ImportError as exc:                       # pragma: no cover
    print(MARCATORE + json.dumps(
        {"ok": False, "errore": f"pcbnew non importabile: {exc}"}))
    sys.exit(0)


# --- servizio ------------------------------------------------------------------

def _mm(valore):
    """Da unita' interne KiCad a millimetri."""
    return round(pcbnew.ToMM(valore), 4)


def _ui(valore):
    """Da millimetri a unita' interne KiCad."""
    return pcbnew.FromMM(float(valore))


def _nets(board):
    """Le net della scheda per nome. Le chiavi sono wxString: si convertono.

    `sorted()` su wxString solleva TypeError — non implementano il confronto.
    Convertire a str qui evita che ogni chiamante ci ricaschi.
    """
    return {str(nome): net for nome, net in board.GetNetInfo().NetsByName().items()}


def _percorso_libreria(base, libreria):
    if libreria.endswith(".pretty"):
        return os.path.join(base, libreria)
    return os.path.join(base, libreria + ".pretty")


# --- comandi -------------------------------------------------------------------

def cmd_versione(_args):
    return {"ok": True, "versione": pcbnew.GetBuildVersion()}


def cmd_elenca_librerie(args):
    base = args["cartella_librerie"]
    if not os.path.isdir(base):
        return {"ok": False, "errore": f"Cartella librerie inesistente: {base}"}
    nomi = sorted(d[:-len(".pretty")] for d in os.listdir(base)
                  if d.endswith(".pretty"))
    return {"ok": True, "totale": len(nomi), "librerie": nomi}


def cmd_cerca_footprint(args):
    base = args["cartella_librerie"]
    query = str(args.get("query", "")).lower()
    limite = int(args.get("limite", 20))
    solo = args.get("libreria")

    if not os.path.isdir(base):
        return {"ok": False, "errore": f"Cartella librerie inesistente: {base}"}

    cartelle = ([_percorso_libreria(base, solo)] if solo else
                [os.path.join(base, d) for d in sorted(os.listdir(base))
                 if d.endswith(".pretty")])

    trovati = []
    for cartella in cartelle:
        if not os.path.isdir(cartella):
            continue
        nome_lib = os.path.basename(cartella)[:-len(".pretty")]
        try:
            for nome in pcbnew.FootprintEnumerate(cartella):
                if query and query not in str(nome).lower():
                    continue
                trovati.append({"libreria": nome_lib, "footprint": str(nome)})
                if len(trovati) >= limite:
                    return {"ok": True, "totale": len(trovati),
                            "risultati": trovati, "troncato": True}
        except Exception:
            # Una libreria illeggibile non deve far fallire la ricerca intera.
            continue
    return {"ok": True, "totale": len(trovati), "risultati": trovati,
            "troncato": False}


def cmd_crea_scheda(args):
    percorso = args["percorso"]
    larghezza = float(args["larghezza_mm"])
    altezza = float(args["altezza_mm"])
    if larghezza <= 0 or altezza <= 0:
        return {"ok": False, "errore": "Le dimensioni devono essere positive."}
    if os.path.exists(percorso) and not args.get("sovrascrivi"):
        return {"ok": False,
                "errore": f"Esiste gia': {percorso}. Passa sovrascrivi=true per rifarlo."}

    board = pcbnew.BOARD()
    for nome in (args.get("net") or []):
        board.Add(pcbnew.NETINFO_ITEM(board, str(nome)))

    # Il contorno su Edge.Cuts: senza, KiCad non sa dove finisce la scheda e
    # meta' dei controlli di produzione non hanno un riferimento.
    angoli = [(0, 0), (larghezza, 0), (larghezza, altezza), (0, altezza)]
    for i in range(4):
        x1, y1 = angoli[i]
        x2, y2 = angoli[(i + 1) % 4]
        linea = pcbnew.PCB_SHAPE(board)
        linea.SetShape(pcbnew.SHAPE_T_SEGMENT)
        linea.SetStart(pcbnew.VECTOR2I(_ui(x1), _ui(y1)))
        linea.SetEnd(pcbnew.VECTOR2I(_ui(x2), _ui(y2)))
        linea.SetLayer(pcbnew.Edge_Cuts)
        linea.SetWidth(_ui(0.05))
        board.Add(linea)

    os.makedirs(os.path.dirname(os.path.abspath(percorso)), exist_ok=True)
    pcbnew.SaveBoard(percorso, board)

    # KiCad scarta al salvataggio le net che nessun pad usa: riaprendo il file
    # non ci sono piu'. Non e' un difetto, e' come funziona — una net senza
    # connessioni non e' informazione di progetto. Si dichiara nel risultato,
    # perche' un chiamante che le ha elencate ha diritto di sapere che
    # esisteranno solo quando un componente le usera'.
    rilette = sorted(n for n in _nets(pcbnew.LoadBoard(percorso)) if n)
    richieste = [str(n) for n in (args.get("net") or [])]
    return {"ok": True, "percorso": percorso, "larghezza_mm": larghezza,
            "altezza_mm": altezza,
            "net_richieste": richieste,
            "net_nel_file": rilette,
            "net_non_persistite": sorted(set(richieste) - set(rilette)),
            "nota": ("Le net senza pad non vengono salvate da KiCad: "
                     "compariranno quando un componente le usera'.")
                    if set(richieste) - set(rilette) else ""}


def cmd_aggiungi_componente(args):
    percorso = args["percorso"]
    if not os.path.isfile(percorso):
        return {"ok": False, "errore": f"Scheda inesistente: {percorso}"}

    board = pcbnew.LoadBoard(percorso)
    riferimento = str(args["riferimento"])

    # Due pezzi con lo stesso riferimento rendono ambiguo ogni comando
    # successivo che li nomini, compresi quelli di un agente.
    if board.FindFootprintByReference(riferimento):
        return {"ok": False,
                "errore": f"Il riferimento '{riferimento}' e' gia' usato su questa scheda."}

    cartella = _percorso_libreria(args["cartella_librerie"], args["libreria"])
    if not os.path.isdir(cartella):
        return {"ok": False, "errore": f"Libreria inesistente: {cartella}"}

    try:
        fp = pcbnew.FootprintLoad(cartella, str(args["footprint"]))
    except Exception as exc:
        return {"ok": False, "errore": f"Caricamento fallito: {exc}"}
    if fp is None:
        return {"ok": False,
                "errore": f"Footprint '{args['footprint']}' non trovato in {args['libreria']}."}

    fp.SetReference(riferimento)
    fp.SetValue(str(args.get("valore", "")))
    fp.SetPosition(pcbnew.VECTOR2I(_ui(args["x_mm"]), _ui(args["y_mm"])))
    rotazione = float(args.get("rotazione", 0) or 0)
    if rotazione:
        fp.SetOrientationDegrees(rotazione)

    nets = _nets(board)
    mappa = args.get("net_per_pad") or {}
    assegnati, mancanti = [], []
    for pad in fp.Pads():
        numero = str(pad.GetNumber())
        nome_net = mappa.get(numero)
        if not nome_net:
            continue
        if nome_net not in nets:
            board.Add(pcbnew.NETINFO_ITEM(board, str(nome_net)))
            nets = _nets(board)
        if nome_net in nets:
            pad.SetNet(nets[nome_net])
            assegnati.append({"pad": numero, "net": nome_net})
        else:
            mancanti.append(numero)

    board.Add(fp)
    pcbnew.SaveBoard(percorso, board)
    return {"ok": True, "riferimento": riferimento,
            "footprint": str(fp.GetFPIDAsString()),
            "pad": fp.GetPadCount(), "net_assegnate": assegnati,
            "pad_senza_net": mancanti,
            "x_mm": float(args["x_mm"]), "y_mm": float(args["y_mm"]),
            "rotazione": rotazione}


def cmd_leggi_scheda(args):
    percorso = args["percorso"]
    if not os.path.isfile(percorso):
        return {"ok": False, "errore": f"Scheda inesistente: {percorso}"}

    board = pcbnew.LoadBoard(percorso)
    riquadro = board.GetBoardEdgesBoundingBox()

    componenti = []
    for fp in board.GetFootprints():
        pads = [{"numero": str(p.GetNumber()), "net": str(p.GetNetname()),
                 "x_mm": _mm(p.GetPosition().x), "y_mm": _mm(p.GetPosition().y)}
                for p in fp.Pads()]
        componenti.append({
            "riferimento": str(fp.GetReference()),
            "valore": str(fp.GetValue()),
            "footprint": str(fp.GetFPIDAsString()),
            "x_mm": _mm(fp.GetPosition().x), "y_mm": _mm(fp.GetPosition().y),
            "rotazione": fp.GetOrientationDegrees(),
            "lato": "bottom" if fp.IsFlipped() else "top",
            "pad": pads,
        })

    piste, via = [], []
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            via.append({"x_mm": _mm(t.GetPosition().x),
                        "y_mm": _mm(t.GetPosition().y),
                        "diametro_mm": _mm(t.GetWidth()),
                        "foro_mm": _mm(t.GetDrill()),
                        "net": str(t.GetNetname())})
        else:
            piste.append({"da": [_mm(t.GetStart().x), _mm(t.GetStart().y)],
                          "a": [_mm(t.GetEnd().x), _mm(t.GetEnd().y)],
                          "larghezza_mm": _mm(t.GetWidth()),
                          "layer": str(board.GetLayerName(t.GetLayer())),
                          "net": str(t.GetNetname())})

    return {"ok": True, "percorso": percorso,
            "larghezza_mm": _mm(riquadro.GetWidth()),
            "altezza_mm": _mm(riquadro.GetHeight()),
            "componenti": componenti, "totale_componenti": len(componenti),
            "piste": piste, "via": via,
            "net": sorted(n for n in _nets(board) if n)}


COMANDI = {
    "versione": cmd_versione,
    "elenca_librerie": cmd_elenca_librerie,
    "cerca_footprint": cmd_cerca_footprint,
    "crea_scheda": cmd_crea_scheda,
    "aggiungi_componente": cmd_aggiungi_componente,
    "leggi_scheda": cmd_leggi_scheda,
}


def main():
    try:
        richiesta = json.loads(sys.stdin.read() or "{}")
        comando = richiesta.get("comando")
        funzione = COMANDI.get(comando)
        if funzione is None:
            esito = {"ok": False,
                     "errore": f"Comando '{comando}' sconosciuto. "
                               f"Disponibili: {', '.join(sorted(COMANDI))}."}
        else:
            esito = funzione(richiesta.get("argomenti") or {})
    except Exception as exc:
        esito = {"ok": False, "errore": str(exc),
                 "traccia": traceback.format_exc()[-800:]}

    print(MARCATORE + json.dumps(esito, ensure_ascii=False))


if __name__ == "__main__":
    main()
