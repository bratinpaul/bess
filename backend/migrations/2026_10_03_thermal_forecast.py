"""Temperature forecasting: the thermal feature view on the hypertables and the forecast runs in battery_ml.

    python 2026_10_03_thermal_forecast.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_03_thermal_forecast.py --commit   # run for real (then materialises the aggregates)

battery_telemetry.system_thermal_15m / pcs_thermal_15m / hvac_thermal_15m
    continuous aggregates (15-min buckets) of the thermal signals per asset: max / avg of the temperatures, mean
    |power|, apparent power, HVAC power - refreshed every 15 min by a policy.
battery_telemetry.v_thermal_rolling_1h
    per battery system and 15-min bucket: the max / mean over the last four buckets (1 h) of the three aggregates.
battery_master.v_thermal_assets
    battery system -> its PCS, HVAC unit and EMS (the first of each).
battery_telemetry.v_thermal_features
    one row per battery system and 5-min reading: BMS (cell temps, power, C-rate, ambient, coolant), PCS (IGBT,
    heatsink, inlet coolant, AC / DC power), HVAC (mode, compressor, flow, supply / return / enclosure temp, HVAC power),
    EMS (setpoint, mode, grid service) and the rolling 1 h features of the last completed 15-min bucket (no look-ahead).
battery_ml.thermal_forecast_run / _score / _point
    model building runs, scores per target / horizon / method, and backtest forecasts for the viewer.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

CAGGS = {
    "system_thermal_15m": """
        CREATE MATERIALIZED VIEW battery_telemetry.system_thermal_15m WITH (timescaledb.continuous) AS
        SELECT system_id, time_bucket('15 minutes'::interval, ts) AS bucket,
               max(cell_temp_max_c) AS cell_max_c, avg(cell_temp_max_c) AS cell_max_avg_c,
               avg(abs(power_kw)) AS power_abs_kw, avg(abs(c_rate)) AS c_rate_abs, avg(ambient_temp_c) AS ambient_c,
               count(*) AS n
        FROM battery_telemetry.system_telemetry
        GROUP BY system_id, time_bucket('15 minutes'::interval, ts)
        WITH NO DATA""",
    "pcs_thermal_15m": """
        CREATE MATERIALIZED VIEW battery_telemetry.pcs_thermal_15m WITH (timescaledb.continuous) AS
        SELECT pcs_id, time_bucket('15 minutes'::interval, ts) AS bucket,
               max(igbt_temp_c) AS igbt_max_c, avg(igbt_temp_c) AS igbt_avg_c, max(heatsink_temp_c) AS heatsink_max_c,
               avg(abs(ac_active_power_kw)) AS ac_abs_kw, avg(ac_apparent_power_kva) AS apparent_kva, count(*) AS n
        FROM battery_telemetry.pcs_telemetry
        GROUP BY pcs_id, time_bucket('15 minutes'::interval, ts)
        WITH NO DATA""",
    "hvac_thermal_15m": """
        CREATE MATERIALIZED VIEW battery_telemetry.hvac_thermal_15m WITH (timescaledb.continuous) AS
        SELECT hvac_id, time_bucket('15 minutes'::interval, ts) AS bucket,
               max(coolant_return_temp_c) AS coolant_return_max_c, avg(coolant_return_temp_c) AS coolant_return_avg_c,
               max(enclosure_temp_c) AS enclosure_max_c, avg(hvac_power_kw) AS hvac_power_kw,
               avg(compressor_speed_pct) AS compressor_pct, count(*) AS n
        FROM battery_telemetry.hvac_telemetry
        GROUP BY hvac_id, time_bucket('15 minutes'::interval, ts)
        WITH NO DATA""",
}

VIEWS = [
    """CREATE VIEW battery_master.v_thermal_assets AS
    SELECT bs.battery_system_id,
           (SELECT min(p.pcs_id) FROM battery_master.pcs p WHERE p.system_id = bs.battery_system_id) AS pcs_id,
           (SELECT min(h.hvac_id) FROM battery_master.hvac_unit h WHERE h.battery_system_id = bs.battery_system_id) AS hvac_id,
           (SELECT min(e.ems_id) FROM battery_master.ems_controller e WHERE e.battery_system_id = bs.battery_system_id) AS ems_id
    FROM battery_master.battery_system bs""",
    """CREATE VIEW battery_telemetry.v_thermal_rolling_1h AS
    SELECT a.battery_system_id, s.bucket,
           max(s.cell_max_c) OVER w AS cell_max_1h_c, avg(s.power_abs_kw) OVER w AS power_abs_1h_kw,
           avg(s.c_rate_abs) OVER w AS c_rate_abs_1h,
           max(p.igbt_max_c) OVER w AS igbt_max_1h_c, avg(p.apparent_kva) OVER w AS apparent_1h_kva,
           max(h.coolant_return_max_c) OVER w AS coolant_return_max_1h_c, max(h.enclosure_max_c) OVER w AS enclosure_max_1h_c,
           avg(h.hvac_power_kw) OVER w AS hvac_power_1h_kw
    FROM battery_master.v_thermal_assets a
    JOIN battery_telemetry.system_thermal_15m s ON s.system_id = a.battery_system_id
    LEFT JOIN battery_telemetry.pcs_thermal_15m p ON p.pcs_id = a.pcs_id AND p.bucket = s.bucket
    LEFT JOIN battery_telemetry.hvac_thermal_15m h ON h.hvac_id = a.hvac_id AND h.bucket = s.bucket
    WINDOW w AS (PARTITION BY a.battery_system_id ORDER BY s.bucket ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)""",
    """CREATE VIEW battery_telemetry.v_thermal_features AS
    SELECT s.ts, a.battery_system_id, a.pcs_id, a.hvac_id, a.ems_id,
           s.cell_temp_max_c, s.cell_temp_avg_c, s.cell_temp_min_c, s.power_kw, s.c_rate, s.soc_pct,
           s.ambient_temp_c, s.coolant_temp_c AS bms_coolant_temp_c,
           p.igbt_temp_c, p.heatsink_temp_c, p.inlet_coolant_temp_c, p.ac_active_power_kw, p.ac_apparent_power_kva,
           p.dc_power_kw, p.mode_code AS pcs_mode,
           h.cooling_mode, h.compressor_speed_pct, h.coolant_flow_lpm, h.coolant_setpoint_c, h.coolant_supply_temp_c,
           h.coolant_return_temp_c, h.hvac_power_kw, h.enclosure_temp_c, h.battery_heat_load_kw,
           e.p_setpoint_kw, e.dispatch_mode, e.grid_service,
           r.cell_max_1h_c, r.power_abs_1h_kw, r.c_rate_abs_1h, r.igbt_max_1h_c, r.apparent_1h_kva,
           r.coolant_return_max_1h_c, r.enclosure_max_1h_c, r.hvac_power_1h_kw
    FROM battery_telemetry.system_telemetry s
    JOIN battery_master.v_thermal_assets a ON a.battery_system_id = s.system_id
    LEFT JOIN battery_telemetry.pcs_telemetry p ON p.pcs_id = a.pcs_id AND p.ts = s.ts
    LEFT JOIN battery_telemetry.hvac_telemetry h ON h.hvac_id = a.hvac_id AND h.ts = s.ts
    LEFT JOIN battery_telemetry.ems_telemetry e ON e.ems_id = a.ems_id AND e.ts = s.ts
    -- the last completed 15-min bucket: no look-ahead into the current one
    LEFT JOIN battery_telemetry.v_thermal_rolling_1h r
           ON r.battery_system_id = s.system_id
          AND r.bucket = time_bucket('15 minutes'::interval, s.ts) - interval '15 minutes'""",
]

TABLES = [
    """CREATE TABLE battery_ml.thermal_forecast_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'thermal_forecast',
        run_name          text,
        status            text        NOT NULL,
        is_default        boolean     NOT NULL DEFAULT false,
        system_ids        bigint[]    NOT NULL,
        date_from         date,
        date_to           date,
        targets           text[]      NOT NULL,
        horizons_min      integer[]   NOT NULL,
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
        CONSTRAINT thermal_forecast_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
    )""",
    "CREATE UNIQUE INDEX uq_thermal_forecast_run_default ON battery_ml.thermal_forecast_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.thermal_forecast_score (
        run_id        bigint   NOT NULL REFERENCES battery_ml.thermal_forecast_run (run_id) ON DELETE CASCADE,
        target        text     NOT NULL,
        horizon_min   integer  NOT NULL,
        method        text     NOT NULL,
        n             integer,
        mae           numeric,
        rmse          numeric,
        pinball       numeric,
        coverage_pct  numeric,
        threshold_c   numeric,
        events        integer,
        recall_p50    numeric,
        precision_p50 numeric,
        recall_p90    numeric,
        precision_p90 numeric,
        PRIMARY KEY (run_id, target, horizon_min, method)
    )""",
    """CREATE TABLE battery_ml.thermal_forecast_point (
        run_id       bigint      NOT NULL REFERENCES battery_ml.thermal_forecast_run (run_id) ON DELETE CASCADE,
        target       text        NOT NULL,
        system_id    bigint      NOT NULL,
        origin_ts    timestamptz NOT NULL,
        horizon_min  smallint    NOT NULL,
        method       text        NOT NULL,
        p10          real,
        p50          real,
        p90          real,
        actual       real,
        now_c        real,
        PRIMARY KEY (run_id, target, system_id, origin_ts, horizon_min, method)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in [*CAGGS.values(), *VIEWS, *TABLES]:
        cur.execute(sql)
    cur.execute("""SELECT view_name FROM timescaledb_information.continuous_aggregates
                   WHERE view_name LIKE '%thermal_15m' ORDER BY 1""")
    print("   aggregates:", [r[0] for r in cur.fetchall()])
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'thermal_forecast%' ORDER BY 1""")
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
    cur.execute("SELECT count(*), count(cell_max_1h_c), count(igbt_temp_c), count(coolant_return_temp_c) FROM battery_telemetry.v_thermal_features")
    print("   v_thermal_features rows / with rolling / with IGBT / with coolant:", cur.fetchone())
    conn.close()
    print("COMMITTED")


if __name__ == "__main__":
    main("--commit" in sys.argv)
