"""Fault classification / diagnosis runs in battery_ml.

    python 2026_10_19_fault_diag.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_19_fault_diag.py --commit   # run for real

fault_diag_run         one training run: window, parameters (leakage mode, granularity, feature families, engine and
                       ML settings, fusion weight), summary (support, coverage, time-to-detect), metrics (out-of-fold and
                       forward scorecards for the signature engine, the ML model and the fused model; importance),
                       warnings and the model file.
fault_diag_example     the run's out-of-fold result per training window: label, fused top-3, ML / engine top-3,
                       contributions and the signature evidence (the viewer's episode diagnosis).
fault_diag_scan_point  windowed inference over a system / date range: top class and probability per window.
fault_diag_candidate   merged candidate fault events from a scan, with evidence, the matching episode and the
                       fault_prediction row it was written to (the operator confirmation loop).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE TABLE IF NOT EXISTS battery_ml.fault_diag_run (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_name        text,
    status          text        NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    is_default      boolean     NOT NULL DEFAULT false,
    date_from       date,
    date_to         date,
    params          jsonb       NOT NULL DEFAULT '{}',
    summary         jsonb,
    metrics         jsonb,
    warnings        jsonb       NOT NULL DEFAULT '[]',
    artifact_path   text,
    published_at    timestamptz,
    error_message   text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    duration_ms     integer
);

CREATE TABLE IF NOT EXISTS battery_ml.fault_diag_example (
    run_id          bigint      NOT NULL REFERENCES battery_ml.fault_diag_run (run_id) ON DELETE CASCADE,
    example_key     text        NOT NULL,
    group_key       text        NOT NULL,
    kind            text        NOT NULL,            -- episode | none
    episode_id      text,
    system_id       bigint,
    window_start    timestamptz NOT NULL,
    window_end      timestamptz NOT NULL,
    label           text        NOT NULL,
    predicted       text        NOT NULL,
    probability     numeric(6,4),
    correct         boolean     NOT NULL,
    fold            smallint,
    detail          jsonb       NOT NULL DEFAULT '{}',   -- top3 (fused / ml / engine), contributions, evidence
    PRIMARY KEY (run_id, example_key)
);
CREATE INDEX IF NOT EXISTS ix_fault_diag_example_ep ON battery_ml.fault_diag_example (run_id, episode_id);

CREATE TABLE IF NOT EXISTS battery_ml.fault_diag_scan_point (
    run_id          bigint      NOT NULL REFERENCES battery_ml.fault_diag_run (run_id) ON DELETE CASCADE,
    system_id       bigint      NOT NULL,
    ts              timestamptz NOT NULL,             -- window end
    predicted       text        NOT NULL,
    probability     numeric(6,4),
    p_none          numeric(6,4),
    top3            jsonb,
    alarms          text[],
    PRIMARY KEY (run_id, system_id, ts)
);

CREATE TABLE IF NOT EXISTS battery_ml.fault_diag_candidate (
    candidate_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          bigint      NOT NULL REFERENCES battery_ml.fault_diag_run (run_id) ON DELETE CASCADE,
    system_id       bigint      NOT NULL,
    first_ts        timestamptz NOT NULL,
    peak_ts         timestamptz NOT NULL,
    last_ts         timestamptz NOT NULL,
    fault_code      text        NOT NULL REFERENCES battery_master.fault_catalog (fault_code),
    probability     numeric(6,4),
    n_windows       integer     NOT NULL DEFAULT 1,
    top3            jsonb,
    contributions   jsonb,
    evidence        jsonb,
    alarms          text[],
    asset_code      text,
    episode_id      text REFERENCES battery_master.fault_episode (episode_id) ON DELETE SET NULL,
    actual_fault_code text REFERENCES battery_master.fault_catalog (fault_code),
    prediction_id   bigint REFERENCES battery_master.fault_prediction (prediction_id) ON DELETE SET NULL,
    status          text        NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'CONFIRMED', 'REJECTED')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, system_id, peak_ts, fault_code)
);
CREATE INDEX IF NOT EXISTS ix_fault_diag_candidate_run ON battery_ml.fault_diag_candidate (run_id, system_id, peak_ts);
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("""SELECT table_name FROM information_schema.tables
                           WHERE table_schema = 'battery_ml' AND table_name LIKE 'fault_diag%' ORDER BY 1""")
            print("tables:", [r[0] for r in cur.fetchall()])
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
