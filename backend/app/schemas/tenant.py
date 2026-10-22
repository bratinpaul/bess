import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TenantStatus = Literal["active", "suspended", "inactive"]

# pragmatic checks: one @ and a dotted domain, no spaces; the database keeps tenant emails unique
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PHONE_PATTERN = r"^[0-9+()\-.\s]{5,30}$"


def _blank_to_none(value, field_name: str, required: tuple[str, ...]):
    """Trim text; store empty optional fields as NULL (so unique indexes ignore them)."""
    if isinstance(value, str):
        value = value.strip()
        if value == "" and field_name not in required:
            return None
    return value


def _check_email(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if not re.match(EMAIL_PATTERN, value):
        raise ValueError("Enter a valid email address, e.g. ops@example.com")
    return value.lower()


def _check_phone(value: Optional[str]) -> Optional[str]:
    if value is not None and not re.match(PHONE_PATTERN, value):
        raise ValueError("Phone may contain only digits, spaces and + ( ) - . (5-30 characters)")
    return value


# ---------------------------------------------------------------- tenant


class TenantBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: Optional[str] = Field(default=None, max_length=200)
    tenant_type: Optional[str] = Field(default=None, max_length=50)
    address_line1: Optional[str] = Field(default=None, max_length=200)
    address_line2: Optional[str] = Field(default=None, max_length=200)
    city: Optional[str] = Field(default=None, max_length=100)
    state_province: Optional[str] = Field(default=None, max_length=100)
    postal_code: Optional[str] = Field(default=None, max_length=20)
    country: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)
    status: TenantStatus = "active"

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, value, info):
        return _blank_to_none(value, info.field_name, ("name", "status"))

    @field_validator("email")
    @classmethod
    def check_email(cls, value: Optional[str]) -> Optional[str]:
        return _check_email(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: Optional[str]) -> Optional[str]:
        return _check_phone(value)


# ---------------------------------------------------------------- contacts


class TenantContactBase(BaseModel):
    contact_name: str = Field(min_length=1, max_length=200)
    role: Optional[str] = Field(default=None, max_length=50)
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)
    is_primary: bool = False

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, value, info):
        return _blank_to_none(value, info.field_name, ("contact_name",))

    @field_validator("email")
    @classmethod
    def check_email(cls, value: Optional[str]) -> Optional[str]:
        return _check_email(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: Optional[str]) -> Optional[str]:
        return _check_phone(value)


class TenantContactCreate(TenantContactBase):
    pass


class TenantContactUpdate(TenantContactBase):
    pass


class TenantContactIn(TenantContactBase):
    """A contact sent with the tenant form: contact_id set = existing contact, missing = new one."""

    contact_id: Optional[int] = None


def _check_contacts(contacts: Optional[list[TenantContactIn]]) -> None:
    if not contacts:
        return
    if sum(1 for c in contacts if c.is_primary) > 1:
        raise ValueError("A tenant can have only one primary contact")
    ids = [c.contact_id for c in contacts if c.contact_id is not None]
    if len(ids) != len(set(ids)):
        raise ValueError("The same contact is listed twice")


class TenantCreate(TenantBase):
    contacts: list[TenantContactIn] = []

    @model_validator(mode="after")
    def check_contacts(self):
        _check_contacts(self.contacts)
        return self


class TenantUpdate(TenantBase):
    # None leaves the tenant's contacts as they are; a list (even empty) makes them match it
    contacts: Optional[list[TenantContactIn]] = None

    @model_validator(mode="after")
    def check_contacts(self):
        _check_contacts(self.contacts)
        return self


class TenantContactOut(TenantContactBase):
    model_config = ConfigDict(from_attributes=True)

    contact_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- ownership (tenant_site)


class TenantSiteLink(BaseModel):
    """A site owned (in part) by a tenant, as shown on the tenant."""

    site_id: int
    site_code: str
    site_name: str
    ownership_pct: Optional[Decimal] = None
    is_primary_owner: bool


class TenantOut(TenantBase):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: int
    created_at: datetime
    updated_at: datetime
    site_count: int = 0
    contact_count: int = 0
    primary_contact_name: Optional[str] = None
    source_uuid: Optional[UUID] = None


class TenantDetail(TenantOut):
    contacts: list[TenantContactOut] = []
    sites: list[TenantSiteLink] = []
