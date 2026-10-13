"""Timeline non distruttiva di una produzione.

La produzione genera clip; la timeline decide come si usano. Un elemento della
traccia video punta a una *versione* (take) di un'inquadratura e ne usa un
intervallo [src_in, src_out]: tagliare, accorciare o spostare non tocca i file,
e rigenerare un'inquadratura aggiunge una versione invece di sovrascrivere.

Le tracce audio contengono clip posizionate nel tempo della timeline (dialoghi,
voci fuori campo, musica, effetti). L'audio generato da H3 insieme al video non
e' una traccia a parte: segue gli elementi video e si regola dalla traccia
`clip` (volume, muto).

Ogni modifica passa da `apply_op`, che salva lo stato precedente nella
cronologia: annulla/ripeti sono uno scambio di stati, non operazioni inverse
da scrivere e mantenere una per una.
"""

from __future__ import annotations

import copy
import json
import os
import time
import uuid
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_timeline")

FPS = 24
HISTORY_LIMIT = 80
TRANSITIONS = ("cut", "fade", "dip")
AUDIO_KINDS = ("clip", "dialogue", "voice", "music", "sfx")
MIN_ITEM_S = 1.0 / FPS
EDITOR_ORIGINS = ("edit", "import", "title", "scene")
OVERLAY_STYLES = ("title", "lower", "caption")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _snap(t: float) -> float:
    """Allinea al fotogramma: tagli fra un frame e l'altro non esistono."""
    return round(round(float(t) * FPS) / FPS, 6)


# ---------------------------------------------------------------------------
# Versioni delle inquadrature
# ---------------------------------------------------------------------------

def ensure_takes(shot: dict) -> list[dict]:
    """Converte il clip singolo dei manifest precedenti in una lista di versioni."""
    takes = shot.setdefault("takes", [])
    if not takes and shot.get("clip_path"):
        takes.append({"id": "t1", "clip_path": shot["clip_path"], "last_frame": shot.get("last_frame", ""),
                      "seed": shot.get("seed"), "prompt": shot.get("prompt", ""), "frames": shot.get("frames", 0),
                      "created": shot.get("rendered_at") or time.time(), "kind": "render",
                      "timings": shot.get("timings", {})})
        shot["take"] = "t1"
    return takes


def add_take(shot: dict, clip_path: str, **meta) -> dict:
    takes = ensure_takes(shot)
    take = {"id": f"t{len(takes) + 1}", "clip_path": clip_path, "created": time.time(), **meta}
    takes.append(take)
    shot["take"] = take["id"]
    # I campi "piatti" restano allineati alla versione attiva: il runner e il
    # montaggio classico continuano a leggerli.
    shot["clip_path"] = clip_path
    shot["last_frame"] = meta.get("last_frame", shot.get("last_frame", ""))
    shot["frames"] = meta.get("frames", shot.get("frames", 0))
    return take


def active_take(shot: dict, take_id: str | None = None) -> dict | None:
    takes = ensure_takes(shot)
    wanted = take_id or shot.get("take")
    return next((t for t in takes if t["id"] == wanted), takes[-1] if takes else None)


def take_duration(take: dict) -> float:
    frames = int(take.get("frames") or 0)
    if frames:
        return frames / FPS
    from core.modules.sigma_creative_lab.video.production import probe
    try:
        info = probe(Path(take["clip_path"]))
        take["frames"] = info["frames"] or round(info["duration"] * FPS)
        return take["frames"] / FPS
    except Exception as e:
        log.warning(f"durata della versione {take.get('id')} non leggibile: {e}")
        return 0.0


# ---------------------------------------------------------------------------
# Costruzione e lettura
# ---------------------------------------------------------------------------

def empty_timeline() -> dict:
    return {"version": 0, "video": [],
            "audio": [{"id": _id("trk"), "kind": k, "name": n, "gain_db": g, "mute": False, "clips": []}
                      for k, n, g in (("clip", "Audio dei clip", 0.0), ("dialogue", "Dialoghi", 0.0),
                                      ("voice", "Voce fuori campo", 0.0), ("music", "Musica", -14.0),
                                      ("sfx", "Effetti", -6.0))],
            "markers": [], "overlays": []}


