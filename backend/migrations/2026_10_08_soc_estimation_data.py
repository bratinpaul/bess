"""Staging table battery_raw.soc_estimation_data, then UPDATE battery_telemetry.system_telemetry from it.

    python 2026_10_08_soc_estimation_data.py                         # rehearsal: stage + update, verify, ROLLBACK
    python 2026_10_08_soc_estimation_data.py --commit                # for real
    python 2026_10_08_soc_estimation_data.py --system 01-BATTERY-01  # system the file belongs to (default)

The CSV (BESS DESIGN/soc_estimation_data.csv) has no system column - it is BESS-01, i.e. 01-BATTERY-01. Staging keeps
the file as is (ts without a time zone, plant time) plus system_name / source_file / row_no / loaded_at; reloading a
file replaces its rows. The update matches system_telemetry rows on (system_id, ts read in the site's time zone) and
only fills the SOC-estimation columns - it never inserts:

    measured_current_a, current_sensor_offset_a, soc_coulomb_pct, usable_capacity_ah, coulombic_efficiency,
    at_rest, rest_duration_min, ocv_rested_v              -> same-named columns
    soc_bms_pct (the file's fused estimate)               -> soc_battery_telemetry_pct
                                                             (telemetry soc_bms_pct already equals the file's
                                                              soc_true_pct and is left alone)
    true_current_a, soc_true_pct                          -> staged only (= pack_current_a / soc_bms_pct already)
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "soc_estimation_data.csv"
COLUMNS = ["ts", "true_current_a", "measured_current_a", "current_sensor_offset_a", "soc_true_pct", "soc_coulomb_pct",
           "soc_bms_pct", "usable_capacity_ah", "coulombic_efficiency", "at_rest", "rest_duration_min", "ocv_rested_v"]

DDL = """
CREATE TABLE IF NOT EXISTS battery_raw.soc_estimation_data (
    stg_id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_name             text        NOT NULL,      -- the file has no system column; given at load time
    ts                      timestamp without time zone, -- as written in the file (plant time, no conversion)
    true_current_a          numeric,
    measured_current_a      numeric,
    current_sensor_offset_a numeric,
    soc_true_pct            numeric,
    soc_coulomb_pct         numeric,
    soc_bms_pct             numeric,
    usable_capacity_ah      numeric,
    coulombic_efficiency    numeric,
    at_rest                 boolean,
    rest_duration_min       numeric,
    ocv_rested_v            numeric,
    source_file             text        NOT NULL,
    row_no                  integer     NOT NULL,      -- data row in the file (1 = first row after the header)
    loaded_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_soc_estimation_data_file_row UNIQUE (source_file, row_no)
);
COMMENT ON TABLE battery_raw.soc_estimation_data IS
    'Staging copy of soc_estimation_data CSV files, as is; used to UPDATE system_telemetry SOC-estimation columns.';
"""

UPDATE = """
UPDATE battery_telemetry.system_telemetry t
   SET measured_current_a        = s.measured_current_a,
       current_sensor_offset_a   = s.current_sensor_offset_a,
       soc_coulomb_pct           = s.soc_coulomb_pct,
       soc_battery_telemetry_pct = s.soc_bms_pct,
       usable_capacity_ah        = s.usable_capacity_ah,
       coulombic_efficiency      = s.coulombic_efficiency,
       at_rest                   = s.at_rest,
       rest_duration_min         = s.rest_duration_min,
       ocv_rested_v              = s.ocv_rested_v
  FROM battery_raw.soc_estimation_data s
 WHERE s.source_file = %(file)s
   AND t.system_id   = %(sid)s
   AND t.ts          = s.ts AT TIME ZONE %(tz)s
"""


def main(commit: bool, system_name: str) -> None:
    df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")

    def val(v):
        v = v.strip()
        return v or None

    rows = [(system_name, *(val(getattr(r, c)) for c in COLUMNS), CSV.name, i)
            for i, r in enumerate(df.itertuples(index=False), start=1)]

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("""SELECT b.battery_system_id, s.timezone FROM battery_master.battery_system b
                   JOIN battery_master.site s ON s.site_id = b.site_id WHERE b.system_name = %s""", (system_name,))
    found = cur.fetchone()
    if not found:
        raise SystemExit(f"Unknown battery system {system_name!r}")
    sid, tz = found

    cur.execute(DDL)
    cur.execute("DELETE FROM battery_raw.soc_estimation_data WHERE source_file = %s", (CSV.name,))
    replaced = cur.rowcount
    execute_values(cur, f"""INSERT INTO battery_raw.soc_estimation_data
                            (system_name, {', '.join(COLUMNS)}, source_file, row_no) VALUES %s""", rows)
    print(f"   staged {len(rows)} rows from {CSV.name} ({replaced} replaced) as {system_name} (id {sid}, {tz})")

    cur.execute(UPDATE, dict(file=CSV.name, sid=sid, tz=tz))
    updated = cur.rowcount
    cur.execute("""SELECT count(*) FROM battery_raw.soc_estimation_data s
                   WHERE s.source_file = %(file)s AND NOT EXISTS (
                       SELECT 1 FROM battery_telemetry.system_telemetry t
                       WHERE t.system_id = %(sid)s AND t.ts = s.ts AT TIME ZONE %(tz)s)""",
                dict(file=CSV.name, sid=sid, tz=tz))
    unmatched = cur.fetchone()[0]
    cur.execute("""SELECT count(*), count(soc_coulomb_pct), min(ts), max(ts)
                   FROM battery_telemetry.system_telemetry WHERE system_id = %s AND soc_coulomb_pct IS NOT NULL""", (sid,))
    n, filled, first, last = cur.fetchone()
    print(f"   system_telemetry: {updated} rows updated, {unmatched} staged rows without a telemetry row · "
          f"filled {filled} rows {first} -> {last}")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    name = args[args.index("--system") + 1] if "--system" in args else "01-BATTERY-01"
    main("--commit" in args, name)
