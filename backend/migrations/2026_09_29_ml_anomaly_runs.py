"""Weak module detection (anomaly) runs in battery_ml.

    python 2026_09_29_ml_anomaly_runs.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_29_ml_anomaly_runs.py --commit   # run for real

anomaly_run            one detection run: the system, window, grain, features, Isolation Forest / DBSCAN settings,
                       counts and the saved model file. run_kind 'train' fits the models on its window; 'score'
                       applies a train run's saved Isolation Forest (and its DBSCAN settings) to a new window.
anomaly_module_result  per module of a run: verdict (WEAK = flagged by both models, SUSPECT = by one, NORMAL),
                       combined score and rank, each model's share of anomalous days, feature means and the reasons.
anomaly_point          per module and time bucket (e.g. module-day): the feature values, the Isolation Forest score
                       and flag, and the DBSCAN label (-1 = noise) - for the scatter and the drill-down.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """CREATE TABLE battery_ml.anomaly_run (
        run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case          text        NOT NULL DEFAULT 'weak_module',
        run_kind          text        NOT NULL DEFAULT 'train',
        parent_run_id     bigint      REFERENCES battery_ml.anomaly_run (run_id) ON DELETE SET NULL,
        run_name          text,
        status            text        NOT NULL,
        battery_system_id bigint      NOT NULL REFERENCES battery_master.battery_system (battery_system_id) ON DELETE CASCADE,
        system_name       text        NOT NULL,
        date_from         date,
        date_to           date,
        grain             text        NOT NULL,
        feature_groups    text[]      NOT NULL,
        features          text[]      NOT NULL,
        params            jsonb       NOT NULL DEFAULT '{}',
        n_rows            integer,
        n_modules         integer,
        n_packs           integer,
        if_anomalies      integer,
        db_noise          integer,
        db_clusters       integer,
        eps_used          numeric,
        silhouette        numeric,
        n_weak            integer,
        n_suspect         integer,
        feature_stats     jsonb,
        warnings          jsonb       NOT NULL DEFAULT '[]',
        error_message     text,
        artifact_path     text,
        started_at        timestamptz NOT NULL DEFAULT now(),
        finished_at       timestamptz,
        duration_ms       integer,
        CONSTRAINT anomaly_run_kind CHECK (run_kind IN ('train', 'score')),
        CONSTRAINT anomaly_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
        CONSTRAINT anomaly_run_grain CHECK (grain IN ('hour', 'day'))
    )""",
    "CREATE INDEX idx_anomaly_run_system ON battery_ml.anomaly_run (battery_system_id, run_id DESC)",
    """CREATE TABLE battery_ml.anomaly_module_result (
        run_id            bigint   NOT NULL REFERENCES battery_ml.anomaly_run (run_id) ON DELETE CASCADE,
        module_id         bigint   NOT NULL,
        serial_number     text,
        pack_id           bigint,
        pack_number       text,
        position          integer,
        verdict           text     NOT NULL,
        combined_score    numeric  NOT NULL,
        rank              integer  NOT NULL,
        n_points          integer  NOT NULL,
        if_score_mean     numeric,
        if_anomaly_share  numeric,
        db_noise_share    numeric,
        if_flag           boolean  NOT NULL,
        db_flag           boolean  NOT NULL,
        feature_means     jsonb    NOT NULL DEFAULT '{}',
        reasons           jsonb    NOT NULL DEFAULT '[]',
        first_anomaly     timestamptz,
        PRIMARY KEY (run_id, module_id),
        CONSTRAINT anomaly_verdict CHECK (verdict IN ('WEAK', 'SUSPECT', 'NORMAL'))
    )""",
    """CREATE TABLE battery_ml.anomaly_point (
        run_id     bigint      NOT NULL REFERENCES battery_ml.anomaly_run (run_id) ON DELETE CASCADE,
        module_id  bigint      NOT NULL,
        bucket     timestamptz NOT NULL,
        features   jsonb       NOT NULL,
        if_score   numeric,
        if_flag    boolean,
        db_label   integer,
        PRIMARY KEY (run_id, module_id, bucket)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'anomaly%' ORDER BY 1""")
    print("   tables:", [r[0] for r in cur.fetchall()])
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
