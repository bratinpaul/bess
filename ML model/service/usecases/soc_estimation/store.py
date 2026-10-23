"""SOC estimation runs in battery_ml.soc_estimation_run / _score / _point / _state and their model files."""
import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import ArtifactMissing

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "soc_estimation"

RUN_COLUMNS = """run_id, run_name, status, is_default, system_ids, date_from, date_to, test_fraction, label_source,
    params, n_train_rows, n_test_rows, n_test_anchors, best_method, primary_scope, metrics, warnings, error_message,
    started_at, finished_at, duration_ms"""
SCORE_KEYS = ("n", "rmse", "mae", "bias", "max_error", "p95_abs", "coverage_pct", "width", "skill_pct")
POINT_COLUMNS = ["truth", "anchor", "anchor_method", "coulomb", "ocv_lookup", "bms", "ekf", "ekf_p10", "ekf_p90", "gbm",
                 "gbm_p10", "gbm_p90", "hybrid", "hybrid_p10", "hybrid_p90", "ekf_bias", "ekf_gain", "recal_kind",
                 "at_rest"]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _json(v) -> str:
    return json.dumps(v, default=lambda o: _num(o) if isinstance(o, (np.floating, np.integer)) else str(o))


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.soc_estimation_run (run_name, status, system_ids, date_from, date_to, test_fraction,
                label_source, params)
            VALUES (:run_name, 'RUNNING', :system_ids, :date_from, :date_to, :test_fraction, :label_source,
                CAST(:params AS jsonb))
            RETURNING run_id"""), {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.soc_estimation_run SET status = 'FAILED', error_message = :m,
                             finished_at = now(), duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int
                             WHERE run_id = :id"""), {"id": run_id, "m": message})


def save_artifact(run_id: int, artifact: dict) -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(artifact, path)
    return str(path)


def complete_run(engine: Engine, run_id: int, summary: dict, points: pd.DataFrame, warnings: list[str], artifact: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.soc_estimation_run SET status = 'COMPLETED', n_train_rows = :n_train_rows,
                n_test_rows = :n_test_rows, n_test_anchors = :n_test_anchors, best_method = :best_method,
                primary_scope = :primary_scope, label_source = :label_source, metrics = CAST(:metrics AS jsonb),
                results = CAST(:results AS jsonb), warnings = CAST(:warnings AS jsonb), artifact_path = :artifact,
                finished_at = now(), duration_ms = :duration_ms
            WHERE run_id = :id"""), {
            "id": run_id, **{k: summary[k] for k in ("n_train_rows", "n_test_rows", "n_test_anchors", "best_method",
                                                     "primary_scope", "label_source", "duration_ms")},
            "metrics": _json(summary["metrics"]), "results": _json(summary["results"]),
            "warnings": _json(warnings), "artifact": artifact})
        conn.execute(text(f"""
            INSERT INTO battery_ml.soc_estimation_score (run_id, method, scope, {', '.join(SCORE_KEYS)})
            VALUES (:run_id, :method, :scope, {', '.join(':' + k for k in SCORE_KEYS)})"""),
            [{"run_id": run_id, "method": m, "scope": s, **{k: _num(v.get(k)) for k in SCORE_KEYS}}
             for m, scopes in summary["metrics"].items() for s, v in scopes.items()])
    values = []
    for ts, r in zip(points.index, points.itertuples(index=False)):
        d = r._asdict()
        values.append((run_id, int(d["system_id"]), ts.to_pydatetime(), bool(d["is_test"]),
                       *[(d[c] if isinstance(d[c], str) else None) if c in ("anchor_method", "recal_kind")
                         else (bool(d[c]) if c == "at_rest" else _num(d[c])) for c in POINT_COLUMNS]))
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(cur, f"""INSERT INTO battery_ml.soc_estimation_point (run_id, system_id, ts, is_test,
                               {', '.join(POINT_COLUMNS)}) VALUES %s""", values, page_size=5000)
        raw.commit()
    finally:
        raw.close()


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {RUN_COLUMNS} FROM battery_ml.soc_estimation_run ORDER BY run_id DESC LIMIT :l"), {"l": limit})]


def get_run(engine: Engine, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}, results, artifact_path FROM battery_ml.soc_estimation_run "
                                "WHERE run_id = :id"), {"id": run_id}).first()
    return _row(row) if row else None


def resolve(engine: Engine, model: str) -> Optional[dict]:
    """'active' = the default run, else the latest completed one; or a run id."""
    if model == "active":
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT run_id FROM battery_ml.soc_estimation_run WHERE status = 'COMPLETED'
                                       ORDER BY is_default DESC, run_id DESC LIMIT 1""")).first()
        if not row:
            return None
        model = str(row[0])
    if not str(model).isdigit():
        return None
    run = get_run(engine, int(model))
    return run if run and run["status"] == "COMPLETED" else None


