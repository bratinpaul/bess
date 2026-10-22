"""Operations schema and the activity log (user actions, failed requests, loads, KPI runs, model training, auth events).

    python 2026_10_21_activity_log.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_21_activity_log.py --commit   # run for real

battery_itops.activity_log   written by bess_common.logging (backend, ML service, loaders) - one row per
                           changing request (POST/PUT/PATCH/DELETE), failed request (4xx/5xx), auth event, load,
                           KPI run and training run. Metadata only - never request bodies, passwords or tokens.
                           Kept 90 days (purged by the writer once a day). Full detail stays in the JSON log files.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE SCHEMA IF NOT EXISTS battery_itops;

CREATE TABLE IF NOT EXISTS battery_itops.activity_log (
    activity_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts            timestamptz NOT NULL DEFAULT now(),
    service       text        NOT NULL,              -- backend | ml | loader-realtime | loader-static | loader-historical
    kind          text        NOT NULL CHECK (kind IN ('REQUEST', 'AUTH', 'LOAD', 'KPI', 'TRAINING', 'ERROR')),
    event         text        NOT NULL,              -- e.g. request, load.end, kpi.end, training.end, LOGIN_FAILED
    outcome       text        NOT NULL CHECK (outcome IN ('success', 'failed')),
    request_id    text,
    user_email    text,
    role          text,
    method        text,
    path          text,
    status_code   smallint,
    duration_ms   integer,
    operation     text,                              -- e.g. bms_bulk_upload, bms_kpi_calculate, hvac-cop training
    rows_total    integer,
    rows_inserted integer,
    rows_updated  integer,
    rows_rejected integer,
    ip            text,
    detail        jsonb                              -- small, redacted extras (error class, run id, entity ...)
);
CREATE INDEX IF NOT EXISTS ix_activity_ts ON battery_itops.activity_log (ts DESC);
CREATE INDEX IF NOT EXISTS ix_activity_request ON battery_itops.activity_log (request_id);
CREATE INDEX IF NOT EXISTS ix_activity_kind ON battery_itops.activity_log (kind, ts DESC);
CREATE INDEX IF NOT EXISTS ix_activity_user ON battery_itops.activity_log (user_email, ts DESC);
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("SELECT count(*) FROM battery_itops.activity_log")
            print("activity_log rows:", cur.fetchone()[0])
        if commit:
            conn.commit()
            print("committed")
        else:
            conn.rollback()
            print("rehearsal - rolled back (use --commit)")
    finally:
        conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
