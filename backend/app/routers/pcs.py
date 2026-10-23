from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.hierarchy import remove_node, sync_node

router = APIRouter(prefix="/api/pcs", tags=["pcs"])


@router.get("", response_model=list[schemas.PcsOut])
def list_pcs(request: Request, db: Session = Depends(get_db)):
    q = db.query(models.Pcs)
    allowed = scope.system_ids(db, request)
    if allowed is not None:
        q = q.filter(models.Pcs.system_id.in_(allowed))
    return q.order_by(models.Pcs.pcs_code).all()


@router.get("/{pcs_id}", response_model=schemas.PcsOut)
def get_pcs(pcs_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(models.Pcs, pcs_id)
    if not item:
        raise HTTPException(status_code=404, detail="PCS not found")
    scope.ensure_visible(scope.system_ids(db, request), item.system_id, "PCS")
    return item


@router.post("", response_model=schemas.PcsOut, status_code=201)
def create_pcs(payload: schemas.PcsCreate, db: Session = Depends(get_db)):
    if not db.get(models.BatterySystem, payload.system_id):
        raise HTTPException(status_code=400, detail="Battery system not found")
    item = models.Pcs(**payload.model_dump())
    db.add(item)
    db.flush()  # assigns pcs_id
    sync_node(db, "pcs", item.pcs_id)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{pcs_id}", response_model=schemas.PcsOut)
def update_pcs(pcs_id: int, payload: schemas.PcsUpdate, db: Session = Depends(get_db)):
    item = db.get(models.Pcs, pcs_id)
    if not item:
        raise HTTPException(status_code=404, detail="PCS not found")
    if not db.get(models.BatterySystem, payload.system_id):
        raise HTTPException(status_code=400, detail="Battery system not found")
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    sync_node(db, "pcs", pcs_id)  # code or battery system may have changed
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{pcs_id}", status_code=204)
def delete_pcs(pcs_id: int, db: Session = Depends(get_db)):
    item = db.get(models.Pcs, pcs_id)
    if not item:
        raise HTTPException(status_code=404, detail="PCS not found")
    remove_node(db, "pcs", pcs_id)  # undone with the request (get_db) if the delete fails
    db.delete(item)
    db.commit()
    return None
