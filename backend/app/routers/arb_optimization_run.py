"""Optimizer runs (battery_master.optimization_run): one row per run with horizon, method, objective, solver status
and expected profit; listed with how much schedule, state and realized outcome hangs off each run.
Deleting a run deletes its decision_state and dispatch_schedule rows and unlinks its dispatch_outcome rows."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.battery_system import BatterySystem
from app.models.arbitrage import DecisionState, DispatchOutcome, DispatchSchedule, OptimizationRun
from app.routers.arb_common import (
    bulk_result,
    commit_or_409,
    fmt,
    in_days,
    local,
    resolvers,
    sync_run_sequence,
    system_code,
)
from app.schemas.arbitrage import (
    BulkResult,
    OptimizationRunCreate,
    OptimizationRunOut,
    OptimizationRunUpdate,
    Page,
    Stat,
)
from app.services.arbitrage_import import Col, num, parse_upload, ts_span, upsert, validate_rows

router = APIRouter(prefix="/api/optimization-runs", tags=["dispatch"])

Run = OptimizationRun
TIMES = ("issued_at", "horizon_start", "horizon_end")
VALUES = ("issued_at", "horizon_start", "horizon_end", "resolution_min", "method", "objective", "solver_status",
          "expected_profit_usd", "solve_seconds")
COLS = [
    Col("run_id", ("run_id",), "int"),
    Col("system_id", ("system_code", "system"), "code", True, "system"),
    Col("issued_at", ("issued_at",), "ts", True),
    Col("horizon_start", ("horizon_start",), "ts", True),
    Col("horizon_end", ("horizon_end",), "ts", True),
    Col("resolution_min", ("resolution_min", "resolution"), "int"),
    Col("method", ("method",), "text"),
    Col("objective", ("objective",), "text"),
    Col("solver_status", ("solver_status", "status"), "text"),
    Col("expected_profit_usd", ("expected_profit_usd", "expected_profit", "exp"), "num"),
    Col("solve_seconds", ("solve_seconds", "secs"), "num"),
]


def _rollups(db: Session):
    sched = (db.query(DispatchSchedule.run_id.label("run_id"), func.count().label("n"))
             .group_by(DispatchSchedule.run_id).subquery())
    outc = (db.query(DispatchOutcome.run_id.label("run_id"), func.count().label("n"),
                     func.sum(DispatchOutcome.net_pnl_usd).label("net"))
            .group_by(DispatchOutcome.run_id).subquery())
    return sched, outc


def _base(db: Session):
    sched, outc = _rollups(db)
    return (db.query(Run, BatterySystem.system_name, sched.c.n, DecisionState.run_id, outc.c.n, outc.c.net)
            .join(BatterySystem, BatterySystem.battery_system_id == Run.system_id)
            .outerjoin(sched, sched.c.run_id == Run.run_id)
            .outerjoin(DecisionState, DecisionState.run_id == Run.run_id)
            .outerjoin(outc, outc.c.run_id == Run.run_id))


def _out(r: Run, code, n_sched, state_id, n_out, net) -> OptimizationRunOut:
    return OptimizationRunOut(
        run_id=r.run_id, system_id=r.system_id, system_code=code, issued_at=r.issued_at,
        horizon_start=r.horizon_start, horizon_end=r.horizon_end, resolution_min=r.resolution_min, method=r.method,
        objective=r.objective, solver_status=r.solver_status, expected_profit_usd=num(r.expected_profit_usd),
        solve_seconds=num(r.solve_seconds), schedule_rows=n_sched or 0, has_state=state_id is not None,
        outcome_intervals=n_out or 0, realized_net_usd=num(net, 2))


def _get(db: Session, run_id: int):
    found = _base(db).filter(Run.run_id == run_id).first()
    if not found:
        raise HTTPException(status_code=404, detail=f"Optimization run {run_id} does not exist")
    return found


def _schedule_fits(db: Session, run_id: int, start, end, resolution: int) -> Optional[str]:
    """A changed horizon / resolution must still hold the run's schedule rows."""
    rows = [t for (t,) in db.query(DispatchSchedule.interval_start).filter(DispatchSchedule.run_id == run_id)]
    outside = [t for t in rows if not (start <= t < end)]
    if outside:
        return f"{len(outside)} schedule row(s) would fall outside the new horizon"
    off = [t for t in rows if int((t - start).total_seconds()) % (resolution * 60)]
    if off:
        return f"{len(off)} schedule row(s) are not on the new {resolution}-minute grid"
    return None


