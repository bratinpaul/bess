"""Multivariate anomaly detection (ML service use case /mv-anomaly): runs, per-interval scores and the alarm view.

    python 2026_10_14_mv_anomaly.py            # rehearsal: create, verify, ROLLBACK
    python 2026_10_14_mv_anomaly.py --commit   # for real

battery_ml.mv_anomaly_run     one row per model build (run_kind 'train'), per scoring of another window with a built
                              model ('score') and per model's rolling live scores ('live', the micro-batch target)
battery_ml.mv_anomaly_score   per (run, system, 5-min ts): anomaly_score (primary model, 1.0 = threshold), smoothed
                              score, is_anomaly (debounced model flag OR a frozen / missing sensor rule), the rule flags,
                              every model's score and the top contributing features - a TimescaleDB hypertable on ts
battery_ml.v_mv_anomaly_alarm the scores next to the alarm_event rows active at that ts (evaluation / explanation)
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

DDL = """
CREATE TABLE IF NOT EXISTS battery_ml.mv_anomaly_run (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_name        text,
    run_kind        text        NOT NULL DEFAULT 'train' CHECK (run_kind IN ('train', 'score', 'live')),
    parent_run_id   bigint      REFERENCES battery_ml.mv_anomaly_run (run_id) ON DELETE CASCADE,
    status          text        NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    is_default      boolean     NOT NULL DEFAULT false,   -- the system's model for live scoring
    system_id       bigint      NOT NULL REFERENCES battery_master.battery_system (battery_system_id) ON DELETE CASCADE,
    date_from       date,
    date_to         date,
    eval_from       timestamptz,                          -- train runs: the evaluation window starts here
    params          jsonb       NOT NULL DEFAULT '{}',
    features        jsonb,                                -- model input features (after regime encoding)
    thresholds      jsonb,                                -- per model (and regime): raw score at the limit
    metrics         jsonb,                                -- per model: precision / recall / F1 / AUC / event recall ...
    summary         jsonb,                                -- counts: rows, train rows, excluded by reason, flags, episodes
    warnings        jsonb,
    artifact_path   text,
    error_message   text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    duration_ms     integer
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_anomaly_default ON battery_ml.mv_anomaly_run (system_id)
    WHERE is_default AND run_kind = 'train';
CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_anomaly_live ON battery_ml.mv_anomaly_run (parent_run_id)
    WHERE run_kind = 'live';
COMMENT ON TABLE battery_ml.mv_anomaly_run IS
    'Multivariate anomaly detection runs: model builds (train), scorings of other windows (score), live micro-batch target (live).';

CREATE TABLE IF NOT EXISTS battery_ml.mv_anomaly_score (
    run_id            bigint      NOT NULL REFERENCES battery_ml.mv_anomaly_run (run_id) ON DELETE CASCADE,
    system_id         bigint      NOT NULL,
    ts                timestamptz NOT NULL,
    split             text        NOT NULL,              -- train | eval | score | live
    regime            text,
    anomaly_score     double precision,                  -- primary model, normalised: 1.0 = its threshold
    score_smooth      double precision,                  -- rolling mean the flag is decided on
    model_flag        boolean     NOT NULL DEFAULT false, -- primary model above the limit for N consecutive intervals
    is_anomaly        boolean     NOT NULL DEFAULT false, -- model_flag OR a rule flag
    rule_flags        text[],                            -- e.g. frozen:pack_voltage_v, missing:igbt_temp_c
    model_scores      jsonb,                             -- every model's normalised score
    models_flagging   smallint,                          -- how many models are above their limit (smoothed)
    top_contributors  jsonb,                             -- [{feature, label, share}] of the primary model
    PRIMARY KEY (run_id, system_id, ts)
);
SELECT create_hypertable('battery_ml.mv_anomaly_score', 'ts', chunk_time_interval => interval '7 days',
                         if_not_exists => true);
CREATE INDEX IF NOT EXISTS ix_mv_anomaly_score_flag ON battery_ml.mv_anomaly_score (run_id, ts) WHERE is_anomaly;
COMMENT ON TABLE battery_ml.mv_anomaly_score IS
    'Per-interval multivariate anomaly score, flag and top contributing features (sibling of system_telemetry).';

CREATE OR REPLACE VIEW battery_ml.v_mv_anomaly_alarm AS
SELECT s.run_id, s.system_id, s.ts, s.split, s.regime, s.anomaly_score, s.score_smooth, s.model_flag, s.is_anomaly,
       s.rule_flags, s.models_flagging, s.top_contributors,
       a.alarm_count > 0                AS alarm_active,
       COALESCE(a.alarm_count, 0)       AS alarm_count,
       a.alarm_codes, a.alarm_sources, a.max_severity
FROM battery_ml.mv_anomaly_score s
LEFT JOIN LATERAL (
    SELECT count(*) AS alarm_count,
           array_agg(DISTINCT c.alarm_code) AS alarm_codes,
           array_agg(DISTINCT c.source) AS alarm_sources,
           max(e.severity_level) AS max_severity
    FROM battery_telemetry.alarm_event e
    LEFT JOIN battery_master.alarm_catalog c ON c.alarm_catalog_id = e.alarm_catalog_id
    WHERE e.battery_system_id = s.system_id
      AND e.time <= s.ts AND s.ts < COALESCE(e.end_time, e.time + interval '30 minutes')
) a ON true;
COMMENT ON VIEW battery_ml.v_mv_anomaly_alarm IS
    'Multivariate anomaly scores with the alarm_event rows active at each interval - for evaluation and explanation.';
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE '%mv_anomaly%' ORDER BY 1""")
    print("   objects:", ", ".join(r[0] for r in cur.fetchall()))
    cur.execute("""SELECT hypertable_name FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'battery_ml' AND hypertable_name = 'mv_anomaly_score'""")
    print("   hypertable:", cur.fetchone())
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
