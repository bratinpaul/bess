"""Backend side of the historical loader (/api/batch/historical - the frontend's Batch -> Historical Load page):
the sites / systems to choose from, folders under <project>\\input, a scan (preview) of a folder, starting a load
in the background and following its progress, and the batch log (job 'historical_load').
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import historical_load as H  # noqa: E402

SCRIPT = HERE / "historical_load.py"
PROGRESS = HERE / "logs" / "last_run.json"
STATUSES = ("SUCCESS", "PARTIAL", "FAILED")


class HistoricalLoadError(Exception):
    pass


def options(db: Session) -> dict:
    """Sites with their battery systems and each system's EMS / HVAC units, plus the folders under input."""
    rows = db.execute(text("""
        SELECT s.site_id, s.site_name, s.site_code, b.battery_system_id, b.system_name,
               (SELECT array_agg(e.ems_code ORDER BY e.ems_code) FROM battery_master.ems_controller e
                 WHERE e.battery_system_id = b.battery_system_id) AS ems,
               (SELECT array_agg(h.hvac_code ORDER BY h.hvac_code) FROM battery_master.hvac_unit h
                 WHERE h.battery_system_id = b.battery_system_id) AS hvac
        FROM battery_master.site s JOIN battery_master.battery_system b USING (site_id)
        ORDER BY s.site_name, b.system_name""")).mappings()
    sites: dict[int, dict] = {}
    for r in rows:
        site = sites.setdefault(r["site_id"], {"site_id": r["site_id"], "site_name": r["site_name"],
                                               "site_code": r["site_code"], "systems": []})
        site["systems"].append({"battery_system_id": r["battery_system_id"], "system_name": r["system_name"],
                                "ems_codes": list(r["ems"] or []), "hvac_codes": list(r["hvac"] or [])})
    return {"input_root": str(H.INPUT_ROOT), "folders": folders(), "sites": list(sites.values()),
            "feeds": [{"key": f.key, "label": f.label, "endpoint": f.endpoint} for f in H.FEEDS]}


def folders(max_depth: int = 3) -> list[dict]:
    """Folders under input that contain loadable files (relative path, file count)."""
    root = H.INPUT_ROOT
    out = []
    for dirpath, dirnames, _ in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "archieve" and len(rel.parts) < max_depth]
        if not rel.parts:
            continue
        files = sum(1 for p in Path(dirpath).rglob("*")
                    if p.suffix.lower() in H.EXTENSIONS and "archieve" not in p.parts and not p.name.startswith("~$"))
        if files:
            out.append({"path": str(rel), "files": files})
    return sorted(out, key=lambda f: f["path"].lower())


def preview(db_system: str, folder: str, feeds: tuple[str, ...], recursive: bool, ems_code: Optional[str],
            hvac_code: Optional[str]) -> dict:
    import psycopg2
    try:
        path = H.resolve_folder(folder)
        with psycopg2.connect(**H.database_dsn()) as conn:
            assets = H.system_assets(conn, db_system)
        conn.close()
    except H.LoadError as exc:
        raise HistoricalLoadError(str(exc))
    plan = H.scan(path, assets, feeds, recursive, ems_code, hvac_code)
    plan["site_name"] = assets["site_name"]
    plan["system_name"] = assets["system_name"]
    return plan


def running() -> tuple[bool, Optional[str]]:
    if not H.LOCK.exists() or time.time() - H.LOCK.stat().st_mtime > H.STALE_LOCK_S:
        return False, None
    return True, datetime.fromtimestamp(H.LOCK.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def start(system: str, folder: str, feeds: tuple[str, ...], recursive: bool, ems_code: Optional[str],
          hvac_code: Optional[str], files: Optional[list[str]] = None) -> dict:
    """Start a load of the selected files (None = all that pass the check). It runs as its own process; the page
    shows its progress when the user refreshes (status())."""
    if files is not None and not files:
        raise HistoricalLoadError("Select at least one file to load")
    if running()[0]:
        raise HistoricalLoadError("A historical load is already running")
    PROGRESS.parent.mkdir(exist_ok=True)
    PROGRESS.unlink(missing_ok=True)
    args = [sys.executable, str(SCRIPT), "--folder", folder, "--system", system, "--feeds", ",".join(feeds),
            "--progress", str(PROGRESS)]
    if not recursive:
        args.append("--no-recursive")
    if ems_code:
        args += ["--ems-code", ems_code]
    if hvac_code:
        args += ["--hvac-code", hvac_code]
    if files is not None:
        selection = HERE / "logs" / "selected_files.json"
        selection.write_text(json.dumps(sorted(set(files))), encoding="utf-8")
        args += ["--files-json", str(selection)]
    log = open(HERE / "logs" / "historical_load.log", "a", encoding="utf-8")
    log.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {system} {folder}\n")
    log.flush()
    subprocess.Popen(args, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT,
                     env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(50):  # wait until the run has written its first progress
        if PROGRESS.exists():
            break
        time.sleep(0.1)
    return status()


def status() -> dict:
    is_running, since = running()
    progress = None
    for _ in range(5):  # the load may be replacing the file right now
        try:
            progress = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else None
            break
        except (OSError, ValueError):
            time.sleep(0.05)
    if progress and progress.get("status") == "RUNNING" and not is_running:
        # the process is gone without finishing (stopped or crashed): show it as interrupted
        progress["status"] = "FAILED"
        progress["error"] = progress.get("error") or "The load was interrupted before it finished (process stopped)"
        for f in progress.get("files", []):
            if f.get("status") in ("PENDING", "LOADING"):  # EXCLUDED files stay excluded
                f["status"] = "SKIPPED"
                f["message"] = "not loaded: the run was interrupted"
    return {"running": is_running, "running_since": since, "progress": progress}


# ---------------------------------------------------------------- batch log

_COLUMNS = """batch_id, run_id::text AS run_id, file_name, file_time, snapshot_time, status, started_at, finished_at,
    duration_ms, feeds_total, feeds_loaded, feeds_failed, rows_total, rows_inserted, rows_updated, rows_skipped,
    feed_results, warnings, id_changes, error_message, archive_path"""


def _dicts(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), {"job": H.JOB_NAME, **params})]


def list_logs(db: Session, status: Optional[str] = None, q: Optional[str] = None, limit: int = 25,
              offset: int = 0) -> tuple[list[dict], int, dict[str, int]]:
    where = ["job_name = :job"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        where.append("status = :status")
        params["status"] = status
    if q and q.strip():
        where.append("(file_name ILIKE :q OR archive_path ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    clause = "WHERE " + " AND ".join(where)
    items = _dicts(db, f"SELECT {_COLUMNS} FROM battery_raw.batchlog {clause} ORDER BY batch_id DESC "
                       "LIMIT :limit OFFSET :offset", **params)
    total = db.execute(text(f"SELECT count(*) FROM battery_raw.batchlog {clause}"), {"job": H.JOB_NAME, **params}).scalar_one()
    counts = {r["status"]: r["n"] for r in _dicts(
        db, "SELECT status, count(*) AS n FROM battery_raw.batchlog WHERE job_name = :job GROUP BY status")}
    return items, total, {s: counts.get(s, 0) for s in STATUSES}
