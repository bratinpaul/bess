"""Master-data CRUD for EMS controllers and HVAC units (each belongs to a battery system)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.hierarchy import remove_node, sync_node


def _crud_router(
    *,
    prefix: str,
    tag: str,
    label: str,
    model,
    id_attr: str,
    code_attr: str,
    asset_type: str,
    out_schema,
    create_schema,
    update_schema,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])
    code_col = getattr(model, code_attr)

    def to_out(row, system_name):
        out = out_schema.model_validate(row)
        out.system_name = system_name
        return out

    def get_or_404(db: Session, item_id: int):
        row = db.get(model, item_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"{label} not found")
        return row

    def check_system(db: Session, battery_system_id: int):
        if not db.get(models.BatterySystem, battery_system_id):
            raise HTTPException(status_code=400, detail="Battery system not found")

    def system_name(db: Session, battery_system_id):
        if battery_system_id is None:
            return None
        system = db.get(models.BatterySystem, battery_system_id)
        return system.system_name if system else None

    def save(db: Session, row, item_id=None):
        try:
            db.flush()
            sync_node(db, asset_type, item_id or getattr(row, id_attr))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Another {label} already uses this code")
        db.refresh(row)
        return to_out(row, system_name(db, row.battery_system_id))

    @router.get("", response_model=list[out_schema])
    def list_items(request: Request, db: Session = Depends(get_db)):
        q = (
            db.query(model, models.BatterySystem.system_name)
            .outerjoin(models.BatterySystem, models.BatterySystem.battery_system_id == model.battery_system_id)
        )
        allowed = scope.system_ids(db, request)  # tenant-scoped callers see their tenant's units only
        if allowed is not None:
            q = q.filter(model.battery_system_id.in_(allowed))
        rows = q.order_by(code_col).all()
        return [to_out(row, name) for row, name in rows]

    @router.get("/{item_id}", response_model=out_schema)
    def get_item(item_id: int, request: Request, db: Session = Depends(get_db)):
        row = get_or_404(db, item_id)
        scope.ensure_visible(scope.system_ids(db, request), row.battery_system_id, label)
        return to_out(row, system_name(db, row.battery_system_id))

    @router.post("", response_model=out_schema, status_code=201)
    def create_item(payload: create_schema, db: Session = Depends(get_db)):
        check_system(db, payload.battery_system_id)
        row = model(**payload.model_dump())
        db.add(row)
        return save(db, row)

    @router.put("/{item_id}", response_model=out_schema)
    def update_item(item_id: int, payload: update_schema, db: Session = Depends(get_db)):
        row = get_or_404(db, item_id)
        check_system(db, payload.battery_system_id)
        for field, value in payload.model_dump().items():
            setattr(row, field, value)
        return save(db, row, item_id)

    @router.delete("/{item_id}", status_code=204)
    def delete_item(item_id: int, db: Session = Depends(get_db)):
        row = get_or_404(db, item_id)
        remove_node(db, asset_type, item_id)  # rolled back below if the delete fails
        db.delete(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Cannot delete {label}: it still has telemetry recorded against it")
        return None

    # FastAPI names operations after the function; keep them unique per router
    for route in router.routes:
        route.operation_id = f"{tag}_{route.name}"
    return router


ems_router = _crud_router(
    prefix="/api/ems-controllers",
    tag="ems-controllers",
    label="EMS controller",
    model=models.EmsController,
    id_attr="ems_id",
    code_attr="ems_code",
    asset_type="ems_controller",
    out_schema=schemas.EmsControllerOut,
    create_schema=schemas.EmsControllerCreate,
    update_schema=schemas.EmsControllerUpdate,
)

hvac_router = _crud_router(
    prefix="/api/hvac-units",
    tag="hvac-units",
    label="HVAC unit",
    model=models.HvacUnit,
    id_attr="hvac_id",
    code_attr="hvac_code",
    asset_type="hvac_unit",
    out_schema=schemas.HvacUnitOut,
    create_schema=schemas.HvacUnitCreate,
    update_schema=schemas.HvacUnitUpdate,
)
