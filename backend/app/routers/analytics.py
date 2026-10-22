from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.telemetry_daily import get_daily_aggregates, get_telemetry_date_range

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/telemetry-date-range", response_model=schemas.TelemetryDateRange)
def telemetry_date_range(system_id: int, db: Session = Depends(get_db)):
    return get_telemetry_date_range(db, system_id)


@router.get("/daily-summary", response_model=schemas.DailySummary)
def daily_summary(system_id: int, date: date, db: Session = Depends(get_db)):
    system = db.get(models.BatterySystem, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="Battery system not found")

    rows = get_daily_aggregates(db, system_id, date, date)
    if not rows:
        raise HTTPException(status_code=404, detail="No telemetry data for this system on this date")

    row = rows[0]
    return schemas.DailySummary(system_id=system_id, system_name=system.system_name, date=row["day"], **_without(row))


@router.get("/daily-series", response_model=list[schemas.DailySummary])
def daily_series(system_id: int, start: date, end: date, db: Session = Depends(get_db)):
    system = db.get(models.BatterySystem, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="Battery system not found")
    if start > end:
        raise HTTPException(status_code=400, detail="start date must not be after end date")

    rows = get_daily_aggregates(db, system_id, start, end)
    return [
        schemas.DailySummary(system_id=system_id, system_name=system.system_name, date=row["day"], **_without(row))
        for row in rows
    ]


def _without(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "day"}
