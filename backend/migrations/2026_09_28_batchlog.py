"""Create battery_raw.batchlog: one row per snapshot file the realtime batch processed.

    python 2026_09_28_batchlog.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_28_batchlog.py --commit   # run for real

Written by snapshot_loader/realtime_batch.py after each file (see its docstring):

    run_id                one scheduler run (a run can process several files)
    file_name, file_time  the input file and the time in its name (YYYY-MM-DD-HH-MM-SS.json)
    snapshot_time         meta.timestamp inside the file (plant local time)
    status                SUCCESS / PARTIAL (some rows skipped or a feed failed) / FAILED (nothing loaded)
    started_at .. duration_ms
    feeds_*, rows_*       totals over the seven bulk loads
    feed_results          per feed: rows, inserted, updated, skipped, row errors, HTTP status
    warnings, id_changes  snapshot checks and alarm/dispatch IDs the loader reassigned
    error_message         why a FAILED file couldn't be used
    archive_path          archieve/<file name> folder holding the CSVs, load_report.json and the input file
    report                the full load report
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
T = "battery_raw.batchlog"

STEPS = [
    f"""CREATE TABLE {T} (
        batch_id        bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_id          uuid        NOT NULL,
        job_name        text        NOT NULL DEFAULT 'realtime_snapshot',
        file_name       text        NOT NULL,
        file_time       timestamptz,
        snapshot_time   timestamptz,
        status          text        NOT NULL,
        started_at      timestamptz NOT NULL,
        finished_at     timestamptz NOT NULL,
        duration_ms     integer     NOT NULL,
        feeds_total     integer     NOT NULL DEFAULT 0,
        feeds_loaded    integer     NOT NULL DEFAULT 0,
        feeds_failed    integer     NOT NULL DEFAULT 0,
        rows_total      integer     NOT NULL DEFAULT 0,
        rows_inserted   integer     NOT NULL DEFAULT 0,
        rows_updated    integer     NOT NULL DEFAULT 0,
        rows_skipped    integer     NOT NULL DEFAULT 0,
        feed_results    jsonb       NOT NULL DEFAULT '[]'::jsonb,
        warnings        jsonb       NOT NULL DEFAULT '[]'::jsonb,
        id_changes      jsonb       NOT NULL DEFAULT '[]'::jsonb,
        error_message   text,
        archive_path    text,
        api_url         text,
        host_name       text,
        report          jsonb,
        created_at      timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT batchlog_status CHECK (status IN ('SUCCESS', 'PARTIAL', 'FAILED')),
        CONSTRAINT batchlog_times CHECK (finished_at >= started_at),
        CONSTRAINT batchlog_rows CHECK (rows_inserted + rows_updated + rows_skipped <= rows_total)
    )""",
    f"CREATE INDEX idx_batchlog_started ON {T} (started_at DESC)",
    f"CREATE INDEX idx_batchlog_snapshot ON {T} (snapshot_time DESC)",
    f"CREATE INDEX idx_batchlog_file ON {T} (file_name)",
    f"CREATE INDEX idx_batchlog_problems ON {T} (started_at DESC) WHERE status <> 'SUCCESS'",
    f"COMMENT ON TABLE {T} IS 'Load reports of the realtime snapshot batch: one row per input file processed'",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute(
        """SELECT column_name, data_type, is_nullable FROM information_schema.columns
           WHERE table_schema = 'battery_raw' AND table_name = 'batchlog' ORDER BY ordinal_position"""
    )
    for row in cur.fetchall():
        print("  ", row)
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
