"""Multivariate anomaly runs in battery_ml.mv_anomaly_run, per-interval scores in battery_ml.mv_anomaly_score
(hypertable; live scores are upserted) and the model files (one joblib per train run)."""
import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Engine

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "mv_anomaly"

RUN_COLUMNS = """r.run_id, r.run_name, r.run_kind, r.parent_run_id, r.status, r.is_default, r.system_id, bs.system_name,
    r.date_from, r.date_to, r.eval_from, r.params, r.summary, r.metrics, r.warnings, r.error_message, r.started_at,
    r.finished_at, r.duration_ms"""


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _json(v) -> str:
    def default(o):
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, (np.floating, np.integer)):
            return _num(o)
        if isinstance(o, pd.Timestamp):
            return o.isoformat()
        return str(o)
    return json.dumps(v, default=default)


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.mv_anomaly_run (run_name, run_kind, parent_run_id, status, system_id, date_from,
                date_to, params)
            VALUES (:run_name, :run_kind, :parent_run_id, 'RUNNING', :system_id, :date_from, :date_to,
                CAST(:params AS jsonb))
            RETURNING run_id"""), {"parent_run_id": None, **values, "params": _json(values.get("params", {}))}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.mv_anomaly_run SET status = 'FAILED', error_message = :m,
                             finished_at = now(), duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int
                             WHERE run_id = :id"""), {"id": run_id, "m": message[:2000]})


def save_artifact(run_id: int, artifact: dict) -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(artifact, path)
    return str(path)


def write_scores(engine: Engine, run_id: int, system_id: int, rows: pd.DataFrame, upsert: bool = False) -> None:
    """Bulk insert (one statement per page); live runs upsert so re-scoring a window replaces its rows."""
    if rows.empty:
        return
    conflict = """ON CONFLICT (run_id, system_id, ts) DO UPDATE SET split = EXCLUDED.split, regime = EXCLUDED.regime,
        anomaly_score = EXCLUDED.anomaly_score, score_smooth = EXCLUDED.score_smooth,
        model_flag = EXCLUDED.model_flag, is_anomaly = EXCLUDED.is_anomaly, rule_flags = EXCLUDED.rule_flags,
        model_scores = EXCLUDED.model_scores, models_flagging = EXCLUDED.models_flagging,
        top_contributors = EXCLUDED.top_contributors""" if upsert else ""
    recs = [(run_id, system_id, pd.Timestamp(r.ts).to_pydatetime(), r.split, r.regime, _num(r.anomaly_score),
             _num(r.score_smooth), bool(r.model_flag), bool(r.is_anomaly), list(r.rule_flags or []) or None,
             _json(r.model_scores), int(r.models_flagging), _json(r.top_contributors))
            for r in rows.itertuples()]
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(cur, f"""INSERT INTO battery_ml.mv_anomaly_score (run_id, system_id, ts, split, regime,
                anomaly_score, score_smooth, model_flag, is_anomaly, rule_flags, model_scores, models_flagging,
                top_contributors) VALUES %s {conflict}""", recs,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, CAST(%s AS jsonb))",
                page_size=5000)
        raw.commit()
    finally:
        raw.close()


def complete_run(engine: Engine, run_id: int, result: dict, warnings: list[str], artifact: Optional[str],
                 duration_ms: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.mv_anomaly_run SET status = 'COMPLETED', eval_from = :eval_from,
                features = CAST(:features AS jsonb), thresholds = CAST(:thresholds AS jsonb),
                metrics = CAST(:metrics AS jsonb), summary = CAST(:summary AS jsonb),
                warnings = CAST(:warnings AS jsonb), artifact_path = :artifact, finished_at = now(),
                duration_ms = :ms
            WHERE run_id = :id"""), {
            "id": run_id, "eval_from": result.get("eval_from"), "features": _json(result.get("features")),
            "thresholds": _json({"raw": result.get("thresholds"), "limits": result.get("limits")}),
            "metrics": _json(result.get("metrics")), "summary": _json(result.get("summary")),
            "warnings": _json(warnings), "artifact": artifact, "ms": duration_ms})


def list_runs(engine: Engine, system_id: Optional[int] = None, limit: int = 200) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(f"""
            SELECT {RUN_COLUMNS} FROM battery_ml.mv_anomaly_run r
            JOIN battery_master.battery_system bs ON bs.battery_system_id = r.system_id
            WHERE (CAST(:s AS bigint) IS NULL OR r.system_id = :s)
            ORDER BY r.run_id DESC LIMIT :l"""), {"s": system_id, "l": limit})]


def get_run(engine: Engine, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT {RUN_COLUMNS}, r.features, r.thresholds, r.artifact_path FROM battery_ml.mv_anomaly_run r
            JOIN battery_master.battery_system bs ON bs.battery_system_id = r.system_id
            WHERE r.run_id = :id"""), {"id": run_id}).first()
    return _row(row) if row else None


def model_run(engine: Engine, run: dict) -> Optional[dict]:
    """The train run whose model a run uses (itself for train runs)."""
    return run if run["run_kind"] == "train" else get_run(engine, run["parent_run_id"])


