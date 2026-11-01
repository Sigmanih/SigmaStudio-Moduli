"""Contratti dell'editor per produzione, costruttori e regole del progetto."""
import json
import math
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from core.store import JsonStore
from core.harness.tool_schema import function_schema


def _tools():
    from . import tools
    return tools


def _native(name, action, **arguments):
    from . import pcbnew_bridge
    tools = _tools()
    result = pcbnew_bridge._esegui("modifica_scheda", {"percorso": str(tools._pcb()),
                                                     "action": action, **arguments})
    if result.get("ok") and result.get("backup"):
        from .pcb_writer import WriteResult
        tools._ricorda(WriteResult(True, action, {}, result["backup"]))
    return tools._esito_dal_ponte(name, result)


def kicad_zone_add(points, net, layer="F.Cu", clearance_mm=0.2):
    return _native("kicad_zone_add", "zone", points=points, net=net,
                   layer=layer, clearance_mm=clearance_mm)


def kicad_constructor_hole(reference, x_mm, y_mm, diameter_mm=3.2):
    return _native("kicad_constructor_hole", "hole", reference=reference,
                   x_mm=x_mm, y_mm=y_mm, diameter_mm=diameter_mm)


def kicad_constructor_fiducial(reference, x_mm, y_mm, diameter_mm=1, layer="F.Cu"):
    return _native("kicad_constructor_fiducial", "fiducial", reference=reference,
                   x_mm=x_mm, y_mm=y_mm, diameter_mm=diameter_mm, layer=layer)


def kicad_constructor_testpoint(reference, x_mm, y_mm, net, diameter_mm=1, layer="F.Cu"):
    return _native("kicad_constructor_testpoint", "testpoint", reference=reference,
                   x_mm=x_mm, y_mm=y_mm, diameter_mm=diameter_mm, layer=layer, net=net)


def kicad_constructor_silkscreen(text, x_mm, y_mm, size_mm=1, layer="F.Cu"):
    return _native("kicad_constructor_silkscreen", "silkscreen", text=text,
                   x_mm=x_mm, y_mm=y_mm, size_mm=size_mm, layer=layer)


def kicad_constructor_outline(width_mm, height_mm):
    return dict(_tools().kicad_set_board_outline(width_mm, height_mm), tool="kicad_constructor_outline")


def _backup(path):
    if path.is_file():
        directory = path.parent / ".sigma_backups"
        directory.mkdir(exist_ok=True)
        backup = directory / f"{path.stem}-{uuid.uuid4().hex}{path.suffix}"
        shutil.copy2(path, backup)
        return str(backup)
    return None


def kicad_netclass_set(name, clearance_mm=0.2, track_width_mm=0.25, via_diameter_mm=0.8,
                      via_drill_mm=0.4, net_pattern=""):
    if not str(name).strip():
        raise ValueError("Nome della classe obbligatorio.")
    values = [float(value) for value in (clearance_mm, track_width_mm, via_diameter_mm, via_drill_mm)]
    if any(not math.isfinite(value) or value <= 0 for value in values) or values[3] >= values[2]:
        raise ValueError("Misure non valide: il foro del via deve essere minore del diametro.")
    tools = _tools()
    destination = Path(tools._project().get("pro") or tools._pcb().with_suffix(".kicad_pro"))

    def update(config):
        settings = config.setdefault("net_settings", {})
        classes = settings.setdefault("classes", [])
        entry = next((item for item in classes if item.get("name") == name), None)
        if entry is None:
            entry = {"name": name}
            classes.append(entry)
        entry.update(clearance=values[0], track_width=values[1], via_diameter=values[2], via_drill=values[3])
        if net_pattern:
            patterns = settings.setdefault("netclass_patterns", [])
            patterns[:] = [item for item in patterns if item.get("pattern") != net_pattern]
            patterns.append({"netclass": name, "pattern": net_pattern})
        return config

    if destination.is_file():
        json.loads(destination.read_text(encoding="utf-8"))
    backup = _backup(destination)
    JsonStore(str(destination)).update(update)
    return tools._esito("kicad_netclass_set", True, output_path=str(destination), backup=backup)


