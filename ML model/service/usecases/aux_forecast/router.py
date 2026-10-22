"""Auxiliary / HVAC energy forecasting API (mounted at /aux-forecast): options, model building runs and scores, backtest
trajectories / horizon series / daily energy, online prediction (features fetched from v_aux_features) and stateless
prediction from a feature vector."""
from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.auth import can_approve
from core.db import engine
from usecases.aux_forecast import features as F
from usecases.aux_forecast import store
from usecases.aux_forecast import trainer as T

USE_CASE = "aux_forecast"
PREFIX = "aux-forecast"
router = APIRouter(tags=["Auxiliary / HVAC energy forecasting"])

METHOD_LABELS = {"persistence": "Persistence", "seasonal": "Seasonal naïve (same time yesterday)",
                 "greybox": "Grey-box (heat load / COP)", "hybrid": "Hybrid (grey-box + LightGBM)"}


class TrainRequest(BaseModel):
    ems_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    horizon_hours: int = Field(default=24, ge=1, le=24)
    plan_source: Literal["scheduled", "typical"] = "scheduled"
    ambient_source: Literal["forecast", "profile", "actual"] = "forecast"
    test_fraction: float = Field(default=0.2, gt=0.05, lt=0.6)
    train_origin_step: int = Field(default=6, ge=1, le=48)
    steps_per_origin: int = Field(default=24, ge=4, le=288)
    gbm_params: dict[str, Any] = Field(default_factory=dict)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class PredictRequest(BaseModel):
    ems_id: int
    horizon_hours: Optional[int] = Field(default=None, ge=1, le=24)
    plan_source: Optional[Literal["scheduled", "typical"]] = None
    ambient_source: Optional[Literal["forecast", "profile", "actual"]] = None
    as_of: Optional[str] = None
    max_data_age_min: Optional[float] = Field(default=None, gt=0)
    history_hours: int = Field(default=24, ge=1, le=24)


class VectorRequest(BaseModel):
    ems_id: int
    inputs: dict[str, Any]
    horizon_hours: Optional[int] = Field(default=None, ge=1, le=24)
    plan_kw: Optional[list[float]] = None
    ambient_fc_c: Optional[list[float]] = None
    aux_yesterday_kw: Optional[list[float]] = None
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
        raise HTTPException(status_code=404, detail="No completed aux forecast model yet" if model == "active"
                            else f"Run {model} is not a completed aux forecast run")
    try:
        return run, store.load_artifact(run)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/options")
def options():
    return {
        "sites": F.sites(engine), "methods": METHOD_LABELS, "buckets": [b[2] for b in T.BUCKETS],
        "report_horizons": T.REPORT_HORIZONS, "gbm_params": T.GBM_PARAMS,
        "defaults": {"horizon_hours": 24, "test_fraction": 0.2, "train_origin_step": 6, "steps_per_origin": 24,
                     "plan_source": "scheduled", "ambient_source": "forecast"},
    }


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    try:
        gbm = T.clean_gbm(body.gbm_params)
    except T.AuxForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    params = {"gbm": gbm, "plan_source": body.plan_source, "ambient_source": body.ambient_source,
              "train_origin_step": body.train_origin_step, "steps_per_origin": body.steps_per_origin}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "ems_ids": body.ems_ids, "date_from": body.date_from, "date_to": body.date_to,
        "horizon_hours": body.horizon_hours, "test_fraction": body.test_fraction, "params": params})
    cfg = T.RunConfig(F.Selection(body.ems_ids, body.date_from, body.date_to), body.horizon_hours, body.plan_source,
                      body.ambient_source, body.test_fraction, body.train_origin_step, body.steps_per_origin,
                      gbm_params=gbm)
    try:
        artifact, summary, points, daily, warnings = T.train(engine, cfg)
        path = store.save_artifact(run_id, artifact)
        store.complete_run(engine, run_id, summary, points, daily, warnings, path)
    except (T.AuxForecastError, ValueError) as exc:
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


@router.get("/runs/{run_id}/origins")
def run_origins(run_id: int, ems_id: int):
    """Backtest origins with a full stored trajectory (every 6 h, ending at :55)."""
    return store.trajectory_origins(engine, run_id, ems_id)


@router.get("/runs/{run_id}/trajectory")
def run_trajectory(run_id: int, ems_id: int, origin_ts: str, methods: str = Query("seasonal,greybox,hybrid")):
    return store.trajectory(engine, run_id, ems_id, origin_ts, [m for m in methods.split(",") if m])


@router.get("/runs/{run_id}/series")
def run_series(run_id: int, ems_id: int, horizon_min: int, methods: str = Query("seasonal,greybox,hybrid")):
    """Backtest forecasts over the test period for one site at a fixed horizon (every 30-min origin)."""
    return store.horizon_series(engine, run_id, ems_id, horizon_min, [m for m in methods.split(",") if m])


@router.get("/runs/{run_id}/daily")
def run_daily(run_id: int, ems_id: Optional[int] = None):
    """Daily aux energy (kWh) of the test days: actual vs the forecasts issued at 23:55 the evening before."""
    return store.daily(engine, run_id, ems_id)


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
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "ems_ids", "horizon_hours", "metrics", "finished_at")}
            for r in out]


@router.post("/predict")
def predict(body: PredictRequest, model: str = "active"):
    """Online: features from v_aux_features at the newest reading (or the newest at / before as_of) ->
    {ts_target, horizon_min, aux_kw_p50, aux_kw_p10, aux_kw_p90} per 5-min step + aux_energy_kwh per interval and day,
    NULL with a staleness flag when inputs are stale / missing."""
    run, art = _run(model)
    try:
        out = T.predict_live(engine, art, body.ems_id, body.horizon_hours, body.plan_source, body.ambient_source,
                             body.as_of, body.history_hours, body.max_data_age_min)
    except T.AuxForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run["run_id"], **out}


@router.post("/predict/vector")
def predict_vector(body: VectorRequest, model: str = "active"):
    """Stateless: the forecast from a feature vector (no database read)."""
    run, art = _run(model)
    try:
        out = T.predict_vector(art, body.ems_id, body.inputs, body.horizon_hours, body.plan_kw, body.ambient_fc_c,
                               body.aux_yesterday_kw, body.origin_ts)
    except T.AuxForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run["run_id"], **out}
