from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.hierarchy import remove_node, sync_node

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


# ---------------------------------------------------------------- helpers


def _counts(db: Session, column) -> dict[int, int]:
    """tenant_id -> number of rows in the table `column` belongs to."""
    return dict(db.query(column, func.count()).group_by(column).all())


def _primary_contacts(db: Session) -> dict[int, str]:
    rows = db.query(models.TenantContact.tenant_id, models.TenantContact.contact_name).filter(
        models.TenantContact.is_primary.is_(True)
    )
    return {tenant_id: name for tenant_id, name in rows}


def _summary(db: Session, tenant: models.Tenant, sites: dict, contacts: dict, primaries: dict) -> schemas.TenantOut:
    out = schemas.TenantOut.model_validate(tenant)
    out.site_count = sites.get(tenant.tenant_id, 0)
    out.contact_count = contacts.get(tenant.tenant_id, 0)
    out.primary_contact_name = primaries.get(tenant.tenant_id)
    return out


def _detail(db: Session, tenant: models.Tenant) -> schemas.TenantDetail:
    contacts = (
        db.query(models.TenantContact)
        .filter(models.TenantContact.tenant_id == tenant.tenant_id)
        .order_by(models.TenantContact.is_primary.desc(), models.TenantContact.contact_name)
        .all()
    )
    links = (
        db.query(models.TenantSite, models.Site.site_code, models.Site.site_name)
        .join(models.Site, models.Site.site_id == models.TenantSite.site_id)
        .filter(models.TenantSite.tenant_id == tenant.tenant_id)
        .order_by(models.Site.site_name)
        .all()
    )
    out = schemas.TenantDetail.model_validate(tenant)
    out.contacts = [schemas.TenantContactOut.model_validate(c) for c in contacts]
    out.sites = [
        schemas.TenantSiteLink(
            site_id=link.site_id,
            site_code=code,
            site_name=name,
            ownership_pct=link.ownership_pct,
            is_primary_owner=link.is_primary_owner,
        )
        for link, code, name in links
    ]
    out.site_count = len(out.sites)
    out.contact_count = len(out.contacts)
    primary = next((c for c in contacts if c.is_primary), None)
    out.primary_contact_name = primary.contact_name if primary else None
    return out


def _get_tenant(db: Session, tenant_id: int) -> models.Tenant:
    tenant = db.get(models.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def tenant_types(db: Session) -> list[str]:
    """Values of the tenant_type Postgres enum, in their defined order."""
    rows = db.execute(
        text(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'tenant_type' ORDER BY e.enumsortorder"
        )
    )
    return [r[0] for r in rows]


def _check_type(db: Session, tenant_type: str | None) -> None:
    if tenant_type is None:
        return
    allowed = tenant_types(db)
    if tenant_type not in allowed:
        raise HTTPException(
            status_code=422, detail=f"Type must be one of: {', '.join(allowed)} (got '{tenant_type}')"
        )


def _sync_contacts(db: Session, tenant_id: int, contacts: list[schemas.TenantContactIn]) -> None:
    """Make the tenant's contacts match `contacts`: update listed ones, add new ones, delete the rest."""
    existing = {
        c.contact_id: c
        for c in db.query(models.TenantContact).filter(models.TenantContact.tenant_id == tenant_id)
    }
    unknown = [c.contact_id for c in contacts if c.contact_id is not None and c.contact_id not in existing]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Contact not found for this tenant: {unknown}")
    keep = {c.contact_id for c in contacts if c.contact_id is not None}
    for contact_id, row in existing.items():
        if contact_id not in keep:
            db.delete(row)
        else:
            # clear every primary flag first and flush, because the one-primary unique index
            # is checked row by row; set on the loaded rows so the ORM sees the later change back
            row.is_primary = False
    db.flush()
    for c in contacts:
        values = c.model_dump(exclude={"contact_id"})
        if c.contact_id is None:
            db.add(models.TenantContact(tenant_id=tenant_id, **values))
        else:
            row = existing[c.contact_id]
            for field, value in values.items():
                setattr(row, field, value)


# ---------------------------------------------------------------- tenants


@router.get("", response_model=list[schemas.TenantOut])
def list_tenants(db: Session = Depends(get_db)):
    sites = _counts(db, models.TenantSite.tenant_id)
    contacts = _counts(db, models.TenantContact.tenant_id)
    primaries = _primary_contacts(db)
    tenants = db.query(models.Tenant).order_by(models.Tenant.name).all()
    return [_summary(db, t, sites, contacts, primaries) for t in tenants]


@router.get("/types", response_model=list[str])
def list_tenant_types(db: Session = Depends(get_db)):
    """Allowed tenant types (the tenant_type enum), for the Type dropdown."""
    return tenant_types(db)


@router.get("/{tenant_id}", response_model=schemas.TenantDetail)
def get_tenant(tenant_id: int, db: Session = Depends(get_db)):
    """Tenant with its contacts and the sites it owns (tenant_site)."""
    return _detail(db, _get_tenant(db, tenant_id))


@router.post("", response_model=schemas.TenantDetail, status_code=201)
def create_tenant(payload: schemas.TenantCreate, db: Session = Depends(get_db)):
    _check_type(db, payload.tenant_type)
    tenant = models.Tenant(**payload.model_dump(exclude={"contacts"}))
    db.add(tenant)
    db.flush()  # assigns tenant_id for the contacts
    for c in payload.contacts:
        db.add(models.TenantContact(tenant_id=tenant.tenant_id, **c.model_dump(exclude={"contact_id"})))
    sync_node(db, "tenant", tenant.tenant_id)
    db.commit()
    db.refresh(tenant)
    return _detail(db, tenant)


@router.put("/{tenant_id}", response_model=schemas.TenantDetail)
def update_tenant(tenant_id: int, payload: schemas.TenantUpdate, db: Session = Depends(get_db)):
    tenant = _get_tenant(db, tenant_id)
    _check_type(db, payload.tenant_type)
    for field, value in payload.model_dump(exclude={"contacts"}).items():
        setattr(tenant, field, value)
    if payload.contacts is not None:
        _sync_contacts(db, tenant_id, payload.contacts)
    sync_node(db, "tenant", tenant_id)  # name may have changed
    db.commit()
    db.refresh(tenant)
    return _detail(db, tenant)


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: int, db: Session = Depends(get_db)):
    """Deletes the tenant; the database cascades to its contacts and site-ownership rows (sites stay)."""
    tenant = _get_tenant(db, tenant_id)
    remove_node(db, "tenant", tenant_id)  # its sites stay in the hierarchy, without a parent
    db.delete(tenant)
    db.commit()
    return None


