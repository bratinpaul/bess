"""Electricity-price forecasting: TOU tariff bands in battery_master and forecast runs in battery_ml.

    python 2026_10_02_price_forecast.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_02_price_forecast.py --commit   # run for real

battery_master.ems_tariff_period  time-of-use bands: hour window [start_hour, end_hour), day type, season, validity;
                                  ems_id NULL = every EMS. Seeded with the six bands of the sample market price
                                  (hourly profile of ems_telemetry.market_price_mwh, Aug-Sep 2026).
battery_ml.price_forecast_run     one model generation run: EMS units, window, horizon, features, the models and their
                                  parameters, scores and the results the viewer draws.
battery_ml.price_forecast_score   per run, model and metric family: MAE / RMSE / sMAPE, pinball loss, P10-P90
                                  coverage and width, skill vs seasonal naive, spike metrics, spread capture.
battery_ml.price_forecast_point   backtest forecasts per origin, target hour and model (P10 / P50 / P90, mean,
                                  spike probability) with the actual price - for the results viewer.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

BANDS = [
    # code, name, level, start, end, observed mean $/MWh
    ("NIGHT", "Night off-peak", "OFF_PEAK", 0, 6, 23.3),
    ("MORNING", "Morning shoulder", "SHOULDER", 6, 9, 42.4),
    ("SOLAR", "Midday solar trough", "SUPER_OFF_PEAK", 9, 15, 16.2),
    ("RAMP", "Afternoon ramp", "SHOULDER_HIGH", 15, 17, 53.6),
    ("PEAK", "Evening peak", "PEAK", 17, 22, 100.6),
    ("LATE", "Late evening shoulder", "SHOULDER", 22, 24, 37.1),
]

STEPS = [
    """CREATE TABLE battery_master.ems_tariff_period (
        tariff_period_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        ems_id            bigint REFERENCES battery_master.ems_controller (ems_id) ON DELETE CASCADE,
        band_code         text     NOT NULL,
        band_name         text     NOT NULL,
        price_level       text     NOT NULL,
        start_hour        smallint NOT NULL,
        end_hour          smallint NOT NULL,
        day_type          text     NOT NULL DEFAULT 'ALL',
        season            text     NOT NULL DEFAULT 'ALL',
        reference_price_mwh numeric,
        valid_from        date,
        valid_to          date,
        note              text,
        created_at        timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ems_tariff_hours CHECK (start_hour BETWEEN 0 AND 23 AND end_hour BETWEEN 1 AND 24 AND end_hour > start_hour),
        CONSTRAINT ems_tariff_day_type CHECK (day_type IN ('ALL', 'WEEKDAY', 'WEEKEND')),
        CONSTRAINT ems_tariff_level CHECK (price_level IN ('SUPER_OFF_PEAK', 'OFF_PEAK', 'SHOULDER', 'SHOULDER_HIGH', 'PEAK'))
    )""",
    *[f"""INSERT INTO battery_master.ems_tariff_period (band_code, band_name, price_level, start_hour, end_hour,
            reference_price_mwh, note)
         VALUES ('{c}', '{n}', '{lv}', {s}, {e}, {p}, 'Seeded from the sample market price profile (Aug-Sep 2026)')"""
      for c, n, lv, s, e, p in BANDS],
    """CREATE TABLE battery_ml.price_forecast_run (
        run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case        text        NOT NULL DEFAULT 'price_forecast',
        run_name        text,
        status          text        NOT NULL,
        is_default      boolean     NOT NULL DEFAULT false,
        ems_ids         bigint[]    NOT NULL,
        date_from       date,
        date_to         date,
        resolution      text        NOT NULL DEFAULT 'hour',
        horizon_hours   integer     NOT NULL,
        test_fraction   numeric     NOT NULL,
        origin_step_h   integer     NOT NULL,
        feature_groups  text[]      NOT NULL,
        models          text[]      NOT NULL,
        params          jsonb       NOT NULL DEFAULT '{}',
        n_hours         integer,
        n_train_rows    integer,
        n_test_origins  integer,
        n_spikes        integer,
        best_model      text,
        metrics         jsonb,
        results         jsonb,
        warnings        jsonb       NOT NULL DEFAULT '[]',
        error_message   text,
        artifact_path   text,
        started_at      timestamptz NOT NULL DEFAULT now(),
        finished_at     timestamptz,
        duration_ms     integer,
        CONSTRAINT price_forecast_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
        CONSTRAINT price_forecast_run_resolution CHECK (resolution IN ('hour', '5min'))
    )""",
    "CREATE UNIQUE INDEX uq_price_forecast_run_default ON battery_ml.price_forecast_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.price_forecast_score (
        run_id        bigint  NOT NULL REFERENCES battery_ml.price_forecast_run (run_id) ON DELETE CASCADE,
        model         text    NOT NULL,
        n             integer,
        mae           numeric,
        rmse          numeric,
        smape_pct     numeric,
        pinball       numeric,
        coverage_pct  numeric,
        width_mwh     numeric,
        skill_mae_pct numeric,
        peak_mae      numeric,
        spike_recall  numeric,
        spike_precision numeric,
        spike_brier   numeric,
        spread_capture_pct numeric,
        PRIMARY KEY (run_id, model)
    )""",
    """CREATE TABLE battery_ml.price_forecast_point (
        run_id      bigint      NOT NULL REFERENCES battery_ml.price_forecast_run (run_id) ON DELETE CASCADE,
        ems_id      bigint      NOT NULL,
        origin_ts   timestamptz NOT NULL,
        target_ts   timestamptz NOT NULL,
        horizon_h   smallint    NOT NULL,
        model       text        NOT NULL,
        p10         real,
        p50         real,
        p90         real,
        mean        real,
        spike_prob  real,
        actual      real,
        PRIMARY KEY (run_id, ems_id, origin_ts, model, horizon_h)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("SELECT band_code, start_hour, end_hour FROM battery_master.ems_tariff_period ORDER BY start_hour")
    print("   bands:", cur.fetchall())
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'price_forecast%' ORDER BY 1""")
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
