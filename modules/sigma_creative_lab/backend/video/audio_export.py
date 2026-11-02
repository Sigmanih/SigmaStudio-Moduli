"""Esportazione di un master con tracce vocali e sottotitoli selezionabili."""

from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger("creative_audio_export")

LANG_TAGS = {"en": ("eng", "English"), "it": ("ita", "Italiano"), "fr": ("fra", "Français"),
             "de": ("deu", "Deutsch"), "es": ("spa", "Español"), "pt": ("por", "Português"),
             "zh": ("zho", "中文"), "ar": ("ara", "العربية")}

SIGLA_CTA = {"en": "SUBSCRIBE", "it": "ISCRIVITI", "fr": "ABONNEZ-VOUS", "de": "ABONNIEREN",
             "es": "SUSCRÍBETE", "pt": "INSCREVA-SE", "zh": "订阅频道", "ar": "اشترك بالقناة"}


def _flags() -> int:
    import subprocess
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _audio_mix(tracks: list[dict], language: str, out: Path, duration: float,
               source_audio: Path | None = None, source_is_dialogue: bool = False) -> None:
    import subprocess
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin

    cmd = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", "-filter_complex_threads", "2"]
    graph, buses = [], {"voice": [], "dialogue": [], "music": [], "sfx": []}
    index = -1
    if source_audio:
        from core.modules.sigma_creative_lab.video.score_quality import source_music_filter
        cmd += ["-i", str(source_audio)]
        index = 0
        source_filter = 'anull' if source_is_dialogue else source_music_filter(tracks)
        gain = 0 if source_is_dialogue else -6
        graph.append(f"[0:a]{source_filter},aresample=48000,aformat=channel_layouts=stereo,volume={gain}dB,apad,"
                     f"atrim=duration={duration:.6f}[original]")
        buses['dialogue' if source_is_dialogue else 'music'].append('[original]')
    for track in tracks:
        kind = track.get("kind")
        if kind not in buses:
            continue
        is_restore_track = str(track.get("id", "")).startswith("restore_voice_")
        if is_restore_track:
            if not str(track["id"]).endswith(f"_{language}"):
                continue
        elif track.get("mute"):
            continue
        for clip in track.get("clips") or []:
            source = Path(str(clip.get("src") or ""))
            if not source.is_file():
                log.warning(f"clip audio mancante, saltata: {source}")
                continue
            index += 1
            cmd += ["-i", str(source)]
            span = max(0.02, float(clip["src_out"]) - float(clip.get("src_in", 0.0)))
            delay = max(0, round(float(clip.get("start", 0.0)) * 1000))
            gain = float(track.get("gain_db", 0.0)) + float(clip.get("gain_db", 0.0))
            fade_in = max(0.02, float(clip.get("fade_in") or 0.0))
            fade_out = max(0.02, float(clip.get("fade_out") or 0.0))
            label = f"a{index}"
            graph.append(f"[{index}:a]atrim=start={float(clip.get('src_in', 0.0)):.4f}:duration={span:.4f},"
                         f"asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={gain}dB,"
                         f"afade=t=in:d={fade_in:.3f},afade=t=out:st={max(0.0, span-fade_out):.4f}:d={fade_out:.3f},"
                         f"adelay={delay}|{delay}[{label}]")
            buses[kind].append(f"[{label}]")

    if not any(buses.values()):
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph.append("[0:a]atrim=duration=" + f"{duration:.6f}[mix]")
    else:
        def bus(name: str, labels: list[str]) -> str:
            if len(labels) == 1:
                graph.append(f"{labels[0]}anull[{name}]")
            else:
                graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[{name}]")
            return f"[{name}]"

        speech_parts = buses["voice"] + buses["dialogue"]
        speech = bus("speech", speech_parts) if speech_parts else None
        final_parts = []
        if speech:
            final_parts.append(speech)
        if buses["music"]:
            music = bus("music", buses["music"])
            if speech:
                graph.append(f"{speech}asplit=2[speech_out][speech_key]")
                graph.append(f"[speech_key]apad,atrim=duration={duration:.6f}[speech_key_full]")
                graph.append(f"{music}[speech_key_full]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[ducked]")
                final_parts = ["[speech_out]", "[ducked]"]
            else:
                final_parts.append(music)
        if buses["sfx"]:
            final_parts.append(bus("sfx", buses["sfx"]))
        graph.append(f"{''.join(final_parts)}amix=inputs={len(final_parts)}:duration=longest:normalize=0,"
                     f"alimiter=limit=0.95,apad,atrim=duration={duration:.6f}[mix]")
    codec = ["-c:a", "flac"] if out.suffix.lower() == ".flac" else ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    cmd += ["-filter_complex", ";".join(graph), "-map", "[mix]", "-t", f"{duration:.6f}",
            *codec, "-threads", "2", "-ar", "48000", "-ac", "2", str(out)]
    _run(cmd, timeout=1800)


