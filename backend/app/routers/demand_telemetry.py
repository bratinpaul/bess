"""Site demand readings (battery_telemetry.demand_telemetry): list / filter, read, add, edit, delete, bulk load and
chart series - per metering point (battery_master.metering_point)."""
import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.demand_telemetry_import import parse_demand_file, upsert_demand_rows
from app.services.demand_telemetry_series import get_demand_series

router = APIRouter(prefix="/api/demand-telemetry", tags=["demand-telemetry"])

Reading = models.DemandTelemetry
Point = models.MeteringPoint


def _pf(row: Reading) -> Optional[float]:
    if row.net_load_kw is None or row.load_reactive_kvar is None:
        return None
    s = math.hypot(float(row.net_load_kw), float(row.load_reactive_kvar))
    return round(abs(float(row.net_load_kw)) / s, 4) if s else None


def _out(row: Reading, mp_code: Optional[str]) -> schemas.DemandTelemetryOut:
    out = schemas.DemandTelemetryOut.model_validate(row)
    out.mp_code = mp_code
    out.power_factor = _pf(row)
    return out


def _point(db: Session, mp_id: int) -> Point:
    mp = db.get(Point, mp_id)
    if not mp:
        raise HTTPException(status_code=404, detail=f"Metering point {mp_id} not found")
    return mp


def _get(db: Session, mp_id: int, ts: datetime) -> Reading:
    row = db.get(Reading, (mp_id, ts))
    if not row:
        raise HTTPException(status_code=404, detail="Demand reading not found")
    return row


@router.get("/lookups")
def lookups(db: Session = Depends(get_db)):
    """Metering points with their site and the readings they hold."""
    stats = {r.metering_point_id: r for r in db.query(
        Reading.metering_point_id, func.count().label("n"), func.min(Reading.ts).label("first"),
        func.max(Reading.ts).label("last")).group_by(Reading.metering_point_id)}
    sites = {s.site_id: s.site_name for s in db.query(models.Site)}
    return {"metering_points": [
        schemas.MeteringPointOut(
            metering_point_id=mp.metering_point_id, mp_code=mp.mp_code, mp_type=mp.mp_type, site_id=mp.site_id,
            site_name=sites.get(mp.site_id), voltage_kv=float(mp.voltage_kv) if mp.voltage_kv is not None else None,
            description=mp.description, readings=stats[mp.metering_point_id].n if mp.metering_point_id in stats else 0,
            first_ts=stats[mp.metering_point_id].first if mp.metering_point_id in stats else None,
            last_ts=stats[mp.metering_point_id].last if mp.metering_point_id in stats else None)
        for mp in db.query(Point).order_by(Point.mp_code)]}


@router.get("/series", response_model=schemas.DemandTelemetrySeries)
def series(metering_point_id: int, start: Optional[datetime] = None, end: Optional[datetime] = None,
           max_points: int = Query(2500, ge=100, le=10000), db: Session = Depends(get_db)):
    """Chart-ready series for one metering point (default: the last 7 days of data)."""
    mp = _point(db, metering_point_id)
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")
    tariff = (db.query(models.DemandTariff).filter(models.DemandTariff.site_id == mp.site_id)
              .order_by(models.DemandTariff.valid_from.desc().nullslast()).first())
    ws = float(tariff.peak_window_start) if tariff and tariff.peak_window_start is not None else None
    we = float(tariff.peak_window_end) if tariff and tariff.peak_window_end is not None else None
    data = get_demand_series(db, metering_point_id, start, end, max_points, ws, we)
    states = data.pop("states")
    timelines = {col: {"states": ["PEAK_WINDOW", "OFF_PEAK", "NO_TARIFF"], "segments": segs} for col, segs in states.items()}

    # reference values over the window: the peak net load, the peak inside the billing window, its ratchet level
    refs: dict[str, Optional[float]] = {"peak_net_kw": None, "billing_peak_kw": None, "ratchet_kw": None}
    if data["end"]:
        q = db.query(func.max(Reading.net_load_kw)).filter(Reading.metering_point_id == metering_point_id,
                                                           Reading.ts >= data["start"], Reading.ts <= data["end"])
        peak = q.scalar()
        refs["peak_net_kw"] = float(peak) if peak is not None else None
        if ws is not None and we is not None:
            local_h = func.extract("hour", func.timezone("Asia/Kolkata", Reading.ts)) + \
                func.extract("minute", func.timezone("Asia/Kolkata", Reading.ts)) / 60.0
            bp = q.filter(local_h >= ws, local_h < we).scalar()
            refs["billing_peak_kw"] = float(bp) if bp is not None else None
            if bp is not None and tariff.ratchet_pct is not None:
                refs["ratchet_kw"] = float(bp) * float(tariff.ratchet_pct) / 100.0
    return schemas.DemandTelemetrySeries(
        metering_point_id=metering_point_id, mp_code=mp.mp_code, timelines=timelines, refs=refs,
        tariff={"name": tariff.name, "demand_charge_per_kw": float(tariff.demand_charge_per_kw or 0),
                "peak_window_start": ws, "peak_window_end": we, "ratchet_pct": float(tariff.ratchet_pct or 0),
                "measurement_minutes": tariff.measurement_minutes} if tariff else None,
        **data)


