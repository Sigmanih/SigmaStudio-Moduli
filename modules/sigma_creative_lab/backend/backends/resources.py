"""Arbitra l'acceleratore fra editor e produzioni, prima di caricare modelli."""
from contextlib import nullcontext

from core.resource_pool import resource_pool

ACCELERATOR = "creative:accelerator"


def reserve_accelerator(owner: str):
    return resource_pool.reserve((ACCELERATOR,), owner)


def accelerator_busy() -> bool:
    return resource_pool.occupied(ACCELERATOR)


def reserve_job(job: dict, cpu_kinds: set[str]):
    return nullcontext() if job["kind"] in cpu_kinds else reserve_accelerator(job["id"])