def default_run(engine: Engine, system_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        rid = conn.execute(text("""SELECT run_id FROM battery_ml.mv_anomaly_run
                                   WHERE system_id = :s AND run_kind = 'train' AND status = 'COMPLETED'
                                   ORDER BY is_default DESC, run_id DESC LIMIT 1"""), {"s": system_id}).scalar()
    return get_run(engine, rid) if rid else None


def default_systems(engine: Engine) -> list[int]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("""SELECT DISTINCT system_id FROM battery_ml.mv_anomaly_run
                                                    WHERE run_kind = 'train' AND status = 'COMPLETED'"""))]


def live_run(engine: Engine, parent: dict) -> int:
    """The live run of a model (created on first use) - the target of the micro-batch."""
    with engine.begin() as conn:
        rid = conn.execute(text("""SELECT run_id FROM battery_ml.mv_anomaly_run
                                   WHERE parent_run_id = :p AND run_kind = 'live'"""), {"p": parent["run_id"]}).scalar()
        if rid:
            return rid
        return conn.execute(text("""
            INSERT INTO battery_ml.mv_anomaly_run (run_name, run_kind, parent_run_id, status, system_id, params)
            VALUES (:n, 'live', :p, 'COMPLETED', :s, '{}') RETURNING run_id"""),
            {"n": f"Live scores of model #{parent['run_id']}", "p": parent["run_id"],
             "s": parent["system_id"]}).scalar_one()


def touch_live(engine: Engine, run_id: int, summary: dict, warnings: list[str], date_from, date_to) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.mv_anomaly_run SET summary = CAST(:s AS jsonb), warnings = CAST(:w AS jsonb),
                date_from = LEAST(COALESCE(date_from, CAST(:f AS date)), CAST(:f AS date)),
                date_to = GREATEST(COALESCE(date_to, CAST(:t AS date)), CAST(:t AS date)), finished_at = now()
            WHERE run_id = :id"""), {"id": run_id, "s": _json(summary), "w": _json(warnings), "f": date_from,
                                     "t": date_to})


def set_default(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("""SELECT system_id FROM battery_ml.mv_anomaly_run WHERE run_id = :id
                                   AND run_kind = 'train' AND status = 'COMPLETED'"""), {"id": run_id}).first()
        if not row:
            return False
        conn.execute(text("UPDATE battery_ml.mv_anomaly_run SET is_default = false WHERE system_id = :s AND is_default"),
                     {"s": row[0]})
        conn.execute(text("UPDATE battery_ml.mv_anomaly_run SET is_default = true WHERE run_id = :id"), {"id": run_id})
    return True


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.mv_anomaly_run WHERE run_id = :id RETURNING artifact_path"),
                           {"id": run_id}).first()
    if row is None:
        return False
    if row[0]:
        Path(row[0]).unlink(missing_ok=True)
        _cache.pop(row[0], None)
    return True


_cache: dict[str, dict] = {}


def load_artifact(run: dict) -> dict:
    path = run.get("artifact_path")
    if not path or not Path(path).exists():
        raise FileNotFoundError(f"The model file of run #{run['run_id']} is missing")
    if path not in _cache:
        _cache[path] = joblib.load(path)
    return _cache[path]


# --- reads for the results viewer ------------------------------------------------------------------------------------

def score_frame(engine: Engine, run_id: int, start=None, end=None) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT ts, split, regime, anomaly_score, score_smooth, model_flag, is_anomaly, rule_flags, model_scores,
                   models_flagging, top_contributors
            FROM battery_ml.mv_anomaly_score
            WHERE run_id = :r AND (CAST(:a AS timestamptz) IS NULL OR ts >= :a)
              AND (CAST(:b AS timestamptz) IS NULL OR ts < :b)
            ORDER BY ts"""), conn, params={"r": run_id, "a": start, "b": end})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Kolkata")
        df["rule_flags"] = df["rule_flags"].map(lambda v: list(v) if v is not None else [])
    return df


def timeline(df: pd.DataFrame, max_points: int) -> list[dict]:
    """Chart series: every flagged interval kept, the rest thinned to ~max_points (max score per bucket)."""
    if df.empty:
        return []
    keep = df["is_anomaly"].to_numpy().copy()
    step = max(1, int(np.ceil(len(df) / max_points)))
    if step > 1:
        bucket = np.arange(len(df)) // step
        s = df["score_smooth"].fillna(-1).to_numpy()
        best = pd.Series(s).groupby(bucket).idxmax().to_numpy()
        keep[best] = True
    else:
        keep[:] = True
    sub = df[keep]
    return [{"ts": r.ts.isoformat(), "score": _num(r.anomaly_score), "smooth": _num(r.score_smooth),
             "flag": bool(r.is_anomaly), "model_flag": bool(r.model_flag), "rules": r.rule_flags,
             "models": r.model_scores, "n_models": int(r.models_flagging) if r.models_flagging is not None else 0,
             "regime": r.regime, "split": r.split}
            for r in sub.itertuples()]
