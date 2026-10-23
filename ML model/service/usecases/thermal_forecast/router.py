"""Temperature forecasting API (mounted at /thermal-forecast): options, model building runs and scores, backtest series,
online prediction (features fetched from v_thermal_features) and stateless prediction from a feature vector."""
from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from bess_common.errors import run_guard
from core.auth import can_approve
from core.db import engine
from usecases.thermal_forecast import features as F
from usecases.thermal_forecast import store
from usecases.thermal_forecast import trainer as T

USE_CASE = "thermal_forecast"
PREFIX = "thermal-forecast"
router = APIRouter(tags=["Temperature forecasting"])

METHOD_LABELS = {"persistence": "Persistence", "seasonal": "Seasonal naïve (24 h)", "rc": "RC grey-box",
                 "hybrid": "Hybrid (RC + LightGBM)"}


class TrainRequest(BaseModel):
    system_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    targets: list[str] = Field(default_factory=lambda: list(F.TARGETS))
    horizons_min: list[int] = Field(default_factory=lambda: [5, 15, 30, 60])
    thresholds: dict[str, float] = Field(default_factory=dict)
    plan_source: Literal["scheduled", "typical"] = "scheduled"
    test_fraction: float = Field(default=0.2, gt=0.05, lt=0.6)
    train_origin_step: int = Field(default=2, ge=1, le=24)
    gbm_params: dict[str, Any] = Field(default_factory=dict)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class PredictRequest(BaseModel):
    system_id: int
    targets: Optional[list[str]] = None
    horizons_min: Optional[list[int]] = None
    plan_source: Optional[Literal["scheduled", "typical"]] = None
    max_data_age_min: Optional[float] = Field(default=None, gt=0)
    history_hours: int = Field(default=6, ge=1, le=48)


class VectorRequest(BaseModel):
    system_id: int
    target: str
    inputs: dict[str, Any]
    horizons_min: Optional[list[int]] = None
    plan_kw: Optional[list[float]] = None
    origin_ts: Optional[str] = None


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


def _run(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed temperature forecast model yet" if model == "active"
                            else f"Run {model} is not a completed temperature forecast run")
    return run, store.load_artifact(run)


@router.get("/options")
def options():
    return {
        "systems": F.systems(engine),
        "targets": [{"key": k, **{x: v for x, v in s.items()}} for k, s in F.TARGETS.items()],
        "families": F.FAMILIES, "methods": METHOD_LABELS, "catalog_thresholds": F.thresholds(engine),
        "gbm_params": T.GBM_PARAMS, "defaults": {"horizons_min": [5, 15, 30, 60], "test_fraction": 0.2,
                                                 "train_origin_step": 2, "plan_source": "scheduled"},
    }


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    gbm = T.clean_gbm(body.gbm_params)
    params = {"gbm": gbm, "thresholds": body.thresholds, "plan_source": body.plan_source,
              "train_origin_step": body.train_origin_step}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "system_ids": body.system_ids, "date_from": body.date_from, "date_to": body.date_to,
        "targets": body.targets, "horizons_min": sorted(set(body.horizons_min)), "test_fraction": body.test_fraction,
        "params": params})
    cfg = T.RunConfig(F.Selection(body.system_ids, body.date_from, body.date_to), body.targets, body.horizons_min,
                      body.thresholds, body.plan_source, body.test_fraction, body.train_origin_step, gbm_params=gbm)
    with run_guard(fail=lambda msg: store.fail_run(engine, run_id, msg), context={"run_id": run_id}):
        artifact, summary, points, warnings = T.train(engine, cfg)
        path = store.save_artifact(run_id, artifact)
        store.complete_run(engine, run_id, summary, points, warnings, path)
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


@router.get("/runs/{run_id}/series")
def run_series(run_id: int, system_id: int, target: str, horizon_min: int,
               methods: str = Query("persistence,rc,hybrid")):
    """Backtest forecasts over the test period for one system / target / horizon (every stored origin)."""
    return store.series(engine, run_id, system_id, target, horizon_min, [m for m in methods.split(",") if m])


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
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "system_ids", "targets", "horizons_min", "metrics",
                                "finished_at")} for r in out]


@router.post("/predict")
def predict(body: PredictRequest, model: str = "active"):
    """Online: features from v_thermal_features at the newest reading -> {target, asset_id, horizon_min, pred_c,
    p10_c, p90_c} per target and horizon, NULL with a flag when stale / missing."""
    run, art = _run(model)
    out = T.predict_live(engine, art, body.system_id, body.plan_source, body.targets, body.horizons_min,
                         body.history_hours, body.max_data_age_min)
    return {"run_id": run["run_id"], **out}


@router.post("/predict/vector")
def predict_vector(body: VectorRequest, model: str = "active"):
    """Stateless: the forecast of one target from a feature vector (no database read)."""
    run, art = _run(model)
    out = T.predict_vector(art, body.system_id, body.target, body.inputs, body.horizons_min, body.plan_kw,
                           body.origin_ts)
    return {"run_id": run["run_id"], **out}
