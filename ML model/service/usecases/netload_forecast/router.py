"""Net-load & demand / peak forecasting API (mounted at /netload-forecast): options, preview, model generation runs,
scores, backtests and the live forecast."""
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from bess_common.errors import run_guard
from core.auth import can_approve
from core.db import engine
from core.metrics import finite
from usecases.netload_forecast import features as F
from usecases.netload_forecast import store
from usecases.netload_forecast import trainer as T
from usecases.netload_forecast.models import ALL_MODELS, BASELINE, PEAK, clean_params
from usecases.netload_forecast.schemas import SelectionIn, TrainRequest

USE_CASE = "netload_forecast"
PREFIX = "netload-forecast"
router = APIRouter(tags=["Net-load & peak forecasting"])


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _selection(body: SelectionIn) -> F.Selection:
    unknown = [g for g in body.feature_groups if g not in F.FEATURE_GROUPS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown feature group(s): {', '.join(unknown)}")
    return F.Selection(body.mp_ids, body.date_from, body.date_to, body.feature_groups, body.weather_source,
                       body.peak_threshold_kw)


def _run(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed net-load forecast model yet" if model == "active"
                            else f"Run {model} is not a completed net-load forecast run")
    return run, store.load_artifact(run)


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


@router.get("/options")
def options():
    points = F.metering_points(engine)
    return {
        "units": points,
        "tariffs": {str(p["mp_id"]): F.tariff(engine, p["site_id"]) for p in points},
        "feature_groups": [{"key": k, "label": v, "required": k in F.REQUIRED_GROUPS, "features": F.GROUP_FEATURES[k]}
                           for k, v in F.FEATURE_GROUPS.items()],
        "models": [{"key": k, "label": c.label, "family": c.family, "params": c.param_specs, "always": k == BASELINE}
                   for k, c in ALL_MODELS.items()],
        "defaults": {"horizon_hours": 48, "test_fraction": 0.25, "origin_step_h": 3, "train_origin_step_h": 2,
                     "weather_source": "forecast"},
    }


@router.post("/preview")
def preview(body: SelectionIn):
    """Days, gaps, weather-forecast coverage and the daily billing peaks per metering point in the selection."""
    meta = {m["mp_id"]: m for m in F.metering_points(engine)}
    cal = F.calendar(engine)
    out = []
    for mp in body.mp_ids:
        df = F.demand(engine, mp, body.date_from, body.date_to)
        m = meta.get(mp)
        if df.empty or m is None:
            out.append({"mp_id": mp, "readings": 0})
            continue
        s = F.Series.build(engine, m, df, cal, F.tariff(engine, m["site_id"]))
        pk = s.daily_peaks()
        dates = sorted(set(df.index.date))
        wd, hol = s.day_info(np.array(dates))
        out.append({
            "mp_id": mp, "readings": int(df["net"].notna().sum()), "missing": int(df["gap"].sum()),
            "days": len(dates), "from": df.index[0].isoformat(), "to": df.index[-1].isoformat(),
            "workdays": int(wd.sum()), "holidays": int(hol.sum()),
            "calendar_missing": int(sum(d not in cal for d in dates)),
            "weather_actual_share": finite(float(np.isfinite(s.temp).mean())),
            "weather_runs": len(s.runs), "window": list(s.window),
            "peaks": [{"date": str(d), "peak": finite(r["peak"]), "peak_ts": pd.Timestamp(r["peak_ts"]).isoformat(),
                       "workday": bool(s.cal.get(d, (d.weekday() < 5,))[0])} for d, r in pk.iterrows()],
            "peak_p75": finite(float(np.quantile(pk["peak"], 0.75))) if len(pk) else None,
        })
    return {"units": out}


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    sel = _selection(body)
    unknown = [m for m in body.models if m not in ALL_MODELS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown model(s): {', '.join(unknown)}")
    models = [BASELINE] + [m for m in body.models if m != BASELINE]
    params = {m: clean_params(ALL_MODELS[m], body.params.get(m, {})) for m in models}
    stored = {**params, "train_origin_step_h": body.train_origin_step_h, "random_state": body.random_state}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "mp_ids": body.mp_ids, "date_from": body.date_from, "date_to": body.date_to,
        "horizon_hours": body.horizon_hours, "test_fraction": body.test_fraction, "origin_step_h": body.origin_step_h,
        "feature_groups": sel.feature_groups, "weather_source": body.weather_source,
        "peak_threshold_kw": body.peak_threshold_kw, "models": models, "params": stored})
    cfg = T.RunConfig(sel, models, params, body.horizon_hours, body.test_fraction, body.origin_step_h,
                      body.train_origin_step_h, body.random_state)
    with run_guard(fail=lambda msg: store.fail_run(engine, run_id, msg), context={"run_id": run_id}):
        result = T.train(engine, cfg)
        artifact = store.save_artifact(run_id, result.artifact)
        store.complete_run(engine, run_id, result.summary, result.points, result.peaks, result.warnings, artifact,
                           result.artifact["threshold"])
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
def run_origins(run_id: int, mp_id: int):
    return store.origins(engine, run_id, mp_id)


@router.get("/runs/{run_id}/peaks")
def run_peaks(run_id: int, mp_id: int):
    """Every backtest daily-peak forecast of the run (per origin, target day and model)."""
    return store.peak_table(engine, run_id, mp_id)


@router.get("/runs/{run_id}/backtest")
def run_backtest(run_id: int, mp_id: int, origin_ts: datetime, history_hours: int = Query(24, ge=0, le=168)):
    """Every model's forecast from one backtest origin, its daily peaks, and the actual load around it."""
    pts, pks = store.backtest(engine, run_id, mp_id, origin_ts)
    if not pts:
        raise HTTPException(status_code=404, detail="No backtest forecast for this origin")
    first = pd.Timestamp(min(p["target_ts"] for p in pts))
    last = pd.Timestamp(max(p["target_ts"] for p in pts))
    start = first - pd.Timedelta(hours=history_hours, minutes=F.STEP_MIN)
    df = F.demand(engine, mp_id, start.date(), last.date())
    df = df[(df.index >= start) & (df.index <= last)]
    return {"origin_ts": origin_ts.isoformat(), "points": pts, "peaks": pks,
            "history": [{"ts": t.isoformat(), "net": finite(a), "gross": finite(b), "gen": finite(c)}
                        for t, a, b, c in zip(df.index, df["net"], df["gross"], df["gen"])]}


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
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "mp_ids", "models", "best_model", "metrics",
                                "horizon_hours", "peak_threshold_kw", "weather_source", "finished_at")} for r in out]


@router.get("/forecast")
def forecast(mp_id: int, model: str = "active", history_hours: int = Query(48, ge=6, le=336),
             threshold_kw: Optional[float] = Query(None, gt=0)):
    """The next horizon from the newest reading of the metering point, with every model of the run, and the daily
    billing peaks (optionally against another threshold than the run's)."""
    run, art = _run(model)
    out = T.forecast(engine, art, mp_id, history_hours, threshold_kw)
    return {"run_id": run["run_id"], "best_model": run["best_model"], "has_classifier": PEAK in art["models"], **out}
