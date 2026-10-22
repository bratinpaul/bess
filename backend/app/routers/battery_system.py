from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.hierarchy import remove_node, remove_nodes, sync_node

router = APIRouter(prefix="/api/battery-systems", tags=["battery-systems"])


@router.get("", response_model=list[schemas.BatterySystemOut])
def list_battery_systems(request: Request, db: Session = Depends(get_db)):
    q = db.query(models.BatterySystem)
    allowed = scope.system_ids(db, request)  # tenant-scoped callers see their tenant's systems only
    if allowed is not None:
        q = q.filter(models.BatterySystem.battery_system_id.in_(allowed))
    return q.order_by(models.BatterySystem.system_name).all()


@router.get("/{battery_system_id}", response_model=schemas.BatterySystemOut)
def get_battery_system(battery_system_id: int, request: Request, db: Session = Depends(get_db)):
    scope.ensure_visible(scope.system_ids(db, request), battery_system_id, "Battery system")
    battery_system = db.get(models.BatterySystem, battery_system_id)
    if not battery_system:
        raise HTTPException(status_code=404, detail="Battery system not found")
    return battery_system


@router.post("", response_model=schemas.BatterySystemOut, status_code=201)
def create_battery_system(payload: schemas.BatterySystemCreate, db: Session = Depends(get_db)):
    if not db.get(models.Site, payload.site_id):
        raise HTTPException(status_code=400, detail="Site not found")
    if not db.get(models.BatteryChemistry, payload.chemistry_code):
        raise HTTPException(status_code=400, detail="Chemistry not found")
    battery_system = models.BatterySystem(**payload.model_dump())
    db.add(battery_system)
    try:
        db.flush()  # assigns battery_system_id
        sync_node(db, "battery_system", battery_system.battery_system_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not save battery system")
    db.refresh(battery_system)
    return battery_system


@router.put("/{battery_system_id}", response_model=schemas.BatterySystemOut)
def update_battery_system(
    battery_system_id: int, payload: schemas.BatterySystemUpdate, db: Session = Depends(get_db)
):
    battery_system = db.get(models.BatterySystem, battery_system_id)
    if not battery_system:
        raise HTTPException(status_code=404, detail="Battery system not found")
    if not db.get(models.Site, payload.site_id):
        raise HTTPException(status_code=400, detail="Site not found")
    if not db.get(models.BatteryChemistry, payload.chemistry_code):
        raise HTTPException(status_code=400, detail="Chemistry not found")
    for field, value in payload.model_dump().items():
        setattr(battery_system, field, value)
    try:
        sync_node(db, "battery_system", battery_system_id)  # name or site may have changed
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not save battery system")
    db.refresh(battery_system)
    return battery_system


@router.delete("/{battery_system_id}", status_code=204)
def delete_battery_system(battery_system_id: int, db: Session = Depends(get_db)):
    battery_system = db.get(models.BatterySystem, battery_system_id)
    if not battery_system:
        raise HTTPException(status_code=404, detail="Battery system not found")
    pcs_ids = [i for (i,) in db.query(models.Pcs.pcs_id).filter(models.Pcs.system_id == battery_system_id)]
    remove_nodes(db, "pcs", pcs_ids)  # the database cascades the PCS rows themselves
    remove_node(db, "battery_system", battery_system_id)  # rolled back below if the delete fails
    db.delete(battery_system)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cannot delete battery system: it still has containers, EMS controllers or HVAC units attached to it, or PCS telemetry",
        )
    return None
