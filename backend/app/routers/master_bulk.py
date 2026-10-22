"""Bulk load of master data files (CSV / Excel), one entity per call - see services/master_import.py."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.services import master_import as M

router = APIRouter(prefix="/api/master-bulk", tags=["master-bulk"])


@router.get("", response_model=list[schemas.MasterBulkEntity])
def entities():
    """The master data that can be bulk loaded, in load order, with each file's columns."""
    return [M.describe(M.ENTITIES[k]) for k in M.LOAD_ORDER]


@router.post("/{entity}", response_model=schemas.BulkMasterResult)
async def bulk_load(entity: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Insert or update (by source_uuid) the records in the file; invalid rows are reported and skipped."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        result = M.import_file(db, entity, file.filename or "upload.csv", content)
    except M.MasterImportError as exc:
        raise HTTPException(status_code=404 if exc.args[0].startswith("Unknown master data") else 400, detail=str(exc))
    db.commit()
    return schemas.BulkMasterResult(
        entity=entity, filename=file.filename or "upload", total_rows=result.total_rows, valid_rows=result.valid_rows,
        inserted=result.inserted, updated=result.updated, error_count=len(result.errors), errors=result.errors[:200],
    )
