"""Heat-load prediction (thermal design) runs in battery_ml.

    python 2026_10_18_heatload.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_18_heatload.py --commit   # run for real

heatload_run             one run: battery systems, window, parameters (envelope, solar, measured reference, forecast,
                         design condition), the calibrated grey-box per system, the summary (closure audit, design
                         sizing, duty curve, forecast scores) and warnings.
heatload_ledger          per-interval heat ledger (hypertable on ts): the component heat terms (battery ohmic /
                         overpotential, battery entropic, PCS, auxiliary electronics, solar, envelope), the stored-heat
                         term, Q_total (nameplate physics), the calibrated model, the measured references and the
                         balance residual.
heatload_forecast_point  forecasts by issue vintage (hypertable on valid_at): actual, persistence, calibrated physics
                         (RC lag) and the hybrid P10 / P50 / P90 per issue time and horizon.
v_heatload_daily         time_bucket('1 day') roll-up of the ledger: daily peaks, means and heat energy.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE TABLE IF NOT EXISTS battery_ml.heatload_run (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_name        text,
    status          text        NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    system_ids      bigint[]    NOT NULL,
    date_from       date        NOT NULL,
    date_to         date        NOT NULL,
    params          jsonb       NOT NULL DEFAULT '{}',
    models          jsonb,
    summary         jsonb,
    warnings        jsonb       NOT NULL DEFAULT '[]',
    error_message   text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    duration_ms     integer
);

CREATE TABLE IF NOT EXISTS battery_ml.heatload_ledger (
    run_id              bigint      NOT NULL REFERENCES battery_ml.heatload_run (run_id) ON DELETE CASCADE,
    system_id           bigint      NOT NULL,
    ts                  timestamptz NOT NULL,
    direction           text        NOT NULL CHECK (direction IN ('CHARGE', 'DISCHARGE', 'IDLE')),
    is_train            boolean     NOT NULL,
    q_batt_irr_kw       numeric(10,4),   -- I·(V - OCV): ohmic + overpotential, always heating
    q_batt_rev_kw       numeric(10,4),   -- I·T·dU/dT: entropic, sign flips with direction
    q_pcs_kw            numeric(10,4),
    q_aux_kw            numeric(10,4),   -- auxiliary electronics inside the enclosure
    q_solar_kw          numeric(10,4),
    q_env_kw            numeric(10,4),   -- UA·(T_amb - T_enclosure)
    q_storage_kw        numeric(10,4),   -- C·dT/dt (heat absorbed by the thermal mass)
    q_total_kw          numeric(10,4),   -- generation + gains (nameplate physics)
    q_model_kw          numeric(10,4),   -- calibrated grey-box
    measured_kw         numeric(10,4),   -- the run's measured reference
    heat_load_sensor_kw numeric(10,4),   -- hvac battery_heat_load_kw
    cooling_kw          numeric(10,4),   -- hvac cooling_capacity_kw (cooling delivered)
    hvac_kw             numeric(10,4),
    residual_kw         numeric(10,4),   -- q_total - q_storage - measured
    t_amb_c             numeric(7,3),
    t_enc_c             numeric(7,3),
    t_cell_max_c        numeric(7,3),
    dt_cell_c           numeric(7,3),
    ghi_wm2             numeric(8,2),
    ghi_source          text,
    PRIMARY KEY (run_id, system_id, ts)
);
SELECT create_hypertable('battery_ml.heatload_ledger', 'ts', if_not_exists => TRUE, migrate_data => TRUE);
CREATE INDEX IF NOT EXISTS ix_heatload_ledger_run ON battery_ml.heatload_ledger (run_id, system_id, ts);

CREATE TABLE IF NOT EXISTS battery_ml.heatload_forecast_point (
    run_id       bigint      NOT NULL REFERENCES battery_ml.heatload_run (run_id) ON DELETE CASCADE,
    system_id    bigint      NOT NULL,
    issued_at    timestamptz NOT NULL,
    horizon_min  integer     NOT NULL,
    valid_at     timestamptz NOT NULL,
    actual_kw    numeric(10,4),
    persistence_kw numeric(10,4),
    physics_kw   numeric(10,4),
    p10_kw       numeric(10,4),
    p50_kw       numeric(10,4),
    p90_kw       numeric(10,4),
    plan_kw      numeric(10,3),       -- planned power at valid_at (+ charge / - discharge)
    PRIMARY KEY (run_id, system_id, issued_at, horizon_min, valid_at)
);
SELECT create_hypertable('battery_ml.heatload_forecast_point', 'valid_at', if_not_exists => TRUE, migrate_data => TRUE);
CREATE INDEX IF NOT EXISTS ix_heatload_fc_run ON battery_ml.heatload_forecast_point (run_id, system_id, horizon_min, valid_at);

CREATE OR REPLACE VIEW battery_ml.v_heatload_daily AS
SELECT run_id, system_id, time_bucket('1 day', ts, 'Asia/Kolkata') AS day,
       count(*)                       AS intervals,
       max(q_total_kw)                AS q_total_peak_kw,
       avg(q_total_kw)                AS q_total_mean_kw,
       max(q_model_kw)                AS q_model_peak_kw,
       max(measured_kw)               AS measured_peak_kw,
       avg(measured_kw)               AS measured_mean_kw,
       sum(q_total_kw) / 12.0         AS q_total_kwh,
       sum(measured_kw) / 12.0        AS measured_kwh,
       avg(q_batt_irr_kw)             AS q_batt_irr_mean_kw,
       avg(q_batt_rev_kw)             AS q_batt_rev_mean_kw,
       avg(q_pcs_kw)                  AS q_pcs_mean_kw,
       avg(q_aux_kw)                  AS q_aux_mean_kw,
       avg(q_solar_kw)                AS q_solar_mean_kw,
       avg(q_env_kw)                  AS q_env_mean_kw,
       avg(residual_kw)               AS residual_mean_kw,
       max(t_amb_c)                   AS t_amb_max_c,
       max(dt_cell_c)                 AS dt_cell_max_c
FROM battery_ml.heatload_ledger
GROUP BY run_id, system_id, time_bucket('1 day', ts, 'Asia/Kolkata');
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                           AND table_name LIKE '%heatload%' ORDER BY 1""")
            print("objects:", [r[0] for r in cur.fetchall()])
        if commit:
            conn.commit()
            print("committed")
        else:
            conn.rollback()
            print("rolled back (rehearsal) - pass --commit to apply")
    finally:
        conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
