"""Static data batch: load the master data JSON files waiting in input\\static.

Run from the frontend (Batch -> Static Data Load), or by hand (run_static_load.bat / python static_batch.py).

Every *.json file in the inbox (default C:\\bratin\\claude\\bess\\input\\static), oldest first:
  1. write the CSVs (tenant, site, battery system, container, pack, module, PCS, EMS, HVAC) to
     <inbox>\\archieve\\<YYYY-MM-DD>\\ (today's date; a second run the same day uses <YYYY-MM-DD>_2, ...)
     and load each through its master-data bulk loader (static_load.run), parents first;
  2. write load_report.json in that folder and move the JSON file into it;
  3. record the load report in battery_raw.batchlog (job_name 'static_data_load', one row per file).

The loaders insert new records and update known ones (by the JSON's UUIDs), so a file loaded twice doesn't
duplicate anything. A file that can't be used at all (bad JSON, missing sections, nothing loaded) stays in the
inbox so it can be fixed and run again; its failure is still logged. If the backend isn't answering nothing is
moved or logged. A lock file stops two runs overlapping. Activity is logged to logs\\static_batch.log.
"""
import argparse
import json
import logging
import os
import shutil
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import psycopg2
from psycopg2.extras import Json

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import static_load  # noqa: E402

PROJECT = HERE.parent
DEFAULT_INBOX = PROJECT / "input" / "static"
ARCHIVE_DIR = "archieve"
JOB_NAME = "static_data_load"
LOCK_NAME = ".static_batch.lock"
STALE_LOCK_S = 30 * 60
MIN_FILE_AGE_S = 5  # leave files alone that may still be being written
PLANT_TZ = "Asia/Kolkata"

from bess_common import observability as obs  # noqa: E402  (JSON logs, operations, activity log)

log = logging.getLogger("static_batch")


def setup_logging(verbose: bool) -> None:
    """JSON lines to stdout and <project>/logs/loader-static/ (bess_common.observability); rows also go to the activity log."""
    obs.setup_logging("loader-static", level="DEBUG" if verbose else "INFO")


def database_dsn() -> dict:
    """Connection settings from the backend's .env (DATABASE_URL), in plant local time."""
    url = None
    env = PROJECT / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
    if not url:
        raise RuntimeError(f"DATABASE_URL not found in {env}")
    u = urlparse(url.replace("postgresql+psycopg2://", "postgresql://"))
    return dict(host=u.hostname, port=u.port or 5432, dbname=u.path.lstrip("/"), user=unquote(u.username or ""),
                password=unquote(u.password or ""), options=f"-c timezone={PLANT_TZ}")


class Lock:
    def __init__(self, path: Path):
        self.path, self.held = path, False

    def __enter__(self) -> bool:
        if self.path.exists() and time.time() - self.path.stat().st_mtime > STALE_LOCK_S:
            log.warning("removing stale lock %s", self.path)
            self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as f:
            f.write(f"pid {os.getpid()} since {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        self.held = True
        return True

    def __exit__(self, *exc) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)


def pending_files(inbox: Path) -> list[Path]:
    """JSON files in the inbox, oldest first (by modified time, then name)."""
    files = [p for p in inbox.glob("*.json") if p.is_file() and not p.name.startswith(".")]
    ready = []
    for p in files:
        if time.time() - p.stat().st_mtime < MIN_FILE_AGE_S:
            log.info("%s was changed in the last %ss; skipped this run", p.name, MIN_FILE_AGE_S)
            continue
        ready.append(p)
    return sorted(ready, key=lambda p: (p.stat().st_mtime, p.name))


def archive_folder(inbox: Path, day: str) -> Path:
    """archieve/<YYYY-MM-DD>; if that already holds a run, <YYYY-MM-DD>_2, _3, ..."""
    base = inbox / ARCHIVE_DIR / day
    folder, n = base, 1
    while folder.exists() and any(folder.iterdir()):
        n += 1
        folder = base.with_name(f"{day}_{n}")
    return folder


def summarize(report: dict) -> dict:
    feeds = report.get("feeds", [])
    loaded = [f for f in feeds if f.get("http") == 200]
    return dict(
        feeds_total=len(feeds), feeds_loaded=len(loaded),
        feeds_failed=sum(1 for f in feeds if "http" in f and f.get("http") != 200),
        rows_total=sum(f.get("rows", 0) for f in feeds),
        rows_inserted=sum(f.get("inserted", 0) for f in loaded),
        rows_updated=sum(f.get("updated", 0) for f in loaded),
        rows_skipped=sum(f.get("skipped", 0) for f in feeds),
    )


