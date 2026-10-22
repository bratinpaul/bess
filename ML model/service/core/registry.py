"""Model runs in battery_ml.model_run / model_run_curve, their model files, and the default runs.

A run row is written as RUNNING before training starts and completed (scores, curve, importance, test
predictions, model file) or marked FAILED afterwards. Every run belongs to a use case (model_run.use_case) and
a scope: a base model (plant-agnostic, battery_system_id NULL) or a battery system (plant) model. One run per
use case and scope can be active (the default): one base default, and one per battery system.
"""
import json
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import BaseRegressor, TrainingResult

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "runs"

SUMMARY_COLUMNS = """run_id, use_case, run_name, model_type, status, params, grain, date_from, date_to, feature_groups,
    features, module_rows_only, include_snapshots, split_method, test_fraction, random_state, n_rows, n_train, n_test,
    train_from, train_to, test_from, test_to, target_min, target_max, target_std, r2, mae, rmse, mape_pct,
    max_error, median_ae, explained_variance, train_r2, train_mae, train_rmse, iterations, best_iteration,
    warnings, error_message, is_active, started_at, finished_at, duration_ms, min_importance_pct, importance_method,
    candidate_features, scope, site_id, battery_system_id, training_mode, parent_run_id, systems, holdout_system_id,
    metrics_by_system, holdout_metrics"""


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):  # Decimal
            out[k] = float(v)
    return out


def start_run(engine: Engine, use_case: str, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.model_run (use_case, run_name, model_type, status, params, grain, date_from, date_to,
                feature_groups, features, candidate_features, module_rows_only, include_snapshots, split_method,
                test_fraction, random_state, min_importance_pct, scope, site_id, battery_system_id, training_mode,
                parent_run_id, holdout_system_id)
            VALUES (:use_case, :run_name, :model_type, 'RUNNING', CAST(:params AS jsonb), :grain, :date_from, :date_to,
                :feature_groups, :features, :features, :module_rows_only, :include_snapshots, :split_method,
                :test_fraction, :random_state, :min_importance_pct, :scope, :site_id, :battery_system_id,
                :training_mode, :parent_run_id, :holdout_system_id)
            RETURNING run_id"""), {"scope": "base", "site_id": None, "battery_system_id": None, "training_mode": "scratch",
                                   "parent_run_id": None, "holdout_system_id": None, **values, "use_case": use_case,
                                   "params": json.dumps(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str, warnings: Optional[list] = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.model_run SET status = 'FAILED', error_message = :m,
                             warnings = CAST(:w AS jsonb), finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int
                             WHERE run_id = :id"""), {"id": run_id, "m": message, "w": json.dumps(warnings or [])})


def save_model(run_id: int, model: BaseRegressor) -> str:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"run_{run_id}_{model.key}{model.file_suffix}"
    model.save(path)
    return str(path)