def _track_for_language(track: dict, language: str) -> bool:
    if track.get("kind") == "voice" and str(track.get("id", "")).startswith("restore_voice_"):
        return str(track["id"]).endswith(f"_{language}")
    return not track.get("mute")


def validate_sigla_assets(asset_dir: str | Path, languages: list[str]) -> dict:
    """Valida i video e le voci della sigla prima di avviare i passaggi costosi."""
    from core.modules.sigma_creative_lab.video.production import probe

    root = Path(asset_dir).expanduser().resolve()
    intro, outro = root / "intro.mp4", root / "outro.mp4"
    missing = [str(p) for p in (intro, outro) if not p.is_file()]
    audio = {lang: (root / f"intro_{lang}.wav", root / f"outro_{lang}.wav") for lang in languages}
    missing.extend(str(p) for pair in audio.values() for p in pair if not p.is_file())
    if missing:
        raise ValueError("Asset della sigla mancanti: " + ", ".join(missing[:8]))
    intro_info, outro_info = probe(intro), probe(outro)
    for label, info in (("intro", intro_info), ("outro", outro_info)):
        if not info["width"] or not info["height"] or info["duration"] <= 0:
            raise ValueError(f"Il video {label} della sigla non è valido")
    for lang, (voice_in, voice_out) in audio.items():
        for label, path, duration in (("intro", voice_in, intro_info["duration"]),
                                      ("outro", voice_out, outro_info["duration"])):
            info = probe(path)
            if not info["has_audio"] or abs(info["audio_duration"] - duration) > 0.5:
                raise ValueError(f"La voce {label} {lang.upper()} deve durare {duration:.2f} s: {path}")
    return {"directory": root, "intro": intro, "outro": outro,
            "intro_duration": intro_info["duration"], "outro_duration": outro_info["duration"],
            "voices": audio}


