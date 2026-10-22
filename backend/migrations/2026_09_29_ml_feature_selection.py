"""Add feature selection to battery_ml.model_run.

    python 2026_09_29_ml_feature_selection.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_29_ml_feature_selection.py --commit   # run for real

min_importance_pct    a feature must bring at least this share of the importance to be kept (0 = all kept)
importance_method     gain or permutation (what the screening fit measured)
candidate_features    the features offered (from the chosen feature groups); `features` holds the kept ones
selection_importance  the screening importance share of every candidate
Runs trained before this change used all their features: candidate_features = features, threshold 0.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """ALTER TABLE battery_ml.model_run
        ADD COLUMN min_importance_pct   numeric NOT NULL DEFAULT 0,
        ADD COLUMN importance_method    text,
        ADD COLUMN candidate_features   text[],
        ADD COLUMN selection_importance jsonb""",
    "UPDATE battery_ml.model_run SET candidate_features = features WHERE candidate_features IS NULL",
    """ALTER TABLE battery_ml.model_run ADD CONSTRAINT model_run_threshold
        CHECK (min_importance_pct >= 0 AND min_importance_pct < 100)""",
    """ALTER TABLE battery_ml.model_run ADD CONSTRAINT model_run_importance_method
        CHECK (importance_method IS NULL OR importance_method IN ('gain', 'permutation'))""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("SELECT run_id, cardinality(features), cardinality(candidate_features), min_importance_pct FROM battery_ml.model_run ORDER BY run_id")
    print("   runs:", cur.fetchall())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
