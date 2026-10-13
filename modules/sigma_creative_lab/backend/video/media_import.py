"""Media dell'utente nella timeline: video propri, immagini, audio e cartelli di testo.

Un video di presentazione e' fatto soprattutto di materiale reale (registrazioni
dello schermo, foto del prototipo, il logo) con titoli e voce narrante; i clip
generati servono per le scene che non si possono riprendere. Qui tutto diventa
un clip normalizzato (H.264, 24 fps, audio stereo 48 kHz) che la timeline tratta
come una qualunque versione di un'inquadratura.

I file importati si tengono fino a 1080p anche se la produzione genera a 480p:
l'export li riduce se serve, mentre una schermata di codice ridotta a 480p
diventerebbe illeggibile.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_media_import")

FPS = 24
MAX_HEIGHT = 1080
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
CHUNK_MAX = 16 * 1024 * 1024


def _ff():
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    return ffmpeg_bin, _run, probe


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    raise ValueError(f"formato non supportato: {ext or 'senza estensione'}")


def safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem)[:48].strip("_") or "media"
    return f"{stem}{Path(name).suffix.lower()}"


# ---------------------------------------------------------------------------
# Caricamento a pezzi
# ---------------------------------------------------------------------------

def append_chunk(upload_dir: Path, upload_id: str, offset: int, data: bytes) -> int:
    """Aggiunge un pezzo al file in arrivo; ritorna la dimensione raggiunta.

    A pezzi e non in un'unica richiesta: una registrazione dello schermo di
    qualche centinaio di MB in un solo corpo starebbe tutta in memoria, e sul
    Raspberry Pi non c'e' spazio per farlo.
    """
    if not re.fullmatch(r"[a-z0-9]{8,32}", upload_id):
        raise ValueError("identificativo di caricamento non valido")
    if len(data) > CHUNK_MAX:
        raise ValueError("pezzo troppo grande")
    upload_dir.mkdir(parents=True, exist_ok=True)
    part = upload_dir / f"{upload_id}.part"
    size = part.stat().st_size if part.exists() else 0
    if offset != size:
        # Un pezzo ripetuto (rete instabile) o fuori ordine: il client riparte da qui.
        raise ValueError(f"offset {offset} atteso {size}")
    with open(part, "ab") as f:
        f.write(data)
    return size + len(data)


def finish_upload(upload_dir: Path, upload_id: str, filename: str, target_dir: Path) -> Path:
    part = upload_dir / f"{upload_id}.part"
    if not part.is_file():
        raise ValueError("caricamento inesistente")
    target_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(filename)
    target = target_dir / f"{Path(name).stem}_{int(time.time())}{Path(name).suffix}"
    part.replace(target)
    return target


# ---------------------------------------------------------------------------
# Conversione in clip
# ---------------------------------------------------------------------------

def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def normalize_video(src: Path, out: Path) -> dict:
    """Video dell'utente in clip standard: fino a 1080p, 24 fps costanti, audio sempre presente."""
    ffmpeg_bin, _run, probe = _ff()
    info = probe(src)
    h = min(MAX_HEIGHT, int(info["height"] or MAX_HEIGHT))
    vf = f"scale=-2:{h}:flags=lanczos,fps={FPS},format=yuv420p"
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-i", str(src)]
    if info["has_audio"]:
        cmd += ["-map", "0:v:0", "-map", "0:a:0", "-vf", vf, "-af", "aresample=48000", "-ac", "2"]
    else:
        # La timeline e l'export lavorano con clip che hanno sempre audio.
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a",
                "-vf", vf, "-shortest"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", str(out)]
    _run(cmd, timeout=3600)
    done = probe(out)
    return {"clip_path": str(out), "frames": done["frames"] or round(done["duration"] * FPS),
            "width": done["width"], "height": done["height"]}


MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "none")


def image_to_clip(image: Path, out: Path, seconds: float = 4.0, size: tuple[int, int] = (1920, 1080),
                  motion: str = "zoom_in") -> dict:
    """Immagine ferma in clip con un movimento lento (effetto Ken Burns).

    Un'immagine immobile per quattro secondi sembra un errore di montaggio; un
    avvicinamento dell'8% la fa sembrare una ripresa. L'immagine si adatta al
    formato senza deformarsi: lo spazio in piu' si riempie con la stessa
    immagine sfocata, come nei servizi televisivi.
    """
    ffmpeg_bin, _run, probe = _ff()
    w, h = _even(size[0]), _even(size[1])
    n = max(1, int(round(seconds * FPS)))
    # Si lavora al doppio della risoluzione: zoompan arrotonda le coordinate ai
    # pixel e a risoluzione finale il movimento lento "scatta".
    W, H = w * 2, h * 2
    zoom = {"zoom_in": f"1+0.08*on/{n}", "zoom_out": f"1.08-0.08*on/{n}"}.get(motion, "1.06")
    x = {"pan_left": f"(iw-iw/zoom)*(1-on/{n})", "pan_right": f"(iw-iw/zoom)*on/{n}"}.get(motion, "(iw-iw/zoom)/2")
    if motion == "none":
        zoom, x = "1", "0"
    graph = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:5[bg];"
             f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
             f"zoompan=z='{zoom}':x='{x}':y='(ih-ih/zoom)/2':d={n}:s={w}x{h}:fps={FPS},format=yuv420p[v]")
    _run([ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", str(image), "-f", "lavfi",
          "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
          "-frames:v", str(n), "-t", f"{n / FPS:.3f}", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
          "-c:a", "aac", "-b:a", "128k", str(out)], timeout=900)
    return {"clip_path": str(out), "frames": n, "width": w, "height": h}


