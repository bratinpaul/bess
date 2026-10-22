"""RUL lifecycle events (battery_master.lifecycle_event): commissioning, augmentation, module replacement, end of life,
failure and decommissioning of the RUL fleet systems (battery_master.battery_system) - list / filter, read, edit and
delete. Loaded from rul_lifecycle_events.csv (migrations/2026_10_06_lifecycle_event_load.py)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.schemas.lifecycle_event import EVENT_TYPES

router = APIRouter(prefix="/api/lifecycle-events", tags=["lifecycle event"])

Event = models.LifecycleEvent
Sys = models.BatterySystem
SORTABLE = {"event_date", "system_id", "event_type", "age_days", "soh_at_event"}


def _out(row: Event, code: Optional[str]) -> schemas.LifecycleEventOut:
    out = schemas.LifecycleEventOut.model_validate(row)
    out.system_code = code
    return out


def _get(db: Session, event_id: int) -> Event:
    row = db.get(Event, event_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Lifecycle event {event_id} not found")
    return row


@router.get("/types", response_model=list[str])
def event_types():
    """The event types the table accepts (chk_evt)."""
    return list(EVENT_TYPES)


@router.get("/systems", response_model=list[schemas.LifecycleSystem])
def systems(db: Session = Depends(get_db)):
    """The battery systems that have events, with their event count, commissioning date and latest event."""
    by_sys: dict[int, list[Event]] = {}
    for e in db.query(Event).order_by(Event.system_id, Event.event_date, Event.event_id):
        by_sys.setdefault(e.system_id, []).append(e)
    out = []
    for s in db.query(Sys).order_by(Sys.system_name):
        evs = by_sys.get(s.battery_system_id, [])
        if not evs:
            continue
        commission = next((e.event_date for e in evs if e.event_type == "COMMISSION"), None)
        last = evs[-1] if evs else None
        out.append(schemas.LifecycleSystem(
            system_id=s.battery_system_id, system_code=s.system_name, events=len(evs), commissioned_on=commission,
            last_event_type=last.event_type if last else None, last_event_date=last.event_date if last else None))
    return out


@router.get("", response_model=schemas.LifecycleEventPage)
def list_events(system_id: Optional[int] = None, event_type: Optional[str] = None, start: Optional[date] = None,
                end: Optional[date] = None, sort: str = "event_date", order: Literal["asc", "desc"] = "asc",
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    q = db.query(Event, Sys.system_name).join(Sys, Sys.battery_system_id == Event.system_id)
    if system_id is not None:
        q = q.filter(Event.system_id == system_id)
    if start:
        q = q.filter(Event.event_date >= start)
    if end:
        q = q.filter(Event.event_date <= end)
    # counts per type within the system / date filter, before the type filter itself
    counts = {t: n for t, n in q.with_entities(Event.event_type, func.count()).group_by(Event.event_type)}
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if sort not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")
    total = q.count()
    col = getattr(Event, sort)
    keys = [col.asc() if order == "asc" else col.desc()]
    if sort != "system_id":
        keys.append(Sys.system_name.asc())
    if sort != "event_date":
        keys.append(Event.event_date.asc())
    rows = q.order_by(*keys, Event.event_id).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.LifecycleEventPage(items=[_out(r, code) for r, code in rows], total=total, page=page,
                                      page_size=page_size, counts=counts)


@router.get("/{event_id}", response_model=schemas.LifecycleEventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    row = _get(db, event_id)
    return _out(row, db.get(Sys, row.system_id).system_name)


@router.put("/{event_id}", response_model=schemas.LifecycleEventOut)
def update_event(event_id: int, payload: schemas.LifecycleEventUpdate, db: Session = Depends(get_db)):
    row = _get(db, event_id)
    clash = (db.query(Event.event_id).filter(Event.system_id == row.system_id, Event.event_type == payload.event_type,
                                             Event.event_date == payload.event_date, Event.event_id != event_id).first())
    if clash:
        raise HTTPException(status_code=409, detail=f"This system already has a {payload.event_type} event on "
                                                    f"{payload.event_date.isoformat()}")
    values = payload.model_dump()
    for k in ("failure_mode", "note"):
        values[k] = (values[k] or "").strip() or None
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, db.get(Sys, row.system_id).system_name)


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, event_id))
    db.commit()
    return None
