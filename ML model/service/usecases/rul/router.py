"""Remaining Useful Life API (mounted at /rul): options, model building runs and scores, leave-one-unit-out backtest,
per-unit forecasts of a run and the what-if prediction of one unit."""
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.auth import can_approve
from core.db import engine
from usecases.rul import features as F
from usecases.rul import store
from usecases.rul import trainer as T

USE_CASE = "rul"
PREFIX = "rul"
router = APIRouter(tags=["Remaining useful life"])

METHOD_LABELS = {
    "physics": "Physics fade curve (√t + cycle power-law + Arrhenius + knee)",
    "gbm": "LightGBM quantile regression",
    "hybrid": "Hybrid (physics + LightGBM residual)",
    "cox": "Cox proportional hazards (survival)",
    "rsf": "Random Survival Forest (survival)",
}


class TrainRequest(BaseModel):
    system_ids: Optional[list[int]] = None
    methods: list[str] = Field(default_factory=lambda: list(T.METHODS), min_length=1)
    feature_groups: list[str] = Field(default_factory=lambda: list(F.FEATURE_GROUPS), min_length=1)
    failures_as: Literal["event", "censored"] = "event"
    arrhenius: bool = True
    knee: bool = True
    calibrate_bands: bool = True
    physics: dict[str, Any] = Field(default_factory=dict)
    gbm: dict[str, Any] = Field(default_factory=dict)
    survival: dict[str, Any] = Field(default_factory=dict)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class PredictRequest(BaseModel):
    system_id: int
    cycles_per_day: Optional[float] = Field(default=None, ge=0, le=20)
    temp_c: Optional[float] = Field(default=None, ge=-20, le=70)


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


def _run(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed RUL model yet" if model == "active"
                            else f"Run {model} is not a completed RUL run")
    try:
        return run, store.load_artifact(run)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/options")
def options():
    return {
        "systems": F.systems(engine), "eol_criteria": F.eol_criteria(engine), "methods": METHOD_LABELS,
        "feature_groups": {k: {"label": v["label"], "columns": v["columns"]} for k, v in F.FEATURE_GROUPS.items()},
        "physics_params": T.PHYSICS_PARAMS, "gbm_params": T.GBM_PARAMS, "survival_params": T.SURVIVAL_PARAMS,
        "life_buckets": [b[2] for b in T.LIFE_BUCKETS], "cox_features": T.COX_FEATURES,
    }


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    try:
        params = {"physics": T.clean(T.PHYSICS_PARAMS, body.physics), "gbm": T.clean(T.GBM_PARAMS, body.gbm),
                  "survival": T.clean(T.SURVIVAL_PARAMS, body.survival)}
    except T.RulError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    params.update({"feature_groups": body.feature_groups, "failures_as": body.failures_as, "arrhenius": body.arrhenius,
                   "knee": body.knee, "calibrate_bands": body.calibrate_bands})
    run_id = store.start_run(engine, {"run_name": body.run_name, "system_ids": body.system_ids or [],
                                      "methods": body.methods, "params": params})
    cfg = T.RunConfig(body.system_ids or None, body.methods, body.feature_groups, body.failures_as, body.arrhenius,
                      body.knee, body.calibrate_bands, params["physics"], params["gbm"], params["survival"])
    try:
        artifact, summary, bt, fc, warnings = T.train(engine, cfg)
        path = store.save_artifact(run_id, artifact)
        store.complete_run(engine, run_id, summary, bt, fc, warnings, path)
    except (T.RulError, ValueError) as exc:
        store.fail_run(engine, run_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": run_id})
    except Exception as exc:  # noqa: BLE001 - keep a record of unexpected failures
        store.fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Training failed: {exc}", "run_id": run_id})
    if body.make_default and can_approve(request):
        store.set_default(engine, run_id)
    return _public(store.get_run(engine, run_id))


@router.get("/runs")
def runs(limit: int = Query(100, ge=1, le=500)):
    return store.list_runs(engine, limit)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    run = store.get_run(engine, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return _public(run)


@router.get("/runs/{run_id}/forecasts")
def run_forecasts(run_id: int):
    """RUL per in-service unit at its latest snapshot, every method of the run."""
    return store.forecasts(engine, run_id)


@router.get("/runs/{run_id}/backtest")
def run_backtest(run_id: int, system_id: int, methods: str = Query("physics,hybrid,rsf")):
    """Leave-one-unit-out predictions at every snapshot of one unit (true RUL for retired units; the known-alive bound
    and the synthetic label for censored ones)."""
    return store.backtest(engine, run_id, system_id, [m for m in methods.split(",") if m])


@router.post("/runs/{run_id}/default", status_code=204)
def make_default(run_id: int):
    if not store.set_default(engine, run_id):
        raise HTTPException(status_code=400, detail=f"Run #{run_id} is not a completed run")


@router.delete("/runs/{run_id}", status_code=204)
def delete(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


@router.get("/models")
def models():
    out = [r for r in store.list_runs(engine) if r["status"] == "COMPLETED"]
    out.sort(key=lambda r: (not r["is_default"], -r["run_id"]))
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "methods", "n_units", "metrics", "finished_at")}
            for r in out]


@router.post("/predict")
def predict(body: PredictRequest, model: str = "active"):
    """RUL of one unit at its latest snapshot - every method of the model - optionally under a what-if duty (EFC per
    day) and cell temperature, with the projected SOH / resistance paths and the survival curves."""
    run, art = _run(model)
    try:
        out = T.predict_unit(engine, art, body.system_id, body.cycles_per_day, body.temp_c)
    except T.RulError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run["run_id"], **out}
