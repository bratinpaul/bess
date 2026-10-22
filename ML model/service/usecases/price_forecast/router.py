"""Electricity-price forecasting API (mounted at /price-forecast): options, preview, model generation runs, scores,
backtests and the live forecast."""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from core.auth import can_approve
from core.db import engine
from usecases.price_forecast import features as F
from usecases.price_forecast import store
from usecases.price_forecast import trainer as T
from usecases.price_forecast.models import BASELINE, FORECASTERS, ForecastError, clean_params
from usecases.price_forecast.schemas import SelectionIn, TrainRequest

USE_CASE = "price_forecast"
PREFIX = "price-forecast"
router = APIRouter(tags=["Electricity price forecasting"])


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _selection(body: SelectionIn) -> F.Selection:
    unknown = [g for g in body.feature_groups if g not in F.FEATURE_GROUPS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown feature group(s): {', '.join(unknown)}")
    return F.Selection(body.ems_ids, body.date_from, body.date_to, body.feature_groups, body.spike_threshold)


def _run(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed price forecast model yet" if model == "active"
                            else f"Run {model} is not a completed price forecast run")
    try:
        return run, store.load_artifact(run)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


@router.get("/options")
def options():
    return {
        "units": F.ems_units(engine),
        "feature_groups": [{"key": k, "label": v, "required": k in F.REQUIRED_GROUPS, "features": F.GROUP_FEATURES[k]}
                           for k, v in F.FEATURE_GROUPS.items()],
        "models": [{"key": k, "label": c.label, "family": c.family, "params": c.param_specs, "always": k == BASELINE}
                   for k, c in FORECASTERS.items()],
        "tariff": F.tariff(engine),
        "external_drivers": F.EXTERNAL_DRIVERS,
        "defaults": {"horizon_hours": 48, "test_fraction": 0.2, "origin_step_h": 6, "train_origin_step_h": 2,
                     "spike_threshold": 150.0},
    }


@router.get("/tariff")
def tariff(ems_id: Optional[int] = None):
    return F.tariff(engine, ems_id)


@router.post("/preview")
def preview(body: SelectionIn):
    """Hours, gaps and spike hours per EMS in the selection."""
    out = []
    for ems in body.ems_ids:
        df = F.hourly(engine, ems, body.date_from, body.date_to)
        if df.empty:
            out.append({"ems_id": ems, "hours": 0})
            continue
        price = df["price"]
        out.append({"ems_id": ems, "hours": int(price.notna().sum()), "missing_hours": int(price.isna().sum()),
                    "from": df.index[0].isoformat(), "to": df.index[-1].isoformat(),
                    "spike_hours": int((df["price_max5"] > body.spike_threshold).sum()),
                    "price_mean": float(price.mean()), "price_p95": float(price.quantile(0.95))})
    return {"units": out, "hours": sum(u["hours"] for u in out), "spike_hours": sum(u.get("spike_hours", 0) for u in out)}


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    sel = _selection(body)
    unknown = [m for m in body.models if m not in FORECASTERS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown model(s): {', '.join(unknown)}")
    models = [BASELINE] + [m for m in body.models if m != BASELINE]
    try:
        params = {m: clean_params(FORECASTERS[m], body.params.get(m, {})) for m in models}
    except ForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stored = {**params, "spike_threshold": body.spike_threshold, "train_origin_step_h": body.train_origin_step_h,
              "random_state": body.random_state}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "ems_ids": body.ems_ids, "date_from": body.date_from, "date_to": body.date_to,
        "horizon_hours": body.horizon_hours, "test_fraction": body.test_fraction, "origin_step_h": body.origin_step_h,
        "feature_groups": sel.feature_groups, "models": models, "params": stored})
    cfg = T.RunConfig(sel, models, params, body.horizon_hours, body.test_fraction, body.origin_step_h,
                      body.train_origin_step_h, body.random_state)
    try:
        result = T.train(engine, cfg)
        artifact = store.save_artifact(run_id, result.artifact)
        store.complete_run(engine, run_id, result.summary, result.points, result.warnings, artifact)
    except (ForecastError, ValueError) as exc:
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
    """The backtest forecast origins of an EMS in a run."""
    return store.origins(engine, run_id, ems_id)


@router.get("/runs/{run_id}/backtest")
def run_backtest(run_id: int, ems_id: int, origin_ts: datetime):
    """Every model's forecast from one backtest origin, with the hourly actuals and the 5-min prices."""
    rows = store.backtest(engine, run_id, ems_id, origin_ts)
    if not rows:
        raise HTTPException(status_code=404, detail="No backtest forecast for this origin")
    first = min(r["target_ts"] for r in rows)
    last = max(r["target_ts"] for r in rows)
    start = pd.Timestamp(first) - pd.Timedelta(hours=25)
    end = pd.Timestamp(last) + pd.Timedelta(hours=1)
    hist = F.hourly(engine, ems_id, start.date(), end.date())
    hist = hist[(hist.index >= start) & (hist.index < end)]
    return {"origin_ts": origin_ts.isoformat(), "points": rows,
            "history": [{"ts": t.isoformat(), "price": T.finite(p) if p == p else None} for t, p in hist["price"].items()],
            "history_5min": F.five_min(engine, ems_id, start, end)}


@router.get("/scores")
def scores():
    return store.scores(engine)


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
    """Completed runs for the viewer's picker (the default first)."""
    out = [r for r in store.list_runs(engine) if r["status"] == "COMPLETED"]
    out.sort(key=lambda r: (not r["is_default"], -r["run_id"]))
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "ems_ids", "models", "best_model", "metrics",
                                "horizon_hours", "finished_at")} for r in out]


@router.get("/forecast")
def forecast(ems_id: int, model: str = "active", history_hours: int = Query(72, ge=24, le=336)):
    """The next horizon from the newest complete hour of the EMS's prices, with every model of the run."""
    run, art = _run(model)
    try:
        out = T.forecast(engine, art, ems_id, list(art["models"]), history_hours)
    except ForecastError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run["run_id"], "best_model": run["best_model"], **out}