def build_from_shots(prod: dict) -> dict:
    """Prima timeline: le inquadrature completate in ordine, come il montaggio classico."""
    tl = empty_timeline()
    # Le inquadrature nate dall'editor (rigenerazioni, media importati, cartelli)
    # vivono solo nella timeline che le ha create: ricostruire dallo storyboard
    # non le reinserisce.
    done = [s for s in prod["shots"] if s.get("status") == "done" and s.get("origin") not in EDITOR_ORIGINS
            and (s.get("clip_path") or s.get("takes"))]
    for i, shot in enumerate(done):
        take = active_take(shot)
        if not take:
            continue
        dur = take_duration(take)
        # Un `continue` ripete come primo frame l'ultimo del clip precedente: lo si salta.
        src_in = (1.0 / FPS) if shot.get("transition") == "continue" and i > 0 else 0.0
        tl["video"].append({"id": _id("v"), "shot_id": shot["id"], "take_id": take["id"],
                            "src_in": src_in, "src_out": _snap(dur), "transition": {"type": "cut", "duration": 0.0}})
    music = Path(prod.get("soundtrack_path") or "")
    if music.is_file():
        track = audio_track(tl, "music")
        track["clips"].append({"id": _id("a"), "src": str(music), "start": 0.0, "src_in": 0.0,
                               "src_out": layout(tl, prod)["duration"], "gain_db": 0.0, "label": "Colonna sonora"})
    return tl


def audio_track(tl: dict, kind: str) -> dict:
    track = next((t for t in tl["audio"] if t["kind"] == kind), None)
    if track is None:
        track = {"id": _id("trk"), "kind": kind, "name": kind, "gain_db": 0.0, "mute": False, "clips": []}
        tl["audio"].append(track)
    return track


def shot_by_id(prod: dict, shot_id: str) -> dict | None:
    return next((s for s in prod["shots"] if s["id"] == shot_id), None)


def layout(tl: dict, prod: dict) -> dict:
    """Posizione assoluta di ogni elemento video (le dissolvenze sovrappongono i due lati)."""
    t = 0.0
    items = []
    for i, it in enumerate(tl["video"]):
        dur = max(MIN_ITEM_S, it["src_out"] - it["src_in"])
        overlap = it["transition"]["duration"] if i > 0 and it["transition"]["type"] == "fade" else 0.0
        start = max(0.0, t - overlap)
        shot = shot_by_id(prod, it["shot_id"]) or {}
        take = active_take(shot, it["take_id"]) if shot else None
        items.append({**it, "start": round(start, 6), "end": round(start + dur, 6), "duration": round(dur, 6),
                      "clip_path": (take or {}).get("clip_path", ""), "prompt": (take or {}).get("prompt") or shot.get("prompt", ""),
                      "scene": shot.get("scene", ""), "takes": len(shot.get("takes") or [])})
        t = start + dur
    return {"items": items, "duration": round(t, 6)}


def locate(tl: dict, prod: dict, t: float) -> tuple[int, float] | None:
    """Elemento video sotto l'istante t e posizione dentro la sorgente."""
    for i, it in enumerate(layout(tl, prod)["items"]):
        if it["start"] <= t < it["end"] or (i == len(tl["video"]) - 1 and abs(t - it["end"]) < 1e-6):
            return i, it["src_in"] + (t - it["start"])
    return None


# ---------------------------------------------------------------------------
# Operazioni
# ---------------------------------------------------------------------------

class TimelineError(ValueError):
    """Operazione non valida sulla timeline (messaggio leggibile dall'utente)."""


def _find(seq: list, item_id: str, what: str) -> tuple[int, dict]:
    for i, x in enumerate(seq):
        if x["id"] == item_id:
            return i, x
    raise TimelineError(f"{what} inesistente: {item_id}")


def _find_audio_clip(tl: dict, clip_id: str) -> tuple[dict, int, dict]:
    for track in tl["audio"]:
        for i, c in enumerate(track["clips"]):
            if c["id"] == clip_id:
                return track, i, c
    raise TimelineError(f"clip audio inesistente: {clip_id}")


