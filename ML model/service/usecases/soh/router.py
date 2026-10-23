"""SOH estimation API: SOH Estimator (models, model-info, predict, sample, average) and Model Training (train, runs).

Mounted at /soh (and, for older callers, at the root). Models are plant aware:
  * base model        plant-agnostic, trained on several (or all) battery systems; raw kWh features are not allowed
                      (they depend on plant size) - use energy throughput / rated kWh instead;
  * battery system    one plant (site -> battery system), trained from scratch on its rows or fine-tuned from a base
    model           run (continued boosting on the plant's rows, with the base run's features).
There is one default ("active") run per scope: a base default and one per battery system. Every estimator endpoint
takes ?model= : "active" or a run id, and ?system_id= : with "active" the battery system's default is used, else
the base default, else the latest base run.
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from bess_common.errors import run_guard
from core import registry
from core.base import TrainingError
from core.db import engine
from usecases.soh import features as F
from usecases.soh.models import MODELS
from usecases.soh.schemas import (DataSelectionIn, ModelInfo, SampleReading, SohEstimateResponse, SystemAverage,
                                  TrainRequest)
from usecases.soh.trainer import trainer

USE_CASE = "soh"
router = APIRouter(tags=["SOH estimation"])


def _system_names() -> dict[int, dict]:
    return {s["battery_system_id"]: s for s in F.systems(engine)}


def _scope_label(run: dict, names: Optional[dict] = None) -> str:
    if run.get("scope") == "system":
        s = (names or _system_names()).get(run["battery_system_id"]) or {}
        return f"{s.get('site_name', '?')} · {s.get('system_name', run['battery_system_id'])}"
    return "base"


def _run_version(run: dict) -> str:
    return f"run #{run['run_id']} · {MODELS[run['model_type']].label}"


def _selection(src: Any) -> F.DataSelection:
    """A data selection from a request (or a stored run), checked against the scope."""
    get = (lambda k: src.get(k)) if isinstance(src, dict) else (lambda k: getattr(src, k, None))
    groups = list(get("feature_groups") or [])
    unknown = [g for g in groups if g not in F.FEATURE_GROUPS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown feature group(s): {', '.join(unknown)}")
    scope = get("scope") or "base"
    if scope not in F.SCOPES:
        raise HTTPException(status_code=400, detail="scope must be base or system")
    not_allowed = [F.FEATURE_GROUPS[g]["label"] for g in groups if g not in F.groups_for(scope)]
    if not_allowed:
        raise HTTPException(status_code=400, detail=f"A {scope} model can't use {', '.join(not_allowed)} (raw kWh depend "
                                                    "on plant size; use energy throughput ÷ rated kWh)")
    system_id, systems = None, None
    if scope == "system":
        system_id = get("battery_system_id")
        if system_id is None:
            raise HTTPException(status_code=400, detail="Choose the battery system of a battery system model")
    else:
        systems = [int(x) for x in (get("systems") or [])] or None
        holdout = get("holdout_system_id")
        if holdout is not None:
            # the held-out plant never takes part in training
            pool = systems or [s["battery_system_id"] for s in F.systems(engine) if s["has_telemetry"]]
            systems = [x for x in pool if x != holdout]
            if not systems:
                raise HTTPException(status_code=400, detail="Holding that plant out leaves no plant to train on")
    return F.DataSelection(grain=get("grain"), date_from=F.as_date(get("date_from")), date_to=F.as_date(get("date_to")),
                           feature_groups=groups, module_rows_only=bool(get("module_rows_only")),
                           include_snapshots=bool(get("include_snapshots")), system_id=system_id, systems=systems)


def resolve_default(system_id: Optional[int] = None) -> tuple[Optional[dict], Optional[str]]:
    """The run "active" means for a battery system (None = no plant): its default, the base default, the latest base
    run - and why it was chosen."""
    if system_id is not None:
        run = registry.active_run(engine, USE_CASE, system_id)
        if run:
            return run, "default for this battery system"
    run = registry.active_run(engine, USE_CASE, None)
    if run:
        return run, "base default" + (" (no default for this battery system)" if system_id is not None else "")
    run = registry.latest_run(engine, USE_CASE, scope="base")
    if run:
        return run, "latest base run (no default set)"
    return None, None


def default_run() -> Optional[dict]:
    return resolve_default(None)[0]


def status() -> dict:
    """For /health: the model predictions use by default (the base default)."""
    run = default_run()
    return {"model_version": _run_version(run) if run else None,
            "default_is_set": bool(run and run["is_active"])}


def _resolve(model: str, system_id: Optional[int] = None) -> tuple[dict, Optional[str]]:
    """The run to predict with, and why (for "active")."""
    if model == "active":
        run, why = resolve_default(system_id)
        if not run:
            raise HTTPException(status_code=404, detail="No trained SOH model yet - train one on the SOH Model Training page")
        return run, why
    if model == "original":
        raise HTTPException(status_code=410, detail="The original daily model was retired - choose a trained run")
    if not model.isdigit():
        raise HTTPException(status_code=400, detail="model must be 'active' or a run id")
    run = registry.get_run(engine, USE_CASE, int(model))
    if not run:
        raise HTTPException(status_code=404, detail=f"Run #{model} not found")
    if run["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Run #{model} didn't complete ({run['status']})")
    return run, None


def _out_of_range(values: dict, ranges: dict) -> list[dict]:
    """Inputs outside the min-max seen in training (trees then predict as at the nearest edge)."""
    out = []
    for feature, value in values.items():
        r = ranges.get(feature) or {}
        lo, hi = r.get("min"), r.get("max")
        if value is None or lo is None or hi is None:
            continue
        if value < lo or value > hi:
            out.append({"feature": feature, "value": value, "min": lo, "max": hi})
    return out


def _system(system_id: Optional[int]) -> Optional[dict]:
    if system_id is None:
        return None
    found = _system_names().get(system_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Battery system {system_id} not found")
    return found


# ---------------------------------------------------------------- SOH Estimator


@router.get("/systems")
def systems():
    """Sites and their battery systems (with the span of their BMS telemetry), for the pickers."""
    return F.systems(engine)


@router.get("/models")
def models(system_id: Optional[int] = None):
    """Models the estimator can use: completed runs - for a battery system, the base runs and its own runs."""
    names = _system_names()
    runs = registry.list_runs(engine, USE_CASE, status="COMPLETED", limit=500, for_system=system_id)
    items = [{
        "key": str(run["run_id"]), "run_id": run["run_id"], "label": _run_version(run), "run_name": run["run_name"],
        "model_type": run["model_type"], "grain": run["grain"], "features": len(run["features"]),
        "r2": run["r2"], "rmse": run["rmse"], "mae": run["mae"],
        "trained_at": (run["finished_at"] or run["started_at"]).isoformat(), "is_active": run["is_active"],
        "scope": run["scope"], "battery_system_id": run["battery_system_id"], "scope_label": _scope_label(run, names),
        "training_mode": run["training_mode"], "parent_run_id": run["parent_run_id"],
    } for run in runs]
    chosen, why = resolve_default(system_id)
    base_default = registry.active_run(engine, USE_CASE, None)
    system_default = registry.active_run(engine, USE_CASE, system_id) if system_id is not None else None
    return {"active_key": str(base_default["run_id"]) if base_default else None,
            "system_active_key": str(system_default["run_id"]) if system_default else None,
            "default_key": str(chosen["run_id"]) if chosen else None, "default_reason": why, "models": items}


@router.get("/model-info", response_model=ModelInfo)
def model_info(model: str = "active", system_id: Optional[int] = None):
    run, why = _resolve(model, system_id)
    names = _system_names()
    plant = names.get(run["battery_system_id"]) or {} if run["battery_system_id"] else {}
    metrics = {k: run[k] for k in ("r2", "mae", "rmse", "mape_pct", "max_error", "median_ae", "explained_variance",
                                   "train_r2", "train_rmse", "train_mae") if run.get(k) is not None}
    metrics.update(n_train=run["n_train"], n_test=run["n_test"])
    scope_text = (f"battery system model for {_scope_label(run, names)}" if run["scope"] == "system"
                  else f"base model on {len(run['systems'])} battery systems" if run["systems"] else "base model on every battery system")
    if run["training_mode"] == "finetune":
        scope_text += f", fine-tuned from base run #{run['parent_run_id']}"
    return ModelInfo(
        model_version=_run_version(run), trained_at=(run["finished_at"] or run["started_at"]).isoformat(),
        target=F.TARGET, features=list(run["features"]), feature_ranges=run["feature_ranges"] or {},
        feature_importances=run["feature_importance"] or {}, metrics=metrics,
        caveat=(f"{scope_text[0].upper()}{scope_text[1:]}. Trained on {run['n_rows']} {run['grain']} rows "
                f"({run['split_method']} {int(run['test_fraction'] * 100)}% test)"
                + (", only rows with module data" if run["module_rows_only"] else "") + "."),
        run_id=run["run_id"], run_name=run["run_name"], model_type=run["model_type"], grain=run["grain"],
        feature_labels={f: F.FEATURE_LABELS.get(f, f) for f in run["features"]},
        params=run["params"], is_active=run["is_active"], warnings=run["warnings"] or [],
        data_selection={
            "grain": run["grain"], "date_from": run["date_from"].isoformat() if run["date_from"] else None,
            "date_to": run["date_to"].isoformat() if run["date_to"] else None,
            "feature_groups": list(run["feature_groups"]), "module_rows_only": run["module_rows_only"],
            "include_snapshots": run["include_snapshots"], "split": f"{run['split_method']}, {int(run['test_fraction'] * 100)}% test",
            "candidate_features": len(run["candidate_features"] or run["features"]), "used_features": len(run["features"]),
            "min_importance_pct": run["min_importance_pct"], "importance_method": run["importance_method"],
            "rows": run["n_rows"], "target_min": run["target_min"], "target_max": run["target_max"],
        },
        scope=run["scope"], site_id=run["site_id"], site_name=plant.get("site_name"),
        battery_system_id=run["battery_system_id"], system_name=plant.get("system_name"),
        training_mode=run["training_mode"], parent_run_id=run["parent_run_id"],
        systems=list(run["systems"]) if run["systems"] else None, holdout_system_id=run["holdout_system_id"],
        metrics_by_system=run["metrics_by_system"], holdout_metrics=run["holdout_metrics"], chosen_as=why,
    )


@router.post("/predict", response_model=SohEstimateResponse)
def predict(payload: dict[str, Optional[float]] = Body(...), model: str = "active", system_id: Optional[int] = None):
    run, _ = _resolve(model, system_id)
    missing = [f for f in run["features"] if f not in payload]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing feature(s): {', '.join(missing)}")
    values = {f: payload[f] for f in run["features"]}
    predicted = registry.predict(run, MODELS, values)
    return SohEstimateResponse(
        predicted_soh_pct=round(predicted, 3), model_version=_run_version(run), model_key=str(run["run_id"]),
        run_id=run["run_id"], out_of_range=_out_of_range(values, run["feature_ranges"] or {}))


@router.get("/sample", response_model=SampleReading)
def sample(model: str = "active", system_id: Optional[int] = None):
    """The latest reading as this model's inputs (its features, at its grain); of one battery system when given."""
    run, _ = _resolve(model, system_id)
    system = _system(system_id)
    sel = F.DataSelection(grain=run["grain"], feature_groups=list(run["feature_groups"]),
                          module_rows_only=run["module_rows_only"], include_snapshots=True, system_id=system_id)
    row = F.latest_row(engine, sel)
    if row is None:
        where = f" for {system['system_name']}" if system else ""
        extra = " with module data" if run["module_rows_only"] else ""
        raise HTTPException(status_code=404, detail=f"No telemetry rows{extra}{where} match this model's data selection")
    return SampleReading(day=F.fmt_ts(row["ts"]), system_name=system["system_name"] if system else None,
                         values={f: F.to_float(row[f]) for f in run["features"]},
                         actual_soh_pct=F.to_float(row[F.TARGET]))


