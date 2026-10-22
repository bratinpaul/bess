"""SOC reference (battery_master.soc_reference): repoint its system FK to the plant battery systems and load
BESS DESIGN/soc_reference.csv.

    python 2026_10_06_soc_reference.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_06_soc_reference.py --commit   # run for real

Why the FK moves: soc_reference holds the independent ground-truth SOC of a plant at given moments (rest-OCV / full
charge / lab anchors), and battery_master.v_soc_features joins it to battery_telemetry.system_telemetry on
(system_id, ts) - so system_id must be a plant battery system (battery_master.battery_system), not a RUL fleet unit
(battery_master.bess_system). The file's BESS-01 rows match the Kolkata plant (01-BATTERY-01) exactly at all 91
timestamps, so they load there.

Timestamps in the file are plant time (Asia/Kolkata), as for every telemetry import. Upserted on (system_id, ts).
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "soc_reference.csv"
PLANT_TZ = "Asia/Kolkata"
# file system_code -> plant battery system name (codes that are already system names map to themselves)
ALIASES = {"BESS-01": "01-BATTERY-01"}
METHODS = {"FULL_CHARGE", "FULL_DISCHARGE", "LAB_RPT", "REST_OCV"}  # soc_reference_method_check


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("""SELECT confrelid::regclass::text FROM pg_constraint
                   WHERE conname = 'soc_reference_system_id_fkey'""")
    target = (cur.fetchone() or [None])[0]
    if target != "battery_system":
        cur.execute("SELECT count(*) FROM battery_master.soc_reference")
        if cur.fetchone()[0]:
            raise SystemExit("soc_reference already has rows keyed to bess_system - repoint by hand")
        cur.execute("ALTER TABLE battery_master.soc_reference DROP CONSTRAINT IF EXISTS soc_reference_system_id_fkey")
        cur.execute("""ALTER TABLE battery_master.soc_reference ADD CONSTRAINT soc_reference_system_id_fkey
                       FOREIGN KEY (system_id) REFERENCES battery_master.battery_system (battery_system_id) ON DELETE CASCADE""")
        print(f"   FK repointed: {target} -> battery_system")

    df = pd.read_csv(CSV)
    missing = {"system_code", "ts", "soc_true_pct"} - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["system_code"] = df["system_code"].str.strip()
    df["method"] = df.get("method", pd.Series(dtype=str)).astype("string").str.strip().str.upper()
    bad = sorted(set(df["method"].dropna()) - METHODS)
    if bad:
        raise SystemExit(f"Unknown method(s): {', '.join(bad)}")
    if not df["soc_true_pct"].between(0, 100).all():
        raise SystemExit("soc_true_pct must be within 0..100")
    ts = pd.to_datetime(df["ts"])
    df["ts"] = ts.dt.tz_localize(PLANT_TZ) if ts.dt.tz is None else ts
    cur.execute("SELECT system_name, battery_system_id FROM battery_master.battery_system")
    systems = {n.strip().lower(): i for n, i in cur.fetchall()}
    df["system_id"] = df["system_code"].map(lambda c: systems.get(ALIASES.get(c, c).lower()))
    unknown = sorted(df.loc[df["system_id"].isna(), "system_code"].unique())
    if unknown:
        raise SystemExit(f"Unknown system(s): {', '.join(unknown)} (add them to ALIASES or use the battery system name)")
    if df.duplicated(["system_id", "ts"]).any():
        raise SystemExit("Duplicate (system, ts) rows in the file")
    note = df["note"] if "note" in df.columns else pd.Series([None] * len(df))
    execute_values(cur, """INSERT INTO battery_master.soc_reference (system_id, ts, soc_true_pct, method, note) VALUES %s
                           ON CONFLICT (system_id, ts) DO UPDATE SET soc_true_pct = EXCLUDED.soc_true_pct,
                           method = EXCLUDED.method, note = EXCLUDED.note""",
                   [(int(r.system_id), r.ts.to_pydatetime(), float(r.soc_true_pct),
                     None if pd.isna(r.method) else r.method, None if pd.isna(n) else str(n))
                    for r, n in zip(df.itertuples(), note)])
    cur.execute("""SELECT b.system_name, r.method, count(*), min(r.ts), max(r.ts) FROM battery_master.soc_reference r
                   JOIN battery_master.battery_system b ON b.battery_system_id = r.system_id GROUP BY 1, 2 ORDER BY 1, 2""")
    for row in cur.fetchall():
        print("  ", row)
    cur.execute("""SELECT count(*), count(soc_error_vs_bms), round(avg(abs(soc_error_vs_bms)), 3)
                   FROM battery_master.v_soc_features WHERE soc_true_pct IS NOT NULL""")
    print("   v_soc_features rows with a reference / with a BMS error / mean |error|:", cur.fetchone())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
