"""Weak module detection API (mounted at /weak-module): options, preview, detection runs (train / score), results,
points for the scatter and a module's deviation series for the drill-down."""
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from core.db import engine
from usecases.weak_module import detector as D
from usecases.weak_module import features as F
from usecases.weak_module import store
from usecases.weak_module.models import DETECTORS, DetectionError
from usecases.weak_module.schemas import DetectRequest, ScoreRequest, WindowIn

USE_CASE = "weak_module"
PREFIX = "weak-module"
router = APIRouter(tags=["Weak module detection"])


def status() -> dict:
    runs = store.list_runs(engine, limit=1)
    return {"runs": len(runs) > 0, "latest_run": runs[0]["run_id"] if runs else None}


def _system(system_id: int) -> dict:
    """The battery system (a window without module telemetry is reported by the preview / the detection)."""
    with engine.connect() as conn:
        row = conn.execute(text("SELECT battery_system_id, system_name FROM battery_master.battery_system "
                                "WHERE battery_system_id = :id"), {"id": system_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail=f"Battery system {system_id} not found")
    return dict(row)


def _run_or_404(run_id: int) -> dict:
    run = store.get_run(engine, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return run


@router.get("/options")
def options():
    return {
        "systems": F.coverage(engine),
        "feature_groups": [{"key": k, "label": g["label"],
                            "features": [{"key": f, **F.FEATURES[f]} for f in g["features"]]}
                           for k, g in F.FEATURE_GROUPS.items()],
        "grains": [{"key": "day", "label": "Module-day"}, {"key": "hour", "label": "Module-hour"}],
        "models": [{"key": k, "label": d.label, "params": d.param_specs} for k, d in DETECTORS.items()],
        "default_min_anomalous_share": D.DEFAULT_MIN_SHARE,
    }


@router.post("/preview")
def preview(window: WindowIn):
    """Rows, modules and days the window gives."""
    _system(window.battery_system_id)
    return F.count(engine, F.Selection(window.battery_system_id, window.date_from, window.date_to, window.grain))


@router.post("/runs")
def detect(request: DetectRequest):
    """Fit Isolation Forest and DBSCAN on the window and store the weak module verdicts."""
    system = _system(request.battery_system_id)
    unknown = [g for g in request.feature_groups if g not in F.FEATURE_GROUPS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown feature group(s): {', '.join(unknown)}")
    sel = F.Selection(request.battery_system_id, request.date_from, request.date_to, request.grain, request.feature_groups)
    try:
        if_params = DETECTORS["isolation_forest"].clean_params(request.if_params)
        db_params = DETECTORS["dbscan"].clean_params(request.db_params)
    except DetectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    params = {"isolation_forest": if_params, "dbscan": db_params, "min_anomalous_share": request.min_anomalous_share,
              "random_state": request.random_state}
    run_id = store.start_run(engine, {
        "run_kind": "train", "parent_run_id": None, "run_name": request.run_name,
        "battery_system_id": request.battery_system_id, "system_name": system["system_name"],
        "date_from": request.date_from, "date_to": request.date_to, "grain": request.grain,
        "feature_groups": request.feature_groups, "features": sel.features, "params": params})
    try:
        df = F.build(engine, sel)
        result = D.train(df, sel.features, if_params, db_params, request.min_anomalous_share,
                         F.modules(engine, request.battery_system_id), request.random_state)
        params["dbscan"] = {**db_params, "min_samples": result.stats["min_samples_used"]}
        artifact = store.save_artifact(run_id, D.artifact_of(result, sel.features, request.min_anomalous_share))
        store.complete_run(engine, run_id, result, params, artifact)
    except (DetectionError, ValueError) as exc:
        store.fail_run(engine, run_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": run_id})
    except Exception as exc:  # noqa: BLE001 - keep a record of unexpected failures
        store.fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Detection failed: {exc}", "run_id": run_id})
    return _public(store.get_run(engine, run_id))


@router.post("/runs/{run_id}/score")
def score(run_id: int, request: ScoreRequest):
    """Apply a train run's saved Isolation Forest to another window; DBSCAN clusters that window with the run's
    settings (it can't place unseen points)."""
    parent = _run_or_404(run_id)
    if parent["run_kind"] != "train" or parent["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail="Only a completed train run can score new data")
    try:
        artifact = store.load_artifact(parent)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    sel = F.Selection(parent["battery_system_id"], request.date_from, request.date_to, parent["grain"],
                      list(parent["feature_groups"]))
    new_id = store.start_run(engine, {
        "run_kind": "score", "parent_run_id": run_id, "run_name": request.run_name or f"Scored with run #{run_id}",
        "battery_system_id": parent["battery_system_id"], "system_name": parent["system_name"],
        "date_from": request.date_from, "date_to": request.date_to, "grain": parent["grain"],
        "feature_groups": list(parent["feature_groups"]), "features": list(parent["features"]),
        "params": parent["params"]})
    try:
        df = F.build(engine, sel)
        result = D.score(df, artifact, F.modules(engine, parent["battery_system_id"]))
        store.complete_run(engine, new_id, result, parent["params"], None)
    except (DetectionError, ValueError) as exc:
        store.fail_run(engine, new_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": new_id})
    return _public(store.get_run(engine, new_id))


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


@router.get("/runs")
def runs(battery_system_id: Optional[int] = None, limit: int = Query(100, ge=1, le=500)):
    return store.list_runs(engine, battery_system_id, limit)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    return _public(_run_or_404(run_id))


@router.get("/runs/{run_id}/points")
def run_points(run_id: int, module_id: Optional[int] = None):
    """The module rows of a run (features, IF score and flag, DBSCAN label) - for the scatter and the drill-down."""
    _run_or_404(run_id)
    return store.points(engine, run_id, module_id)


@router.get("/runs/{run_id}/modules/{module_id}/series")
def module_series(run_id: int, module_id: int, grain: str = Query("hour", pattern="^(hour|day)$")):
    """A module's deviation from its pack over the run's window, with the spread of the pack's other modules."""
    run = _run_or_404(run_id)
    module = next((m for m in run["modules"] if m["module_id"] == module_id), None)
    if module is None:
        raise HTTPException(status_code=404, detail=f"Module {module_id} is not part of run #{run_id}")
    df = F.build(engine, F.Selection(run["battery_system_id"], run["date_from"], run["date_to"], grain),
                 pack_id=module["pack_id"])
    if df.empty:
        raise HTTPException(status_code=404, detail="No telemetry for this module in the run's window")
    others = df[df.module_id != module_id].groupby("bucket")[["v_dev_pack_mv", "t_dev_pack_c"]]
    q10, q90 = others.quantile(0.1), others.quantile(0.9)
    band = pd.DataFrame({"v_p10": q10.v_dev_pack_mv, "v_p90": q90.v_dev_pack_mv,
                         "t_p10": q10.t_dev_pack_c, "t_p90": q90.t_dev_pack_c})
    mine = df[df.module_id == module_id].set_index("bucket")
    # only the module's pack is read here, so the per-pack deviation is the meaningful one
    out = mine[["v_dev_pack_mv", "t_dev_pack_c", "imbalance_mv"]].join(band)
    return [{"bucket": ts.isoformat(), **{k: F.to_float(v) for k, v in row.items()}} for ts, row in out.iterrows()]


@router.delete("/runs/{run_id}", status_code=204)
def delete(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
