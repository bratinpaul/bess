from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, func, Identity, Numeric, String

from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

TENANT_STATUSES = ("active", "suspended", "inactive")


class Tenant(Base):
    __tablename__ = "tenant"

    tenant_id = Column(BigInteger, Identity(), primary_key=True)
    name = Column(String(200), nullable=False)
    legal_name = Column(String(200))
    tenant_type = Column(String(50))
    address_line1 = Column(String(200))
    address_line2 = Column(String(200))
    city = Column(String(100))
    state_province = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100))
    phone = Column(String(30))
    email = Column(String(200))
    # the tenant_status enum type already exists in Postgres; SQLAlchemy must not create it
    status = Column(
        Enum(*TENANT_STATUSES, name="tenant_status", create_type=False),
        nullable=False,
        server_default="active",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)


class TenantContact(Base):
    """People at a tenant; at most one is the primary contact (kept so by the API)."""

    __tablename__ = "tenant_contact"

    contact_id = Column(BigInteger, Identity(), primary_key=True)
    # ON DELETE CASCADE in the database: a tenant's contacts go with it
    tenant_id = Column(BigInteger, ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    contact_name = Column(String(200), nullable=False)
    role = Column(String(50))
    phone = Column(String(30))
    email = Column(String(200))
    is_primary = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TenantSite(Base):
    """Which tenants own a site, and how much (a site can have several owners, one primary)."""

    __tablename__ = "tenant_site"

    tenant_id = Column(BigInteger, ForeignKey("tenant.tenant_id", ondelete="CASCADE"), primary_key=True)
    site_id = Column(BigInteger, ForeignKey("site.site_id", ondelete="CASCADE"), primary_key=True)
    ownership_pct = Column(Numeric)
    is_primary_owner = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
