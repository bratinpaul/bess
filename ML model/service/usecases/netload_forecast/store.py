"""Net-load forecast runs in battery_ml.netload_forecast_run / _score / _point / _peak and their model files."""
import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Engine

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "netload_forecast"

RUN_COLUMNS = """run_id, run_name, status, is_default, mp_ids, date_from, date_to, horizon_hours, test_fraction,
    origin_step_h, feature_groups, weather_source, peak_threshold_kw, models, params, n_readings, n_train_rows,
    n_test_origins, n_test_days, best_model, metrics, warnings, error_message, started_at, finished_at, duration_ms"""
SCORE_KEYS = ("n", "mae", "rmse", "mape_pct", "bias", "pinball", "coverage_pct", "width_kw", "skill_mae_pct",
              "window_mae", "peak_mae_kw", "peak_bias_kw", "peak_time_mae_min", "exceed_brier", "exceed_auc",
              "exceed_recall", "exceed_precision")


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


def _ts(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else pd.Timestamp(v).to_pydatetime()


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.netload_forecast_run (run_name, status, mp_ids, date_from, date_to, horizon_hours,
                test_fraction, origin_step_h, feature_groups, weather_source, peak_threshold_kw, models, params)
            VALUES (:run_name, 'RUNNING', :mp_ids, :date_from, :date_to, :horizon_hours, :test_fraction,
                :origin_step_h, :feature_groups, :weather_source, :peak_threshold_kw, :models, CAST(:params AS jsonb))
            RETURNING run_id"""), {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.netload_forecast_run SET status = 'FAILED', error_message = :m,
                             finished_at = now(), duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int
                             WHERE run_id = :id"""), {"id": run_id, "m": message})


def save_artifact(run_id: int, artifact: dict) -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(artifact, path)
    return str(path)


def complete_run(engine: Engine, run_id: int, summary: dict, points: pd.DataFrame, peaks: pd.DataFrame,
                 warnings: list[str], artifact: str, threshold: float) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.netload_forecast_run SET status = 'COMPLETED', n_readings = :n_readings,
                n_train_rows = :n_train_rows, n_test_origins = :n_test_origins, n_test_days = :n_test_days,
                best_model = :best_model, metrics = CAST(:metrics AS jsonb), results = CAST(:results AS jsonb),
                warnings = CAST(:warnings AS jsonb), artifact_path = :artifact, peak_threshold_kw = :threshold,
                finished_at = now(), duration_ms = :duration_ms
            WHERE run_id = :id"""), {
            "id": run_id, **{k: summary[k] for k in ("n_readings", "n_train_rows", "n_test_origins", "n_test_days",
                                                     "best_model", "duration_ms")},
            "metrics": _json(summary["metrics"]), "results": _json({**summary["results"], "features": summary["features"]}),
            "warnings": _json(warnings), "artifact": artifact, "threshold": threshold})
        conn.execute(text(f"""
            INSERT INTO battery_ml.netload_forecast_score (run_id, model, {', '.join(SCORE_KEYS)})
            VALUES (:run_id, :model, {', '.join(':' + k for k in SCORE_KEYS)})"""),
            [{"run_id": run_id, "model": m, **{k: _num(s.get(k)) for k in SCORE_KEYS}}
             for m, s in summary["metrics"].items()])
        raw = conn.connection.dbapi_connection if hasattr(conn.connection, "dbapi_connection") else conn.connection
        with raw.cursor() as cur:
            execute_values(cur, """INSERT INTO battery_ml.netload_forecast_point (run_id, mp_id, origin_ts, target_ts,
                                   step, model, p10, p50, p90, actual) VALUES %s""",
                           [(run_id, int(r.mp_id), _ts(r.origin_ts), _ts(r.target_ts), int(r.step), r.model,
                             _num(r.p10), _num(r.p50), _num(r.p90), _num(r.actual)) for r in points.itertuples()],
                           page_size=5000)
            if not peaks.empty:
                get = lambda r, c: getattr(r, c, None)  # noqa: E731
                execute_values(cur, """INSERT INTO battery_ml.netload_forecast_peak (run_id, mp_id, origin_ts,
                                       target_date, model, lead_h, p10, p50, p90, peak_ts, prob_exceed, actual,
                                       actual_ts, threshold_kw) VALUES %s""",
                               [(run_id, int(r.mp_id), _ts(r.origin_ts), r.target_date, r.model, _num(get(r, "lead_h")),
                                 _num(get(r, "p10")), _num(get(r, "p50")), _num(get(r, "p90")), _ts(get(r, "peak_ts")),
                                 _num(get(r, "prob_exceed")), _num(get(r, "actual")), _ts(get(r, "actual_ts")),
                                 _num(get(r, "threshold_kw"))) for r in peaks.itertuples()], page_size=2000)


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {RUN_COLUMNS} FROM battery_ml.netload_forecast_run ORDER BY run_id DESC LIMIT :l"), {"l": limit})]


def get_run(engine: Engine, run_id: int, full: bool = True) -> Optional[dict]:
    extra = ", results, artifact_path" if full else ", artifact_path"
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}{extra} FROM battery_ml.netload_forecast_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def resolve(engine: Engine, model: str) -> Optional[dict]:
    """'active' = the default run, else the latest completed one; or a run id."""
    if model == "active":
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT run_id FROM battery_ml.netload_forecast_run WHERE status = 'COMPLETED'
                                       ORDER BY is_default DESC, run_id DESC LIMIT 1""")).first()
        if not row:
            return None
        model = str(row[0])
    if not str(model).isdigit():
        return None
    run = get_run(engine, int(model))
    return run if run and run["status"] == "COMPLETED" else None


