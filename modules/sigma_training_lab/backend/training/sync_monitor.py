import time
import json
import re
from pathlib import Path

task_log = Path(r"C:\Users\Sigma\.gemini\antigravity-ide\brain\360c983f-7eb9-4fd3-92bd-b9eadf98a19f\.system_generated\tasks\task-2548.log")
job_id = "c119a075"
train_log = Path(rf"C:\Users\Sigma\Desktop\Sigma_Studio\store\training\jobs\{job_id}\train.log")
jobs_json_path = Path(r"C:\Users\Sigma\Desktop\Sigma_Studio\store\training\training_jobs.json")

_LOSS_RE = re.compile(r"loss[:\s=]+([0-9]*\.?[0-9]+)", re.IGNORECASE)
_EPOCH_RE = re.compile(r"[Ee]poch\s+(\d+)\s*/\s*(\d+)")
_STEP_RE = re.compile(r"step\s+(\d+)\s*/\s*(\d+)")
_PCT_RE = re.compile(r"\((\d+(?:\.\d+)?)%\)")

state = {
    "progress_pct": 0, "current_epoch": 0, "total_epochs": 3,
    "current_step": 0, "total_steps": 0, "last_loss": None
}

def parse_line(line: str) -> bool:
    changed = False
    m = _LOSS_RE.search(line)
    if m:
        try:
            state["last_loss"] = float(m.group(1))
            changed = True
        except ValueError:
            pass
    m = _EPOCH_RE.search(line)
    if m:
        state["current_epoch"], state["total_epochs"] = int(m.group(1)), int(m.group(2))
        changed = True
    m = _STEP_RE.search(line)
    if m:
        state["current_step"], state["total_steps"] = int(m.group(1)), int(m.group(2))
        if state["total_steps"]:
            state["progress_pct"] = round(100.0 * state["current_step"] / state["total_steps"], 1)
        changed = True
    m = _PCT_RE.search(line)
    if m:
        try:
            state["progress_pct"] = float(m.group(1))
            changed = True
        except ValueError:
            pass
    return changed

def update_job_meta():
    try:
        if jobs_json_path.exists():
            with open(jobs_json_path, "r", encoding="utf-8") as f:
                jobs = json.load(f)
            if job_id in jobs:
                jobs[job_id].update(state)
                jobs[job_id]["status"] = "running"
                with open(jobs_json_path, "w", encoding="utf-8") as f:
                    json.dump(jobs, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

offset = 0
while True:
    if task_log.exists():
        try:
            with open(task_log, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                chunk = fh.read()
                offset = fh.tell()
            if chunk:
                with open(train_log, "a", encoding="utf-8", errors="replace") as out:
                    out.write(chunk)
                    out.flush()
                dirty = False
                for line in chunk.splitlines():
                    dirty |= parse_line(line)
                if dirty:
                    update_job_meta()
        except Exception:
            pass
    time.sleep(1.0)
