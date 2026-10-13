"""Upscale Real-ESRGAN (SRVGGNetCompact: realesr-general-x4v3) di un flusso di fotogrammi.

Gira nel venv delle voci, che ha gia' torch con CUDA: legge fotogrammi RGB24
grezzi da stdin e scrive su stdout i fotogrammi ingranditi alla misura
richiesta. ffmpeg decodifica a monte e codifica a valle, cosi' non passa
nessun PNG dal disco.

Si usa PyTorch e non l'eseguibile ncnn-vulkan perche' su questa macchina
Vulkan espone solo la GPU integrata: le NVIDIA restavano inutilizzate e un
clip da 5 s richiedeva tre minuti.
"""

from __future__ import annotations

import argparse
import sys

import torch
from torch import nn
from torch.nn import functional as F


class SRVGGNetCompact(nn.Module):
    """Architettura dei modelli compatti di Real-ESRGAN (BSD-3): convoluzioni in serie e pixel shuffle."""

    def __init__(self, num_feat: int = 64, num_conv: int = 16, upscale: int = 4):
        super().__init__()
        self.upscale = upscale
        body = [nn.Conv2d(3, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        for _ in range(num_conv):
            body += [nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        body.append(nn.Conv2d(num_feat, 3 * upscale * upscale, 3, 1, 1))
        self.body = nn.ModuleList(body)
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for layer in self.body:
            out = layer(out)
        # La rete impara il residuo rispetto all'ingrandimento nearest.
        return self.upsampler(out) + F.interpolate(x, scale_factor=self.upscale, mode="nearest")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--out-width", type=int, required=True)
    ap.add_argument("--out-height", type=int, required=True)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--num-conv", type=int, default=16)
    args = ap.parse_args()

    device = torch.device(f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu")
    net = SRVGGNetCompact(num_conv=args.num_conv)
    state = torch.load(args.weights, map_location="cpu", weights_only=True)
    net.load_state_dict(state.get("params", state))
    net.eval().to(device)
    half = device.type == "cuda"
    if half:
        net.half()

    frame_bytes = args.width * args.height * 3
    src, dst = sys.stdin.buffer, sys.stdout.buffer
    with torch.inference_mode():
        while True:
            buf = src.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            x = torch.frombuffer(bytearray(buf), dtype=torch.uint8).to(device)
            x = x.view(args.height, args.width, 3).permute(2, 0, 1).unsqueeze(0)
            x = x.half() / 255.0 if half else x.float() / 255.0
            y = net(x)
            # x4 e poi giu' alla misura esatta con antialias: piu' pulito che chiedere x2 a una rete x4.
            y = F.interpolate(y.float(), size=(args.out_height, args.out_width), mode="bicubic",
                              antialias=True, align_corners=False)
            y = (y.clamp(0, 1) * 255.0).round().to(torch.uint8)[0].permute(1, 2, 0).contiguous()
            dst.write(y.cpu().numpy().tobytes())
    dst.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
