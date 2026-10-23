"""RUL battery provenance (battery_master.battery_provenance): cell provenance, batch and beginning-of-life baseline
per RUL fleet system (battery_master.battery_system) - list / filter, read, edit and delete. Loaded from rul_systems.csv
(one-off load). Each row is read with the system's COMMISSION lifecycle event and
its chemistry's end-of-life criteria as read-only context."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/battery-provenance", tags=["battery provenance"])

Prov = models.BatteryProvenance
Sys = models.BatterySystem
Eol = models.EolCriteria
Event = models.LifecycleEvent
SORTABLE = {"system_code", "chemistry", "batch_lot", "build_date", "bol_capacity_kwh", "bol_resistance_mohm",
            "usage_cycles_per_day", "climate_avg_temp_c"}


def _commissioned(db: Session) -> dict:
    return {sid: d for sid, d in db.query(Event.system_id, Event.event_date).filter(Event.event_type == "COMMISSION")
            .order_by(Event.event_date.desc())}


def _out(row: Prov, code: Optional[str], commissioned: dict, eol: dict) -> schemas.BatteryProvenanceOut:
    out = schemas.BatteryProvenanceOut.model_validate(row)
    out.system_code = code
    out.commissioned_on = commissioned.get(row.system_id)
    crit = eol.get((row.chemistry or "").upper())
    if crit:
        out.soh_eol_pct = float(crit.soh_eol_pct)
        out.resistance_eol_pct = float(crit.resistance_eol_pct) if crit.resistance_eol_pct is not None else None
    return out


def _eol(db: Session) -> dict:
    return {c.chemistry.upper(): c for c in db.query(Eol)}


def _get(db: Session, system_id: int) -> Prov:
    row = db.get(Prov, system_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"No provenance for system {system_id}")
    return row


@router.get("/options", response_model=schemas.ProvenanceOptions)
def options(db: Session = Depends(get_db)):
    """Values in use (for filters and form suggestions) and the end-of-life criteria per chemistry."""
    def distinct(col):
        return [v for (v,) in db.query(col).filter(col.isnot(None)).distinct().order_by(col)]

    eol = db.query(Eol).order_by(Eol.chemistry).all()
    chems = sorted(set(distinct(Prov.chemistry)) | {e.chemistry for e in eol})
    return schemas.ProvenanceOptions(
        chemistries=chems, batch_lots=distinct(Prov.batch_lot), manufacturers=distinct(Prov.manufacturer),
        cell_models=distinct(Prov.cell_model), cell_formats=distinct(Prov.cell_format),
        eol_criteria=[{"chemistry": e.chemistry, "soh_eol_pct": float(e.soh_eol_pct),
                       "resistance_eol_pct": float(e.resistance_eol_pct) if e.resistance_eol_pct is not None else None,
                       "description": e.description} for e in eol])


@router.get("", response_model=list[schemas.BatteryProvenanceOut])
def list_provenance(chemistry: Optional[str] = None, batch_lot: Optional[str] = None, sort: str = "system_code",
                    order: Literal["asc", "desc"] = "asc", db: Session = Depends(get_db)):
    """All systems' provenance (one row per system - a small fleet, so no paging)."""
    q = db.query(Prov, Sys.system_name).join(Sys, Sys.battery_system_id == Prov.system_id)
    if chemistry:
        q = q.filter(Prov.chemistry == chemistry)
    if batch_lot:
        q = q.filter(Prov.batch_lot == batch_lot)
    if sort not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")
    col = Sys.system_name if sort == "system_code" else getattr(Prov, sort)
    keys = [col.asc() if order == "asc" else col.desc()]
    if sort != "system_code":
        keys.append(Sys.system_name.asc())
    commissioned, eol = _commissioned(db), _eol(db)
    return [_out(r, code, commissioned, eol) for r, code in q.order_by(*keys).all()]


@router.get("/{system_id}", response_model=schemas.BatteryProvenanceOut)
def get_provenance(system_id: int, db: Session = Depends(get_db)):
    row = _get(db, system_id)
    return _out(row, db.get(Sys, system_id).system_name, _commissioned(db), _eol(db))


@router.put("/{system_id}", response_model=schemas.BatteryProvenanceOut)
def update_provenance(system_id: int, payload: schemas.BatteryProvenanceUpdate, db: Session = Depends(get_db)):
    row = _get(db, system_id)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, db.get(Sys, system_id).system_name, _commissioned(db), _eol(db))


@router.delete("/{system_id}", status_code=204)
def delete_provenance(system_id: int, db: Session = Depends(get_db)):
    """Deletes the provenance row only - the system and its tests, events and snapshots stay."""
    db.delete(_get(db, system_id))
    db.commit()
    return None
