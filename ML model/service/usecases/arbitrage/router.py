"""Energy-arbitrage / dispatch optimization API (mounted at /arbitrage): options, studies (run / list / detail /
delete) and the Dispatch Viewer's day view."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import engine
from usecases.arbitrage import data as D
from usecases.arbitrage import store
from usecases.arbitrage import view as V
from usecases.arbitrage.backtest import StudyConfig, run_study
from usecases.arbitrage.optimizer import Settings

USE_CASE = "arbitrage"
PREFIX = "arbitrage"
router = APIRouter(tags=["Energy arbitrage / dispatch optimization"])


class StudyRequest(BaseModel):
    system_id: int
    date_from: date
    date_to: date
    mode: Literal["deterministic", "stochastic"] = "deterministic"
    efficiency: Literal["scalar", "curve"] = "scalar"
    degradation: Literal["scalar", "curve"] = "scalar"
    as_stacking: bool = True
    as_max_mw: Optional[float] = Field(default=None, ge=0, le=100)
    terminal: Literal["next_open", "start", "value", "free"] = "next_open"
    terminal_soc: float = Field(default=50.0, ge=0, le=100)
    resolve_every_h: int = Field(default=4, ge=1, le=24)
    cvar_lambda: float = Field(default=0.0, ge=0, le=1)
    cvar_alpha: float = Field(default=0.9, ge=0.5, le=0.99)
    time_limit: float = Field(default=30.0, ge=1, le=300)
    study_name: Optional[str] = Field(default=None, max_length=120)


def status() -> dict:
    studies = [s for s in store.list_studies(engine, 1) if s["status"] == "COMPLETED"]
    return {"model": studies[0]["study_id"] if studies else None}


@router.get("/options")
def options():
    systems = D.systems(engine)
    return {
        "systems": systems,
        "modes": [{"key": "deterministic", "label": "Deterministic MILP on the P50 forecast"},
                  {"key": "stochastic", "label": "Stochastic two-stage MILP over the price scenarios (rolling)"}],
        "defaults": StudyRequest(system_id=systems[0]["system_id"] if systems else 0,
                                 date_from=systems[0]["first_day"] if systems else date.today(),
                                 date_to=systems[0]["last_day"] if systems else date.today()).model_dump(),
        "solver": "HiGHS (scipy.optimize.milp)",
    }


@router.post("/studies")
def create_study(body: StudyRequest):
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    try:
        node_id, _ = D.node_of(engine, body.system_id)
    except D.ArbitrageDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    settings = Settings(efficiency=body.efficiency, degradation=body.degradation, as_stacking=body.as_stacking,
                        terminal=body.terminal, terminal_soc=body.terminal_soc, cvar_lambda=body.cvar_lambda,
                        cvar_alpha=body.cvar_alpha, time_limit=body.time_limit, as_max_mw=body.as_max_mw)
    study_id = store.start_study(engine, {
        "name": body.study_name, "system_id": body.system_id, "node_id": node_id, "date_from": body.date_from,
        "date_to": body.date_to, "mode": body.mode, "params": body.model_dump(mode="json")})
    cfg = StudyConfig(body.system_id, body.date_from, body.date_to, body.mode, settings, body.resolve_every_h,
                      body.study_name)
    try:
        result = run_study(engine, cfg)
        as_on = body.as_stacking and result["metrics"].get("as_usd", 0) > 0
        store.complete_study(engine, study_id, body.system_id, body.mode, as_on, result)
    except D.ArbitrageDataError as exc:
        store.fail_study(engine, study_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "study_id": study_id})
    except Exception as exc:  # noqa: BLE001 - keep a record of unexpected failures
        store.fail_study(engine, study_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Study failed: {exc}", "study_id": study_id})
    return store.get_study(engine, study_id)


@router.get("/studies")
def studies(limit: int = Query(100, ge=1, le=500)):
    return store.list_studies(engine, limit)


@router.get("/studies/{study_id}")
def study(study_id: int):
    s = store.get_study(engine, study_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Study #{study_id} not found")
    return s


@router.delete("/studies/{study_id}", status_code=204)
def delete_study(study_id: int):
    if not store.delete_study(engine, study_id):
        raise HTTPException(status_code=404, detail=f"Study #{study_id} not found")


@router.get("/days")
def days(source: Literal["pack", "study"] = "pack", system_id: Optional[int] = None, study_id: Optional[int] = None):
    """Days the viewer can show for a source, with their net P&L (the pack's realized / the study's backtest)."""
    if source == "study":
        s = store.get_study(engine, study_id) if study_id else None
        if not s:
            raise HTTPException(status_code=404, detail="Pick a study")
        system_id = s["system_id"]
    if system_id is None:
        systems = D.systems(engine)
        if not systems:
            raise HTTPException(status_code=400, detail="No battery system has optimizer parameters")
        system_id = systems[0]["system_id"]
    return {"system_id": system_id, "days": V.days(engine, source, system_id, study_id)}


@router.get("/day")
def day(day: date, source: Literal["pack", "study"] = "pack", system_id: Optional[int] = None,
        study_id: Optional[int] = None):
    """Everything the Dispatch Viewer shows for one day of one source."""
    if source == "study":
        s = store.get_study(engine, study_id) if study_id else None
        if not s:
            raise HTTPException(status_code=404, detail="Pick a study")
        system_id = s["system_id"]
    if system_id is None:
        system_id = D.systems(engine)[0]["system_id"]
    try:
        return V.day_view(engine, source, day, system_id, study_id)
    except (V.ViewError, D.ArbitrageDataError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
