"""HVAC COP & cooling-performance API (mounted at /hvac-cop): options, runs (compute / list / detail / delete), interval
points, and the what-if predictor (COP, capacity and HVAC kW at given conditions - the hook for HVAC-energy forecasting)."""
from datetime import date
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import engine
from usecases.hvac_cop import model as M
from usecases.hvac_cop import monitor as Mon
from usecases.hvac_cop import store
from usecases.hvac_cop.run import RunConfig, run

USE_CASE = "hvac_cop"
PREFIX = "hvac-cop"
router = APIRouter(tags=["HVAC COP & cooling performance"])


class RunRequest(BaseModel):
    hvac_ids: list[int] = Field(min_length=1)
    date_from: date
    date_to: date
    run_name: Optional[str] = Field(default=None, max_length=120)
    cop_definition: Literal["logged", "ratio", "loop"] = "logged"
    capacity_definition: Literal["logged", "loop"] = "logged"
    lift_source: Literal["temperature", "pressure"] = "temperature"
    evap_approach_k: float = Field(default=5.0, ge=0, le=20)
    cond_approach_k: float = Field(default=10.0, ge=0, le=30)
    fluid_density_kg_l: float = Field(default=1.04, gt=0.5, le=1.5)
    fluid_cp_kj_kgk: float = Field(default=3.7, gt=1, le=5)
    min_speed_pct: float = Field(default=20.0, ge=0, le=100)
    min_power_kw: float = Field(default=1.0, ge=0, le=100)
    max_dt_step_k: float = Field(default=0.5, gt=0, le=10)
    train_frac: float = Field(default=0.7, ge=0.3, le=0.95)
    expected_model: Literal["map", "grey", "hybrid"] = "map"
    n_estimators: int = Field(default=300, ge=20, le=3000)
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    num_leaves: int = Field(default=15, ge=4, le=256)
    ref_ambient_c: float = Field(default=35.0, ge=-20, le=60)
    ref_supply_c: float = Field(default=25.0, ge=0, le=45)
    ref_plr: float = Field(default=0.75, gt=0, le=1)
    rated_capacity_kw: Optional[float] = Field(default=None, gt=0, le=100_000)
    ewma_lambda: float = Field(default=0.2, gt=0, le=1)
    ewma_l: float = Field(default=3.0, gt=0, le=10)
    cusum_k: float = Field(default=0.5, ge=0, le=5)
    cusum_h: float = Field(default=5.0, gt=0, le=50)


class PredictRequest(BaseModel):
    run_id: int
    hvac_id: int
    ambient_c: float = Field(ge=-30, le=60)
    supply_c: float = Field(ge=-10, le=45)
    plr: Optional[float] = Field(default=None, gt=0, le=1.2)
    heat_load_kw: Optional[float] = Field(default=None, ge=0)


def status() -> dict:
    runs = [r for r in store.list_runs(engine, 5) if r["status"] == "COMPLETED"]
    return {"latest_run": runs[0]["run_id"] if runs else None}


def _config(b: RunRequest) -> RunConfig:
    return RunConfig(
        hvac_ids=b.hvac_ids, date_from=b.date_from, date_to=b.date_to,
        model=M.ModelSettings(cop_definition=b.cop_definition, capacity_definition=b.capacity_definition,
                              lift_source=b.lift_source, evap_approach_k=b.evap_approach_k, cond_approach_k=b.cond_approach_k,
                              fluid_density_kg_l=b.fluid_density_kg_l, fluid_cp_kj_kgk=b.fluid_cp_kj_kgk,
                              min_speed_pct=b.min_speed_pct, min_power_kw=b.min_power_kw, max_dt_step_k=b.max_dt_step_k,
                              train_frac=b.train_frac, expected_model=b.expected_model, n_estimators=b.n_estimators,
                              learning_rate=b.learning_rate, num_leaves=b.num_leaves),
        monitor=Mon.MonitorSettings(ref_ambient_c=b.ref_ambient_c, ref_supply_c=b.ref_supply_c, ref_plr=b.ref_plr,
                                    rated_capacity_kw=b.rated_capacity_kw, ewma_lambda=b.ewma_lambda, ewma_l=b.ewma_l,
                                    cusum_k=b.cusum_k, cusum_h=b.cusum_h))


