from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.ems_telemetry_daily import get_ems_daily_aggregates, get_ems_telemetry_date_range

router = APIRouter(prefix="/api/ems-analytics", tags=["ems-analytics"])


@router.get("/telemetry-date-range", response_model=schemas.EmsTelemetryDateRange)
def telemetry_date_range(ems_id: int, db: Session = Depends(get_db)):
    return get_ems_telemetry_date_range(db, ems_id)


@router.get("/daily-summary", response_model=schemas.EmsDailySummary)
def daily_summary(ems_id: int, date: date, db: Session = Depends(get_db)):
    controller = db.get(models.EmsController, ems_id)
    if not controller:
        raise HTTPException(status_code=404, detail="EMS controller not found")

    rows = get_ems_daily_aggregates(db, ems_id, date, date)
    if not rows:
        raise HTTPException(status_code=404, detail="No EMS telemetry data for this controller on this date")

    row = rows[0]
    return schemas.EmsDailySummary(ems_id=ems_id, ems_code=controller.ems_code, date=row["day"], **_without(row))


@router.get("/daily-series", response_model=list[schemas.EmsDailySummary])
def daily_series(ems_id: int, start: date, end: date, db: Session = Depends(get_db)):
    controller = db.get(models.EmsController, ems_id)
    if not controller:
        raise HTTPException(status_code=404, detail="EMS controller not found")
    if start > end:
        raise HTTPException(status_code=400, detail="start date must not be after end date")

    rows = get_ems_daily_aggregates(db, ems_id, start, end)
    return [
        schemas.EmsDailySummary(ems_id=ems_id, ems_code=controller.ems_code, date=row["day"], **_without(row))
        for row in rows
    ]


def _without(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "day"}