def op_split(tl, prod, t):
    hit = locate(tl, prod, _snap(t))
    if not hit:
        raise TimelineError("nessun elemento in quel punto")
    i, src_t = hit
    it = tl["video"][i]
    src_t = _snap(src_t)
    if src_t - it["src_in"] < MIN_ITEM_S or it["src_out"] - src_t < MIN_ITEM_S:
        raise TimelineError("troppo vicino al bordo dell'elemento")
    right = {**copy.deepcopy(it), "id": _id("v"), "src_in": src_t, "transition": {"type": "cut", "duration": 0.0}}
    it["src_out"] = src_t
    tl["video"].insert(i + 1, right)
    return {"left": it["id"], "right": right["id"]}


def op_delete(tl, prod, item_id):
    i, _ = _find(tl["video"], item_id, "elemento")
    tl["video"].pop(i)
    return {}


def op_delete_range(tl, prod, t_a, t_b):
    """Toglie il tratto [a, b) dividendo gli elementi ai due estremi."""
    t_a, t_b = sorted((_snap(t_a), _snap(t_b)))
    if t_b - t_a < MIN_ITEM_S:
        raise TimelineError("intervallo troppo corto")
    for t in (t_b, t_a):
        try:
            op_split(tl, prod, t)
        except TimelineError:
            pass                       # gia' su un bordo
    lay = layout(tl, prod)["items"]
    keep = [tl["video"][k] for k, it in enumerate(lay) if not (it["start"] >= t_a - 1e-6 and it["end"] <= t_b + 1e-6)]
    removed = len(tl["video"]) - len(keep)
    tl["video"] = keep
    return {"removed": removed, "insert_at": next((k for k, it in enumerate(lay) if it["start"] >= t_a - 1e-6), len(lay)) }


def op_trim(tl, prod, item_id, src_in=None, src_out=None):
    _, it = _find(tl["video"], item_id, "elemento")
    shot = shot_by_id(prod, it["shot_id"])
    take = active_take(shot, it["take_id"]) if shot else None
    limit = take_duration(take) if take else it["src_out"]
    new_in = _snap(it["src_in"] if src_in is None else max(0.0, float(src_in)))
    new_out = _snap(it["src_out"] if src_out is None else min(limit, float(src_out)))
    if new_out - new_in < MIN_ITEM_S:
        raise TimelineError("l'elemento resterebbe vuoto")
    it["src_in"], it["src_out"] = new_in, new_out
    return {}


def op_move(tl, prod, item_id, index):
    i, it = _find(tl["video"], item_id, "elemento")
    tl["video"].pop(i)
    tl["video"].insert(max(0, min(int(index), len(tl["video"]))), it)
    return {}


def op_duplicate(tl, prod, item_id):
    i, it = _find(tl["video"], item_id, "elemento")
    tl["video"].insert(i + 1, {**copy.deepcopy(it), "id": _id("v")})
    return {}


def op_transition(tl, prod, item_id, type="cut", duration=0.5):
    if type not in TRANSITIONS:
        raise TimelineError(f"transizione sconosciuta: {type}")
    _, it = _find(tl["video"], item_id, "elemento")
    it["transition"] = {"type": type, "duration": 0.0 if type == "cut" else max(0.1, min(2.0, float(duration)))}
    return {}


def op_set_take(tl, prod, item_id, take_id):
    _, it = _find(tl["video"], item_id, "elemento")
    shot = shot_by_id(prod, it["shot_id"])
    if not shot or not any(t["id"] == take_id for t in ensure_takes(shot)):
        raise TimelineError("versione inesistente")
    take = active_take(shot, take_id)
    it["take_id"] = take_id
    it["src_out"] = min(it["src_out"], take_duration(take)) if it["src_out"] > 0 else take_duration(take)
    return {}


def op_insert_item(tl, prod, shot_id, take_id, index, src_in=0.0, src_out=None):
    shot = shot_by_id(prod, shot_id)
    take = active_take(shot, take_id) if shot else None
    if not take:
        raise TimelineError("inquadratura o versione inesistente")
    item = {"id": _id("v"), "shot_id": shot_id, "take_id": take["id"], "src_in": _snap(src_in),
            "src_out": _snap(src_out if src_out is not None else take_duration(take)),
            "transition": {"type": "cut", "duration": 0.0}}
    tl["video"].insert(max(0, min(int(index), len(tl["video"]))), item)
    return {"item": item["id"]}