def points(engine: Engine, run_id: int, system_id: int, ts_from=None, ts_to=None) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT ts, is_test, {', '.join(POINT_COLUMNS)} FROM battery_ml.soc_estimation_point
            WHERE run_id = :r AND system_id = :s
              AND (CAST(:f AS timestamptz) IS NULL OR ts >= CAST(:f AS timestamptz))
              AND (CAST(:t AS timestamptz) IS NULL OR ts <= CAST(:t AS timestamptz))
            ORDER BY ts"""), {"r": run_id, "s": system_id, "f": ts_from, "t": ts_to})
        out = []
        for r in rows:
            d = _row(r)
            d["ts"] = d["ts"].isoformat()
            out.append(d)
        return out


def point_range(engine: Engine, run_id: int, system_id: int) -> dict:
    with engine.connect() as conn:
        r = conn.execute(text("""SELECT min(ts), max(ts), min(ts) FILTER (WHERE is_test) FROM battery_ml.soc_estimation_point
                                 WHERE run_id = :r AND system_id = :s"""), {"r": run_id, "s": system_id}).first()
    return {"from": r[0].isoformat() if r[0] else None, "to": r[1].isoformat() if r[1] else None,
            "test_from": r[2].isoformat() if r[2] else None}


def set_default(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM battery_ml.soc_estimation_run WHERE run_id = :id AND status = 'COMPLETED'"),
                            {"id": run_id}).first():
            return False
        conn.execute(text("UPDATE battery_ml.soc_estimation_run SET is_default = false WHERE is_default"))
        conn.execute(text("UPDATE battery_ml.soc_estimation_run SET is_default = true WHERE run_id = :id"), {"id": run_id})
    return True


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.soc_estimation_run WHERE run_id = :id RETURNING artifact_path"),
                           {"id": run_id}).first()
    if row is None:
        return False
    if row[0]:
        Path(row[0]).unlink(missing_ok=True)
        _cache.pop(row[0], None)
    return True


# ---------------------------------------------------------------- live EKF state


def get_state(engine: Engine, run_id: int, system_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text("""SELECT state, updated_at FROM battery_ml.soc_estimation_state
                                   WHERE run_id = :r AND system_id = :s"""), {"r": run_id, "s": system_id}).first()
    return {**row[0], "updated_at": row[1].isoformat()} if row else None


def save_state(engine: Engine, run_id: int, system_id: int, state: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO battery_ml.soc_estimation_state (run_id, system_id, state_ts, state)
            VALUES (:r, :s, :ts, CAST(:st AS jsonb))
            ON CONFLICT (run_id, system_id) DO UPDATE SET state_ts = EXCLUDED.state_ts, state = EXCLUDED.state,
                updated_at = now()"""), {"r": run_id, "s": system_id, "ts": state["ts"], "st": _json(state)})


def clear_state(engine: Engine, run_id: int, system_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM battery_ml.soc_estimation_state WHERE run_id = :r AND system_id = :s"),
                     {"r": run_id, "s": system_id})


_cache: dict[str, dict] = {}


def load_artifact(run: dict) -> dict:
    path = run.get("artifact_path")
    if not path or not Path(path).exists():
        raise ArtifactMissing(f"The model file of run #{run['run_id']} is missing. Retrain the model.")
    if path not in _cache:
        _cache[path] = joblib.load(path)
    return _cache[path]
