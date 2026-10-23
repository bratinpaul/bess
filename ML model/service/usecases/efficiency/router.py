"""PCS conversion & round-trip efficiency API (mounted at /efficiency): options, preview, model generation runs,
their cycles and scores, and the estimator (one operating point, one cycle)."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from bess_common.errors import NotFound, run_guard
from core.auth import can_approve
from core.db import engine
from usecases.efficiency import cycles as C
from usecases.efficiency import estimator as E
from usecases.efficiency import features as F
from usecases.efficiency import store
from usecases.efficiency import trainer as T
from usecases.efficiency.models import (BOOSTERS, EfficiencyError, GamEfficiencyModel, GreyBoxLossModel,
                                        clean_params)
from usecases.efficiency.schemas import CycleIn, PointIn, SelectionIn, TrainRequest

USE_CASE = "efficiency"
PREFIX = "efficiency"
router = APIRouter(tags=["PCS & round-trip efficiency"])


def status() -> dict:
    run = store.resolve(engine, "active")
    return {"model": run["run_id"] if run else None}


def _selection(body: SelectionIn) -> F.Selection:
    unknown = [g for g in body.feature_groups if g not in F.FEATURE_GROUPS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown feature group(s): {', '.join(unknown)}")
    return F.Selection(body.pcs_ids, body.date_from, body.date_to, body.min_load_frac, body.exclude_snapshots,
                       body.feature_groups)


def _model(model: str) -> tuple[dict, dict]:
    run = store.resolve(engine, model)
    if not run:
        raise HTTPException(status_code=404, detail="No completed efficiency model yet" if model == "active"
                            else f"Run {model} is not a completed efficiency run")
    return run, store.load_artifact(run)


@router.get("/options")
def options():
    return {
        "units": F.coverage(engine),
        "feature_groups": [{"key": k, "label": label, "required": k in F.REQUIRED_GROUPS,
                            "features": [{"key": f, **spec} for f, spec in F.FEATURES.items() if spec["group"] == k]}
                           for k, label in F.FEATURE_GROUPS.items()],
        "models": {
            "greybox": {"label": GreyBoxLossModel.label, "params": GreyBoxLossModel.param_specs},
            "gam": {"label": GamEfficiencyModel.label, "params": GamEfficiencyModel.param_specs},
            "boosters": [{"key": k, "label": b.label, "params": b.param_specs} for k, b in BOOSTERS.items()],
        },
        "cycle_features": C.CYCLE_FEATURES,
        "defaults": {"min_load_frac": 0.02, "test_fraction": 0.2, "major_share": C.CycleOptions.major_share,
                     "soc_tolerance_pct": C.CycleOptions.soc_tolerance_pct},
    }


@router.post("/preview")
def preview(body: SelectionIn):
    """Active readings the selection gives, per unit and direction."""
    df = F.build(engine, _selection(body))
    if df.empty:
        return {"rows": 0, "units": []}
    per = df.groupby("pcs_id").agg(rows=("ts", "size"), charge=("is_charge", "sum"), ts_from=("ts", "min"),
                                   ts_to=("ts", "max"), eta_mean=(F.TARGET, "mean"), eta_min=(F.TARGET, "min"))
    return {
        "rows": int(len(df)), "charge": int(df["is_charge"].sum()), "discharge": int((df["is_charge"] == 0).sum()),
        "light_load": int((df["load_frac"] < 0.1).sum()), "eta_mean": float(df[F.TARGET].mean()),
        "eta_std": float(df[F.TARGET].std()),
        "units": [{"pcs_id": int(u), "rows": int(r.rows), "charge": int(r.charge), "discharge": int(r.rows - r.charge),
                   "from": r.ts_from.isoformat(), "to": r.ts_to.isoformat(), "eta_mean": float(r.eta_mean),
                   "eta_min": float(r.eta_min)} for u, r in per.iterrows()],
    }


@router.post("/runs")
def train(request: Request, body: TrainRequest):
    """Fit the grey-box, the GAM and the residual booster, extract the cycles and store the run."""
    sel = _selection(body)
    gb = clean_params(GreyBoxLossModel.param_specs, body.greybox_params, GreyBoxLossModel.label)
    gam = clean_params(GamEfficiencyModel.param_specs, body.gam_params, GamEfficiencyModel.label)
    bst = clean_params(BOOSTERS[body.booster].param_specs, body.booster_params, BOOSTERS[body.booster].label)
    params = {"greybox": gb, "gam": gam, body.booster: bst, "major_share": body.major_share,
              "soc_tolerance_pct": body.soc_tolerance_pct, "exclude_snapshots": body.exclude_snapshots,
              "random_state": body.random_state}
    run_id = store.start_run(engine, {
        "run_name": body.run_name, "pcs_ids": body.pcs_ids, "date_from": body.date_from, "date_to": body.date_to,
        "split_method": body.split_method, "test_fraction": body.test_fraction, "min_load_frac": body.min_load_frac,
        "feature_groups": sel.feature_groups, "booster": body.booster, "params": params})
    cfg = T.RunConfig(sel, body.split_method, body.test_fraction, body.random_state, gb, gam, body.booster, bst,
                      C.CycleOptions(major_share=body.major_share, soc_tolerance_pct=body.soc_tolerance_pct))
    with run_guard(fail=lambda msg: store.fail_run(engine, run_id, msg), context={"run_id": run_id}):
        result = T.train(engine, cfg)
        artifact = store.save_artifact(run_id, result.artifact)
        store.complete_run(engine, run_id, result.summary, result.cycles, result.warnings, artifact)
    if body.make_default and can_approve(request):
        store.set_default(engine, run_id)
    return _public(store.get_run(engine, run_id))


def _public(run: dict) -> dict:
    run.pop("artifact_path", None)
    return run


@router.get("/runs")
def runs(limit: int = Query(100, ge=1, le=500)):
    return store.list_runs(engine, limit)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    run = store.get_run(engine, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return _public(run)


@router.get("/runs/{run_id}/cycles")
def run_cycles(run_id: int):
    if not store.get_run(engine, run_id, full=False):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return store.cycles(engine, run_id)


@router.get("/scores")
def scores():
    """Every completed run's scores per model and data set (battery_ml.efficiency_score), for the comparison."""
    return store.scores(engine)


