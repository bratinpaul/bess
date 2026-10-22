"""Staging table battery_raw.soc_stg and a load of BESS DESIGN/soc_reference.csv into it, as is.

    python 2026_10_08_soc_stg.py            # rehearsal: create + load, verify, ROLLBACK
    python 2026_10_08_soc_stg.py --commit   # for real

soc_stg holds the file the way it is: its own columns (system_code as written - e.g. BESS-01 - and ts without a time
zone, no conversion), plus where each row came from (source_file, row_no) and when it was loaded. No system mapping,
method check or upsert rules here - that is what battery_master.soc_reference applies (2026_10_06_soc_reference.py).
Loading a file again replaces that file's rows, so the staging table mirrors the latest copy of each file.
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "soc_reference.csv"
COLUMNS = ["system_code", "ts", "soc_true_pct", "method", "note"]

DDL = """
CREATE TABLE IF NOT EXISTS battery_raw.soc_stg (
    stg_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_code   text,
    ts            timestamp without time zone,   -- as written in the file (plant time, no conversion)
    soc_true_pct  numeric,
    method        text,
    note          text,
    source_file   text        NOT NULL,
    row_no        integer     NOT NULL,          -- data row in the file (1 = first row after the header)
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_soc_stg_file_row UNIQUE (source_file, row_no)
);
COMMENT ON TABLE battery_raw.soc_stg IS
    'Staging copy of soc_reference CSV files, as is (no mapping / validation); reloading a file replaces its rows.';
"""


def main(commit: bool) -> None:
    df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")

    def val(v):
        v = v.strip()
        return v or None

    rows = [(val(r.system_code), val(r.ts), val(r.soc_true_pct), val(r.method), val(r.note), CSV.name, i)
            for i, r in enumerate(df.itertuples(index=False), start=1)]

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute("DELETE FROM battery_raw.soc_stg WHERE source_file = %s", (CSV.name,))
    replaced = cur.rowcount
    execute_values(cur, """INSERT INTO battery_raw.soc_stg (system_code, ts, soc_true_pct, method, note, source_file, row_no)
                           VALUES %s""", rows)
    cur.execute("""SELECT count(*), count(DISTINCT system_code), min(ts), max(ts), string_agg(DISTINCT method, ', ')
                   FROM battery_raw.soc_stg WHERE source_file = %s""", (CSV.name,))
    n, systems, first, last, methods = cur.fetchone()
    print(f"   {CSV.name}: {len(rows)} rows in the file, {replaced} replaced, {n} staged · systems {systems} · "
          f"{first} -> {last} · methods {methods}")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
