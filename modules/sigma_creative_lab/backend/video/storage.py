"""Percorsi delle produzioni: il progetto raccoglie anche le proprie esportazioni."""
from pathlib import Path


def export_path(store, prod: dict, version: int | None = None) -> Path:
    root = store.path(prod['id']).resolve()
    folder = root / 'exports'
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve().parent != root:
        raise ValueError('La cartella di esportazione deve restare nel progetto')
    name = 'master.mp4' if version is None else f'edit_v{int(version)}.mp4'
    return folder / name


def layout(store, prod: dict) -> dict:
    root = store.path(prod['id']).resolve()
    return {'project': str(root), 'exports': str(root / 'exports'),
            'assembly': str(root / 'assembly'), 'current_video': prod.get('output_path', ''),
            'legacy_export': bool(prod.get('output_path')) and
            not Path(prod['output_path']).resolve().is_relative_to(root / 'exports')}
