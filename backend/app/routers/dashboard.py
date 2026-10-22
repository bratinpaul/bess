from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=schemas.DashboardSummary)
def get_summary(request: Request, db: Session = Depends(get_db)):
    q = db.query(
        func.count(models.Site.site_id),
        func.coalesce(func.sum(models.Site.rated_power_mw), 0),
        func.coalesce(func.sum(models.Site.rated_energy_mwh), 0),
    )
    allowed = scope.site_ids(db, request)  # a tenant-scoped caller: its tenant's sites only
    if allowed is not None:
        q = q.filter(models.Site.site_id.in_(allowed))
    site_count, total_power, total_energy = q.one()
    return schemas.DashboardSummary(
        site_count=site_count,
        total_power_mw=Decimal(total_power),
        total_energy_mwh=Decimal(total_energy),
    )


@router.get("/site-map", response_model=list[schemas.SiteMapPoint])
def get_site_map_points(request: Request, db: Session = Depends(get_db)):
    q = db.query(models.Site).filter(models.Site.latitude.isnot(None), models.Site.longitude.isnot(None))
    allowed = scope.site_ids(db, request)
    if allowed is not None:
        q = q.filter(models.Site.site_id.in_(allowed))
    return q.order_by(models.Site.site_name).all()