@router.get("", response_model=Page[OptimizationRunOut])
def list_runs(system_id: Optional[int] = None, solver_status: Optional[str] = None, start: Optional[date] = None,
              end: Optional[date] = None, order: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1),
              page_size: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    """Runs whose horizon starts in the plant-time date range, with schedule / state / outcome roll-ups."""
    q = _base(db)
    if system_id is not None:
        q = q.filter(Run.system_id == system_id)
    if solver_status:
        q = q.filter(Run.solver_status == solver_status)
    q = in_days(q, Run.horizon_start, start, end)
    total = q.count()
    sub = q.with_entities(Run.run_id).subquery()
    agg = (db.query(func.count(), func.avg(Run.expected_profit_usd), func.sum(Run.expected_profit_usd),
                    func.avg(Run.solve_seconds), func.count(func.distinct(Run.system_id)))
           .filter(Run.run_id.in_(db.query(sub.c.run_id))).one())
    realized = (db.query(func.sum(DispatchOutcome.net_pnl_usd))
                .filter(DispatchOutcome.run_id.in_(db.query(sub.c.run_id))).scalar())
    not_optimal = (db.query(func.count()).filter(Run.run_id.in_(db.query(sub.c.run_id)),
                                                 func.coalesce(Run.solver_status, "") != "OPTIMAL").scalar())
    no_sched = sum(1 for r in q.all() if not r[2])
    stats = [Stat(label=f"Runs · {agg[4]} system(s)", value=str(agg[0])),
             Stat(label="Avg expected profit", value=fmt(agg[1], 2, "USD")),
             Stat(label="Total expected", value=fmt(agg[2], 2, "USD")),
             Stat(label="Total realized net (outcomes)", value=fmt(realized, 2, "USD")),
             Stat(label="Avg solve time", value=fmt(agg[3], 2, "s")),
             Stat(label="Not OPTIMAL", value=str(not_optimal), warn=not_optimal > 0),
             Stat(label="Runs without a schedule", value=str(no_sched), warn=no_sched > 0)]
    col = Run.horizon_start.asc() if order == "asc" else Run.horizon_start.desc()
    rows = q.order_by(col, Run.run_id).offset((page - 1) * page_size).limit(page_size).all()
    return Page[OptimizationRunOut](items=[_out(*r) for r in rows], total=total, page=page, page_size=page_size,
                                    stats=stats)


@router.get("/{run_id}", response_model=OptimizationRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    return _out(*_get(db, run_id))


@router.post("", response_model=OptimizationRunOut, status_code=201)
def add_run(payload: OptimizationRunCreate, db: Session = Depends(get_db)):
    system_code(db, payload.system_id)
    if payload.run_id is not None and db.get(Run, payload.run_id):
        raise HTTPException(status_code=409, detail=f"Run {payload.run_id} already exists")
    data = payload.model_dump(exclude_none=payload.run_id is None)
    for f in TIMES:
        data[f] = local(data[f])
    row = Run(**data)
    db.add(row)
    commit_or_409(db)
    sync_run_sequence(db)
    db.commit()
    return _out(*_get(db, row.run_id))


@router.put("/{run_id}", response_model=OptimizationRunOut)
def update_run(run_id: int, payload: OptimizationRunUpdate, db: Session = Depends(get_db)):
    row = _get(db, run_id)[0]
    data = payload.model_dump()
    for f in TIMES:
        data[f] = local(data[f])
    problem = _schedule_fits(db, run_id, data["horizon_start"], data["horizon_end"], data["resolution_min"])
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    for field, value in data.items():
        setattr(row, field, value)
    commit_or_409(db)
    return _out(*_get(db, run_id))


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, run_id)[0])
    db.commit()
    return None


@router.post("/bulk", response_model=BulkResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load optimization_run.csv / .xlsx. Rows with a run_id keep it (existing runs are updated); rows without one
    get a new id. Load runs before their decision states, schedules and outcomes."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    records, errors, total, ignored = parse_upload(file.filename or "upload", content, COLS, resolvers(db))

    def check(m: OptimizationRunCreate):
        if m.run_id is not None and db.get(Run, m.run_id):
            return _schedule_fits(db, m.run_id, local(m.horizon_start), local(m.horizon_end), m.resolution_min)
        return None

    valid = validate_rows(records, OptimizationRunCreate, errors, check,
                          key=lambda m: m.run_id if m.run_id is not None else id(m))
    with_id = [r for r in valid if r["run_id"] is not None]
    new = [{k: v for k, v in r.items() if k != "run_id"} for r in valid if r["run_id"] is None]
    inserted, updated = upsert(db, Run.__table__, with_id, ["run_id"], ["system_id", *VALUES])
    sync_run_sequence(db)  # new ids must start after the ids just loaded
    if new:
        db.execute(Run.__table__.insert(), new)
        inserted += len(new)
    sync_run_sequence(db)
    db.commit()
    return bulk_result(file.filename or "upload", total, valid, inserted, updated, errors, ignored,
                       span=ts_span(valid, "horizon_start"))
