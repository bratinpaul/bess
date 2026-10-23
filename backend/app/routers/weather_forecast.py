"""Weather forecasts (battery_telemetry.weather_forecast): list / filter, read, add, edit, delete, bulk load, chart
series (forecast vs measured weather) and forecast skill by lead time.

A forecast run is issued at issued_at and gives temp_c / ghi_wm2 for each valid_at hour ahead. The measured value a
forecast is compared with is the mean of the 5-min weather_actual readings within ±30 min of valid_at.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.weather_forecast_import import parse_forecast_file, upsert_forecast_rows

router = APIRouter(prefix="/api/weather-forecast", tags=["weather-forecast"])

Forecast = models.WeatherForecast
Station = models.WeatherStation

# measured weather around a valid hour (alias f = forecast row with valid_at, station_id)
ACTUAL_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT avg(wa.temp_c)::float AS actual_temp_c, avg(wa.ghi_wm2)::float AS actual_ghi_wm2, count(*) AS n_actual
        FROM battery_telemetry.weather_actual wa
        WHERE wa.station_id = f.station_id
          AND wa.ts >= f.valid_at - interval '30 minutes' AND wa.ts < f.valid_at + interval '30 minutes'
    ) a ON true"""
DAYTIME_GHI = 5.0  # W/m²: GHI errors are scored on daylight hours only (night is 0 = 0)


def _num(v) -> Optional[float]:
    return None if v is None else float(v)


def _station(db: Session, station_id: int) -> Station:
    st = db.get(Station, station_id)
    if not st:
        raise HTTPException(status_code=404, detail=f"Weather station {station_id} not found")
    return st


def _get(db: Session, station_id: int, issued_at: datetime, valid_at: datetime) -> Forecast:
    row = db.get(Forecast, (station_id, issued_at, valid_at))
    if not row:
        raise HTTPException(status_code=404, detail="Forecast value not found")
    return row


def _out_rows(db: Session, where: str, params: dict, order: str = "", limit: str = "") -> list[schemas.WeatherForecastOut]:
    rows = db.execute(text(f"""
        SELECT f.station_id, f.issued_at, f.valid_at, s.station_code, f.temp_c, f.ghi_wm2,
               extract(epoch FROM f.valid_at - f.issued_at) / 3600.0 AS lead_h, a.actual_temp_c, a.actual_ghi_wm2
        FROM battery_telemetry.weather_forecast f
        JOIN battery_master.weather_station s ON s.station_id = f.station_id
        {ACTUAL_LATERAL}
        WHERE {where} {order} {limit}"""), params).mappings().all()
    out = []
    for r in rows:
        t, g = _num(r["temp_c"]), _num(r["ghi_wm2"])
        at, ag = r["actual_temp_c"], r["actual_ghi_wm2"]
        out.append(schemas.WeatherForecastOut(
            station_id=r["station_id"], issued_at=r["issued_at"], valid_at=r["valid_at"], station_code=r["station_code"],
            lead_h=round(float(r["lead_h"]), 2), temp_c=r["temp_c"], ghi_wm2=r["ghi_wm2"],
            actual_temp_c=round(at, 2) if at is not None else None,
            actual_ghi_wm2=round(ag, 1) if ag is not None else None,
            temp_error_c=round(t - at, 2) if t is not None and at is not None else None,
            ghi_error_wm2=round(g - ag, 1) if g is not None and ag is not None else None))
    return out


def _one(db: Session, station_id: int, issued_at: datetime, valid_at: datetime) -> schemas.WeatherForecastOut:
    rows = _out_rows(db, "f.station_id = :s AND f.issued_at = :i AND f.valid_at = :v",
                     {"s": station_id, "i": issued_at, "v": valid_at})
    if not rows:
        raise HTTPException(status_code=404, detail="Forecast value not found")
    return rows[0]