# ---------------------------------------------------------------- contacts


def _clear_other_primaries(db: Session, tenant_id: int, keep_contact_id: int | None) -> None:
    q = db.query(models.TenantContact).filter(
        models.TenantContact.tenant_id == tenant_id, models.TenantContact.is_primary.is_(True)
    )
    if keep_contact_id is not None:
        q = q.filter(models.TenantContact.contact_id != keep_contact_id)
    q.update({models.TenantContact.is_primary: False}, synchronize_session=False)


def _get_contact(db: Session, tenant_id: int, contact_id: int) -> models.TenantContact:
    contact = db.get(models.TenantContact, contact_id)
    if not contact or contact.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.get("/{tenant_id}/contacts", response_model=list[schemas.TenantContactOut])
def list_contacts(tenant_id: int, db: Session = Depends(get_db)):
    _get_tenant(db, tenant_id)
    return (
        db.query(models.TenantContact)
        .filter(models.TenantContact.tenant_id == tenant_id)
        .order_by(models.TenantContact.is_primary.desc(), models.TenantContact.contact_name)
        .all()
    )


@router.post("/{tenant_id}/contacts", response_model=schemas.TenantContactOut, status_code=201)
def create_contact(tenant_id: int, payload: schemas.TenantContactCreate, db: Session = Depends(get_db)):
    _get_tenant(db, tenant_id)
    if payload.is_primary:
        _clear_other_primaries(db, tenant_id, None)  # only one primary contact per tenant
    contact = models.TenantContact(tenant_id=tenant_id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.put("/{tenant_id}/contacts/{contact_id}", response_model=schemas.TenantContactOut)
def update_contact(
    tenant_id: int, contact_id: int, payload: schemas.TenantContactUpdate, db: Session = Depends(get_db)
):
    contact = _get_contact(db, tenant_id, contact_id)
    if payload.is_primary:
        _clear_other_primaries(db, tenant_id, contact_id)
    for field, value in payload.model_dump().items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{tenant_id}/contacts/{contact_id}", status_code=204)
def delete_contact(tenant_id: int, contact_id: int, db: Session = Depends(get_db)):
    contact = _get_contact(db, tenant_id, contact_id)
    db.delete(contact)
    db.commit()
    return None
