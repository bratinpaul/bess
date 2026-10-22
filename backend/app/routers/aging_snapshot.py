"""RUL aging snapshots (battery_master.aging_snapshot): list / filter, read, edit and delete. Keyed by the RUL fleet
system (battery_master.battery_system) and the snapshot date; loaded from rul_aging_snapshots.csv
(migrations/2026_10_06_aging_snapshot_load.py)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/aging-snapshots", tags=["aging snapshot"])

Snap = models.AgingSnapshot
Sys = models.BatterySystem
SORTABLE = {"snapshot_date", "system_id", "age_days", "soh_pct", "rul_days", "rul_cycles", "equiv_full_cycles",
            "cum_throughput_mwh", "avg_cell_temp_c", "internal_resistance_mohm"}


def _out(row: Snap, code: Optional[str]) -> schemas.AgingSnapshotOut:
    out = schemas.AgingSnapshotOut.model_validate(row)
    out.system_code = code
    return out


def _get(db: Session, system_id: int, snapshot_date: date) -> Snap:
    row = db.get(Snap, (system_id, snapshot_date))
    if not row:
        raise HTTPException(status_code=404, detail=f"No snapshot for system {system_id} on {snapshot_date.isoformat()}")
    return row


@router.get("/systems", response_model=list[schemas.AgingSystemSummary])
def systems(db: Session = Depends(get_db)):
    """The battery systems that have snapshots, with their snapshot count, date range and latest SOH / RUL."""
    latest = (db.query(Snap.system_id, func.max(Snap.snapshot_date).label("d")).group_by(Snap.system_id).subquery())
    last = {r.system_id: r for r in db.query(Snap).join(latest, (Snap.system_id == latest.c.system_id)
                                                           & (Snap.snapshot_date == latest.c.d))}
    stats = {r[0]: r for r in db.query(Snap.system_id, func.count(), func.min(Snap.snapshot_date),
                                      func.max(Snap.snapshot_date)).group_by(Snap.system_id)}
    out = []
    for s in db.query(Sys).order_by(Sys.system_name):
        st, lr = stats.get(s.battery_system_id), last.get(s.battery_system_id)
        if not st:
            continue  # battery systems without aging data are not part of the RUL reference set
        out.append(schemas.AgingSystemSummary(
            system_id=s.battery_system_id, system_code=s.system_name, snapshots=st[1] if st else 0,
            first_date=st[2] if st else None, last_date=st[3] if st else None,
            latest_soh_pct=float(lr.soh_pct) if lr and lr.soh_pct is not None else None,
            latest_rul_days=lr.rul_days if lr else None, eol_reached=lr.eol_reached if lr else None))
    return out


@router.get("", response_model=schemas.AgingSnapshotPage)
def list_snapshots(system_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
                   eol_reached: Optional[bool] = None, is_censored: Optional[bool] = None,
                   sort: str = "snapshot_date", order: Literal["asc", "desc"] = "asc",
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    q = db.query(Snap, Sys.system_name).join(Sys, Sys.battery_system_id == Snap.system_id)
    if system_id is not None:
        q = q.filter(Snap.system_id == system_id)
    if start:
        q = q.filter(Snap.snapshot_date >= start)
    if end:
        q = q.filter(Snap.snapshot_date <= end)
    if eol_reached is not None:
        q = q.filter(Snap.eol_reached.is_(eol_reached))
    if is_censored is not None:
        q = q.filter(Snap.is_censored.is_(is_censored))
    if sort not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")
    total = q.count()
    col = getattr(Snap, sort)
    keys = [col.asc() if order == "asc" else col.desc()]
    if sort != "system_id":
        keys.append(Sys.system_name.asc())
    if sort != "snapshot_date":
        keys.append(Snap.snapshot_date.asc())
    rows = q.order_by(*keys).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.AgingSnapshotPage(items=[_out(r, code) for r, code in rows], total=total, page=page,
                                     page_size=page_size)


@router.get("/{system_id}/{snapshot_date}", response_model=schemas.AgingSnapshotOut)
def get_snapshot(system_id: int, snapshot_date: date, db: Session = Depends(get_db)):
    row = _get(db, system_id, snapshot_date)
    return _out(row, db.get(Sys, system_id).system_name)


@router.put("/{system_id}/{snapshot_date}", response_model=schemas.AgingSnapshotOut)
def update_snapshot(system_id: int, snapshot_date: date, payload: schemas.AgingSnapshotUpdate,
                    db: Session = Depends(get_db)):
    row = _get(db, system_id, snapshot_date)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, db.get(Sys, system_id).system_name)


@router.delete("/{system_id}/{snapshot_date}", status_code=204)
def delete_snapshot(system_id: int, snapshot_date: date, db: Session = Depends(get_db)):
    db.delete(_get(db, system_id, snapshot_date))
    db.commit()
    return None
