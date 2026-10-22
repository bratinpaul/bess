"""Auxiliary / HVAC energy forecasting: the aux feature view on the hypertables and the forecast runs in battery_ml.

    python 2026_10_06_aux_forecast.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_06_aux_forecast.py --commit   # run for real (then materialises the aggregate)

battery_telemetry.ems_aux_15m
    continuous aggregate (15-min buckets) of the EMS auxiliary load per EMS: mean / max aux_load_kw - refreshed every
    15 min by a policy. HVAC power per 15 min comes from the existing hvac_thermal_15m.
battery_telemetry.v_aux_rolling
    per EMS and 15-min bucket: mean aux over the last 1 h / 3 h, max aux over 1 h and mean HVAC power over 1 h.
battery_telemetry.v_aux_features
    one row per EMS and 5-min reading - the site's parasitic draw and its drivers:
      EMS     aux_load_kw / aux_load_pct (target; always a positive consumption), setpoint, dispatch mode, service
      HVAC    hvac_power_kw, cooling mode, COP, setpoint, compressor, coolant return, enclosure temp / humidity,
              battery heat load, cooling capacity, ambient
      BMS     power, C-rate, max cell temperature (and its ambient when the HVAC has none)
      PCS     apparent power
      rolling the features of the last completed 15-min bucket (no look-ahead into the current one)
    plus the site and its weather station (for the ambient forecast in weather_forecast).
battery_ml.aux_forecast_run / _score / _point / _daily
    model building runs, scores per site / horizon bucket / method, backtest forecasts for the viewer and the daily
    aux-energy (kWh) backtest.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

CAGGS = {
    "ems_aux_15m": """
        CREATE MATERIALIZED VIEW battery_telemetry.ems_aux_15m WITH (timescaledb.continuous) AS
        SELECT ems_id, time_bucket('15 minutes'::interval, ts) AS bucket,
               avg(aux_load_kw) AS aux_avg_kw, max(aux_load_kw) AS aux_max_kw, count(*) AS n
        FROM battery_telemetry.ems_telemetry
        GROUP BY ems_id, time_bucket('15 minutes'::interval, ts)
        WITH NO DATA""",
}

VIEWS = [
    """CREATE VIEW battery_telemetry.v_aux_rolling AS
    SELECT x.ems_id, x.bucket,
           avg(x.aux_avg_kw) OVER w1 AS aux_1h_kw, max(x.aux_max_kw) OVER w1 AS aux_max_1h_kw,
           avg(x.aux_avg_kw) OVER w3 AS aux_3h_kw, avg(h.hvac_power_kw) OVER w1 AS hvac_1h_kw
    FROM battery_telemetry.ems_aux_15m x
    JOIN battery_master.ems_controller ec ON ec.ems_id = x.ems_id
    LEFT JOIN battery_master.v_thermal_assets a ON a.battery_system_id = ec.battery_system_id
    LEFT JOIN battery_telemetry.hvac_thermal_15m h ON h.hvac_id = a.hvac_id AND h.bucket = x.bucket
    WINDOW w1 AS (PARTITION BY x.ems_id ORDER BY x.bucket ROWS BETWEEN 3 PRECEDING AND CURRENT ROW),
           w3 AS (PARTITION BY x.ems_id ORDER BY x.bucket ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)""",
    """CREATE VIEW battery_telemetry.v_aux_features AS
    SELECT e.ts, e.ems_id, bs.site_id, ec.battery_system_id, a.pcs_id, a.hvac_id,
           (SELECT min(w.station_id) FROM battery_master.weather_station w WHERE w.site_id = bs.site_id) AS station_id,
           e.aux_load_kw, e.aux_load_pct, e.p_setpoint_kw, e.dispatch_mode, e.grid_service,
           h.hvac_power_kw, h.cooling_mode, h.cop, h.coolant_setpoint_c, h.compressor_speed_pct, h.condenser_fan_pct,
           h.coolant_return_temp_c, h.enclosure_temp_c, h.enclosure_humidity_pct, h.battery_heat_load_kw,
           h.cooling_capacity_kw, COALESCE(h.ambient_temp_c, s.ambient_temp_c) AS ambient_temp_c,
           s.power_kw, s.c_rate, s.cell_temp_max_c, p.ac_apparent_power_kva,
           r.aux_1h_kw, r.aux_max_1h_kw, r.aux_3h_kw, r.hvac_1h_kw
    FROM battery_telemetry.ems_telemetry e
    JOIN battery_master.ems_controller ec ON ec.ems_id = e.ems_id
    JOIN battery_master.battery_system bs ON bs.battery_system_id = ec.battery_system_id
    LEFT JOIN battery_master.v_thermal_assets a ON a.battery_system_id = ec.battery_system_id
    LEFT JOIN battery_telemetry.hvac_telemetry h ON h.hvac_id = a.hvac_id AND h.ts = e.ts
    LEFT JOIN battery_telemetry.system_telemetry s ON s.system_id = ec.battery_system_id AND s.ts = e.ts
    LEFT JOIN battery_telemetry.pcs_telemetry p ON p.pcs_id = a.pcs_id AND p.ts = e.ts
    -- the last completed 15-min bucket: no look-ahead into the current one
    LEFT JOIN battery_telemetry.v_aux_rolling r
           ON r.ems_id = e.ems_id AND r.bucket = time_bucket('15 minutes'::interval, e.ts) - interval '15 minutes'""",
]

TABLES = [
    """CREATE TABLE battery_ml.aux_forecast_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'aux_forecast',
        run_name          text,
        status            text        NOT NULL,
        is_default        boolean     NOT NULL DEFAULT false,
        ems_ids           bigint[]    NOT NULL,
        date_from         date,
        date_to           date,
        horizon_hours     integer     NOT NULL,
        test_fraction     numeric     NOT NULL,
        params            jsonb       NOT NULL DEFAULT '{}',
        n_train_rows      integer,
        n_test_rows       integer,
        metrics           jsonb,
        results           jsonb,
        warnings          jsonb       NOT NULL DEFAULT '[]',
        error_message     text,
        artifact_path     text,
        started_at        timestamptz NOT NULL DEFAULT now(),
        finished_at       timestamptz,
        duration_ms       integer,
        CONSTRAINT aux_forecast_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
    )""",
    "CREATE UNIQUE INDEX uq_aux_forecast_run_default ON battery_ml.aux_forecast_run (use_case) WHERE is_default",
    # ems_id 0 = all sites of the run together
    """CREATE TABLE battery_ml.aux_forecast_score (
        run_id        bigint   NOT NULL REFERENCES battery_ml.aux_forecast_run (run_id) ON DELETE CASCADE,
        ems_id        bigint   NOT NULL,
        horizon_bucket text    NOT NULL,
        method        text     NOT NULL,
        n             integer,
        mae           numeric,
        rmse          numeric,
        pinball       numeric,
        coverage_pct  numeric,
        bias          numeric,
        PRIMARY KEY (run_id, ems_id, horizon_bucket, method)
    )""",
    """CREATE TABLE battery_ml.aux_forecast_point (
        run_id       bigint      NOT NULL REFERENCES battery_ml.aux_forecast_run (run_id) ON DELETE CASCADE,
        ems_id       bigint      NOT NULL,
        origin_ts    timestamptz NOT NULL,
        horizon_min  smallint    NOT NULL,
        method       text        NOT NULL,
        p10          real,
        p50          real,
        p90          real,
        actual       real,
        PRIMARY KEY (run_id, ems_id, origin_ts, horizon_min, method)
    )""",
    """CREATE TABLE battery_ml.aux_forecast_daily (
        run_id       bigint   NOT NULL REFERENCES battery_ml.aux_forecast_run (run_id) ON DELETE CASCADE,
        ems_id       bigint   NOT NULL,
        day          date     NOT NULL,
        method       text     NOT NULL,
        actual_kwh   numeric,
        p10_kwh      numeric,
        p50_kwh      numeric,
        p90_kwh      numeric,
        PRIMARY KEY (run_id, ems_id, day, method)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in [*CAGGS.values(), *VIEWS, *TABLES]:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'aux_forecast%' ORDER BY 1""")
    print("   tables:", [r[0] for r in cur.fetchall()])
    if not commit:
        conn.rollback()
        conn.close()
        print("rehearsal OK - rolled back (run with --commit)")
        return
    conn.commit()
    # materialise and keep fresh (outside a transaction block)
    conn.autocommit = True
    for name in CAGGS:
        cur.execute(f"CALL refresh_continuous_aggregate('battery_telemetry.{name}', NULL, NULL)")
        cur.execute(f"""SELECT add_continuous_aggregate_policy('battery_telemetry.{name}',
                        start_offset => INTERVAL '3 days', end_offset => INTERVAL '15 minutes',
                        schedule_interval => INTERVAL '15 minutes')""")
        cur.execute(f"SELECT count(*) FROM battery_telemetry.{name}")
        print(f"   {name}: {cur.fetchone()[0]} buckets")
    cur.execute("""SELECT ems_id, count(*), count(hvac_power_kw), count(aux_1h_kw), count(power_kw), max(station_id)
                   FROM battery_telemetry.v_aux_features GROUP BY 1 ORDER BY 1""")
    print("   v_aux_features per EMS (rows / HVAC / rolling / BMS / station):", cur.fetchall())
    conn.close()
    print("COMMITTED")


if __name__ == "__main__":
    main("--commit" in sys.argv)
