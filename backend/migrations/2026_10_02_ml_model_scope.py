"""Plant-aware model runs: a run is a base model (plant-agnostic, trained on several battery systems) or a battery
system model (one plant; trained from scratch or fine-tuned from a base run).

    python 2026_10_02_ml_model_scope.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_02_ml_model_scope.py --commit   # run for real

scope              'base' | 'system'
site_id            the plant's site (system runs)
battery_system_id  the plant (system runs; NULL for base runs)
training_mode      'scratch' | 'finetune' (system runs fine-tuned from a base run)
parent_run_id      the base run a fine-tuned run started from
systems            the battery systems whose rows the run trained on (NULL on runs from before: every system then)
holdout_system_id  a base run's held-out battery system (never trained on; scored separately)
metrics_by_system  test scores per battery system {system_id: {n, r2, rmse, mae, ...}}
holdout_metrics    scores on the held-out battery system's rows

One default ("active") run per use case and scope: one base default, and one per battery system (was: one per use
case). Existing runs were trained on every system together, so they become base runs (run #20 stays the default).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """ALTER TABLE battery_ml.model_run
         ADD COLUMN scope text NOT NULL DEFAULT 'base',
         ADD COLUMN site_id bigint,
         ADD COLUMN battery_system_id bigint,
         ADD COLUMN training_mode text NOT NULL DEFAULT 'scratch',
         ADD COLUMN parent_run_id bigint REFERENCES battery_ml.model_run (run_id) ON DELETE SET NULL,
         ADD COLUMN systems bigint[],
         ADD COLUMN holdout_system_id bigint,
         ADD COLUMN metrics_by_system jsonb,
         ADD COLUMN holdout_metrics jsonb""",
    """ALTER TABLE battery_ml.model_run
         ADD CONSTRAINT model_run_scope CHECK (scope IN ('base', 'system')),
         ADD CONSTRAINT model_run_training_mode CHECK (training_mode IN ('scratch', 'finetune')),
         ADD CONSTRAINT model_run_scope_system CHECK (
             (scope = 'base' AND battery_system_id IS NULL) OR (scope = 'system' AND battery_system_id IS NOT NULL)),
         ADD CONSTRAINT model_run_finetune_parent CHECK (training_mode = 'scratch' OR scope = 'system')""",
    "DROP INDEX battery_ml.model_run_one_active",
    """CREATE UNIQUE INDEX model_run_one_active ON battery_ml.model_run (use_case, COALESCE(battery_system_id, 0))
         WHERE is_active""",
    "CREATE INDEX idx_model_run_system ON battery_ml.model_run (use_case, battery_system_id, run_id DESC)",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT use_case, scope, count(*), count(*) FILTER (WHERE is_active) FROM battery_ml.model_run
                   GROUP BY 1, 2 ORDER BY 1, 2""")
    print("   runs per use case / scope (total, active):", cur.fetchall())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
