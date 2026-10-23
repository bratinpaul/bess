"""Loss decomposition / performance benchmarking API (mounted at /loss): options, runs (compute / list / detail /
delete), and the viewer's reads (daily scorecard, interval ledger)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from bess_common.errors import run_guard
from core.db import engine
from usecases.loss import data as D
from usecases.loss import store
from usecases.loss.benchmark import BenchmarkSettings
from usecases.loss.ledger import LedgerSettings
from usecases.loss.run import RunConfig, run
from usecases.loss.scorecard import STAGE_LABELS, ScoreSettings

USE_CASE = "loss"
PREFIX = "loss"
router = APIRouter(tags=["Loss decomposition / performance benchmarking"])


class RunRequest(BaseModel):
    system_ids: list[int] = Field(min_length=1)
    date_from: date
    date_to: date
    run_name: Optional[str] = Field(default=None, max_length=120)
    # ledger
    idle_frac: float = Field(default=0.01, ge=0, le=0.2)
    transformer_mode: Literal["metered", "model"] = "metered"
    xfmr_kva: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    xfmr_core_pct: float = Field(default=0.2, ge=0, le=5)
    xfmr_cu_pct: float = Field(default=1.0, ge=0, le=5)
    standby_min_rest_h: float = Field(default=1.0, ge=0.25, le=48)
    standby_max_drop_pct_h: float = Field(default=0.5, ge=0.01, le=10)
    # benchmark
    baseline_days: int = Field(default=7, ge=0, le=365)
    resistance_growth_pct_per_soh: float = Field(default=3.3, ge=0, le=20)
    self_discharge_pct_day: Optional[float] = Field(default=None, ge=0, le=5)
    ref_load_frac: float = Field(default=0.5, gt=0, le=1.2)
    ref_temp_c: float = Field(default=25.0, ge=-20, le=60)
    ref_ambient_c: float = Field(default=30.0, ge=-20, le=60)
    # scorecard
    guarantee_rte_pct: Optional[float] = Field(default=None, gt=0, le=100)
    guarantee_basis: Literal["dc", "ac", "poi_excl_aux", "plant"] = "poi_excl_aux"
    min_cycle_frac: float = Field(default=0.05, ge=0, le=1)
    ewma_lambda: float = Field(default=0.2, gt=0, le=1)
    ewma_l: float = Field(default=3.0, gt=0, le=10)
    cusum_k: float = Field(default=0.5, ge=0, le=5)
    cusum_h: float = Field(default=5.0, gt=0, le=50)


def status() -> dict:
    runs = [r for r in store.list_runs(engine, 5) if r["status"] == "COMPLETED"]
    return {"latest_run": runs[0]["run_id"] if runs else None}


def _config(body: RunRequest) -> RunConfig:
    return RunConfig(
        system_ids=body.system_ids, date_from=body.date_from, date_to=body.date_to,
        ledger=LedgerSettings(idle_frac=body.idle_frac, transformer_mode=body.transformer_mode, xfmr_kva=body.xfmr_kva,
                              xfmr_core_pct=body.xfmr_core_pct, xfmr_cu_pct=body.xfmr_cu_pct,
                              standby_min_rest_h=body.standby_min_rest_h,
                              standby_max_drop_pct_h=body.standby_max_drop_pct_h),
        bench=BenchmarkSettings(baseline_days=body.baseline_days,
                                resistance_growth_pct_per_soh=body.resistance_growth_pct_per_soh,
                                self_discharge_pct_day=body.self_discharge_pct_day, ref_load_frac=body.ref_load_frac,
                                ref_temp_c=body.ref_temp_c, ref_ambient_c=body.ref_ambient_c),
        score=ScoreSettings(guarantee_rte_pct=body.guarantee_rte_pct, guarantee_basis=body.guarantee_basis,
                            min_cycle_frac=body.min_cycle_frac, ewma_lambda=body.ewma_lambda, ewma_l=body.ewma_l,
                            cusum_k=body.cusum_k, cusum_h=body.cusum_h))


@router.get("/options")
def options():
    systems = D.systems(engine)
    first = min((s["first_day"] for s in systems), default=date.today().isoformat())
    last = max((s["last_day"] for s in systems), default=date.today().isoformat())
    defaults = RunRequest(system_ids=[s["system_id"] for s in systems] or [0], date_from=first, date_to=last)
    return {
        "systems": systems,
        "defaults": defaults.model_dump(mode="json"),
        "stages": [{"key": k, "label": v} for k, v in STAGE_LABELS.items()],
        "guarantee_bases": [
            {"key": "poi_excl_aux", "label": "POI, auxiliaries excluded"},
            {"key": "ac", "label": "PCS AC terminals"},
            {"key": "plant", "label": "Plant (POI incl. auxiliaries)"},
            {"key": "dc", "label": "Battery DC terminals"},
        ],
    }


@router.post("/runs")
def create_run(body: RunRequest):
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    known = {s["system_id"] for s in D.systems(engine)}
    unknown = [s for s in body.system_ids if s not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"No BMS / PCS / EMS telemetry for battery system(s) {unknown}")
    run_id = store.start_run(engine, {"name": body.run_name, "systems": body.system_ids, "date_from": body.date_from,
                                      "date_to": body.date_to, "params": body.model_dump(mode="json")})
    with run_guard(fail=lambda msg: store.fail_run(engine, run_id, msg), context={"run_id": run_id}):
        result = run(engine, _config(body))
        steps = {r.system_id: r.summary["audit"]["step_min"] / 60 for r in result["results"]}
        store.complete_run(engine, run_id, result, steps)
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


def _check(run_id: int, system_id: int) -> dict:
    r = store.get_run(engine, run_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    if system_id not in (r["system_ids"] or []):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} doesn't cover battery system {system_id}")
    return r


@router.get("/runs/{run_id}/days")
def run_days(run_id: int, system_id: int):
    """The daily benchmark scorecard of one battery system."""
    _check(run_id, system_id)
    return store.days(engine, run_id, system_id)


@router.get("/runs/{run_id}/ledger")
def run_ledger(run_id: int, system_id: int, day_from: date, day_to: Optional[date] = None):
    """The interval ledger of one battery system for a day range (at most ~10 days of 5-min rows)."""
    _check(run_id, system_id)
    return store.ledger(engine, run_id, system_id, day_from, day_to or day_from)
