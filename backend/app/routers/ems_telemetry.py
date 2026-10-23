from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.ems_telemetry_series import get_ems_series
from app.services.ems_telemetry_import import parse_ems_telemetry_file, upsert_ems_telemetry_rows

router = APIRouter(prefix="/api/ems-telemetry", tags=["ems-telemetry"])


def _to_out(row: models.EmsTelemetry, ems_code: Optional[str]) -> schemas.EmsTelemetryOut:
    data = {c.name: getattr(row, c.name) for c in models.EmsTelemetry.__table__.columns}
    data["ems_code"] = ems_code
    return schemas.EmsTelemetryOut.model_validate(data)


@router.get("/lookups")
def get_lookups(db: Session = Depends(get_db)):
    return {
        "controllers": [
            {"ems_id": c.ems_id, "ems_code": c.ems_code}
            for c in db.query(models.EmsController).order_by(models.EmsController.ems_code).all()
        ],
        "dispatch_modes": [
            m.mode_code for m in db.query(models.EmsDispatchMode).order_by(models.EmsDispatchMode.mode_code).all()
        ],
        "grid_services": [
            g.service_code for g in db.query(models.EmsGridService).order_by(models.EmsGridService.service_code).all()
        ],
    }


@router.get("/series", response_model=schemas.EmsTelemetrySeries)
def get_ems_telemetry_series(
    ems_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    max_points: int = Query(2500, ge=100, le=10000),
    db: Session = Depends(get_db),
):
    """Chart-ready series for one EMS controller; defaults to the last 7 days of data."""
    controller = db.get(models.EmsController, ems_id)
    if not controller:
        raise HTTPException(status_code=404, detail="EMS controller not found")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")

    series = get_ems_series(db, ems_id, start, end, max_points)
    known_states = {
        "dispatch_mode": [m.mode_code for m in db.query(models.EmsDispatchMode).order_by(models.EmsDispatchMode.mode_code)],
        "grid_service": [g.service_code for g in db.query(models.EmsGridService).order_by(models.EmsGridService.service_code)],
    }
    timelines = {
        col: {"states": known_states[col], "segments": segments} for col, segments in series.pop("states").items()
    }
    return schemas.EmsTelemetrySeries(ems_id=ems_id, ems_code=controller.ems_code, timelines=timelines, **series)


@router.get("", response_model=schemas.EmsTelemetryPage)
def list_ems_telemetry(
    ems_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=3000),
    db: Session = Depends(get_db),
):
    query = db.query(models.EmsTelemetry, models.EmsController.ems_code).join(
        models.EmsController, models.EmsTelemetry.ems_id == models.EmsController.ems_id
    )
    if ems_id:
        query = query.filter(models.EmsTelemetry.ems_id == ems_id)
    if start:
        query = query.filter(models.EmsTelemetry.ts >= start)
    if end:
        query = query.filter(models.EmsTelemetry.ts <= end)

    total = query.count()
    rows = (
        query.order_by(models.EmsTelemetry.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_out(row, code) for row, code in rows]
    return schemas.EmsTelemetryPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=schemas.EmsTelemetryOut, status_code=201)
def add_ems_telemetry(payload: schemas.EmsTelemetryCreate, db: Session = Depends(get_db)):
    controller = db.get(models.EmsController, payload.ems_id)
    if not controller:
        raise HTTPException(status_code=400, detail="EMS controller not found")
    if payload.dispatch_mode and not db.get(models.EmsDispatchMode, payload.dispatch_mode):
        raise HTTPException(status_code=400, detail=f"Unknown dispatch_mode '{payload.dispatch_mode}'")
    if payload.grid_service and not db.get(models.EmsGridService, payload.grid_service):
        raise HTTPException(status_code=400, detail=f"Unknown grid_service '{payload.grid_service}'")

    upsert_ems_telemetry_rows(db, [payload])
    db.commit()

    row = db.get(models.EmsTelemetry, (payload.ems_id, payload.ts))
    return _to_out(row, controller.ems_code)


@router.post("/bulk", response_model=schemas.BulkEmsTelemetryResult)
async def bulk_add_ems_telemetry(
    file: UploadFile = File(...), ems_code: str = Form(...), db: Session = Depends(get_db)
):
    controller = db.query(models.EmsController).filter(models.EmsController.ems_code == ems_code).first()
    if not controller:
        raise HTTPException(status_code=400, detail=f"Unknown EMS controller '{ems_code}'")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    valid_rows, row_errors, total_rows = parse_ems_telemetry_file(
        file.filename or "upload", content, db, controller.ems_id
    )

    inserted, updated = upsert_ems_telemetry_rows(db, valid_rows)
    db.commit()

    return schemas.BulkEmsTelemetryResult(
        filename=file.filename or "upload",
        ems_code=ems_code,
        total_rows=total_rows,
        valid_rows=len(valid_rows),
        inserted=inserted,
        updated=updated,
        error_count=len(row_errors),
        errors=row_errors[:200],
    )
