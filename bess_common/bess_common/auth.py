"""JWT access tokens (RS256) and the FastAPI dependencies that enforce them - one implementation for the backend (which
signs tokens) and the ML service (which only verifies them).

    authenticated        router-include-level dependency: every route needs a valid bearer token (deny by default);
                         a token flagged "must change password" only reaches the PASSWORD_CHANGE_PATHS
    require("res:act")   per-route permission check against the token's `perms` claim (the RBAC matrix)
    Principal            the caller, as read from the token (no database round trip per request)
    set_forbidden_hook   each service registers a writer for refused requests (403) -> battery_users.auth_audit
    set_freshness_check  each service registers a check of the token's role / user versions (rv / uv) against the
                         database (bess_common.rbac_store.TokenFreshness); a stale token gets 401 and the client refreshes
    enforced_permissions every permission code some require() / permission_by_method() of this process checks

Keys are read once per process (JWT_PRIVATE_KEY_PATH only where tokens are signed, JWT_PUBLIC_KEY_PATH everywhere).

Access-token claims: iss, aud, sub (user id), email, name, role, role_name, perms, tenant_id (tenant-scoped roles only),
mcp (must change password), svc (service account), rv (role version), uv (user version), iat, exp, jti, typ = "access".
"""
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Callable, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bess_common.observability import set_user

log = logging.getLogger("bess.auth")  # JSON output is configured by bess_common.observability.setup_logging

ROOT = Path(__file__).resolve().parents[2]
PASSWORD_CHANGE_PATHS = ("/api/auth/",)  # all a must-change-password token may call (me, change-password, revoke)
bearer = HTTPBearer(auto_error=False)
_ENFORCED: set[str] = set()  # filled at import time by require() / permission_by_method()


def enforced_permissions() -> frozenset:
    """The permission codes this process checks - registered into battery_users.privilege at start-up."""
    return frozenset(_ENFORCED)


class TokenSettings:
    def __init__(self) -> None:
        self.private_key_path = Path(os.getenv("JWT_PRIVATE_KEY_PATH", ROOT / "keys" / "jwt_private.pem"))
        self.public_key_path = Path(os.getenv("JWT_PUBLIC_KEY_PATH", ROOT / "keys" / "jwt_public.pem"))
        self.issuer = os.getenv("JWT_ISSUER", "bess-auth")
        self.audience = os.getenv("JWT_AUDIENCE", "bess-api")
        self.algorithm = "RS256"
        self.access_minutes = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))

    @cached_property
    def private_key(self) -> str:  # read once - only the backend ever asks for it
        return self.private_key_path.read_text(encoding="utf-8")

    @cached_property
    def public_key(self) -> str:  # read once - not per request
        return self.public_key_path.read_text(encoding="utf-8")


@lru_cache
def token_settings() -> TokenSettings:
    return TokenSettings()


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: Optional[str]
    role: str
    role_name: str
    perms: frozenset = field(default_factory=frozenset)
    tenant_id: Optional[int] = None
    must_change_password: bool = False
    is_service: bool = False
    role_version: Optional[int] = None
    user_version: Optional[int] = None

    def can(self, perm: str) -> bool:
        return perm in self.perms


def create_access_token(*, user_id: str, email: str, name: Optional[str], role: str, role_name: str, perms: list[str],
                        tenant_id: Optional[int], must_change_password: bool, is_service: bool,
                        role_version: Optional[int] = None, user_version: Optional[int] = None,
                        lifetime_seconds: Optional[int] = None) -> tuple[str, int]:
    s = token_settings()
    now = datetime.now(timezone.utc)
    lifetime = lifetime_seconds if lifetime_seconds is not None else s.access_minutes * 60
    claims = {
        "iss": s.issuer, "aud": s.audience, "sub": user_id, "email": email, "name": name, "role": role,
        "role_name": role_name, "perms": sorted(perms), "tenant_id": tenant_id, "mcp": must_change_password,
        "svc": is_service, "rv": role_version, "uv": user_version, "iat": now, "exp": now + timedelta(seconds=lifetime), "jti": uuid.uuid4().hex, "typ": "access",
    }
    return jwt.encode(claims, s.private_key, algorithm=s.algorithm), lifetime


def _unauthorized(message: str, error: str = "invalid_request") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message,
                         headers={"WWW-Authenticate": f'Bearer error="{error}"'})


def decode_access_token(token: str) -> Principal:
    s = token_settings()
    try:
        c = jwt.decode(token, s.public_key, algorithms=[s.algorithm], audience=s.audience, issuer=s.issuer,
                       options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Access token expired", "invalid_token")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid access token", "invalid_token")
    if c.get("typ") != "access":
        raise _unauthorized("Not an access token", "invalid_token")
    return Principal(user_id=c["sub"], email=c.get("email", ""), name=c.get("name"), role=c.get("role", ""),
                     role_name=c.get("role_name", ""), perms=frozenset(c.get("perms") or []), tenant_id=c.get("tenant_id"),
                     must_change_password=bool(c.get("mcp")), is_service=bool(c.get("svc")),
                     role_version=c.get("rv"), user_version=c.get("uv"))