# ---------------------------------------------------------------------------
# Testo: cartelli e testi sovrapposti
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = {
    "sans": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Helvetica.ttc"],
    "sans_bold": ["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/arialbd.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"],
    "serif": ["C:/Windows/Fonts/georgia.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
              "/System/Library/Fonts/Times.ttc"],
}


def font(kind: str, size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES.get(kind, _FONT_CANDIDATES["sans"]):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for word in words:
            probe = f"{line} {word}".strip()
            if draw.textlength(probe, font=fnt) <= max_w or not line:
                line = probe
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


TEXT_STYLES = ("title", "lower", "caption")


def render_text(size: tuple[int, int], text: str, sub: str = "", style: str = "title", color: str = "#ffffff",
                accent: str = "#4fc3f7", font_kind: str = "sans_bold"):
    """Immagine trasparente con il testo impaginato: titolo centrale, sottopancia o didascalia."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if style == "title":
        big, small = font(font_kind, int(h * 0.085)), font("sans", int(h * 0.04))
        lines = _wrap(draw, text, big, int(w * 0.8))
        sub_lines = _wrap(draw, sub, small, int(w * 0.75)) if sub else []
        lh, sh = int(h * 0.1), int(h * 0.055)
        y = (h - (len(lines) * lh + (len(sub_lines) * sh + int(h * 0.03) if sub_lines else 0))) // 2
        blocks = [(ln, big, lh, color) for ln in lines] + [(ln, small, sh, "#d8d8d8") for ln in sub_lines]
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        yy = y
        for k, (ln, fnt, step, col) in enumerate(blocks):
            if k == len(lines) and sub_lines:
                yy += int(h * 0.03)
            tw = draw.textlength(ln, font=fnt)
            sd.text(((w - tw) / 2 + 3, yy + 3), ln, font=fnt, fill=(0, 0, 0, 200))
            draw.text(((w - tw) / 2, yy), ln, font=fnt, fill=col)
            yy += step
        # Ombra morbida sotto il testo: leggibile anche su immagini chiare.
        img = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(h * 0.006)), img)
    elif style == "lower":
        big, small = font(font_kind, int(h * 0.05)), font("sans", int(h * 0.032))
        x0, y0 = int(w * 0.06), int(h * 0.74)
        tw = max(draw.textlength(text, font=big), draw.textlength(sub, font=small) if sub else 0)
        box_h = int(h * (0.12 if sub else 0.085))
        draw.rectangle([x0 - int(h * 0.02), y0 - int(h * 0.015), x0 + tw + int(h * 0.03), y0 + box_h],
                       fill=(0, 0, 0, 165))
        draw.rectangle([x0 - int(h * 0.02), y0 - int(h * 0.015), x0 - int(h * 0.012), y0 + box_h], fill=accent)
        draw.text((x0, y0), text, font=big, fill=color)
        if sub:
            draw.text((x0, y0 + int(h * 0.062)), sub, font=small, fill="#dddddd")
    else:                                                  # caption: testo in basso al centro
        fnt = font("sans", int(h * 0.042))
        lines = _wrap(draw, text, fnt, int(w * 0.84))
        lh = int(h * 0.055)
        y = int(h * 0.9) - len(lines) * lh
        for ln in lines:
            tw = draw.textlength(ln, font=fnt)
            pad = int(h * 0.012)
            draw.rectangle([(w - tw) / 2 - pad, y - pad // 2, (w + tw) / 2 + pad, y + lh - pad // 2], fill=(0, 0, 0, 150))
            draw.text(((w - tw) / 2, y), ln, font=fnt, fill=color)
            y += lh
    return img


def title_card(out: Path, title: str, sub: str = "", seconds: float = 3.5, size: tuple[int, int] = (1920, 1080),
               background: str = "#101418", background_image: Path | None = None, accent: str = "#4fc3f7") -> dict:
    """Cartello a tutto schermo: titolo e sottotitolo su un colore o su un'immagine sfocata, con dissolvenze."""
    from PIL import Image, ImageFilter
    ffmpeg_bin, _run, _probe = _ff()
    w, h = _even(size[0]), _even(size[1])
    if background_image and Path(background_image).is_file():
        bg = Image.open(background_image).convert("RGB")
        scale = max(w / bg.width, h / bg.height)
        bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
        left, top = (bg.width - w) // 2, (bg.height - h) // 2
        bg = bg.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(h * 0.02))
        bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.45)   # piu' scuro: il testo resta leggibile
    else:
        bg = Image.new("RGB", (w, h), background)
    frame = Image.alpha_composite(bg.convert("RGBA"), render_text((w, h), title, sub, "title", accent=accent))
    png = out.with_suffix(".png")
    frame.convert("RGB").save(png)
    n = max(1, int(round(seconds * FPS)))
    fade = min(0.5, seconds / 4)
    _run([ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", str(png), "-f", "lavfi",
          "-i", "anullsrc=r=48000:cl=stereo",
          "-vf", f"zoompan=z='1+0.03*on/{n}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={n}:s={w}x{h}:fps={FPS},"
                 f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={n / FPS - fade:.2f}:d={fade:.2f},format=yuv420p",
          "-map", "0:v", "-map", "1:a", "-frames:v", str(n), "-t", f"{n / FPS:.3f}",
          "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "128k", str(out)], timeout=600)
    return {"clip_path": str(out), "frames": n, "width": w, "height": h, "poster": str(png)}


def overlay_png(out: Path, size: tuple[int, int], text: str, sub: str = "", style: str = "lower",
                accent: str = "#4fc3f7") -> Path:
    render_text(size, text, sub, style, accent=accent).save(out)
    return out