@router.get("", response_model=schemas.DemandTelemetryPage)
def list_readings(metering_point_id: Optional[int] = None, start: Optional[datetime] = None,
                  end: Optional[datetime] = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=3000),
                  db: Session = Depends(get_db)):
    query = db.query(Reading, Point.mp_code).join(Point, Point.metering_point_id == Reading.metering_point_id)
    if metering_point_id:
        query = query.filter(Reading.metering_point_id == metering_point_id)
    if start:
        query = query.filter(Reading.ts >= start)
    if end:
        query = query.filter(Reading.ts <= end)
    total = query.count()
    rows = query.order_by(Reading.ts.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.DemandTelemetryPage(items=[_out(r, c) for r, c in rows], total=total, page=page, page_size=page_size)


@router.get("/{metering_point_id}/{ts}", response_model=schemas.DemandTelemetryOut)
def get_reading(metering_point_id: int, ts: datetime, db: Session = Depends(get_db)):
    mp = _point(db, metering_point_id)
    return _out(_get(db, metering_point_id, ts), mp.mp_code)


@router.post("", response_model=schemas.DemandTelemetryOut, status_code=201)
def add_reading(payload: schemas.DemandTelemetryCreate, db: Session = Depends(get_db)):
    """Add a reading; a reading that already exists for the point and time is refused (edit it instead)."""
    mp = _point(db, payload.metering_point_id)
    if db.get(Reading, (payload.metering_point_id, payload.ts)):
        raise HTTPException(status_code=409, detail="A reading already exists for this metering point and time")
    row = Reading(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row, mp.mp_code)


@router.put("/{metering_point_id}/{ts}", response_model=schemas.DemandTelemetryOut)
def update_reading(metering_point_id: int, ts: datetime, payload: schemas.DemandTelemetryUpdate,
                   db: Session = Depends(get_db)):
    mp = _point(db, metering_point_id)
    row = _get(db, metering_point_id, ts)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, mp.mp_code)


@router.delete("/{metering_point_id}/{ts}", status_code=204)
def delete_reading(metering_point_id: int, ts: datetime, db: Session = Depends(get_db)):
    db.delete(_get(db, metering_point_id, ts))
    db.commit()
    return None


@router.post("/bulk", response_model=schemas.BulkDemandTelemetryResult)
async def bulk_load(file: UploadFile = File(...), metering_point_code: Optional[str] = Form(None),
                    db: Session = Depends(get_db)):
    """Load a .csv / .xlsx: the metering point comes from the file's metering_point_code column, or the one chosen
    for files without it. Existing (point, ts) readings are updated."""
    default_id = None
    if metering_point_code:
        mp = db.query(Point).filter(func.upper(Point.mp_code) == metering_point_code.strip().upper()).first()
        if not mp:
            raise HTTPException(status_code=400, detail=f"Unknown metering point '{metering_point_code}'")
        default_id = mp.metering_point_id
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    valid, errors, total, ignored, codes = parse_demand_file(file.filename or "upload", content, db, default_id)
    inserted, updated = upsert_demand_rows(db, valid)
    db.commit()
    if ignored:
        errors.insert(0, schemas.BulkDemandTelemetryRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    return schemas.BulkDemandTelemetryResult(
        filename=file.filename or "upload", total_rows=total, valid_rows=len(valid), inserted=inserted,
        updated=updated, error_count=len(errors) - (1 if ignored else 0), errors=errors[:200], metering_points=codes)
