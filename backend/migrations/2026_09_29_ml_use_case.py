"""Tag model runs with their ML use case (the ML service now has one package per use case).

    python 2026_09_29_ml_use_case.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_29_ml_use_case.py --commit   # run for real

use_case   the use case that trained the run ('soh' = SOH estimation); existing runs are all SOH runs
One run per use case can be active (was: one run overall).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    "ALTER TABLE battery_ml.model_run ADD COLUMN use_case text NOT NULL DEFAULT 'soh'",
    "DROP INDEX battery_ml.model_run_one_active",
    "CREATE UNIQUE INDEX model_run_one_active ON battery_ml.model_run (use_case) WHERE is_active",
    "CREATE INDEX idx_model_run_use_case ON battery_ml.model_run (use_case, run_id DESC)",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("SELECT use_case, count(*), count(*) FILTER (WHERE is_active) FROM battery_ml.model_run GROUP BY 1")
    print("   runs per use case (total, active):", cur.fetchall())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