@router.get("/lookups")
def lookups(db: Session = Depends(get_db)):
    """Weather stations, and the forecast runs each one holds (newest first)."""
    sites = {s.site_id: s.site_name for s in db.query(models.Site)}
    stations = [schemas.WeatherStationOut(
        station_id=st.station_id, station_code=st.station_code, provider=st.provider, site_id=st.site_id,
        site_name=sites.get(st.site_id), latitude=_num(st.latitude), longitude=_num(st.longitude))
        for st in db.query(Station).order_by(Station.station_code)]
    runs = [schemas.ForecastRunOut(station_id=r.station_id, issued_at=r.issued_at, points=r.n, first_valid=r.first,
                                   last_valid=r.last)
            for r in db.query(Forecast.station_id, Forecast.issued_at, func.count().label("n"),
                              func.min(Forecast.valid_at).label("first"), func.max(Forecast.valid_at).label("last"))
            .group_by(Forecast.station_id, Forecast.issued_at).order_by(Forecast.issued_at.desc())]
    return {"stations": stations, "runs": runs}


@router.get("/series", response_model=schemas.WeatherForecastSeries)
def series(station_id: int, issued_at: Optional[datetime] = None, start: Optional[datetime] = None,
           end: Optional[datetime] = None, db: Session = Depends(get_db)):
    """Hourly forecast vs measured weather. Without issued_at each hour uses the latest run that covers it (what an
    operator would have seen); with issued_at only that run is shown (default: its whole window). The band columns
    are the spread of every run's value for the same hour."""
    st = _station(db, station_id)
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")
    if issued_at is not None:
        bounds = db.query(func.min(Forecast.valid_at), func.max(Forecast.valid_at)).filter(
            Forecast.station_id == station_id, Forecast.issued_at == issued_at).one()
        if bounds[0] is None:
            raise HTTPException(status_code=404, detail="No forecast run was issued at that time for this station")
        start, end = start or bounds[0], end or bounds[1]
    else:
        last = db.query(func.max(Forecast.valid_at)).filter(Forecast.station_id == station_id).scalar()
        end = end or last
        start = start or (end - timedelta(days=7) if end else None)

    timelines = {"horizon": {"states": ["LEAD_0-6H", "LEAD_6-24H", "LEAD_24H+"], "segments": []},
                 "actuals": {"states": ["MEASURED", "NO_MEASUREMENT"], "segments": []}}
    empty = schemas.WeatherForecastSeries(station_id=station_id, station_code=st.station_code, issued_at=issued_at,
                                          start=start, end=end, points=[], timelines=timelines)
    if start is None:
        return empty
    pick = "f.issued_at = :run" if issued_at is not None else "f.rn = 1"
    rows = db.execute(text(f"""
        WITH f AS (
            SELECT station_id, valid_at, issued_at, temp_c::float AS temp_c, ghi_wm2::float AS ghi_wm2,
                   row_number() OVER w2 AS rn,
                   min(temp_c) OVER w AS temp_fc_min, max(temp_c) OVER w AS temp_fc_max,
                   min(ghi_wm2) OVER w AS ghi_fc_min, max(ghi_wm2) OVER w AS ghi_fc_max, count(*) OVER w AS runs
            FROM battery_telemetry.weather_forecast
            WHERE station_id = :sid AND valid_at >= :start AND valid_at <= :end
            WINDOW w AS (PARTITION BY valid_at), w2 AS (PARTITION BY valid_at ORDER BY issued_at DESC)
        )
        SELECT f.*, extract(epoch FROM f.valid_at - f.issued_at) / 3600.0 AS lead_h, a.*
        FROM f {ACTUAL_LATERAL}
        WHERE {pick}
        ORDER BY f.valid_at"""), {"sid": station_id, "start": start, "end": end, "run": issued_at}).mappings().all()
    if not rows:
        return empty

    points, horizon, actual = [], [], []
    errs_t, errs_g = [], []
    for r in rows:
        t, g, at, ag = r["temp_c"], r["ghi_wm2"], r["actual_temp_c"], r["actual_ghi_wm2"]
        te = t - at if t is not None and at is not None else None
        ge = g - ag if g is not None and ag is not None else None
        if te is not None:
            errs_t.append(abs(te))
        if ge is not None and max(g, ag) > DAYTIME_GHI:
            errs_g.append(abs(ge))
        lead = float(r["lead_h"])
        points.append({
            "ts": r["valid_at"].isoformat(), "temp_fc_c": t, "temp_fc_min_c": _num(r["temp_fc_min"]),
            "temp_fc_max_c": _num(r["temp_fc_max"]), "temp_actual_c": at, "ghi_fc_wm2": g,
            "ghi_fc_min_wm2": _num(r["ghi_fc_min"]), "ghi_fc_max_wm2": _num(r["ghi_fc_max"]), "ghi_actual_wm2": ag,
            "temp_error_c": te, "ghi_error_wm2": ge, "lead_h": round(lead, 2), "runs": r["runs"]})
        horizon.append((r["valid_at"], "LEAD_0-6H" if lead <= 6 else "LEAD_6-24H" if lead <= 24 else "LEAD_24H+"))
        actual.append((r["valid_at"], "MEASURED" if r["n_actual"] else "NO_MEASUREMENT"))

    def segments(states):
        segs = []
        for ts, state in states:
            stop = ts + timedelta(hours=1)
            if segs and segs[-1]["state"] == state and segs[-1]["end"] >= ts:
                segs[-1]["end"] = stop
            else:
                segs.append({"state": state, "start": ts, "end": stop})
        return segs

    timelines["horizon"]["segments"] = segments(horizon)
    timelines["actuals"]["segments"] = segments(actual)
    refs = {"temp_mae": round(sum(errs_t) / len(errs_t), 2) if errs_t else None,
            "ghi_mae": round(sum(errs_g) / len(errs_g), 1) if errs_g else None}
    return schemas.WeatherForecastSeries(
        station_id=station_id, station_code=st.station_code, issued_at=issued_at, start=rows[0]["valid_at"],
        end=rows[-1]["valid_at"], points=points, timelines=timelines, refs=refs)


