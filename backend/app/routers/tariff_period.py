"""Time-of-use tariff bands (battery_master.ems_tariff_period): list, lookups, read, add, edit, delete.

Bands of one scope (an EMS, or the shared bands with ems_id NULL) must not overlap in hours when their day type,
season and validity overlap: 'ALL' day type / season overlaps every other value, an open validity date is
unbounded. The price forecasting model reads these bands (an EMS's own bands, else the shared ones).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.models.tariff_period import DAY_TYPES, PRICE_LEVELS

router = APIRouter(prefix="/api/tariff-periods", tags=["tariff-periods"])

Band = models.EmsTariffPeriod
DEFAULT_SEASONS = ["ALL", "SUMMER", "MONSOON", "WINTER"]


def _ems_names(db: Session) -> dict[int, tuple[str, Optional[str]]]:
    rows = db.execute(text("""
        SELECT e.ems_id, e.ems_code, s.site_name FROM battery_master.ems_controller e
        LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = e.battery_system_id
        LEFT JOIN battery_master.site s ON s.site_id = bs.site_id ORDER BY e.ems_id"""))
    return {r.ems_id: (r.ems_code, r.site_name) for r in rows}


def _out(row: Band, names: dict) -> schemas.TariffPeriodOut:
    out = schemas.TariffPeriodOut.model_validate(row)
    if row.ems_id is not None and row.ems_id in names:
        out.ems_code, out.site_name = names[row.ems_id]
    return out


def _get(db: Session, tariff_period_id: int) -> Band:
    row = db.get(Band, tariff_period_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tariff band not found")
    return row


def _overlaps_dates(a_from: Optional[date], a_to: Optional[date], b_from: Optional[date], b_to: Optional[date]) -> bool:
    return (a_to is None or b_from is None or b_from <= a_to) and (b_to is None or a_from is None or a_from <= b_to)


def _check(db: Session, payload: schemas.TariffPeriodCreate | schemas.TariffPeriodUpdate, exclude_id: Optional[int] = None) -> None:
    if payload.ems_id is not None and payload.ems_id not in _ems_names(db):
        raise HTTPException(status_code=400, detail=f"EMS {payload.ems_id} not found")
    query = db.query(Band).filter(Band.ems_id.is_(None) if payload.ems_id is None else Band.ems_id == payload.ems_id)
    if exclude_id is not None:
        query = query.filter(Band.tariff_period_id != exclude_id)
    for other in query:
        same_day = "ALL" in (payload.day_type, other.day_type) or payload.day_type == other.day_type
        same_season = "ALL" in (payload.season, other.season) or payload.season == other.season
        hours = payload.start_hour < other.end_hour and other.start_hour < payload.end_hour
        if same_day and same_season and hours and _overlaps_dates(payload.valid_from, payload.valid_to,
                                                                  other.valid_from, other.valid_to):
            raise HTTPException(status_code=409, detail=(
                f"Overlaps band {other.band_code} ({other.start_hour:02d}–{other.end_hour:02d} h, {other.day_type}, "
                f"{other.season}) of the same scope"))


@router.get("", response_model=list[schemas.TariffPeriodOut])
def list_bands(db: Session = Depends(get_db)):
    names = _ems_names(db)
    rows = db.query(Band).order_by(Band.ems_id.nulls_first(), Band.day_type, Band.season, Band.start_hour).all()
    return [_out(r, names) for r in rows]


@router.get("/lookups", response_model=schemas.TariffPeriodLookups)
def lookups(db: Session = Depends(get_db)):
    used = [v for (v,) in db.query(Band.season).distinct().order_by(Band.season)]
    return schemas.TariffPeriodLookups(
        price_levels=list(PRICE_LEVELS), day_types=list(DAY_TYPES),
        seasons=list(dict.fromkeys(DEFAULT_SEASONS + used)),
        ems=[schemas.TariffEmsOption(ems_id=e, ems_code=c, site_name=s) for e, (c, s) in _ems_names(db).items()])


@router.get("/{tariff_period_id}", response_model=schemas.TariffPeriodOut)
def get_band(tariff_period_id: int, db: Session = Depends(get_db)):
    return _out(_get(db, tariff_period_id), _ems_names(db))


@router.post("", response_model=schemas.TariffPeriodOut, status_code=201)
def create_band(payload: schemas.TariffPeriodCreate, db: Session = Depends(get_db)):
    _check(db, payload)
    row = Band(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row, _ems_names(db))


@router.put("/{tariff_period_id}", response_model=schemas.TariffPeriodOut)
def update_band(tariff_period_id: int, payload: schemas.TariffPeriodUpdate, db: Session = Depends(get_db)):
    row = _get(db, tariff_period_id)
    _check(db, payload, exclude_id=tariff_period_id)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, _ems_names(db))


@router.delete("/{tariff_period_id}", status_code=204)
def delete_band(tariff_period_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, tariff_period_id))
    db.commit()
    return None
