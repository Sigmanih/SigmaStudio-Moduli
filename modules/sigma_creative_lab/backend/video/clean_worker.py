"""Toglie polvere e macchie da un film in bianco e nero, fotogramma per fotogramma.

Legge fotogrammi grigi (gray8) da stdin e li scrive puliti su stdout; su
stderr "frame N" per l'avanzamento. Gira in un processo a parte come
recolor_worker.py: ffmpeg decodifica a monte e codifica a valle.

Una macchia di polvere sta su un solo fotogramma, la scena no: il precedente e
il successivo, riallineati col flusso ottico, la mostrano pulita. Si
sostituisce solo dove i due vicini concordano fra loro e il fotogramma
corrente si scosta da entrambi: un oggetto che si muove davvero fa
discordare i vicini (o sbagliare il flusso) e non viene toccato. La mediana
temporale di ffmpeg (tmedian) non segue il movimento e lascia scie su tutto
cio' che si sposta.
"""

from __future__ import annotations

import argparse
import sys

import cv2
import numpy as np

#: Scarto (0-255) oltre il quale un pixel e' "diverso dai vicini".
#: 22 raddoppiava le correzioni (sulla grana) senza togliere piu' macchie vere: si resta a 28.
SPOT_DIFF = 28.0
#: Quanto devono somigliarsi i due vicini riallineati perche' la loro media sia credibile.
AGREE_DIFF = 14.0
#: Salto medio di luminanza oltre il quale c'e' uno stacco: li' i vicini non servono.
CUT_DIFF = 28.0
#: Una "macchia" piu' grande di cosi' (frazione del fotogramma) e' quasi sempre un errore del flusso.
MAX_SPOT_FRAC = 0.004


def _warp(src: np.ndarray, flow: np.ndarray, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    return cv2.remap(src, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


class Duster:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        gx, gy = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
        self.gx, self.gy = gx, gy
        self.max_area = int(MAX_SPOT_FRAC * width * height)
        self.fixed = 0

    def clean(self, prev: np.ndarray | None, cur: np.ndarray, nxt: np.ndarray | None) -> np.ndarray:
        if prev is None or nxt is None:
            return cur
        # Flusso calcolato su copie sfocate: la grana non deve guidarlo, e la macchia non deve attirarlo.
        c = cv2.GaussianBlur(cur, (5, 5), 0)
        p = cv2.GaussianBlur(prev, (5, 5), 0)
        n = cv2.GaussianBlur(nxt, (5, 5), 0)
        if np.abs(c.astype(np.int16) - p).mean() > CUT_DIFF or np.abs(c.astype(np.int16) - n).mean() > CUT_DIFF:
            return cur
        wp = _warp(prev, self.dis.calc(c, p, None), self.gx, self.gy).astype(np.float32)
        wn = _warp(nxt, self.dis.calc(c, n, None), self.gx, self.gy).astype(np.float32)
        curf = cur.astype(np.float32)
        ref = (wp + wn) * 0.5
        spot = (np.abs(wp - wn) < AGREE_DIFF) & (np.abs(curf - ref) > SPOT_DIFF)
        mask = spot.astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        big = np.flatnonzero(stats[1:, cv2.CC_STAT_AREA] > self.max_area) + 1
        if len(big):
            mask[np.isin(labels, big)] = 0
        if not mask.any():
            return cur
        # Un pixel di margine: il bordo della macchia e' sfumato e resterebbe come un alone.
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
        self.fixed += int(count - 1 - len(big))
        out = curf.copy()
        out[mask > 0] = ref[mask > 0]
        return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    args = ap.parse_args()
    size = args.width * args.height
    src, dst = sys.stdin.buffer, sys.stdout.buffer
    duster = Duster(args.width, args.height)
    n = 0

    def read() -> np.ndarray | None:
        buf = src.read(size)
        return np.frombuffer(buf, np.uint8).reshape(args.height, args.width) if len(buf) == size else None

    prev = None
    cur = read()
    nxt = read() if cur is not None else None
    while cur is not None:
        dst.write(duster.clean(prev, cur, nxt).tobytes())
        n += 1
        if n % 50 == 0:
            print(f"frame {n} spots {duster.fixed}", file=sys.stderr, flush=True)
        prev, cur = cur, nxt
        nxt = read() if cur is not None else None
    dst.flush()
    print(f"frame {n} spots {duster.fixed}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
