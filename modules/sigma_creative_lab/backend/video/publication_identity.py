"""Identità editoriale renderizzata dai dati del film, mai ereditata da un altro master."""
import json
import hashlib
import os
import re
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_template(directory):
    path = Path(directory) / 'sigla_template.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('La sigla deve avere un template verificato sigla_template.json') from exc
    if not isinstance(value, dict) or value.get('layout') != 'sigma-logo-title-v1':
        raise ValueError('Layout della sigla non supportato: prepara un template neutro')
    for kind in ('intro', 'outro'):
        clip = Path(directory) / f'{kind}.mp4'
        if not clip.is_file() or file_sha256(clip) != value.get(f'{kind}_sha256'):
            raise ValueError(f'Il video {kind} è cambiato: verifica nuovamente il template della sigla')
    voices = value.get('audio_sha256', {})
    if not isinstance(voices, dict):
        raise ValueError('Registro delle voci della sigla non valido')
    for name, digest in voices.items():
        if not re.fullmatch(r'(intro|outro)_[a-z]{2}\.wav', name):
            raise ValueError('Nome della voce della sigla non valido')
        audio = Path(directory) / name
        if not audio.is_file() or file_sha256(audio) != digest:
            raise ValueError(f'Audio della sigla cambiato: verifica nuovamente {name}')
    return value


def title_overlay(width, height, title, year, target, edition='RESTORED EDITION'):
    from PIL import Image, ImageDraw, ImageFont
    title = str(title).strip()
    if not title or len(title) > 100:
        raise ValueError('Titolo del film obbligatorio e non superiore a 100 caratteri')
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    # Il template dichiara questa fascia riservata: si eliminano anche i titoli già impressi.
    draw.rectangle((0, int(height * .70), width, height), fill=(8, 9, 24, 255))
    candidates = ([Path(os.environ.get('WINDIR', '')) / 'Fonts' / 'arial.ttf'] if os.name == 'nt'
                  else [Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')])
    font_path = next((p for p in candidates if p.is_file()), None)
    if font_path is None:
        raise ValueError('Installa un font TrueType per renderizzare il titolo senza sostituzioni')
    label = title + (f' · {year}' if year else '')
    size = max(16, height // 24)
    while True:
        font = ImageFont.truetype(str(font_path), size)
        box = draw.textbbox((0, 0), label, font=font)
        if box[2] - box[0] <= width * .90 or size <= 12:
            break
        size -= 1
    draw.text(((width - box[2] + box[0]) / 2, height * .75), label, font=font, fill='white')
    subtitle = 'SIGMA STUDIO · ' + edition
    font = ImageFont.truetype(str(font_path), max(12, height // 42))
    box = draw.textbbox((0, 0), subtitle, font=font)
    draw.text(((width - box[2] + box[0]) / 2, height * .84), subtitle, font=font, fill=(186, 170, 244))
    canvas.save(target)
    return target


def verify_title_frame(video, overlay, at, target):
    from PIL import Image, ImageChops, ImageStat
    from .production import _run, ffmpeg_bin
    _run([ffmpeg_bin(), '-v', 'error', '-y', '-ss', str(at), '-i', str(video), '-frames:v', '1', str(target)], 120)
    with Image.open(target) as actual, Image.open(overlay) as expected:
        actual, expected = actual.convert('RGB'), expected.convert('RGB')
        if actual.size != expected.size:
            raise ValueError('Risoluzione della sigla diversa dal template')
        bounds = (0, int(actual.height * .70) + 4, actual.width, actual.height)
        actual, expected = actual.crop(bounds), expected.crop(bounds)
        # La media sull'intera fascia nasconderebbe un titolo errato fra molti pixel scuri.
        mask = ImageChops.lighter(actual.convert('L'), expected.convert('L')).point(lambda value: 255 if value > 60 else 0)
        difference = ImageStat.Stat(ImageChops.difference(actual, expected), mask)
        if not mask.getbbox() or max(difference.mean) > 20:
            raise ValueError('Il titolo nel video finale non coincide con il cartello generato per il film')
        # Anche una sola cifra dell'anno deve essere controllata, senza diluirla nel resto del titolo.
        tile = max(8, expected.height // 8)
        for top in range(0, expected.height, tile):
            for left in range(0, expected.width, tile):
                region = (left, top, min(left + tile, expected.width), min(top + tile, expected.height))
                local_mask = mask.crop(region)
                if sum(local_mask.histogram()[1:]) < 8:
                    continue
                local = ImageStat.Stat(ImageChops.difference(actual.crop(region), expected.crop(region)), local_mask)
                if max(local.mean) > 35:
                    raise ValueError('Il titolo nel video finale non coincide con il cartello generato per il film')
    return str(target)
