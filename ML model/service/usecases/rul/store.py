"""RUL runs in battery_ml.rul_run / _score / _backtest / _forecast and their model files (one joblib per run: the
per-chemistry physics, quantile and survival models)."""
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

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "rul"

RUN_COLUMNS = """run_id, run_name, status, is_default, system_ids, methods, params, n_units, n_rows, metrics, warnings,
    error_message, started_at, finished_at, duration_ms"""
SCORE_KEYS = ("n", "mae_days", "rmse_days", "bias_days", "mae_cycles", "coverage_pct", "pinball_days", "c_index",
              "censored_violation_pct", "oracle_mae_days")


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
        return str(o)
    return json.dumps(v, default=default)


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
        elif hasattr(v, "isoformat") and k in ("snapshot_date", "as_of", "eol_date_p50"):
            out[k] = v.isoformat()
    return out


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.rul_run (run_name, status, system_ids, methods, params)
            VALUES (:run_name, 'RUNNING', :system_ids, :methods, CAST(:params AS jsonb)) RETURNING run_id"""),
            {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.rul_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message})


def save_artifact(run_id: int, artifact: dict) -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(artifact, path)
    return str(path)


def complete_run(engine: Engine, run_id: int, summary: dict, bt: pd.DataFrame, fc: pd.DataFrame, warnings: list[str],
                 artifact: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.rul_run SET status = 'COMPLETED', n_units = :n_units, n_rows = :n_rows,
                metrics = CAST(:metrics AS jsonb), results = CAST(:results AS jsonb), warnings = CAST(:warnings AS jsonb),
                artifact_path = :artifact, finished_at = now(), duration_ms = :duration_ms
            WHERE run_id = :id"""), {
            "id": run_id, "n_units": summary["n_units"], "n_rows": summary["n_rows"],
            "metrics": _json(summary["metrics"]), "results": _json(summary["results"]), "warnings": _json(warnings),
            "artifact": artifact, "duration_ms": summary["duration_ms"]})
        conn.execute(text(f"""
            INSERT INTO battery_ml.rul_score (run_id, method, scope, {', '.join(SCORE_KEYS)})
            VALUES (:run_id, :method, :scope, {', '.join(':' + k for k in SCORE_KEYS)})"""),
            [{"run_id": run_id, "method": m, "scope": sc, **{k: _num(s.get(k)) for k in SCORE_KEYS}}
             for m, by in summary["metrics"].items() for sc, s in by.items()])
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(cur, """INSERT INTO battery_ml.rul_backtest (run_id, system_id, snapshot_date, method, p10_days,
                               p50_days, p90_days, p50_cycles, beyond, actual_days, actual_cycles, known_alive_days,
                               censored) VALUES %s""",
                           [(run_id, int(r.system_id), r.snapshot_date.date(), r.method, _num(r.p10_days), _num(r.p50_days),
                             _num(r.p90_days), _num(r.p50_cycles), bool(r.beyond), _num(r.rul_days), _num(r.rul_cycles),
                             _num(r.known_alive_days), not bool(r.retired)) for r in bt.itertuples()], page_size=5000)
            if not fc.empty:
                execute_values(cur, """INSERT INTO battery_ml.rul_forecast (run_id, system_id, method, as_of, soh_pct,
                                   resistance_ratio, p10_days, p50_days, p90_days, p10_cycles, p50_cycles, p90_cycles,
                                   eol_date_p50, trigger, beyond) VALUES %s""",
                               [(run_id, int(r.system_id), r.method, r.snapshot_date.date(), _num(r.soh_pct), _num(r.r_ratio),
                                 _num(r.p10_days), _num(r.p50_days), _num(r.p90_days), _num(r.p10_cycles), _num(r.p50_cycles),
                                 _num(r.p90_cycles), (r.snapshot_date + pd.Timedelta(days=float(r.p50_days))).date(),
                                 str(r.trigger), bool(r.beyond)) for r in fc.itertuples()])
        raw.commit()
    finally:
        raw.close()


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {RUN_COLUMNS} FROM battery_ml.rul_run ORDER BY run_id DESC LIMIT :l"), {"l": limit})]


def get_run(engine: Engine, run_id: int, full: bool = True) -> Optional[dict]:
    extra = ", results, artifact_path" if full else ", artifact_path"
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}{extra} FROM battery_ml.rul_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def resolve(engine: Engine, model: str) -> Optional[dict]:
    if model == "active":
        with engine.connect() as conn:
            row = conn.execute(text("""SELECT run_id FROM battery_ml.rul_run WHERE status = 'COMPLETED'
                                       ORDER BY is_default DESC, run_id DESC LIMIT 1""")).first()
        if not row:
            return None
        model = str(row[0])
    if not str(model).isdigit():
        return None
    run = get_run(engine, int(model))
    return run if run and run["status"] == "COMPLETED" else None


def forecasts(engine: Engine, run_id: int) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT f.*, b.system_name AS system_code FROM battery_ml.rul_forecast f
            JOIN battery_master.battery_system b ON b.battery_system_id = f.system_id
            WHERE f.run_id = :r ORDER BY b.system_name, f.method"""), {"r": run_id})]


def backtest(engine: Engine, run_id: int, system_id: int, methods: list[str]) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT system_id, snapshot_date, method, p10_days, p50_days, p90_days, p50_cycles, beyond, actual_days,
                   actual_cycles, known_alive_days, censored
            FROM battery_ml.rul_backtest WHERE run_id = :r AND system_id = :s AND method = ANY(:m)
            ORDER BY method, snapshot_date"""), {"r": run_id, "s": system_id, "m": methods})]


def set_default(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM battery_ml.rul_run WHERE run_id = :id AND status = 'COMPLETED'"),
                            {"id": run_id}).first():
            return False
        conn.execute(text("UPDATE battery_ml.rul_run SET is_default = false WHERE is_default"))
        conn.execute(text("UPDATE battery_ml.rul_run SET is_default = true WHERE run_id = :id"), {"id": run_id})
    return True


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.rul_run WHERE run_id = :id RETURNING artifact_path"),
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
