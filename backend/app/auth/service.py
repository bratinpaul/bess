"""Token service: password login, refresh-token rotation with reuse detection, revocation, password change, audit.

Refresh tokens are opaque random strings; only their SHA-256 is stored. Every login starts a token *family* with an
absolute expiry (REFRESH_TOKEN_HOURS). Each refresh marks the presented token used and issues a successor in the same
family. Presenting an already-used token again (outside a short race window) is treated as theft: the whole family is
revoked and the user must log in again.
"""
import hashlib
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bess_common.observability import record_activity

from app.auth.models import AuthAudit, Privilege, RefreshToken, Role, RolePrivilege, User
from app.auth.security import create_access_token
from app.auth.settings import get_settings
from app.auth.users import UserManager, password_helper

log = logging.getLogger(__name__)
# rejected outright as new passwords (case-insensitive, also with trailing digits / punctuation)
BLOCKLIST = {"password", "passw0rd", "welcome", "admin", "administrator", "bess", "battery", "qwerty", "letmein",
             "changeme", "default", "secret", "12345678", "123456789", "1234567890", "iloveyou", "monkey", "dragon"}


class AuthError(Exception):
    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error, self.description = error, description


@dataclass
class TokenPair:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int

    def as_response(self, include_refresh: bool = True) -> dict:
        body = {"access_token": self.access_token, "token_type": "Bearer", "expires_in": self.expires_in,
                "refresh_expires_in": self.refresh_expires_in, "scope": "bess"}
        if include_refresh:
            body["refresh_token"] = self.refresh_token
        return body


@dataclass
class Credentials:  # what UserManager.authenticate reads (shape of OAuth2PasswordRequestForm)
    username: str
    password: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def audit(db: AsyncSession, event: str, success: bool, *, user: Optional[User] = None, email: Optional[str] = None,
                ip: Optional[str] = None, agent: Optional[str] = None, detail: Optional[dict] = None) -> None:
    who = user.email if user else email
    log.log(logging.INFO if success else logging.WARNING, f"auth {event}",
            extra={"event": f"auth.{event.lower()}", "outcome": "success" if success else "failed", "subject": who, "ip": ip})
    record_activity("AUTH", event, "success" if success else "failed", user_email=who, ip=ip, detail=detail)
    db.add(AuthAudit(event=event, success=success, user_id=user.id if user else None,
                     email=(user.email if user else email), ip=ip, user_agent=(agent or "")[:300], detail=detail))


async def role_and_perms(db: AsyncSession, user: User) -> tuple[Role, list[str]]:
    role = await db.get(Role, user.role_id)
    rows = await db.execute(select(Privilege.code).join(RolePrivilege, RolePrivilege.privilege_id == Privilege.privilege_id)
                            .where(RolePrivilege.role_id == user.role_id))
    return role, [r[0] for r in rows]