def kicad_rules_set(rules):
    from .kicad_parser import parse_sexpr
    if not isinstance(rules, str) or not rules.strip() or len(rules.encode()) > 65536:
        raise ValueError("Le regole devono essere testo non vuoto, entro 64 KiB.")
    tree = parse_sexpr(rules)
    if not tree or tree[0] != ["version", "1"]:
        raise ValueError("Le regole devono iniziare con (version 1).")
    tools = _tools()
    destination = tools._pcb().with_suffix(".kicad_dru")
    backup = _backup(destination)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(rules)
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return tools._esito("kicad_rules_set", True, output_path=str(destination), backup=backup,
                        validation="sintassi; validazione elettrica da eseguire con DRC")


def kicad_sync_netlist(netlist_path=""):
    tools = _tools()
    from . import kicad_cli
    with tempfile.TemporaryDirectory(prefix="sigma-netlist-") as directory:
        path = Path(netlist_path) if netlist_path else Path(directory) / "netlist.xml"
        if not netlist_path:
            kicad_cli.export_netlist(tools._sch(), path)
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Netlist assente o oltre 20 MiB.")
        text = path.read_text(encoding="utf-8")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("Dichiarazioni XML non consentite nella netlist.")
        root = ET.fromstring(text)
        if root.tag != "export":
            raise ValueError("Serve una netlist XML esportata da KiCad.")
        assignments = []
        for net in root.findall("./nets/net"):
            for node in net.findall("node"):
                assignments.append({"net": net.attrib["name"], "reference": node.attrib["ref"],
                                    "pad": node.attrib["pin"]})
        if not assignments:
            raise ValueError("La netlist non contiene connessioni da sincronizzare.")
        return _native("kicad_sync_netlist", "sync_netlist", assignments=assignments)


def kicad_export_drill(output_dir=""):
    from . import kicad_cli
    tools = _tools()
    result = kicad_cli.export_drill(tools._pcb(), Path(output_dir) if output_dir else None)
    return tools._esito_dal_ponte("kicad_export_drill", result)


def kicad_export_pickplace(output_path=""):
    from . import kicad_cli
    tools = _tools()
    result = kicad_cli.export_positions(tools._pcb(), Path(output_path) if output_path else None)
    return tools._esito_dal_ponte("kicad_export_pickplace", result)


def kicad_bom_export(output_path=""):
    return dict(_tools().kicad_export_bom(output_path), tool="kicad_bom_export")


def kicad_render_3d(output_path=""):
    return dict(_tools().kicad_render(output_path, "3d"), tool="kicad_render_3d")


EXECUTORS = {function.__name__: function for function in (
    kicad_zone_add, kicad_constructor_hole, kicad_constructor_fiducial,
    kicad_constructor_testpoint, kicad_constructor_silkscreen, kicad_constructor_outline,
    kicad_netclass_set, kicad_rules_set, kicad_sync_netlist, kicad_export_drill,
    kicad_export_pickplace, kicad_bom_export, kicad_render_3d,
)}


def schemas():
    import inspect
    strings = {"reference", "net", "layer", "text", "name", "net_pattern", "rules",
               "netlist_path", "output_dir", "output_path"}
    descriptions = {
        "kicad_zone_add": "Aggiunge il poligono di una zona di rame; il riempimento resta da eseguire in KiCad.",
        "kicad_sync_netlist": "Sincronizza le net sui pad già presenti da una netlist XML KiCad, senza creare componenti.",
        "kicad_rules_set": "Salva regole DRC del progetto; richiede un successivo controllo DRC.",
    }
    result = []
    for name, function in EXECUTORS.items():
        properties, required = {}, []
        for key, parameter in inspect.signature(function).parameters.items():
            properties[key] = ({"type": "string"} if key in strings else {"type": "number"})
            if key == "points":
                properties[key] = {"type": "array", "minItems": 3, "items": {
                    "type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}}
            if parameter.default is inspect.Parameter.empty:
                required.append(key)
        result.append(function_schema(name, descriptions.get(name, name.replace("kicad_", "").replace("_", " ")),
                                      properties, required))
    return result
