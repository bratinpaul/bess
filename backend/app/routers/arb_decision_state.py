"""Decision state (battery_master.decision_state): what the optimizer saw at horizon start for each run - SOC, SOH,
usable energy, temperature, available power, cycle budget, aux forecast and AS reservation. One row per run."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.battery_system import BatterySystem
from app.models.arbitrage import DecisionState, OptimizationRun
from app.routers.arb_common import bulk_result, commit_or_409, fmt, in_days, resolvers
from app.schemas.arbitrage import (
    BulkResult,
    DecisionStateCreate,
    DecisionStateOut,
    DecisionStateUpdate,
    Page,
    Stat,
)
from app.services.arbitrage_import import ArbitrageImportError, Col, num, parse_upload, upsert, validate_rows

router = APIRouter(prefix="/api/decision-states", tags=["dispatch"])

DS, Run = DecisionState, OptimizationRun
VALUES = ("soc_start_pct", "soh_pct", "usable_energy_mwh", "avg_cell_temp_c", "p_charge_avail_kw",
          "p_discharge_avail_kw", "cycles_used_today", "aux_load_forecast_kw", "reserved_mw_as")
COLS = [Col("run_id", ("run_id",), "int", True)] + [
    Col("soc_start_pct", ("soc_start_pct", "soc"), "num", True),
    Col("soh_pct", ("soh_pct", "soh")),
    Col("usable_energy_mwh", ("usable_energy_mwh", "uemwh")),
    Col("avg_cell_temp_c", ("avg_cell_temp_c", "temp")),
    Col("p_charge_avail_kw", ("p_charge_avail_kw", "pch")),
    Col("p_discharge_avail_kw", ("p_discharge_avail_kw", "pdis")),
    Col("cycles_used_today", ("cycles_used_today", "cyc")),
    Col("aux_load_forecast_kw", ("aux_load_forecast_kw", "aux")),
    Col("reserved_mw_as", ("reserved_mw_as", "resv")),
]


def _base(db: Session):
    return (db.query(DS, BatterySystem.system_name, Run.issued_at, Run.horizon_start)
            .join(Run, Run.run_id == DS.run_id).join(BatterySystem, BatterySystem.battery_system_id == Run.system_id))


def _out(d: DS, code, issued, start) -> DecisionStateOut:
    return DecisionStateOut(run_id=d.run_id, system_code=code, issued_at=issued, horizon_start=start,
                            **{f: num(getattr(d, f)) for f in VALUES})


def _get(db: Session, run_id: int):
    found = _base(db).filter(DS.run_id == run_id).first()
    if not found:
        raise HTTPException(status_code=404, detail=f"Run {run_id} has no decision state")
    return found


@router.get("", response_model=Page[DecisionStateOut])
def list_states(system_id: Optional[int] = None, run_id: Optional[int] = None, start: Optional[date] = None,
                end: Optional[date] = None, order: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    """States of runs whose horizon starts in the plant-time date range."""
    q = _base(db)
    if system_id is not None:
        q = q.filter(Run.system_id == system_id)
    if run_id is not None:
        q = q.filter(DS.run_id == run_id)
    q = in_days(q, Run.horizon_start, start, end)
    agg = q.with_entities(func.count(), func.avg(DS.soc_start_pct), func.min(DS.soc_start_pct),
                          func.max(DS.soc_start_pct), func.avg(DS.soh_pct), func.min(DS.soh_pct),
                          func.avg(DS.usable_energy_mwh), func.max(DS.avg_cell_temp_c),
                          func.avg(DS.reserved_mw_as)).one()
    runs_without = (db.query(func.count(Run.run_id)).outerjoin(DS, DS.run_id == Run.run_id)
                    .filter(DS.run_id.is_(None)).scalar())
    stats = [Stat(label="States", value=str(agg[0])),
             Stat(label="Avg SOC at start", value=fmt(agg[1], 1, "%")),
             Stat(label="SOC at start range", value=f"{fmt(agg[2], 1)} – {fmt(agg[3], 1)} %" if agg[2] is not None else None),
             Stat(label="Avg / min SOH", value=f"{fmt(agg[4], 1)} / {fmt(agg[5], 1)} %" if agg[4] is not None else None),
             Stat(label="Avg usable energy", value=fmt(agg[6], 3, "MWh")),
             Stat(label="Max avg cell temp", value=fmt(agg[7], 1, "°C"), warn=agg[7] is not None and float(agg[7]) > 40),
             Stat(label="Avg AS reservation", value=fmt(agg[8], 3, "MW")),
             Stat(label="Runs without a state (all)", value=str(runs_without), warn=runs_without > 0)]
    col = Run.horizon_start.asc() if order == "asc" else Run.horizon_start.desc()
    rows = q.order_by(col).offset((page - 1) * page_size).limit(page_size).all()
    return Page[DecisionStateOut](items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size,
                                  stats=stats)


@router.get("/{run_id}", response_model=DecisionStateOut)
def get_state(run_id: int, db: Session = Depends(get_db)):
    return _out(*_get(db, run_id))


@router.post("", response_model=DecisionStateOut, status_code=201)
def add_state(payload: DecisionStateCreate, db: Session = Depends(get_db)):
    if not db.get(Run, payload.run_id):
        raise HTTPException(status_code=422, detail=f"Run {payload.run_id} does not exist")
    if db.get(DS, payload.run_id):
        raise HTTPException(status_code=409, detail=f"Run {payload.run_id} already has a decision state")
    db.add(DS(**payload.model_dump()))
    commit_or_409(db)
    return _out(*_get(db, payload.run_id))


@router.put("/{run_id}", response_model=DecisionStateOut)
def update_state(run_id: int, payload: DecisionStateUpdate, db: Session = Depends(get_db)):
    row = _get(db, run_id)[0]
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    commit_or_409(db)
    return _out(*_get(db, run_id))


@router.delete("/{run_id}", status_code=204)
def delete_state(run_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, run_id)[0])
    db.commit()
    return None


@router.post("/bulk", response_model=BulkResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load decision_state.csv / .xlsx; existing states are updated. Every run_id must already be loaded."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        records, errors, total, ignored = parse_upload(file.filename or "upload", content, COLS, resolvers(db))
    except ArbitrageImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    runs = {r for (r,) in db.query(Run.run_id)}
    valid = validate_rows(records, DecisionStateCreate, errors,
                          lambda m: None if m.run_id in runs else
                          f"run_id: run {m.run_id} does not exist - load optimization_run first",
                          key=lambda m: m.run_id)
    inserted, updated = upsert(db, DS.__table__, valid, ["run_id"], list(VALUES))
    db.commit()
    return bulk_result(file.filename or "upload", total, valid, inserted, updated, errors, ignored)