@router.get("/average", response_model=SystemAverage)
def average(system_id: int, model: str = "active"):
    """A battery system's mean of the model's features over the model's training data (same grain, dates, feature
    groups and filters); over all the system's rows when it had none in the training data."""
    run, _ = _resolve(model, system_id)
    system = _system(system_id)
    base = dict(grain=run["grain"], feature_groups=list(run["feature_groups"]), module_rows_only=run["module_rows_only"],
                include_snapshots=run["include_snapshots"], system_id=system_id)
    scope = "training"
    df = F.build_dataset(engine, F.DataSelection(date_from=run["date_from"], date_to=run["date_to"], **base))
    if df.empty:
        scope = "history"
        df = F.build_dataset(engine, F.DataSelection(**{**base, "include_snapshots": True}))
    if df.empty:
        extra = " with module data" if run["module_rows_only"] else ""
        raise HTTPException(status_code=404, detail=f"{system['system_name']} has no telemetry rows{extra} for this model")
    return SystemAverage(
        battery_system_id=system_id, system_name=system["system_name"],
        values={f: F.to_float(df[f].mean()) for f in run["features"]}, rows=int(len(df)),
        date_from=F.fmt_ts(df["ts"].min()), date_to=F.fmt_ts(df["ts"].max()), scope=scope,
        actual_soh_pct=F.to_float(df[F.TARGET].mean()))


