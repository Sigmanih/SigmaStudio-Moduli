"""Adapter video del worker nativo, per il VideoGenerator (un clip alla volta).

Le produzioni lunghe non passano da qui: usano direttamente il backend e i
file su disco. Questo adapter serve la generazione singola del Creative Lab,
che lavora a byte.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from core.modules.sigma_creative_lab.backends.sigma_native_backend import SigmaNativeBackend

_JOB_KEYS = ("width", "height", "fps", "seed", "steps", "sample_method", "scheduler", "cfg_scale",
             "flow_shift", "cache_mode", "cache_option", "negative_prompt", "video_codec")


class NativeVideoAdapter:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.backend = SigmaNativeBackend(config=self.config)

    def _job(self, prompt: str, params: dict, out: Path) -> dict:
        job = {k: params[k] for k in _JOB_KEYS if params.get(k) not in (None, "")}
        if params.get("num_frames") or params.get("video_frames"):
            job["video_frames"] = int(params.get("video_frames") or params.get("num_frames"))
        elif params.get("duration"):
            from core.modules.sigma_creative_lab.video.production import h3_frames
            job["video_frames"] = h3_frames(float(params["duration"]))
        job.update({"prompt": prompt, "output_path": str(out)})
        return job

    async def _run(self, job: dict, params: dict) -> tuple[bytes, str]:
        out = Path(job["output_path"])
        try:
            await self.backend.run_job({"profile": params.get("profile") or self.config.get("profile") or "minimax-h3-q4",
                                        "placement": params.get("placement", ""), "job": job})
            return out.read_bytes(), "mp4"
        finally:
            for f in (out, out.with_suffix(".last.png")):
                f.unlink(missing_ok=True)

    async def text_to_video(self, prompt: str, params: dict) -> tuple[bytes, str]:
        out = Path(tempfile.gettempdir()) / f"sigma_native_{uuid.uuid4().hex}.mp4"
        return await self._run(self._job(prompt, params, out), params)

    async def image_to_video(self, image_bytes: bytes, prompt: str, params: dict) -> tuple[bytes, str]:
        tmp = Path(tempfile.gettempdir())
        first = tmp / f"sigma_native_{uuid.uuid4().hex}.png"
        first.write_bytes(image_bytes)
        out = tmp / f"sigma_native_{uuid.uuid4().hex}.mp4"
        try:
            job = self._job(prompt, params, out)
            job["init_image"] = str(first)
            if params.get("end_image_path"):
                job["end_image"] = str(params["end_image_path"])
            return await self._run(job, params)
        finally:
            first.unlink(missing_ok=True)
