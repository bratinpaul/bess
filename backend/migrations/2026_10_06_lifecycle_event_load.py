"""Load BESS DESIGN/rul_lifecycle_events.csv into battery_master.lifecycle_event (commissioning, augmentation, module
replacement, end of life, failure and decommissioning events of the RUL fleet systems).

    python 2026_10_06_lifecycle_event_load.py            # rehearsal: load, verify, ROLLBACK
    python 2026_10_06_lifecycle_event_load.py --commit   # load for real

lifecycle_event.system_id references battery_master.bess_system (the RUL fleet registry, also used by aging_snapshot
and capacity_test); unknown system_code values are registered there (identity system_id). event_id is an identity and
the table has no natural unique key, so a re-run matches existing events on system + event type + date and updates
them instead of inserting duplicates.
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
CSV = Path(__file__).resolve().parents[2] / "BESS DESIGN" / "rul_lifecycle_events.csv"
EVENT_TYPES = {"COMMISSION", "AUGMENTATION", "MODULE_REPLACE", "EOL_REACHED", "FAILURE", "DECOMMISSION"}  # chk_evt
VALUES = ["age_days", "soh_at_event", "failure_mode", "note"]


def _py(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        return v.strip() or None
    return v.item() if hasattr(v, "item") else v


def main(commit: bool) -> None:
    df = pd.read_csv(CSV)
    missing = {"system_code", "event_type", "event_date", *VALUES} - set(df.columns)
    if missing:
        raise SystemExit(f"Missing column(s): {', '.join(sorted(missing))}")
    df["system_code"] = df["system_code"].str.strip()
    df["event_type"] = df["event_type"].str.strip().str.upper()
    df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
    bad = sorted(set(df["event_type"]) - EVENT_TYPES)
    if bad:
        raise SystemExit(f"Unknown event_type(s): {', '.join(bad)} (allowed: {', '.join(sorted(EVENT_TYPES))})")
    if df.duplicated(["system_code", "event_type", "event_date"]).any():
        raise SystemExit("Duplicate (system_code, event_type, event_date) rows in the file")

    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT system_code, system_id FROM battery_master.bess_system")
    ids = dict(cur.fetchall())
    new = [code for code in sorted(df["system_code"].unique()) if code not in ids]
    for code in new:  # system_id is an identity column: the database assigns it
        cur.execute("INSERT INTO battery_master.bess_system (system_code) VALUES (%s) RETURNING system_id", (code,))
        ids[code] = cur.fetchone()[0]
    print(f"   bess_system: {len(new)} registered, {len(ids)} known")

    cur.execute("SELECT system_id, event_type, event_date, event_id FROM battery_master.lifecycle_event")
    existing = {(s, t, d): e for s, t, d, e in cur.fetchall()}
    inserts, updates = [], []
    for r in df.itertuples(index=False):
        sid = ids[r.system_code]
        vals = [_py(getattr(r, c)) for c in VALUES]
        eid = existing.get((sid, r.event_type, r.event_date))
        if eid is None:
            inserts.append((sid, r.event_type, r.event_date, *vals))
        else:
            updates.append((*vals, eid))
    if inserts:
        execute_values(cur, f"""INSERT INTO battery_master.lifecycle_event (system_id, event_type, event_date,
                                {', '.join(VALUES)}) VALUES %s""", inserts)
    if updates:
        cur.executemany(f"""UPDATE battery_master.lifecycle_event SET {', '.join(c + ' = %s' for c in VALUES)}
                            WHERE event_id = %s""", updates)
    print(f"   lifecycle_event: {len(inserts)} inserted, {len(updates)} updated")
    cur.execute("""SELECT event_type, count(*), min(event_date), max(event_date) FROM battery_master.lifecycle_event
                   GROUP BY 1 ORDER BY 1""")
    for row in cur.fetchall():
        print("  ", row)
    cur.execute("SELECT count(*) FROM battery_master.lifecycle_event")
    print(f"   lifecycle_event rows: {cur.fetchone()[0]} (file: {len(df)})")
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
