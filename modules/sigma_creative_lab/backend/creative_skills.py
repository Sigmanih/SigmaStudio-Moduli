"""Contratti operativi condivisi da interfaccia e agenti Creative."""
from pathlib import Path

SKILLS = (
    {"id": "creative-images", "label": "Immagini e ritocco",
     "description": "Scelta del modello, generazione, modifica e verifica dell'immagine.",
     "tools": ["generate_image", "edit_image", "upscale_image", "analyze_image"],
     "inputs": ["descrizione o immagine", "modello o profilo", "formato"],
     "outputs": ["asset_id", "url", "provenienza"]},
    {"id": "creative-3d-materials", "label": "3D e materiali",
     "description": "Ricostruzione 3D, mappe e rendering con sorgenti e strumenti verificati.",
     "tools": ["generate_3d", "generate_material", "render_3d"],
     "inputs": ["immagine o mesh", "operazione", "parametri"],
     "outputs": ["asset_id", "url", "provenienza"]},
    {"id": "creative-pipelines", "label": "Automazioni creative",
     "description": "Pipeline con dipendenze esplicite ed esiti verificabili per passaggio.",
     "tools": ["list_creative_capabilities", "list_creative_assets", "run_creative_pipeline"],
     "inputs": ["nodi", "collegamenti", "asset iniziali"],
     "outputs": ["asset prodotti", "esiti dei passaggi", "errori"]},
)


def skill_catalog(with_instructions: bool = False) -> list[dict]:
    result = []
    for skill in SKILLS:
        entry = {**skill, "uri": f"creative://skills/{skill['id']}"}
        if with_instructions:
            entry["instructions"] = (Path(__file__).parent / "skills" / skill["id"] / "SKILL.md").read_text(encoding="utf-8")
        result.append(entry)
    return result
