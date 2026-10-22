"""Load BESS DESIGN/rul_aging_snapshots.csv into battery_master.aging_snapshot (RUL / aging reference data).

    python 2026_10_06_aging_snapshot_load.py            # rehearsal: load, verify, ROLLBACK
    python 2026_10_06_aging_snapshot_load.py --commit   # load for real

aging_snapshot.system_id references battery_master.bess_system (the RUL fleet registry: system_id + system_code, also
used by battery_provenance / capacity_test / lifecycle_event) - not battery_system. The file's system_code values
(BESS-01 .. BESS-15) are registered there first (system_id is an identity column, assigned by the database), then
the snapshots are upserted on (system_id, snapshot_date). Re-running is safe.
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "rul_aging_snapshots.csv"
COLUMNS = ["snapshot_date", "age_days", "calendar_age_years", "cum_throughput_mwh", "equiv_full_cycles", "avg_dod_pct",
           "avg_cell_temp_c", "days_at_high_soc", "soh_pct", "internal_resistance_mohm", "rul_cycles", "rul_days",
           "is_censored", "eol_reached"]


def main(commit: bool) -> None:
    df = pd.read_csv(CSV)
    missing = {"system_code", *COLUMNS} - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["system_code"] = df["system_code"].str.strip()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    if df.duplicated(["system_code", "snapshot_date"]).any():
        raise SystemExit("Duplicate (system_code, snapshot_date) rows in the file")

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT system_code, system_id FROM battery_master.bess_system")
    ids = dict(cur.fetchall())
    new = [code for code in sorted(df["system_code"].unique()) if code not in ids]
    for code in new:  # system_id is an identity column: the database assigns it
        cur.execute("INSERT INTO battery_master.bess_system (system_code) VALUES (%s) RETURNING system_id", (code,))
        ids[code] = cur.fetchone()[0]
    print(f"   bess_system: {len(new)} registered, {len(ids)} known")

    rows = [(ids[r.system_code], *[None if pd.isna(getattr(r, c)) else getattr(r, c) for c in COLUMNS])
            for r in df.itertuples(index=False)]
    rows = [tuple(v.item() if hasattr(v, "item") else v for v in row) for row in rows]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS[1:])
    execute_values(cur, f"""INSERT INTO battery_master.aging_snapshot (system_id, {', '.join(COLUMNS)}) VALUES %s
                            ON CONFLICT (system_id, snapshot_date) DO UPDATE SET {updates}""", rows)
    cur.execute("""SELECT b.system_code, count(*), min(a.snapshot_date), max(a.snapshot_date), min(a.soh_pct)
                   FROM battery_master.aging_snapshot a JOIN battery_master.bess_system b USING (system_id)
                   GROUP BY 1 ORDER BY 1""")
    for r in cur.fetchall():
        print("  ", r)
    cur.execute("SELECT count(*) FROM battery_master.aging_snapshot")
    print(f"   aging_snapshot rows: {cur.fetchone()[0]} (file: {len(df)})")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
