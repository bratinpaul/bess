"""Control and monitor the static data batch (static_batch.py): the JSON files waiting in the inbox, whether a
run is going, running it on demand, and reading its load reports in battery_raw.batchlog (job 'static_data_load').

Used by the backend API (/api/batch/static - the frontend's Batch -> Static Data Load page).
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from bess_common import observability as obs
from bess_common.errors import DependencyTimeout, InternalError

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import static_batch  # noqa: E402

SCRIPT = HERE / "static_batch.py"
INBOX = static_batch.DEFAULT_INBOX
ARCHIVE = INBOX / static_batch.ARCHIVE_DIR
LOCK = INBOX / static_batch.LOCK_NAME
JOB_NAME = static_batch.JOB_NAME
RUN_TIMEOUT_S = 900
STATUSES = ("SUCCESS", "PARTIAL", "FAILED")
BUSY_MESSAGE = "another run is still going"


class StaticBatchError(InternalError):
    """The batch couldn't be started (generic 500 for the page; the cause is in log_message)."""


class StaticBatchTimeout(DependencyTimeout):
    """The batch ran longer than the page waits (504; it may still finish - see the batch log)."""


def inbox_files(inbox: Path = INBOX) -> list[dict]:
    if not inbox.is_dir():
        return []
    out = []
    for p in sorted(inbox.glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name)):
        if p.name.startswith("."):
            continue
        st = p.stat()
        out.append({"name": p.name, "size_bytes": st.st_size, "modified_at": datetime.fromtimestamp(st.st_mtime).astimezone(), "valid_name": True,
                    "ready": time.time() - st.st_mtime >= static_batch.MIN_FILE_AGE_S})
    return out


def lock_state() -> tuple[bool, Optional[str]]:
    if not LOCK.exists():
        return False, None
    if time.time() - LOCK.stat().st_mtime > static_batch.STALE_LOCK_S:
        return False, None
    return True, datetime.fromtimestamp(LOCK.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def run_now(timeout_s: int = RUN_TIMEOUT_S) -> dict:
    """Run the batch once and wait for it (a separate process: it calls this backend's bulk loaders)."""
    if not SCRIPT.exists():
        raise StaticBatchError(log_message=f"batch script not found: {SCRIPT}")
    started = datetime.now().astimezone()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=str(HERE), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise StaticBatchTimeout(f"The batch didn't finish within {timeout_s // 60} minutes. It may still "
                                 f"complete - check the batch log.") from exc
    output = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    return {"started_at": started, "finished_at": datetime.now().astimezone(), "exit_code": result.returncode,
            "busy": any(BUSY_MESSAGE in line for line in output), "output": obs.display_lines(output)}


# ---------------------------------------------------------------- battery_raw.batchlog (this job only)

_LIST_COLUMNS = """batch_id, run_id::text AS run_id, file_name, file_time, snapshot_time, status, started_at, finished_at,
    duration_ms, feeds_total, feeds_loaded, feeds_failed, rows_total, rows_inserted, rows_updated, rows_skipped,
    feed_results, warnings, id_changes, error_message, error_code, request_id, archive_path"""


def _dicts(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), {"job": JOB_NAME, **params})]


def last_log(db: Session) -> Optional[dict]:
    rows = _dicts(db, f"SELECT {_LIST_COLUMNS} FROM battery_raw.batchlog WHERE job_name = :job "
                      "ORDER BY batch_id DESC LIMIT 1")
    return rows[0] if rows else None


def logs_since(db: Session, since: datetime) -> list[dict]:
    return _dicts(db, f"SELECT {_LIST_COLUMNS} FROM battery_raw.batchlog WHERE job_name = :job AND started_at >= :since "
                      "ORDER BY batch_id", since=since - timedelta(seconds=1))


def list_logs(db: Session, status: Optional[str] = None, q: Optional[str] = None, limit: int = 25,
              offset: int = 0) -> tuple[list[dict], int, dict[str, int]]:
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
    counts = {r["status"]: r["n"] for r in _dicts(
        db, "SELECT status, count(*) AS n FROM battery_raw.batchlog WHERE job_name = :job GROUP BY status")}
    return items, total, {s: counts.get(s, 0) for s in STATUSES}


def get_log(db: Session, batch_id: int) -> Optional[dict]:
    rows = _dicts(db, f"SELECT {_LIST_COLUMNS}, api_url, host_name, report FROM battery_raw.batchlog "
                      "WHERE batch_id = :id AND job_name = :job", id=batch_id)
    return rows[0] if rows else None
