from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.telemetry_series import get_series
from app.services.telemetry_import import parse_telemetry_file, upsert_telemetry_rows

router = APIRouter(prefix="/api/system-telemetry", tags=["system-telemetry"])


def _to_out(row: models.SystemTelemetry, system_name: Optional[str]) -> schemas.SystemTelemetryOut:
    data = {c.name: getattr(row, c.name) for c in models.SystemTelemetry.__table__.columns}
    data["system_name"] = system_name
    return schemas.SystemTelemetryOut.model_validate(data)


@router.get("/lookups")
def get_lookups(db: Session = Depends(get_db)):
    return {
        "modes": [m.mode_code for m in db.query(models.OperatingMode).order_by(models.OperatingMode.mode_code).all()],
        "contactor_states": [
            c.state_code for c in db.query(models.ContactorState).order_by(models.ContactorState.state_code).all()
        ],
    }


@router.get("/series", response_model=schemas.SystemTelemetrySeries)
def get_telemetry_series(
    system_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    max_points: int = Query(2500, ge=100, le=10000),
    db: Session = Depends(get_db),
):
    """Chart-ready series for one system; defaults to the last 7 days of data."""
    system = db.get(models.BatterySystem, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="Battery system not found")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")

    series = get_series(db, system_id, start, end, max_points)
    states = [c.state_code for c in db.query(models.ContactorState).order_by(models.ContactorState.state_code).all()]
    return schemas.SystemTelemetrySeries(
        system_id=system_id,
        system_name=system.system_name,
        contactor_states=states,
        **series,
    )


@router.get("", response_model=schemas.SystemTelemetryPage)
def list_telemetry(
    system_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=3000),
    db: Session = Depends(get_db),
):
    query = db.query(models.SystemTelemetry, models.BatterySystem.system_name).join(
        models.BatterySystem, models.SystemTelemetry.system_id == models.BatterySystem.battery_system_id
    )
    if system_id:
        query = query.filter(models.SystemTelemetry.system_id == system_id)
    if start:
        query = query.filter(models.SystemTelemetry.ts >= start)
    if end:
        query = query.filter(models.SystemTelemetry.ts <= end)

    total = query.count()
    rows = (
        query.order_by(models.SystemTelemetry.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_out(row, name) for row, name in rows]
    return schemas.SystemTelemetryPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=schemas.SystemTelemetryOut, status_code=201)
def add_telemetry(payload: schemas.SystemTelemetryCreate, db: Session = Depends(get_db)):
    system = db.get(models.BatterySystem, payload.system_id)
    if not system:
        raise HTTPException(status_code=400, detail="Battery system not found")
    if payload.mode_code and not db.get(models.OperatingMode, payload.mode_code):
        raise HTTPException(status_code=400, detail=f"Unknown Mode '{payload.mode_code}'")
    if payload.contactor_state and not db.get(models.ContactorState, payload.contactor_state):
        raise HTTPException(status_code=400, detail=f"Unknown Contactor_Status '{payload.contactor_state}'")

    upsert_telemetry_rows(db, [payload])
    db.commit()

    row = db.get(models.SystemTelemetry, (payload.system_id, payload.ts))
    return _to_out(row, system.system_name)


@router.post("/bulk", response_model=schemas.BulkTelemetryResult)
async def bulk_add_telemetry(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    valid_rows, row_errors, total_rows = parse_telemetry_file(file.filename or "upload", content, db)

    inserted, updated = upsert_telemetry_rows(db, valid_rows)
    db.commit()

    return schemas.BulkTelemetryResult(
        filename=file.filename or "upload",
        total_rows=total_rows,
        valid_rows=len(valid_rows),
        inserted=inserted,
        updated=updated,
        error_count=len(row_errors),
        errors=row_errors[:200],
    )
