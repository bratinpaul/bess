from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.hvac_telemetry_daily import (
    get_hvac_daily_aggregates,
    get_hvac_latest,
    get_hvac_telemetry_date_range,
)

router = APIRouter(prefix="/api/hvac-analytics", tags=["hvac-analytics"])


@router.get("/telemetry-date-range", response_model=schemas.HvacTelemetryDateRange)
def telemetry_date_range(hvac_id: int, db: Session = Depends(get_db)):
    return get_hvac_telemetry_date_range(db, hvac_id)


@router.get("/daily-summary", response_model=schemas.HvacDailySummary)
def daily_summary(hvac_id: int, date: date, db: Session = Depends(get_db)):
    unit = db.get(models.HvacUnit, hvac_id)
    if not unit:
        raise HTTPException(status_code=404, detail="HVAC unit not found")

    rows = get_hvac_daily_aggregates(db, hvac_id, date, date)
    if not rows:
        raise HTTPException(status_code=404, detail="No HVAC telemetry data for this unit on this date")

    row = rows[0]
    return schemas.HvacDailySummary(hvac_id=hvac_id, hvac_code=unit.hvac_code, date=row["day"], **_without(row))


@router.get("/daily-series", response_model=list[schemas.HvacDailySummary])
def daily_series(hvac_id: int, start: date, end: date, db: Session = Depends(get_db)):
    unit = db.get(models.HvacUnit, hvac_id)
    if not unit:
        raise HTTPException(status_code=404, detail="HVAC unit not found")
    if start > end:
        raise HTTPException(status_code=400, detail="start date must not be after end date")

    rows = get_hvac_daily_aggregates(db, hvac_id, start, end)
    return [
        schemas.HvacDailySummary(hvac_id=hvac_id, hvac_code=unit.hvac_code, date=row["day"], **_without(row))
        for row in rows
    ]


@router.get("/latest", response_model=schemas.HvacLatestReading)
def latest(hvac_id: int, db: Session = Depends(get_db)):
    unit = db.get(models.HvacUnit, hvac_id)
    if not unit:
        raise HTTPException(status_code=404, detail="HVAC unit not found")

    row = get_hvac_latest(db, hvac_id)
    if not row:
        raise HTTPException(status_code=404, detail="No HVAC telemetry data for this unit")
    return schemas.HvacLatestReading(**row)


def _without(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "day"}