# ---------------------------------------------------------------- Model Training


@router.get("/train/options")
def train_options():
    """Models with their parameters, feature groups (and the scopes allowed to use them), grains, the battery systems
    with their data, and the base runs a plant model can be fine-tuned from (for the training page)."""
    return {
        "models": [{"key": k, "label": m.label, "params": m.param_specs} for k, m in MODELS.items()],
        "feature_groups": [{"key": k, "label": g["label"], "scopes": list(g.get("scopes", F.SCOPES)),
                            "features": [{"key": f, "label": F.FEATURE_LABELS.get(f, f)} for f in g["features"]]}
                           for k, g in F.FEATURE_GROUPS.items()],
        "grains": [{"key": "5min", "label": "5 minutes"}, {"key": "hour", "label": "Hourly"}, {"key": "day", "label": "Daily"}],
        "feature_selection": {
            "default_min_importance_pct": trainer.default_min_importance_pct,
            "methods": [
                {"key": "auto", "label": "Auto", "help": "Permutation for LightGBM linear trees, gain otherwise"},
                {"key": "gain", "label": "Gain", "help": "Share of the split gain in the trees"},
                {"key": "permutation", "label": "Permutation",
                 "help": "How much the training error grows when the feature is shuffled"},
            ],
        },
        "coverage": F.coverage(engine),
        "systems": F.system_coverage(engine),
        "metrics": [
            {"key": "r2", "label": "R²", "better": "higher"}, {"key": "rmse", "label": "RMSE", "better": "lower"},
            {"key": "mae", "label": "MAE", "better": "lower"}, {"key": "mape_pct", "label": "MAPE %", "better": "lower"},
            {"key": "max_error", "label": "Max error", "better": "lower"},
            {"key": "median_ae", "label": "Median AE", "better": "lower"},
            {"key": "explained_variance", "label": "Explained variance", "better": "higher"},
        ],
    }


