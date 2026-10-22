from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SiteOwnerIn(BaseModel):
    """One tenant's ownership of a site (a row of tenant_site)."""

    tenant_id: int
    ownership_pct: Optional[Decimal] = Field(default=None, gt=0, le=100, decimal_places=2)
    is_primary_owner: bool = False


class SiteOwnerOut(SiteOwnerIn):
    tenant_name: str
    tenant_status: str


def _check_owners(owners: Optional[list[SiteOwnerIn]]) -> None:
    if not owners:
        return
    ids = [o.tenant_id for o in owners]
    if len(ids) != len(set(ids)):
        raise ValueError("Each tenant can be listed only once as an owner of a site")
    if sum(1 for o in owners if o.is_primary_owner) > 1:
        raise ValueError("A site can have only one primary owner")
    total = sum((o.ownership_pct or Decimal(0)) for o in owners)
    if total > 100:
        raise ValueError(f"Ownership adds up to {total}% — it cannot exceed 100%")


class SiteBase(BaseModel):
    site_code: str
    site_name: str
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    address: Optional[str] = None
    rated_power_mw: Optional[Decimal] = Field(default=None, gt=0)
    rated_energy_mwh: Optional[Decimal] = Field(default=None, gt=0)
    commission_date: Optional[date] = None
    grid_operator: Optional[str] = None
    state: Optional[str] = None
    grid_voltage_kv: Optional[Decimal] = Field(default=None, gt=0)


class SiteCreate(SiteBase):
    timezone: str = "UTC"
    owners: list[SiteOwnerIn] = []

    @model_validator(mode="after")
    def check_owners(self):
        _check_owners(self.owners)
        return self


class SiteUpdate(SiteBase):
    # None leaves the site's owners as they are; a list (even empty) replaces them
    owners: Optional[list[SiteOwnerIn]] = None

    @model_validator(mode="after")
    def check_owners(self):
        _check_owners(self.owners)
        return self


class SiteOut(SiteBase):
    model_config = ConfigDict(from_attributes=True)

    site_id: int
    created_at: Optional[datetime] = None
    timezone: str
    owners: list[SiteOwnerOut] = []
    primary_owner_name: Optional[str] = None
    source_uuid: Optional[UUID] = None
