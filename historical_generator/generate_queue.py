"""Generate historical telemetry files for one or more sites, one after another (Batch -> Historical Generator).

Started by the backend (generator_control.start) as its own process when the user clicks Generate; the page follows it
by hand (Refresh status reads the progress file). Input is a jobs file:
  {"run_id": "...", "date_from": "2026-08-01", "date_to": "2026-09-30", "module_from": "2026-09-01",
   "sites": [{"battery_system_id": 11, "overrides": {...}, "calendar": {...}}, ...]}
Each site is written to input/historical/<Site> BESS/ by generator.generate (same layout as the Bhadla folder).
One battery_raw.batchlog row is written per run (job_name 'historical_generate'), one feed_results entry per site.

Run by hand:  .venv\\Scripts\\python historical_generator\\generate_queue.py --jobs jobs.json --progress progress.json
"""
import argparse
import json
import os
import socket
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import Json

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import generator as G  # noqa: E402

JOB_NAME = "historical_generate"
LOCK = HERE / ".historical_generate.lock"
STALE_LOCK_S = 6 * 3600


@dataclass
class Progress:
    path: Optional[Path]
    state: dict = field(default_factory=dict)

    def write(self, **changes) -> None:
        self.state.update(changes, updated_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        if not self.path:
            return
        tmp = self.path.with_suffix(".tmp")
        for attempt in range(20):  # the backend may be reading the file right now (Windows refuses the replace)
            try:
                tmp.write_text(json.dumps(self.state, indent=2, default=str), encoding="utf-8")
                os.replace(tmp, self.path)
                return
            except OSError:
                time.sleep(0.05 * (attempt + 1))


def run(jobs: dict, progress_path: Optional[Path], log=print) -> dict:
    start, end = date.fromisoformat(jobs["date_from"]), date.fromisoformat(jobs["date_to"])
    module_from = date.fromisoformat(jobs["module_from"]) if jobs.get("module_from") else None
    started = datetime.now().astimezone()
    sites = [{"battery_system_id": j["battery_system_id"], "site_name": j.get("site_name"),
              "system_name": j.get("system_name"), "folder_relative": j.get("folder_relative"), "status": "PENDING",
              "step": None, "seconds": None, "files": None, "rows": None, "error": None, "warnings": [],
              "scenarios": None, "overrides": None} for j in jobs["sites"]]
    progress = Progress(progress_path)
    progress.write(run_id=jobs["run_id"], status="RUNNING", started_at=started.isoformat(), finished_at=None,
                   date_from=start.isoformat(), date_to=end.isoformat(),
                   module_from=module_from.isoformat() if module_from else None, sites=sites, current=None,
                   error=None, batch_id=None)

    for job, site in zip(jobs["sites"], sites):
        label = site["site_name"] or f"system {site['battery_system_id']}"
        site["status"] = "GENERATING"
        progress.write(current=label, sites=sites)
        log(f"{label}: generating {start} .. {end}")
        t0 = time.perf_counter()

        def step(message: str, site=site) -> None:
            site["step"] = message
            progress.write(sites=sites)
            log(f"  {message}")

        try:
            report = G.generate(job["battery_system_id"], start, end, step, overrides=job.get("overrides"),
                                calendar=job.get("calendar"), module_from=module_from)
            site.update(status="DONE", step=None, files=len(report["files"]),
                        rows=sum(f["rows"] for f in report["files"]), warnings=report["warnings"],
                        scenarios=report["scenarios"], overrides=report.get("overrides"),
                        folder_relative=report["folder_relative"], site_name=report["site_name"],
                        system_name=report["system_name"])
        except G.GenerationError as exc:
            site.update(status="FAILED", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - one site's failure must not stop the others
            site.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
            log(traceback.format_exc())
        site["seconds"] = round(time.perf_counter() - t0, 1)
        progress.write(sites=sites)
        log(f"{label}: {site['status']} ({site['seconds']} s){' - ' + site['error'] if site['error'] else ''}")

    finished = datetime.now().astimezone()
    ok = sum(s["status"] == "DONE" for s in sites)
    status = "SUCCESS" if ok == len(sites) else ("PARTIAL" if ok else "FAILED")
    error = None if ok == len(sites) else f"{len(sites) - ok} of {len(sites)} site(s) failed"
    batch_id = write_batchlog(jobs, sites, status, error, started, finished, log)
    progress.write(status=status, finished_at=finished.isoformat(), error=error, batch_id=batch_id, current=None,
                   sites=sites)
    log(f"{status}: {ok} of {len(sites)} site(s) generated | batchlog #{batch_id}")
    return {"status": status, "batch_id": batch_id}


def write_batchlog(jobs, sites, status, error, started, finished, log) -> Optional[int]:
    rows = sum(s["rows"] or 0 for s in sites)
    names = ", ".join(G.short_name(s["site_name"]) if s["site_name"] else str(s["battery_system_id"]) for s in sites)
    feed_results = [{"feed": s["site_name"], "csv": s["folder_relative"], "rows": s["rows"] or 0,
                     "result": f"{s['files']} files · {s['system_name']}" if s["status"] == "DONE" else None,
                     "errors": [s["error"]] if s["error"] else []} for s in sites]
    try:
        with psycopg2.connect(**G.database_dsn()) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO battery_raw.batchlog
                     (run_id, job_name, file_name, status, started_at, finished_at, duration_ms, feeds_total,
                      feeds_loaded, feeds_failed, rows_total, feed_results, warnings, error_message, archive_path,
                      host_name, report)
                   VALUES (%(run_id)s, %(job)s, %(file_name)s, %(status)s, %(started)s, %(finished)s, %(ms)s, %(total)s,
                      %(done)s, %(failed)s, %(rows)s, %(feed_results)s, %(warnings)s, %(error)s, %(folder)s, %(host)s,
                      %(report)s) RETURNING batch_id""",
                dict(run_id=jobs["run_id"], job=JOB_NAME, file_name=f"{names} · {jobs['date_from']} – {jobs['date_to']}",
                     status=status, started=started, finished=finished,
                     ms=int((finished - started).total_seconds() * 1000), total=len(sites),
                     done=sum(s["status"] == "DONE" for s in sites), failed=sum(s["status"] == "FAILED" for s in sites),
                     rows=rows, feed_results=Json(feed_results),
                     warnings=Json([f"{s['site_name']}: {w}" for s in sites for w in s["warnings"]]), error=error,
                     folder=str(G.HISTORICAL.relative_to(G.PROJECT / "input")), host=socket.gethostname(),
                     report=Json(json.loads(json.dumps({"jobs": jobs, "sites": sites}, default=str)))))
            batch_id = cur.fetchone()[0]
        conn.close()
        return batch_id
    except psycopg2.Error as exc:
        log(f"batch log not written: {exc}")
        return None


class Lock:
    def __enter__(self) -> bool:
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime > STALE_LOCK_S:
            LOCK.unlink(missing_ok=True)
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            self.held = False
            return False
        with os.fdopen(fd, "w") as f:
            f.write(f"pid {os.getpid()} since {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        self.held = True
        return True

    def __exit__(self, *exc) -> None:
        if self.held:
            LOCK.unlink(missing_ok=True)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate historical telemetry files for one or more sites.")
    ap.add_argument("--jobs", required=True, type=Path, help="jobs JSON (see the module docstring)")
    ap.add_argument("--progress", type=Path)
    args = ap.parse_args(argv)
    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    with Lock() as locked:
        if not locked:
            print("another generation is still running")
            return 4
        result = run(jobs, args.progress, log=lambda m: print(m, flush=True))
    return {"SUCCESS": 0, "PARTIAL": 1}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
