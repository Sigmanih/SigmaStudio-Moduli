"""Modifiche native aggiuntive, eseguite nell'interprete pcbnew del worker."""
import math
import os
import shutil
import tempfile
import uuid
from pathlib import Path


def _number(value, *, positive=False):
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("Misura non valida: serve un numero finito e positivo.")
    return number


def _save(pcbnew, board, path):
    directory = path.parent / ".sigma_backups"
    directory.mkdir(exist_ok=True)
    backup = directory / f"{path.stem}-{uuid.uuid4().hex}.kicad_pcb"
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".kicad_pcb", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        pcbnew.SaveBoard(str(temporary), board)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("KiCad non ha salvato la scheda.")
        pcbnew.LoadBoard(str(temporary))
        shutil.copy2(path, backup)
        os.utime(backup, None)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return str(backup)


def edit_board(pcbnew, args):
    path = Path(args["percorso"])
    if not path.is_file():
        raise ValueError(f"Scheda inesistente: {path}")
    board = pcbnew.LoadBoard(str(path))
    action = args["action"]
    x, y = _number(args.get("x_mm", 0)), _number(args.get("y_mm", 0))
    position = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    layer = args.get("layer", "F.Cu")
    layer_id = board.GetLayerID(layer)
    if layer_id < 0:
        raise ValueError(f"Layer inesistente: {layer}")
    if action == "zone":
        if layer not in ("F.Cu", "B.Cu") and not (layer.startswith("In") and layer.endswith(".Cu")):
            raise ValueError("La zona deve appartenere a un layer di rame.")
        points = args.get("points") or []
        if not 3 <= len(points) <= 10000:
            raise ValueError("Il poligono richiede da 3 a 10.000 punti.")
        points = [(_number(point[0]), _number(point[1])) for point in points]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
        if abs(area) < 1e-9:
            raise ValueError("Il poligono della zona ha area nulla.")
        net = board.FindNet(str(args["net"]))
        if net is None or not net.GetNetname():
            raise ValueError("La net della zona deve già esistere sulla scheda.")
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer_id)
        zone.SetNetCode(net.GetNetCode())
        zone.SetLocalClearance(pcbnew.FromMM(_number(args.get("clearance_mm", 0.2), positive=True)))
        outline = zone.Outline()
        outline.NewOutline()
        for px, py in points:
            outline.Append(pcbnew.FromMM(px), pcbnew.FromMM(py))
        board.Add(zone)
    elif action in ("hole", "fiducial", "testpoint"):
        reference = str(args["reference"]).strip()
        if not reference or board.FindFootprintByReference(reference):
            raise ValueError("Il riferimento deve essere non vuoto e libero.")
        diameter = _number(args.get("diameter_mm", 3.2 if action == "hole" else 1), positive=True)
        footprint = pcbnew.FOOTPRINT(board)
        footprint.SetReference(reference)
        footprint.SetValue({"hole": "MountingHole", "fiducial": "Fiducial", "testpoint": "TestPoint"}[action])
        footprint.SetPosition(position)
        pad = pcbnew.PAD(footprint)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(diameter), pcbnew.FromMM(diameter)))
        pad.SetPosition(position)
        if action == "hole":
            pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(diameter), pcbnew.FromMM(diameter)))
            pad.SetLayerSet(pcbnew.LSET.AllCuMask())
        else:
            if layer not in ("F.Cu", "B.Cu"):
                raise ValueError("Fiducial e testpoint richiedono F.Cu o B.Cu.")
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetNumber("1" if action == "testpoint" else "")
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.F_Cu)
            layers.AddLayer(pcbnew.F_Mask)
            pad.SetLayerSet(layers)
            net_name = str(args.get("net", ""))
            if action == "testpoint":
                net = board.FindNet(net_name)
                if net is None or not net_name:
                    raise ValueError("Il testpoint richiede una net già esistente.")
                pad.SetNet(net)
        footprint.Add(pad)
        board.Add(footprint)
        if layer == "B.Cu":
            footprint.Flip(position, True)
    elif action == "silkscreen":
        text = str(args.get("text", "")).strip()
        if not text or len(text) > 1000:
            raise ValueError("La serigrafia richiede testo da 1 a 1.000 caratteri.")
        label = pcbnew.PCB_TEXT(board)
        label.SetText(text)
        label.SetPosition(position)
        label.SetLayer(pcbnew.B_SilkS if layer == "B.Cu" else pcbnew.F_SilkS)
        size = pcbnew.FromMM(_number(args.get("size_mm", 1), positive=True))
        label.SetTextSize(pcbnew.VECTOR2I(size, size))
        board.Add(label)
    elif action == "sync_netlist":
        assignments = args["assignments"]
        pads = []
        for entry in assignments:
            footprint = board.FindFootprintByReference(str(entry["reference"]))
            pad = footprint.FindPadByNumber(str(entry["pad"])) if footprint else None
            if pad is None:
                raise ValueError(f"Pad assente: {entry['reference']}.{entry['pad']}; sincronizzazione annullata.")
            if not str(entry["net"]).strip():
                raise ValueError("Nome di net vuoto.")
            pads.append((pad, str(entry["net"])))
        for pad, name in pads:
            net = board.FindNet(name)
            if net is None:
                net = pcbnew.NETINFO_ITEM(board, name)
                board.Add(net)
            pad.SetNet(net)
    else:
        raise ValueError(f"Operazione non disponibile: {action}")
    return {"ok": True, "operation": action, "backup": _save(pcbnew, board, path),
            "percorso": str(path), "zones_filled": False if action == "zone" else None}