def record(dsn: dict, row: dict) -> Optional[int]:
    with psycopg2.connect(**dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO battery_raw.batchlog
                 (run_id, job_name, file_name, file_time, status, started_at, finished_at, duration_ms,
                  feeds_total, feeds_loaded, feeds_failed, rows_total, rows_inserted, rows_updated, rows_skipped,
                  feed_results, warnings, id_changes, error_message, archive_path, api_url, host_name, report)
               VALUES (%(run_id)s, %(job_name)s, %(file_name)s, %(file_time)s, %(status)s, %(started_at)s,
                  %(finished_at)s, %(duration_ms)s, %(feeds_total)s, %(feeds_loaded)s, %(feeds_failed)s,
                  %(rows_total)s, %(rows_inserted)s, %(rows_updated)s, %(rows_skipped)s, %(feed_results)s,
                  %(warnings)s, '[]'::jsonb, %(error_message)s, %(archive_path)s, %(api_url)s, %(host_name)s,
                  %(report)s)
               RETURNING batch_id""", row)
        batch_id = cur.fetchone()[0]
    conn.close()
    return batch_id


def process(path: Path, inbox: Path, api: str, run_id: str, dsn: dict) -> str:
    started = datetime.now()
    file_time = datetime.fromtimestamp(path.stat().st_mtime)
    folder = archive_folder(inbox, started.strftime("%Y-%m-%d"))
    log.info("processing %s", path.name)
    outcome, report = static_load.run(path, api, out_dir=folder, log=lambda m: log.debug(m))
    if outcome == static_load.API_DOWN:
        log.warning("%s: %s - left in the inbox", path.name, report.get("error"))
        return outcome

    finished = datetime.now()
    status = {static_load.SUCCESS: "SUCCESS", static_load.PARTIAL: "PARTIAL"}.get(outcome, "FAILED")
    report.update(status=status, run_id=run_id, job_name=JOB_NAME, file_name=path.name,
                  started_at=started.isoformat(timespec="seconds"), finished_at=finished.isoformat(timespec="seconds"))
    archived: Optional[Path] = None
    if status == "FAILED":
        # nothing loaded: keep the file in the inbox to fix and rerun; drop the CSVs of this attempt
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    else:
        folder.mkdir(parents=True, exist_ok=True)
        report["archive_path"] = str(folder)
        (folder / "load_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        shutil.move(str(path), str(folder / path.name))
        archived = folder

    totals = summarize(report)
    row = dict(run_id=run_id, job_name=JOB_NAME, file_name=path.name, file_time=file_time, status=status,
               started_at=started, finished_at=finished, duration_ms=int((finished - started).total_seconds() * 1000),
               **totals, feed_results=Json(report.get("feeds", [])), warnings=Json(report.get("warnings", [])),
               error_message=report.get("error"), archive_path=str(archived) if archived else None, api_url=api,
               host_name=socket.gethostname(), report=Json(json.loads(json.dumps(report, default=str))))
    try:
        batch_id = record(dsn, row)
    except psycopg2.Error as exc:
        log.error("%s: %s but the batch log row couldn't be written: %s", path.name, status, exc)
        batch_id = None
    obs.op_set(rows_inserted=totals["rows_inserted"], rows_updated=totals["rows_updated"],
               rows_rejected=totals["rows_skipped"],
               rows_total=totals["rows_inserted"] + totals["rows_updated"] + totals["rows_skipped"],
               outcome="success" if status == "SUCCESS" else "failed", status=status, batch_id=batch_id)
    log.info("%s -> %s: %d inserted, %d updated, %d skipped%s | batchlog #%s | %s", path.name, status,
             totals["rows_inserted"], totals["rows_updated"], totals["rows_skipped"],
             f" | {report.get('error')}" if report.get("error") else "", batch_id, archived or "left in the inbox")
    for feed in report.get("feeds", []):
        for err in feed.get("errors", [])[:5]:
            log.info("  %s: %s", feed["label"], err)
    for warning in report.get("warnings", []):
        log.info("  warning: %s", warning)
    return outcome


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Load the static master data JSON files in the inbox.")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    parser.add_argument("--api", default=static_load.DEFAULT_API)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    if not args.inbox.is_dir():
        log.error("inbox %s doesn't exist", args.inbox)
        return 2
    with Lock(args.inbox / LOCK_NAME) as locked:
        if not locked:
            log.info("another run is still going; nothing done")
            return 0
        files = pending_files(args.inbox)
        if not files:
            log.info("no JSON files in %s", args.inbox)
            return 0
        run_id = str(uuid.uuid4())
        dsn = database_dsn()
        obs.enable_activity_log(obs.engine_from_dsn(dsn))
        outcomes = []
        for p in files:
            with obs.request_context(run_id, user="batch.service@bess.local", role="BATCH_SERVICE"),                     obs.operation("load", "static_master_data", logger=log, file=p.name):
                outcomes.append(process(p, args.inbox, args.api, run_id, dsn))
        obs.activity.flush()
    if static_load.API_DOWN in outcomes:
        return 3
    return 0 if all(o == static_load.SUCCESS for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
