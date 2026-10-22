"""Row-level scope for tenant-scoped callers (Tenant Viewer): the master data they may see is what hangs under the sites
their tenant owns (battery_master.tenant_site). Every helper returns None for unscoped callers (all rows) or the set of
visible ids; list endpoints filter with it and detail endpoints answer 404 outside it.

    site_ids -> system_ids -> container_ids -> pack_ids -> module_ids ; pcs / EMS / HVAC hang off a battery system
"""
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from bess_common.auth import Principal


def principal_of(request: Request) -> Optional[Principal]:
    return getattr(request.state, "principal", None)


def _tenant(request: Request) -> Optional[int]:
    p = principal_of(request)
    return p.tenant_id if p else None


def site_ids(db: Session, request: Request) -> Optional[set[int]]:
    tenant = _tenant(request)
    if tenant is None:
        return None
    return {r[0] for r in db.query(models.TenantSite.site_id).filter(models.TenantSite.tenant_id == tenant)}


def system_ids(db: Session, request: Request) -> Optional[set[int]]:
    sites = site_ids(db, request)
    if sites is None:
        return None
    return {r[0] for r in db.query(models.BatterySystem.battery_system_id).filter(models.BatterySystem.site_id.in_(sites))}


def container_ids(db: Session, request: Request) -> Optional[set[int]]:
    systems = system_ids(db, request)
    if systems is None:
        return None
    return {r[0] for r in db.query(models.BatteryContainer.container_id)
            .filter(models.BatteryContainer.battery_system_id.in_(systems))}


def pack_ids(db: Session, request: Request) -> Optional[set[int]]:
    containers = container_ids(db, request)
    if containers is None:
        return None
    return {r[0] for r in db.query(models.BatteryPack.pack_id).filter(models.BatteryPack.container_id.in_(containers))}


def module_ids(db: Session, request: Request) -> Optional[set[int]]:
    packs = pack_ids(db, request)
    if packs is None:
        return None
    return {r[0] for r in db.query(models.BatteryModule.module_id).filter(models.BatteryModule.pack_id.in_(packs))}


def ensure_visible(allowed: Optional[set[int]], item_id: Optional[int], label: str = "Record") -> None:
    """404 (not 403 - don't reveal that the record exists) when a scoped caller asks for something outside its tenant."""
    if allowed is not None and item_id not in allowed:
        raise HTTPException(status_code=404, detail=f"{label} not found")
