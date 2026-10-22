"""Efficiency runs in battery_ml.efficiency_run / efficiency_score / efficiency_cycle and their model files."""
import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "efficiency"

RUN_COLUMNS = """run_id, run_name, status, is_default, pcs_ids, date_from, date_to, split_method, test_fraction,
    min_load_frac, feature_groups, features, booster, params, n_points, n_train, n_test, n_cycles, best_model, metrics,
    warnings, error_message, started_at, finished_at, duration_ms"""
SCORE_KEYS = ("n", "r2", "mae", "rmse", "mape_pct", "max_error", "median_ae", "loss_mae_kw", "bias_pp")
CYCLE_COLUMNS = {
    "e_dc_in_kwh": "e_dc_in", "e_dc_out_kwh": "e_dc_out", "e_ac_in_kwh": "e_ac_in", "e_ac_out_kwh": "e_ac_out",
    "e_poi_in_kwh": "e_poi_in", "e_poi_out_kwh": "e_poi_out", "e_aux_kwh": "e_aux", "e_hvac_kwh": "e_hvac",
    "soc_start_pct": "soc_start_pct", "soc_end_pct": "soc_end_pct", "depth_pct": "depth_pct",
    "rte_dc_pct": "rte_dc_pct", "rte_ac_pct": "rte_ac_pct", "rte_sys_pct": "rte_sys_pct",
    "rte_dc_pred_pct": "rte_dc_pred_pct", "rte_ac_comp_pct": "rte_ac_comp_pct", "rte_sys_comp_pct": "rte_sys_comp_pct",
    "eta_chg_meas_pct": "eta_chg_meas_pct", "eta_dis_meas_pct": "eta_dis_meas_pct",
    "eta_chg_pred_pct": "eta_chg_pred_pct", "eta_dis_pred_pct": "eta_dis_pred_pct",
}
CYCLE_DETAIL = ("charge_load_frac", "discharge_load_frac", "charge_hours", "discharge_hours", "period_hours",
                "rest_hours", "soc_min_pct", "soc_max_pct", "delta_soc_pct", "cell_temp_avg_c", "ambient_temp_c",
                "fr_share", "vv_share", "direction_changes", "soh_pct", "aux_kw_avg", "hvac_kw_avg", "kwh_per_pct",
                "rte_dc_raw_pct", "rte_ac_raw_pct", "rte_sys_raw_pct")


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return f if np.isfinite(f) else None


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def _json(v) -> str:
    return json.dumps(v, default=lambda o: _num(o) if isinstance(o, (np.floating, np.integer)) else str(o))


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.efficiency_run (run_name, status, pcs_ids, date_from, date_to, split_method,
                test_fraction, min_load_frac, feature_groups, booster, params)
            VALUES (:run_name, 'RUNNING', :pcs_ids, :date_from, :date_to, :split_method, :test_fraction,
                :min_load_frac, :feature_groups, :booster, CAST(:params AS jsonb))
            RETURNING run_id"""), {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.efficiency_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message})


def save_artifact(run_id: int, artifact: dict) -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(artifact, path)
    return str(path)


def complete_run(engine: Engine, run_id: int, summary: dict, cycles: pd.DataFrame, warnings: list[str],
                 artifact: str) -> None:
    results = {k: summary[k] for k in ("residual_features", "split", "metrics_detail", "greybox", "gam", "shap",
                                       "health", "curves", "rte", "boost_curve")}
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.efficiency_run SET status = 'COMPLETED', features = :features, n_points = :n_points,
                n_train = :n_train, n_test = :n_test, n_cycles = :n_cycles, best_model = :best_model,
                metrics = CAST(:metrics AS jsonb), results = CAST(:results AS jsonb),
                predictions = CAST(:predictions AS jsonb), warnings = CAST(:warnings AS jsonb), artifact_path = :artifact,
                finished_at = now(), duration_ms = :duration_ms
            WHERE run_id = :id"""), {
            "id": run_id, "features": summary["features"], "n_points": summary["n_points"],
            "n_train": summary["n_train"], "n_test": summary["n_test"], "n_cycles": summary["n_cycles"],
            "best_model": summary["best_model"], "metrics": _json(summary["metrics"]), "results": _json(results),
            "predictions": _json(summary["predictions"]), "warnings": _json(warnings), "artifact": artifact,
            "duration_ms": summary["duration_ms"]})
        scores = [(m, ds, s) for m, sets in summary["metrics"].items() for ds, s in sets.items()]
        rte = summary["rte"]
        for key, model in (("ac_composition_scores", "rte_ac_composed"), ("sys_composition_scores", "rte_sys_composed")):
            if rte.get(key):
                scores.append((model, "all", {**rte[key], "n": rte.get("n_closed")}))
        if rte.get("dc_model"):
            scores.append(("dc_rte", "cv", {**rte["dc_model"]["scores_cv"], "n": rte["dc_model"]["n"]}))
        conn.execute(text("""
            INSERT INTO battery_ml.efficiency_score (run_id, model, dataset, n, r2, mae, rmse, mape_pct, max_error,
                median_ae, loss_mae_kw, bias_pp)
            VALUES (:run_id, :model, :dataset, :n, :r2, :mae, :rmse, :mape_pct, :max_error, :median_ae, :loss_mae_kw,
                :bias_pp)"""), [
            {"run_id": run_id, "model": m, "dataset": ds, **{k: _num(s.get(k)) for k in SCORE_KEYS}} for m, ds, s in scores])
        if not cycles.empty:
            conn.execute(text(f"""
                INSERT INTO battery_ml.efficiency_cycle (run_id, cycle_no, pcs_id, battery_system_id, start_ts, end_ts,
                    data_set, closed, complete, {', '.join(CYCLE_COLUMNS)}, detail)
                VALUES (:run_id, :cycle_no, :pcs_id, :battery_system_id, :start_ts, :end_ts, :data_set, :closed,
                    :complete, {', '.join(':' + c for c in CYCLE_COLUMNS)}, CAST(:detail AS jsonb))"""), [
                {"run_id": run_id, "cycle_no": i + 1, "pcs_id": int(r["pcs_id"]),
                 "battery_system_id": None if pd.isna(r["battery_system_id"]) else int(r["battery_system_id"]),
                 "start_ts": r["start_ts"].to_pydatetime(), "end_ts": r["end_ts"].to_pydatetime(),
                 "data_set": r.get("set"), "closed": bool(r["closed"]), "complete": bool(r["complete"]),
                 **{c: _num(r.get(src)) for c, src in CYCLE_COLUMNS.items()},
                 "detail": _json({k: _num(r.get(k)) for k in CYCLE_DETAIL})}
                for i, r in enumerate(cycles.to_dict("records"))])


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {RUN_COLUMNS} FROM battery_ml.efficiency_run ORDER BY run_id DESC LIMIT :limit"), {"limit": limit})]


