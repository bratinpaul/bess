from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.hierarchy import remove_node, sync_node

router = APIRouter(prefix="/api/battery-containers", tags=["battery-containers"])


@router.get("", response_model=list[schemas.BatteryContainerOut])
def list_battery_containers(request: Request, db: Session = Depends(get_db)):
    q = db.query(models.BatteryContainer)
    allowed = scope.container_ids(db, request)
    if allowed is not None:
        q = q.filter(models.BatteryContainer.container_id.in_(allowed))
    return q.order_by(models.BatteryContainer.container_number).all()


@router.get("/{container_id}", response_model=schemas.BatteryContainerOut)
def get_battery_container(container_id: int, request: Request, db: Session = Depends(get_db)):
    scope.ensure_visible(scope.container_ids(db, request), container_id, "Battery container")
    container = db.get(models.BatteryContainer, container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Battery container not found")
    return container


@router.post("", response_model=schemas.BatteryContainerOut, status_code=201)
def create_battery_container(payload: schemas.BatteryContainerCreate, db: Session = Depends(get_db)):
    if not db.get(models.BatterySystem, payload.battery_system_id):
        raise HTTPException(status_code=400, detail="Battery system not found")
    container = models.BatteryContainer(**payload.model_dump())
    db.add(container)
    db.flush()  # assigns container_id
    sync_node(db, "battery_container", container.container_id)
    db.commit()
    db.refresh(container)
    return container


@router.put("/{container_id}", response_model=schemas.BatteryContainerOut)
def update_battery_container(
    container_id: int, payload: schemas.BatteryContainerUpdate, db: Session = Depends(get_db)
):
    container = db.get(models.BatteryContainer, container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Battery container not found")
    if not db.get(models.BatterySystem, payload.battery_system_id):
        raise HTTPException(status_code=400, detail="Battery system not found")
    for field, value in payload.model_dump().items():
        setattr(container, field, value)
    sync_node(db, "battery_container", container_id)  # name or battery system may have changed
    db.commit()
    db.refresh(container)
    return container


@router.delete("/{container_id}", status_code=204)
def delete_battery_container(container_id: int, db: Session = Depends(get_db)):
    container = db.get(models.BatteryContainer, container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Battery container not found")
    remove_node(db, "battery_container", container_id)  # undone with the request (get_db) if the delete fails
    db.delete(container)
    db.commit()
    return None
