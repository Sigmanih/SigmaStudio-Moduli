"""Ricompone un film muto gia' esportato senza ricodificarne il video."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_repair_score")


async def repair_score(project: Path, source: Path, output: Path, moods: list[dict], backend,
                       style: str = "", seed: int = 1922) -> dict:
    from core.modules.sigma_creative_lab.video.audio_export import _audio_mix, LANG_TAGS
    from core.modules.sigma_creative_lab.video.production import _run, ffmpeg_bin, probe
    from core.modules.sigma_creative_lab.video.restoration import compose

    if output.exists() or output.resolve() == source.resolve():
        raise ValueError("Scegliere un nuovo file di uscita: il master esistente viene conservato")
    timeline_path = project / "timeline.json"
    original = timeline_path.read_bytes()
    tl = json.loads(original)
    doc = json.loads(_run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(source)]).stdout)
    streams = doc["streams"]
    reverse = {v[0]: k for k, v in LANG_TAGS.items()}
    langs = [reverse.get(s.get("tags", {}).get("language")) for s in streams if s["codec_type"] == "audio"]
    if not langs or any(lang is None for lang in langs) or len(set(langs)) != len(langs):
        raise ValueError("Le tracce del master devono avere lingue supportate e distinte")
    duration = probe(source)["duration"]
    if not moods or abs(float(moods[0]["start"])) > 0.02 or abs(float(moods[-1]["end"]) - duration) > 1:
        raise ValueError("Il piano musicale deve coprire l'intero film")
    tracks = copy.deepcopy(tl.get("audio") or [])
    for lang in langs:
        if not any(t.get("clips") and t.get("kind") == "voice" and
                   str(t.get("id", "")).startswith("restore_voice_") and
                   str(t["id"]).endswith(f"_{lang}") for t in tracks):
            raise ValueError(f"Narrazione mancante per {lang}")
    work = output.parent / f"{output.stem}_audio"
    work.mkdir(parents=True, exist_ok=True)
    (work / "score_plan.json").write_text(json.dumps(moods, ensure_ascii=False, indent=2), encoding="utf-8")

    def progress(message, fraction):
        log.info("%s (%.1f%%)", message, 100 * fraction)

    cues = await compose(moods, work / "cues", 0, style, seed=seed, backend=backend, progress=progress)
    music = {"id": "repaired_score", "kind": "music", "gain_db": -5.0, "clips": [
        {"src": c["path"], "start": c["start"], "src_in": 0.0, "src_out": c["seconds"],
         "fade_in": c["fade_in"], "fade_out": c["fade_out"],
         "meta": {"restoration_score": "repaired", "quality": c["quality"], "arrangement": c["arrangement"]}}
        for c in cues]}
    # Il tappeto si decodifica e miscela una volta sola per tutte le lingue;
    # FLAC evita una generazione AAC intermedia prima del mix con le voci.
    bed = work / "orchestral_score.flac"
    log.info("Montaggio della colonna sonora orchestrale")
    await asyncio.to_thread(_audio_mix, [music], langs[0], bed, duration)
    for track in tracks:
        if track.get("kind") == "music":
            track["clips"] = [c for c in track.get("clips") or []
                              if not (c.get("meta") or {}).get("restoration_score")]
    tracks.append({"id": "repaired_score", "kind": "music", "clips": [
        {"src": str(bed), "start": 0, "src_in": 0, "src_out": duration, "fade_in": 0.02, "fade_out": 0.02}]})
    mixes = []
    for lang in langs:
        log.info("Mix della narrazione %s", lang.upper())
        mix = work / f"audio_{lang}.m4a"
        await asyncio.to_thread(_audio_mix, tracks, lang, mix, duration)
        mixes.append(mix)
    if timeline_path.read_bytes() != original:
        raise RuntimeError("La timeline e' cambiata durante la composizione: verificare prima di esportare")
    temporary = output.with_name(f"{output.stem}.part{output.suffix}")
    cmd = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", "-i", str(source)]
    for mix in mixes:
        cmd += ["-i", str(mix)]
    cmd += ["-map", "0:v:0"]
    for k in range(len(mixes)):
        cmd += ["-map", f"{k + 1}:a:0"]
    cmd += ["-map", "0:s?", "-map_metadata", "0", "-map_chapters", "0", "-c", "copy", "-movflags", "+faststart"]
    for k, lang in enumerate(langs):
        code, name = LANG_TAGS[lang]
        cmd += [f"-metadata:s:a:{k}", f"language={code}", f"-metadata:s:a:{k}", f"title={name}",
                f"-disposition:a:{k}", "default" if k == 0 else "0"]
    cmd += [str(temporary)]
    log.info("Nuovo master: copia video e sottotitoli, sostituzione delle tracce audio")
    await asyncio.to_thread(_run, cmd, 7200)
    verified = json.loads(_run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(temporary)]).stdout)
    audios = [s for s in verified["streams"] if s["codec_type"] == "audio"]
    if len(audios) != len(langs) or any(abs(float(s["duration"]) - duration) > 0.3 for s in audios):
        raise RuntimeError("Durata o numero delle nuove tracce audio non coerenti")
    for kind in ("video", "subtitle"):
        if sum(s["codec_type"] == kind for s in verified["streams"]) != sum(s["codec_type"] == kind for s in streams):
            raise RuntimeError(f"Tracce {kind} non conservate")
    if output.exists():
        raise RuntimeError("Il file di uscita esiste gia': conservato senza sovrascriverlo")
    temporary.replace(output)
    log.info("Master corretto e verificato: %s", output)
    return {"output_path": str(output), "languages": langs, "cues": len(cues), "duration": duration}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8288")
    parser.add_argument("--ffmpeg-dir", type=Path)
    parser.add_argument("--style", default="")
    parser.add_argument("--seed", type=int, default=1922)
    args = parser.parse_args()
    from core.modules.sigma_creative_lab.backends.comfyui_backend import ComfyUIBackend
    from core.modules.sigma_creative_lab.video import production

    if args.ffmpeg_dir:
        import os
        production.ffmpeg_bin = lambda tool="ffmpeg": str(args.ffmpeg_dir / (tool + (".exe" if os.name == "nt" else "")))

    class AvailableBackend(ComfyUIBackend):
        async def run(self, *a, **kw):
            queue = await self.get_queue()
            if queue["running_count"] or queue["pending_count"]:
                raise RuntimeError("ComfyUI e' occupato: riprendere la composizione quando e' libero")
            return await super().run(*a, **kw)

    try:
        moods = json.loads(args.plan.read_text(encoding="utf-8"))
        asyncio.run(repair_score(args.project, args.source, args.output, moods,
                                AvailableBackend(args.backend_url), args.style, args.seed))
        return 0
    except Exception:
        log.exception("Correzione musicale interrotta; il master precedente e' conservato")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
