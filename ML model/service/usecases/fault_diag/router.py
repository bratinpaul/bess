"""Fault classification / diagnosis API (mounted at /fault-diag): options, training runs (signature engine + ML + fusion),
out-of-fold episode diagnoses, publishing to fault_prediction, windowed scans with candidate review (the confirmation
loop), and the reliability analytics behind the viewer (overview, Pareto, fishbone, model scoring)."""
from datetime import date
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.auth import require, tenant_system_ids
from core.db import engine
from usecases.fault_diag import analysis as A
from usecases.fault_diag import data as D
from usecases.fault_diag import engine as E
from usecases.fault_diag import features as F
from usecases.fault_diag import model as M
from usecases.fault_diag import run as R
from usecases.fault_diag import store

USE_CASE = "fault_diag"
PREFIX = "fault-diag"
router = APIRouter(tags=["Fault classification / diagnosis"])

# RBAC (battery_users.role_privilege): viewing needs ml.results:read (every role); training / scanning needs
# ml.run:execute and deleting ml.run:delete (Admin, Data Scientist); default / publish promote a model to production
# use and need ml.model:approve (Admin); confirming a candidate needs fault.review:write (Admin, Asset Engineer,
# Operator, Data Scientist).
READ = [Depends(require("ml.results:read"))]
TRAIN = [Depends(require("ml.run:execute"))]
DELETE = [Depends(require("ml.run:delete"))]
PROMOTE = [Depends(require("ml.model:approve"))]
REVIEW = [Depends(require("fault.review:write"))]

_D = R.RunConfig()


class TrainBody(BaseModel):
    run_name: Optional[str] = Field(default=None, max_length=120)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    leakage_mode: Literal["triage", "early"] = _D.leakage_mode
    granularity: Literal["episode", "window"] = _D.granularity
    lookback_min: int = Field(default=_D.lookback_min, ge=15, le=720)
    post_min: int = Field(default=_D.post_min, ge=0, le=120)
    step_min: int = Field(default=_D.step_min, ge=5, le=120)
    max_span_min: int = Field(default=_D.max_span_min, ge=15, le=1440)
    n_none: int = Field(default=_D.n_none, ge=5, le=500)
    none_guard_h: float = Field(default=_D.none_guard_h, ge=0, le=48)
    families: list[Literal["telemetry", "signature", "alarm", "context"]] = Field(default_factory=lambda: list(F.FAMILIES), min_length=1)
    soft_pct: float = Field(default=_D.soft_pct, gt=0, le=1)
    folds: int = Field(default=_D.folds, ge=2, le=10)
    train_frac: float = Field(default=_D.train_frac, ge=0.4, le=0.9)
    alpha: float = Field(default=_D.alpha, ge=0, le=1)
    calibrate: bool = _D.calibrate
    alert_threshold: float = Field(default=_D.alert_threshold, ge=0.05, le=0.99)
    # signature engine
    kappa: float = Field(default=_D.engine.kappa, gt=0, le=10)
    absent_penalty: float = Field(default=_D.engine.absent_penalty, ge=0, le=1)
    none_prior: float = Field(default=_D.engine.none_prior, gt=0, lt=1)
    none_bias: float = Field(default=_D.engine.none_bias, ge=-10, le=10)
    unknown_penalty: float = Field(default=_D.engine.unknown_penalty, ge=0, le=10)
    mute_rate: float = Field(default=_D.engine.mute_rate, ge=0, le=1)
    prior: Literal["empirical", "uniform"] = _D.engine.prior
    # ML
    algorithm: Literal["lightgbm", "xgboost"] = _D.ml.algorithm
    structure: Literal["hierarchical", "flat"] = _D.ml.structure
    n_estimators: int = Field(default=_D.ml.n_estimators, ge=20, le=3000)
    learning_rate: float = Field(default=_D.ml.learning_rate, gt=0, le=1)
    max_depth: int = Field(default=_D.ml.max_depth, ge=2, le=12)
    num_leaves: int = Field(default=_D.ml.num_leaves, ge=3, le=128)
    min_child_samples: int = Field(default=_D.ml.min_child_samples, ge=1, le=50)
    class_weight_power: float = Field(default=_D.ml.class_weight_power, ge=0, le=1)
    confirmed_boost: float = Field(default=_D.ml.confirmed_boost, ge=0, le=5)
    augment: bool = _D.ml.augment
    augment_min: int = Field(default=_D.ml.augment_min, ge=2, le=30)
    augment_noise: float = Field(default=_D.ml.augment_noise, ge=0, le=1)
    seed: int = _D.ml.seed


class ScanBody(BaseModel):
    system_id: int
    date_from: date
    date_to: date
    step_min: int = Field(default=15, ge=5, le=120)
    threshold: float = Field(default=0.5, ge=0.05, le=0.99)


