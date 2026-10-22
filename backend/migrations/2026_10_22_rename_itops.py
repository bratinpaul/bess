"""Rename schema battery_ops -> battery_itops (activity log). Data, indexes and constraints move with the schema.

Idempotent: does nothing if battery_ops is already gone. Fresh installs create battery_itops directly
(2026_10_21_activity_log.py).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()


def main() -> int:
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT nspname FROM pg_namespace WHERE nspname IN ('battery_ops', 'battery_itops')")
        present = {r[0] for r in cur.fetchall()}
        if "battery_ops" not in present:
            print("battery_ops not found - nothing to rename")
            return 0
        if "battery_itops" in present:
            print("both battery_ops and battery_itops exist - resolve by hand")
            return 1
        cur.execute("ALTER SCHEMA battery_ops RENAME TO battery_itops")
        cur.execute("SELECT count(*) FROM battery_itops.activity_log")
        print(f"renamed battery_ops -> battery_itops ({cur.fetchone()[0]} activity rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
