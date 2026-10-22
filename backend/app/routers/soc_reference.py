"""SOC reference (battery_master.soc_reference): independent ground-truth SOC per plant battery system and moment -
list / filter (with the BMS and coulomb-counted SOC of system_telemetry at that moment and their errors), read, edit
and delete. Loaded from soc_reference.csv (migrations/2026_10_06_soc_reference.py)."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.schemas.soc_reference import SOC_METHODS

router = APIRouter(prefix="/api/soc-reference", tags=["soc reference"])

Ref = models.SocReference
Sys = models.BatterySystem
Tel = models.SystemTelemetry


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _query(db: Session):
    return (db.query(Ref, Sys.system_name, Tel.soc_bms_pct, Tel.soc_coulomb_pct, Tel.mode_code)
            .join(Sys, Sys.battery_system_id == Ref.system_id)
            .outerjoin(Tel, (Tel.system_id == Ref.system_id) & (Tel.ts == Ref.ts)))


def _out(row) -> schemas.SocReferenceOut:
    r, name, bms, coulomb, mode = row
    true = float(r.soc_true_pct)
    bms, coulomb = _f(bms), _f(coulomb)
    return schemas.SocReferenceOut(
        system_id=r.system_id, system_name=name, ts=r.ts, soc_true_pct=true, method=r.method, note=r.note,
        bms_soc_pct=bms, coulomb_soc_pct=coulomb, mode_code=mode,
        error_vs_bms=round(true - bms, 3) if bms is not None else None,
        error_vs_coulomb=round(true - coulomb, 3) if coulomb is not None else None)


def _get(db: Session, system_id: int, ts: datetime) -> Ref:
    row = db.get(Ref, (system_id, ts))
    if not row:
        raise HTTPException(status_code=404, detail=f"No SOC reference for system {system_id} at {ts.isoformat()}")
    return row


def _one(db: Session, r: Ref) -> schemas.SocReferenceOut:
    return _out(_query(db).filter(Ref.system_id == r.system_id, Ref.ts == r.ts).one())


@router.get("/options")
def options(db: Session = Depends(get_db)):
    """Battery systems with reference points (and their range), and the allowed methods."""
    stats = {sid: (n, a, b) for sid, n, a, b in
             db.query(Ref.system_id, func.count(), func.min(Ref.ts), func.max(Ref.ts)).group_by(Ref.system_id)}
    systems = []
    for s in db.query(Sys).order_by(Sys.system_name):
        n, a, b = stats.get(s.battery_system_id, (0, None, None))
        site = db.get(models.Site, s.site_id) if s.site_id else None
        systems.append(schemas.SocRefSystem(system_id=s.battery_system_id, system_name=s.system_name,
                                            site_name=site.site_name if site else None, points=n, first_ts=a, last_ts=b))
    return {"systems": systems, "methods": list(SOC_METHODS)}


@router.get("", response_model=list[schemas.SocReferenceOut])
def list_refs(system_id: Optional[int] = None, method: Optional[str] = None, start: Optional[date] = None,
              end: Optional[date] = None, limit: int = Query(5000, ge=1, le=50000), db: Session = Depends(get_db)):
    q = _query(db)
    if system_id is not None:
        q = q.filter(Ref.system_id == system_id)
    if method:
        q = q.filter(Ref.method == method.upper())
    if start:
        q = q.filter(Ref.ts >= start)
    if end:
        q = q.filter(Ref.ts < datetime.combine(end, datetime.max.time()))
    return [_out(r) for r in q.order_by(Sys.system_name, Ref.ts).limit(limit).all()]


@router.get("/{system_id}/{ts}", response_model=schemas.SocReferenceOut)
def get_ref(system_id: int, ts: datetime, db: Session = Depends(get_db)):
    return _one(db, _get(db, system_id, ts))


@router.put("/{system_id}/{ts}", response_model=schemas.SocReferenceOut)
def update_ref(system_id: int, ts: datetime, payload: schemas.SocReferenceUpdate, db: Session = Depends(get_db)):
    row = _get(db, system_id, ts)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _one(db, row)


@router.delete("/{system_id}/{ts}", status_code=204)
def delete_ref(system_id: int, ts: datetime, db: Session = Depends(get_db)):
    db.delete(_get(db, system_id, ts))
    db.commit()
    return None