@router.post("/train/preview")
def train_preview(selection: DataSelectionIn):
    """How many rows a data selection gives (per battery system too), and how much SOH varies in them."""
    return F.summarize(F.build_dataset(engine, _selection(selection)))


def _parent(request: TrainRequest) -> Optional[dict]:
    """The base run a battery system model is fine-tuned from (checked)."""
    if request.training_mode != "finetune":
        return None
    if request.scope != "system":
        raise HTTPException(status_code=400, detail="Only a battery system model can be fine-tuned from a base model")
    if request.parent_run_id is None:
        raise HTTPException(status_code=400, detail="Choose the base run to fine-tune")
    parent = registry.get_run(engine, USE_CASE, request.parent_run_id)
    if not parent or parent["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Base run #{request.parent_run_id} not found or not completed")
    if parent["scope"] != "base":
        raise HTTPException(status_code=400, detail=f"Run #{parent['run_id']} is not a base model")
    return parent


@router.post("/train")
def train(request: TrainRequest):
    """Train, score and store one model run (status RUNNING while it trains). A fine-tuned battery system model takes
    the base run's algorithm, grain, feature groups and features; the parameters set the rounds added on top."""
    parent = _parent(request)
    model_type = parent["model_type"] if parent else request.model_type
    if parent:
        request = request.model_copy(update={"grain": parent["grain"], "feature_groups": list(parent["feature_groups"]),
                                             "model_type": model_type})
    sel = _selection(request)
    system = _system(request.battery_system_id) if request.scope == "system" else None
    holdout = _system(request.holdout_system_id) if request.scope == "base" and request.holdout_system_id else None
    params = trainer.clean_params(model_type, request.params)
    if parent and model_type == "lightgbm":
        params["linear_tree"] = bool(parent["params"].get("linear_tree"))  # continued trees must match
    features = list(parent["features"]) if parent else sel.features
    run_id = registry.start_run(engine, USE_CASE, {
        "run_name": request.run_name, "model_type": model_type, "params": params, "grain": sel.grain,
        "date_from": sel.date_from, "date_to": sel.date_to, "feature_groups": sel.feature_groups,
        "features": features, "module_rows_only": sel.module_rows_only, "include_snapshots": sel.include_snapshots,
        "split_method": request.split_method, "test_fraction": request.test_fraction, "random_state": request.random_state,
        "min_importance_pct": 0 if parent else request.min_importance_pct,
        "scope": request.scope, "site_id": system["site_id"] if system else None,
        "battery_system_id": request.battery_system_id if system else None, "training_mode": request.training_mode,
        "parent_run_id": parent["run_id"] if parent else None,
        "holdout_system_id": request.holdout_system_id if holdout else None,
    })
    with run_guard(fail=lambda msg: registry.fail_run(engine, run_id, msg), context={"run_id": run_id}):
        df = F.build_dataset(engine, sel)
        if system and df.empty:
            raise TrainingError(f"{system['system_name']} has no rows for this data selection")
        init = registry.load_model(parent, MODELS) if parent else None
        result = trainer.train(df, features, model_type, dict(params), request.split_method, request.test_fraction,
                               request.random_state, request.min_importance_pct, request.importance_method,
                               init_model=init)
        if parent:
            result.warnings.insert(0, f"Fine-tuned from base run #{parent['run_id']}: {result.iterations} rounds added "
                                      f"on {system['system_name']}'s rows, with the base run's {len(features)} features")
        holdout_metrics = None
        if holdout:
            hsel = F.DataSelection(**{**sel.__dict__, "systems": None, "system_id": holdout["battery_system_id"]})
            hdf = F.build_dataset(engine, hsel)
            holdout_metrics = {"system_id": holdout["battery_system_id"], "system_name": holdout["system_name"],
                               "site_name": holdout["site_name"], **trainer.evaluate(result.model, hdf, result.selected)}
            if not hdf.empty and holdout_metrics.get("rmse") and result.metrics.get("rmse") \
                    and holdout_metrics["rmse"] > 3 * result.metrics["rmse"]:
                result.warnings.append(f"On the held-out plant {holdout['system_name']} the error is "
                                       f"{holdout_metrics['rmse'] / result.metrics['rmse']:.1f}x the test error: the base "
                                       "model doesn't generalise well to a plant it hasn't seen")
        artifact = registry.save_model(run_id, result.model)
        registry.complete_run(engine, run_id, result, params, artifact,
                              systems=sorted(int(x) for x in df["system_id"].unique()), holdout_metrics=holdout_metrics)
    return registry.get_run(engine, USE_CASE, run_id)


@router.get("/runs")
def runs(model_type: Optional[str] = None, status: Optional[str] = None, scope: Optional[str] = None,
         system_id: Optional[int] = None, limit: int = Query(100, ge=1, le=500)):
    """Runs newest first; scope=base|system, system_id = one battery system's runs."""
    return registry.list_runs(engine, USE_CASE, model_type, status, limit, scope=scope, battery_system_id=system_id)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    run = registry.get_run(engine, USE_CASE, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    run.pop("artifact_path", None)
    return run


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int):
    if not registry.delete_run(engine, USE_CASE, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


@router.post("/runs/{run_id}/activate")
def activate(run_id: int):
    """Make this run the default of its scope: the base default, or its battery system's default."""
    registry.set_active(engine, USE_CASE, run_id)
    return {"active_run_id": run_id, "at": datetime.now().isoformat(timespec="seconds")}


@router.post("/runs/deactivate")
def deactivate(system_id: Optional[int] = None):
    """Remove the default of a scope: a battery system's (system_id) or the base default (no system_id)."""
    registry.set_active(engine, USE_CASE, None, system_id)
    return {"active_run_id": None, "system_id": system_id}
