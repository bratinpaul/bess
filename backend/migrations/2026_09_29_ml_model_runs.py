"""Create schema battery_ml with the SOH model training registry.

    python 2026_09_29_ml_model_runs.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_29_ml_model_runs.py --commit   # run for real

battery_ml.model_run        one training run: model + parameters, data selection, features, scores
                            (test and train), feature importance, test predictions, artifact, active flag
battery_ml.model_run_curve  the error on the training and validation (test) rows after every boosting round -
                            how the error developed while the model was training
Written by the ML service (ML model/service, /train); read by the frontend's ML Model -> Model Training page.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    "CREATE SCHEMA IF NOT EXISTS battery_ml",
    """CREATE TABLE battery_ml.model_run (
        run_id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_name            text,
        model_type          text        NOT NULL,
        status              text        NOT NULL DEFAULT 'RUNNING',
        params              jsonb       NOT NULL DEFAULT '{}'::jsonb,
        -- data selection
        target              text        NOT NULL DEFAULT 'soh_pct',
        grain               text        NOT NULL,
        date_from           date,
        date_to             date,
        feature_groups      text[]      NOT NULL DEFAULT '{}',
        features            text[]      NOT NULL DEFAULT '{}',
        module_rows_only    boolean     NOT NULL DEFAULT false,
        include_snapshots   boolean     NOT NULL DEFAULT false,
        split_method        text        NOT NULL,
        test_fraction       numeric     NOT NULL,
        random_state        integer     NOT NULL DEFAULT 42,
        -- data actually used
        n_rows              integer,
        n_train             integer,
        n_test              integer,
        train_from          timestamptz,
        train_to            timestamptz,
        test_from           timestamptz,
        test_to             timestamptz,
        target_min          numeric,
        target_max          numeric,
        target_std          numeric,
        -- scores on the test rows
        r2                  numeric,
        mae                 numeric,
        rmse                numeric,
        mape_pct            numeric,
        max_error           numeric,
        median_ae           numeric,
        explained_variance  numeric,
        -- scores on the training rows (to spot over-fitting)
        train_r2            numeric,
        train_mae           numeric,
        train_rmse          numeric,
        iterations          integer,
        best_iteration      integer,
        feature_importance  jsonb,
        feature_ranges      jsonb,
        predictions         jsonb,
        warnings            jsonb       NOT NULL DEFAULT '[]'::jsonb,
        error_message       text,
        artifact_path       text,
        is_active           boolean     NOT NULL DEFAULT false,
        started_at          timestamptz NOT NULL DEFAULT now(),
        finished_at         timestamptz,
        duration_ms         integer,
        CONSTRAINT model_run_type CHECK (model_type IN ('xgboost', 'lightgbm')),
        CONSTRAINT model_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
        CONSTRAINT model_run_grain CHECK (grain IN ('5min', 'hour', 'day')),
        CONSTRAINT model_run_split CHECK (split_method IN ('chronological', 'random')),
        CONSTRAINT model_run_fraction CHECK (test_fraction > 0 AND test_fraction < 1)
    )""",
    # at most one model serves the SOH Estimator
    "CREATE UNIQUE INDEX model_run_one_active ON battery_ml.model_run (is_active) WHERE is_active",
    "CREATE INDEX idx_model_run_started ON battery_ml.model_run (started_at DESC)",
    """CREATE TABLE battery_ml.model_run_curve (
        run_id       bigint  NOT NULL REFERENCES battery_ml.model_run (run_id) ON DELETE CASCADE,
        iteration    integer NOT NULL,
        train_rmse   numeric,
        valid_rmse   numeric,
        train_mae    numeric,
        valid_mae    numeric,
        PRIMARY KEY (run_id, iteration)
    )""",
    "COMMENT ON TABLE battery_ml.model_run IS 'SOH model training runs (XGBoost / LightGBM) with their scores'",
    "COMMENT ON TABLE battery_ml.model_run_curve IS 'Train/validation error per boosting round of a model run'",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml' ORDER BY 1")
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
