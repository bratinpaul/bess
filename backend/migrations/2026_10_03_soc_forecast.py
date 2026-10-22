"""SOC trajectory forecasting runs in battery_ml.

    python 2026_10_03_soc_forecast.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_03_soc_forecast.py --commit   # run for real

soc_forecast_run    one model building run: EMS units, window, horizon, origin steps, SOC limits, LightGBM settings,
                    the fitted physics per EMS (%/kWh charge / discharge, limits, implied capacity and round trip),
                    scores and the results the pages draw. One run can be the viewer's default.
soc_forecast_score  per run and method (hold, physics / hybrid x typical / scheduled plan): MAE, RMSE, MAE at
                    1 h / 4 h / end, max error, P10-P90 coverage and width, skill vs hold, drawdown error, breach rate.
soc_forecast_point  backtest trajectories (every n-th test origin, every 5-min step, every method) with the actual
                    SOC and the planned setpoint - for the viewer.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """CREATE TABLE battery_ml.soc_forecast_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'soc_forecast',
        run_name          text,
        status            text        NOT NULL,
        is_default        boolean     NOT NULL DEFAULT false,
        ems_ids           bigint[]    NOT NULL,
        date_from         date,
        date_to           date,
        horizon_h         numeric     NOT NULL,
        test_fraction     numeric     NOT NULL,
        origin_step_min   integer     NOT NULL,
        params            jsonb       NOT NULL DEFAULT '{}',
        n_train_rows      integer,
        n_test_origins    integer,
        best_method       text,
        metrics           jsonb,
        results           jsonb,
        warnings          jsonb       NOT NULL DEFAULT '[]',
        error_message     text,
        artifact_path     text,
        started_at        timestamptz NOT NULL DEFAULT now(),
        finished_at       timestamptz,
        duration_ms       integer,
        CONSTRAINT soc_forecast_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
    )""",
    "CREATE UNIQUE INDEX uq_soc_forecast_run_default ON battery_ml.soc_forecast_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.soc_forecast_score (
        run_id        bigint  NOT NULL REFERENCES battery_ml.soc_forecast_run (run_id) ON DELETE CASCADE,
        method        text    NOT NULL,
        n             integer,
        mae           numeric,
        rmse          numeric,
        mae_1h        numeric,
        mae_4h        numeric,
        mae_end       numeric,
        max_error     numeric,
        coverage_pct  numeric,
        width         numeric,
        skill_pct     numeric,
        drawdown_mae  numeric,
        breach_pct    numeric,
        PRIMARY KEY (run_id, method)
    )""",
    """CREATE TABLE battery_ml.soc_forecast_point (
        run_id     bigint      NOT NULL REFERENCES battery_ml.soc_forecast_run (run_id) ON DELETE CASCADE,
        ems_id     bigint      NOT NULL,
        origin_ts  timestamptz NOT NULL,
        step       smallint    NOT NULL,
        method     text        NOT NULL,
        p10        real,
        p50        real,
        p90        real,
        actual     real,
        plan_kw    real,
        PRIMARY KEY (run_id, ems_id, origin_ts, method, step)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'soc_forecast%' ORDER BY 1""")
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
