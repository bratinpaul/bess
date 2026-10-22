from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.hierarchy import remove_node, sync_node

router = APIRouter(prefix="/api/battery-modules", tags=["battery-modules"])


@router.get("", response_model=list[schemas.BatteryModuleOut])
def list_battery_modules(request: Request, db: Session = Depends(get_db)):
    q = db.query(models.BatteryModule)
    allowed = scope.module_ids(db, request)
    if allowed is not None:
        q = q.filter(models.BatteryModule.module_id.in_(allowed))
    return q.order_by(models.BatteryModule.serial_number).all()


@router.get("/{module_id}", response_model=schemas.BatteryModuleOut)
def get_battery_module(module_id: int, request: Request, db: Session = Depends(get_db)):
    scope.ensure_visible(scope.module_ids(db, request), module_id, "Battery module")
    module = db.get(models.BatteryModule, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Battery module not found")
    return module


@router.post("", response_model=schemas.BatteryModuleOut, status_code=201)
def create_battery_module(payload: schemas.BatteryModuleCreate, db: Session = Depends(get_db)):
    if not db.get(models.BatteryPack, payload.pack_id):
        raise HTTPException(status_code=400, detail="Battery pack not found")
    module = models.BatteryModule(**payload.model_dump())
    db.add(module)
    try:
        db.flush()  # assigns module_id
        sync_node(db, "battery_module", module.module_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Serial number already exists")
    except DataError:
        db.rollback()
        raise HTTPException(status_code=400, detail="One or more values are out of range for this field")
    db.refresh(module)
    return module


@router.put("/{module_id}", response_model=schemas.BatteryModuleOut)
def update_battery_module(module_id: int, payload: schemas.BatteryModuleUpdate, db: Session = Depends(get_db)):
    module = db.get(models.BatteryModule, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Battery module not found")
    if not db.get(models.BatteryPack, payload.pack_id):
        raise HTTPException(status_code=400, detail="Battery pack not found")
    for field, value in payload.model_dump().items():
        setattr(module, field, value)
    try:
        sync_node(db, "battery_module", module_id)  # serial number or pack may have changed
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Serial number already exists")
    except DataError:
        db.rollback()
        raise HTTPException(status_code=400, detail="One or more values are out of range for this field")
    db.refresh(module)
    return module


@router.delete("/{module_id}", status_code=204)
def delete_battery_module(module_id: int, db: Session = Depends(get_db)):
    module = db.get(models.BatteryModule, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Battery module not found")
    remove_node(db, "battery_module", module_id)  # rolled back below if the delete fails
    db.delete(module)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Cannot delete battery module: it still has module telemetry recorded against it"
        )
    return None