@router.get("/skill", response_model=schemas.WeatherForecastSkill)
def skill(station_id: int, start: Optional[datetime] = None, end: Optional[datetime] = None,
          db: Session = Depends(get_db)):
    """Forecast accuracy against measured weather, overall and by lead hour (valid_at within start..end).
    GHI is scored on daylight hours only."""
    _station(db, station_id)
    cond = ["f.station_id = :sid"]
    if start:
        cond.append("f.valid_at >= :start")
    if end:
        cond.append("f.valid_at <= :end")
    params = {"sid": station_id, "start": start, "end": end, "day": DAYTIME_GHI}
    base = f"""
        WITH m AS (
            SELECT round(extract(epoch FROM f.valid_at - f.issued_at) / 3600.0)::int AS lead_h,
                   f.temp_c::float - a.actual_temp_c AS te, f.ghi_wm2::float - a.actual_ghi_wm2 AS ge,
                   greatest(f.ghi_wm2::float, a.actual_ghi_wm2) > :day AS day
            FROM battery_telemetry.weather_forecast f {ACTUAL_LATERAL}
            WHERE {' AND '.join(cond)} AND a.n_actual > 0
        )"""
    agg = """count(*) AS n, avg(abs(te)) AS temp_mae, avg(te) AS temp_bias, sqrt(avg(te * te)) AS temp_rmse,
             count(*) FILTER (WHERE day AND ge IS NOT NULL) AS ghi_n,
             avg(abs(ge)) FILTER (WHERE day) AS ghi_mae, avg(ge) FILTER (WHERE day) AS ghi_bias,
             sqrt(avg(ge * ge) FILTER (WHERE day)) AS ghi_rmse"""
    overall = db.execute(text(f"{base} SELECT {agg} FROM m"), params).mappings().one()
    by_lead = db.execute(text(f"{base} SELECT lead_h, {agg} FROM m GROUP BY lead_h ORDER BY lead_h"), params).mappings().all()
    counts = db.execute(text(f"""SELECT count(*) AS n, count(DISTINCT issued_at) AS runs
                                 FROM battery_telemetry.weather_forecast f WHERE {' AND '.join(cond)}"""),
                        params).mappings().one()
    r2 = lambda v, d=2: None if v is None else round(float(v), d)  # noqa: E731
    return schemas.WeatherForecastSkill(
        station_id=station_id, runs=counts["runs"], forecasts=counts["n"], matched=overall["n"],
        temp_mae=r2(overall["temp_mae"]), temp_bias=r2(overall["temp_bias"]), temp_rmse=r2(overall["temp_rmse"]),
        ghi_mae=r2(overall["ghi_mae"], 1), ghi_bias=r2(overall["ghi_bias"], 1), ghi_rmse=r2(overall["ghi_rmse"], 1),
        by_lead=[schemas.LeadSkill(lead_h=r["lead_h"], n=r["n"], temp_mae=r2(r["temp_mae"]), temp_bias=r2(r["temp_bias"]),
                                   ghi_mae=r2(r["ghi_mae"], 1), ghi_bias=r2(r["ghi_bias"], 1), ghi_n=r["ghi_n"])
                 for r in by_lead])


