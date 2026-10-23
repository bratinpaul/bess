"""Current-sensor calibrations (battery_master.current_sensor_cal): offset, gain error and offset drift per fleet system
(battery_master.battery_system) and calibration date - list / filter, read, edit and delete. Loaded from
current_sensor_cal.csv (one-off load). Each row also carries the offset its drift
projects to today, or to the system's next calibration when there is a later one."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/current-sensor-cal", tags=["current sensor calibration"])

Cal = models.CurrentSensorCal
Sys = models.BatterySystem


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _outs(rows: list[tuple[Cal, str]]) -> list[schemas.CurrentSensorCalOut]:
    """Rows with the projected offset (drift x days to today or to the next calibration of the same system)."""
    by_sys: dict[int, list[date]] = {}
    for c, _ in rows:
        by_sys.setdefault(c.system_id, []).append(c.calibrated_on)
    today = date.today()
    out = []
    for c, code in rows:
        later = sorted(d for d in by_sys[c.system_id] if d > c.calibrated_on)
        until = later[0] if later else today
        days = max((until - c.calibrated_on).days, 0)
        offset, drift = _f(c.offset_a), _f(c.drift_a_per_day)
        out.append(schemas.CurrentSensorCalOut(
            system_id=c.system_id, system_code=code, calibrated_on=c.calibrated_on, offset_a=offset,
            gain_error_pct=_f(c.gain_error_pct), drift_a_per_day=drift, days_since=days,
            projected_offset_a=round(offset + drift * days, 3) if offset is not None and drift is not None else None,
            superseded_on=later[0] if later else None))
    return out


def _get(db: Session, system_id: int, calibrated_on: date) -> Cal:
    row = db.get(Cal, (system_id, calibrated_on))
    if not row:
        raise HTTPException(status_code=404, detail=f"No calibration of system {system_id} on {calibrated_on.isoformat()}")
    return row


def _one(db: Session, row: Cal) -> schemas.CurrentSensorCalOut:
    rows = (db.query(Cal, Sys.system_name).join(Sys, Sys.battery_system_id == Cal.system_id)
            .filter(Cal.system_id == row.system_id).all())
    return next(o for o in _outs(rows) if o.calibrated_on == row.calibrated_on)


@router.get("/systems", response_model=list[schemas.CalSystem])
def systems(db: Session = Depends(get_db)):
    """Battery systems that have calibrations, with their number of calibrations (for the filter)."""
    counts = dict(db.query(Cal.system_id, func.count()).group_by(Cal.system_id).all())
    return [schemas.CalSystem(system_id=s.battery_system_id, system_code=s.system_name, calibrations=counts.get(s.battery_system_id, 0))
            for s in db.query(Sys).order_by(Sys.system_name) if counts.get(s.battery_system_id)]


@router.get("", response_model=list[schemas.CurrentSensorCalOut])
def list_cals(system_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
              db: Session = Depends(get_db)):
    q = db.query(Cal, Sys.system_name).join(Sys, Sys.battery_system_id == Cal.system_id)
    if system_id is not None:
        q = q.filter(Cal.system_id == system_id)
    rows = q.order_by(Sys.system_name, Cal.calibrated_on).all()
    out = _outs(rows)
    return [o for o in out if (not start or o.calibrated_on >= start) and (not end or o.calibrated_on <= end)]


@router.get("/{system_id}/{calibrated_on}", response_model=schemas.CurrentSensorCalOut)
def get_cal(system_id: int, calibrated_on: date, db: Session = Depends(get_db)):
    return _one(db, _get(db, system_id, calibrated_on))


@router.put("/{system_id}/{calibrated_on}", response_model=schemas.CurrentSensorCalOut)
def update_cal(system_id: int, calibrated_on: date, payload: schemas.CurrentSensorCalUpdate, db: Session = Depends(get_db)):
    row = _get(db, system_id, calibrated_on)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _one(db, row)


@router.delete("/{system_id}/{calibrated_on}", status_code=204)
def delete_cal(system_id: int, calibrated_on: date, db: Session = Depends(get_db)):
    db.delete(_get(db, system_id, calibrated_on))
    db.commit()
    return None
