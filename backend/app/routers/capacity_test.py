"""RUL capacity tests (battery_master.capacity_test): periodic RPT capacity / resistance checkpoints of the RUL fleet
systems (battery_master.battery_system) - list / filter, read, edit and delete. Loaded from rul_capacity_tests.csv
(migrations/2026_10_06_capacity_test_load.py)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/capacity-tests", tags=["capacity test"])

Test = models.CapacityTest
Sys = models.BatterySystem
SORTABLE = {"test_date", "system_id", "age_days", "equiv_full_cycles", "measured_capacity_kwh", "soh_pct",
            "internal_resistance_mohm"}


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _out(row: Test, code: Optional[str]) -> schemas.CapacityTestOut:
    out = schemas.CapacityTestOut.model_validate(row)
    out.system_code = code
    return out


def _get(db: Session, test_id: int) -> Test:
    row = db.get(Test, test_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Capacity test {test_id} not found")
    return row


@router.get("/systems", response_model=list[schemas.CapacityTestSystem])
def systems(db: Session = Depends(get_db)):
    """The battery systems that have tests, with their test count, date range and first / latest measured capacity and SOH."""
    by_sys: dict[int, list[Test]] = {}
    for t in db.query(Test).order_by(Test.system_id, Test.test_date):
        by_sys.setdefault(t.system_id, []).append(t)
    out = []
    for s in db.query(Sys).order_by(Sys.system_name):
        tests = by_sys.get(s.battery_system_id, [])
        if not tests:
            continue
        first, last = (tests[0], tests[-1]) if tests else (None, None)
        out.append(schemas.CapacityTestSystem(
            system_id=s.battery_system_id, system_code=s.system_name, tests=len(tests),
            first_date=first.test_date if first else None, last_date=last.test_date if last else None,
            first_capacity_kwh=_f(first.measured_capacity_kwh) if first else None,
            latest_capacity_kwh=_f(last.measured_capacity_kwh) if last else None,
            latest_soh_pct=_f(last.soh_pct) if last else None))
    return out


@router.get("", response_model=schemas.CapacityTestPage)
def list_tests(system_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
               method: Optional[str] = None, sort: str = "test_date", order: Literal["asc", "desc"] = "asc",
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    q = db.query(Test, Sys.system_name).join(Sys, Sys.battery_system_id == Test.system_id)
    if system_id is not None:
        q = q.filter(Test.system_id == system_id)
    if start:
        q = q.filter(Test.test_date >= start)
    if end:
        q = q.filter(Test.test_date <= end)
    if method:
        q = q.filter(Test.method == method)
    if sort not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")
    total = q.count()
    col = getattr(Test, sort)
    keys = [col.asc() if order == "asc" else col.desc()]
    if sort != "system_id":
        keys.append(Sys.system_name.asc())
    if sort != "test_date":
        keys.append(Test.test_date.asc())
    rows = q.order_by(*keys).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.CapacityTestPage(items=[_out(r, code) for r, code in rows], total=total, page=page,
                                    page_size=page_size)


@router.get("/methods", response_model=list[str])
def methods(db: Session = Depends(get_db)):
    return [m for (m,) in db.query(Test.method).filter(Test.method.isnot(None)).distinct().order_by(Test.method)]


@router.get("/{test_id}", response_model=schemas.CapacityTestOut)
def get_test(test_id: int, db: Session = Depends(get_db)):
    row = _get(db, test_id)
    return _out(row, db.get(Sys, row.system_id).system_name)


@router.put("/{test_id}", response_model=schemas.CapacityTestOut)
def update_test(test_id: int, payload: schemas.CapacityTestUpdate, db: Session = Depends(get_db)):
    row = _get(db, test_id)
    clash = (db.query(Test.test_id).filter(Test.system_id == row.system_id, Test.test_date == payload.test_date,
                                           Test.test_id != test_id).first())
    if clash:
        raise HTTPException(status_code=409, detail=f"This system already has a test on {payload.test_date.isoformat()}")
    values = payload.model_dump()
    values["method"] = (values["method"] or "").strip() or None
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, db.get(Sys, row.system_id).system_name)


@router.delete("/{test_id}", status_code=204)
def delete_test(test_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, test_id))
    db.commit()
    return None
