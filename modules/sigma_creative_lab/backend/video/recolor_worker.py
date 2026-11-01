"""Ricolora un flusso di fotogrammi in bianco e nero (DDColor + coerenza nel tempo).

Legge fotogrammi RGB24 grezzi da stdin e scrive su stdout gli stessi
fotogrammi a colori, come esrgan_worker.py: ffmpeg decodifica a monte e
codifica a valle. Su stderr stampa "frame N" per l'avanzamento.

Perche' cosi' (collaudo sul film dei Lumiere, 2026-10-21):
- DDColor colora senza spostare i contorni (FLUX klein invece ridisegna la
  scena e il colore finiva fuori posto), ma colora ogni fotogramma per conto
  suo: lo stesso oggetto cambiava colore da un decimo di secondo all'altro;
- il colore di ogni fotogramma e' quindi la media di quello di DDColor sui
  vicini (+-K), ciascuno riportato nella posizione attuale col flusso ottico.
  Trascinare in avanti il colore gia' deciso (ricorsivo) stabilizzava di piu'
  ma un errore del flusso diventava una scia lunga secondi;
- DDColor vira tutto al rosa: la tavolozza viene riportata a una naturale
  (statistiche misurate su fotogrammi colorati bene) e la banchina, la strada,
  le superfici chiare in basso, al sole quasi neutre, fanno da bilanciamento
  del bianco.

Il colore si calcola a bassa risoluzione (WORK_H righe), che basta alla
crominanza, e si applica alla luminanza originale a piena risoluzione: i
dettagli restano quelli della pellicola.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ddcolor_arch import DDColor  # noqa: E402

DD_SIZE = 512
WORK_H = 384
#: Mezza finestra (in fotogrammi) delle statistiche di colore: ~0,5 s per lato.
STATS_HALF = 15
#: Tavolozza obiettivo in Lab di OpenCV a virgola mobile (a, b centrati su 0).
PALETTE = {"a_mean": -2.46, "a_std": 7.39, "b_mean": 1.81, "b_std": 11.16}
#: Colore delle superfici chiare al sole: neutro con un filo di caldo.
NEUTRAL = (1.0, 6.0)
BRIGHT_L = 66.7
#: Sotto DARK_L0 il colore scende a DARK_MIN, da DARK_L1 in su resta pieno (L su 0-100).
DARK_L0, DARK_L1, DARK_MIN = 12.0, 55.0, 0.3


def is_title_card(l_work: np.ndarray) -> bool:
    """Didascalia del muto: fondo quasi nero e poco testo, chiaro o grigio.

    DDColor colorava il testo di verde o di ciano. Misure su Nosferatu: le
    didascalie hanno l'83-96% di pixel con L<10; il testo occupa il 2-15% ed e'
    bianco o, nelle didascalie lunghe, grigio spento (L 20-55: la prima regola
    voleva meno dell'8% di toni medi e ne perdeva una parte). La scena piu' buia
    (Orlok nell'ombra) ha il 64% di nero, i sentieri di notte il 22-36%.
    Ma una scena buia con una sola macchia di luce (la stiva coi topi) ha anche
    il 75-86% di nero: il testo e' fatto di tante lettere separate, la luce di
    un'isola sola. Nelle didascalie l'isola chiara piu' grande e' al massimo il
    24% del chiaro, nelle scene buie dal 43% al 100%.
    """
    # Fondo "quasi nero" (L<20) e non nero pieno: alcune didascalie hanno il fondo grigio scuro
    # (66-75% sotto L 10) e le scene buie le esclude gia' il criterio delle isole.
    mask = (l_work >= 20).astype(np.uint8)
    text = mask.mean()
    if not 0.005 < text < 0.22:
        return False
    _n, _labels, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    return bool(len(areas) and areas.max() / areas.sum() < 0.35)


#: Salto medio di luminanza (0-255) oltre il quale c'e' uno stacco di montaggio.
CUT_DIFF = 28.0
FLOW_SIGMA = 12.0


def load_model(weights: Path, device: torch.device) -> DDColor:
    model = DDColor(encoder_name="convnext-l", decoder_name="MultiScaleColorDecoder", input_size=[DD_SIZE, DD_SIZE],
                    num_output_channels=2, last_norm="Spectral", do_normalize=False,
                    num_queries=100, num_scales=3, dec_layers=9)
    state = torch.load(weights, map_location="cpu", weights_only=True)
    missing, unexpected = model.load_state_dict(state.get("params", state), strict=False)
    # strict=False e' richiesto dal checkpoint, ma un file sbagliato darebbe colori casuali senza errori.
    if missing or unexpected:
        raise RuntimeError(f"pesi DDColor non corrispondenti: {len(missing)} mancanti, {len(unexpected)} inattesi")
    return model.to(device).eval()


class Frame:
    __slots__ = ("idx", "seg", "l_full", "l_small", "ab", "stats", "fwd", "bwd", "title")

    def __init__(self, idx, seg, l_full, l_small, ab, stats):
        self.idx, self.seg, self.l_full, self.l_small, self.ab, self.stats = idx, seg, l_full, l_small, ab, stats
        self.title = False
        # Flusso verso il fotogramma successivo e verso il precedente (None oltre uno stacco).
        self.fwd = self.bwd = None


class Recolorer:
    def __init__(self, model, device, width: int, height: int, window: int, chroma: float = 1.0,
                 dark: tuple[float, float, float] = (DARK_L0, DARK_L1, DARK_MIN), warm: float = NEUTRAL[1],
                 titles: bool = True, stretch: bool = False):
        self.model, self.device = model, device
        # Aspetto regolabile per film: la tavolozza dei Lumiere (esterni al sole) spegneva il Fantasma,
        # girato in teatro e quasi tutto in penombra (collaudo del 2026-10-26).
        self.chroma, self.dark, self.warm = chroma, dark, warm
        self.titles, self.stretch = titles, stretch
        self.w, self.h = width, height
        self.sh = min(WORK_H, height)
        self.sw = max(16, int(round(width * self.sh / height)))
        self.window = window
        self.lookahead = max(window, STATS_HALF)
        self.buf: deque[Frame] = deque()
        self.stats: list[tuple] = []           # (seg, m_a, s_a, m_b, s_b, bright_a, bright_b, bright_frac)
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        gx, gy = np.meshgrid(np.arange(self.sw, dtype=np.float32), np.arange(self.sh, dtype=np.float32))
        self.gx, self.gy = gx, gy
        self.next_out = 0
        self.seg = 0

    @torch.inference_mode()
    def prepare(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Luminanza a piena risoluzione e a/b di DDColor alla risoluzione di lavoro.

        Gira sul thread di lettura: mentre la GPU colora il fotogramma successivo,
        il thread principale allinea i colori di quelli gia' pronti.
        """
        l_full = cv2.cvtColor(rgb.astype(np.float32) * (1.0 / 255.0), cv2.COLOR_RGB2LAB)[..., 0]
        l_in = cv2.resize(l_full, (DD_SIZE, DD_SIZE), interpolation=cv2.INTER_AREA)
        if self.stretch:
            # Il grigio di una copia virata ha neri lattiginosi e poco contrasto: DDColor lo colora
            # timidamente. Lui vede i livelli stesi, l'uscita tiene la luminanza della pellicola.
            lo, hi = np.percentile(l_in, (0.5, 99.7))
            l_in = np.clip((l_in - lo) * (100.0 / max(1.0, hi - lo)), 0.0, 100.0).astype(np.float32)
        gray_lab = np.dstack([l_in, np.zeros_like(l_in), np.zeros_like(l_in)])
        gray_rgb = cv2.cvtColor(gray_lab, cv2.COLOR_LAB2RGB)
        x = torch.from_numpy(np.ascontiguousarray(gray_rgb.transpose(2, 0, 1))).unsqueeze(0).to(self.device)
        # Mezza precisione su GPU: quasi il doppio piu' veloce, scarto di colore invisibile (misurato < 1 su a/b).
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=self.device.type == "cuda"):
            ab = self.model(x)[0].float().cpu().numpy().transpose(1, 2, 0)
        return l_full, cv2.resize(ab, (self.sw, self.sh), interpolation=cv2.INTER_LINEAR)

    def push(self, l_full: np.ndarray, ab: np.ndarray) -> list[np.ndarray]:
        idx = len(self.stats)
        l_small = cv2.GaussianBlur(cv2.resize((l_full * 2.55).astype(np.uint8), (self.sw, self.sh),
                                              interpolation=cv2.INTER_AREA), (5, 5), 0)
        prev = self.buf[-1] if self.buf else None
        if prev is not None and np.abs(l_small.astype(np.float32) - prev.l_small).mean() > CUT_DIFF:
            self.seg += 1
        l_work = cv2.resize(l_full, (self.sw, self.sh), interpolation=cv2.INTER_AREA)
        bright = l_work[self.sh // 2:] > BRIGHT_L
        low = ab[self.sh // 2:]
        b_mean = low[bright].mean(axis=0) if bright.any() else np.zeros(2, np.float32)
        st = (self.seg, float(ab[..., 0].mean()), float(ab[..., 0].std()), float(ab[..., 1].mean()),
              float(ab[..., 1].std()), float(b_mean[0]), float(b_mean[1]), float(bright.mean()))
        self.stats.append(st)
        cur = Frame(idx, self.seg, l_full, l_small, ab, st)
        cur.title = self.titles and is_title_card(l_work)
        if prev is not None and prev.seg == cur.seg:
            # Solo i flussi fra fotogrammi adiacenti: quelli verso i vicini lontani si ottengono
            # concatenandoli. Prima se ne calcolavano 16 a fotogramma ed erano meta' del tempo.
            prev.fwd = self.dis.calc(prev.l_small, l_small, None)
            cur.bwd = self.dis.calc(l_small, prev.l_small, None)
        self.buf.append(cur)
        out = []
        while self.buf and self.buf[-1].idx - self.next_out >= self.lookahead:
            out.append(self._emit())
        return out

    def flush(self) -> list[np.ndarray]:
        out = []
        while self.next_out < len(self.stats):
            out.append(self._emit())
        return out

    def _affine(self, t: int, seg: int) -> tuple[float, float, float, float, float, float]:
        """Correzione della tavolozza per il fotogramma t: statistiche mediate sullo stesso stacco."""
        lo, hi = max(0, t - STATS_HALF), min(len(self.stats), t + STATS_HALF + 1)
        rows = np.array([s[1:] for s in self.stats[lo:hi] if s[0] == seg], np.float64)
        m_a, s_a, m_b, s_b, br_a, br_b, br_frac = rows.mean(axis=0)
        k_a = min(3.0 * self.chroma, PALETTE["a_std"] * self.chroma / max(s_a, 1.0))
        k_b = min(3.0 * self.chroma, PALETTE["b_std"] * self.chroma / max(s_b, 1.0))
        shift_a = shift_b = 0.0
        if br_frac > 0.02:
            shift_a = NEUTRAL[0] - ((br_a - m_a) * k_a + PALETTE["a_mean"])
            shift_b = self.warm - ((br_b - m_b) * k_b + PALETTE["b_mean"])
        return m_a, k_a, PALETTE["a_mean"] + shift_a, m_b, k_b, PALETTE["b_mean"] + shift_b

    def _emit(self) -> np.ndarray:
        t = self.next_out
        self.next_out += 1
        by_idx = {f.idx: f for f in self.buf}
        cur = by_idx[t]
        # Il vicino piu' lontano all'indietro (t - window) serve ancora a questo fotogramma.
        while self.buf and self.buf[0].idx < t - self.window:
            self.buf.popleft()
        if cur.title:
            lab = np.dstack([cur.l_full, np.zeros_like(cur.l_full), np.zeros_like(cur.l_full)])
            rgb = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB)
            return (np.clip(rgb, 0, 1) * 255.0 + 0.5).astype(np.uint8)
        acc = cur.ab.copy()
        weight = np.ones((self.sh, self.sw), np.float32)
        l_cur = cur.l_small.astype(np.float32)
        for step, attr in ((1, "fwd"), (-1, "bwd")):
            # Spostamento cumulato da t al vicino: flusso(t->t+1) + flusso(t+1->t+2) letto dove si e' arrivati, ...
            total = np.zeros((self.sh, self.sw, 2), np.float32)
            for k in range(1, self.window + 1):
                here = by_idx.get(t + step * (k - 1))
                there = by_idx.get(t + step * k)
                link = getattr(here, attr) if here is not None else None
                if there is None or link is None:
                    break
                mx, my = self.gx + total[..., 0], self.gy + total[..., 1]
                total += cv2.remap(link, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                mx, my = self.gx + total[..., 0], self.gy + total[..., 1]
                ab = cv2.remap(there.ab, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                l_back = cv2.remap(there.l_small, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                err = (l_cur - l_back) * (1.0 / FLOW_SIGMA)
                # Piu' lontano nel tempo, meno peso: la catena di flussi accumula errore.
                w = cv2.exp(-(err * err)) * float(np.exp(-(k / self.window) ** 2))
                w[(mx < 0) | (mx > self.sw - 1) | (my < 0) | (my > self.sh - 1)] = 0.0
                acc += w[..., None] * ab
                weight += w
        ab = acc / weight[..., None]
        m_a, k_a, t_a, m_b, k_b, t_b = self._affine(t, cur.seg)
        ab[..., 0] = (ab[..., 0] - m_a) * k_a + t_a
        ab[..., 1] = (ab[..., 1] - m_b) * k_b + t_b
        ab_full = cv2.resize(ab, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        # Nelle zone scure DDColor tira a caso verso il blu o il viola (scene notturne di
        # Nosferatu): il colore si attenua con la luminanza, come succede davvero nell'ombra.
        l0, l1, floor = self.dark
        dim = np.clip((cur.l_full - l0) * (1.0 / (l1 - l0)), floor, 1.0)
        lab = np.dstack([cur.l_full, np.clip(ab_full * dim[..., None], -110, 110)])
        rgb = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB)
        return (np.clip(rgb, 0, 1) * 255.0 + 0.5).astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--window", type=int, default=8)
    ap.add_argument("--chroma", type=float, default=1.0, help="moltiplica la varieta' della tavolozza")
    ap.add_argument("--dark", default=f"{DARK_L0},{DARK_L1},{DARK_MIN}", help="L0,L1,minimo dell'attenuazione")
    ap.add_argument("--warm", type=float, default=NEUTRAL[1], help="b* delle superfici chiare")
    ap.add_argument("--no-titles", action="store_true", help="i cartelli li gestisce chi chiama")
    ap.add_argument("--stretch", action="store_true", help="livelli stesi per DDColor")
    args = ap.parse_args()
    l0, l1, floor = (float(x) for x in args.dark.split(","))
    if not (l1 > l0 and 0.0 <= floor <= 1.0):
        print(f"--dark non valido: {args.dark}", file=sys.stderr)
        return 2

    device = torch.device(f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu")
    rec = Recolorer(load_model(Path(args.weights), device), device, args.width, args.height, max(1, args.window),
                    chroma=args.chroma, dark=(l0, l1, floor), warm=args.warm, titles=not args.no_titles,
                    stretch=args.stretch)
    frame_bytes = args.width * args.height * 3
    src, dst = sys.stdin.buffer, sys.stdout.buffer
    ready: queue.Queue = queue.Queue(maxsize=8)

    def produce() -> None:
        # Lettura e DDColor su un thread: torch e OpenCV rilasciano il GIL, GPU e CPU lavorano insieme.
        try:
            while len(buf := src.read(frame_bytes)) == frame_bytes:
                ready.put(rec.prepare(np.frombuffer(buf, np.uint8).reshape(args.height, args.width, 3)))
            ready.put(None)
        except BaseException as e:
            ready.put(e)

    threading.Thread(target=produce, name="ddcolor", daemon=True).start()
    n = 0
    while (item := ready.get()) is not None:
        if isinstance(item, BaseException):
            raise item
        for out in rec.push(*item):
            dst.write(out.tobytes())
            n += 1
            if n % 25 == 0:
                print(f"frame {n}", file=sys.stderr, flush=True)
    for out in rec.flush():
        dst.write(out.tobytes())
        n += 1
    dst.flush()
    print(f"frame {n}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
