"""Dispatch schedule (battery_master.dispatch_schedule): the optimizer's setpoint per interval (+ discharge / - charge),
SOC target, mode, market and the price it assumed. Keyed by (run_id, interval_start); every interval must lie in its
run's horizon on the run's resolution grid. Each row shows the realized outcome over the same interval."""
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.battery_system import BatterySystem
from app.models.arbitrage import DispatchOutcome, DispatchSchedule, OptimizationRun
from app.routers.arb_common import bulk_result, commit_or_409, fmt, in_days, local, resolvers
from app.schemas.arbitrage import (
    BulkResult,
    DispatchScheduleCreate,
    DispatchScheduleOut,
    DispatchScheduleUpdate,
    Page,
    Stat,
)
from app.services.arbitrage_import import Col, num, parse_upload, ts_span, upsert, validate_rows

router = APIRouter(prefix="/api/dispatch-schedules", tags=["dispatch"])

DSch, Run, Out = DispatchSchedule, OptimizationRun, DispatchOutcome
VALUES = ("p_setpoint_kw", "soc_target_pct", "mode", "market", "forecast_price_mwh")
COLS = [
    Col("run_id", ("run_id",), "int", True),
    Col("interval_start", ("interval_start", "ts"), "ts", True),
    Col("p_setpoint_kw", ("p_setpoint_kw", "p_setpoint"), "num", True),
    Col("soc_target_pct", ("soc_target_pct", "soc_target")),
    Col("mode", ("mode",), "text"),
    Col("market", ("market",), "text"),
    Col("forecast_price_mwh", ("forecast_price_mwh", "fprice")),
]


def _realized(db: Session):
    """Mean actual kW and net P&L of the outcome intervals inside each schedule interval of the same run."""
    end = DSch.interval_start + func.make_interval(0, 0, 0, 0, 0, Run.resolution_min)
    return (db.query(DSch.run_id.label("run_id"), DSch.interval_start.label("interval_start"),
                     func.avg(Out.p_actual_kw).label("actual"), func.sum(Out.net_pnl_usd).label("net"))
            .join(Run, Run.run_id == DSch.run_id)
            .join(Out, and_(Out.run_id == DSch.run_id, Out.interval_start >= DSch.interval_start,
                            Out.interval_start < end))
            .group_by(DSch.run_id, DSch.interval_start).subquery())


def _base(db: Session):
    real = _realized(db)
    return (db.query(DSch, BatterySystem.system_name, Run.resolution_min, real.c.actual, real.c.net)
            .join(Run, Run.run_id == DSch.run_id).join(BatterySystem, BatterySystem.battery_system_id == Run.system_id)
            .outerjoin(real, and_(real.c.run_id == DSch.run_id, real.c.interval_start == DSch.interval_start)))


def _out(s: DSch, code, resolution, actual, net) -> DispatchScheduleOut:
    return DispatchScheduleOut(run_id=s.run_id, system_code=code, interval_start=s.interval_start,
                               resolution_min=resolution, actual_kw=num(actual, 1), net_pnl_usd=num(net, 4),
                               **{f: num(getattr(s, f)) if f not in ("mode", "market") else getattr(s, f)
                                  for f in VALUES})


def _get(db: Session, run_id: int, interval_start: datetime):
    found = _base(db).filter(DSch.run_id == run_id, DSch.interval_start == local(interval_start)).first()
    if not found:
        raise HTTPException(status_code=404,
                            detail=f"Run {run_id} has no schedule row at {interval_start.isoformat()}")
    return found


def _fits(run: Run, start: datetime) -> Optional[str]:
    if not (run.horizon_start <= start < run.horizon_end):
        return (f"interval_start {start:%Y-%m-%d %H:%M} is outside run {run.run_id}'s horizon "
                f"({run.horizon_start:%Y-%m-%d %H:%M} → {run.horizon_end:%Y-%m-%d %H:%M})")
    if int((start - run.horizon_start).total_seconds()) % (run.resolution_min * 60):
        return f"interval_start {start:%H:%M} is not on run {run.run_id}'s {run.resolution_min}-minute grid"
    return None


