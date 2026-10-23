"""Thermal forecast runs in battery_ml.thermal_forecast_run / _score / _point and their model files (one joblib per
run: the per-asset RC registry, the per-target quantile models, profiles and thresholds)."""
import json
from pathlib import Path
from typing import Optional

import joblib
from psycopg2.extras import execute_values
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import ArtifactMissing

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "thermal_forecast"

RUN_COLUMNS = """run_id, run_name, status, is_default, system_ids, date_from, date_to, targets, horizons_min,
    test_fraction, params, n_train_rows, n_test_rows, metrics, warnings, error_message, started_at, finished_at,
    duration_ms"""
SCORE_KEYS = ("n", "mae", "rmse", "pinball", "coverage_pct", "threshold_c", "events", "recall_p50", "precision_p50",
              "recall_p90", "precision_p90")


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
            INSERT INTO battery_ml.thermal_forecast_run (run_name, status, system_ids, date_from, date_to, targets,
                horizons_min, test_fraction, params)
            VALUES (:run_name, 'RUNNING', :system_ids, :date_from, :date_to, :targets, :horizons_min, :test_fraction,
                CAST(:params AS jsonb))
            RETURNING run_id"""), {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.thermal_forecast_run SET status = 'FAILED', error_message = :m,
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
            UPDATE battery_ml.thermal_forecast_run SET status = 'COMPLETED', n_train_rows = :n_train_rows,
                n_test_rows = :n_test_rows, metrics = CAST(:metrics AS jsonb), results = CAST(:results AS jsonb),
                warnings = CAST(:warnings AS jsonb), artifact_path = :artifact, finished_at = now(),
                duration_ms = :duration_ms
            WHERE run_id = :id"""), {
            "id": run_id, "n_train_rows": summary["n_train_rows"], "n_test_rows": summary["n_test_rows"],
            "metrics": _json(summary["metrics"]), "results": _json(summary["results"]), "warnings": _json(warnings),
            "artifact": artifact, "duration_ms": summary["duration_ms"]})
        conn.execute(text(f"""
            INSERT INTO battery_ml.thermal_forecast_score (run_id, target, horizon_min, method, {', '.join(SCORE_KEYS)})
            VALUES (:run_id, :target, :horizon_min, :method, {', '.join(':' + k for k in SCORE_KEYS)})"""),
            [{"run_id": run_id, "target": t, "horizon_min": int(h), "method": m, **{k: _num(s.get(k)) for k in SCORE_KEYS}}
             for t, by_h in summary["metrics"].items() for h, by_m in by_h.items() for m, s in by_m.items()])
    # the backtest points in batches (one INSERT per page, not per row)
    recs = points.assign(origin_ts=lambda d: pd.to_datetime(d["origin_ts"]))
    values = [(run_id, r.target, int(r.system_id), r.origin_ts.to_pydatetime(), int(r.horizon_min), r.method,
               _num(r.p10), _num(r.p50), _num(r.p90), _num(r.actual), _num(r.now_c)) for r in recs.itertuples()]
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(cur, """INSERT INTO battery_ml.thermal_forecast_point (run_id, target, system_id, origin_ts,
                               horizon_min, method, p10, p50, p90, actual, now_c) VALUES %s""", values, page_size=5000)
        raw.commit()
    finally:
        raw.close()


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {RUN_COLUMNS} FROM battery_ml.thermal_forecast_run ORDER BY run_id DESC LIMIT :l"), {"l": limit})]


def get_run(engine: Engine, run_id: int, full: bool = True) -> Optional[dict]:
    extra = ", results, artifact_path" if full else ", artifact_path"
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}{extra} FROM battery_ml.thermal_forecast_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def resolve(engine: Engine, model: str) -> Optional[dict]:
    if model == "active":
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT run_id FROM battery_ml.thermal_forecast_run WHERE status = 'COMPLETED'
                                       ORDER BY is_default DESC, run_id DESC LIMIT 1""")).first()
        if not row:
            return None
        model = str(row[0])
    if not str(model).isdigit():
        return None
    run = get_run(engine, int(model))
    return run if run and run["status"] == "COMPLETED" else None


def series(engine: Engine, run_id: int, system_id: int, target: str, horizon_min: int, methods: list[str]) -> list[dict]:
    """Backtest forecasts of one target / system / horizon over the test period (target time = origin + horizon)."""
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT method, origin_ts + make_interval(mins => horizon_min) AS target_ts, p10, p50, p90, actual, now_c
            FROM battery_ml.thermal_forecast_point
            WHERE run_id = :r AND system_id = :s AND target = :t AND horizon_min = :h AND method = ANY(:m)
            ORDER BY method, origin_ts"""), {"r": run_id, "s": system_id, "t": target, "h": horizon_min, "m": methods})]


def set_default(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM battery_ml.thermal_forecast_run WHERE run_id = :id AND status = 'COMPLETED'"),
                            {"id": run_id}).first():
            return False
        conn.execute(text("UPDATE battery_ml.thermal_forecast_run SET is_default = false WHERE is_default"))
        conn.execute(text("UPDATE battery_ml.thermal_forecast_run SET is_default = true WHERE run_id = :id"), {"id": run_id})
    return True


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.thermal_forecast_run WHERE run_id = :id RETURNING artifact_path"),
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
        raise ArtifactMissing(f"The model file of run #{run['run_id']} is missing. Retrain the model.")
    if path not in _cache:
        _cache[path] = joblib.load(path)
    return _cache[path]
