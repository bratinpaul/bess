"""Async SQLAlchemy models of the battery_users schema (see migrations/2026_10_21_battery_users.py).

They use their own declarative base and an asyncpg engine, because fastapi-users needs an async session; the rest of the
backend keeps its sync psycopg2 engine.
"""
import os
import uuid
from datetime import datetime
from typing import AsyncGenerator, Optional

from dotenv import load_dotenv
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()
SCHEMA = "battery_users"


class AuthBase(DeclarativeBase):
    pass


class Role(AuthBase):
    __tablename__ = "role"
    __table_args__ = {"schema": SCHEMA}
    role_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    role_code: Mapped[str] = mapped_column(Text, unique=True)
    role_name: Mapped[str] = mapped_column(Text, unique=True)
    is_tenant_scoped: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(Text)


class Privilege(AuthBase):
    __tablename__ = "privilege"
    __table_args__ = {"schema": SCHEMA}
    privilege_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text, Computed("resource || ':' || action"))
    module_label: Mapped[Optional[str]] = mapped_column(Text)


class RolePrivilege(AuthBase):
    __tablename__ = "role_privilege"
    __table_args__ = {"schema": SCHEMA}
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(f"{SCHEMA}.role.role_id"), primary_key=True)
    privilege_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{SCHEMA}.privilege.privilege_id"), primary_key=True)


class User(SQLAlchemyBaseUserTableUUID, AuthBase):
    """fastapi-users user (id, email, hashed_password, is_active, is_superuser, is_verified) + BESS fields."""
    __tablename__ = "app_user"
    __table_args__ = {"schema": SCHEMA}
    full_name: Mapped[Optional[str]] = mapped_column(Text)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(f"{SCHEMA}.role.role_id"))
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer)
    is_service_account: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RefreshToken(AuthBase):
    __tablename__ = "refresh_token"
    __table_args__ = {"schema": SCHEMA}
    token_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.app_user.id"))
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(Text)


class AuthAudit(AuthBase):
    __tablename__ = "auth_audit"
    __table_args__ = {"schema": SCHEMA}
    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    email: Mapped[Optional[str]] = mapped_column(String)
    event: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean)
    ip: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB)


def _async_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")


# AUTH_DB_NULLPOOL=1 (tests): no pooling, because each TestClient runs its own event loop and asyncpg connections are
# bound to the loop that opened them
if os.getenv("AUTH_DB_NULLPOOL") == "1":
    from sqlalchemy.pool import NullPool
    async_engine = create_async_engine(_async_url(), poolclass=NullPool)
else:
    async_engine = create_async_engine(_async_url(), pool_pre_ping=True, pool_size=5)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


class AccessRequest(AuthBase):
    """Self-service sign-up waiting for (or decided by) an Admin - see migrations/2026_10_21_access_request.py."""
    __tablename__ = "access_request"
    __table_args__ = {"schema": SCHEMA}
    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(String(320))
    organisation: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    hashed_password: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(Text, default="PENDING")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_ip: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[Optional[str]] = mapped_column(Text)
    role_id: Mapped[Optional[int]] = mapped_column(SmallInteger)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer)
    decision_note: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