def get_run(engine: Engine, run_id: int, full: bool = True) -> Optional[dict]:
    extra = ", results, predictions, artifact_path" if full else ", artifact_path"
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}{extra} FROM battery_ml.efficiency_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def resolve(engine: Engine, model: str) -> Optional[dict]:
    """'active' = the default run, else the latest completed one; or a run id."""
    with engine.connect() as conn:
        if model == "active":
            row = conn.execute(text("""SELECT run_id FROM battery_ml.efficiency_run WHERE status = 'COMPLETED'
                                       ORDER BY is_default DESC, run_id DESC LIMIT 1""")).first()
            if not row:
                return None
            model = str(row[0])
    if not str(model).isdigit():
        return None
    run = get_run(engine, int(model), full=False)
    return run if run and run["status"] == "COMPLETED" else None


def results(engine: Engine, run_id: int, keys: tuple[str, ...]) -> dict:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT results FROM battery_ml.efficiency_run WHERE run_id = :id"), {"id": run_id}).first()
    return {k: (row[0] or {}).get(k) for k in keys} if row else {}


def cycles(engine: Engine, run_id: int) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            "SELECT * FROM battery_ml.efficiency_cycle WHERE run_id = :id ORDER BY pcs_id, start_ts"), {"id": run_id})]


def scores(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT s.* FROM battery_ml.efficiency_score s JOIN battery_ml.efficiency_run r USING (run_id)
            WHERE r.status = 'COMPLETED' ORDER BY s.run_id DESC, s.model, s.dataset"""))]


def set_default(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        ok = conn.execute(text("SELECT 1 FROM battery_ml.efficiency_run WHERE run_id = :id AND status = 'COMPLETED'"),
                          {"id": run_id}).first()
        if not ok:
            return False
        conn.execute(text("UPDATE battery_ml.efficiency_run SET is_default = false WHERE is_default"))
        conn.execute(text("UPDATE battery_ml.efficiency_run SET is_default = true WHERE run_id = :id"), {"id": run_id})
    return True


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.efficiency_run WHERE run_id = :id RETURNING artifact_path"),
                           {"id": run_id}).first()
    if row is None:
        return False
    if row[0]:
        Path(row[0]).unlink(missing_ok=True)
    return True


_cache: dict[str, dict] = {}


def load_artifact(run: dict) -> dict:
    path = run.get("artifact_path")
    if not path or not Path(path).exists():
        raise FileNotFoundError(f"The model file of run #{run['run_id']} is missing")
    if path not in _cache:
        _cache[path] = joblib.load(path)
    return _cache[path]
