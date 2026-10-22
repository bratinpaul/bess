"""Loss decomposition / performance benchmarking runs in battery_ml.

    python 2026_10_18_loss_decomposition.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_18_loss_decomposition.py --commit   # run for real

loss_run     one computation: the battery systems, window, baseline window and parameters (transformer, guarantee,
             standby, control limits), the fitted expected-loss models per system and stage, the run summary
             (energy balance, RTE factor chain, loss shares, closure audit, loading curves) and warnings.
loss_daily   the benchmark scorecard: per run, system and plant day - energies at every node, loss per stage
             (actual / expected / excess), the RTE factor chain, performance ratio, guarantee gap, fixed vs variable
             loss, closure errors, loss value in USD and the EWMA / CUSUM control-chart state per stage.
loss_ledger  the per-interval loss ledger (TimescaleDB hypertable on ts): power at every node, loss per stage in kWh,
             expected loss per stage, stage efficiencies, loading and the energy-balance closure error.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE TABLE IF NOT EXISTS battery_ml.loss_run (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_name        text,
    status          text        NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    system_ids      bigint[]    NOT NULL,
    date_from       date        NOT NULL,
    date_to         date        NOT NULL,
    params          jsonb       NOT NULL DEFAULT '{}',
    models          jsonb,                          -- {system_id: {stage: fitted expected-loss model}}
    summary         jsonb,                          -- {system_id: run totals, chain, shares, closure audit, curves}
    warnings        jsonb       NOT NULL DEFAULT '[]',
    error_message   text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    duration_ms     integer
);

CREATE TABLE IF NOT EXISTS battery_ml.loss_daily (
    run_id              bigint  NOT NULL REFERENCES battery_ml.loss_run (run_id) ON DELETE CASCADE,
    system_id           bigint  NOT NULL,
    day                 date    NOT NULL,
    intervals           integer NOT NULL,
    is_baseline         boolean NOT NULL DEFAULT false,
    -- energy at the nodes (kWh, in = toward the battery, out = toward the grid)
    e_in_poi_kwh        numeric(14,3),
    e_out_poi_kwh       numeric(14,3),
    e_in_ac_kwh         numeric(14,3),
    e_out_ac_kwh        numeric(14,3),
    e_in_term_kwh       numeric(14,3),
    e_out_term_kwh      numeric(14,3),
    stored_kwh          numeric(14,3),              -- energy left in the cells (+) or taken from them (-)
    throughput_kwh      numeric(14,3),              -- |P_ac| integrated
    utilization_pct     numeric(8,3),               -- throughput / (rated kW x 24 h)
    -- losses per stage (kWh): actual, expected at the same operating conditions
    loss_batt_kwh       numeric(12,3),
    loss_dc_kwh         numeric(12,3),
    loss_pcs_kwh        numeric(12,3),
    loss_xfmr_kwh       numeric(12,3),
    aux_hvac_kwh        numeric(12,3),
    aux_ctrl_kwh        numeric(12,3),
    standby_kwh         numeric(12,3),
    exp_batt_kwh        numeric(12,3),
    exp_pcs_kwh         numeric(12,3),
    exp_xfmr_kwh        numeric(12,3),
    exp_aux_kwh         numeric(12,3),
    exp_standby_kwh     numeric(12,3),
    fixed_kwh           numeric(12,3),
    variable_kwh        numeric(12,3),
    -- round trip and its factors (fractions)
    rte_term            numeric(8,5),
    rte_dc              numeric(8,5),
    rte_ac              numeric(8,5),
    rte_poi_excl_aux    numeric(8,5),
    rte_plant           numeric(8,5),
    rte_expected        numeric(8,5),
    performance_ratio   numeric(8,5),
    guarantee_gap_pts   numeric(8,4),               -- guaranteed RTE - actual (on the guarantee basis), points
    -- audit and value
    closure_kwh         numeric(12,4),              -- in - out - stored - losses
    closure_pcs_kwh     numeric(12,4),              -- metered PCS loss - loss implied by efficiency_pct
    avg_price_mwh       numeric(10,3),
    loss_usd            numeric(12,4),
    excess_usd          numeric(12,4),
    extra               jsonb,                      -- normalized efficiencies, counter closures, control charts
    PRIMARY KEY (run_id, system_id, day)
);

CREATE TABLE IF NOT EXISTS battery_ml.loss_ledger (
    run_id          bigint      NOT NULL REFERENCES battery_ml.loss_run (run_id) ON DELETE CASCADE,
    system_id       bigint      NOT NULL,
    ts              timestamptz NOT NULL,
    direction       text        NOT NULL CHECK (direction IN ('CHARGE', 'DISCHARGE', 'IDLE')),
    -- power at the nodes, kW, + toward the battery (charge) / - toward the grid (discharge)
    p_poi_kw        numeric(10,3),
    p_ac_kw         numeric(10,3),
    p_dc_kw         numeric(10,3),
    p_term_kw       numeric(10,3),
    p_chem_kw       numeric(10,3),
    load_frac       numeric(8,5),
    -- losses in the interval, kWh
    loss_batt_kwh   numeric(10,5),
    loss_dc_kwh     numeric(10,5),
    loss_pcs_kwh    numeric(10,5),
    loss_xfmr_kwh   numeric(10,5),
    aux_hvac_kwh    numeric(10,5),
    aux_ctrl_kwh    numeric(10,5),
    standby_kwh     numeric(10,5),
    exp_batt_kwh    numeric(10,5),
    exp_pcs_kwh     numeric(10,5),
    exp_xfmr_kwh    numeric(10,5),
    exp_aux_kwh     numeric(10,5),
    eta_pcs         numeric(8,5),
    eta_batt        numeric(8,5),
    closure_kwh     numeric(10,5),
    price_mwh       numeric(10,3),
    PRIMARY KEY (run_id, system_id, ts)
);
SELECT create_hypertable('battery_ml.loss_ledger', 'ts', if_not_exists => TRUE, migrate_data => TRUE);
CREATE INDEX IF NOT EXISTS ix_loss_ledger_run_system ON battery_ml.loss_ledger (run_id, system_id, ts);
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                           AND table_name LIKE 'loss_%' ORDER BY 1""")
            print("tables:", [r[0] for r in cur.fetchall()])
            cur.execute("""SELECT hypertable_name FROM timescaledb_information.hypertables
                           WHERE hypertable_schema = 'battery_ml' AND hypertable_name = 'loss_ledger'""")
            print("hypertable:", cur.fetchall())
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
