"""Realtime snapshot batch: load every new snapshot file dropped in the realtime inbox.

Scheduled every minute (install_schedule.bat); can also be run by hand (realtime_batch.bat).

Every file named YYYY-MM-DD-HH-MM-SS.json in the inbox (default C:\\bratin\\claude\\bess\\input\\realtime) is
loaded in a loop, sorted by the date/time in its name, oldest first (at most MAX_FILES_PER_RUN per run; a larger
backlog continues in the next runs). For each file:
  1. write the seven CSVs (BMS, module, PCS, EMS, HVAC, dispatch events, alarms) to
     <inbox>\\archieve\\<YYYY-MM-DD-HH-MM-SS>\\ and load each through its bulk-load API (load_snapshot.run);
  2. write load_report.json in that folder;
  3. move the input file into that folder;
  4. record the load report in battery_raw.batchlog (one row per file).

Every bulk load inserts a record that is new and updates the one that exists with the same primary key
(telemetry: asset + timestamp; alarms/dispatches: id + start), so loading a file twice doesn't duplicate data.
An update changes only the columns the file has; the others keep their stored values.

A file that can't be used (bad JSON, missing sections) is archived the same way with status FAILED, so it
isn't retried every minute. If the backend isn't answering, nothing is moved: the files stay in the inbox and
the next run tries again. Files changed in the last few seconds (maybe still being copied) wait for the next
run, and a lock file stops two runs overlapping. Activity is logged to logs\\realtime_batch.log.
"""
import argparse
import json
import logging
import os
import re
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_snapshot  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DEFAULT_INBOX = PROJECT / "input" / "realtime"
ARCHIVE_DIR = "archieve"
FILE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.json$")
MIN_FILE_AGE_S = 5  # leave files alone that may still be being written
STALE_LOCK_S = 15 * 60
LOCK_NAME = ".realtime_batch.lock"  # in the inbox while a run is going
TASK_NAME = r"BESS\Realtime Snapshot Load"  # the scheduled task (install_schedule.bat)
# a backlog is worked off over several runs (oldest first) so a run stays well inside the scheduler's 10-minute limit
MAX_FILES_PER_RUN = 500
PLANT_TZ = "Asia/Kolkata"  # times are plant local; the database session uses the same zone

from bess_common import observability as obs  # noqa: E402  (JSON logs, operations, activity log)
from bess_common.errors import (EXIT_CONFIG, EXIT_FAILED, EXIT_OK, EXIT_PARTIAL, EXIT_UNEXPECTED,  # noqa: E402
                                batch_error_code, run_main)

log = logging.getLogger("realtime_batch")


# ---------------------------------------------------------------- setup


def setup_logging(verbose: bool) -> None:
    """JSON lines to stdout and <project>/logs/loader-realtime/ (bess_common.observability); rows also go to the activity log."""
    obs.setup_logging("loader-realtime", level="DEBUG" if verbose else "INFO")


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
    """Lock file so a run that takes longer than a minute isn't joined by the next one."""

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


# ---------------------------------------------------------------- one file


def pending_files(inbox: Path) -> list[tuple[Path, datetime]]:
    """Snapshot files in the inbox with the time in their name, oldest first (ties by name)."""
    found = []
    for path in inbox.iterdir():
        match = FILE_PATTERN.match(path.name)
        if not path.is_file() or path.name.startswith("."):  # the lock and the simulator's temporary files
            continue
        if not match:
            log.debug("ignoring %s (not named YYYY-MM-DD-HH-MM-SS.json)", path.name)
            continue
        try:
            file_time = datetime.strptime(match.group(1), "%Y-%m-%d-%H-%M-%S")
        except ValueError:
            log.warning("ignoring %s: the name isn't a valid date/time", path.name)
            continue
        if time.time() - path.stat().st_mtime < MIN_FILE_AGE_S:
            log.info("%s was changed in the last %ss; waiting for the next run", path.name, MIN_FILE_AGE_S)
            continue
        found.append((path, file_time))
    return sorted(found, key=lambda f: (f[1], f[0].name))


