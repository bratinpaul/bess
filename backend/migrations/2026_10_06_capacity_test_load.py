"""Load BESS DESIGN/rul_capacity_tests.csv into battery_master.capacity_test (periodic RPT capacity / resistance
checkpoints - the SOH ground truth of the RUL fleet).

    python 2026_10_06_capacity_test_load.py            # rehearsal: load, verify, ROLLBACK
    python 2026_10_06_capacity_test_load.py --commit   # load for real

capacity_test.system_id references battery_master.bess_system (the RUL fleet registry, also used by aging_snapshot);
unknown system_code values are registered there (identity system_id). test_id is an identity and the table has no
unique (system_id, test_date), so a re-run matches existing tests on system + date and updates them instead of
inserting duplicates.
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "rul_capacity_tests.csv"
VALUES = ["age_days", "equiv_full_cycles", "measured_capacity_kwh", "soh_pct", "internal_resistance_mohm", "test_temp_c",
          "method"]


def _py(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def main(commit: bool) -> None:
    df = pd.read_csv(CSV)
    missing = {"system_code", "test_date", *VALUES} - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["system_code"] = df["system_code"].str.strip()
    df["test_date"] = pd.to_datetime(df["test_date"]).dt.date
    if df.duplicated(["system_code", "test_date"]).any():
        raise SystemExit("Duplicate (system_code, test_date) rows in the file")
    bad = df[(df["soh_pct"] < 0) | (df["soh_pct"] > 110)]
    if len(bad):
        raise SystemExit(f"{len(bad)} rows with soh_pct outside 0..110 (chk_rpt_soh)")

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT system_code, system_id FROM battery_master.bess_system")
    ids = dict(cur.fetchall())
    new = [code for code in sorted(df["system_code"].unique()) if code not in ids]
    for code in new:  # system_id is an identity column: the database assigns it
        cur.execute("INSERT INTO battery_master.bess_system (system_code) VALUES (%s) RETURNING system_id", (code,))
        ids[code] = cur.fetchone()[0]
    print(f"   bess_system: {len(new)} registered, {len(ids)} known")

    cur.execute("SELECT system_id, test_date, test_id FROM battery_master.capacity_test")
    existing = {(s, d): t for s, d, t in cur.fetchall()}
    inserts, updates = [], []
    for r in df.itertuples(index=False):
        sid = ids[r.system_code]
        vals = [_py(getattr(r, c)) for c in VALUES]
        tid = existing.get((sid, r.test_date))
        if tid is None:
            inserts.append((sid, r.test_date, *vals))
        else:
            updates.append((*vals, tid))
    if inserts:
        execute_values(cur, f"""INSERT INTO battery_master.capacity_test (system_id, test_date, {', '.join(VALUES)})
                                VALUES %s""", inserts)
    if updates:
        cur.executemany(f"""UPDATE battery_master.capacity_test SET {', '.join(c + ' = %s' for c in VALUES)}
                            WHERE test_id = %s""", updates)
    print(f"   capacity_test: {len(inserts)} inserted, {len(updates)} updated")
    cur.execute("""SELECT b.system_code, count(*), min(t.test_date), max(t.test_date), min(t.soh_pct)
                   FROM battery_master.capacity_test t JOIN battery_master.bess_system b USING (system_id)
                   GROUP BY 1 ORDER BY 1""")
    for row in cur.fetchall():
        print("  ", row)
    cur.execute("SELECT count(*) FROM battery_master.capacity_test")
    print(f"   capacity_test rows: {cur.fetchone()[0]} (file: {len(df)})")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
