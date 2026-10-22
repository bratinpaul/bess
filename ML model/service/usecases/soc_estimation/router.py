"""SOC estimation / correction API (mounted at /soc-estimation): options, model building runs and their timelines,
the stateful per-system estimator (live or replayed as of a time) and a single EKF step for the I/O contract."""
from datetime import date, datetime
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from core.auth import can_approve
from core.db import engine
from core.metrics import finite
from usecases.soc_estimation import ekf as E
from usecases.soc_estimation import features as F
from usecases.soc_estimation import store
from usecases.soc_estimation import trainer as T

USE_CASE = "soc_estimation"
PREFIX = "soc-estimation"
router = APIRouter(tags=["SOC estimation / correction"])

METHOD_LABELS = {
    "coulomb": "Coulomb counting (raw)",
    "ocv_lookup": "OCV lookup (naïve)",
    "bms": "BMS reported",
    "ekf": "EKF",
    "gbm": "Coulomb + LightGBM",
    "hybrid": "EKF + LightGBM (hybrid)",
}
SCOPE_LABELS = {
    "anchors": "Anchors · all",
    "anchors_rest": "Anchors · REST_OCV",
    "anchors_full": "Anchors · FULL_CHARGE",
    "dense": "Dense truth · all rows",
    "dense_flat": "Dense truth · flat 25–80 %",
    "dense_active": "Dense truth · under current",
}
WARMUP_H = 48           # replay starts this long before the window so the filter has recalibrated at least once
STALE_AFTER_MIN = 15    # inputs older than this (vs now / as-of) are stale
ANCHOR_WINDOW_H = 24    # no OCV update or FULL_CHARGE recalibration for this long -> "no anchor"


class TrainRequest(BaseModel):
    system_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    test_fraction: float = Field(default=0.25, gt=0.05, lt=0.6)
    label_source: Literal["anchors", "dense"] = "anchors"
    tune_ekf: bool = True
    full_charge_reset: bool = True
    ekf_params: dict[str, Any] = Field(default_factory=dict)
    gbm_params: dict[str, Any] = Field(default_factory=dict)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class EstimateRequest(BaseModel):
    system_id: int
    as_of: Optional[datetime] = None   # None = live (newest inputs, stateful)
    history_hours: int = Field(default=24, ge=1, le=240)
    reset: bool = False                # live: drop the carried EKF state and re-initialise


class StepState(BaseModel):
    soc: float = Field(ge=0, le=100)
    bias: float = 0.0
    gain: float = Field(default=1.0, ge=0.5, le=1.5)
    sigma_soc: float = Field(default=1.0, gt=0, le=50)
    direction: Literal["CHARGE", "DISCHARGE", "MEAN"] = "MEAN"
    ts: Optional[datetime] = None
    last_recal_ts: Optional[datetime] = None
    last_ocv_ts: Optional[datetime] = None


class StepFeatures(BaseModel):
    soc_coulomb_pct: float = Field(ge=-5, le=105)
    measured_current_a: float
    current_sensor_offset_a: float = 0.0
    pack_voltage_v: Optional[float] = None
    cell_v_avg_v: Optional[float] = None
    ocv_rested_v: Optional[float] = Field(default=None, ge=1.5, le=4.5)
    cell_temp_avg_c: float = Field(default=25.0, ge=-40, le=90)
    usable_capacity_ah: float = Field(gt=0)
    c_rate: Optional[float] = None
    coulombic_efficiency: float = Field(default=1.0, gt=0.5, le=1.0)
    at_rest: bool = False
    rest_duration_min: float = Field(default=0.0, ge=0)
    soc_bms_pct: Optional[float] = None


class StepRequest(BaseModel):
    system_id: int
    ts: Optional[datetime] = None
    dt_min: float = Field(default=5.0, gt=0, le=1440)
    state: StepState
    features: StepFeatures
    anchor_soc_pct: Optional[float] = Field(default=None, ge=0, le=100)
    anchor_method: Optional[Literal["FULL_CHARGE", "REST_OCV"]] = None


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


def _run(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed SOC estimation model yet" if model == "active"
                            else f"Run {model} is not a completed SOC estimation run")
    try:
        return run, store.load_artifact(run)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/options")
