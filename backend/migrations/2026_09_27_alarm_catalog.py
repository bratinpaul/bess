"""Create battery_master.alarm_catalog: the definitions of the alarms BMS / PCS / HVAC / EMS can raise.

    python 2026_09_27_alarm_catalog.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_27_alarm_catalog.py --commit   # run for real

Built from the 'Alarm Catalog' sheet of BESS DESIGN/BESS_Alarm_SampleData.xlsx:

    alarm_code, source, alarm_type, severity, asset_type, description, probable_cause, threshold, unit

An entry is identified by (source, alarm_code); alarm_catalog_id is a surrogate key for the API.
severity is stored as severity_level -> alarm_severity (0 Info, 1 Warning, 2 Alarm, 3 Critical).
The sheet's 'count (30d)' column is a statistic of the sample alarm log and is not stored.
Rows are loaded with the bulk API (POST /api/alarm-catalog/bulk), not here.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

DDL = """
CREATE TABLE battery_master.alarm_catalog (
    alarm_catalog_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alarm_code       text     NOT NULL,
    source           text     NOT NULL CHECK (source IN ('BMS', 'PCS', 'HVAC', 'EMS')),
    alarm_type       text     NOT NULL,
    severity_level   smallint NOT NULL REFERENCES battery_master.alarm_severity (severity_level),
    asset_type       text,
    description      text     NOT NULL,
    probable_cause   text,
    threshold        numeric,
    unit             text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT alarm_catalog_source_code_key UNIQUE (source, alarm_code),
    CONSTRAINT alarm_catalog_code_not_blank CHECK (btrim(alarm_code) <> ''),
    CONSTRAINT alarm_catalog_type_not_blank CHECK (btrim(alarm_type) <> ''),
    CONSTRAINT alarm_catalog_description_not_blank CHECK (btrim(description) <> '')
);
COMMENT ON TABLE battery_master.alarm_catalog IS
    'Alarm definitions per source system (BMS/PCS/HVAC/EMS); key (source, alarm_code)';
COMMENT ON COLUMN battery_master.alarm_catalog.threshold IS 'Trip threshold, in unit; NULL for event-type alarms';
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute(
        """SELECT column_name, data_type, is_nullable FROM information_schema.columns
           WHERE table_schema = 'battery_master' AND table_name = 'alarm_catalog' ORDER BY ordinal_position"""
    )
    for row in cur.fetchall():
        print("  ", row)
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
