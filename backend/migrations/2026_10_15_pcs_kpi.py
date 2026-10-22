"""PCS KPI store: battery_ml.pcs_kpi (daily KPI values per PCS unit) and battery_ml.pcs_kpi_run (one row per calculation).

    python 2026_10_15_pcs_kpi.py            # rehearsal: create, verify, ROLLBACK
    python 2026_10_15_pcs_kpi.py --commit   # for real

Same design as battery_ml.bms_kpi / bms_kpi_run (2026_10_14_bms_kpi.py), keyed by pcs_id instead of system_id. The
KPI definitions live in backend/kpi_config/pcs_kpi.yaml; the shared engine app/services/bms_kpi (domain PCS) computes
them from battery_telemetry.pcs_telemetry and writes here. Long format: one row per PCS unit / day / KPI code, so
adding a KPI to the config needs no schema change. Every value keeps the config version + file hash it was made with.
The run table keeps the engine's column names (systems_done = PCS units done).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

DDL = """
CREATE TABLE IF NOT EXISTS battery_ml.pcs_kpi_run (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status          text        NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    triggered_by    text        NOT NULL,                 -- api | cli
    pcs_ids         bigint[],                             -- NULL = all PCS units with telemetry
    start_date      date,                                 -- NULL = from the first telemetry day
    end_date        date,                                 -- NULL = to the last telemetry day
    config_file     text        NOT NULL,
    config_version  integer     NOT NULL,
    config_hash     text        NOT NULL,                 -- sha256 of the YAML file, first 16 hex chars
    kpi_codes       text[]      NOT NULL,
    systems_done    integer,                              -- PCS units computed
    days            integer,
    rows_deleted    integer,
    rows_written    integer,
    error_message   text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    duration_ms     integer
);
COMMENT ON TABLE battery_ml.pcs_kpi_run IS 'One row per PCS KPI calculation (API button or CLI).';

CREATE TABLE IF NOT EXISTS battery_ml.pcs_kpi (
    pcs_id          bigint      NOT NULL REFERENCES battery_master.pcs (pcs_id) ON DELETE CASCADE,
    kpi_date        date        NOT NULL,                 -- plant-local day (config timezone)
    kpi_code        text        NOT NULL,
    kpi_name        text        NOT NULL,
    unit            text,
    value           numeric,                              -- NULL when the KPI has no value that day (e.g. ÷ 0)
    sample_count    integer     NOT NULL,                 -- telemetry rows in the day
    config_version  integer     NOT NULL,
    config_hash     text        NOT NULL,
    run_id          bigint      REFERENCES battery_ml.pcs_kpi_run (run_id) ON DELETE SET NULL,
    calculated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pcs_id, kpi_date, kpi_code)
);
CREATE INDEX IF NOT EXISTS ix_pcs_kpi_code_date ON battery_ml.pcs_kpi (kpi_code, kpi_date);
COMMENT ON TABLE battery_ml.pcs_kpi IS
    'Daily PCS KPIs per PCS unit, computed from pcs_telemetry by the definitions in kpi_config/pcs_kpi.yaml.';
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'battery_ml' AND table_name IN ('pcs_kpi', 'pcs_kpi_run') ORDER BY 1""")
    print("   tables:", ", ".join(r[0] for r in cur.fetchall()))
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
