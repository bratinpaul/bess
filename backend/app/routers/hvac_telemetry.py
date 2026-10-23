from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.hvac_telemetry_series import get_hvac_series
from app.services.hvac_telemetry_import import parse_hvac_telemetry_file, upsert_hvac_telemetry_rows

router = APIRouter(prefix="/api/hvac-telemetry", tags=["hvac-telemetry"])


def _to_out(row: models.HvacTelemetry, hvac_code: Optional[str]) -> schemas.HvacTelemetryOut:
    data = {c.name: getattr(row, c.name) for c in models.HvacTelemetry.__table__.columns}
    data["hvac_code"] = hvac_code
    return schemas.HvacTelemetryOut.model_validate(data)


@router.get("/lookups")
def get_lookups(db: Session = Depends(get_db)):
    return {
        "units": [
            {"hvac_id": u.hvac_id, "hvac_code": u.hvac_code}
            for u in db.query(models.HvacUnit).order_by(models.HvacUnit.hvac_code).all()
        ],
        "cooling_modes": [
            m.mode_code for m in db.query(models.HvacCoolingMode).order_by(models.HvacCoolingMode.mode_code).all()
        ],
    }


@router.get("/series", response_model=schemas.HvacTelemetrySeries)
def get_hvac_telemetry_series(
    hvac_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    max_points: int = Query(2500, ge=100, le=10000),
    db: Session = Depends(get_db),
):
    """Chart-ready series for one HVAC unit; defaults to the last 7 days of data."""
    unit = db.get(models.HvacUnit, hvac_id)
    if not unit:
        raise HTTPException(status_code=404, detail="HVAC unit not found")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")

    series = get_hvac_series(db, hvac_id, start, end, max_points)
    modes = [m.mode_code for m in db.query(models.HvacCoolingMode).order_by(models.HvacCoolingMode.mode_code)]
    timelines = {col: {"states": modes, "segments": segments} for col, segments in series.pop("states").items()}
    # the setpoint is drawn as a reference line: use the latest one in the window
    setpoint_q = db.query(models.HvacTelemetry.coolant_setpoint_c).filter(
        models.HvacTelemetry.hvac_id == hvac_id, models.HvacTelemetry.coolant_setpoint_c.isnot(None)
    )
    if series["end"]:
        setpoint_q = setpoint_q.filter(models.HvacTelemetry.ts <= series["end"])
    setpoint = setpoint_q.order_by(models.HvacTelemetry.ts.desc()).limit(1).scalar()
    return schemas.HvacTelemetrySeries(
        hvac_id=hvac_id,
        hvac_code=unit.hvac_code,
        timelines=timelines,
        coolant_setpoint_c=float(setpoint) if setpoint is not None else None,
        **series,
    )


@router.get("", response_model=schemas.HvacTelemetryPage)
def list_hvac_telemetry(
    hvac_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=3000),
    db: Session = Depends(get_db),
):
    query = db.query(models.HvacTelemetry, models.HvacUnit.hvac_code).join(
        models.HvacUnit, models.HvacTelemetry.hvac_id == models.HvacUnit.hvac_id
    )
    if hvac_id:
        query = query.filter(models.HvacTelemetry.hvac_id == hvac_id)
    if start:
        query = query.filter(models.HvacTelemetry.ts >= start)
    if end:
        query = query.filter(models.HvacTelemetry.ts <= end)

    total = query.count()
    rows = (
        query.order_by(models.HvacTelemetry.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_out(row, code) for row, code in rows]
    return schemas.HvacTelemetryPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=schemas.HvacTelemetryOut, status_code=201)
def add_hvac_telemetry(payload: schemas.HvacTelemetryCreate, db: Session = Depends(get_db)):
    unit = db.get(models.HvacUnit, payload.hvac_id)
    if not unit:
        raise HTTPException(status_code=400, detail="HVAC unit not found")
    if payload.cooling_mode and not db.get(models.HvacCoolingMode, payload.cooling_mode):
        raise HTTPException(status_code=400, detail=f"Unknown cooling_mode '{payload.cooling_mode}'")

    upsert_hvac_telemetry_rows(db, [payload])
    db.commit()

    row = db.get(models.HvacTelemetry, (payload.hvac_id, payload.ts))
    return _to_out(row, unit.hvac_code)


@router.post("/bulk", response_model=schemas.BulkHvacTelemetryResult)
async def bulk_add_hvac_telemetry(
    file: UploadFile = File(...), hvac_code: str = Form(...), db: Session = Depends(get_db)
):
    unit = db.query(models.HvacUnit).filter(models.HvacUnit.hvac_code == hvac_code).first()
    if not unit:
        raise HTTPException(status_code=400, detail=f"Unknown HVAC unit '{hvac_code}'")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    valid_rows, row_errors, total_rows = parse_hvac_telemetry_file(
        file.filename or "upload", content, db, unit.hvac_id
    )

    inserted, updated = upsert_hvac_telemetry_rows(db, valid_rows)
    db.commit()

    return schemas.BulkHvacTelemetryResult(
        filename=file.filename or "upload",
        hvac_code=hvac_code,
        total_rows=total_rows,
        valid_rows=len(valid_rows),
        inserted=inserted,
        updated=updated,
        error_count=len(row_errors),
        errors=row_errors[:200],
    )
