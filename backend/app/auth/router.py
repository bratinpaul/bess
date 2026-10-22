"""Auth API (mounted without the deny-by-default dependency - these are the only public routes besides /api/health).

POST /api/auth/token            OAuth2 token endpoint, form-encoded:
                                  grant_type=password&username=<email>&password=...&client_id=...   -> login
                                  grant_type=refresh_token[&refresh_token=...]                      -> rotation
                                Web clients (client_id bess-web) get the refresh token ONLY as an HttpOnly, SameSite=Strict
                                cookie scoped to /api/auth (never readable by page scripts) and refresh with that cookie;
                                other clients (bess-batch) get it in the body as before.
                                returns {access_token, token_type, expires_in, refresh_expires_in, scope[, refresh_token]}
                                errors: 400 {error, error_description} (RFC 6749)
POST /api/auth/revoke           token=<refresh token> or the cookie -> revokes the session family (logout, RFC 7009)
POST /api/auth/change-password  {current_password, new_password} with a bearer token -> new session (clears mcp)
GET  /api/auth/me               the caller (from the access token)
GET  /api/auth/roles | /users   admin:read
"""
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.models import Privilege, Role, RolePrivilege, User, get_async_session
from app.auth.security import Principal, authenticated, require
from app.auth.settings import get_settings
from app.auth.users import UserManager, get_user_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
KNOWN_CLIENTS = {"bess-web", "bess-batch"}


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
    client_id: str = "bess-web"


def _client(request: Request) -> tuple[Optional[str], Optional[str]]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")


def _oauth_error(e: service.AuthError, clear_cookie: bool = False) -> JSONResponse:
    resp = JSONResponse(status_code=400, content={"error": e.error, "error_description": e.description}, headers=NO_STORE)
    if clear_cookie:
        _clear_cookie(resp)
    return resp


def _set_cookie(resp: JSONResponse, pair: service.TokenPair) -> None:
    s = get_settings()
    resp.set_cookie(s.cookie_name, pair.refresh_token, max_age=pair.refresh_expires_in, path=s.cookie_path,
                    httponly=True, secure=s.cookie_secure, samesite="strict")


def _clear_cookie(resp: JSONResponse) -> None:
    s = get_settings()
    resp.delete_cookie(s.cookie_name, path=s.cookie_path, httponly=True, secure=s.cookie_secure, samesite="strict")


def _token_response(pair: service.TokenPair, client_id: Optional[str]) -> JSONResponse:
    web = (client_id or "bess-web") in get_settings().web_clients
    resp = JSONResponse(content=pair.as_response(include_refresh=not web), headers=NO_STORE)
    if web:
        _set_cookie(resp, pair)
    return resp


def _present(value: Optional[str]) -> Optional[str]:
    return value if value and value not in ("null", "undefined") else None


@router.post("/token")
async def token(request: Request, grant_type: str = Form(...), username: Optional[str] = Form(None),
                password: Optional[str] = Form(None), refresh_token: Optional[str] = Form(None),
                client_id: Optional[str] = Form(None), scope: Optional[str] = Form(None),
                db: AsyncSession = Depends(get_async_session), manager: UserManager = Depends(get_user_manager)):
    ip, agent = _client(request)
    client_id = client_id or "bess-web"
    if client_id not in KNOWN_CLIENTS:
        return _oauth_error(service.AuthError("invalid_client", f"Unknown client '{client_id}'"))
    try:
        if grant_type == "password":
            if not username or not password:
                raise service.AuthError("invalid_request", "E-mail and password are required")
            pair = await service.login(db, manager, username, password, ip, agent)
        elif grant_type == "refresh_token":
            raw = request.cookies.get(get_settings().cookie_name) or _present(refresh_token)
            if not raw:
                raise service.AuthError("invalid_request", "No refresh token (sign in again)")
            pair = await service.refresh(db, raw, ip, agent)
        else:
            raise service.AuthError("unsupported_grant_type", f"grant_type '{grant_type}' is not supported")
    except service.AuthError as e:
        # a dead refresh cookie is removed so the browser stops sending it (a racing tab keeps its cookie)
        dead = grant_type == "refresh_token" and "already rotated" not in e.description
        return _oauth_error(e, clear_cookie=dead)
    return _token_response(pair, client_id)


@router.post("/revoke")
async def revoke(request: Request, token: Optional[str] = Form(None), token_type_hint: Optional[str] = Form(None),
                 client_id: Optional[str] = Form(None), db: AsyncSession = Depends(get_async_session)):
    ip, agent = _client(request)
    raw = _present(token) or request.cookies.get(get_settings().cookie_name)
    if raw:
        await service.revoke(db, raw, ip, agent)
    resp = JSONResponse(content={}, headers=NO_STORE)
    _clear_cookie(resp)
    return resp


@router.post("/change-password")
async def change_password(request: Request, body: ChangePasswordBody, principal: Principal = Depends(authenticated),
                          db: AsyncSession = Depends(get_async_session)):
    ip, agent = _client(request)
    try:
        pair = await service.change_password(db, principal.user_id, body.current_password, body.new_password, ip, agent)
    except service.AuthError as e:
        return _oauth_error(e)
    return _token_response(pair, body.client_id)


@router.get("/password-policy")
def password_policy():
    """Rules the change-password page shows (and the server enforces)."""
    return {"min_length": get_settings().password_min_length,
            "rules": [f"At least {get_settings().password_min_length} characters", "At least one letter and one digit",
                      "Not a common or default password (e.g. Password, Welcome1)", "Must not contain your e-mail name",
                      "Must differ from the current password"]}


@router.get("/me")
def me(principal: Principal = Depends(authenticated)):
    return {"user_id": principal.user_id, "email": principal.email, "name": principal.name, "role": principal.role,
            "role_name": principal.role_name, "permissions": sorted(principal.perms), "tenant_id": principal.tenant_id,
            "must_change_password": principal.must_change_password}


@router.get("/roles", dependencies=[Depends(require("admin:read"))])
async def roles(db: AsyncSession = Depends(get_async_session)):
    rows = await db.execute(select(Role.role_code, Role.role_name, Role.is_tenant_scoped, Privilege.code)
                            .join(RolePrivilege, RolePrivilege.role_id == Role.role_id, isouter=True)
                            .join(Privilege, Privilege.privilege_id == RolePrivilege.privilege_id, isouter=True)
                            .order_by(Role.role_id, Privilege.code))
    out: dict[str, dict] = {}
    for code, name, scoped, perm in rows:
        r = out.setdefault(code, {"role_code": code, "role_name": name, "is_tenant_scoped": scoped, "permissions": []})
        if perm:
            r["permissions"].append(perm)
    return list(out.values())


@router.get("/users", dependencies=[Depends(require("admin:read"))])
async def users(db: AsyncSession = Depends(get_async_session)):
    rows = await db.execute(select(User, Role.role_name).join(Role, Role.role_id == User.role_id).order_by(User.email))
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": name, "tenant_id": u.tenant_id,
             "is_active": u.is_active, "is_service_account": u.is_service_account,
             "must_change_password": u.must_change_password, "last_login_at": u.last_login_at,
             "locked": bool(u.locked_until)} for u, name in rows]