def _sigla_overlays(width: int, height: int, work: Path, cta_language: str,
                    logo_frame: Path) -> tuple[Path, Path]:
    """Ritaglia il marchio in un alpha-mask circolare e crea il pulsante finale."""
    from PIL import Image, ImageDraw, ImageFont

    logo_path, button_path = work / "sigma_logo_circle.png", work / "sigla_subscribe.png"
    frame = Image.open(logo_frame).convert("RGBA")
    side = min(frame.width, int(frame.height * 0.55))
    left, top = (frame.width - side) // 2, int(frame.height * 0.05)
    logo = frame.crop((left, top, left + side, top + side))
    diameter = int(min(width * 0.42, height * 0.55))
    logo = logo.resize((diameter * 3, diameter * 3), Image.Resampling.LANCZOS)
    mask = Image.new("L", logo.size, 0)
    ImageDraw.Draw(mask).ellipse((2, 2, logo.width - 3, logo.height - 3), fill=255)
    logo = logo.resize((diameter, diameter), Image.Resampling.LANCZOS)
    logo.putalpha(mask.resize((diameter, diameter), Image.Resampling.LANCZOS))
    logo.save(logo_path)

    bw, bh = int(width * 0.30), int(height * 0.082)
    button = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(button)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=bh // 3,
                        fill=(220, 35, 55, 248), outline=(255, 150, 165, 255), width=max(2, width // 720))
    text = SIGLA_CTA.get(cta_language, SIGLA_CTA["en"])
    try:
        import os
        candidates = ([Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf"]
                      if os.name == "nt" else [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")])
        font = next((ImageFont.truetype(str(path), max(18, width // 36)) for path in candidates if path.is_file()),
                    ImageFont.load_default())
        try:
            box = d.textbbox((0, 0), text, font=font, direction="rtl" if cta_language == "ar" else None)
            d.text(((bw - (box[2] - box[0])) // 2, (bh - (box[3] - box[1])) // 2 - box[1]),
                   text, font=font, fill=(255, 255, 255, 255), direction="rtl" if cta_language == "ar" else None)
        except (TypeError, ValueError, UnicodeEncodeError):
            text, font = SIGLA_CTA["en"], ImageFont.load_default()
            box = d.textbbox((0, 0), text, font=font)
            d.text(((bw - (box[2] - box[0])) // 2, (bh - (box[3] - box[1])) // 2 - box[1]),
                   text, font=font, fill=(255, 255, 255, 255))
    except OSError:
        d.text((20, bh // 3), "SUBSCRIBE", fill=(255, 255, 255, 255))
    button.save(button_path)
    return logo_path, button_path


def _join_sigla_video(source: Path, bumpers: list[Path], output: Path, info: dict) -> bool:
    """Conserva il bitstream del film quando i segmenti possono essere concatenati."""
    import json
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin
    from core.modules.sigma_creative_lab.video.postprocess import video_encoder_args
    document = json.loads(_run([ffmpeg_bin('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
                               '-show_entries', 'stream=codec_name,pix_fmt,r_frame_rate,time_base',
                               '-of', 'json', str(source)]).stdout)
    video = next(iter(document.get('streams', [])), {})
    if (video.get('codec_name') != 'h264' or video.get('pix_fmt') != 'yuv420p'
            or video.get('r_frame_rate') != '24/1'):
        return False
    denominator = int(video.get('time_base', '1/12288').split('/')[-1])
    normalized = []
    for index, bumper in enumerate(bumpers):
        target = output.parent / f'bumper_copy_{index}.mp4'
        _run([ffmpeg_bin(), '-hide_banner', '-v', 'error', '-y', '-i', str(bumper),
              '-vf', f"scale={info['width']}:{info['height']}:flags=lanczos,fps=24,setsar=1,format=yuv420p",
              '-an', *video_encoder_args(18, 0), '-video_track_timescale', str(denominator), str(target)], timeout=1800)
        normalized.append(target)
    playlist = output.parent / 'sigla_concat.txt'
    def line(path):
        return "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'\n"
    playlist.write_text(''.join(line(path) for path in (normalized[0], source, normalized[1])), encoding='utf-8')
    _run([ffmpeg_bin(), '-hide_banner', '-v', 'error', '-y', '-f', 'concat', '-safe', '0',
          '-i', str(playlist), '-map', '0:v:0', '-an', '-c:v', 'copy',
          '-video_track_timescale', str(denominator), str(output)], timeout=1800)
    return True


def add_sigla_to_master(source: Path, output: Path, asset_dir: str | Path, languages: list[str],
                        cta_language: str = "en", progress: Callable[[str, float], None] | None = None,
                        film_title: str = '', film_year: str = '') -> dict:
    """Inserisce intro/outro animate e localizzate senza alterare il montaggio del film."""
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    from core.modules.sigma_creative_lab.video.postprocess import nvenc_available, video_encoder_args

    langs = list(dict.fromkeys(str(x).lower()[:2] for x in languages))
    if not langs or set(langs) - LANG_TAGS.keys():
        raise ValueError("lingue della sigla non supportate")
    if not str(film_title).strip():
        raise ValueError('Indica il titolo del film prima di aggiungere una sigla')
    assets = validate_sigla_assets(asset_dir, langs)
    if film_title:
        from .publication_identity import validate_template
        validate_template(asset_dir)
    source_info = probe(source)
    if not source_info["width"] or not source_info["height"]:
        raise ValueError("Il master deve contenere un video valido")
    cta_language = cta_language if cta_language in SIGLA_CTA else "en"
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".sigla_work_", dir=output.parent))
    try:
        ff = ffmpeg_bin()
        encoder = video_encoder_args(18, 0)
        logo_frame = work / "sigla_logo_frame.png"
        logo_time = min(5.8, max(0.0, assets['intro_duration'] - 0.2))
        _run([ff, "-hide_banner", "-v", "error", "-y", "-ss", f'{logo_time:.3f}', "-i", str(assets["intro"]),
              "-frames:v", "1", "-update", "1", str(logo_frame)], timeout=120)
        if not logo_frame.is_file():
            raise RuntimeError('Impossibile estrarre il marchio dal video di apertura')
        logo_mask, button = _sigla_overlays(source_info["width"], source_info["height"], work,
                                             cta_language, logo_frame)
        logo_diameter = int(min(source_info["width"] * 0.42, source_info["height"] * 0.55))
        enhanced = []
        for kind, source_bumper, overlay, start in (
                ("intro", assets["intro"], logo_mask, min(5.7, max(0.0, assets['intro_duration'] - 0.8))),
                ("outro", assets["outro"], button, max(0.0, assets["outro_duration"] - 9.0))):
            target = work / f"{kind}_enhanced.mp4"
            if progress:
                progress(f"Rifinitura sigla: {kind}", 0.12 if kind == "intro" else 0.30)
            vf = ("[0:v]scale={w}:{h}:flags=lanczos,fps=24,setsar=1,"
                  "drawbox=x={x}:y={y}:w={d}:h={d}:color=black:t=fill:enable='gte(t,{start:.3f})'[base];"
                  "[1:v]format=rgba,fade=t=in:st={start:.3f}:d=0.55:alpha=1[mark];"
                  "[base][mark]overlay=(W-w)/2:(H*0.05)+(H*0.55-h)/2:format=auto:"
                  "enable='gte(t,{start:.3f})',format=yuv420p[v]").format(
                      w=source_info["width"], h=source_info["height"], x=(source_info["width"]-logo_diameter)//2,
                      y=int(source_info["height"]*0.05), d=logo_diameter, start=start)
            if kind == "outro":
                vf = ("[0:v]scale={w}:{h}:flags=lanczos,fps=24,setsar=1,format=yuv420p[base];"
                      "[1:v]format=rgba,fade=t=in:st={start:.3f}:d=0.45:alpha=1[mark];"
                      "[base][mark]overlay=(W-w)/2:H-h-0.08*H:format=auto:"
                      "enable='gte(t,{start:.3f})'[v]").format(
                          w=source_info["width"], h=source_info["height"], start=start)
            args = [ff, "-hide_banner", "-v", "error", "-y", "-i", str(source_bumper), "-loop", "1", "-i", str(overlay),
                    "-filter_complex", vf, "-map", "[v]", "-an", "-t", f"{assets[kind + '_duration']:.6f}",
                    *encoder, str(target)]
            _run(args, timeout=1800)
            if film_title and kind == 'intro':
                from .publication_identity import title_overlay
                card = title_overlay(source_info['width'], source_info['height'], film_title, film_year,
                                     work / 'film_title.png')
                titled = work / 'intro_titled.mp4'
                _run([ff, '-v', 'error', '-y', '-i', str(target), '-loop', '1', '-i', str(card),
                      '-filter_complex', '[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]',
                      '-map', '[v]', '-an', '-t', str(assets['intro_duration']), *encoder, str(titled)], timeout=300)
                target = titled
            enhanced.append(target)

        joined_video = work / "joined_video.mp4"
        if progress:
            progress("Montaggio della sigla animata", 0.45)
        graph = ("[0:v]scale={w}:{h}:flags=lanczos,fps=24,setsar=1,setpts=PTS-STARTPTS[v0];"
                 "[1:v]scale={w}:{h}:flags=lanczos,fps=24,setsar=1,setpts=PTS-STARTPTS[v1];"
                 "[2:v]scale={w}:{h}:flags=lanczos,fps=24,setsar=1,setpts=PTS-STARTPTS[v2];"
                 "[v0][v1][v2]concat=n=3:v=1:a=0[v]").format(w=source_info["width"], h=source_info["height"])
        copied_video = _join_sigla_video(source, enhanced, joined_video, source_info)
        if not copied_video:
            _run([ff, "-hide_banner", "-v", "error", "-y", "-i", str(enhanced[0]), "-i", str(source), "-i", str(enhanced[1]),
                  "-filter_complex", graph, "-map", "[v]", *encoder, str(joined_video)], timeout=7200)

        stream_doc = _run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type",
                           "-of", "json", str(source)])
        import json
        types = [s.get("codec_type") for s in json.loads(stream_doc.stdout).get("streams", [])]
        if types.count("audio") < len(langs) or types.count("subtitle") < len(langs):
            raise ValueError("Il master non contiene tutte le tracce audio e i sottotitoli selezionati")

        cmd = [ff, "-hide_banner", "-v", "error", "-y", "-i", str(joined_video), "-i", str(source)]
        audio_inputs = {}
        next_input = 2
        for lang in langs:
            audio_inputs[lang] = (next_input, next_input + 1)
            cmd += ["-i", str(assets["voices"][lang][0]), "-i", str(assets["voices"][lang][1])]
            next_input += 2
        subtitle_input = next_input
        cmd += ["-itsoffset", f"{assets['intro_duration']:.6f}", "-i", str(source)]
        streams = json.loads(_run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries",
                                   "stream=codec_type:stream_tags=language", "-of", "json", str(source)]).stdout).get("streams", [])
        reverse_tags = {tag[0]: lang for lang, tag in LANG_TAGS.items()}
        source_audio = [reverse_tags.get(s.get("tags", {}).get("language", "")) for s in streams
                        if s.get("codec_type") == "audio"]
        source_subtitles = [reverse_tags.get(s.get("tags", {}).get("language", "")) for s in streams
                            if s.get("codec_type") == "subtitle"]
        audio_streams = {lang: (source_audio.index(lang) if lang in source_audio else index)
                         for index, lang in enumerate(langs)}
        subtitle_streams = {lang: (source_subtitles.index(lang) if lang in source_subtitles else index)
                            for index, lang in enumerate(langs)}
        filters, audio_labels = [], []
        for idx, lang in enumerate(langs):
            intro_input, outro_input = audio_inputs[lang]
            filters.extend((f"[{intro_input}:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={assets['intro_duration']:.6f},asetpts=PTS-STARTPTS[pre{idx}]",
                            f"[1:a:{audio_streams[lang]}]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={source_info['duration']:.6f},asetpts=PTS-STARTPTS[mid{idx}]",
                            f"[{outro_input}:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={assets['outro_duration']:.6f},asetpts=PTS-STARTPTS[post{idx}]",
                            f"[pre{idx}][mid{idx}][post{idx}]concat=n=3:v=0:a=1[a{idx}]"))
            audio_labels.append(f"[a{idx}]")
        cmd += ["-filter_complex", ";".join(filters), "-map", "0:v:0"]
        for label in audio_labels:
            cmd += ["-map", label]
        for idx in range(len(langs)):
            cmd += ["-map", f"{subtitle_input}:s:{subtitle_streams[langs[idx]]}"]
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-c:s", "copy", "-movflags", "+faststart",
                "-map_metadata", "1", "-t", f"{assets['intro_duration'] + source_info['duration'] + assets['outro_duration']:.6f}"]
        for idx, lang in enumerate(langs):
            code, name = LANG_TAGS[lang]
            cmd += [f"-metadata:s:a:{idx}", f"language={code}", f"-metadata:s:a:{idx}", f"title={name}"]
            cmd += [f"-metadata:s:s:{idx}", f"language={code}", f"-metadata:s:s:{idx}", f"title={name}"]
        temporary = output.with_name(f"{output.stem}.part{output.suffix}")
        cmd += [str(temporary)]
        if progress:
            progress("Esportazione con tracce vocali e sottotitoli sincronizzati", 0.72)
        _run(cmd, timeout=7200)
        final_info = probe(temporary)
        if abs(final_info["duration"] - (assets["intro_duration"] + source_info["duration"] + assets["outro_duration"])) > 0.5:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Durata del master con sigla non coerente")
        if film_title:
            from .publication_identity import verify_title_frame
            verify_title_frame(temporary, card, assets['intro_duration'] / 2, work / 'title_verified.png')
        temporary.replace(output)
        if film_title:
            from core.store import JsonStore
            preview = output.with_name(output.stem + '_intro.png')
            shutil.copy2(work / 'title_verified.png', preview)
            JsonStore(output.with_suffix('.identity.json')).save({'title': film_title, 'year': film_year,
                'intro_verified': True, 'preview': str(preview), 'size': output.stat().st_size})
        if progress:
            progress("Sigla completata e verificata", 1.0)
        return {"output_path": str(output), "duration": final_info["duration"], "intro_duration": assets["intro_duration"],
                "outro_duration": assets["outro_duration"], "languages": langs, "cta_language": cta_language,
                "film_video_copied": copied_video, 'identity_title': film_title, 'identity_year': film_year}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def export_multilingual(tl: dict, prod: dict, production_dir: Path, output: Path, languages: list[str],
                        progress: Callable[[str, float], None] | None = None) -> dict:
    """Esporta un video con una traccia audio e una traccia SRT per ogni lingua richiesta."""
    from core.modules.sigma_creative_lab.video.export import export_timeline
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, _slug
    from core.modules.sigma_creative_lab.video.timeline import layout
    from core.modules.sigma_creative_lab.video.postprocess import video_encoder_args

    langs = list(dict.fromkeys(str(x).lower()[:2] for x in languages))
    if not langs or set(langs) - LANG_TAGS.keys():
        raise ValueError("lingue di esportazione non supportate")
    audio_tracks = tl.get("audio") or []
    native_language = (prod.get('settings') or {}).get('source_language') if (prod.get('settings') or {}).get('restoration_content_type') == 'documentary' else None
    missing = [lang for lang in langs if lang != native_language and not any(t.get("kind") == "voice" and
               str(t.get("id", "")).startswith("restore_voice_") and str(t["id"]).endswith(f"_{lang}")
               and t.get("clips") for t in audio_tracks)]
    if missing:
        raise ValueError(f"mancano le narrazioni: {', '.join(missing)}")

    film_duration = float(layout(tl, prod)["duration"])
    audio_duration = max((float(c.get("start", 0.0)) + float(c["src_out"]) - float(c.get("src_in", 0.0))
                          for lang in langs for track in audio_tracks if track.get("kind") != "clip" and
                          _track_for_language(track, lang)
                          for c in track.get("clips") or []), default=film_duration)
    duration = max(film_duration, audio_duration)
    if duration - film_duration > 120:
        raise ValueError(f"la narrazione supera il film di {duration-film_duration:.1f} s; correggere o accorciare le battute")

    work = production_dir / "exports" / ".multilingual"
    work.mkdir(parents=True, exist_ok=True)
    base = work / "video_only.mp4"
    video_timeline = copy.deepcopy(tl)
    for track in video_timeline.get("audio") or []:
        track["mute"] = True
    if progress:
        progress("Preparazione del video", 0.02)
    preserve_audio = bool((prod.get("settings") or {}).get("preserve_source_audio", True))
    for track in video_timeline.get("audio") or []:
        if track.get("kind") == "clip":
            track["mute"] = not preserve_audio
    from core.modules.sigma_creative_lab.video.postprocess import nvenc_available
    codec = "h264_nvenc" if nvenc_available(0) else "libx264"
    export_timeline(video_timeline, prod, base, codec=codec,
                    quality=int((prod.get("settings") or {}).get("final_quality", 18)))
    from core.modules.sigma_creative_lab.video.production import probe
    source_audio = base if preserve_audio and probe(base)["has_audio"] else None
    if native_language in langs and source_audio is None:
        raise ValueError("La traccia originale del documentario non contiene audio utilizzabile")

    mix_paths = []
    for i, lang in enumerate(langs):
        mix = work / f"audio_{lang}.m4a"
        if progress:
            progress(f"Mix audio {lang.upper()}", 0.08 + 0.72 * i / len(langs))
        _audio_mix(audio_tracks, lang, mix, duration,
                   source_audio if not native_language or lang == native_language else None,
                   source_is_dialogue=bool(native_language and lang == native_language))
        mix_paths.append(mix)

    subtitles = []
    for lang in langs:
        sub = production_dir / "subtitles" / f"{_slug(prod.get('title') or prod['id'])}_{lang}.srt"
        if sub.is_file():
            subtitles.append((lang, sub))
    missing_subtitles = sorted(set(langs) - {lang for lang, _ in subtitles})
    if missing_subtitles:
        raise ValueError(f"mancano i sottotitoli: {', '.join(missing_subtitles)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f"{output.stem}.part{output.suffix}")
    cmd = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", "-i", str(base)]
    for mix in mix_paths:
        cmd += ["-i", str(mix)]
    for _lang, sub in subtitles:
        cmd += ["-i", str(sub)]
    cmd += ["-map", "0:v:0"]
    for i in range(len(mix_paths)):
        cmd += ["-map", f"{1+i}:a:0"]
    for i in range(len(subtitles)):
        cmd += ["-map", f"{1+len(mix_paths)+i}:s:0"]
    cmd += ["-c:a", "copy", "-c:s", "mov_text", "-metadata", f"title={prod.get('title') or prod['id']} · Restauro multilingua",
            "-movflags", "+faststart"]
    if duration > film_duration + 0.02:
        pad = duration - film_duration
        cmd += ["-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f}", "-r", "24",
                *video_encoder_args(int((prod.get("settings") or {}).get("final_quality", 18)), 0)]
    else:
        cmd += ["-c:v", "copy"]
    for i, lang in enumerate(langs):
        code, name = LANG_TAGS[lang]
        cmd += [f"-metadata:s:a:{i}", f"language={code}", f"-metadata:s:a:{i}", f"title={name}",
                f"-disposition:a:{i}", "default" if i == 0 else "0"]
    for i, (lang, _sub) in enumerate(subtitles):
        code, name = LANG_TAGS[lang]
        cmd += [f"-metadata:s:s:{i}", f"language={code}", f"-metadata:s:s:{i}", f"title={name}",
                f"-disposition:s:{i}", "0"]
    cmd += ["-t", f"{duration:.6f}", str(temporary_output)]
    if progress:
        progress("Mux finale e sottotitoli", 0.83)
    _run(cmd, timeout=7200)
    if progress:
        progress("Verifica tracce audio", 0.97)
    from core.modules.sigma_creative_lab.video.production import probe
    info = probe(temporary_output)
    ffprobe = ffmpeg_bin("ffprobe")
    streams = _run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(temporary_output)])
    import json
    stream_types = [x.get("codec_type") for x in json.loads(streams.stdout).get("streams", [])]
    if (not info["width"] or not info["height"] or abs(float(info["duration"]) - duration) > 0.25 or
            stream_types.count("audio") != len(langs) or stream_types.count("subtitle") != len(subtitles)):
        temporary_output.unlink(missing_ok=True)
        raise RuntimeError("verifica del master multilingua non riuscita")
    temporary_output.replace(output)
    shutil.rmtree(work, ignore_errors=True)
    return {"output_path": str(output), "duration": duration, "languages": langs,
            "subtitles": [lang for lang, _ in subtitles], "video": [info["width"], info["height"]]}
