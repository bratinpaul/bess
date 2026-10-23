"""Backend side of the historical generator (/api/batch/history-generator - the frontend's Batch -> Historical
Generator page): the sites that can be generated, a preview (mapping + proposed scenario calendar) per site, starting
a generation of several sites in the background (generate_queue.py, its own process) and following its progress by
hand, and the batch log (job 'historical_generate').
"""
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import generator as G  # noqa: E402
import generate_queue as Q  # noqa: E402
from bess_common.errors import BusinessRuleViolation, InternalError  # noqa: E402

SCRIPT = HERE / "generate_queue.py"
LOGS = HERE / "logs"
PROGRESS = LOGS / "last_run.json"
JOBS = LOGS / "jobs.json"
STATUSES = ("SUCCESS", "PARTIAL", "FAILED")
DEFAULT_FROM, DEFAULT_TO = date(2026, 8, 1), date(2026, 9, 30)


class GeneratorControlError(BusinessRuleViolation):
    status = 400
    code = "GENERATOR_REJECTED"


def options() -> dict:
    """Battery systems with what they have in master data, whether their folder exists, and the climate profiles."""
    try:
        systems = G.eligible()
    except Exception as exc:  # noqa: BLE001 - one generic 500 for the page; the cause is chained for the log
        raise InternalError(log_message="history generator could not read the master data") from exc
    for s in systems:
        folder = G.HISTORICAL / s["folder"]
        s["folder_relative"] = str(folder.relative_to(G.PROJECT / "input"))
        s["existing_files"] = sum(1 for f in folder.rglob("*") if f.is_file()) if folder.exists() else 0
        report = folder / "generation_report.json"
        s["last_generated"] = None
        if report.exists():
            try:
                r = json.loads(report.read_text(encoding="utf-8"))
                s["last_generated"] = {"at": r.get("generated_at"), "date_from": r.get("date_from"),
                                       "date_to": r.get("date_to")}
            except ValueError:
                pass
    missing = [f for f in G.SAMPLE_FILES if not (G.SAMPLES / f).exists()]
    return {"samples_folder": str(G.SAMPLES), "sample_files": list(G.SAMPLE_FILES), "missing_samples": missing,
            "max_days": G.MAX_DAYS, "default_from": DEFAULT_FROM.isoformat(), "default_to": DEFAULT_TO.isoformat(),
            "systems": systems}


def preview(battery_system_id: int, start: date, end: date, overrides: Optional[dict]) -> dict:
    try:
        return G.preview(battery_system_id, start, end, overrides)
    except G.GenerationError as exc:
        raise GeneratorControlError(str(exc))


def running() -> tuple[bool, Optional[str]]:
    if not Q.LOCK.exists() or time.time() - Q.LOCK.stat().st_mtime > Q.STALE_LOCK_S:
        return False, None
    return True, datetime.fromtimestamp(Q.LOCK.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def start(date_from: date, date_to: date, module_from: Optional[date], sites: list[dict]) -> dict:
    """Check every site's mapping and calendar, then start the generation as its own process (sites one after
    another). The page shows its progress when the user refreshes (status())."""
    if not sites:
        raise GeneratorControlError("Select at least one site")
    if len({s["battery_system_id"] for s in sites}) != len(sites):
        raise GeneratorControlError("A battery system is selected twice")
    if running()[0]:
        raise GeneratorControlError("A generation is already running", status=409, code="GENERATION_RUNNING")
    missing = [f for f in G.SAMPLE_FILES if not (G.SAMPLES / f).exists()]
    if missing:
        raise GeneratorControlError(f"Sample file(s) missing in {G.SAMPLES}: {', '.join(missing)}")
    jobs = []
    for s in sites:
        try:
            G.check_range(date_from, date_to, module_from)
            profile, _ = G.apply_overrides(G.load_profile(s["battery_system_id"]), s.get("overrides"))
            if s.get("calendar") is not None:
                G.calendar_from_dict(s["calendar"], date_from, date_to)
        except G.GenerationError as exc:
            raise GeneratorControlError(f"{s.get('site_name') or s['battery_system_id']}: {exc}")
        jobs.append({"battery_system_id": s["battery_system_id"], "site_name": profile.site_name,
                     "system_name": profile.system_name,
                     "folder_relative": str(G.output_dir(profile).relative_to(G.PROJECT / "input")),
                     "overrides": s.get("overrides") or {}, "calendar": s.get("calendar")})
    LOGS.mkdir(exist_ok=True)
    PROGRESS.unlink(missing_ok=True)
    payload = {"run_id": str(uuid.uuid4()), "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
               "module_from": module_from.isoformat() if module_from else None, "sites": jobs}
    JOBS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log = open(LOGS / "generate.log", "a", encoding="utf-8")
    log.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {', '.join(j['site_name'] for j in jobs)} "
              f"{date_from} .. {date_to}\n")
    log.flush()
    subprocess.Popen([sys.executable, str(SCRIPT), "--jobs", str(JOBS), "--progress", str(PROGRESS)], cwd=str(HERE),
                     stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(50):  # wait until the run has written its first progress
        if PROGRESS.exists():
            break
        time.sleep(0.1)
    return status()


def status() -> dict:
    is_running, since = running()
    progress = None
    for _ in range(5):  # the run may be replacing the file right now
        try:
            progress = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else None
            break
        except (OSError, ValueError):
            time.sleep(0.05)
    if progress and progress.get("status") == "RUNNING" and not is_running:
        # the process is gone without finishing (stopped or crashed): show it as interrupted
        progress["status"] = "FAILED"
        progress["error"] = progress.get("error") or "The generation was interrupted before it finished (process stopped)"
        for s in progress.get("sites", []):
            if s.get("status") in ("PENDING", "GENERATING"):
                s["status"] = "FAILED"
                s["error"] = "not generated: the run was interrupted"
    return {"running": is_running, "running_since": since, "progress": progress}


# ---------------------------------------------------------------- batch log

_COLUMNS = """batch_id, run_id::text AS run_id, file_name, file_time, snapshot_time, status, started_at, finished_at,
    duration_ms, feeds_total, feeds_loaded, feeds_failed, rows_total, rows_inserted, rows_updated, rows_skipped,
    feed_results, warnings, id_changes, error_message, error_code, request_id, archive_path"""


def list_logs(db: Session, status: Optional[str] = None, limit: int = 25,
              offset: int = 0) -> tuple[list[dict], int, dict[str, int]]:
    where = ["job_name = :job"]
    params: dict[str, Any] = {"job": Q.JOB_NAME, "limit": limit, "offset": offset}
    if status:
        where.append("status = :status")
        params["status"] = status
    clause = "WHERE " + " AND ".join(where)
    items = [dict(r._mapping) for r in db.execute(text(
        f"SELECT {_COLUMNS} FROM battery_raw.batchlog {clause} ORDER BY batch_id DESC LIMIT :limit OFFSET :offset"),
        params)]
    total = db.execute(text(f"SELECT count(*) FROM battery_raw.batchlog {clause}"), params).scalar_one()
    counts = {r[0]: r[1] for r in db.execute(text(
        "SELECT status, count(*) FROM battery_raw.batchlog WHERE job_name = :job GROUP BY status"), {"job": Q.JOB_NAME})}
    return items, total, {s: counts.get(s, 0) for s in STATUSES}
