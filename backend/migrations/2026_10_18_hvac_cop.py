"""HVAC COP & cooling-performance runs in battery_ml.

    python 2026_10_18_hvac_cop.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_18_hvac_cop.py --commit   # run for real

hvac_cop_run    one run: HVAC units, window, parameters (COP / capacity definition, steady-state filter, approach
                temperatures, coolant properties, reference conditions, control limits), the fitted performance maps
                per unit (COP / CAP biquadratics, part-load curve, Carnot-anchored eta_2nd_law, GBM residual), the
                scorecard, closure audit, daily trend with control charts, setpoint sensitivities and warnings.
hvac_cop_point  per-interval view (hypertable on ts): measured COP three ways, expected COP per model, the residual,
                eta_2nd_law, Carnot COP, lift, part-load ratio, capacity actual / expected, Q_cool from flow x dT,
                power actual / expected, the condenser-balance closure and the steady-state flag.
v_hvac_cop_daily time_bucket('1 day') roll-up of the points: weighted COP, kW/ton, mean residual and eta_2nd_law.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE TABLE IF NOT EXISTS battery_ml.hvac_cop_run (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_name        text,
    status          text        NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    hvac_ids        bigint[]    NOT NULL,
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

CREATE TABLE IF NOT EXISTS battery_ml.hvac_cop_point (
    run_id          bigint      NOT NULL REFERENCES battery_ml.hvac_cop_run (run_id) ON DELETE CASCADE,
    hvac_id         bigint      NOT NULL,
    ts              timestamptz NOT NULL,
    mode            text,
    steady          boolean     NOT NULL,
    is_train        boolean     NOT NULL,
    cop_actual      numeric(8,4),     -- the run's COP definition
    cop_logged      numeric(8,4),
    cop_ratio       numeric(8,4),     -- cooling_capacity_kw / hvac_power_kw
    cop_loop        numeric(8,4),     -- flow x rho x cp x dT / hvac_power_kw
    cop_map         numeric(8,4),
    cop_grey        numeric(8,4),
    cop_hybrid      numeric(8,4),
    cop_expected    numeric(8,4),     -- the monitoring baseline (performance map)
    cop_residual    numeric(8,4),     -- actual - expected
    eta_2nd_law     numeric(8,5),
    cop_carnot      numeric(9,4),
    lift_k          numeric(8,3),
    plr             numeric(7,4),
    cap_actual_kw   numeric(10,3),
    cap_expected_kw numeric(10,3),
    q_dt_kw         numeric(10,3),    -- cooling from the coolant loop (independent)
    power_kw        numeric(10,3),
    power_expected_kw numeric(10,3),
    rej_closure_kw  numeric(10,3),    -- heat_rejected - (cooling + power)
    t_amb_c         numeric(7,3),
    t_supply_c      numeric(7,3),
    PRIMARY KEY (run_id, hvac_id, ts)
);
SELECT create_hypertable('battery_ml.hvac_cop_point', 'ts', if_not_exists => TRUE, migrate_data => TRUE);
CREATE INDEX IF NOT EXISTS ix_hvac_cop_point_run ON battery_ml.hvac_cop_point (run_id, hvac_id, ts);

CREATE OR REPLACE VIEW battery_ml.v_hvac_cop_daily AS
SELECT run_id, hvac_id, time_bucket('1 day', ts, 'Asia/Kolkata') AS day,
       count(*) FILTER (WHERE mode = 'COOLING')                       AS cooling_intervals,
       count(*) FILTER (WHERE steady)                                 AS steady_intervals,
       sum(cap_actual_kw) FILTER (WHERE mode = 'COOLING') / NULLIF(sum(power_kw) FILTER (WHERE mode = 'COOLING'), 0)
                                                                      AS weighted_cop,
       sum(power_kw) FILTER (WHERE mode = 'COOLING') / NULLIF(sum(cap_actual_kw) FILTER (WHERE mode = 'COOLING') / 3.517, 0)
                                                                      AS kw_per_ton,
       avg(cop_residual) FILTER (WHERE steady)                        AS residual_mean,
       avg(eta_2nd_law) FILTER (WHERE steady)                         AS eta_2nd_law_mean,
       avg(cop_actual) FILTER (WHERE steady)                          AS cop_mean,
       avg(cop_expected) FILTER (WHERE steady)                        AS cop_expected_mean,
       max(t_amb_c)                                                   AS t_amb_max_c
FROM battery_ml.hvac_cop_point
GROUP BY run_id, hvac_id, time_bucket('1 day', ts, 'Asia/Kolkata');
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                           AND table_name LIKE '%hvac_cop%' ORDER BY 1""")
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
