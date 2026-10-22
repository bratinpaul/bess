"""Link EMS controllers and HVAC units to a battery system, so they fit in asset_hierarchy.

    python 2026_09_27_ems_hvac_parent.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_27_ems_hvac_parent.py --commit   # run for real

Adds ems_controller.battery_system_id and hvac_unit.battery_system_id (-> battery_system, no cascade:
a battery system with EMS/HVAC attached can't be deleted). The existing controllers/units are put on
the only battery system when there is exactly one; otherwise they are left empty to be set by hand.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT battery_system_id FROM battery_master.battery_system")
    systems = [r[0] for r in cur.fetchall()]
    for table in ("ems_controller", "hvac_unit"):
        cur.execute(f"ALTER TABLE battery_master.{table} ADD COLUMN battery_system_id bigint")
        cur.execute(
            f"ALTER TABLE battery_master.{table} ADD CONSTRAINT {table}_battery_system_fkey "
            "FOREIGN KEY (battery_system_id) REFERENCES battery_master.battery_system (battery_system_id)"
        )
        cur.execute(f"CREATE INDEX idx_{table}_battery_system ON battery_master.{table} (battery_system_id)")
        if len(systems) == 1:
            cur.execute(f"UPDATE battery_master.{table} SET battery_system_id = %s", (systems[0],))
        cur.execute(f"SELECT * FROM battery_master.{table} ORDER BY 1")
        print(table, cur.fetchall())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
