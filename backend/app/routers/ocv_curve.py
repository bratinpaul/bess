"""OCV curves (battery_master.ocv_curve): per-cell open-circuit voltage vs SOC by chemistry, direction and temperature -
list / filter, the curves for charting, read, edit and delete a point. Loaded from ocv_curve.csv
(migrations/2026_10_06_ocv_curve_load.py)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/ocv-curve", tags=["ocv curve"])

Pt = models.OcvCurve
DIRECTIONS = ("CHARGE", "DISCHARGE", "MEAN")  # ocv_curve_direction_check


def _out(r: Pt) -> schemas.OcvPointOut:
    return schemas.OcvPointOut(chemistry=r.chemistry, direction=r.direction, temp_c=float(r.temp_c),
                               soc_pct=float(r.soc_pct), ocv_v=float(r.ocv_v))


def _filtered(db: Session, chemistry: Optional[str], direction: Optional[str], temp_c: Optional[float]):
    q = db.query(Pt)
    if chemistry:
        q = q.filter(Pt.chemistry == chemistry.upper())
    if direction:
        q = q.filter(Pt.direction == direction.upper())
    if temp_c is not None:
        q = q.filter(Pt.temp_c == temp_c)
    return q


def _get(db: Session, chemistry: str, direction: str, temp_c: float, soc_pct: float) -> Pt:
    row = db.get(Pt, (chemistry.upper(), direction.upper(), temp_c, soc_pct))
    if not row:
        raise HTTPException(status_code=404, detail=f"No OCV point {chemistry} / {direction} / {temp_c} °C / {soc_pct} % SOC")
    return row


@router.get("/options")
def options(db: Session = Depends(get_db)):
    """Chemistries and temperatures in the table, and the allowed directions."""
    return {
        "chemistries": [c for (c,) in db.query(Pt.chemistry).distinct().order_by(Pt.chemistry)],
        "temperatures": [float(t) for (t,) in db.query(Pt.temp_c).distinct().order_by(Pt.temp_c)],
        "directions": list(DIRECTIONS),
    }


@router.get("/curves", response_model=list[schemas.OcvCurveSummary])
def curves(chemistry: Optional[str] = None, direction: Optional[str] = None, temp_c: Optional[float] = None,
           db: Session = Depends(get_db)):
    """Each curve's points in SOC order, with its range and whether OCV rises with SOC throughout."""
    rows = _filtered(db, chemistry, direction, temp_c).order_by(Pt.chemistry, Pt.direction, Pt.temp_c, Pt.soc_pct).all()
    groups: dict[tuple, list[Pt]] = {}
    for r in rows:
        groups.setdefault((r.chemistry, r.direction, float(r.temp_c)), []).append(r)
    out = []
    for (chem, direc, temp), pts in groups.items():
        soc = [float(p.soc_pct) for p in pts]
        ocv = [float(p.ocv_v) for p in pts]
        out.append(schemas.OcvCurveSummary(
            chemistry=chem, direction=direc, temp_c=temp, points=len(pts), soc_min=min(soc), soc_max=max(soc),
            ocv_min=min(ocv), ocv_max=max(ocv), monotonic=all(b >= a for a, b in zip(ocv, ocv[1:])), soc=soc, ocv=ocv))
    return out


@router.get("", response_model=list[schemas.OcvPointOut])
def list_points(chemistry: Optional[str] = None, direction: Optional[str] = None, temp_c: Optional[float] = None,
                db: Session = Depends(get_db)):
    """All points matching the filters (a curve table is small: no paging)."""
    q = _filtered(db, chemistry, direction, temp_c).order_by(Pt.chemistry, Pt.direction, Pt.temp_c, Pt.soc_pct)
    return [_out(r) for r in q.limit(20000).all()]


@router.get("/{chemistry}/{direction}/{temp_c}/{soc_pct}", response_model=schemas.OcvPointOut)
def get_point(chemistry: str, direction: str, temp_c: float, soc_pct: float, db: Session = Depends(get_db)):
    return _out(_get(db, chemistry, direction, temp_c, soc_pct))


@router.put("/{chemistry}/{direction}/{temp_c}/{soc_pct}", response_model=schemas.OcvPointOut)
def update_point(chemistry: str, direction: str, temp_c: float, soc_pct: float, payload: schemas.OcvPointUpdate,
                 db: Session = Depends(get_db)):
    row = _get(db, chemistry, direction, temp_c, soc_pct)
    row.ocv_v = payload.ocv_v
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{chemistry}/{direction}/{temp_c}/{soc_pct}", status_code=204)
def delete_point(chemistry: str, direction: str, temp_c: float, soc_pct: float, db: Session = Depends(get_db)):
    db.delete(_get(db, chemistry, direction, temp_c, soc_pct))
    db.commit()
    return None
