"""Measured weather (battery_telemetry.weather_actual): list / filter, read, add, edit, delete, bulk load and chart
series - per weather station (battery_master.weather_station)."""
import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.weather_import import WeatherImportError, parse_weather_file, upsert_weather_rows
from app.services.weather_series import get_weather_series

router = APIRouter(prefix="/api/weather", tags=["weather"])

Reading = models.WeatherActual
Station = models.WeatherStation


def dew_point(temp, rh) -> Optional[float]:
    if temp is None or rh is None:
        return None
    t, h = float(temp), max(float(rh), 1.0)
    g = math.log(h / 100.0) + 17.62 * t / (243.12 + t)
    return round(243.12 * g / (17.62 - g), 2)


def _out(row: Reading, code: Optional[str]) -> schemas.WeatherActualOut:
    out = schemas.WeatherActualOut.model_validate(row)
    out.station_code = code
    out.dew_point_c = dew_point(row.temp_c, row.humidity_pct)
    return out


def _station(db: Session, station_id: int) -> Station:
    st = db.get(Station, station_id)
    if not st:
        raise HTTPException(status_code=404, detail=f"Weather station {station_id} not found")
    return st


def _get(db: Session, station_id: int, ts: datetime) -> Reading:
    row = db.get(Reading, (station_id, ts))
    if not row:
        raise HTTPException(status_code=404, detail="Weather reading not found")
    return row


@router.get("/lookups")
def lookups(db: Session = Depends(get_db)):
    """Weather stations with their site and the readings they hold."""
    stats = {r.station_id: r for r in db.query(
        Reading.station_id, func.count().label("n"), func.min(Reading.ts).label("first"),
        func.max(Reading.ts).label("last")).group_by(Reading.station_id)}
    sites = {s.site_id: s.site_name for s in db.query(models.Site)}
    out = []
    for st in db.query(Station).order_by(Station.station_code):
        s = stats.get(st.station_id)
        out.append(schemas.WeatherStationOut(
            station_id=st.station_id, station_code=st.station_code, provider=st.provider, site_id=st.site_id,
            site_name=sites.get(st.site_id), latitude=float(st.latitude) if st.latitude is not None else None,
            longitude=float(st.longitude) if st.longitude is not None else None,
            readings=s.n if s else 0, first_ts=s.first if s else None, last_ts=s.last if s else None))
    return {"stations": out}


@router.get("/series", response_model=schemas.WeatherSeries)
def series(station_id: int, start: Optional[datetime] = None, end: Optional[datetime] = None,
           max_points: int = Query(2500, ge=100, le=10000), db: Session = Depends(get_db)):
    """Chart-ready series for one station (default: the last 7 days of data)."""
    st = _station(db, station_id)
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")
    data = get_weather_series(db, station_id, start, end, max_points)
    states = data.pop("states")
    timelines = {col: {"states": ["DAYLIGHT", "NIGHT"], "segments": segs} for col, segs in states.items()}
    refs: dict[str, Optional[float]] = {"temp_max_c": None, "temp_min_c": None, "ghi_max_wm2": None}
    if data["end"]:
        r = db.query(func.max(Reading.temp_c), func.min(Reading.temp_c), func.max(Reading.ghi_wm2)).filter(
            Reading.station_id == station_id, Reading.ts >= data["start"], Reading.ts <= data["end"]).one()
        refs = {k: (float(v) if v is not None else None) for k, v in zip(refs, r)}
    return schemas.WeatherSeries(station_id=station_id, station_code=st.station_code, timelines=timelines, refs=refs,
                                 **data)


@router.get("", response_model=schemas.WeatherActualPage)
def list_readings(station_id: Optional[int] = None, start: Optional[datetime] = None, end: Optional[datetime] = None,
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=3000), db: Session = Depends(get_db)):
    query = db.query(Reading, Station.station_code).join(Station, Station.station_id == Reading.station_id)
    if station_id:
        query = query.filter(Reading.station_id == station_id)
    if start:
        query = query.filter(Reading.ts >= start)
    if end:
        query = query.filter(Reading.ts <= end)
    total = query.count()
    rows = query.order_by(Reading.ts.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.WeatherActualPage(items=[_out(r, c) for r, c in rows], total=total, page=page, page_size=page_size)


@router.get("/{station_id}/{ts}", response_model=schemas.WeatherActualOut)
def get_reading(station_id: int, ts: datetime, db: Session = Depends(get_db)):
    st = _station(db, station_id)
    return _out(_get(db, station_id, ts), st.station_code)


@router.post("", response_model=schemas.WeatherActualOut, status_code=201)
def add_reading(payload: schemas.WeatherActualCreate, db: Session = Depends(get_db)):
    """Add a reading; one that already exists for the station and time is refused (edit it instead)."""
    st = _station(db, payload.station_id)
    if db.get(Reading, (payload.station_id, payload.ts)):
        raise HTTPException(status_code=409, detail="A reading already exists for this station and time")
    row = Reading(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row, st.station_code)


@router.put("/{station_id}/{ts}", response_model=schemas.WeatherActualOut)
def update_reading(station_id: int, ts: datetime, payload: schemas.WeatherActualUpdate, db: Session = Depends(get_db)):
    st = _station(db, station_id)
    row = _get(db, station_id, ts)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, st.station_code)


@router.delete("/{station_id}/{ts}", status_code=204)
def delete_reading(station_id: int, ts: datetime, db: Session = Depends(get_db)):
    db.delete(_get(db, station_id, ts))
    db.commit()
    return None


@router.post("/bulk", response_model=schemas.BulkWeatherResult)
async def bulk_load(file: UploadFile = File(...), station_code: Optional[str] = Form(None), db: Session = Depends(get_db)):
    """Load a .csv / .xlsx: the station comes from the file's station_code column, or the one chosen for files
    without it. Existing (station, ts) readings are updated."""
    default_id = None
    if station_code:
        st = db.query(Station).filter(func.upper(Station.station_code) == station_code.strip().upper()).first()
        if not st:
            raise HTTPException(status_code=400, detail=f"Unknown weather station '{station_code}'")
        default_id = st.station_id
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        valid, errors, total, ignored, codes = parse_weather_file(file.filename or "upload", content, db, default_id)
    except WeatherImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    inserted, updated = upsert_weather_rows(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, schemas.BulkWeatherRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    return schemas.BulkWeatherResult(filename=file.filename or "upload", total_rows=total, valid_rows=len(valid),
                                     inserted=inserted, updated=updated, error_count=n_errors, errors=errors[:200],
                                     stations=codes)
