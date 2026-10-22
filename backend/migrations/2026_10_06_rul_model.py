"""Remaining Useful Life (RUL): model building runs, scores, leave-one-unit-out backtest and per-unit forecasts.

    python 2026_10_06_rul_model.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_06_rul_model.py --commit   # run for real

Training data comes from battery_master.v_rul_training (aging_snapshot + bess_system + battery_provenance), with
capacity_test (RPT ground truth), lifecycle_event (failures) and eol_criteria (the EOL definition) read alongside.

battery_ml.rul_run        one model building run (per chemistry models inside the artifact)
battery_ml.rul_score      scores per method and scope (all / life-fraction bucket / per unit)
battery_ml.rul_backtest   leave-one-unit-out predictions at every snapshot of every unit
battery_ml.rul_forecast   the final model's RUL per unit at its latest snapshot / RPT
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

TABLES = [
    """CREATE TABLE battery_ml.rul_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'rul',
        run_name          text,
        status            text        NOT NULL,
        is_default        boolean     NOT NULL DEFAULT false,
        system_ids        bigint[]    NOT NULL,
        methods           text[]      NOT NULL,
        params            jsonb       NOT NULL DEFAULT '{}',
        n_units           integer,
        n_rows            integer,
        metrics           jsonb,
        results           jsonb,
        warnings          jsonb       NOT NULL DEFAULT '[]',
        error_message     text,
        artifact_path     text,
        started_at        timestamptz NOT NULL DEFAULT now(),
        finished_at       timestamptz,
        duration_ms       integer,
        CONSTRAINT rul_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
    )""",
    "CREATE UNIQUE INDEX uq_rul_run_default ON battery_ml.rul_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.rul_score (
        run_id                 bigint  NOT NULL REFERENCES battery_ml.rul_run (run_id) ON DELETE CASCADE,
        method                 text    NOT NULL,
        scope                  text    NOT NULL,   -- 'all', 'life:<bucket>', 'unit:<system_code>'
        n                      integer,
        mae_days               numeric,
        rmse_days              numeric,
        bias_days              numeric,
        mae_cycles             numeric,
        coverage_pct           numeric,
        pinball_days           numeric,
        c_index                numeric,
        censored_violation_pct numeric,
        oracle_mae_days        numeric,
        PRIMARY KEY (run_id, method, scope)
    )""",
    """CREATE TABLE battery_ml.rul_backtest (
        run_id            bigint   NOT NULL REFERENCES battery_ml.rul_run (run_id) ON DELETE CASCADE,
        system_id         bigint   NOT NULL,
        snapshot_date     date     NOT NULL,
        method            text     NOT NULL,
        p10_days          real,
        p50_days          real,
        p90_days          real,
        p50_cycles        real,
        beyond            boolean,
        actual_days       real,     -- retired units: the true RUL; censored units: the synthetic label (oracle only)
        actual_cycles     real,
        known_alive_days  real,     -- censored units: days the unit is known to have survived past the snapshot
        censored          boolean  NOT NULL,
        PRIMARY KEY (run_id, system_id, snapshot_date, method)
    )""",
    """CREATE TABLE battery_ml.rul_forecast (
        run_id            bigint   NOT NULL REFERENCES battery_ml.rul_run (run_id) ON DELETE CASCADE,
        system_id         bigint   NOT NULL,
        method            text     NOT NULL,
        as_of             date     NOT NULL,
        soh_pct           real,
        resistance_ratio  real,
        p10_days          real,
        p50_days          real,
        p90_days          real,
        p10_cycles        real,
        p50_cycles        real,
        p90_cycles        real,
        eol_date_p50      date,
        trigger           text,     -- capacity / resistance / hazard
        beyond            boolean,
        PRIMARY KEY (run_id, system_id, method)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in TABLES:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'rul_%' ORDER BY 1""")
    print("   tables:", [r[0] for r in cur.fetchall()])
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
