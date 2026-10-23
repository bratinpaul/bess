from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.models.alarm_catalog import ALARM_SOURCES
from app.services.alarm_catalog_import import parse_alarm_catalog_file, upsert_alarm_catalog

router = APIRouter(prefix="/api/alarm-catalog", tags=["alarm-catalog"])

Catalog = models.AlarmCatalog


def _severity_names(db: Session) -> dict[int, str]:
    return {s.severity_level: s.severity_name for s in db.query(models.AlarmSeverity)}


def _out(row: Catalog, names: dict[int, str]) -> schemas.AlarmCatalogOut:
    out = schemas.AlarmCatalogOut.model_validate(row)
    out.severity_name = names.get(row.severity_level)
    return out


def _get(db: Session, alarm_catalog_id: int) -> Catalog:
    row = db.get(Catalog, alarm_catalog_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alarm catalog entry not found")
    return row


def _save(db: Session, row: Catalog) -> schemas.AlarmCatalogOut:
    db.commit()
    db.refresh(row)
    return _out(row, _severity_names(db))


@router.get("", response_model=list[schemas.AlarmCatalogOut])
def list_alarm_catalog(db: Session = Depends(get_db)):
    names = _severity_names(db)
    rows = db.query(Catalog).order_by(Catalog.source, Catalog.alarm_code).all()
    return [_out(r, names) for r in rows]


@router.get("/lookups", response_model=schemas.AlarmCatalogLookups)
def get_lookups(db: Session = Depends(get_db)):
    """Allowed sources and severities, plus the alarm / asset types already in use (for suggestions)."""
    distinct = lambda col: [v for (v,) in db.query(col).filter(col.isnot(None)).distinct().order_by(col)]
    return schemas.AlarmCatalogLookups(
        sources=list(ALARM_SOURCES),
        severities=[schemas.AlarmSeverityOut.model_validate(s) for s in
                    db.query(models.AlarmSeverity).order_by(models.AlarmSeverity.severity_level)],
        alarm_types=distinct(Catalog.alarm_type),
        asset_types=distinct(Catalog.asset_type),
    )


@router.post("/bulk", response_model=schemas.BulkAlarmCatalogResult)
async def bulk_load_alarm_catalog(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load an .xlsx ('Alarm Catalog' sheet) or .csv. Existing (source, alarm_code) entries are updated."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    sheet, valid, errors, total, ignored = parse_alarm_catalog_file(file.filename or "upload", content, db)
    inserted, updated = upsert_alarm_catalog(db, valid)
    db.commit()
    return schemas.BulkAlarmCatalogResult(
        filename=file.filename or "upload",
        sheet=sheet,
        total_rows=total,
        valid_rows=len(valid),
        inserted=inserted,
        updated=updated,
        error_count=len(errors),
        errors=errors[:200],
        ignored_columns=ignored,
    )


@router.get("/{alarm_catalog_id}", response_model=schemas.AlarmCatalogOut)
def get_alarm_catalog_entry(alarm_catalog_id: int, db: Session = Depends(get_db)):
    return _out(_get(db, alarm_catalog_id), _severity_names(db))


@router.post("", response_model=schemas.AlarmCatalogOut, status_code=201)
def create_alarm_catalog_entry(payload: schemas.AlarmCatalogCreate, db: Session = Depends(get_db)):
    row = Catalog(**payload.model_dump())
    db.add(row)
    return _save(db, row)


@router.put("/{alarm_catalog_id}", response_model=schemas.AlarmCatalogOut)
def update_alarm_catalog_entry(
    alarm_catalog_id: int, payload: schemas.AlarmCatalogUpdate, db: Session = Depends(get_db)
):
    row = _get(db, alarm_catalog_id)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    return _save(db, row)


@router.delete("/{alarm_catalog_id}", status_code=204)
def delete_alarm_catalog_entry(alarm_catalog_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, alarm_catalog_id))
    db.commit()
    return None