def origins(engine: Engine, run_id: int, mp_id: int) -> list[str]:
    with engine.connect() as conn:
        return [r[0].isoformat() for r in conn.execute(text("""
            SELECT DISTINCT origin_ts FROM battery_ml.netload_forecast_point WHERE run_id = :r AND mp_id = :m
            ORDER BY 1"""), {"r": run_id, "m": mp_id})]


def backtest(engine: Engine, run_id: int, mp_id: int, origin_ts) -> tuple[list[dict], list[dict]]:
    with engine.connect() as conn:
        pts = [_row(r) for r in conn.execute(text("""
            SELECT model, step, target_ts, p10, p50, p90, actual FROM battery_ml.netload_forecast_point
            WHERE run_id = :r AND mp_id = :m AND origin_ts = :o ORDER BY model, step"""),
            {"r": run_id, "m": mp_id, "o": origin_ts})]
        pks = [_row(r) for r in conn.execute(text("""
            SELECT model, target_date, lead_h, p10, p50, p90, peak_ts, prob_exceed, actual, actual_ts, threshold_kw
            FROM battery_ml.netload_forecast_peak WHERE run_id = :r AND mp_id = :m AND origin_ts = :o
            ORDER BY target_date, model"""), {"r": run_id, "m": mp_id, "o": origin_ts})]
    for p in pks:
        p["target_date"] = p["target_date"].isoformat()
    return pts, pks


def peak_table(engine: Engine, run_id: int, mp_id: int) -> list[dict]:
    """Every backtest peak forecast of a run (for the day-by-day table)."""
    with engine.connect() as conn:
        rows = [_row(r) for r in conn.execute(text("""
            SELECT model, origin_ts, target_date, lead_h, p10, p50, p90, peak_ts, prob_exceed, actual, actual_ts
            FROM battery_ml.netload_forecast_peak WHERE run_id = :r AND mp_id = :m ORDER BY target_date, origin_ts, model"""),
            {"r": run_id, "m": mp_id})]
    for p in rows:
        p["target_date"] = p["target_date"].isoformat()
    return rows


def scores(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT s.* FROM battery_ml.netload_forecast_score s JOIN battery_ml.netload_forecast_run r USING (run_id)
            WHERE r.status = 'COMPLETED' ORDER BY s.run_id DESC, s.model"""))]


def set_default(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM battery_ml.netload_forecast_run WHERE run_id = :id AND status = 'COMPLETED'"),
                            {"id": run_id}).first():
            return False
        conn.execute(text("UPDATE battery_ml.netload_forecast_run SET is_default = false WHERE is_default"))
        conn.execute(text("UPDATE battery_ml.netload_forecast_run SET is_default = true WHERE run_id = :id"), {"id": run_id})
    return True


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.netload_forecast_run WHERE run_id = :id RETURNING artifact_path"),
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