# ------------------------------------------------------------------ refused requests (403)
_forbidden_hook: Optional[Callable[[Principal, Request, str, list[str]], None]] = None


def set_forbidden_hook(hook: Callable[[Principal, Request, str, list[str]], None]) -> None:
    """hook(principal, request, reason, missing_permissions) - called for every 403 (e.g. to write auth_audit)."""
    global _forbidden_hook
    _forbidden_hook = hook


def _forbid(principal: Principal, request: Request, reason: str, missing: list[str], detail: str) -> HTTPException:
    log.warning("forbidden", extra={"event": "auth.forbidden", "reason": reason, "missing": missing,
                                    "method": request.method, "path": request.url.path})
    if _forbidden_hook:
        try:
            _forbidden_hook(principal, request, reason, missing)
        except Exception as exc:  # noqa: BLE001 - auditing must never break the request
            log.error("forbidden hook failed: %s", exc)
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ------------------------------------------------------------------ token freshness (role / user versions)
_freshness_check: Optional[Callable[[Principal], Optional[str]]] = None


def set_freshness_check(check: Callable[[Principal], Optional[str]]) -> None:
    """check(principal) -> None if the token's role / user versions are current, else a reason ("role_changed", ...)."""
    global _freshness_check
    _freshness_check = check


# ------------------------------------------------------------------ FastAPI dependencies
def authenticated(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> Principal:
    """Deny by default: no or invalid bearer token -> 401. A token that still has to change its password is refused (403)
    everywhere except the auth endpoints."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized("Not authenticated")
    principal = decode_access_token(creds.credentials)
    if _freshness_check is not None:
        reason = _freshness_check(principal)
        if reason:  # role / grants / user changed since the token was issued: the client refreshes and retries
            log.info("stale token", extra={"event": "auth.token_stale", "reason": reason, "user": principal.email})
            raise _unauthorized(f"Access token is out of date ({reason}) - refresh it", "invalid_token")
    if principal.must_change_password and not request.url.path.startswith(PASSWORD_CHANGE_PATHS):
        raise _forbid(principal, request, "PASSWORD_CHANGE_REQUIRED", [],
                      "Password change required - set a new password before using the platform")
    request.state.principal = principal
    set_user(principal.email, principal.role)  # every log line of this request carries the caller
    return principal


def require(*perms: str):
    """Route dependency: the caller needs every listed permission (e.g. require("master.asset:write"))."""
    def check(request: Request, principal: Principal = Depends(authenticated)) -> Principal:
        missing = [p for p in perms if not principal.can(p)]
        if missing:
            raise _forbid(principal, request, "MISSING_PERMISSION", missing,
                          f"Your role ({principal.role_name}) lacks permission: {', '.join(missing)}")
        return principal
    check.required_permissions = perms  # read by the route-coverage tests
    _ENFORCED.update(perms)
    return check


# ------------------------------------------------------------------ router-level RBAC (method + path rules)
CRUD_ACTIONS = {"GET": "read", "HEAD": "read", "OPTIONS": "read", "POST": "write", "PUT": "write", "PATCH": "write",
                "DELETE": "delete"}


def crud(resource: str, **overrides: str) -> dict[str, str]:
    """{method: permission} for a CRUD resource, e.g. crud("master.asset") -> GET master.asset:read, POST ...:write,
    DELETE ...:delete. Overrides replace a method's permission (full code), e.g. crud("batch", POST="batch:execute")."""
    rules = {m: f"{resource}:{a}" for m, a in CRUD_ACTIONS.items()}
    rules.update({m.upper(): p for m, p in overrides.items()})
    return rules


def permission_by_method(rules: dict[str, str], path_rules: tuple[tuple[str, str, str], ...] = (), name: str = ""):
    """Router-include-level RBAC dependency. The permission is chosen per request: the first path rule
    (method or "*", regex searched in the URL path, permission) that matches, else rules[method]. A method with no rule is
    refused (deny by default). Used as app.include_router(r, dependencies=[Depends(authenticated), Depends(dep)])."""
    import re
    compiled = tuple((m.upper(), re.compile(rx), perm) for m, rx, perm in path_rules)
    _ENFORCED.update(rules.values())
    _ENFORCED.update(perm for _, _, perm in path_rules)

    def check(request: Request, principal: Principal = Depends(authenticated)) -> Principal:
        method, path = request.method.upper(), request.url.path
        perm = next((p for m, rx, p in compiled if m in ("*", method) and rx.search(path)), None) or rules.get(method)
        if perm is None:
            raise _forbid(principal, request, "NO_RULE", [], f"{method} is not allowed here")
        if not principal.can(perm):
            raise _forbid(principal, request, "MISSING_PERMISSION", [perm],
                          f"Your role ({principal.role_name}) lacks permission: {perm}")
        return principal

    check.rbac_rules = {"rules": dict(rules), "path_rules": path_rules, "name": name}  # read by tests / docs
    check.__name__ = f"rbac_{name or 'router'}"
    return check