class ReviewBody(BaseModel):
    status: Literal["CONFIRMED", "REJECTED", "NEW"]
    actual_fault_code: Optional[str] = None


def status() -> dict:
    return {"default_run": store.default_run(engine)}


def _config(b: TrainBody) -> R.RunConfig:
    return R.RunConfig(
        leakage_mode=b.leakage_mode, granularity=b.granularity, lookback_min=b.lookback_min, post_min=b.post_min,
        step_min=b.step_min, max_span_min=b.max_span_min, n_none=b.n_none, none_guard_h=b.none_guard_h,
        families=list(b.families), soft_pct=b.soft_pct, folds=b.folds, train_frac=b.train_frac, alpha=b.alpha,
        calibrate=b.calibrate, alert_threshold=b.alert_threshold,
        engine=E.EngineSettings(kappa=b.kappa, absent_penalty=b.absent_penalty, none_prior=b.none_prior, none_bias=b.none_bias, unknown_penalty=b.unknown_penalty, prior=b.prior,
                                mute_rate=b.mute_rate),
        ml=M.MLSettings(algorithm=b.algorithm, structure=b.structure, n_estimators=b.n_estimators,
                        learning_rate=b.learning_rate, max_depth=b.max_depth, num_leaves=b.num_leaves,
                        min_child_samples=b.min_child_samples, class_weight_power=b.class_weight_power,
                        confirmed_boost=b.confirmed_boost, augment=b.augment, augment_min=b.augment_min,
                        augment_noise=b.augment_noise, seed=b.seed))


