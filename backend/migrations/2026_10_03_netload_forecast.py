"""Net-load & demand / peak forecasting runs in battery_ml.

    python 2026_10_03_netload_forecast.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_03_netload_forecast.py --commit   # run for real

battery_ml.netload_forecast_run    one model generation run: metering points, window, horizon, features, weather
                                   source, peak threshold, the models and their parameters, scores and the results the
                                   pages draw.
battery_ml.netload_forecast_score  per run and model: MAE / RMSE / MAPE / bias, pinball loss, P10-P90 coverage and
                                   width, skill vs seasonal naive, billing-window MAE, and the daily-peak scores (peak
                                   MAE, timing error, exceedance Brier / AUC / recall / precision).
battery_ml.netload_forecast_point  backtest forecasts per origin, 5-min target and model (P10 / P50 / P90) with the
                                   actual net load - for the viewer.
battery_ml.netload_forecast_peak   backtest daily billing-window peaks per origin, target day and model: forecast peak
                                   P10 / P50 / P90, its time, exceedance probability, and the actual peak and time.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """CREATE TABLE battery_ml.netload_forecast_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'netload_forecast',
        run_name          text,
        status            text        NOT NULL,
        is_default        boolean     NOT NULL DEFAULT false,
        mp_ids            bigint[]    NOT NULL,
        date_from         date,
        date_to           date,
        horizon_hours     integer     NOT NULL,
        test_fraction     numeric     NOT NULL,
        origin_step_h     integer     NOT NULL,
        feature_groups    text[]      NOT NULL,
        weather_source    text        NOT NULL DEFAULT 'forecast',
        peak_threshold_kw numeric,
        models            text[]      NOT NULL,
        params            jsonb       NOT NULL DEFAULT '{}',
        n_readings        integer,
        n_train_rows      integer,
        n_test_origins    integer,
        n_test_days       integer,
        best_model        text,
        metrics           jsonb,
        results           jsonb,
        warnings          jsonb       NOT NULL DEFAULT '[]',
        error_message     text,
        artifact_path     text,
        started_at        timestamptz NOT NULL DEFAULT now(),
        finished_at       timestamptz,
        duration_ms       integer,
        CONSTRAINT netload_forecast_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
        CONSTRAINT netload_forecast_run_weather CHECK (weather_source IN ('forecast', 'actual'))
    )""",
    "CREATE UNIQUE INDEX uq_netload_forecast_run_default ON battery_ml.netload_forecast_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.netload_forecast_score (
        run_id            bigint  NOT NULL REFERENCES battery_ml.netload_forecast_run (run_id) ON DELETE CASCADE,
        model             text    NOT NULL,
        n                 integer,
        mae               numeric,
        rmse              numeric,
        mape_pct          numeric,
        bias              numeric,
        pinball           numeric,
        coverage_pct      numeric,
        width_kw          numeric,
        skill_mae_pct     numeric,
        window_mae        numeric,
        peak_mae_kw       numeric,
        peak_bias_kw      numeric,
        peak_time_mae_min numeric,
        exceed_brier      numeric,
        exceed_auc        numeric,
        exceed_recall     numeric,
        exceed_precision  numeric,
        PRIMARY KEY (run_id, model)
    )""",
    """CREATE TABLE battery_ml.netload_forecast_point (
        run_id      bigint      NOT NULL REFERENCES battery_ml.netload_forecast_run (run_id) ON DELETE CASCADE,
        mp_id       bigint      NOT NULL,
        origin_ts   timestamptz NOT NULL,
        target_ts   timestamptz NOT NULL,
        step        smallint    NOT NULL,
        model       text        NOT NULL,
        p10         real,
        p50         real,
        p90         real,
        actual      real,
        PRIMARY KEY (run_id, mp_id, origin_ts, model, step)
    )""",
    """CREATE TABLE battery_ml.netload_forecast_peak (
        run_id       bigint      NOT NULL REFERENCES battery_ml.netload_forecast_run (run_id) ON DELETE CASCADE,
        mp_id        bigint      NOT NULL,
        origin_ts    timestamptz NOT NULL,
        target_date  date        NOT NULL,
        model        text        NOT NULL,
        lead_h       real,
        p10          real,
        p50          real,
        p90          real,
        peak_ts      timestamptz,
        prob_exceed  real,
        actual       real,
        actual_ts    timestamptz,
        threshold_kw real,
        PRIMARY KEY (run_id, mp_id, origin_ts, target_date, model)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'battery_ml' AND table_name LIKE 'netload_forecast%' ORDER BY 1""")
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
