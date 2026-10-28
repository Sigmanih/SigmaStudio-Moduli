"""Dal ritratto di un agente al suo personaggio 3D animabile, in un solo comando.

La catena che ha prodotto i personaggi della plancia, senza passi a mano:

1. FLUX.2 klein 4B (Apache 2.0) disegna dal ritratto alcune figure intere in
   A-pose, con le braccia larghe: con le braccia vicine ai fianchi TRELLIS le
   univa al busto e il rig lasciava schegge;
2. scegli_variante.py sceglie la figura con le braccia piu' staccate;
3. TRELLIS fa la mesh, Blender la alleggerisce (12k triangoli, texture 1024);
4. blender_rig.py le da' lo scheletro della Universal Animation Library (CC0).

Il risultato finisce in works/creative/agenti_3d/<nome>/ e nel Creative Studio
come asset 3D. Per pubblicarlo con il ruolo: tools/agenti_3d/pacchetti.py.

    python -m core.modules.sigma_creative_lab.three_d.locale.agenti genera --nome sceneggiatore \
        --ritratto sigma_studio/public/images/sceneggiatore.jpg
    python -m core.modules.sigma_creative_lab.three_d.locale.agenti importa
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from core import paths
from core.logger import get_logger
from core.modules.sigma_creative_lab.three_d.locale import trellis_locale as TL

log = get_logger("creative.agenti_3d")

# Il ritratto contiene spesso tavolo, libri, schermi o scritte: vanno esclusi
# esplicitamente, altrimenti klein li porta nella figura e TRELLIS li fonde al corpo.
PROMPT_FIGURA = (
    "Full body shot of the exact same character as in the reference image, same face, same outfit, "
    "same colors and materials. Standing upright in an A-pose: both arms straight, extended diagonally "
    "down and outward at about 45 degrees from the torso, with a wide clear gap of empty space between "
    "each arm and the body, hands open with palms facing forward, legs straight with feet shoulder "
    "width apart, facing the camera. "
    "The whole figure is visible from the top of the head to the feet, centered. "
    "Plain light grey studio background, soft even lighting, no shadows on the floor. "
    "No table, no furniture, no props, no other people, no text."
)


def cartella_agenti() -> Path:
    return paths.creative_dir() / "agenti_3d"


async def _figure_intere(nome: str, ritratto: Path, cartella: Path, varianti: int, seed: int) -> list[Path]:
    from core.modules.sigma_creative_lab.video import image_gen

    uscite = []
    for i in range(varianti):
        out = cartella / f"figura_{seed + i}.png"
        r = await image_gen.generate("klein", PROMPT_FIGURA, out, width=768, height=1344,
                                     seed=seed + i, refs=[str(ritratto)])
        log.info("%s: figura %d in %.1f s", nome, seed + i, r["seconds"])
        uscite.append(out)
    return uscite


def registra_asset(nome: str, personaggio: Path, anteprima: Path | None, metadati: dict):
    """Il personaggio compare nel Creative Studio tra gli asset 3D."""
    from core.modules.sigma_creative_lab.asset_graph import AssetGraph, AssetType

    grafo = AssetGraph()
    asset = grafo.create_asset(type_val=AssetType.MODEL_3D, name=f"agente_{nome}",
                               metadata={"operation": "agente_3d", **metadati}, tags=["agente", nome])
    asset = grafo.attach_file(asset.asset_id, "model", "personaggio.glb", personaggio.read_bytes())
    if anteprima and anteprima.is_file():
        asset = grafo.attach_file(asset.asset_id, "image", f"anteprima{anteprima.suffix}", anteprima.read_bytes())
    return asset


async def genera_agente(nome: str, ritratto: Path, varianti: int = 4, seed: int = 21,
                        registra: bool = True) -> dict:
    pronto, motivo = TL.disponibile()
    if not pronto:
        raise RuntimeError(f"TRELLIS locale non disponibile: {motivo}")
    if not TL.LIBRERIA_ANIMAZIONI.is_file():
        raise RuntimeError(f"manca la libreria di animazioni in {TL.LIBRERIA_ANIMAZIONI}")
    cartella = cartella_agenti() / nome
    cartella.mkdir(parents=True, exist_ok=True)

    figure = await _figure_intere(nome, ritratto, cartella, varianti, seed)
    scelta = await asyncio.to_thread(TL.scegli_variante, figure)
    await asyncio.to_thread(TL.genera_mesh, {"mesh": scelta}, cartella, 1)
    statico = cartella / "statico.glb"
    dettagli = await asyncio.to_thread(TL.ottimizza, cartella / "mesh" / "alto_gauss.ply", statico,
                                       12000, 1024, cartella / "anteprima.png")
    personaggio = cartella / "personaggio.glb"
    await asyncio.to_thread(TL.rig, statico, personaggio)

    metadati = {"ritratto": str(ritratto), "figura": scelta.name, **dettagli}
    (cartella / "agente.json").write_text(json.dumps(metadati, indent=2, ensure_ascii=False), encoding="utf-8")
    if registra:
        registra_asset(nome, personaggio, cartella / "anteprima_fronte.png", metadati)
    log.info("%s: personaggio pronto in %s", nome, personaggio)
    return {"personaggio": str(personaggio), **metadati}


def importa_installati() -> list[str]:
    """Porta nel Creative Studio i personaggi gia' arrivati con i ruoli installati."""
    from core.modules.sigma_creative_lab.asset_graph import AssetGraph

    # Non si duplica chi e' gia' stato importato
    presenti = {a.name for a in AssetGraph().list_assets(tag_filter="agente", limit=1000)}
    importati = []
    for glb in sorted(paths.roles_dir().glob("*/personaggio.glb")):
        nome = glb.parent.name
        if f"agente_{nome}" in presenti:
            continue
        immagine = next((glb.parent / n for n in ("immagine.jpg", "immagine.png") if (glb.parent / n).is_file()), None)
        registra_asset(nome, glb, immagine, {"fonte": "ruolo installato"})
        importati.append(nome)
    log.info("Personaggi importati nel Creative Studio: %d", len(importati))
    return importati


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("genera", help="ritratto -> personaggio animabile")
    g.add_argument("--nome", required=True)
    g.add_argument("--ritratto", type=Path, required=True)
    g.add_argument("--varianti", type=int, default=4)
    g.add_argument("--seed", type=int, default=21)
    sub.add_parser("importa", help="i personaggi dei ruoli installati nel Creative Studio")
    args = p.parse_args()

    if args.comando == "importa":
        importa_installati()
        return 0
    try:
        asyncio.run(genera_agente(args.nome, args.ritratto, args.varianti, args.seed))
        return 0
    except Exception:
        log.exception("personaggio non generato per %s", args.nome)
        return 1


if __name__ == "__main__":
    sys.exit(main())
