"""Load BESS DESIGN/ocv_curve.csv into battery_master.ocv_curve (per-cell open-circuit voltage vs SOC by chemistry,
direction - charge / discharge hysteresis or their mean - and temperature).

    python 2026_10_06_ocv_curve_load.py            # rehearsal: load, verify, ROLLBACK
    python 2026_10_06_ocv_curve_load.py --commit   # load for real

Upserted on the key (chemistry, direction, temp_c, soc_pct), so a re-run is safe.
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "ocv_curve.csv"
KEY = ["chemistry", "direction", "temp_c", "soc_pct"]
DIRECTIONS = {"CHARGE", "DISCHARGE", "MEAN"}  # ocv_curve_direction_check


def main(commit: bool) -> None:
    df = pd.read_csv(CSV)
    missing = set(KEY + ["ocv_v"]) - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["chemistry"] = df["chemistry"].str.strip().str.upper()
    df["direction"] = df["direction"].str.strip().str.upper()
    bad = sorted(set(df["direction"]) - DIRECTIONS)
    if bad:
        raise SystemExit(f"Unknown direction(s): {', '.join(bad)}")
    if df[KEY + ["ocv_v"]].isna().any().any():
        raise SystemExit("Every row needs chemistry, direction, temp_c, soc_pct and ocv_v")
    if not df["soc_pct"].between(0, 100).all() or not df["ocv_v"].between(0, 6).all():
        raise SystemExit("soc_pct must be 0..100 and ocv_v 0..6 V (a per-cell voltage)")
    if df.duplicated(KEY).any():
        raise SystemExit("Duplicate (chemistry, direction, temp_c, soc_pct) rows in the file")

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM battery_master.ocv_curve")
    before = cur.fetchone()[0]
    execute_values(cur, """INSERT INTO battery_master.ocv_curve (chemistry, direction, temp_c, soc_pct, ocv_v) VALUES %s
                           ON CONFLICT (chemistry, direction, temp_c, soc_pct) DO UPDATE SET ocv_v = EXCLUDED.ocv_v""",
                   [(r.chemistry, r.direction, float(r.temp_c), float(r.soc_pct), float(r.ocv_v)) for r in df.itertuples()])
    cur.execute("""SELECT chemistry, direction, temp_c, count(*), min(ocv_v), max(ocv_v) FROM battery_master.ocv_curve
                   GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")
    for row in cur.fetchall():
        print("  ", row)
    cur.execute("SELECT count(*) FROM battery_master.ocv_curve")
    print(f"   ocv_curve rows: {before} -> {cur.fetchone()[0]} (file: {len(df)})")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
