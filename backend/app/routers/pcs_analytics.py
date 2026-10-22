from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.pcs_telemetry_daily import get_pcs_daily_aggregates, get_pcs_telemetry_date_range

router = APIRouter(prefix="/api/pcs-analytics", tags=["pcs-analytics"])


@router.get("/telemetry-date-range", response_model=schemas.PcsTelemetryDateRange)
def telemetry_date_range(pcs_id: int, db: Session = Depends(get_db)):
    return get_pcs_telemetry_date_range(db, pcs_id)


@router.get("/daily-summary", response_model=schemas.PcsDailySummary)
def daily_summary(pcs_id: int, date: date, db: Session = Depends(get_db)):
    pcs = db.get(models.Pcs, pcs_id)
    if not pcs:
        raise HTTPException(status_code=404, detail="PCS not found")

    rows = get_pcs_daily_aggregates(db, pcs_id, date, date)
    if not rows:
        raise HTTPException(status_code=404, detail="No PCS telemetry data for this unit on this date")

    row = rows[0]
    return schemas.PcsDailySummary(pcs_id=pcs_id, pcs_code=pcs.pcs_code, date=row["day"], **_without(row))


@router.get("/daily-series", response_model=list[schemas.PcsDailySummary])
def daily_series(pcs_id: int, start: date, end: date, db: Session = Depends(get_db)):
    pcs = db.get(models.Pcs, pcs_id)
    if not pcs:
        raise HTTPException(status_code=404, detail="PCS not found")
    if start > end:
        raise HTTPException(status_code=400, detail="start date must not be after end date")

    rows = get_pcs_daily_aggregates(db, pcs_id, start, end)
    return [
        schemas.PcsDailySummary(pcs_id=pcs_id, pcs_code=pcs.pcs_code, date=row["day"], **_without(row))
        for row in rows
    ]


def _without(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "day"}
