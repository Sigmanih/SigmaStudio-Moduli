"""Backend nativo: worker Rust `sigma-diffusion` su stable-diffusion.cpp.

Rispetta lo stesso contratto di ComfyUIBackend, cosi' il router e la pipeline
dei video lunghi possono usare l'uno o l'altro senza saperlo. Il payload di
`submit` e' `{"profile", "placement", "job"}`: il profilo viene caricato (una
volta sola) prima di accodare il job.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.logger import get_logger
from core.modules.sigma_creative_lab.backends.base import BackendJob, BackendUnavailable, GenerationBackend
from core.modules.sigma_creative_lab.native.runtime import PROFILES, get_runtime

log = get_logger("sigma_native_backend")

_STATUS = {"queued": "pending", "running": "running", "completed": "done", "failed": "error", "cancelled": "cancelled"}


def job_progress(job: dict) -> float:
    """Percentuale complessiva: il campionamento domina, codifica e decodifica pesano poco."""
    status = job.get("status")
    if status == "completed":
        return 100.0
    steps = job.get("steps") or 0
    if status != "running" or steps <= 0:
        return 0.0
    return round(min(95.0, 95.0 * (job.get("step") or 0) / steps), 1)


class SigmaNativeBackend(GenerationBackend):
    id = "sigma_native"
    label = "SigmaDiffusion nativo"

    def __init__(self, base_url: str = "", config: dict | None = None):
        self.config = config or {}
        self.runtime = get_runtime(self.config)
        self.timeout_s = int(self.config.get("timeout", 7200))

    async def _call(self, fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except ConnectionError as e:
            raise BackendUnavailable(f"worker nativo non raggiungibile: {e}") from e

    # --- stato ----------------------------------------------------------

    async def is_available(self) -> bool:
        ok, _ = self.runtime.availability()
        return ok

    async def get_system_stats(self) -> dict:
        ok, why = self.runtime.availability()
        stats = {"backend": self.id, "installed": ok, "detail": why, "running": self.runtime.is_alive()}
        if stats["running"]:
            info = await self._call(self.runtime.get, "/v1/info")
            stats.update({"version": info.get("commit", ""), "devices": info.get("devices", []),
                          "loaded": await self._call(self.runtime.loaded)})
        return stats

    async def discover_models(self) -> dict:
        from core.modules.sigma_creative_lab.native.runtime import resolve_profile
        out = {}
        for pid, profile in PROFILES.items():
            _spec, missing = resolve_profile(pid)
            out[pid] = {"label": profile.label, "capabilities": list(profile.capabilities),
                        "installed": not missing, "missing": missing}
        return {"profiles": out}

    # --- esecuzione -----------------------------------------------------

    async def get_queue(self) -> dict:
        jobs = (await self._call(self.runtime.get, "/v1/jobs")).get("jobs", [])
        running = [j["id"] for j in jobs if j.get("status") == "running"]
        pending = [j["id"] for j in jobs if j.get("status") == "queued"]
        return {"running": running, "pending": pending, "running_count": len(running), "pending_count": len(pending)}

    async def ensure_profile(self, profile: str, placement: str = "", overrides: dict | None = None) -> dict:
        await self._call(self.runtime.ensure_started)
        return await self._call(self.runtime.load_profile, profile, placement, overrides)

    async def submit(self, payload: dict) -> str:
        profile = payload.get("profile") or self.config.get("profile") or "minimax-h3-q4"
        await self.ensure_profile(profile, payload.get("placement", ""), payload.get("load_overrides"))
        defaults = PROFILES[profile].defaults if profile in PROFILES else {}
        job = {**defaults, **(payload.get("job") or {})}
        data = await self._call(self.runtime.post, "/v1/jobs", job)
        return data["id"]

    async def get_job_status(self, job_id: str) -> BackendJob:
        job = await self._call(self.runtime.get, f"/v1/jobs/{job_id}")
        status = _STATUS.get(job.get("status", ""), "running")
        outputs = []
        result = job.get("result") or {}
        if result.get("output_path"):
            outputs.append({"filename": Path(result["output_path"]).name, "path": result["output_path"],
                            "kind": "output", "subfolder": ""})
        step = f"step {job.get('step', 0)}/{job.get('steps', 0)}" if status == "running" else ""
        return BackendJob(job_id, status, job_progress(job), node=step, error=job.get("error") or "", outputs=outputs)

    async def cancel_job(self, job_id: str) -> bool:
        try:
            await self._call(self.runtime.post, f"/v1/jobs/{job_id}/cancel", {})
            return True
        except Exception as e:
            log.warning(f"annullamento {job_id} fallito: {e}")
            return False

    async def get_history(self, job_id: str) -> dict:
        return await self._call(self.runtime.get, f"/v1/jobs/{job_id}")

    async def get_outputs(self, job_id: str) -> list[tuple[bytes, str]]:
        job = await self.get_history(job_id)
        path = (job.get("result") or {}).get("output_path")
        if not path or not Path(path).is_file():
            return []
        return [(Path(path).read_bytes(), Path(path).name)]

    async def run_job(self, payload: dict, progress_cb=None, timeout_s: int | None = None) -> dict:
        """Esegue e ritorna il record completo del worker (percorsi, tempi, seed).

        La pipeline dei video lunghi lavora con i file su disco: farsi restituire
        i byte di ogni clip (`run`) significherebbe ricopiare gigabyte in RAM.
        """
        timeout_s = timeout_s or self.timeout_s
        job_id = await self.submit(payload)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        last = None
        while loop.time() < deadline:
            job = await self.get_history(job_id)
            if progress_cb:
                snapshot = (job.get("status"), job.get("step"))
                if snapshot != last:
                    progress_cb({"job_id": job_id, "status": job.get("status"), "progress": job_progress(job),
                                 "step": job.get("step"), "steps": job.get("steps")})
                    last = snapshot
            if job.get("status") == "completed":
                return job
            if job.get("status") in ("failed", "cancelled"):
                raise RuntimeError(f"worker nativo: {job.get('error') or job.get('status')}")
            await asyncio.sleep(1.0)
        await self.cancel_job(job_id)
        raise TimeoutError(f"{self.label}: timeout dopo {timeout_s}s")
