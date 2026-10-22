"""Point battery_telemetry.demand_telemetry at the real metering points.

    python 2026_10_03_demand_telemetry_fk.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_03_demand_telemetry_fk.py --commit   # run for real

demand_telemetry.metering_point_id referenced battery_telemetry.metering_point - an empty two-column stub - while the
metering points (mp_code, site, type, voltage) live in battery_master.metering_point, like every other master table
the telemetry references. With the stub empty no demand reading could be stored. The foreign key now references
battery_master.metering_point; the stub table itself is left untouched (nothing else references it).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    "ALTER TABLE battery_telemetry.demand_telemetry DROP CONSTRAINT demand_telemetry_metering_point_id_fkey",
    """ALTER TABLE battery_telemetry.demand_telemetry ADD CONSTRAINT demand_telemetry_metering_point_id_fkey
       FOREIGN KEY (metering_point_id) REFERENCES battery_master.metering_point (metering_point_id)""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM battery_telemetry.demand_telemetry")
    print("   demand_telemetry rows:", cur.fetchone()[0])
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                   WHERE conname = 'demand_telemetry_metering_point_id_fkey'""")
    print("  ", cur.fetchone()[0])
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
