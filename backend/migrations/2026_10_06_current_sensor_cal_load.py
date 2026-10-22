"""Load BESS DESIGN/current_sensor_cal.csv into battery_master.current_sensor_cal (current-sensor calibrations per fleet
system: offset, gain error and offset drift at each calibration).

    python 2026_10_06_current_sensor_cal_load.py            # rehearsal: load, verify, ROLLBACK
    python 2026_10_06_current_sensor_cal_load.py --commit   # load for real

current_sensor_cal.system_id references battery_master.bess_system; unknown system_code values are registered there
(identity system_id). Upserted on (system_id, calibrated_on), so a re-run is safe.
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "current_sensor_cal.csv"
VALUES = ["offset_a", "gain_error_pct", "drift_a_per_day"]


def _num(v):
    return None if pd.isna(v) else float(v)


def main(commit: bool) -> None:
    df = pd.read_csv(CSV)
    missing = {"system_code", "calibrated_on", *VALUES} - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["system_code"] = df["system_code"].str.strip()
    df["calibrated_on"] = pd.to_datetime(df["calibrated_on"]).dt.date
    if df.duplicated(["system_code", "calibrated_on"]).any():
        raise SystemExit("Duplicate (system_code, calibrated_on) rows in the file")

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT system_code, system_id FROM battery_master.bess_system")
    ids = dict(cur.fetchall())
    new = [code for code in sorted(df["system_code"].unique()) if code not in ids]
    for code in new:  # system_id is an identity column: the database assigns it
        cur.execute("INSERT INTO battery_master.bess_system (system_code) VALUES (%s) RETURNING system_id", (code,))
        ids[code] = cur.fetchone()[0]
    print(f"   bess_system: {len(new)} registered, {len(ids)} known")
    execute_values(cur, f"""INSERT INTO battery_master.current_sensor_cal (system_id, calibrated_on, {', '.join(VALUES)})
                            VALUES %s ON CONFLICT (system_id, calibrated_on) DO UPDATE SET
                            {', '.join(f'{c} = EXCLUDED.{c}' for c in VALUES)}""",
                   [(ids[r.system_code], r.calibrated_on, *[_num(getattr(r, c)) for c in VALUES]) for r in df.itertuples()])
    cur.execute("""SELECT b.system_code, c.calibrated_on, c.offset_a, c.gain_error_pct, c.drift_a_per_day
                   FROM battery_master.current_sensor_cal c JOIN battery_master.bess_system b USING (system_id)
                   ORDER BY 1, 2""")
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
