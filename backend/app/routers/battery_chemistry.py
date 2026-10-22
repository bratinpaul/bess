from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/battery-chemistries", tags=["battery-chemistries"])


@router.get("", response_model=list[schemas.BatteryChemistryOut])
def list_battery_chemistries(db: Session = Depends(get_db)):
    return db.query(models.BatteryChemistry).order_by(models.BatteryChemistry.chemistry_code).all()
