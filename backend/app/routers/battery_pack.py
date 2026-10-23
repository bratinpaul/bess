from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.hierarchy import remove_node, sync_node

router = APIRouter(prefix="/api/battery-packs", tags=["battery-packs"])


@router.get("", response_model=list[schemas.BatteryPackOut])
def list_battery_packs(request: Request, db: Session = Depends(get_db)):
    q = db.query(models.BatteryPack)
    allowed = scope.pack_ids(db, request)
    if allowed is not None:
        q = q.filter(models.BatteryPack.pack_id.in_(allowed))
    return q.order_by(models.BatteryPack.pack_number).all()


@router.get("/{pack_id}", response_model=schemas.BatteryPackOut)
def get_battery_pack(pack_id: int, request: Request, db: Session = Depends(get_db)):
    scope.ensure_visible(scope.pack_ids(db, request), pack_id, "Battery pack")
    pack = db.get(models.BatteryPack, pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Battery pack not found")
    return pack


@router.post("", response_model=schemas.BatteryPackOut, status_code=201)
def create_battery_pack(payload: schemas.BatteryPackCreate, db: Session = Depends(get_db)):
    if not db.get(models.BatteryContainer, payload.container_id):
        raise HTTPException(status_code=400, detail="Battery container not found")
    pack = models.BatteryPack(**payload.model_dump())
    db.add(pack)
    db.flush()  # assigns pack_id
    sync_node(db, "battery_pack", pack.pack_id)
    db.commit()
    db.refresh(pack)
    return pack


@router.put("/{pack_id}", response_model=schemas.BatteryPackOut)
def update_battery_pack(pack_id: int, payload: schemas.BatteryPackUpdate, db: Session = Depends(get_db)):
    pack = db.get(models.BatteryPack, pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Battery pack not found")
    if not db.get(models.BatteryContainer, payload.container_id):
        raise HTTPException(status_code=400, detail="Battery container not found")
    for field, value in payload.model_dump().items():
        setattr(pack, field, value)
    sync_node(db, "battery_pack", pack_id)  # name or container may have changed
    db.commit()
    db.refresh(pack)
    return pack


@router.delete("/{pack_id}", status_code=204)
def delete_battery_pack(pack_id: int, db: Session = Depends(get_db)):
    pack = db.get(models.BatteryPack, pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Battery pack not found")
    remove_node(db, "battery_pack", pack_id)  # undone with the request (get_db) if the delete fails
    db.delete(pack)
    db.commit()
    return None
