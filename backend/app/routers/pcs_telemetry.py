from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.pcs_telemetry_series import get_pcs_series
from app.services.pcs_telemetry_import import (
    PcsTelemetryImportError,
    parse_pcs_telemetry_file,
    upsert_pcs_telemetry_rows,
)

router = APIRouter(prefix="/api/pcs-telemetry", tags=["pcs-telemetry"])


def _to_out(row: models.PcsTelemetry, pcs_code: Optional[str]) -> schemas.PcsTelemetryOut:
    data = {c.name: getattr(row, c.name) for c in models.PcsTelemetry.__table__.columns}
    data["pcs_code"] = pcs_code
    return schemas.PcsTelemetryOut.model_validate(data)


@router.get("/lookups")
def get_lookups(db: Session = Depends(get_db)):
    return {
        "modes": [m.mode_code for m in db.query(models.PcsMode).order_by(models.PcsMode.mode_code).all()],
        "grid_services": [
            g.service_code for g in db.query(models.PcsGridService).order_by(models.PcsGridService.service_code).all()
        ],
        "breaker_states": [
            b.state_code for b in db.query(models.PcsBreakerState).order_by(models.PcsBreakerState.state_code).all()
        ],
    }


@router.get("/series", response_model=schemas.PcsTelemetrySeries)
def get_pcs_telemetry_series(
    pcs_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    max_points: int = Query(2500, ge=100, le=10000),
    db: Session = Depends(get_db),
):
    """Chart-ready series for one PCS; defaults to the last 7 days of data."""
    pcs = db.get(models.Pcs, pcs_id)
    if not pcs:
        raise HTTPException(status_code=404, detail="PCS not found")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")

    series = get_pcs_series(db, pcs_id, start, end, max_points)
    known_states = {
        "breaker_state": [b.state_code for b in db.query(models.PcsBreakerState).order_by(models.PcsBreakerState.state_code)],
        "mode_code": [m.mode_code for m in db.query(models.PcsMode).order_by(models.PcsMode.mode_code)],
        "grid_service": [g.service_code for g in db.query(models.PcsGridService).order_by(models.PcsGridService.service_code)],
    }
    timelines = {
        col: {"states": known_states[col], "segments": segments}
        for col, segments in series.pop("states").items()
    }
    return schemas.PcsTelemetrySeries(
        pcs_id=pcs_id,
        pcs_code=pcs.pcs_code,
        timelines=timelines,
        min_power_factor=float(pcs.min_power_factor) if pcs.min_power_factor is not None else None,
        rated_apparent_kva=float(pcs.rated_apparent_kva) if pcs.rated_apparent_kva is not None else None,
        **series,
    )


@router.get("", response_model=schemas.PcsTelemetryPage)
def list_pcs_telemetry(
    pcs_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=3000),
    db: Session = Depends(get_db),
):
    query = db.query(models.PcsTelemetry, models.Pcs.pcs_code).join(
        models.Pcs, models.PcsTelemetry.pcs_id == models.Pcs.pcs_id
    )
    if pcs_id:
        query = query.filter(models.PcsTelemetry.pcs_id == pcs_id)
    if start:
        query = query.filter(models.PcsTelemetry.ts >= start)
    if end:
        query = query.filter(models.PcsTelemetry.ts <= end)

    total = query.count()
    rows = (
        query.order_by(models.PcsTelemetry.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_out(row, code) for row, code in rows]
    return schemas.PcsTelemetryPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=schemas.PcsTelemetryOut, status_code=201)
def add_pcs_telemetry(payload: schemas.PcsTelemetryCreate, db: Session = Depends(get_db)):
    pcs = db.get(models.Pcs, payload.pcs_id)
    if not pcs:
        raise HTTPException(status_code=400, detail="PCS not found")
    if payload.mode_code and not db.get(models.PcsMode, payload.mode_code):
        raise HTTPException(status_code=400, detail=f"Unknown mode_code '{payload.mode_code}'")
    if payload.grid_service and not db.get(models.PcsGridService, payload.grid_service):
        raise HTTPException(status_code=400, detail=f"Unknown grid_service '{payload.grid_service}'")
    if payload.breaker_state and not db.get(models.PcsBreakerState, payload.breaker_state):
        raise HTTPException(status_code=400, detail=f"Unknown breaker_state '{payload.breaker_state}'")

    upsert_pcs_telemetry_rows(db, [payload])
    db.commit()

    row = db.get(models.PcsTelemetry, (payload.pcs_id, payload.ts))
    return _to_out(row, pcs.pcs_code)


@router.post("/bulk", response_model=schemas.BulkPcsTelemetryResult)
async def bulk_add_pcs_telemetry(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        valid_rows, row_errors, total_rows = parse_pcs_telemetry_file(file.filename or "upload", content, db)
    except PcsTelemetryImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    inserted, updated = upsert_pcs_telemetry_rows(db, valid_rows)
    db.commit()

    return schemas.BulkPcsTelemetryResult(
        filename=file.filename or "upload",
        total_rows=total_rows,
        valid_rows=len(valid_rows),
        inserted=inserted,
        updated=updated,
        error_count=len(row_errors),
        errors=row_errors[:200],
    )