@router.get("", response_model=Page[DispatchScheduleOut])
def list_schedule(run_id: Optional[int] = None, system_id: Optional[int] = None, mode: Optional[str] = None,
                  market: Optional[str] = None, start: Optional[date] = None, end: Optional[date] = None,
                  order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                  page_size: int = Query(48, ge=1, le=5000), db: Session = Depends(get_db)):
    """Schedule rows in a plant-time date range, with energy and mode statistics over the whole filtered range."""
    q = _base(db)
    if run_id is not None:
        q = q.filter(DSch.run_id == run_id)
    if system_id is not None:
        q = q.filter(Run.system_id == system_id)
    if mode:
        q = q.filter(DSch.mode == mode)
    if market:
        q = q.filter(DSch.market == market)
    q = in_days(q, DSch.interval_start, start, end)
    mwh = DSch.p_setpoint_kw * Run.resolution_min / 60.0 / 1000.0
    agg = q.with_entities(func.count(), func.count(func.distinct(DSch.run_id)),
                          func.sum(func.greatest(mwh, 0)), func.sum(func.least(mwh, 0)),
                          func.avg(DSch.forecast_price_mwh), func.max(DSch.p_setpoint_kw),
                          func.min(DSch.p_setpoint_kw)).one()
    top_mode = (q.with_entities(DSch.mode, func.count()).group_by(DSch.mode)
                .order_by(func.count().desc()).first())
    stats = [Stat(label=f"Intervals · {agg[1]} run(s)", value=str(agg[0])),
             Stat(label="Scheduled discharge", value=fmt(agg[2], 2, "MWh")),
             Stat(label="Scheduled charge", value=fmt(-agg[3] if agg[3] is not None else None, 2, "MWh")),
             Stat(label="Setpoint range", value=f"{fmt(agg[6], 0)} … {fmt(agg[5], 0)} kW" if agg[5] is not None else None),
             Stat(label="Avg assumed price", value=fmt(agg[4], 2, "USD/MWh")),
             Stat(label="Most common mode", value=f"{top_mode[0]} ({top_mode[1]})" if top_mode else None)]
    col = DSch.interval_start.asc() if order == "asc" else DSch.interval_start.desc()
    rows = q.order_by(col, DSch.run_id).offset((page - 1) * page_size).limit(page_size).all()
    return Page[DispatchScheduleOut](items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size,
                                     stats=stats)


@router.get("/{run_id}/{interval_start}", response_model=DispatchScheduleOut)
def get_row(run_id: int, interval_start: datetime, db: Session = Depends(get_db)):
    return _out(*_get(db, run_id, interval_start))


@router.post("", response_model=DispatchScheduleOut, status_code=201)
def add_row(payload: DispatchScheduleCreate, db: Session = Depends(get_db)):
    run = db.get(Run, payload.run_id)
    if not run:
        raise HTTPException(status_code=422, detail=f"Run {payload.run_id} does not exist")
    start = local(payload.interval_start)
    problem = _fits(run, start)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if db.get(DSch, (payload.run_id, start)):
        raise HTTPException(status_code=409, detail=f"Run {payload.run_id} already has a row at {start.isoformat()}")
    db.add(DSch(**{**payload.model_dump(), "interval_start": start}))
    commit_or_409(db)
    return _out(*_get(db, payload.run_id, start))


@router.put("/{run_id}/{interval_start}", response_model=DispatchScheduleOut)
def update_row(run_id: int, interval_start: datetime, payload: DispatchScheduleUpdate, db: Session = Depends(get_db)):
    row = _get(db, run_id, interval_start)[0]
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    commit_or_409(db)
    return _out(*_get(db, run_id, interval_start))


@router.delete("/{run_id}/{interval_start}", status_code=204)
def delete_row(run_id: int, interval_start: datetime, db: Session = Depends(get_db)):
    db.delete(_get(db, run_id, interval_start)[0])
    db.commit()
    return None


@router.post("/bulk", response_model=BulkResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load dispatch_schedule.csv / .xlsx; existing (run_id, interval_start) rows are updated. Every run must already be
    loaded, and every interval must lie in its run's horizon on the run's resolution grid."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    records, errors, total, ignored = parse_upload(file.filename or "upload", content, COLS, resolvers(db))
    runs = {r.run_id: r for r in db.query(Run)}

    def check(m: DispatchScheduleCreate):
        run = runs.get(m.run_id)
        if run is None:
            return f"run_id: run {m.run_id} does not exist - load optimization_run first"
        return _fits(run, local(m.interval_start))

    valid = validate_rows(records, DispatchScheduleCreate, errors, check,
                          key=lambda m: (m.run_id, local(m.interval_start)))
    for r in valid:
        r["interval_start"] = local(r["interval_start"])
    inserted, updated = upsert(db, DSch.__table__, valid, ["run_id", "interval_start"], list(VALUES))
    db.commit()
    warnings = []
    short = [rid for rid in {r["run_id"] for r in valid}
             if (n := db.query(func.count()).filter(DSch.run_id == rid).scalar())
             < (runs[rid].horizon_end - runs[rid].horizon_start) / timedelta(minutes=runs[rid].resolution_min)]
    if short:
        warnings.append(f"{len(short)} run(s) do not yet cover their whole horizon: "
                        f"{', '.join(map(str, sorted(short)[:10]))}{' …' if len(short) > 10 else ''}")
    return bulk_result(file.filename or "upload", total, valid, inserted, updated, errors, ignored, warnings,
                       ts_span(valid, "interval_start"))