async def _user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    # exact, case-insensitive match - never LIKE/ILIKE, whose % and _ wildcards would match other accounts
    return (await db.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()


def _locked(user: Optional[User]) -> bool:
    return bool(user and user.locked_until and user.locked_until > _now())


async def _issue(db: AsyncSession, user: User, family_id: uuid.UUID, family_expires: datetime,
                 ip: Optional[str], agent: Optional[str]) -> tuple[TokenPair, RefreshToken]:
    role, perms = await role_and_perms(db, user)
    access, lifetime = create_access_token(
        user_id=str(user.id), email=user.email, name=user.full_name, role=role.role_code, role_name=role.role_name,
        perms=perms, tenant_id=user.tenant_id if role.is_tenant_scoped else None,
        must_change_password=user.must_change_password, is_service=user.is_service_account)
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(token_id=uuid.uuid4(), user_id=user.id, family_id=family_id, token_hash=_hash(raw),
                       expires_at=family_expires, user_agent=(agent or "")[:300], ip=ip)
    db.add(row)
    remaining = max(0, int((family_expires - _now()).total_seconds()))
    return TokenPair(access, lifetime, raw, remaining), row


async def login(db: AsyncSession, manager: UserManager, email: str, password: str, ip: Optional[str],
                agent: Optional[str]) -> TokenPair:
    s = get_settings()
    email = (email or "").strip()
    found = await _user_by_email(db, email)
    if _locked(found):
        await audit(db, "LOGIN_LOCKED", False, user=found, ip=ip, agent=agent)
        await db.commit()
        mins = int((found.locked_until - _now()).total_seconds() // 60) + 1
        raise AuthError("invalid_grant", f"Account locked after repeated failures - try again in {mins} min")
    user = await manager.authenticate(Credentials(email, password))  # timing-safe; also rehashes outdated hashes
    if user is None or not user.is_active:
        if found:
            found.failed_logins = (found.failed_logins or 0) + 1
            if found.failed_logins >= s.max_failures:
                found.locked_until = _now() + timedelta(minutes=s.lock_minutes)
                found.failed_logins = 0
                await audit(db, "LOCKED", False, user=found, ip=ip, agent=agent)
        await audit(db, "LOGIN_FAILED", False, user=found, email=email, ip=ip, agent=agent)
        await db.commit()
        if found is None:  # maybe a sign-up that isn't approved yet (explained only when the password matches it)
            from app.auth.signup import request_status_for_login
            why = await request_status_for_login(db, email, password)
            if why:
                raise AuthError("invalid_grant", why)
        raise AuthError("invalid_grant", "Invalid e-mail or password")
    user = await db.get(User, user.id)
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, _now()
    pair, _ = await _issue(db, user, uuid.uuid4(), _now() + timedelta(hours=s.refresh_hours), ip, agent)
    await audit(db, "LOGIN", True, user=user, ip=ip, agent=agent)
    await db.commit()
    return pair


async def refresh(db: AsyncSession, raw: str, ip: Optional[str], agent: Optional[str]) -> TokenPair:
    s = get_settings()
    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw or "")))).scalar_one_or_none()
    if row is None:
        raise AuthError("invalid_grant", "Unknown refresh token")
    user = await db.get(User, row.user_id)
    if row.revoked_at is not None:
        raise AuthError("invalid_grant", "Refresh token revoked - please log in again")
    if row.used_at is not None:
        if (_now() - row.used_at).total_seconds() <= s.refresh_race_seconds:
            # two refreshes raced (e.g. two tabs); the other one already got the successor
            raise AuthError("invalid_grant", "Refresh token already rotated")
        await _revoke_family(db, row.family_id)
        await audit(db, "REFRESH_REUSE", False, user=user, ip=ip, agent=agent, detail={"family": str(row.family_id)})
        await db.commit()
        raise AuthError("invalid_grant", "Refresh token reuse detected - the session was revoked")
    if row.expires_at <= _now():
        raise AuthError("invalid_grant", "Session expired - please log in again")
    if user is None or not user.is_active:
        raise AuthError("invalid_grant", "User is disabled")
    if _locked(user):
        await audit(db, "REFRESH_LOCKED", False, user=user, ip=ip, agent=agent)
        await db.commit()
        raise AuthError("invalid_grant", "Account is locked - please try again later")
    pair, successor = await _issue(db, user, row.family_id, row.expires_at, ip, agent)
    row.used_at, row.replaced_by = _now(), successor.token_id
    await audit(db, "REFRESH", True, user=user, ip=ip, agent=agent)
    await db.commit()
    return pair


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(update(RefreshToken).where(RefreshToken.family_id == family_id,
                                                RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))


async def revoke(db: AsyncSession, raw: str, ip: Optional[str], agent: Optional[str]) -> None:
    """Logout: revoke the presented refresh token's whole family (RFC 7009 - unknown tokens are not an error)."""
    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw or "")))).scalar_one_or_none()
    if row is None:
        return
    await _revoke_family(db, row.family_id)
    await audit(db, "LOGOUT", True, user=await db.get(User, row.user_id), ip=ip, agent=agent)
    await db.commit()


def password_problems(new: str, email: str) -> list[str]:
    """Policy: minimum length, a letter and a digit, not a common / default password, not the e-mail name."""
    s = get_settings()
    problems = []
    if len(new) < s.password_min_length:
        problems.append(f"at least {s.password_min_length} characters")
    if not re.search(r"[A-Za-z]", new) or not re.search(r"\d", new):
        problems.append("at least one letter and one digit")
    core = re.sub(r"[\d\W_]+$", "", new.lower())
    if new.lower() in BLOCKLIST or core in BLOCKLIST:
        problems.append("not a common or default password")
    local = email.split("@")[0].lower()
    if len(local) >= 3 and any(part and part in new.lower() for part in re.split(r"[._-]", local) if len(part) >= 3):
        problems.append("must not contain your e-mail name")
    return problems


async def change_password(db: AsyncSession, user_id: str, current: str, new: str, ip: Optional[str],
                          agent: Optional[str]) -> TokenPair:
    """Verify the current password, enforce the policy, store the new argon2 hash, clear must_change_password, end every
    other session of the user and start a fresh one."""
    s = get_settings()
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise AuthError("invalid_grant", "User is disabled")
    ok, _ = password_helper.verify_and_update(current or "", user.hashed_password)
    if not ok:
        await audit(db, "PASSWORD_CHANGE_FAILED", False, user=user, ip=ip, agent=agent, detail={"reason": "wrong current"})
        await db.commit()
        raise AuthError("invalid_grant", "Current password is incorrect")
    if new == current:
        raise AuthError("invalid_request", "The new password must differ from the current one")
    problems = password_problems(new or "", user.email)
    if problems:
        raise AuthError("invalid_request", "New password needs: " + "; ".join(problems))
    user.hashed_password = password_helper.hash(new)
    user.must_change_password = False
    await db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id,
                                                RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
    pair, _ = await _issue(db, user, uuid.uuid4(), _now() + timedelta(hours=s.refresh_hours), ip, agent)
    await audit(db, "PASSWORD_CHANGED", True, user=user, ip=ip, agent=agent)
    await db.commit()
    return pair
