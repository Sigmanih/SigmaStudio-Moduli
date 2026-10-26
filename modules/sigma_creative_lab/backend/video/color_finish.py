"""Finitura del colore di un film muto ricolorato: cadenza dei doppioni, mappa delle tinte, cartelli, composizione.

Nasce dal Fantasma dell'Opera (1925), dove DDColor da solo non bastava:
- il riversamento ripeteva un fotogramma ogni tre (20 fps veri dentro 30): lavorare sui doppioni costava
  un terzo di calcolo in piu' e falsava la media dei colori sui vicini;
- la copia era virata (ambra, verde, blu) e aveva scene GIA' a colori (Technicolor del ballo, mantello
  rosso dipinto a mano): ricolorarle le avrebbe distrutte;
- le notti virate blu, tolta la tinta, uscivano da DDColor come tramonti arancioni;
- DDColor dava ombre oliva, mani e scie verdi, e coloriva di verde il testo dei cartelli.

La finitura sceglie fotogramma per fotogramma fra quattro versioni: ricolorato "giorno", ricolorato
"notte", originale (protetto) e cartello (grigio caldo dalla copia in bianco e nero).
"""
from __future__ import annotations

import colorsys
import json
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from core.logger import get_logger

log = get_logger("creative_color_finish")
Progress = Callable[[str, float], None]


def _nop(_m: str, _p: float) -> None:
    return None


def _ff():
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin, probe
    return ffmpeg_bin, probe


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _hw(gpu: int) -> list[str]:
    """Decodifica sulla GPU se c'e' una scheda NVIDIA (sul Raspberry si decodifica su CPU)."""
    from core.modules.sigma_creative_lab.video.postprocess import nvenc_available
    return ["-hwaccel", "cuda", "-hwaccel_device", str(gpu)] if nvenc_available(gpu) else []


# ---------------------------------------------------------------------------
# Fotogrammi ripetuti (pellicola a 16-20 fps riversata a 25-30)
# ---------------------------------------------------------------------------

