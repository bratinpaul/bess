"""Multivariate anomaly detection API (mounted at /mv-anomaly): options, preview, model building, scoring other windows
with a built model, live micro-batch scoring, and the reads behind the results viewer (timeline, episodes with their
contributors and overlapping alarms, raw signals for a drill-down)."""
from datetime import date, timedelta
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.auth import can_approve
from core.db import engine
from usecases.mv_anomaly import features as F
from usecases.mv_anomaly import models as M
from usecases.mv_anomaly import store
from usecases.mv_anomaly import trainer as T

USE_CASE = "mv_anomaly"
PREFIX = "mv-anomaly"
router = APIRouter(tags=["Multivariate anomaly detection"])

DEFAULTS = T.RunConfig(system_id=0)


class WindowBody(BaseModel):
    system_id: int
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    eval_fraction: float = Field(default=DEFAULTS.eval_fraction, gt=0.05, lt=0.7)
    frozen_intervals: int = Field(default=DEFAULTS.frozen_intervals, ge=2, le=288)
    alarm_pad_min: float = Field(default=DEFAULTS.alarm_pad_min, ge=0, le=720)
    commissioning_days: int = Field(default=DEFAULTS.commissioning_days, ge=0, le=365)
    exclude_alarm_level: bool = True


class TrainBody(WindowBody):
    models: list[Literal["pca", "iforest", "robust_cov", "autoencoder", "window_ae"]] = Field(min_length=1)
    primary: Literal["pca", "iforest", "robust_cov", "autoencoder", "window_ae"] = "pca"
    model_params: dict[str, dict[str, float]] = Field(default_factory=dict)
    feature_groups: list[str] = Field(default_factory=lambda: list(F.GROUPS), min_length=1)
    regime_strategy: Literal["feature", "separate"] = "feature"
    min_regime_rows: int = Field(default=300, ge=50, le=5000)
    threshold_pct: float = Field(default=99.5, ge=90, le=99.99)
    threshold_mode: Literal["percentile", "best_f1"] = "percentile"
    smooth_window: int = Field(default=3, ge=1, le=24)
    debounce: int = Field(default=3, ge=1, le=24)
    top_k: int = Field(default=3, ge=1, le=8)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class ScoreBody(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    run_name: Optional[str] = Field(default=None, max_length=120)


class LiveBody(BaseModel):
    system_id: Optional[int] = None  # None = every system with a built model
    hours: int = Field(default=24, ge=1, le=24 * 31)


def status() -> dict:
    return {"systems_with_model": store.default_systems(engine)}


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


def _get(run_id: int) -> dict:
    run = store.get_run(engine, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return run


def _artifact(run: dict) -> tuple[dict, dict]:
    model = store.model_run(engine, run)
    if not model or model["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Run #{run['run_id']} has no completed model")
    try:
        return model, store.load_artifact(model)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/options")
def options():
    return {
        "systems": F.systems(engine),
        "models": [{"key": k, "label": M.MODEL_LABELS[k], "interpretable": k in M.INTERPRETABLE,
                    "params": M.PARAM_SPECS[k], "defaults": M.DEFAULT_PARAMS[k]} for k in M.DETECTORS],
        "feature_groups": [{"key": g, "label": lbl,
                            "features": [{"key": f, "label": v[0]} for f, v in F.FEATURES.items() if v[1] == g]}
                           for g, lbl in F.GROUPS.items()],
        "regimes": F.REGIMES, "soc_bands": F.SOC_BAND_LABELS,
        "frozen_signals": [{"key": k, "label": F.FEATURES.get(k, (k,))[0], "only_when_active": v}
                           for k, v in F.FROZEN_SIGNALS.items()],
        "defaults": {"models": DEFAULTS.models, "primary": DEFAULTS.primary, "regime_strategy": DEFAULTS.regime_strategy,
                     "min_regime_rows": DEFAULTS.min_regime_rows, "eval_fraction": DEFAULTS.eval_fraction,
                     "threshold_pct": DEFAULTS.threshold_pct, "threshold_mode": DEFAULTS.threshold_mode,
                     "smooth_window": DEFAULTS.smooth_window, "debounce": DEFAULTS.debounce,
                     "frozen_intervals": DEFAULTS.frozen_intervals, "alarm_pad_min": DEFAULTS.alarm_pad_min,
                     "commissioning_days": DEFAULTS.commissioning_days, "top_k": DEFAULTS.top_k},
    }


@router.post("/preview")
def preview(body: WindowBody):
    cfg = T.RunConfig(body.system_id, body.date_from, body.date_to, eval_fraction=body.eval_fraction,
                      frozen_intervals=body.frozen_intervals, alarm_pad_min=body.alarm_pad_min,
                      commissioning_days=body.commissioning_days, exclude_alarm_level=body.exclude_alarm_level)
    try:
        _, _, info = T.prepare(engine, cfg)
    except T.MvAnomalyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {**info, "eval_from": info["eval_from"].isoformat()}


@router.post("/runs")
def train(request: Request, body: TrainBody):
    unknown = set(body.feature_groups) - set(F.GROUPS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown feature group(s): {', '.join(sorted(unknown))}")
    cfg = T.RunConfig(
        system_id=body.system_id, date_from=body.date_from, date_to=body.date_to, models=list(dict.fromkeys(body.models)),
        primary=body.primary, model_params=body.model_params, feature_groups=body.feature_groups,
        regime_strategy=body.regime_strategy, min_regime_rows=body.min_regime_rows, eval_fraction=body.eval_fraction,
        threshold_pct=body.threshold_pct, threshold_mode=body.threshold_mode, smooth_window=body.smooth_window,
        debounce=body.debounce, frozen_intervals=body.frozen_intervals, alarm_pad_min=body.alarm_pad_min,
        commissioning_days=body.commissioning_days, exclude_alarm_level=body.exclude_alarm_level, top_k=body.top_k)
    params = body.model_dump(exclude={"system_id", "date_from", "date_to", "run_name", "make_default"})
    run_id = store.start_run(engine, {"run_name": body.run_name, "run_kind": "train", "system_id": body.system_id,
                                      "date_from": body.date_from, "date_to": body.date_to, "params": params})
    try:
        art, result, rows, warnings = T.train(engine, cfg)
        path = store.save_artifact(run_id, art)
        store.write_scores(engine, run_id, body.system_id, rows)
        store.complete_run(engine, run_id, result, warnings, path, result["summary"]["duration_ms"])
    except (T.MvAnomalyError, ValueError) as exc:
        store.fail_run(engine, run_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": run_id})
    except Exception as exc:  # noqa: BLE001 - keep a record of unexpected failures
        store.fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Training failed: {exc}", "run_id": run_id})
    if (body.make_default and can_approve(request)) or not any(r["is_default"] for r in store.list_runs(engine, body.system_id)
                                    if r["run_kind"] == "train"):
        store.set_default(engine, run_id)  # the first model of a system becomes its live model
    return _public(store.get_run(engine, run_id))


@router.get("/runs")
def runs(system_id: Optional[int] = None, limit: int = Query(200, ge=1, le=1000)):
    return store.list_runs(engine, system_id, limit)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    run = _public(_get(run_id))
    if run["run_kind"] != "train":
        model = store.model_run(engine, run)
        if model:
            run["model"] = {k: model[k] for k in ("run_id", "run_name", "params", "thresholds", "features", "metrics")}
    return run


@router.post("/runs/{run_id}/default", status_code=204)
def make_default(run_id: int):
    if not store.set_default(engine, run_id):
        raise HTTPException(status_code=400, detail=f"Run #{run_id} is not a completed model run")


@router.delete("/runs/{run_id}", status_code=204)
def delete(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


@router.post("/runs/{run_id}/score")
def score(run_id: int, body: ScoreBody):
    """Apply a built model (no refit) to another window -> a new 'score' run."""
    model, art = _artifact(_get(run_id))
    new_id = store.start_run(engine, {"run_name": body.run_name, "run_kind": "score", "parent_run_id": model["run_id"],
                                      "system_id": model["system_id"], "date_from": body.date_from,
                                      "date_to": body.date_to, "params": {}})
    try:
        rows, summary, warnings = T.score_window(engine, art, F.Window(model["system_id"], body.date_from, body.date_to))
        store.write_scores(engine, new_id, model["system_id"], rows)
        store.complete_run(engine, new_id, {"summary": summary}, warnings, None, 0)
    except T.MvAnomalyError as exc:
        store.fail_run(engine, new_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": new_id})
    except Exception as exc:  # noqa: BLE001
        store.fail_run(engine, new_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Scoring failed: {exc}", "run_id": new_id})
    return _public(store.get_run(engine, new_id))


def live_score(system_id: Optional[int], hours: int) -> list[dict]:
    """Micro-batch: the default model of each system scores the newest `hours` of telemetry into its live run
    (upsert). Used by POST /live/score and by usecases/mv_anomaly/batch.py."""
    out = []
    for sid in ([system_id] if system_id else store.default_systems(engine)):
        model = store.default_run(engine, sid)
        if not model:
            out.append({"system_id": sid, "status": "skipped", "message": "no built model"})
            continue
        last = T.latest_ts(engine, sid)
        if last is None:
            out.append({"system_id": sid, "status": "skipped", "message": "no telemetry"})
            continue
        last = pd.Timestamp(last).tz_convert("Asia/Kolkata")
        start = last - pd.Timedelta(hours=hours)
        art = store.load_artifact(model)
        rows, _, warnings = T.score_window(engine, art, F.Window(sid, start.date(), last.date()), split="live")
        rows = rows[rows["ts"] > start].reset_index(drop=True)
        live_id = store.live_run(engine, model)
        store.write_scores(engine, live_id, sid, rows, upsert=True)
        summary = {"rows": int(len(rows)), "flagged_intervals": int(rows["is_anomaly"].sum()),
                   "model_flag_intervals": int(rows["model_flag"].sum()), "window_start": start.isoformat(),
                   "window_end": last.isoformat()}
        store.touch_live(engine, live_id, summary, warnings, start.date(), last.date())
        out.append({"system_id": sid, "status": "ok", "model_run_id": model["run_id"], "live_run_id": live_id,
                    **summary, "warnings": warnings})
    return out


@router.post("/live/score")
def live(body: LiveBody):
    try:
        return live_score(body.system_id, body.hours)
    except T.MvAnomalyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- results viewer reads --------------------------------------------------------------------------------------------

@router.get("/runs/{run_id}/timeline")
def run_timeline(run_id: int, start: Optional[str] = None, end: Optional[str] = None,
                 max_points: int = Query(1500, ge=100, le=20000)):
    _get(run_id)
    return store.timeline(store.score_frame(engine, run_id, start, end), max_points)


@router.get("/runs/{run_id}/episodes")
def run_episodes(run_id: int, start: Optional[str] = None, end: Optional[str] = None):
    run = _get(run_id)
    model = store.model_run(engine, run)
    pad = (model or {}).get("params", {}).get("alarm_pad_min", 30.0)
    df = store.score_frame(engine, run_id, start, end)
    if df.empty:
        return []
    al = F.alarms(engine, F.Window(run["system_id"], df["ts"].min().date(), df["ts"].max().date()))
    return T.episodes(df, al, pad)


@router.get("/runs/{run_id}/alarms")
def run_alarms(run_id: int, start: Optional[str] = None, end: Optional[str] = None):
    run = _get(run_id)
    df = store.score_frame(engine, run_id, start, end)
    if df.empty:
        return []
    al = F.alarms(engine, F.Window(run["system_id"], df["ts"].min().date(), df["ts"].max().date()))
    return [{"alarm_id": r.alarm_id, "start": r.start_ts.isoformat(), "end": r.end_ts.isoformat(),
             "alarm_code": r.alarm_code, "source": r.source,
             "severity": int(r.severity_level) if pd.notna(r.severity_level) else None} for r in al.itertuples()]


@router.get("/runs/{run_id}/contributors")
def run_contributors(run_id: int):
    """Share of each feature in the attribution of the model-flagged intervals (what drives this run's flags)."""
    _get(run_id)
    df = store.score_frame(engine, run_id)
    agg: dict[str, dict] = {}
    flagged = df[df["model_flag"]] if not df.empty else df
    for lst in flagged.get("top_contributors", []):
        for c in lst or []:
            e = agg.setdefault(c["feature"], {"feature": c["feature"], "label": c["label"], "share": 0.0, "count": 0})
            e["share"] += c["share"]
            e["count"] += 1
    tot = sum(e["share"] for e in agg.values()) or 1.0
    rules: dict[str, int] = {}
    for lst in (df["rule_flags"] if not df.empty else []):
        for f in lst:
            rules[f] = rules.get(f, 0) + 1
    return {"features": sorted(({**e, "share": round(e["share"] / tot, 4)} for e in agg.values()),
                               key=lambda e: -e["share"]),
            "rules": [{"flag": k, "intervals": v} for k, v in sorted(rules.items(), key=lambda t: -t[1])],
            "flagged_intervals": int(len(flagged))}


@router.get("/runs/{run_id}/signals")
def run_signals(run_id: int, start: str, end: str, features: str = Query(..., description="comma-separated keys")):
    """Raw / derived signal values (residuals from the run's model) for a drill-down window."""
    run = _get(run_id)
    _, art = _artifact(run)
    keys = [k for k in features.split(",") if k in F.FEATURES]
    if not keys:
        raise HTTPException(status_code=400, detail="No known feature keys")
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    if t1 <= t0 or t1 - t0 > pd.Timedelta(days=14):
        raise HTTPException(status_code=400, detail="The window must be positive and at most 14 days")
    raw = F.load_frame(engine, F.Window(run["system_id"], t0.date(), t1.date()), lookback_intervals=6)
    if raw.empty:
        return {"features": keys, "points": []}
    df = F.apply_residuals(F.derive(raw), art["residuals"])
    df = df[(df["ts"] >= t0) & (df["ts"] <= t1)]
    return {"features": [{"key": k, "label": F.FEATURES[k][0]} for k in keys],
            "points": [{"ts": r["ts"].isoformat(), **{k: (None if pd.isna(r[k]) else round(float(r[k]), 4)) for k in keys}}
                       for _, r in df.iterrows()]}
