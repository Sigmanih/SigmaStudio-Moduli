"""TRELLIS in locale: il backend 3D che non chiede ComfyUI personalizzato ne' chiavi API.

TRELLIS (Microsoft, licenza MIT) gira in un venv suo, store/engine_runtime/image3d,
con torch cu128 per le schede Blackwell: il kernel e il modulo non ne importano
nulla e lo lanciano in sottoprocesso. Blender fa decimazione, texture e rig.

Qui stanno i passi riusabili: dalla foto alla mesh (genera_mesh.py), dalla mesh
a un GLB leggero (blender_ottimizza.py), dal GLB al personaggio con scheletro
(blender_rig.py), e la scelta della figura migliore (scegli_variante.py).
LocalTrellisAdapter li offre al Creative Studio come backend "local".
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from core import paths
from core.logger import get_logger

log = get_logger("creative.trellis_locale")

QUI = Path(__file__).resolve().parent
RUNTIME = paths.store_dir() / "engine_runtime" / "image3d"
TRELLIS_SRC = RUNTIME / "src" / "TRELLIS"
#: Universal Animation Library di Quaternius (CC0): scheletro, manichino e clip
LIBRERIA_ANIMAZIONI = RUNTIME / "animazioni" / "AnimationLibrary_Godot_Standard.glb"

TIMEOUT_TRELLIS = 1800  # caricamento (anche il primo download) e generazione
TIMEOUT_BLENDER = 900


def python_venv() -> Path:
    nome = "python.exe" if sys.platform == "win32" else "python"
    cartella = "Scripts" if sys.platform == "win32" else "bin"
    return RUNTIME / "venv" / cartella / nome


def blender_exe() -> str:
    from core.modules.sigma_creative_lab.three_d.blender_bridge import BlenderBridge
    return BlenderBridge().blender_path or ""


def disponibile() -> tuple[bool, str]:
    """Pronto se ci sono venv, sorgenti di TRELLIS, Blender e una GPU CUDA."""
    if not python_venv().is_file():
        return False, f"manca il venv di TRELLIS in {RUNTIME / 'venv'}"
    if not TRELLIS_SRC.is_dir():
        return False, f"mancano i sorgenti di TRELLIS in {TRELLIS_SRC}"
    if not blender_exe():
        return False, "Blender non trovato: serve per texture, decimazione e rig"
    return True, ""


def libera_comfyui() -> None:
    """TRELLIS vuole ~12 GB: con klein ancora in VRAM debordava in RAM e passava da 8 a 500 s."""
    try:
        from core.modules.sigma_creative_lab.backends.comfy_launcher import BASE_PORT, instances
        for gpu in (0, 1):
            instances.free(BASE_PORT + gpu)
    except Exception as exc:
        log.debug("ComfyUI non liberato: %s", exc)


def _esegui(cmd: list[str], timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    log.info("Avvio: %s", " ".join(str(c) for c in cmd[:4]))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=env, cwd=str(paths.project_root()))
    if r.returncode != 0:
        coda = (r.stderr or r.stdout or "")[-1500:]
        raise RuntimeError(f"{Path(cmd[1] if len(cmd) > 1 else cmd[0]).name} uscito con {r.returncode}: {coda}")
    return r


def genera_mesh(immagini: dict[str, Path], uscita: Path, seed: int = 1) -> None:
    """Una cartella per nome con alto_gauss.ply e metriche.json."""
    libera_comfyui()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(TRELLIS_SRC)
    # La 5070 Ti: la prima scheda per bus PCI, indipendente dall'ordine di CUDA
    env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    elenco = ",".join(f"{n}={p}" for n, p in immagini.items())
    _esegui([str(python_venv()), str(QUI / "genera_mesh.py"), "--immagini", elenco,
             "--uscita", str(uscita), "--seed", str(seed)], TIMEOUT_TRELLIS, env)


def ottimizza(ply: Path, glb: Path, triangoli: int = 12000, texture: int = 1024,
              anteprima: Path | None = None) -> dict:
    cmd = [blender_exe(), "--background", "--factory-startup", "--python", str(QUI / "blender_ottimizza.py"),
           "--", "--ingresso", str(ply), "--uscita", str(glb), "--triangoli", str(triangoli),
           "--texture", str(texture)]
    if anteprima:
        cmd += ["--anteprima", str(anteprima)]
    _esegui(cmd, TIMEOUT_BLENDER)
    return json.loads(glb.with_name("dettagli.json").read_text(encoding="utf-8"))


def rig(statico: Path, personaggio: Path, animazioni: Path | None = None) -> None:
    cmd = [blender_exe(), "--background", "--factory-startup", "--python", str(QUI / "blender_rig.py"),
           "--", "--personaggio", str(statico), "--libreria", str(LIBRERIA_ANIMAZIONI),
           "--uscita", str(personaggio)]
    if animazioni:
        cmd += ["--animazioni", str(animazioni)]
    _esegui(cmd, TIMEOUT_BLENDER)


def scegli_variante(immagini: list[Path]) -> Path:
    r = _esegui([str(python_venv()), str(QUI / "scegli_variante.py"), *map(str, immagini)], 600)
    esito = json.loads(r.stdout.strip().splitlines()[-1])
    log.info("Varianti: %s", esito["punteggi"])
    return Path(esito["scelta"])


class LocalTrellisAdapter:
    """Image to 3D del Creative Studio con TRELLIS sulla GPU locale.

    Restituisce un GLB texturizzato gia' alleggerito: `triangoli` e `texture`
    nei parametri regolano il compromesso fra dettaglio e peso.
    """

    async def image_to_3d(self, image_bytes: bytes, params: dict) -> tuple[bytes, str]:
        return await asyncio.to_thread(self._image_to_3d, image_bytes, params or {})

    def _image_to_3d(self, image_bytes: bytes, params: dict) -> tuple[bytes, str]:
        with tempfile.TemporaryDirectory(prefix="trellis_") as tmp:
            cartella = Path(tmp)
            foto = cartella / "ingresso.png"
            foto.write_bytes(image_bytes)
            # Il Creative Studio usa -1 per "casuale": TRELLIS vuole un seed esplicito
            seed = int(params.get("seed") or 1)
            genera_mesh({"mesh": foto}, cartella, seed=seed if seed >= 0 else 1)
            glb = cartella / "mesh" / "modello.glb"
            ottimizza(cartella / "mesh" / "alto_gauss.ply", glb,
                      triangoli=int(params.get("triangoli") or 40000), texture=int(params.get("texture") or 2048))
            return glb.read_bytes(), "glb"


def build_local_adapter():
    pronto, motivo = disponibile()
    if not pronto:
        log.debug("TRELLIS locale non disponibile: %s", motivo)
        return None
    return LocalTrellisAdapter()