def complete_run(engine: Engine, run_id: int, result: TrainingResult, params: dict, artifact: str,
                 systems: Optional[list[int]] = None, holdout_metrics: Optional[dict] = None) -> None:
    s, m = result.split, result.metrics
    ts = lambda v: None if v is None or pd.isna(v) else pd.Timestamp(v).to_pydatetime()  # noqa: E731
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.model_run SET status = 'COMPLETED', params = CAST(:params AS jsonb),
                n_rows = :n_rows, n_train = :n_train, n_test = :n_test, train_from = :train_from, train_to = :train_to,
                test_from = :test_from, test_to = :test_to, target_min = :target_min, target_max = :target_max,
                target_std = :target_std, r2 = :r2, mae = :mae, rmse = :rmse, mape_pct = :mape_pct,
                max_error = :max_error, median_ae = :median_ae, explained_variance = :explained_variance,
                train_r2 = :train_r2, train_mae = :train_mae, train_rmse = :train_rmse, iterations = :iterations,
                best_iteration = :best_iteration, feature_importance = CAST(:importance AS jsonb),
                feature_ranges = CAST(:ranges AS jsonb), predictions = CAST(:predictions AS jsonb),
                warnings = CAST(:warnings AS jsonb), artifact_path = :artifact, finished_at = now(),
                features = :selected, candidate_features = :candidates, importance_method = :importance_method,
                selection_importance = CAST(:selection AS jsonb),
                systems = :systems, metrics_by_system = CAST(:by_system AS jsonb),
                holdout_metrics = CAST(:holdout AS jsonb),
                duration_ms = :duration_ms
            WHERE run_id = :id"""), {
            "id": run_id, "params": json.dumps(params), **{k: s[k] for k in ("n_rows", "n_train", "n_test", "target_min", "target_max", "target_std")},
            **{k: ts(s[k]) for k in ("train_from", "train_to", "test_from", "test_to")}, **m,
            "iterations": result.iterations, "best_iteration": result.best_iteration,
            "importance": json.dumps(result.importance), "ranges": json.dumps(result.feature_ranges),
            "predictions": json.dumps(result.predictions), "warnings": json.dumps(result.warnings),
            "artifact": artifact, "duration_ms": result.duration_ms,
            "selected": result.selected, "candidates": result.candidates,
            "importance_method": result.importance_method if result.min_importance_pct > 0 else None,
            "selection": json.dumps(result.screening_importance) if result.screening_importance else None,
            "systems": systems, "by_system": json.dumps(result.metrics_by_group) if result.metrics_by_group else None,
            "holdout": json.dumps(holdout_metrics) if holdout_metrics else None,
        })
        if result.curve:
            conn.execute(text("""INSERT INTO battery_ml.model_run_curve (run_id, iteration, train_rmse, valid_rmse, train_mae, valid_mae)
                                 VALUES (:run_id, :iteration, :train_rmse, :valid_rmse, :train_mae, :valid_mae)"""),
                         [{"run_id": run_id, **c} for c in result.curve])


def list_runs(engine: Engine, use_case: str, model_type: Optional[str] = None, status: Optional[str] = None,
              limit: int = 100, scope: Optional[str] = None, battery_system_id: Optional[int] = None,
              for_system: Optional[int] = None) -> list[dict]:
    """Runs newest first. for_system: the runs a battery system can use (base runs and its own runs)."""
    where, params = ["use_case = :uc"], {"uc": use_case, "limit": limit}
    if scope:
        where.append("scope = :scope")
        params["scope"] = scope
    if battery_system_id is not None:
        where.append("battery_system_id = :bsid")
        params["bsid"] = battery_system_id
    if for_system is not None:
        where.append("(scope = 'base' OR battery_system_id = :fsid)")
        params["fsid"] = for_system
    if model_type:
        where.append("model_type = :mt")
        params["mt"] = model_type
    if status:
        where.append("status = :st")
        params["st"] = status
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"""SELECT {SUMMARY_COLUMNS} FROM battery_ml.model_run WHERE {' AND '.join(where)}
                ORDER BY run_id DESC LIMIT :limit"""), params)]


def get_run(engine: Engine, use_case: str, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"""SELECT {SUMMARY_COLUMNS}, feature_importance, feature_ranges, predictions, artifact_path,
                                           selection_importance
                                    FROM battery_ml.model_run WHERE run_id = :id AND use_case = :uc"""),
                           {"id": run_id, "uc": use_case}).first()
        if row is None:
            return None
        run = _row(row)
        run["curve"] = [_row(r) for r in conn.execute(text(
            """SELECT iteration, train_rmse, valid_rmse, train_mae, valid_mae FROM battery_ml.model_run_curve
               WHERE run_id = :id ORDER BY iteration"""), {"id": run_id})]
    return run


def delete_run(engine: Engine, use_case: str, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("""DELETE FROM battery_ml.model_run WHERE run_id = :id AND use_case = :uc
                                   RETURNING artifact_path"""), {"id": run_id, "uc": use_case}).first()
    if row is None:
        return False
    if row[0]:
        Path(row[0]).unlink(missing_ok=True)
    _cache.pop(run_id, None)
    return True


def set_active(engine: Engine, use_case: str, run_id: Optional[int], battery_system_id: Optional[int] = None) -> None:
    """Make a completed run the default of its scope (the base default, or its battery system's default).
    run_id None removes the default of the scope given by battery_system_id (None = the base default)."""
    with engine.begin() as conn:
        if run_id is not None:
            row = conn.execute(text("SELECT battery_system_id FROM battery_ml.model_run WHERE run_id = :id AND use_case = :uc"),
                               {"id": run_id, "uc": use_case}).first()
            if row is None:
                raise ValueError(f"Run #{run_id} doesn't exist")
            battery_system_id = row[0]
        conn.execute(text("""UPDATE battery_ml.model_run SET is_active = false
                             WHERE is_active AND use_case = :uc AND battery_system_id IS NOT DISTINCT FROM :bsid"""),
                     {"uc": use_case, "bsid": battery_system_id})
        if run_id is not None:
            done = conn.execute(text("""UPDATE battery_ml.model_run SET is_active = true
                                        WHERE run_id = :id AND use_case = :uc AND status = 'COMPLETED'
                                        RETURNING run_id"""), {"id": run_id, "uc": use_case}).scalar()
            if done is None:
                raise ValueError(f"Run #{run_id} doesn't exist or didn't complete")


def active_run(engine: Engine, use_case: str, battery_system_id: Optional[int] = None) -> Optional[dict]:
    """The default run of a scope: a battery system's default, or (None) the base default."""
    with engine.connect() as conn:
        run_id = conn.execute(text("""SELECT run_id FROM battery_ml.model_run WHERE is_active AND use_case = :uc
                                      AND battery_system_id IS NOT DISTINCT FROM :bsid"""),
                              {"uc": use_case, "bsid": battery_system_id}).scalar()
    return get_run(engine, use_case, run_id) if run_id else None


def latest_run(engine: Engine, use_case: str, scope: Optional[str] = None,
               battery_system_id: Optional[int] = None) -> Optional[dict]:
    """The most recent completed run (of a scope / battery system when given)."""
    runs = list_runs(engine, use_case, status="COMPLETED", limit=1, scope=scope, battery_system_id=battery_system_id)
    return get_run(engine, use_case, runs[0]["run_id"]) if runs else None


# ---------------------------------------------------------------- loaded models

_cache: dict[int, BaseRegressor] = {}


def load_model(run: dict, models: dict[str, type[BaseRegressor]]) -> BaseRegressor:
    """The fitted model of a run (cached)."""
    if run["run_id"] not in _cache:
        path = run.get("artifact_path")
        if not path or not Path(path).exists():
            raise FileNotFoundError(f"Model file of run #{run['run_id']} is missing")
        if run["model_type"] not in models:
            raise ValueError(f"Run #{run['run_id']} has an unknown model type '{run['model_type']}'")
        _cache[run["run_id"]] = models[run["model_type"]].load(Path(path))
    return _cache[run["run_id"]]


def predict(run: dict, models: dict[str, type[BaseRegressor]], values: dict[str, Optional[float]]) -> float:
    """One prediction from a run's model; values holds its features (None = missing)."""
    features = list(run["features"])
    frame = pd.DataFrame([[values.get(f) for f in features]], columns=features, dtype=float)
    return float(load_model(run, models).predict(frame)[0])
