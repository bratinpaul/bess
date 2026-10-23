from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services import module_telemetry_summary
from app.services.module_telemetry_series import get_module_series
from app.services.module_telemetry_import import parse_module_telemetry_file, upsert_module_telemetry_rows

router = APIRouter(prefix="/api/module-telemetry", tags=["module-telemetry"])


def _to_out(row: models.ModuleTelemetry, serial_number: Optional[str]) -> schemas.ModuleTelemetryOut:
    data = {c.name: getattr(row, c.name) for c in models.ModuleTelemetry.__table__.columns}
    data["serial_number"] = serial_number
    if row.cell_v_max_v is not None and row.cell_v_min_v is not None:
        data["imbalance_mv"] = ((row.cell_v_max_v - row.cell_v_min_v) * 1000).quantize(Decimal("0.1"))
    return schemas.ModuleTelemetryOut.model_validate(data)


@router.get("/modules", response_model=list[schemas.ModuleOption])
def list_modules(db: Session = Depends(get_db)):
    """Modules that telemetry can be recorded against, for filter and form dropdowns."""
    rows = (
        db.query(models.BatteryModule.module_id, models.BatteryModule.serial_number, models.BatteryPack.pack_number)
        .join(models.BatteryPack, models.BatteryModule.pack_id == models.BatteryPack.pack_id)
        .order_by(models.BatteryModule.module_id)
        .all()
    )
    return [schemas.ModuleOption(module_id=m, serial_number=s, pack_number=p) for m, s, p in rows]


@router.get("/date-range", response_model=schemas.ModuleTelemetryDateRange)
def get_module_telemetry_date_range(
    pack_id: Optional[int] = None,
    battery_system_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """First and last day with module telemetry (optionally for one pack / battery system)."""
    return module_telemetry_summary.get_date_range(db, pack_id, battery_system_id)


@router.get("/summary", response_model=schemas.ModuleTelemetrySummary)
def get_module_telemetry_summary(
    start_date: date,
    end_date: date,
    pack_id: Optional[int] = None,
    battery_system_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """KPIs, per-module and per-day figures for the Daily Module Summary page.

    pack_id / battery_system_id narrow it to the modules of one pack / battery system.
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")
    return module_telemetry_summary.get_summary(db, start_date, end_date, pack_id, battery_system_id)


@router.get("/series", response_model=schemas.ModuleTelemetrySeries)
def get_module_telemetry_series(
    module_id: int,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    max_points: int = Query(2500, ge=100, le=10000),
    db: Session = Depends(get_db),
):
    """Chart-ready series for one module; defaults to the last 7 days of data."""
    module = db.get(models.BatteryModule, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Battery module not found")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")

    series = get_module_series(db, module_id, start, end, max_points)
    series.pop("states")
    return schemas.ModuleTelemetrySeries(module_id=module_id, serial_number=module.serial_number, **series)


@router.get("", response_model=schemas.ModuleTelemetryPage)
def list_module_telemetry(
    module_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=3000),
    db: Session = Depends(get_db),
):
    query = db.query(models.ModuleTelemetry, models.BatteryModule.serial_number).join(
        models.BatteryModule, models.ModuleTelemetry.module_id == models.BatteryModule.module_id
    )
    if module_id:
        query = query.filter(models.ModuleTelemetry.module_id == module_id)
    if start:
        query = query.filter(models.ModuleTelemetry.ts >= start)
    if end:
        query = query.filter(models.ModuleTelemetry.ts <= end)

    total = query.count()
    rows = (
        query.order_by(models.ModuleTelemetry.ts.desc(), models.ModuleTelemetry.module_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_out(row, serial) for row, serial in rows]
    return schemas.ModuleTelemetryPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=schemas.ModuleTelemetryOut, status_code=201)
def add_module_telemetry(payload: schemas.ModuleTelemetryCreate, db: Session = Depends(get_db)):
    module = db.get(models.BatteryModule, payload.module_id)
    if not module:
        raise HTTPException(status_code=400, detail="Battery module not found")

    upsert_module_telemetry_rows(db, [payload])
    db.commit()

    row = db.get(models.ModuleTelemetry, (payload.module_id, payload.ts))
    return _to_out(row, module.serial_number)


@router.post("/bulk", response_model=schemas.BulkModuleTelemetryResult)
async def bulk_add_module_telemetry(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    valid_rows, row_errors, total_rows = parse_module_telemetry_file(file.filename or "upload", content, db)

    inserted, updated = upsert_module_telemetry_rows(db, valid_rows)
    db.commit()

    return schemas.BulkModuleTelemetryResult(
        filename=file.filename or "upload",
        total_rows=total_rows,
        valid_rows=len(valid_rows),
        inserted=inserted,
        updated=updated,
        error_count=len(row_errors),
        errors=row_errors[:200],
    )