@router.get("", response_model=schemas.WeatherForecastPage)
def list_forecasts(station_id: Optional[int] = None, issued_at: Optional[datetime] = None,
                   start: Optional[datetime] = None, end: Optional[datetime] = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=3000), db: Session = Depends(get_db)):
    """Forecast values, newest run first; start / end filter on valid_at, issued_at picks one run."""
    cond, params = ["true"], {}
    for col, key, val, op in (("f.station_id", "s", station_id, "="), ("f.issued_at", "i", issued_at, "="),
                              ("f.valid_at", "a", start, ">="), ("f.valid_at", "b", end, "<=")):
        if val is not None:
            cond.append(f"{col} {op} :{key}")
            params[key] = val
    where = " AND ".join(cond)
    total = db.execute(text(f"SELECT count(*) FROM battery_telemetry.weather_forecast f WHERE {where}"), params).scalar()
    params.update(lim=page_size, off=(page - 1) * page_size)
    items = _out_rows(db, where, params, "ORDER BY f.issued_at DESC, f.valid_at", "LIMIT :lim OFFSET :off")
    return schemas.WeatherForecastPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{station_id}/{issued_at}/{valid_at}", response_model=schemas.WeatherForecastOut)
def get_forecast(station_id: int, issued_at: datetime, valid_at: datetime, db: Session = Depends(get_db)):
    return _one(db, station_id, issued_at, valid_at)


@router.post("", response_model=schemas.WeatherForecastOut, status_code=201)
def add_forecast(payload: schemas.WeatherForecastCreate, db: Session = Depends(get_db)):
    """Add one forecast value; one that already exists for the station, run and hour is refused (edit it instead)."""
    _station(db, payload.station_id)
    if db.get(Forecast, (payload.station_id, payload.issued_at, payload.valid_at)):
        raise HTTPException(status_code=409, detail="This run already has a value for that station and hour")
    db.add(Forecast(**payload.model_dump()))
    db.commit()
    return _one(db, payload.station_id, payload.issued_at, payload.valid_at)


@router.put("/{station_id}/{issued_at}/{valid_at}", response_model=schemas.WeatherForecastOut)
def update_forecast(station_id: int, issued_at: datetime, valid_at: datetime, payload: schemas.WeatherForecastUpdate,
                    db: Session = Depends(get_db)):
    row = _get(db, station_id, issued_at, valid_at)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return _one(db, station_id, issued_at, valid_at)


@router.delete("/{station_id}/{issued_at}/{valid_at}", status_code=204)
def delete_forecast(station_id: int, issued_at: datetime, valid_at: datetime, db: Session = Depends(get_db)):
    db.delete(_get(db, station_id, issued_at, valid_at))
    db.commit()
    return None


@router.post("/bulk", response_model=schemas.BulkWeatherForecastResult)
async def bulk_load(file: UploadFile = File(...), station_code: Optional[str] = Form(None), db: Session = Depends(get_db)):
    """Load a .csv / .xlsx of forecast runs: the station comes from the file's station_code column, or the one chosen
    for files without it. Existing (station, issued_at, valid_at) values are updated."""
    default_id = None
    if station_code:
        st = db.query(Station).filter(func.upper(Station.station_code) == station_code.strip().upper()).first()
        if not st:
            raise HTTPException(status_code=400, detail=f"Unknown weather station '{station_code}'")
        default_id = st.station_id
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    valid, errors, total, ignored, codes = parse_forecast_file(file.filename or "upload", content, db, default_id)
    inserted, updated = upsert_forecast_rows(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, schemas.BulkWeatherForecastRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    return schemas.BulkWeatherForecastResult(
        filename=file.filename or "upload", total_rows=total, valid_rows=len(valid), inserted=inserted, updated=updated,
        error_count=n_errors, errors=errors[:200], stations=codes,
        runs=len({(r.station_id, r.issued_at) for r in valid}))