def op_audio_add(tl, prod, kind, src, start, src_in=0.0, src_out=None, gain_db=0.0, label="", meta=None):
    if kind not in AUDIO_KINDS or kind == "clip":
        raise TimelineError(f"traccia non valida per una clip audio: {kind}")
    if not Path(src).is_file():
        raise TimelineError("file audio inesistente")
    if src_out is None:
        from core.modules.sigma_creative_lab.video.production import probe
        src_out = probe(Path(src))["audio_duration"]
    if float(src_out) - float(src_in) < MIN_ITEM_S:
        raise TimelineError("il file audio e' vuoto o illeggibile")
    clip = {"id": _id("a"), "src": str(src), "start": max(0.0, float(start)), "src_in": float(src_in),
            "src_out": float(src_out), "gain_db": float(gain_db), "label": label, **({"meta": meta} if meta else {})}
    audio_track(tl, kind)["clips"].append(clip)
    return {"clip": clip["id"]}


def op_audio_update(tl, prod, clip_id, **fields):
    _, _, clip = _find_audio_clip(tl, clip_id)
    for key in ("start", "src_in", "src_out", "gain_db", "label", "fade_in", "fade_out"):
        if key in fields and fields[key] is not None:
            clip[key] = fields[key] if key == "label" else float(fields[key])
    if clip["src_out"] - clip["src_in"] < MIN_ITEM_S:
        raise TimelineError("la clip audio resterebbe vuota")
    clip["start"] = max(0.0, clip["start"])
    # Le dissolvenze non possono superare insieme la durata della clip.
    length = clip["src_out"] - clip["src_in"]
    for key in ("fade_in", "fade_out"):
        if key in clip:
            clip[key] = round(max(0.0, min(float(clip[key]), length / 2)), 3)
    return {}


def op_audio_delete(tl, prod, clip_id):
    track, i, _ = _find_audio_clip(tl, clip_id)
    track["clips"].pop(i)
    return {}


def op_track(tl, prod, track_id, gain_db=None, mute=None):
    _, track = _find(tl["audio"], track_id, "traccia")
    if gain_db is not None:
        track["gain_db"] = max(-60.0, min(12.0, float(gain_db)))
    if mute is not None:
        track["mute"] = bool(mute)
    return {}


def op_overlay_add(tl, prod, text, start, end=None, sub="", style="lower"):
    """Testo sovrapposto al video (sottopancia, didascalia, titolo) fra start ed end."""
    if style not in OVERLAY_STYLES:
        raise TimelineError(f"stile di testo sconosciuto: {style}")
    if not str(text).strip():
        raise TimelineError("il testo e' vuoto")
    start = _snap(max(0.0, float(start)))
    end = _snap(float(end) if end is not None else start + 3.0)
    if end - start < 0.2:
        raise TimelineError("il testo deve restare visibile almeno 0,2 s")
    ov = {"id": _id("o"), "text": str(text).strip(), "sub": str(sub or "").strip(), "style": style,
          "start": start, "end": end}
    tl.setdefault("overlays", []).append(ov)
    tl["overlays"].sort(key=lambda o: o["start"])
    return {"overlay": ov["id"]}


def op_overlay_update(tl, prod, overlay_id, **fields):
    _, ov = _find(tl.setdefault("overlays", []), overlay_id, "testo")
    for key in ("text", "sub", "style"):
        if fields.get(key) is not None:
            ov[key] = str(fields[key]).strip()
    for key in ("start", "end"):
        if fields.get(key) is not None:
            ov[key] = _snap(max(0.0, float(fields[key])))
    if ov["style"] not in OVERLAY_STYLES:
        raise TimelineError(f"stile di testo sconosciuto: {ov['style']}")
    if ov["end"] - ov["start"] < 0.2 or not ov["text"]:
        raise TimelineError("testo vuoto o troppo breve")
    tl["overlays"].sort(key=lambda o: o["start"])
    return {}


def op_overlay_delete(tl, prod, overlay_id):
    i, _ = _find(tl.setdefault("overlays", []), overlay_id, "testo")
    tl["overlays"].pop(i)
    return {}