@router.post("/runs/{run_id}/default", status_code=204)
def make_default(run_id: int):
    if not store.set_default(engine, run_id):
        raise HTTPException(status_code=400, detail=f"Run #{run_id} is not a completed run")


@router.delete("/runs/{run_id}", status_code=204)
def delete(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


# ---------------------------------------------------------------- estimator


@router.get("/models")
def models():
    """Completed runs for the estimator's picker (the default first)."""
    out = [r for r in store.list_runs(engine) if r["status"] == "COMPLETED"]
    out.sort(key=lambda r: (not r["is_default"], -r["run_id"]))
    return [{k: r[k] for k in ("run_id", "run_name", "is_default", "pcs_ids", "date_from", "date_to", "booster",
                                "best_model", "metrics", "n_points", "n_cycles", "finished_at")} for r in out]


@router.get("/model-info")
def model_info(model: str = "active"):
    """What the estimator needs: the units, their typical inputs, the input ranges, the curves, the measured
    points, the DC round-trip regression and the per-unit cycle figures."""
    run, art = _model(model)
    extra = store.results(engine, run["run_id"], ("curves", "rte", "greybox"))
    full = store.get_run(engine, run["run_id"])
    points = [{k: p[k] for k in ("pcs_id", "load_frac", "charge", "actual", "set")} for p in (full.get("predictions") or [])]
    return {
        "run": _public(run), "features": art["features"],
        "labels": {f: F.FEATURES[f] for f in art["features"]},
        "units": [{**info, "typical": {d: E.profile_at(art, u, d, 0.5) for d in ("charge", "discharge")},
                   "medians": art["medians"].get(u, {}), "cycle": art.get("rte_units", {}).get(str(u))}
                  for u, info in art["units"].items()],
        "ranges": art["ranges"], "curves": extra.get("curves"), "points": points,
        "dc_rte_model": (extra.get("rte") or {}).get("dc_model"), "rte": {k: v for k, v in (extra.get("rte") or {}).items()
                                                                          if k not in ("dc_model",)},
        "greybox": extra.get("greybox"),
    }


@router.get("/sample")
def sample(pcs_id: int, direction: Optional[str] = Query(None, pattern="^(charge|discharge)$"), model: str = "active"):
    """The unit's newest active reading as estimator inputs (with its measured efficiency)."""
    _, art = _model(model)
    try:
        # the newest reading the model was trained for (above its light-load cut)
        return E.sample_point(art, F.latest_point(engine, pcs_id, direction, art["min_load_frac"]), pcs_id)
    except EfficiencyError as exc:
        raise NotFound(exc.public) from exc


@router.post("/predict")
def predict(point: PointIn, model: str = "active"):
    run, art = _model(model)
    return {"run_id": run["run_id"], **E.predict_point(art, point)}


@router.post("/cycle")
def cycle(body: CycleIn, model: str = "active"):
    run, art = _model(model)
    return {"run_id": run["run_id"], **E.predict_cycle(art, body)}