def _run_or_404(run_id: int, completed: bool = True) -> dict:
    r = store.get_run(engine, run_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    if completed and r["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Run #{run_id} is {r['status']}")
    return r


# ---------------------------------------------------------------------------------------------------- options
@router.get("/options", dependencies=READ)
def options():
    cat = D.catalog(engine)
    sigs = D.signatures(engine)
    eps = D.episodes(engine)
    support = eps["fault_code"].value_counts().to_dict()
    classes = [{"fault_code": r.fault_code, "fault_name": r.fault_name, "subsystem": r.subsystem, "category": r.category,
                "severity": D._num(r.default_severity), "safety_critical": bool(r.is_safety_critical),
                "episodes": int(support.get(r.fault_code, 0)),
                "signatures": int((sigs["fault_code"] == r.fault_code).sum())} for r in cat.itertuples()]
    return {
        "defaults": TrainBody().model_dump(mode="json"),
        "systems": D.systems(engine),
        "classes": classes,
        "families": [{"key": k, "label": v} for k, v in F.FAMILIES.items()],
        "episodes": {"n": int(len(eps)), "classes": int(eps["fault_code"].nunique()),
                     "date_from": eps["detected_ts"].min().date().isoformat() if len(eps) else None,
                     "date_to": eps["detected_ts"].max().date().isoformat() if len(eps) else None,
                     "filed_systems": sorted(int(s) for s in eps["system_id"].unique()),
                     "telemetry_systems": sorted(int(s) for s in eps["telemetry_system_id"].unique()),
                     "confirmed_by_repair": int((eps["fault_confirmed"] == True).sum())},  # noqa: E712
        "signatures": [{"signature_id": int(s.signature_id), "fault_code": s.fault_code, "signal": s.signal,
                        "kind": s.signal_kind, "operator": s.operator, "threshold": D._num(s.threshold), "unit": s.unit,
                        "window_min": int(s.window_min), "weight": float(s.weight),
                        "unavailable": D.UNAVAILABLE.get(s.signal)} for s in sigs.itertuples()],
        "model_versions": store.model_versions(engine),
    }


# ------------------------------------------------------------------------------------------------------- runs
@router.post("/runs", dependencies=TRAIN)
def create_run(body: TrainBody):
    if body.date_from and body.date_to and body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    cfg = _config(body)
    run_id = store.start_run(engine, body.run_name, body.date_from, body.date_to, body.model_dump(mode="json"))
    try:
        result = R.train(engine, cfg, body.date_from, body.date_to)
        store.complete_run(engine, run_id, result)
    except R.FaultDiagError as exc:
        store.fail_run(engine, run_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": run_id})
    except Exception as exc:  # noqa: BLE001
        store.fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Run failed: {exc}", "run_id": run_id})
    return store.get_run(engine, run_id)


@router.get("/runs", dependencies=READ)
def runs(limit: int = Query(100, ge=1, le=500)):
    return store.list_runs(engine, limit)


@router.get("/runs/{run_id}", dependencies=READ)
def run_detail(run_id: int):
    return _run_or_404(run_id, completed=False)


@router.delete("/runs/{run_id}", status_code=204, dependencies=DELETE)
def delete_run(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


@router.post("/runs/{run_id}/default", dependencies=PROMOTE)
def make_default(run_id: int):
    _run_or_404(run_id)
    store.set_default(engine, run_id)
    return store.get_run(engine, run_id)


@router.post("/runs/{run_id}/publish", dependencies=PROMOTE)
def publish(run_id: int):
    """Write the out-of-fold predictions to battery_master.fault_prediction (model_version fault-diag-r<id>)."""
    _run_or_404(run_id)
    n = store.publish(engine, run_id)
    return {"model_version": store.model_version(run_id), "rows": n}


@router.get("/runs/{run_id}/examples", dependencies=READ)
def run_examples(run_id: int, kind: Optional[Literal["episode", "none"]] = None):
    _run_or_404(run_id)
    return store.examples(engine, run_id, kind)


@router.get("/runs/{run_id}/examples/{key}", dependencies=READ)
def run_example(run_id: int, key: str):
    _run_or_404(run_id)
    x = store.example_detail(engine, run_id, key)
    if not x:
        raise HTTPException(status_code=404, detail=f"No example {key} in run #{run_id}")
    if x.get("episode_id"):
        eps = D.episodes(engine)
        e = eps[eps["episode_id"] == x["episode_id"]]
        if not e.empty:
            r = e.iloc[0]
            x["episode"] = {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in {
                "episode_id": r["episode_id"], "fault_code": r["fault_code"], "asset_type": r["asset_type"],
                "asset_code": r["asset_code"], "onset_ts": r["onset_ts"], "detected_ts": r["detected_ts"],
                "resolved_ts": r["resolved_ts"] if pd.notna(r["resolved_ts"]) else None,
                "severity_level": D._num(r["severity_level"]), "label_confidence": D._num(r["label_confidence"]),
                "root_cause_confirmed": r["root_cause_confirmed"], "operating_context": r["operating_context"],
                "alarms": r["all_alarms"], "primary_alarms": r["primary_alarms"], "component": r["component"],
                "fault_confirmed": r["fault_confirmed"], "telemetry_system_id": int(r["telemetry_system_id"])}.items()}
    return x


@router.get("/runs/{run_id}/compare", dependencies=READ)
def compare(run_id: int, model_version: Optional[str] = None):
    """This run's out-of-fold scorecards beside a logged model's (fault_prediction, e.g. xgb-fault-v1)."""
    r = _run_or_404(run_id)
    out = {"run": r["metrics"]["oof"], "episode_level": r["metrics"].get("episode_level"), "logged": None}
    mv = model_version or next((v for v in store.model_versions(engine) if not v.startswith("fault-diag-")), None)
    if mv:
        lp = store.logged_predictions(engine, mv)
        if not lp.empty:
            cat = D.catalog(engine)
            classes = list(cat["fault_code"])
            ix = {c: i for i, c in enumerate(classes)}
            p = np.zeros((len(lp), len(classes)))
            for i, row in enumerate(lp.itertuples()):
                got = {}
                for part in (row.top3 or "").split("|"):
                    if ":" in part:
                        c, v = part.rsplit(":", 1)
                        if c in ix and c not in got:
                            got[c] = float(v)
                got.setdefault(row.predicted_fault_code, float(row.probability or 0.5))
                rest = max(1e-6, 1 - sum(got.values()))
                p[i, :] = rest / max(1, len(classes) - len(got))
                for c, v in got.items():
                    p[i, ix[c]] = v
                p[i] /= p[i].sum()
            keep = lp["actual_fault_code"].isin(ix).to_numpy()
            out["logged"] = {"model_version": mv,
                             "card": M.scorecard(list(lp.loc[keep, "actual_fault_code"]), p[keep], classes, cat)}
    out["scoring"] = store.scoring(engine)
    return out


# ------------------------------------------------------------------------------------------------------- scan
@router.post("/runs/{run_id}/scan", dependencies=TRAIN)
def scan(run_id: int, body: ScanBody):
    """Windowed inference over a system / date range with the run's model; candidates go to fault_prediction
    (model_version fault-diag-r<id>-scan) for operator review."""
    r = _run_or_404(run_id)
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    if (body.date_to - body.date_from).days > 62:
        raise HTTPException(status_code=400, detail="Scan at most 62 days at a time")
    try:
        art = store.artifact(r)
        scores = R.score_windows(engine, art, body.system_id, body.date_from, body.date_to, body.step_min)
    except R.FaultDiagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    events = R.candidates(scores, body.threshold, body.step_min)
    res = store.save_scan(engine, run_id, body.system_id, scores, events, D.episodes(engine),
                          D.system_name(engine, body.system_id))
    by_fault = pd.Series([e["fault_code"] for e in events]).value_counts().to_dict() if events else {}
    return {**res, "by_fault": by_fault, "flagged_windows": int(((scores["predicted"] != R.NONE) &
                                                               (scores["probability"] >= body.threshold)).sum())}


@router.get("/runs/{run_id}/scans", dependencies=READ)
def scans(run_id: int):
    _run_or_404(run_id)
    return store.scanned_systems(engine, run_id)


@router.get("/runs/{run_id}/scan-points", dependencies=READ)
def scan_points(run_id: int, system_id: int, date_from: date, date_to: Optional[date] = None):
    _run_or_404(run_id)
    return store.scan_points(engine, run_id, system_id, date_from, date_to or date_from)


@router.get("/runs/{run_id}/candidates", dependencies=READ)
def candidates(run_id: int, system_id: Optional[int] = None):
    _run_or_404(run_id)
    return store.list_candidates(engine, run_id, system_id)


@router.post("/candidates/{candidate_id}/review", dependencies=REVIEW)
def review(candidate_id: int, body: ReviewBody):
    actual = body.actual_fault_code
    if body.status == "CONFIRMED" and not actual:
        raise HTTPException(status_code=400, detail="Confirming needs the actual fault class")
    if body.status == "REJECTED" and not actual:
        actual = R.NONE
    if body.status == "NEW":
        actual = None
    if actual and actual not in set(D.catalog(engine)["fault_code"]):
        raise HTTPException(status_code=400, detail=f"Unknown fault class {actual}")
    r = store.review_candidate(engine, candidate_id, actual, body.status)
    if not r:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found")
    return r


# -------------------------------------------------------------------------------------------------- analytics
def _range(date_from, date_to):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")


@router.get("/analytics/overview", dependencies=READ)
def overview(request: Request, date_from: Optional[date] = None, date_to: Optional[date] = None,
             system_id: Optional[int] = None):
    _range(date_from, date_to)
    return A.overview(engine, date_from, date_to, system_id, systems=tenant_system_ids(request))


@router.get("/analytics/pareto", dependencies=READ)
def pareto(request: Request, measure: Literal["count", "downtime_min", "energy_lost_kwh", "cost_usd", "labor_hours", "alarms"] = "count",
           group_by: Literal["fault", "subsystem", "category", "root_cause", "component", "asset", "alarm_code", "context"] = "fault",
           date_from: Optional[date] = None, date_to: Optional[date] = None, system_id: Optional[int] = None,
           cutoff: float = Query(0.8, ge=0.5, le=0.95)):
    _range(date_from, date_to)
    return A.pareto(engine, measure, group_by, date_from, date_to, system_id, cutoff, systems=tenant_system_ids(request))


@router.get("/analytics/effects", dependencies=READ)
def effects():
    return A.effects(engine)


def _model_insight(codes: set, run_id: Optional[int]) -> Optional[dict]:
    """Strongest features (mean |contribution|) the model used on these faults' out-of-fold windows."""
    rid = run_id or store.default_run(engine)
    if not rid:
        return None
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT label, correct, detail -> 'contributions' AS c FROM battery_ml.fault_diag_example
                                    WHERE run_id = :r AND label = ANY(:codes)"""), {"r": rid, "codes": list(codes)}).all()
    if not rows:
        return {"run_id": rid, "features": [], "recall": None, "n": 0}
    agg: dict[str, list] = {}
    for r in rows:
        for c in r.c or []:
            agg.setdefault(c["label"], []).append(abs(c["contribution"]))
    feats = sorted(({"label": k, "family": None, "mean_abs": float(np.sum(v) / len(rows))} for k, v in agg.items()),
                   key=lambda x: -x["mean_abs"])[:10]
    return {"run_id": rid, "features": feats, "n": len(rows), "recall": float(np.mean([r.correct for r in rows]))}


@router.get("/analytics/fishbone", dependencies=READ)
def fishbone(request: Request, effect: str = "ALL", date_from: Optional[date] = None, date_to: Optional[date] = None,
             system_id: Optional[int] = None, run_id: Optional[int] = None):
    _range(date_from, date_to)
    cat = D.catalog(engine)
    if effect.startswith("SUB:"):
        codes = set(cat.loc[cat["subsystem"] == effect[4:], "fault_code"])
    elif effect == "ALL":
        codes = set(cat["fault_code"]) - {R.NONE}
    else:
        codes = {effect}
    try:
        return A.fishbone(engine, effect, date_from, date_to, system_id, _model_insight(codes, run_id),
                          systems=tenant_system_ids(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/analytics/scoring", dependencies=READ)
def scoring():
    return store.scoring(engine)
