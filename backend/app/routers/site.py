from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import Principal, require
from app.database import get_db
from app.hierarchy import remove_node, sync_node

router = APIRouter(prefix="/api/sites", tags=["sites"])

# RBAC (battery_users.role_privilege, resource master.asset): read for every role, write for Admin / Asset Engineer /
# Data Engineer, delete for Admin. A tenant-scoped principal (Tenant Viewer) only sees the sites its tenant owns.
READ, WRITE, DELETE = require("master.asset:read"), require("master.asset:write"), require("master.asset:delete")


def _tenant_site_ids(db: Session, principal: Principal) -> set[int] | None:
    """Sites the caller may see: None = all; a set for tenant-scoped callers."""
    if principal.tenant_id is None:
        return None
    rows = db.query(models.TenantSite.site_id).filter(models.TenantSite.tenant_id == principal.tenant_id).all()
    return {r[0] for r in rows}


def _owners_by_site(db: Session, site_ids: list[int] | None = None) -> dict[int, list[schemas.SiteOwnerOut]]:
    """Owners per site (tenant_site joined to tenant), primary owner first, then by share."""
    q = db.query(models.TenantSite, models.Tenant.name, models.Tenant.status).join(
        models.Tenant, models.Tenant.tenant_id == models.TenantSite.tenant_id
    )
    if site_ids is not None:
        q = q.filter(models.TenantSite.site_id.in_(site_ids))
    owners: dict[int, list[schemas.SiteOwnerOut]] = {}
    for link, name, status in q.all():
        owners.setdefault(link.site_id, []).append(
            schemas.SiteOwnerOut(
                tenant_id=link.tenant_id,
                ownership_pct=link.ownership_pct,
                is_primary_owner=link.is_primary_owner,
                tenant_name=name,
                tenant_status=status,
            )
        )
    for rows in owners.values():
        rows.sort(key=lambda o: (not o.is_primary_owner, -(o.ownership_pct or 0), o.tenant_name.lower()))
    return owners


def _to_out(site: models.Site, owners: list[schemas.SiteOwnerOut]) -> schemas.SiteOut:
    out = schemas.SiteOut.model_validate(site)
    out.owners = owners
    primary = next((o for o in owners if o.is_primary_owner), None)
    out.primary_owner_name = primary.tenant_name if primary else None
    return out


def _replace_owners(db: Session, site_id: int, owners: list[schemas.SiteOwnerIn]) -> None:
    """Make tenant_site for this site match `owners` exactly (same transaction as the site change)."""
    ids = [o.tenant_id for o in owners]
    if ids:
        found = {t for (t,) in db.query(models.Tenant.tenant_id).filter(models.Tenant.tenant_id.in_(ids))}
        missing = sorted(set(ids) - found)
        if missing:
            raise HTTPException(status_code=400, detail=f"Tenant not found: {', '.join(map(str, missing))}")
    db.query(models.TenantSite).filter(models.TenantSite.site_id == site_id).delete(synchronize_session=False)
    for o in owners:
        db.add(
            models.TenantSite(
                tenant_id=o.tenant_id,
                site_id=site_id,
                ownership_pct=o.ownership_pct,
                is_primary_owner=o.is_primary_owner,
            )
        )


@router.get("", response_model=list[schemas.SiteOut])
def list_sites(db: Session = Depends(get_db), principal: Principal = Depends(READ)):
    owners = _owners_by_site(db)
    q = db.query(models.Site)
    allowed = _tenant_site_ids(db, principal)
    if allowed is not None:
        q = q.filter(models.Site.site_id.in_(allowed))
    sites = q.order_by(models.Site.site_name).all()
    return [_to_out(s, owners.get(s.site_id, [])) for s in sites]


@router.get("/{site_id}", response_model=schemas.SiteOut)
def get_site(site_id: int, db: Session = Depends(get_db), principal: Principal = Depends(READ)):
    site = db.get(models.Site, site_id)
    allowed = _tenant_site_ids(db, principal)
    if not site or (allowed is not None and site_id not in allowed):
        raise HTTPException(status_code=404, detail="Site not found")
    return _to_out(site, _owners_by_site(db, [site_id]).get(site_id, []))


@router.post("", response_model=schemas.SiteOut, status_code=201)
def create_site(payload: schemas.SiteCreate, db: Session = Depends(get_db), _: Principal = Depends(WRITE)):
    site = models.Site(**payload.model_dump(exclude={"owners"}))
    db.add(site)
    try:
        db.flush()  # assigns site_id for the ownership rows
        _replace_owners(db, site.site_id, payload.owners)
        sync_node(db, "site", site.site_id)  # parent = primary owner
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Site code already exists")
    except HTTPException:
        db.rollback()
        raise
    db.refresh(site)
    return _to_out(site, _owners_by_site(db, [site.site_id]).get(site.site_id, []))


@router.put("/{site_id}", response_model=schemas.SiteOut)
def update_site(site_id: int, payload: schemas.SiteUpdate, db: Session = Depends(get_db),
                _: Principal = Depends(WRITE)):
    site = db.get(models.Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    for field, value in payload.model_dump(exclude={"owners"}).items():
        setattr(site, field, value)
    try:
        if payload.owners is not None:
            _replace_owners(db, site_id, payload.owners)
        sync_node(db, "site", site_id)  # name or primary owner may have changed
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Site code already exists")
    except HTTPException:
        db.rollback()
        raise
    db.refresh(site)
    return _to_out(site, _owners_by_site(db, [site_id]).get(site_id, []))


@router.delete("/{site_id}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db), _: Principal = Depends(DELETE)):
    site = db.get(models.Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    remove_node(db, "site", site_id)  # rolled back below if the site can't be deleted
    db.delete(site)  # tenant_site rows go with it (ON DELETE CASCADE)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Cannot delete site: it still has battery systems attached to it"
        )
    return None