def archive_folder(inbox: Path, stem: str) -> Path:
    """archieve/<stem>; a file name seen before gets archieve/<stem>_2, _3, ..."""
    base = inbox / ARCHIVE_DIR / stem
    folder, n = base, 1
    while (folder / f"{stem}.json").exists():
        n += 1
        folder = base.with_name(f"{stem}_{n}")
    return folder


def summarize(report: dict) -> dict:
    feeds = report.get("feeds", [])
    loaded = [f for f in feeds if f.get("http") == 200]
    return dict(
        feeds_total=len(feeds),
        feeds_loaded=len(loaded),
        feeds_failed=sum(1 for f in feeds if "http" in f and f.get("http") != 200),
        rows_total=sum(f.get("rows", 0) for f in feeds),
        rows_inserted=sum(f.get("inserted", 0) for f in loaded),
        rows_updated=sum(f.get("updated", 0) for f in loaded),
        rows_skipped=sum(f.get("skipped", 0) for f in loaded),
    )


def record(conn, row: dict) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO battery_raw.batchlog
                 (run_id, file_name, file_time, snapshot_time, status, started_at, finished_at, duration_ms,
                  feeds_total, feeds_loaded, feeds_failed, rows_total, rows_inserted, rows_updated, rows_skipped,
                  feed_results, warnings, id_changes, error_message, error_code, request_id, archive_path, api_url,
                  host_name, report)
               VALUES (%(run_id)s, %(file_name)s, %(file_time)s, %(snapshot_time)s, %(status)s, %(started_at)s,
                  %(finished_at)s, %(duration_ms)s, %(feeds_total)s, %(feeds_loaded)s, %(feeds_failed)s,
                  %(rows_total)s, %(rows_inserted)s, %(rows_updated)s, %(rows_skipped)s, %(feed_results)s,
                  %(warnings)s, %(id_changes)s, %(error_message)s, %(error_code)s, %(request_id)s, %(archive_path)s,
                  %(api_url)s, %(host_name)s, %(report)s)
               RETURNING batch_id""",
            row,
        )
        batch_id = cur.fetchone()[0]
    conn.commit()
    return batch_id


def process(path: Path, file_time: datetime, inbox: Path, api: str, run_id: str, dsn: dict) -> str:
    """Load one file; returns the outcome (API_DOWN leaves the file in place)."""
    started = datetime.now()
    folder = archive_folder(inbox, path.stem)
    log.info("processing %s", path.name)
    outcome, report = load_snapshot.run(path, api, out_dir=folder, log=lambda msg: log.debug(msg.strip()))
    if outcome == load_snapshot.API_DOWN:
        log.warning("%s: %s - left in the inbox, will retry next run", path.name, report.get("error"))
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        return outcome

    # the file name and the snapshot inside should describe the same interval
    if report.get("interval") and report["interval"][:19] != file_time.isoformat():
        report["warnings"].append(f"file name says {file_time:%Y-%m-%d %H:%M:%S} but meta.timestamp is "
                                  f"{report['interval'].replace('T', ' ')}")

    # archive: CSVs are already there; add the report and move the input file in
    finished = datetime.now()
    status = {load_snapshot.SUCCESS: "SUCCESS", load_snapshot.PARTIAL: "PARTIAL"}.get(outcome, "FAILED")
    folder.mkdir(parents=True, exist_ok=True)
    report.update(status=status, run_id=run_id, file_name=path.name, file_time=file_time.isoformat(),
                  started_at=started.isoformat(timespec="seconds"), finished_at=finished.isoformat(timespec="seconds"),
                  archive_path=str(folder))
    (folder / "load_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.move(str(path), str(folder / path.name))

    totals = summarize(report)
    row = dict(
        run_id=run_id, file_name=path.name, file_time=file_time,
        snapshot_time=datetime.fromisoformat(report["interval"]) if report.get("interval") else None,
        status=status, started_at=started, finished_at=finished,
        duration_ms=int((finished - started).total_seconds() * 1000), **totals,
        feed_results=Json(report.get("feeds", [])), warnings=Json(report.get("warnings", [])),
        id_changes=Json(report.get("id_changes", [])), error_message=report.get("error"),
        error_code=batch_error_code(status, report.get("error_code")), request_id=run_id,
        archive_path=str(folder), api_url=api, host_name=socket.gethostname(), report=Json(report),
    )
    try:
        with psycopg2.connect(**dsn) as conn:
            batch_id = record(conn, row)
        conn.close()
    except psycopg2.Error as exc:
        log.error("%s loaded (%s) but the batch log row couldn't be written: %s", path.name, status, exc)
        batch_id = None
    obs.op_set(rows_inserted=totals["rows_inserted"], rows_updated=totals["rows_updated"],
               rows_rejected=totals["rows_skipped"],
               rows_total=totals["rows_inserted"] + totals["rows_updated"] + totals["rows_skipped"],
               outcome="success" if status == "SUCCESS" else "failed", status=status, batch_id=batch_id)
    log.info("%s -> %s: %d inserted, %d updated, %d skipped%s | batchlog #%s | %s",
             path.name, status, totals["rows_inserted"], totals["rows_updated"], totals["rows_skipped"],
             f" | {report.get('error')}" if report.get("error") else "", batch_id, folder)
    for warning in report.get("warnings", []):
        log.info("  warning: %s", warning)
    for change in report.get("id_changes", []):
        log.info("  id: %s", change)
    return outcome


# ---------------------------------------------------------------- main


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Load new snapshot files from the realtime inbox.")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX, help=f"inbox folder (default {DEFAULT_INBOX})")
    parser.add_argument("--api", default=load_snapshot.DEFAULT_API, help="backend base URL")
    parser.add_argument("--verbose", action="store_true", help="also log each step of every load")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    inbox = args.inbox
    if not inbox.is_dir():
        log.error("inbox %s doesn't exist", inbox)
        return EXIT_CONFIG
    (inbox / ARCHIVE_DIR).mkdir(exist_ok=True)

    with Lock(inbox / LOCK_NAME) as locked:
        if not locked:
            log.info("another run is still going (lock %s); skipping this one", inbox / LOCK_NAME)
            return 0
        files = pending_files(inbox)
        if not files:
            log.debug("no new files")
            return 0
        if len(files) > MAX_FILES_PER_RUN:
            log.info("%d files waiting; loading the oldest %d now, the rest in the next runs", len(files), MAX_FILES_PER_RUN)
            files = files[:MAX_FILES_PER_RUN]
        log.info("%d file(s) to load, oldest first: %s", len(files), ", ".join(p.name for p, _ in files))
        dsn = database_dsn()
        obs.enable_activity_log(obs.engine_from_dsn(dsn))
        run_id = str(uuid.uuid4())
        results = []
        for path, file_time in files:
            try:
                # the run id is the request id of every API call of this file (backend log lines match)
                with obs.request_context(run_id, user="batch.service@bess.local", role="BATCH_SERVICE"),                         obs.operation("load", "realtime_snapshot", logger=log, file=path.name):
                    outcome = process(path, file_time, inbox, args.api.rstrip("/"), run_id, dsn)
            except Exception:  # noqa: BLE001 - keep the scheduler alive; the file stays for the next run
                log.exception("unexpected error while processing %s; left in the inbox", path.name)
                obs.activity.flush()
                return EXIT_UNEXPECTED
            results.append(outcome)
            if outcome == load_snapshot.API_DOWN:
                break  # the rest would fail the same way
        log.info("run %s: %d file(s) - %s", run_id[:8], len(results), ", ".join(results))
        obs.activity.flush()
        if all(r == load_snapshot.SUCCESS for r in results):
            return EXIT_OK
        return EXIT_PARTIAL if all(r in (load_snapshot.SUCCESS, load_snapshot.PARTIAL) for r in results) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(run_main("realtime_snapshot_load", main))
