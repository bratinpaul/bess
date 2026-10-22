"""Groundwork for the energy-arbitrage optimizer (ML use case `arbitrage`) and its result viewer.

    python 2026_10_15_arbitrage_optimizer.py            # rehearsal: apply, verify, ROLLBACK
    python 2026_10_15_arbitrage_optimizer.py --commit   # for real

1. grid_charge was empty: the data pack seeds it against site_code 'SITE-01', which does not exist here (same as
   price_node). Seed the pack's four charges for Bhadla (site 8, where the arbitrage data lives since 2026-10-15).
   Checked against dispatch_outcome row by row: grid_cost = 1.80 $/MWh x |energy| + 2.50 $/MWh x import
   + 0.05 x |price x energy|  (reproduces the pack's $669.05).
2. battery_ml.arb_study: one optimizer study (a backtest over a date range with one set of parameters).
3. optimization_run.study_id: the daily runs a study writes into the decision chain (optimization_run ->
   decision_state -> dispatch_schedule); the pack's own runs keep NULL.
4. battery_ml.arb_study_day: per day of a study - expected vs realized vs oracle profit, energy, cycles, checks.
5. battery_ml.arb_backtest: per 15-min interval - the simulated execution of the policy (settled at rt_price) and
   the perfect-foresight oracle. dispatch_outcome cannot hold these (one row per system and interval).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
INSERT INTO battery_master.grid_charge (site_id, charge_type, applies_to, rate, unit, valid_from, description)
SELECT s.site_id, x.ct, x.ap, x.rate, x.unit, DATE '2026-01-01', x.descr
FROM battery_master.site s,
     (VALUES ('WHEELING', 'BOTH', 1.80, '$/MWh', 'Transmission/wheeling charge on throughput'),
             ('IMPORT_DUTY', 'IMPORT', 2.50, '$/MWh', 'Duty/cross-subsidy surcharge on grid import'),
             ('TAX', 'BOTH', 0.05, 'fraction', 'Electricity tax on gross energy value'),
             ('DEMAND', 'PEAK_DEMAND', 9.00, '$/kW-month', 'Demand charge on monthly billing peak'))
         AS x(ct, ap, rate, unit, descr)
WHERE s.site_code = 'BHADLA-BESS-SITE'
  AND NOT EXISTS (SELECT 1 FROM battery_master.grid_charge g WHERE g.site_id = s.site_id AND g.charge_type = x.ct);

CREATE TABLE IF NOT EXISTS battery_ml.arb_study (
    study_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    study_name     text,
    status         text NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    system_id      bigint NOT NULL REFERENCES battery_master.battery_system (battery_system_id) ON DELETE CASCADE,
    node_id        bigint NOT NULL REFERENCES battery_master.price_node (node_id) ON DELETE CASCADE,
    date_from      date NOT NULL,
    date_to        date NOT NULL,
    mode           text NOT NULL,                 -- deterministic | stochastic
    params         jsonb NOT NULL,
    metrics        jsonb,
    checks         jsonb,
    warnings       jsonb,
    error_message  text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    duration_ms    integer
);

ALTER TABLE battery_master.optimization_run
    ADD COLUMN IF NOT EXISTS study_id bigint REFERENCES battery_ml.arb_study (study_id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS battery_ml.arb_study_day (
    study_id             bigint NOT NULL REFERENCES battery_ml.arb_study (study_id) ON DELETE CASCADE,
    kpi_date             date NOT NULL,
    run_id               bigint REFERENCES battery_master.optimization_run (run_id) ON DELETE SET NULL,
    solver_status        text,
    solve_seconds        numeric(10,3),
    expected_profit_usd  numeric(12,2),
    gross_usd            numeric(12,4),
    degradation_usd      numeric(12,4),
    grid_usd             numeric(12,4),
    net_usd              numeric(12,4),
    oracle_net_usd       numeric(12,4),
    pack_net_usd         numeric(12,4),             -- the pack's realized net that day (dispatch_outcome)
    discharge_mwh        numeric(12,6),
    charge_mwh           numeric(12,6),
    cycles               numeric(8,4),
    soc_start_pct        numeric(6,2),
    soc_end_pct          numeric(6,2),
    checks               jsonb,
    PRIMARY KEY (study_id, kpi_date)
);

CREATE TABLE IF NOT EXISTS battery_ml.arb_backtest (
    study_id        bigint NOT NULL REFERENCES battery_ml.arb_study (study_id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN ('policy', 'oracle')),
    interval_start  timestamptz NOT NULL,
    run_id          bigint REFERENCES battery_master.optimization_run (run_id) ON DELETE SET NULL,
    p_kw            numeric(10,2),                 -- + discharge / - charge
    c_as_mw         numeric(8,3),
    soc_pct         numeric(6,2),                  -- at the end of the interval
    rt_price_mwh    numeric(10,2),
    fc_price_mwh    numeric(10,2),
    energy_mwh      numeric(12,6),
    gross_usd       numeric(12,4),
    degradation_usd numeric(12,4),
    grid_usd        numeric(12,4),
    as_usd          numeric(12,4),
    net_usd         numeric(12,4),
    PRIMARY KEY (study_id, kind, interval_start)
);
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("SELECT charge_type, rate, unit FROM battery_master.grid_charge ORDER BY charge_id")
            print("grid_charge:", cur.fetchall())
            cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                           AND table_name LIKE 'arb_%' ORDER BY 1""")
            print("tables:", [r[0] for r in cur.fetchall()])
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
