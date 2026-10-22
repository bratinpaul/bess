"""Dispatch outcome (battery_master.dispatch_outcome): realized per-interval result - scheduled vs actual power,
settlement price, delivered energy, gross revenue net of degradation and grid cost. Keyed by (system_id,
interval_start). gross = price x energy and net = gross - degradation - grid are derived when empty and refused when
they contradict; a run_id must exist and the interval must lie in that run's horizon."""
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.battery_system import BatterySystem
from app.models.arbitrage import DispatchOutcome, OptimizationRun
from app.routers.arb_common import bulk_result, commit_or_409, fmt, in_days, local, resolvers, system_code
from app.schemas.arbitrage import (
    BulkResult,
    DispatchOutcomeCreate,
    DispatchOutcomeOut,
    DispatchOutcomeUpdate,
    Page,
    Stat,
)
from app.services.arbitrage_import import ArbitrageImportError, Col, num, parse_upload, ts_span, upsert, validate_rows

router = APIRouter(prefix="/api/dispatch-outcomes", tags=["dispatch"])

DO, Run = DispatchOutcome, OptimizationRun
VALUES = ("run_id", "p_scheduled_kw", "p_actual_kw", "price_mwh", "energy_mwh", "gross_revenue_usd",
          "degradation_cost_usd", "grid_cost_usd", "net_pnl_usd")
COLS = [
    Col("system_id", ("system_code", "system"), "code", True, "system"),
    Col("interval_start", ("interval_start", "ts"), "ts", True),
    Col("run_id", ("run_id",), "int"),
    Col("p_scheduled_kw", ("p_scheduled_kw", "p_sched")),
    Col("p_actual_kw", ("p_actual_kw", "p_act")),
    Col("price_mwh", ("price_mwh", "price")),
    Col("energy_mwh", ("energy_mwh", "energy")),
    Col("gross_revenue_usd", ("gross_revenue_usd", "gross")),
    Col("degradation_cost_usd", ("degradation_cost_usd", "degr")),
    Col("grid_cost_usd", ("grid_cost_usd", "grid")),
    Col("net_pnl_usd", ("net_pnl_usd", "net")),
]


def _base(db: Session):
    return db.query(DO, BatterySystem.system_name).join(BatterySystem, BatterySystem.battery_system_id == DO.system_id)


def _out(o: DO, code) -> DispatchOutcomeOut:
    vals = {f: (getattr(o, f) if f == "run_id" else num(getattr(o, f))) for f in VALUES}
    dev = (vals["p_actual_kw"] - vals["p_scheduled_kw"]
           if vals["p_actual_kw"] is not None and vals["p_scheduled_kw"] is not None else None)
    # skip the derive / consistency validator: stored rows are shown as they are
    return DispatchOutcomeOut.model_construct(system_id=o.system_id, system_code=code, interval_start=o.interval_start,
                                              deviation_kw=round(dev, 2) if dev is not None else None, **vals)


def _get(db: Session, system_id: int, interval_start: datetime):
    found = _base(db).filter(DO.system_id == system_id, DO.interval_start == local(interval_start)).first()
    if not found:
        raise HTTPException(status_code=404,
                            detail=f"System {system_id} has no outcome at {interval_start.isoformat()}")
    return found


def _run_fits(run: Optional[Run], run_id: Optional[int], start: datetime) -> Optional[str]:
    if run_id is None:
        return None
    if run is None:
        return f"run_id: run {run_id} does not exist - load optimization_run first"
    if not (run.horizon_start <= start < run.horizon_end):
        return f"interval_start {start:%Y-%m-%d %H:%M} is outside run {run_id}'s horizon"
    return None


