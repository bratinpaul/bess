"""SOC estimation / correction runs in battery_ml.

    python 2026_10_09_soc_estimation.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_09_soc_estimation.py --commit   # run for real

soc_estimation_run    one model building run: systems, window, test share, label source (anchors / dense sample
                      truth), EKF settings (tuned or entered), FULL_CHARGE recalibration, LightGBM settings, scores and
                      the results the pages draw. One run can be the estimator's default.
soc_estimation_score  per run, method (coulomb, ocv_lookup, bms, ekf, gbm, hybrid) and scope (anchors / REST_OCV /
                      FULL_CHARGE anchors, dense / flat 25-80 % / under current): RMSE, MAE, bias, max and P95 error,
                      P10-P90 coverage and width, skill vs coulomb counting.
soc_estimation_point  every 5-min row of the run's window with each method's SOC (and bands), the anchor, the dense
                      truth, the EKF bias / gain and recalibrations - for the viewer's timeline.
soc_estimation_state  the live estimator's EKF state per run and system (carried from call to call).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """CREATE TABLE battery_ml.soc_estimation_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'soc_estimation',
        run_name          text,
        status            text        NOT NULL,
        is_default        boolean     NOT NULL DEFAULT false,
        system_ids        bigint[]    NOT NULL,
        date_from         date,
        date_to           date,
        test_fraction     numeric     NOT NULL,
        label_source      text        NOT NULL,
        params            jsonb       NOT NULL DEFAULT '{}',
        n_train_rows      integer,
        n_test_rows       integer,
        n_test_anchors    integer,
        best_method       text,
        primary_scope     text,
        metrics           jsonb,
        results           jsonb,
        warnings          jsonb       NOT NULL DEFAULT '[]',
        error_message     text,
        artifact_path     text,
        started_at        timestamptz NOT NULL DEFAULT now(),
        finished_at       timestamptz,
        duration_ms       integer,
        CONSTRAINT soc_estimation_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
        CONSTRAINT soc_estimation_run_label CHECK (label_source IN ('anchors', 'dense'))
    )""",
    "CREATE UNIQUE INDEX uq_soc_estimation_run_default ON battery_ml.soc_estimation_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.soc_estimation_score (
        run_id        bigint  NOT NULL REFERENCES battery_ml.soc_estimation_run (run_id) ON DELETE CASCADE,
        method        text    NOT NULL,
        scope         text    NOT NULL,
        n             integer,
        rmse          numeric,
        mae           numeric,
        bias          numeric,
        max_error     numeric,
        p95_abs       numeric,
        coverage_pct  numeric,
        width         numeric,
        skill_pct     numeric,
        PRIMARY KEY (run_id, method, scope)
    )""",
    """CREATE TABLE battery_ml.soc_estimation_point (
        run_id         bigint      NOT NULL REFERENCES battery_ml.soc_estimation_run (run_id) ON DELETE CASCADE,
        system_id      bigint      NOT NULL,
        ts             timestamptz NOT NULL,
        is_test        boolean     NOT NULL,
        truth          real,
        anchor         real,
        anchor_method  text,
        coulomb        real,
        ocv_lookup     real,
        bms            real,
        ekf            real,
        ekf_p10        real,
        ekf_p90        real,
        gbm            real,
        gbm_p10        real,
        gbm_p90        real,
        hybrid         real,
        hybrid_p10     real,
        hybrid_p90     real,
        ekf_bias       real,
        ekf_gain       real,
        recal_kind     text,
        at_rest        boolean,
        PRIMARY KEY (run_id, system_id, ts)
    )""",
    """CREATE TABLE battery_ml.soc_estimation_state (
        run_id      bigint      NOT NULL REFERENCES battery_ml.soc_estimation_run (run_id) ON DELETE CASCADE,
        system_id   bigint      NOT NULL,
        state_ts    timestamptz NOT NULL,
        state       jsonb       NOT NULL,
        updated_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (run_id, system_id)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'soc_estimation%' ORDER BY 1""")
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