@router.get("/options")
def options():
    units = M.units(engine)
    first = min((u["first_day"] for u in units), default=date.today().isoformat())
    last = max((u["last_day"] for u in units), default=date.today().isoformat())
    defaults = RunRequest(hvac_ids=[u["hvac_id"] for u in units] or [0], date_from=first, date_to=last)
    return {"units": units, "defaults": defaults.model_dump(mode="json"),
            "cop_definitions": [
                {"key": "logged", "label": "Logged cop (the unit's own reading)"},
                {"key": "ratio", "label": "cooling_capacity_kw ÷ hvac_power_kw"},
                {"key": "loop", "label": "Coolant loop: flow × ρ·cp × ΔT ÷ hvac_power_kw"}],
            "capacity_definitions": [
                {"key": "logged", "label": "cooling_capacity_kw (logged)"},
                {"key": "loop", "label": "Coolant loop: flow × ρ·cp × ΔT"}]}


@router.post("/runs")
def create_run(body: RunRequest):
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    run_id = store.start_run(engine, {"name": body.run_name, "ids": body.hvac_ids, "date_from": body.date_from,
                                      "date_to": body.date_to, "params": body.model_dump(mode="json")})
    try:
        result = run(engine, _config(body))
        store.complete_run(engine, run_id, result)
    except M.HvacCopError as exc:
        store.fail_run(engine, run_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": run_id})
    except Exception as exc:  # noqa: BLE001
        store.fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Run failed: {exc}", "run_id": run_id})
    return store.get_run(engine, run_id)


@router.get("/runs")
def runs(limit: int = Query(100, ge=1, le=500)):
    return store.list_runs(engine, limit)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    r = store.get_run(engine, run_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return r


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


@router.get("/runs/{run_id}/points")
def run_points(run_id: int, hvac_id: int, day_from: date, day_to: Optional[date] = None):
    r = store.get_run(engine, run_id)
    if not r or hvac_id not in (r["hvac_ids"] or []):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} doesn't cover HVAC unit {hvac_id}")
    return store.points(engine, run_id, hvac_id, day_from, day_to or day_from)


@router.post("/predict")
def predict(body: PredictRequest):
    """COP (map, grey-box), capacity and HVAC kW at the given ambient / coolant supply and part load - or, with a heat load,
    the part load that delivers it and the HVAC kW it costs (the heat-load -> HVAC-energy hook)."""
    r = store.get_run(engine, body.run_id)
    if not r or r["status"] != "COMPLETED" or str(body.hvac_id) not in (r["models"] or {}):
        raise HTTPException(status_code=404, detail="Pick a completed run and one of its HVAC units")
    m = r["models"][str(body.hvac_id)]
    p = r["params"]
    if p.get("lift_source") == "pressure":
        raise HTTPException(status_code=400, detail="The what-if uses temperatures; this run's lift came from the pressures")
    te, tc = body.supply_c - p["evap_approach_k"], body.ambient_c + p["cond_approach_k"]
    cap_full = float(M.eval_map(m["cap_map"], te, tc, 1.0)[0])
    plr_lo = float(m["ranges"]["plr"][0])
    if body.heat_load_kw is not None:
        needed = body.heat_load_kw / cap_full if cap_full > 0 else 1.0
    else:
        needed = body.plr if body.plr is not None else 0.75
    # below the lowest compressor speed seen in training the unit cycles on / off at its minimum speed
    cycling = bool(needed < plr_lo)
    plr = float(np.clip(needed, plr_lo, 1.0))
    cop = float(M.eval_map(m["cop_map"], te, tc, plr)[0])
    lift = tc - te
    carnot = (te + 273.15) / lift if lift > 1 else None
    grey = float(M.eval_grey(m["grey"], plr, lift, carnot)[0]) if carnot else None
    cap = float(M.eval_map(m["cap_map"], te, tc, plr)[0])
    q = body.heat_load_kw if body.heat_load_kw is not None else cap
    lo, hi = m["ranges"]["ambient_temp_c"]
    return {"plr": plr, "cop_map": cop, "cop_grey": grey, "cop_carnot": carnot, "eta_2nd_law": cop / carnot if carnot else None,
            "lift_k": lift, "capacity_kw": cap, "capacity_full_kw": cap_full, "cooling_kw": q,
            "hvac_kw": q / cop if cop > 0 else None, "kw_per_ton": (q / cop) / (q / 3.517) if cop > 0 and q > 0 else None,
            "heat_load_exceeds_capacity": bool(body.heat_load_kw is not None and body.heat_load_kw > cap_full),
            "plr_needed": needed, "cycling": cycling, "min_plr": plr_lo,
            "out_of_range": not (lo - 2 <= body.ambient_c <= hi + 2)}
