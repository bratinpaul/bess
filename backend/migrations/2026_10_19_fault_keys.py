"""Natural keys for the fault tables with generated ids, so bulk re-uploads update instead of duplicating.

    python 2026_10_19_fault_keys.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_19_fault_keys.py --commit   # run for real

fault_signature   unique (fault_code, signal)                                - one rule per symptom and fault
fault_prediction  unique (model_version, system_id, asset_code, predicted_at) - one score per model run and asset
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_fault_signature_code_signal
    ON battery_master.fault_signature (fault_code, signal);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fault_prediction_natural
    ON battery_master.fault_prediction (model_version, system_id, asset_code, predicted_at);
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("""SELECT indexname FROM pg_indexes WHERE schemaname = 'battery_master'
                           AND indexname IN ('uq_fault_signature_code_signal', 'uq_fault_prediction_natural')""")
            print("indexes:", [r[0] for r in cur.fetchall()])
        if commit:
            conn.commit()
            print("committed")
        else:
            conn.rollback()
            print("rolled back (rehearsal) - pass --commit to apply")
    finally:
        conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