@router.get("", response_model=Page[DispatchOutcomeOut])
def list_outcomes(system_id: Optional[int] = None, run_id: Optional[int] = None, start: Optional[date] = None,
                  end: Optional[date] = None, order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                  page_size: int = Query(96, ge=1, le=5000), db: Session = Depends(get_db)):
    """Outcome intervals in a plant-time date range, with energy and P&L totals over the whole filtered range."""
    q = _base(db)
    if system_id is not None:
        q = q.filter(DO.system_id == system_id)
    if run_id is not None:
        q = q.filter(DO.run_id == run_id)
    q = in_days(q, DO.interval_start, start, end)
    agg = q.with_entities(
        func.count(), func.sum(func.greatest(DO.energy_mwh, 0)), func.sum(func.least(DO.energy_mwh, 0)),
        func.sum(DO.gross_revenue_usd), func.sum(DO.degradation_cost_usd), func.sum(DO.grid_cost_usd),
        func.sum(DO.net_pnl_usd), func.avg(func.abs(DO.p_actual_kw - DO.p_scheduled_kw)),
        func.count().filter(DO.run_id.is_(None))).one()
    stats = [Stat(label="Intervals", value=str(agg[0])),
             Stat(label="Discharged", value=fmt(agg[1], 2, "MWh")),
             Stat(label="Charged", value=fmt(-agg[2] if agg[2] is not None else None, 2, "MWh")),
             Stat(label="Gross revenue", value=fmt(agg[3], 2, "USD")),
             Stat(label="Degradation cost", value=fmt(agg[4], 2, "USD")),
             Stat(label="Grid cost", value=fmt(agg[5], 2, "USD")),
             Stat(label="Net P&L", value=fmt(agg[6], 2, "USD", sign=True), warn=agg[6] is not None and agg[6] < 0),
             Stat(label="Tracking error (mean |actual − scheduled|)", value=fmt(agg[7], 1, "kW")),
             Stat(label="Without a run", value=str(agg[8]), warn=agg[8] > 0)]
    col = DO.interval_start.asc() if order == "asc" else DO.interval_start.desc()
    rows = q.order_by(col, BatterySystem.system_name).offset((page - 1) * page_size).limit(page_size).all()
    return Page[DispatchOutcomeOut](items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size,
                                    stats=stats)


@router.get("/{system_id}/{interval_start}", response_model=DispatchOutcomeOut)
def get_outcome(system_id: int, interval_start: datetime, db: Session = Depends(get_db)):
    return _out(*_get(db, system_id, interval_start))


@router.post("", response_model=DispatchOutcomeOut, status_code=201)
def add_outcome(payload: DispatchOutcomeCreate, db: Session = Depends(get_db)):
    system_code(db, payload.system_id)
    start = local(payload.interval_start)
    problem = _run_fits(db.get(Run, payload.run_id) if payload.run_id else None, payload.run_id, start)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if db.get(DO, (payload.system_id, start)):
        raise HTTPException(status_code=409, detail=f"System {payload.system_id} already has an outcome at "
                                                    f"{start.isoformat()}")
    db.add(DO(**{**payload.model_dump(), "interval_start": start}))
    commit_or_409(db)
    return _out(*_get(db, payload.system_id, start))


@router.put("/{system_id}/{interval_start}", response_model=DispatchOutcomeOut)
def update_outcome(system_id: int, interval_start: datetime, payload: DispatchOutcomeUpdate,
                   db: Session = Depends(get_db)):
    row = _get(db, system_id, interval_start)[0]
    problem = _run_fits(db.get(Run, payload.run_id) if payload.run_id else None, payload.run_id, row.interval_start)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    commit_or_409(db)
    return _out(*_get(db, system_id, interval_start))


@router.delete("/{system_id}/{interval_start}", status_code=204)
def delete_outcome(system_id: int, interval_start: datetime, db: Session = Depends(get_db)):
    db.delete(_get(db, system_id, interval_start)[0])
    db.commit()
    return None


@router.post("/bulk", response_model=BulkResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load dispatch_outcome.csv / .xlsx; existing (system, interval_start) rows are updated."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        records, errors, total, ignored = parse_upload(file.filename or "upload", content, COLS, resolvers(db))
    except ArbitrageImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    runs = {r.run_id: r for r in db.query(Run)}
    valid = validate_rows(records, DispatchOutcomeCreate, errors,
                          lambda m: _run_fits(runs.get(m.run_id), m.run_id, local(m.interval_start)),
                          key=lambda m: (m.system_id, local(m.interval_start)))
    for r in valid:
        r["interval_start"] = local(r["interval_start"])
    inserted, updated = upsert(db, DO.__table__, valid, ["system_id", "interval_start"], list(VALUES))
    db.commit()
    return bulk_result(file.filename or "upload", total, valid, inserted, updated, errors, ignored,
                       span=ts_span(valid, "interval_start"))
