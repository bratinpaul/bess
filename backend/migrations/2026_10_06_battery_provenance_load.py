"""Load BESS DESIGN/rul_systems.csv into battery_master.battery_provenance (cell provenance, batch and beginning-of-life
baseline per RUL fleet system).

    python 2026_10_06_battery_provenance_load.py            # rehearsal: load, verify, ROLLBACK
    python 2026_10_06_battery_provenance_load.py --commit   # load for real

battery_provenance.system_id (its primary key) references battery_master.bess_system; unknown system_code values are
registered there (identity system_id). Rows are upserted on system_id, so a re-run is safe.

Not stored: site_code (bess_system here has no site link, and SITE-01..03 are not plant sites in battery_master.site)
and commission_date (already held by the lifecycle_event COMMISSION events - the load checks they agree).
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "rul_systems.csv"
COLUMNS = ["manufacturer", "cell_model", "chemistry", "batch_lot", "cell_format", "build_date", "nameplate_kwh",
           "bol_capacity_kwh", "bol_resistance_mohm", "usage_cycles_per_day", "climate_avg_temp_c"]


def _py(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        return v.strip() or None
    return v.item() if hasattr(v, "item") else v


def main(commit: bool) -> None:
    df = pd.read_csv(CSV)
    missing = {"system_code", *COLUMNS} - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["system_code"] = df["system_code"].str.strip()
    df["build_date"] = pd.to_datetime(df["build_date"]).dt.date
    if df["system_code"].duplicated().any():
        raise SystemExit("Duplicate system_code rows in the file")
    if df["chemistry"].isna().any():
        raise SystemExit("chemistry is required (NOT NULL)")

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT system_code, system_id FROM battery_master.bess_system")
    ids = dict(cur.fetchall())
    new = [code for code in sorted(df["system_code"].unique()) if code not in ids]
    for code in new:  # system_id is an identity column: the database assigns it
        cur.execute("INSERT INTO battery_master.bess_system (system_code) VALUES (%s) RETURNING system_id", (code,))
        ids[code] = cur.fetchone()[0]
    print(f"   bess_system: {len(new)} registered, {len(ids)} known")

    rows = [(ids[r.system_code], *[_py(getattr(r, c)) for c in COLUMNS]) for r in df.itertuples(index=False)]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS)
    execute_values(cur, f"""INSERT INTO battery_master.battery_provenance (system_id, {', '.join(COLUMNS)}) VALUES %s
                            ON CONFLICT (system_id) DO UPDATE SET {updates}""", rows)

    # the file's commission dates should match the lifecycle COMMISSION events (where they are kept)
    if "commission_date" in df.columns:
        cur.execute("""SELECT b.system_code, e.event_date FROM battery_master.lifecycle_event e
                       JOIN battery_master.bess_system b USING (system_id) WHERE e.event_type = 'COMMISSION'""")
        events = dict(cur.fetchall())
        off = [(r.system_code, r.commission_date, events.get(r.system_code)) for r in df.itertuples(index=False)
               if str(events.get(r.system_code)) != str(r.commission_date)]
        print(f"   commission_date vs lifecycle COMMISSION: {len(df) - len(off)} agree"
              + (f", differ / missing: {off}" if off else ""))
    cur.execute("SELECT count(*), count(DISTINCT batch_lot) FROM battery_master.battery_provenance")
    n, lots = cur.fetchone()
    print(f"   battery_provenance rows: {n} (file: {len(df)}), batch lots: {lots}")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
