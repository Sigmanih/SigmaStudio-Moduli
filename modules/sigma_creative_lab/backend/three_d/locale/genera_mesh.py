"""Da immagini a mesh 3D con TRELLIS, in locale.

Gira nel venv dedicato (store/engine_runtime/image3d: torch cu128, spconv,
TRELLIS) e lo lancia trellis_locale.py in un sottoprocesso: il kernel non ha
le dipendenze di TRELLIS e non deve averle. Per ogni immagine produce una mesh
ad alta risoluzione con il colore sui vertici; decimazione, UV e texture si
fanno dopo in Blender (blender_ottimizza.py), cosi' si evitano nvdiffrast e
diff-gaussian-rasterization che TRELLIS usa per la texture ma hanno licenze
solo non commerciali.

    <venv>/python genera_mesh.py --immagini nome=foto.png[,nome2=altra.png] --uscita cartella

Per ogni nome: ritaglio.png, alto_gauss.ply (colori dalle gaussiane) e metriche.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[4]
sys.path.insert(0, str(ROOT))
# Gli shim vanno prima dei pacchetti veri: TRELLIS sceglie il backend all'import.
# Su Windows con Blackwell non ci sono ruote di flash-attn ne' di xformers con
# kernel CUDA: lo shim usa la SDPA di torch.
sys.path.insert(0, str(QUI / "shims"))
os.environ.setdefault("ATTN_BACKEND", "flash_attn")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "flash_attn")
os.environ.setdefault("SPCONV_ALGO", "native")
# Un token Hugging Face scaduto fa rispondere 401 anche ai repository pubblici
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

from core.logger import get_logger  # noqa: E402

log = get_logger("creative.trellis_locale")

# Coefficiente della banda 0 delle armoniche sferiche: colore = 0.5 + C0 * f_dc
SH_C0 = 0.28209479177387814


def colori_da_gaussiane(vertici, gauss):
    """Colore di ogni vertice come media delle gaussiane vicine pesata per opacita'.

    Il decoder della mesh ha una griglia colori grossolana (64^3 celle); le
    gaussiane sono 32 per voxel e conservano molti piu' dettagli della foto.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    xyz = gauss.get_xyz.detach().float().cpu().numpy()
    dc = gauss._features_dc.detach().float().cpu().numpy().reshape(len(xyz), -1)[:, :3]
    rgb = np.clip(0.5 + SH_C0 * dc, 0.0, 1.0)
    alpha = gauss.get_opacity.detach().float().cpu().numpy().reshape(-1)
    dist, idx = cKDTree(xyz).query(vertici, k=8)
    peso = alpha[idx] / (dist + 1e-3)
    peso /= peso.sum(axis=1, keepdims=True)
    return (rgb[idx] * peso[..., None]).sum(axis=1)


def salva_ply(percorso: Path, vertici, facce, colori) -> None:
    import numpy as np
    import trimesh

    rgba = np.concatenate([np.clip(colori, 0, 1) * 255, np.full((len(colori), 1), 255)], axis=1).astype(np.uint8)
    trimesh.Trimesh(vertices=vertici, faces=facce, vertex_colors=rgba, process=False).export(percorso)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--immagini", required=True, help="nome=percorso, separati da virgola")
    parser.add_argument("--uscita", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--passi", type=int, default=25, help="passi di campionamento di ciascuna fase")
    parser.add_argument("--ritaglio", default="birefnet-general", help="modello rembg per lo sfondo")
    args = parser.parse_args()

    import rembg
    import torch
    from PIL import Image
    from trellis.pipelines import TrellisImageTo3DPipeline

    t0 = time.perf_counter()
    pipeline = TrellisImageTo3DPipeline.from_pretrained("microsoft/TRELLIS-image-large")
    pipeline.cuda()
    caricamento = time.perf_counter() - t0
    log.info("TRELLIS caricato in %.1f s", caricamento)
    sessione = rembg.new_session(args.ritaglio)

    falliti = 0
    for voce in [v.strip() for v in args.immagini.split(",") if v.strip()]:
        nome, _, percorso = voce.partition("=")
        try:
            cartella = args.uscita / nome
            cartella.mkdir(parents=True, exist_ok=True)
            ritaglio = rembg.remove(Image.open(percorso).convert("RGB"), session=sessione)
            ritaglio.save(cartella / "ritaglio.png")

            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            t1 = time.perf_counter()
            out = pipeline.run(
                ritaglio,
                seed=args.seed,
                formats=["mesh", "gaussian"],
                sparse_structure_sampler_params={"steps": args.passi, "cfg_strength": 7.5},
                slat_sampler_params={"steps": args.passi, "cfg_strength": 3.0},
            )
            torch.cuda.synchronize()
            durata = time.perf_counter() - t1
            picco = torch.cuda.max_memory_reserved() / 2**30

            # La mesh esce gia' con Y in alto e il viso verso +Z: la rotazione
            # del to_glb di TRELLIS qui la faceva arrivare sdraiata in Blender
            mesh = out["mesh"][0]
            vertici = mesh.vertices.detach().float().cpu().numpy()
            facce = mesh.faces.detach().cpu().numpy()
            salva_ply(cartella / "alto_gauss.ply", vertici, facce, colori_da_gaussiane(vertici, out["gaussian"][0]))
            (cartella / "metriche.json").write_text(json.dumps({
                "modello": "microsoft/TRELLIS-image-large", "seed": args.seed, "passi": args.passi,
                "secondi": round(durata, 1), "caricamento_s": round(caricamento, 1),
                "vram_picco_gb": round(picco, 2), "triangoli": int(len(facce)),
                "gpu": torch.cuda.get_device_name(0),
            }, indent=2), encoding="utf-8")
            log.info("%s: %.1f s, %.2f GB, %d triangoli", nome, durata, picco, len(facce))
        except Exception:
            falliti += 1
            log.exception("generazione fallita per %s", nome)
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
