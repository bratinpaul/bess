"""Control and monitor the realtime batch (realtime_batch.py): what's waiting in the inbox, whether a run is going,
the Windows schedule, running it on demand, and reading its load reports in battery_raw.batchlog.

Used by the backend API (/api/batch/realtime - the frontend's Batch -> Realtime Load page). The batchlog
functions take a SQLAlchemy session; everything else works on the file system and the scheduler.
"""
import csv
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import realtime_batch  # noqa: E402 - one definition of the inbox, file names, lock and task

SCRIPT = HERE / "realtime_batch.py"
INBOX = realtime_batch.DEFAULT_INBOX
ARCHIVE = INBOX / realtime_batch.ARCHIVE_DIR
LOCK = INBOX / realtime_batch.LOCK_NAME
TASK_NAME = realtime_batch.TASK_NAME
RUN_TIMEOUT_S = 600
STATUSES = ("SUCCESS", "PARTIAL", "FAILED")
JOB_NAME = "realtime_snapshot"  # battery_raw.batchlog also holds other jobs' runs (e.g. static_data_load)
# what a run prints when a scheduled run already holds the lock
BUSY_MESSAGE = "another run is still going"


class BatchError(Exception):
    """The batch couldn't be started or didn't finish."""


# ---------------------------------------------------------------- inbox, lock, schedule


def inbox_files(inbox: Path = INBOX) -> list[dict]:
    """Files in the inbox: name, size, modified time, whether the batch takes them and whether they're ready."""
    if not inbox.is_dir():
        return []
    now = time.time()
    files = []
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.name.startswith("."):  # the lock and the simulator's temporary files
            continue
        stat = path.stat()
        files.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone(),
            "valid_name": bool(realtime_batch.FILE_PATTERN.match(path.name)),
            "ready": now - stat.st_mtime >= realtime_batch.MIN_FILE_AGE_S,
        })
    return files


def lock_state() -> tuple[bool, Optional[str]]:
    """(a run is going, since when - the lock file's text)."""
    if not LOCK.exists():
        return False, None
    try:
        return True, LOCK.read_text(encoding="utf-8").strip()
    except OSError:
        return True, "unknown"


def schedule_info() -> dict:
    """The Windows scheduled task's state (schtasks), or installed=False."""
    info: dict[str, Any] = {"task_name": TASK_NAME, "installed": False}
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "CSV", "/V"],
            capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return info
    rows = list(csv.DictReader(io.StringIO(result.stdout))) if result.returncode == 0 else []
    if not rows:
        return info
    row = rows[0]
    last_result = row.get("Last Result")
    return {
        "task_name": TASK_NAME,
        "installed": True,
        "status": row.get("Status") or row.get("Scheduled Task State"),
        "next_run": row.get("Next Run Time"),
        "last_run": row.get("Last Run Time"),
        "last_result": {"0": "OK", "267011": "not run yet", "267009": "running"}.get(last_result or "", last_result),
        "repeat_every": row.get("Repeat: Every"),
    }


# ---------------------------------------------------------------- run on demand


def run_now(timeout_s: int = RUN_TIMEOUT_S) -> dict:
    """Run the batch once (exactly what the scheduler runs) and wait for it.

    Returns started_at, finished_at, exit_code, busy (a scheduled run held the lock, so nothing was done) and
    output (the log lines). Runs as a separate process: it calls the backend's bulk-load APIs while it runs.
    """
    if not SCRIPT.exists():
        raise BatchError(f"Batch script not found: {SCRIPT}")
    started = datetime.now().astimezone()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=str(HERE), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise BatchError(f"The batch didn't finish within {timeout_s // 60} minutes")
    output = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    return {
        "started_at": started,
        "finished_at": datetime.now().astimezone(),
        "exit_code": result.returncode,
        "busy": any(BUSY_MESSAGE in line for line in output),
        "output": output,
    }


# ---------------------------------------------------------------- battery_raw.batchlog

_LIST_COLUMNS = """batch_id, run_id::text AS run_id, file_name, file_time, snapshot_time, status, started_at, finished_at,
    duration_ms, feeds_total, feeds_loaded, feeds_failed, rows_total, rows_inserted, rows_updated, rows_skipped,
    feed_results, warnings, id_changes, error_message, archive_path"""


def _dicts(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), {"job": JOB_NAME, **params})]


def last_log(db: Session) -> Optional[dict]:
    rows = _dicts(db, f"SELECT {_LIST_COLUMNS} FROM battery_raw.batchlog WHERE job_name = :job "
                      "ORDER BY batch_id DESC LIMIT 1")
    return rows[0] if rows else None


def logs_since(db: Session, since: datetime) -> list[dict]:
    """Rows written by runs that started at or after `since` (e.g. the run just triggered)."""
    return _dicts(db, f"SELECT {_LIST_COLUMNS} FROM battery_raw.batchlog WHERE job_name = :job AND started_at >= :since "
                      "ORDER BY batch_id",
                  since=since - timedelta(seconds=1))


def list_logs(db: Session, status: Optional[str] = None, q: Optional[str] = None, limit: int = 25,
              offset: int = 0) -> tuple[list[dict], int, dict[str, int]]:
    """(rows newest first, total matching, count per status over all rows)."""
    where, params = ["job_name = :job"], {"limit": limit, "offset": offset}
    if status:
        where.append("status = :status")
        params["status"] = status
    if q and q.strip():
        where.append("file_name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    clause = f"WHERE {' AND '.join(where)}"
    items = _dicts(db, f"SELECT {_LIST_COLUMNS} FROM battery_raw.batchlog {clause} "
                       "ORDER BY batch_id DESC LIMIT :limit OFFSET :offset", **params)
    total = db.execute(text(f"SELECT count(*) FROM battery_raw.batchlog {clause}"), {"job": JOB_NAME, **params}).scalar_one()
    counts = {r["status"]: r["n"] for r in _dicts(db, "SELECT status, count(*) AS n FROM battery_raw.batchlog WHERE job_name = :job GROUP BY status")}
    return items, total, {s: counts.get(s, 0) for s in STATUSES}


def get_log(db: Session, batch_id: int) -> Optional[dict]:
    """One row with the full load report."""
    rows = _dicts(db, f"SELECT {_LIST_COLUMNS}, api_url, host_name, report FROM battery_raw.batchlog "
                      "WHERE batch_id = :id AND job_name = :job", id=batch_id)
    return rows[0] if rows else None