def op_marker(tl, prod, t, label=""):
    tl["markers"].append({"id": _id("m"), "t": _snap(t), "label": label})
    tl["markers"].sort(key=lambda m: m["t"])
    return {}


def op_marker_delete(tl, prod, marker_id):
    i, _ = _find(tl["markers"], marker_id, "marcatore")
    tl["markers"].pop(i)
    return {}


OPS = {
    "split": op_split, "delete": op_delete, "delete_range": op_delete_range, "trim": op_trim, "move": op_move,
    "duplicate": op_duplicate, "transition": op_transition, "set_take": op_set_take, "insert_item": op_insert_item,
    "audio_add": op_audio_add, "audio_update": op_audio_update, "audio_delete": op_audio_delete, "track": op_track,
    "marker": op_marker, "marker_delete": op_marker_delete,
    "overlay_add": op_overlay_add, "overlay_update": op_overlay_update, "overlay_delete": op_overlay_delete,
}


# ---------------------------------------------------------------------------
# Persistenza e cronologia
# ---------------------------------------------------------------------------

class TimelineStore:
    """Timeline e cronologia in file accanto al manifest della produzione."""

    def __init__(self, production_store):
        self.prods = production_store

    def _dir(self, pid: str) -> Path:
        return self.prods.path(pid)

    def _write(self, path: Path, data) -> None:
        from .production import _atomic_write_json
        _atomic_write_json(path, data, indent=None)

    def _history(self, pid: str) -> dict:
        f = self._dir(pid) / "timeline_history.json"
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                log.warning(f"cronologia della timeline di {pid} illeggibile: riparto da zero")
        return {"undo": [], "redo": []}

    def get(self, pid: str) -> dict:
        prod = self.prods.get(pid)
        if prod is None:
            raise TimelineError("produzione inesistente")
        f = self._dir(pid) / "timeline.json"
        if f.is_file():
            tl = json.loads(f.read_text(encoding="utf-8"))
            tl.setdefault("overlays", [])           # timeline salvate prima dei testi sovrapposti
            return tl
        tl = build_from_shots(prod)
        self._write(f, tl)
        return tl

    def save(self, pid: str, tl: dict) -> None:
        self._write(self._dir(pid) / "timeline.json", tl)

    def apply(self, pid: str, op: str, args: dict) -> tuple[dict, dict]:
        fn = OPS.get(op)
        if fn is None:
            raise TimelineError(f"operazione sconosciuta: {op}")
        prod = self.prods.get(pid)
        tl = self.get(pid)
        before = copy.deepcopy(tl)
        result = fn(tl, prod, **(args or {}))
        tl["version"] = int(tl.get("version", 0)) + 1
        hist = self._history(pid)
        hist["undo"] = (hist["undo"] + [before])[-HISTORY_LIMIT:]
        hist["redo"] = []
        self._write(self._dir(pid) / "timeline_history.json", hist)
        self.save(pid, tl)
        # Le versioni scelte in timeline possono essere nuove: il manifest le registra.
        self.prods.save(prod)
        return tl, result or {}

    def undo(self, pid: str, redo: bool = False) -> dict:
        hist = self._history(pid)
        src, dst = ("redo", "undo") if redo else ("undo", "redo")
        if not hist[src]:
            raise TimelineError("niente da ripetere" if redo else "niente da annullare")
        current = self.get(pid)
        state = hist[src].pop()
        hist[dst].append(current)
        state["version"] = int(current.get("version", 0)) + 1
        self._write(self._dir(pid) / "timeline_history.json", hist)
        self.save(pid, state)
        return state

    def rebuild(self, pid: str) -> dict:
        """Ricostruisce dalla lista delle inquadrature (annullabile come ogni altra modifica)."""
        prod = self.prods.get(pid)
        current = self.get(pid)
        hist = self._history(pid)
        hist["undo"] = (hist["undo"] + [current])[-HISTORY_LIMIT:]
        hist["redo"] = []
        tl = build_from_shots(prod)
        tl["version"] = int(current.get("version", 0)) + 1
        self._write(self._dir(pid) / "timeline_history.json", hist)
        self.save(pid, tl)
        return tl

    def history_depth(self, pid: str) -> dict:
        h = self._history(pid)
        return {"undo": len(h["undo"]), "redo": len(h["redo"])}