def repeat_cycle(src: Path, samples: int = 3, sample_s: float = 12.0) -> int:
    """Ogni quanti fotogrammi uno e' il doppione del precedente: 3 per 20 fps dentro 30, 0 se nessuno.

    Si misura in piu' punti perche' una scena ferma ha doppioni "veri" ovunque: conta lo schema
    regolare, cioe' quanti fotogrammi su N sono ripetuti nei tratti con movimento.
    """
    from core.modules.sigma_creative_lab.video.postprocess import _rate_and_frames
    ffmpeg_bin, probe = _ff()
    fps, total = _rate_and_frames(src, probe(src))
    durata = total / fps if fps else 0.0
    if durata < 30:
        return 0
    w, h = 160, 120
    quote = []
    for k in range(samples):
        at = durata * (k + 1) / (samples + 1)
        raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{at:.1f}", "-t", f"{sample_s:.0f}", "-i", str(src),
                              "-vf", f"scale={w}:{h},format=gray", "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
                             capture_output=True, timeout=300, creationflags=_flags()).stdout
        f = np.frombuffer(raw[: len(raw) // (w * h) * (w * h)], np.uint8).reshape(-1, h, w).astype(np.float32)
        if len(f) < 30:
            continue
        d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
        mov = float(np.median(d))
        if mov < 1.0:
            continue                                   # tratto quasi fermo: non dice niente
        quote.append(float((d < max(0.6, mov * 0.15)).mean()))
    if not quote:
        return 0
    q = float(np.median(quote))
    # 1 su 3 (20 in 30), 1 su 4 (18 in 24), 1 su 5 (24 in 30, pulldown progressivo): la quota sta vicino a 1/N.
    for n in (3, 4, 5, 6):
        if abs(q - 1 / n) < 0.06:
            log.info(f"{src.name}: un fotogramma ripetuto ogni {n} (quota {q:.2f})")
            return n
    return 0


# ---------------------------------------------------------------------------
# Mappa delle tinte e delle scene a colori
# ---------------------------------------------------------------------------

#: Una sequenza protetta (Technicolor, colori dipinti a mano) si estende alle inquadrature virate blu o
#: a colori che le stanno in mezzo, se il buco e' sotto questi secondi: nel Fantasma il ballo alternava
#: inquadrature Technicolor e virate, e il tetto alternava il mantello rosso a inquadrature senza.
PROTECT_GAP_S = 40.0


def color_map(clip: Path, gpu: int = 0, progress: Progress = _nop) -> dict:
    """Inquadrature del film con tinta dominante e protezione: {"fps", "frames", "shots": [...]}.

    Ogni inquadratura: start/end in fotogrammi, tinta (bn, ambra, verde, blu, colore), grado
    ("notte" se virata blu, altrimenti "giorno"), protetta e motivo ("technicolor", "dipinto").
    """
    from core.modules.sigma_creative_lab.video.postprocess import _rate_and_frames
    ffmpeg_bin, probe = _ff()
    fps, total = _rate_and_frames(clip, probe(clip))
    w, h = 192, 140
    proc = subprocess.Popen([ffmpeg_bin(), "-v", "error", *_hw(gpu), "-i", str(clip), "-vf", f"scale={w}:{h}",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE,
                            creationflags=_flags())
    size = w * h * 3
    prev, diffs, kinds = None, [], []
    try:
        while len(buf := proc.stdout.read(size)) == size:
            f = np.frombuffer(buf, np.uint8).reshape(h, w, 3).astype(np.float32) / 255.0
            gray = f.mean(axis=2)
            diffs.append(0.0 if prev is None else float(np.abs(gray - prev).mean() * 255))
            prev = gray
            mx, mn = f.max(axis=2), f.min(axis=2)
            sat = np.where(mx > 0.06, (mx - mn) / (mx + 1e-6), 0)
            r, g, b = f[..., 0], f[..., 1], f[..., 2]
            mask = (sat > 0.18) & (mx > 0.12)
            if mask.mean() < 0.08:
                tinta = "bn"
            else:
                hue = np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)[mask]
                c, s = np.cos(hue).mean(), np.sin(hue).mean()
                media = (np.degrees(np.arctan2(s, c)) + 360) % 360
                # Una tinta sola = virato; tinte opposte nello stesso quadro = colore vero (Technicolor).
                tinta = "colore" if 1 - np.hypot(c, s) > 0.25 else (
                    "blu" if 190 <= media <= 280 else "verde" if 80 <= media < 190 else "ambra")
            rosso = float(((r > 0.25) & (r > 1.8 * g) & (r > 1.8 * b)).mean())
            kinds.append((tinta, rosso))
            if len(kinds) % 2000 == 0:
                progress("Mappa delle tinte", min(0.99, len(kinds) / max(1, total)))
    finally:
        proc.stdout.close()
        proc.wait(timeout=120)
    n = len(kinds)
    if not n:
        raise RuntimeError(f"nessun fotogramma letto da {clip.name}")
    d = np.array(diffs)
    c = np.cumsum(np.concatenate([[0.0], d]))
    # Mediana locale approssimata con la media su 20 fotogrammi: un taglio e' un salto netto rispetto al movimento.
    idx = np.arange(n)
    lo, hi = np.clip(idx - 10, 0, n), np.clip(idx + 10, 0, n)
    local = (c[hi] - c[lo]) / np.maximum(1, hi - lo)
    cuts = [0] + [i for i in range(1, n) if d[i] > max(14.0, 4 * local[i])] + [n]
    shots = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b <= a:
            continue
        tinte = [kinds[i][0] for i in range(a, b)]
        conta = {t: tinte.count(t) for t in set(tinte)}
        dom = max(conta, key=conta.get)
        rosso = max(kinds[i][1] for i in range(a, b))
        tech = conta.get("colore", 0) > 0.5 * (b - a)
        dipinto = dom == "blu" and rosso > 0.004 and (b - a) > 4
        shots.append({"start": a, "end": b, "tinta": dom, "grado": "notte" if dom == "blu" else "giorno",
                      "protetta": bool(tech or dipinto), "motivo": "technicolor" if tech else (
                          "dipinto" if dipinto else "")})
    _extend_protection(shots, fps)
    virati = sum(s["end"] - s["start"] for s in shots if s["tinta"] not in ("bn",))
    return {"fps": fps, "frames": n, "shots": shots, "tinted_ratio": round(virati / n, 3)}


def _extend_protection(shots: list[dict], fps: float) -> None:
    prot = [i for i, s in enumerate(shots) if s["protetta"]]
    for a, b in zip(prot[:-1], prot[1:]):
        if b - a < 2:
            continue
        gap = (shots[b]["start"] - shots[a]["end"]) / fps
        mezzo = shots[a + 1:b]
        if gap <= PROTECT_GAP_S and all(s["tinta"] in ("blu", "colore") for s in mezzo):
            for s in mezzo:
                s["protetta"], s["motivo"] = True, shots[a]["motivo"] or "sequenza"


def set_protection(cmap: dict, ranges: list[dict]) -> dict:
    """Correzione a mano: [{"start_s", "end_s", "protect": bool}] -> inquadrature che ci cadono in mezzo."""
    fps = cmap["fps"]
    for r in ranges:
        a, b = float(r["start_s"]) * fps, float(r["end_s"]) * fps
        for s in cmap["shots"]:
            mid = (s["start"] + s["end"]) / 2
            if a <= mid <= b:
                s["protetta"] = bool(r.get("protect", True))
                s["motivo"] = "a mano" if s["protetta"] else ""
                s["edited"] = True
    return cmap


def summary(cmap: dict) -> dict:
    """Riassunto leggibile per pannello e agenti: protette per tratto, secondi di notte."""
    fps, out, cur = cmap["fps"], [], None
    for s in cmap["shots"]:
        if s["protetta"]:
            if cur and s["start"] - cur["end"] <= 2:
                cur["end"] = s["end"]
            else:
                cur = {"start": s["start"], "end": s["end"], "motivo": s["motivo"]}
                out.append(cur)
    notte = sum(s["end"] - s["start"] for s in cmap["shots"] if s["grado"] == "notte" and not s["protetta"])
    return {"protected": [{"start_s": round(r["start"] / fps, 2), "end_s": round(r["end"] / fps, 2),
                           "reason": r["motivo"]} for r in out],
            "night_s": round(notte / fps, 1), "shots": len(cmap["shots"]), "tinted_ratio": cmap.get("tinted_ratio")}


# ---------------------------------------------------------------------------
# Cartelli: dove il colore va tolto
# ---------------------------------------------------------------------------

def card_spans(clip: Path, cards: list[dict], fps: float, gpu: int = 0) -> list[list[int]]:
    """Tratti (in fotogrammi) dei cartelli: aspetto da cartello E un testo letto in quel punto.

    L'aspetto da solo (fondo scuro, tante lettere chiare) scambia per cartelli molte scene notturne:
    togliere il colore li' farebbe ingrigire il film a lampi. Serve anche che il restauro ci abbia letto
    un testo (state["cards"]).
    """
    from scipy import ndimage
    ffmpeg_bin, _probe = _ff()
    w, h = 240, 174
    proc = subprocess.Popen([ffmpeg_bin(), "-v", "error", *_hw(gpu), "-i", str(clip), "-vf",
                             f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE,
                            creationflags=_flags())
    flags = []
    try:
        while len(buf := proc.stdout.read(w * h)) == w * h:
            g = np.frombuffer(buf, np.uint8).reshape(h, w)[12:-12, 18:-18]
            ok = False
            if (g < 50).mean() > 0.7:
                bright = g > 105
                if 0.003 < bright.mean() < 0.25:
                    lab, n = ndimage.label(bright)
                    ok = n >= 8 and np.bincount(lab.ravel())[1:].max() / bright.sum() < 0.3
            flags.append(ok)
    finally:
        proc.stdout.close()
        proc.wait(timeout=120)
    f = ndimage.binary_closing(np.array(flags), structure=np.ones(5))
    lab, _n = ndimage.label(f)
    tratti = [(sl[0].start, sl[0].stop) for sl in ndimage.find_objects(lab) if sl[0].stop - sl[0].start >= 15]
    letti = [(c["start"] * fps - 20, c["end"] * fps + 20) for c in cards if not c.get("deleted")]
    return [[int(a), int(b)] for a, b in tratti if any(la <= b and a <= lb for la, lb in letti)]


# ---------------------------------------------------------------------------
# Composizione
# ---------------------------------------------------------------------------

#: Giorno: piu' saturo, ombre e luci neutre (DDColor le dava oliva: G-R +2,8, B-R -10 su 60 campioni).
GRADE_DAY = "eq=saturation=1.3,colorbalance=rs=0.02:gs=-0.03:bs=0.01:rm=0.03:bm=-0.03:gh=-0.02"
#: Notte: dove l'originale era virato blu; senza la tinta DDColor ne faceva un tramonto arancione.
GRADE_NIGHT = "eq=saturation=0.75:brightness=-0.03,colorchannelmixer=rr=0.72:gg=0.80:bb=1.12"
BLOCK = 6000


def green_lut(path: Path) -> Path:
    """LUT 3D che spegne il verde inventato (65-175 gradi, fino all'85%) senza toccare pelle e notti."""
    if path.is_file():
        return path
    n, centro, largo, forza = 33, 118.0, 55.0, 0.85
    righe = [f"LUT_3D_SIZE {n}"]
    for b in range(n):
        for g in range(n):
            for r in range(n):
                R, G, B = r / (n - 1), g / (n - 1), b / (n - 1)
                hh, s, v = colorsys.rgb_to_hsv(R, G, B)
                dd = abs(hh * 360 - centro)
                peso = max(0.0, 1 - (dd / largo) ** 2) if dd < largo else 0.0
                R2, G2, B2 = colorsys.hsv_to_rgb(hh, s * (1 - forza * peso), v)
                # Il verde pesa molto nella luminosita': togliendolo, l'immagine si scurirebbe; si compensa.
                y1 = 0.2126 * R + 0.7152 * G + 0.0722 * B
                y2 = 0.2126 * R2 + 0.7152 * G2 + 0.0722 * B2
                k = y1 / y2 if y2 > 1e-6 else 1.0
                righe.append(f"{min(1, R2 * k):.6f} {min(1, G2 * k):.6f} {min(1, B2 * k):.6f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(righe) + "\n", encoding="ascii")
    return path


def _count_frames(path: Path) -> int:
    ffmpeg_bin, _probe = _ff()
    r = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-count_packets", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=600, creationflags=_flags())
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def finish(master: Path, recolored: Path, gray: Path, cmap: dict, cards: list[list[int]], out: Path,
           gpu: int = 0, progress: Progress = _nop) -> dict:
    """Film finito: per ogni fotogramma giorno, notte, originale protetto o cartello in grigio caldo.

    A blocchi da BLOCK fotogrammi in <out>.parti/, saltando quelli gia' finiti: un riavvio a meta'
    film non fa rifare tutto. L'audio del master, se c'e', resta.
    """
    from core import paths
    from core.modules.sigma_creative_lab.video.postprocess import video_encoder_args
    ffmpeg_bin, probe = _ff()
    info = probe(recolored)
    W, H, N, fps = int(info["width"]), int(info["height"]), cmap["frames"], cmap["fps"]
    lut = green_lut(paths.module_data("sigma_creative_lab") / "luts" / "ddcolor_verdi.cube")
    lut_f = lut.as_posix().replace(":", "\\:")
    scelta = ["giorno"] * N
    for s in cmap["shots"]:
        for i in range(s["start"], min(N, s["end"])):
            scelta[i] = "orig" if s["protetta"] else s["grado"]
    for a, b in cards:
        for i in range(max(0, a), min(N, b)):
            if scelta[i] != "orig":
                scelta[i] = "cartello"
    sorgenti = {"giorno": (recolored, f"{GRADE_DAY},lut3d=file='{lut_f}'"),
                "notte": (recolored, f"{GRADE_NIGHT},lut3d=file='{lut_f}'"),
                "orig": (master, f"scale={W}:{H}"), "cartello": (gray, f"scale={W}:{H},{GRADE_DAY}")}
    parti = out.with_suffix(".parti")
    parti.mkdir(parents=True, exist_ok=True)
    size = W * H * 3
    blocchi = [(a, min(N, a + BLOCK)) for a in range(0, N, BLOCK)]
    rate = f"{fps:.6f}"
    for k, (a, b) in enumerate(blocchi):
        dest = parti / f"p{k:03d}.mp4"
        if dest.is_file() and _count_frames(dest) == b - a:
            continue
        progress("Finitura del colore", k / len(blocchi))
        usate = sorted(set(scelta[a:b]))
        first = max(0, a - 40)
        # Un centesimo prima di un fotogramma esatto: con un punto a meta' fra due il blocco partiva uno dopo.
        t0 = max(0.0, first / fps - 0.01)
        flussi = {}
        for nome in usate:
            src, vf = sorgenti[nome]
            flussi[nome] = subprocess.Popen(
                [ffmpeg_bin(), "-v", "error", *_hw(gpu), "-ss", f"{t0:.4f}", "-i", str(src), "-vf",
                 f"trim=start_frame={a - first}:end_frame={b - first},{vf},format=rgb24", "-f", "rawvideo", "-"],
                stdout=subprocess.PIPE, bufsize=size * 2, creationflags=_flags())
        tmp = dest.with_suffix(".part.mp4")
        enc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{W}x{H}", "-framerate", rate, "-i", "-", *video_encoder_args(16, gpu),
                                str(tmp)], stdin=subprocess.PIPE, creationflags=_flags())
        scritti = 0
        try:
            for i in range(a, b):
                frames = {n: p.stdout.read(size) for n, p in flussi.items()}
                if any(len(v) < size for v in frames.values()):
                    break
                enc.stdin.write(frames[scelta[i]])
                scritti += 1
        finally:
            enc.stdin.close()
            for p in flussi.values():
                p.kill()
            enc.wait(timeout=600)
        if scritti != b - a:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"finitura: blocco {k} con {scritti} fotogrammi invece di {b - a}")
        tmp.replace(dest)
    lista = parti / "lista.txt"
    lista.write_text("".join(f"file '{(parti / f'p{k:03d}.mp4').as_posix()}'\n" for k in range(len(blocchi))),
                     encoding="utf-8")
    audio = ["-i", str(master), "-map", "0:v", "-map", "1:a?", "-c:a", "copy"] if probe(master)["has_audio"] else []
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), *audio,
                    "-c:v", "copy", str(out)], check=True, timeout=3600, creationflags=_flags())
    got = _count_frames(out)
    if got != N:
        raise RuntimeError(f"finitura: {got} fotogrammi invece di {N}")
    for p in parti.glob("*"):
        p.unlink(missing_ok=True)
    parti.rmdir()
    conta = {k: scelta.count(k) for k in ("giorno", "notte", "orig", "cartello")}
    progress("Finitura completata", 1.0)
    return {"path": str(out), "frames": got, "uses": conta}


def save_map(path: Path, cmap: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cmap), encoding="utf-8")
    tmp.replace(path)