def options():
    return {"systems": F.systems(engine), "gbm_params": T.GBM_PARAMS, "ekf_params": T.EKF_PARAMS,
            "tune_grid": T.TUNE_GRID, "methods": METHOD_LABELS, "scopes": SCOPE_LABELS,
            "defaults": {"test_fraction": 0.25, "label_source": "anchors", "tune_ekf": True, "full_charge_reset": True}}


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    try:
        gbm = T.clean_gbm(body.gbm_params)
        ekf = T.clean_ekf(body.ekf_params)
    except T.SocEstimationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    params = {"gbm": gbm, "ekf": ekf, "tune_ekf": body.tune_ekf, "full_charge_reset": body.full_charge_reset,
              "label_source_requested": body.label_source}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "system_ids": body.system_ids, "date_from": body.date_from, "date_to": body.date_to,
        "test_fraction": body.test_fraction, "label_source": body.label_source, "params": params})
    cfg = T.RunConfig(F.Selection(body.system_ids, body.date_from, body.date_to), body.test_fraction, body.label_source,
                      body.tune_ekf, ekf, body.full_charge_reset, gbm)
    try:
        artifact, summary, points, warnings = T.train(engine, cfg)
        path = store.save_artifact(run_id, artifact)
        store.complete_run(engine, run_id, summary, points, warnings, path)
    except (T.SocEstimationError, ValueError) as exc:
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


@router.get("/runs/{run_id}/range")
def run_range(run_id: int, system_id: int):
    return store.point_range(engine, run_id, system_id)


@router.get("/runs/{run_id}/points")
def run_points(run_id: int, system_id: int, ts_from: Optional[datetime] = None, ts_to: Optional[datetime] = None):
    """The run's per-row estimates of one system (every method, bands, anchors, dense truth) between two times."""
    return store.points(engine, run_id, system_id, ts_from, ts_to)


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
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "system_ids", "label_source", "best_method",
                                "primary_scope", "metrics", "finished_at")} for r in out]


# ---------------------------------------------------------------- estimator


def _row_out(ts, r: pd.Series) -> dict:
    return {"ts": ts.isoformat(), **{k: (finite(r[k]) if isinstance(r[k], (float, int, np.floating)) and not isinstance(r[k], bool)
                                         else (bool(r[k]) if isinstance(r[k], (bool, np.bool_)) else r[k]))
                                     for k in ("coulomb", "bms", "anchor", "anchor_method", "ocv_soc", "ekf", "ekf_p10",
                                               "ekf_p90", "hybrid", "hybrid_p10", "hybrid_p90", "gbm", "ekf_bias",
                                               "ekf_gain", "recal_kind", "at_rest", "min_since_recal")}}


