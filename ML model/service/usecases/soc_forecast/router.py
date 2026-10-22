"""SOC trajectory forecasting API (mounted at /soc-forecast): options, model building runs, backtests and the live
forecast with a plan source (typical day, dispatch schedule, or custom what-if blocks)."""
from datetime import date, datetime
from typing import Any, Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.auth import can_approve
from core.db import engine
from usecases.soc_forecast import features as F
from usecases.soc_forecast import store
from usecases.soc_forecast import trainer as T

USE_CASE = "soc_forecast"
PREFIX = "soc-forecast"
router = APIRouter(tags=["SOC trajectory forecasting"])

METHOD_LABELS = {
    "hold": "Hold SOC (naïve)",
    "physics_typical": "Physics · typical day",
    "physics_scheduled": "Physics · schedule",
    "hybrid_typical": "Hybrid · typical day",
    "hybrid_scheduled": "Hybrid · schedule",
}


class TrainRequest(BaseModel):
    ems_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    horizon_h: float = Field(default=12, ge=1, le=24)
    test_fraction: float = Field(default=0.2, gt=0.05, lt=0.6)
    origin_step_min: int = Field(default=60, ge=5, le=720)
    train_origin_step_min: int = Field(default=60, ge=5, le=720)
    train_horizon_step: int = Field(default=3, ge=1, le=12)
    soc_min: Optional[float] = Field(default=None, ge=0, le=100)
    soc_max: Optional[float] = Field(default=None, ge=0, le=100)
    gbm_params: dict[str, Any] = Field(default_factory=dict)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class PlanBlock(BaseModel):
    start: datetime
    end: datetime
    kw: float = Field(ge=-100000, le=100000)


class ForecastRequest(BaseModel):
    ems_id: int
    source: Literal["typical", "scheduled", "custom"] = "scheduled"
    blocks: list[PlanBlock] = Field(default_factory=list)
    horizon_h: Optional[float] = Field(default=None, ge=1, le=24)
    history_hours: int = Field(default=24, ge=1, le=168)


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


def _run(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed SOC forecast model yet" if model == "active"
                            else f"Run {model} is not a completed SOC forecast run")
    try:
        return run, store.load_artifact(run)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/options")
def options():
    return {"units": F.ems_units(engine), "gbm_params": T.GBM_PARAMS, "methods": METHOD_LABELS,
            "defaults": {"horizon_h": 12, "test_fraction": 0.2, "origin_step_min": 60, "train_origin_step_min": 60,
                         "train_horizon_step": 3}}


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    limits = None
    if body.soc_min is not None or body.soc_max is not None:
        if body.soc_min is None or body.soc_max is None or body.soc_max <= body.soc_min:
            raise HTTPException(status_code=400, detail="Enter both SOC limits (min below max), or neither for the learned ones")
        limits = (body.soc_min, body.soc_max)
    try:
        gbm = T.clean_gbm(body.gbm_params)
    except T.SocForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    params = {"gbm": gbm, "train_origin_step_min": body.train_origin_step_min, "train_horizon_step": body.train_horizon_step,
              "soc_min": body.soc_min, "soc_max": body.soc_max}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "ems_ids": body.ems_ids, "date_from": body.date_from, "date_to": body.date_to,
        "horizon_h": body.horizon_h, "test_fraction": body.test_fraction, "origin_step_min": body.origin_step_min,
        "params": params})
    cfg = T.RunConfig(F.Selection(body.ems_ids, body.date_from, body.date_to), body.horizon_h, body.test_fraction,
                      body.origin_step_min, body.train_origin_step_min, body.train_horizon_step, limits, gbm)
    try:
        artifact, summary, points, warnings = T.train(engine, cfg)
        path = store.save_artifact(run_id, artifact)
        store.complete_run(engine, run_id, summary, points, warnings, path)
    except (T.SocForecastError, ValueError) as exc:
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
    return store.origins(engine, run_id, ems_id)


@router.get("/runs/{run_id}/backtest")
def run_backtest(run_id: int, ems_id: int, origin_ts: datetime, history_hours: int = Query(12, ge=1, le=72)):
    """Every method's trajectory from one backtest origin, with the SOC history before it."""
    rows = store.backtest(engine, run_id, ems_id, origin_ts)
    if not rows:
        raise HTTPException(status_code=404, detail="No backtest trajectory for this origin")
    o = pd.Timestamp(origin_ts)
    df = F.series(engine, ems_id, (o - pd.Timedelta(hours=history_hours)).date(), o.date())
    df = df[(df.index > o - pd.Timedelta(hours=history_hours)) & (df.index <= o)]
    return {"origin_ts": o.isoformat(), "points": rows,
            "history": [{"ts": t.isoformat(), "soc": T.finite(s) if s == s else None, "sp": T.finite(p) if p == p else None}
                        for t, s, p in zip(df.index, df["soc"], df["sp"])]}


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
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "ems_ids", "horizon_h", "best_method", "metrics",
                                "finished_at")} for r in out]


@router.post("/forecast")
def forecast(body: ForecastRequest, model: str = "active"):
    """SOC trajectories from the newest reading of the EMS for a plan source (custom = the given blocks, typical day
    elsewhere), with the derived available energy and time to the SOC limits."""
    run, art = _run(model)
    try:
        out = T.forecast(engine, art, body.ems_id, body.source, [b.model_dump() for b in body.blocks],
                         body.history_hours, body.horizon_h)
    except T.SocForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run["run_id"], **out}