def _clean(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return v


def _output(system_id: int, ts, r: pd.Series, end_state: E.EkfState) -> dict:
    """The I/O contract record of one row."""
    corrected = float(r["hybrid"])
    return {
        "system_id": system_id, "ts": ts.isoformat(),
        "soc_corrected_pct": finite(corrected), "p10": finite(r["hybrid_p10"]), "p90": finite(r["hybrid_p90"]),
        "drift_correction_pct": finite(corrected - r["coulomb"]) if r["coulomb"] == r["coulomb"] else None,
        "recalibrated": bool(r["recalibrated"]), "recal_kind": r["recal_kind"],
        "soc_coulomb_pct": finite(r["coulomb"]), "soc_bms_pct": _clean(finite(r["bms"])) if r["bms"] == r["bms"] else None,
        "ekf": {"soc": finite(r["ekf"]), "p10": finite(r["ekf_p10"]), "p90": finite(r["ekf_p90"]),
                "bias_a": finite(r["ekf_bias"]), "gain": finite(r["ekf_gain"]), "direction": r["direction"],
                "innovation_mv": finite(r["innovation_mv"]) if r["innovation_mv"] == r["innovation_mv"] else None},
        "ocv_soc": finite(r["ocv_soc"]) if r["ocv_soc"] == r["ocv_soc"] else None,
        "min_since_recal": finite(r["min_since_recal"]) if r["min_since_recal"] == r["min_since_recal"] else None,
        "last_recal_ts": end_state.last_recal_ts,
    }


def _flags(engine_ts_last: pd.Timestamp, ref_now: pd.Timestamp, telemetry_to: Optional[pd.Timestamp],
           out: dict, anchors_total: int) -> tuple[dict, list[str]]:
    msgs = []
    age = (ref_now - engine_ts_last).total_seconds() / 60
    stale = age > STALE_AFTER_MIN
    if stale:
        msgs.append(f"Inputs are stale: the newest SOC-estimation reading is {age / 60:.1f} h old")
    behind = telemetry_to is not None and telemetry_to > engine_ts_last and telemetry_to <= ref_now + pd.Timedelta(minutes=1)
    if behind:
        msgs.append(f"Telemetry runs to {telemetry_to.strftime('%Y-%m-%d %H:%M')} but without the SOC-estimation columns "
                    f"(soc_coulomb_pct ...) - the estimate stops at {engine_ts_last.strftime('%Y-%m-%d %H:%M')}")
    since = out["min_since_recal"]
    no_anchor = since is None or since > ANCHOR_WINDOW_H * 60
    if no_anchor:
        msgs.append("No anchor: no rested-OCV update or FULL_CHARGE recalibration in the last "
                    f"{ANCHOR_WINDOW_H} h - the estimate is coulomb counting with the learnt bias")
    if not anchors_total:
        msgs.append("This system has no soc_reference anchors - FULL_CHARGE recalibration is unavailable")
    return {"stale": stale, "stale_minutes": finite(age), "behind_telemetry": behind,
            "telemetry_to": telemetry_to.isoformat() if telemetry_to is not None else None,
            "no_anchor": no_anchor, "hours_since_recal": finite(since / 60) if since is not None else None,
            "anchors_total": anchors_total}, msgs


@router.get("/state")
def state(system_id: int, model: str = "active"):
    run, _ = _run(model)
    return {"run_id": run["run_id"], "state": store.get_state(engine, run["run_id"], system_id)}


@router.post("/estimate")
def estimate(body: EstimateRequest, model: str = "active"):
    """Corrected SOC per the I/O contract at the newest reading (live: the carried EKF state is advanced over the rows
    since it and saved) or as of a time (replay from WARMUP_H before the window, nothing saved), with the trajectory
    of the last history_hours and staleness / anchor flags."""
    run, art = _run(model)
    sid = body.system_id
    if sid not in art["systems"]:
        raise HTTPException(status_code=400, detail=f"System {sid} is not part of run #{run['run_id']} "
                                                    f"(trained on {', '.join(map(str, art['systems']))})")
    as_of = pd.Timestamp(body.as_of) if body.as_of else None
    if as_of is not None:
        as_of = as_of.tz_localize(F.TZ) if as_of.tzinfo is None else as_of.tz_convert(F.TZ)
    last = F.series(engine, sid, (as_of or pd.Timestamp.now(tz=F.TZ)) - pd.Timedelta(days=400), as_of)
    if last.empty:
        raise HTTPException(status_code=400, detail="No SOC-estimation inputs for this system"
                                                    + (f" before {as_of:%Y-%m-%d %H:%M}" if as_of is not None else ""))
    end_ts = last.index[-1]
    start = end_ts - pd.Timedelta(hours=body.history_hours + WARMUP_H)
    df = last[last.index >= start]
    try:
        rows, end_state = T.estimate_rows(art, sid, df, T.seed_state(art, sid, float(df["soc_coulomb_pct"].iloc[0])))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    mode = "replay"
    current = _output(sid, end_ts, rows.iloc[-1], end_state)
    if as_of is None:
        mode = "live"
        run_id = run["run_id"]
        saved = None if body.reset else store.get_state(engine, run_id, sid)
        if saved and saved.get("ts") and pd.Timestamp(saved["ts"]) <= end_ts:
            st = E.EkfState(**{k: saved[k] for k in E.EkfState.__dataclass_fields__})
            new = last[last.index > pd.Timestamp(st.ts)]
            if len(new):
                r2, end_state = T.estimate_rows(art, sid, new, st)
                current = _output(sid, new.index[-1], r2.iloc[-1], end_state)
            else:
                current = saved.get("last_output") or current
                end_state = st
        store.save_state(engine, run_id, sid, {**end_state.to_dict(), "last_output": current})
    with engine.connect() as conn:
        anchors_total = conn.execute(text("SELECT count(*) FROM battery_master.soc_reference WHERE system_id = :s"),
                                     {"s": sid}).scalar() or 0
    flags, msgs = _flags(end_ts, as_of or pd.Timestamp.now(tz=F.TZ), F.latest_telemetry_ts(engine, sid), current, anchors_total)
    window = rows[rows.index > end_ts - pd.Timedelta(hours=body.history_hours)]
    inputs = df.iloc[-1]
    return {
        "run_id": run["run_id"], "mode": mode, **current, "flags": flags, "messages": msgs,
        "state": end_state.to_dict(),
        "inputs": {k: (finite(inputs[k]) if isinstance(inputs[k], (float, np.floating)) and inputs[k] == inputs[k]
                       else (bool(inputs[k]) if isinstance(inputs[k], (bool, np.bool_)) else None))
                   for k in ("soc_coulomb_pct", "soc_bms_pct", "measured_current_a", "current_sensor_offset_a",
                             "pack_voltage_v", "cell_v_avg_v", "ocv_rested_v", "cell_temp_avg_c", "usable_capacity_ah",
                             "c_rate", "coulombic_efficiency", "at_rest", "rest_duration_min")},
        "params": art["systems"][sid]["params"], "band_scale": art["systems"][sid].get("band_scale", 1.0),
        "trajectory": [_row_out(t, r) for t, r in window.iterrows()],
    }


@router.post("/estimate/step")
def step(body: StepRequest, model: str = "active"):
    """One EKF + correction step from an entered state and feature vector (the I/O contract, stateless)."""
    run, art = _run(model)
    sid = body.system_id
    if sid not in art["systems"]:
        raise HTTPException(status_code=400, detail=f"System {sid} is not part of run #{run['run_id']}")
    s = art["systems"][sid]
    p = E.EkfParams(**s["params"])
    st_in = body.state
    ts = pd.Timestamp(body.ts) if body.ts else (pd.Timestamp(st_in.ts) + pd.Timedelta(minutes=body.dt_min) if st_in.ts
                                                 else pd.Timestamp.now(tz=F.TZ).floor("5min"))
    ts = ts.tz_localize(F.TZ) if ts.tzinfo is None else ts.tz_convert(F.TZ)
    prev = ts - pd.Timedelta(minutes=body.dt_min)
    iso = lambda v: (pd.Timestamp(v).tz_localize(F.TZ) if pd.Timestamp(v).tzinfo is None else pd.Timestamp(v)).isoformat() if v else None  # noqa: E731
    scale = s.get("band_scale", 1.0)
    state_obj = E.EkfState(st_in.soc, st_in.bias, st_in.gain,
                           [[(st_in.sigma_soc / scale) ** 2, 0, 0], [0, p.init_sigma_bias ** 2 / 4, 0], [0, 0, (p.init_sigma_gain / 4) ** 2]],
                           st_in.direction, prev.isoformat(), iso(st_in.last_recal_ts),
                           # without the last OCV time, the last recalibration stands in (keeps the OCV-update spacing)
                           iso(st_in.last_ocv_ts or st_in.last_recal_ts))
    f = body.features.model_dump()
    row = {k: (np.nan if v is None else v) for k, v in f.items()}
    row.update({"soc_true_pct": body.anchor_soc_pct if body.anchor_soc_pct is not None else np.nan,
                "reference_method": body.anchor_method, "gap_min": body.dt_min, "soc_reported_pct": np.nan})
    df = pd.DataFrame([row], index=pd.DatetimeIndex([ts]))
    df["at_rest"] = df["at_rest"].astype(bool)
    if not body.features.at_rest:
        df["ocv_rested_v"] = np.nan
    try:
        rows, end_state = T.estimate_rows(art, sid, df, state_obj)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    out = _output(sid, ts, rows.iloc[-1], end_state)
    msgs = []
    if body.features.ocv_rested_v is not None and not body.features.at_rest:
        msgs.append("ocv_rested_v ignored: only valid when at_rest")
    elif body.features.at_rest and body.features.ocv_rested_v is not None and body.features.rest_duration_min < p.min_rest_min:
        msgs.append(f"OCV not used yet: rest {body.features.rest_duration_min:g} min < {p.min_rest_min:g} min relaxation")
    if out["min_since_recal"] is None:
        msgs.append("No anchor: no recalibration time in the state - the band will keep widening")
    return {"run_id": run["run_id"], **out, "messages": msgs, "state": end_state.to_dict(),
            "sigma_soc": finite((out["ekf"]["p90"] - out["ekf"]["p10"]) / (2 * E.Z90))}
