"""User management for admins: privileges, roles, the RBAC matrix (what goes into the JWT) and user accounts.

Privileges (admin:read / admin:write / admin:delete)
GET    /api/admin/privileges                 catalogue: source (system / custom), enforced, registered_by, roles holding it
POST   /api/admin/privileges                 add a custom privilege (protects nothing until code checks it)
PATCH  /api/admin/privileges/{id}            module label / description
DELETE /api/admin/privileges/{id}            custom only, and only when no role holds it
Roles
GET    /api/admin/roles                      roles with user and privilege counts
POST   /api/admin/roles                      create (optionally copying another role's grants)
PATCH  /api/admin/roles/{code}               name / description / tenant-scoped
DELETE /api/admin/roles/{code}               not system roles, and only when no user holds it
RBAC matrix
GET    /api/admin/rbac-matrix                roles x privileges with the grants and the locked cells
PUT    /api/admin/rbac-matrix                {added: [[role, code], ...], removed: [...]} in one transaction
GET    /api/admin/token-preview/{code}       the perms claim a user of that role gets
GET    /api/admin/rbac-changes               change history (audit:read)
Users
GET    /api/admin/users | /api/admin/tenants
POST   /api/admin/users                      create; returns a one-time temporary password (must change at sign-in)
PATCH  /api/admin/users/{id}                 full name / role / tenant / active
POST   /api/admin/users/{id}/unlock | /reset-password

How changes reach tokens: a grant change bumps the role's `version`, a user change bumps the user's `token_version` (and
revokes their refresh tokens when they lose access); tokens carry both (rv / uv), stale ones are refused with 401 and
the frontend refreshes - see bess_common.rbac_store.

Safeguards: ADMIN keeps every admin:* privilege; system roles can't be deleted; at least one active user must keep
admin:write; admins can't change their own role or disable themselves; anything still in use can't be deleted.
Every change -> battery_users.rbac_change (before / after) and the Activity Log.
"""
import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.freshness import freshness
from app.auth.models import Privilege, RbacChange, RefreshToken, Role, RolePrivilege, User, get_async_session
from app.auth.security import Principal, require
from app.auth.service import password_problems
from app.auth.users import password_helper
from bess_common.observability import current_context, record_activity

router = APIRouter(prefix="/api/admin", tags=["user-management"])
READ, WRITE, DELETE = require("admin:read"), require("admin:write"), require("admin:delete")
ACTIONS = ("read", "write", "delete", "execute", "approve")
RESOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
ROLE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")
ADMIN_ROLE = "ADMIN"
ADMIN_RESOURCE = "admin"  # ADMIN always keeps admin:read / write / delete


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


async def _change(db: AsyncSession, who: Principal, entity: str, action: str, target: str,
                  before: Optional[dict] = None, after: Optional[dict] = None) -> None:
    db.add(RbacChange(actor_email=who.email, request_id=current_context().get("request_id"), entity=entity,
                      action=action, target=target, before=before, after=after))
    record_activity("AUTH", f"rbac.{entity}.{action}", "success", user_email=who.email, role=who.role,
                    operation=f"{entity}:{target}", detail={"before": before, "after": after})


async def _commit(db: AsyncSession) -> None:
    await db.commit()
    freshness.invalidate()  # this process sees the new versions immediately


async def _bump_roles(db: AsyncSession, role_ids: set[int]) -> None:
    if role_ids:
        await db.execute(update(Role).where(Role.role_id.in_(role_ids))
                         .values(version=Role.version + 1, updated_at=func.now()))


async def _bump_user(db: AsyncSession, user: User, revoke: bool) -> None:
    user.token_version = (user.token_version or 1) + 1
    if revoke:  # signs the user out everywhere (refresh tokens can't be used any more)
        await db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                         .values(revoked_at=_now()))


async def _admins_left(db: AsyncSession) -> int:
    """Active human users whose role holds admin:write - must stay >= 1."""
    q = (select(func.count(User.id)).join(RolePrivilege, RolePrivilege.role_id == User.role_id)
         .join(Privilege, Privilege.privilege_id == RolePrivilege.privilege_id)
         .where(Privilege.code == "admin:write", User.is_active.is_(True), User.is_service_account.is_(False)))
    return (await db.execute(q)).scalar() or 0


async def _role(db: AsyncSession, code: str) -> Role:
    role = (await db.execute(select(Role).where(Role.role_code == code))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail=f"Role {code} not found")
    return role


async def _tenant_exists(db: AsyncSession, tenant_id: int) -> bool:
    return bool((await db.execute(text("SELECT 1 FROM battery_master.tenant WHERE tenant_id = :t"),
                                  {"t": tenant_id})).first())


def _temp_password(email: str) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(14)) + secrets.choice(string.digits) + "!"
        if any(c.isalpha() for c in pw) and not password_problems(pw, email):
            return pw


# ================================================================ privileges
class PrivilegeIn(BaseModel):
    resource: str = Field(min_length=2, max_length=60)
    action: Literal["read", "write", "delete", "execute", "approve"]
    module_label: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)


class PrivilegePatch(BaseModel):
    module_label: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)


def _priv_out(p: Privilege, holders: list[str]) -> dict:
    return {"privilege_id": p.privilege_id, "code": p.code, "resource": p.resource, "action": p.action,
            "module_label": p.module_label, "description": p.description, "source": p.source, "enforced": p.enforced,
            "registered_by": list(p.registered_by or []), "roles": holders}


async def _holders(db: AsyncSession) -> dict[int, list[str]]:
    rows = await db.execute(select(RolePrivilege.privilege_id, Role.role_code)
                            .join(Role, Role.role_id == RolePrivilege.role_id).order_by(Role.role_id))
    out: dict[int, list[str]] = {}
    for pid, code in rows:
        out.setdefault(pid, []).append(code)
    return out


@router.get("/privileges", dependencies=[Depends(READ)])
async def list_privileges(db: AsyncSession = Depends(get_async_session)):
    holders = await _holders(db)
    rows = (await db.execute(select(Privilege).order_by(Privilege.resource, Privilege.action))).scalars()
    return [_priv_out(p, holders.get(p.privilege_id, [])) for p in rows]


@router.post("/privileges", status_code=201)
async def add_privilege(body: PrivilegeIn, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    resource = body.resource.strip().lower()
    if not RESOURCE_RE.match(resource):
        raise HTTPException(status_code=422, detail="Resource: lower-case words separated by dots, e.g. 'reports.export'")
    if (await db.execute(select(Privilege).where(Privilege.resource == resource, Privilege.action == body.action))).first():
        raise _conflict(f"Privilege {resource}:{body.action} already exists")
    p = Privilege(resource=resource, action=body.action, module_label=body.module_label, description=body.description,
                  source="custom", enforced=False, registered_by=[])
    db.add(p)
    await db.flush()
    await _change(db, who, "privilege", "create", f"{resource}:{body.action}",
                  after={"module_label": body.module_label, "description": body.description})
    await _commit(db)
    await db.refresh(p)
    return _priv_out(p, [])


@router.patch("/privileges/{privilege_id}")
async def edit_privilege(privilege_id: int, body: PrivilegePatch, who: Principal = Depends(WRITE),
                         db: AsyncSession = Depends(get_async_session)):
    p = await db.get(Privilege, privilege_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Privilege not found")
    before = {"module_label": p.module_label, "description": p.description}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    await _change(db, who, "privilege", "update", p.code, before,
                  {"module_label": p.module_label, "description": p.description})
    await _commit(db)
    return _priv_out(p, (await _holders(db)).get(p.privilege_id, []))


@router.delete("/privileges/{privilege_id}")
async def delete_privilege(privilege_id: int, who: Principal = Depends(DELETE), db: AsyncSession = Depends(get_async_session)):
    p = await db.get(Privilege, privilege_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Privilege not found")
    if p.source != "custom":
        raise _conflict(f"{p.code} is enforced by the code - system privileges can't be deleted")
    held = (await db.execute(select(func.count()).select_from(RolePrivilege)
                             .where(RolePrivilege.privilege_id == privilege_id))).scalar()
    if held:
        raise _conflict(f"{p.code} is granted to {held} role(s) - revoke it in the RBAC matrix first")
    code = p.code
    await db.delete(p)
    await _change(db, who, "privilege", "delete", code, before={"code": code})
    await _commit(db)
    return {"deleted": code}


# ================================================================ roles
class RoleIn(BaseModel):
    role_code: str = Field(min_length=2, max_length=40)
    role_name: str = Field(min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    is_tenant_scoped: bool = False
    copy_from: Optional[str] = None


class RolePatch(BaseModel):
    role_name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    is_tenant_scoped: Optional[bool] = None


async def _roles_out(db: AsyncSession) -> list[dict]:
    users = dict((await db.execute(select(User.role_id, func.count(User.id)).group_by(User.role_id))).all())
    privs = dict((await db.execute(select(RolePrivilege.role_id, func.count()).group_by(RolePrivilege.role_id))).all())
    rows = (await db.execute(select(Role).order_by(Role.role_id))).scalars()
    return [{"role_code": r.role_code, "role_name": r.role_name, "description": r.description,
             "is_tenant_scoped": r.is_tenant_scoped, "is_system": r.is_system, "version": r.version,
             "updated_at": r.updated_at, "user_count": users.get(r.role_id, 0), "privilege_count": privs.get(r.role_id, 0)}
            for r in rows]


@router.get("/roles", dependencies=[Depends(READ)])
async def list_roles(db: AsyncSession = Depends(get_async_session)):
    return await _roles_out(db)


@router.post("/roles", status_code=201)
async def create_role(body: RoleIn, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    code = body.role_code.strip().upper()
    if not ROLE_RE.match(code):
        raise HTTPException(status_code=422, detail="Role code: upper-case letters, digits and _, e.g. SITE_MANAGER")
    if (await db.execute(select(Role.role_id).where((Role.role_code == code) | (Role.role_name == body.role_name.strip())))).first():
        raise _conflict("A role with this code or name already exists")
    role = Role(role_code=code, role_name=body.role_name.strip(), description=body.description,
                is_tenant_scoped=body.is_tenant_scoped, is_system=False, version=1)
    db.add(role)
    await db.flush()
    copied = []
    if body.copy_from:
        src = await _role(db, body.copy_from)
        rows = (await db.execute(select(RolePrivilege.privilege_id, Privilege.code)
                                 .join(Privilege, Privilege.privilege_id == RolePrivilege.privilege_id)
                                 .where(RolePrivilege.role_id == src.role_id))).all()
        for pid, pcode in rows:
            db.add(RolePrivilege(role_id=role.role_id, privilege_id=pid))
            copied.append(pcode)
    await _change(db, who, "role", "create", code, after={"role_name": role.role_name, "is_tenant_scoped": role.is_tenant_scoped,
                                                         "copied_from": body.copy_from, "privileges": sorted(copied)})
    await _commit(db)
    return next(r for r in await _roles_out(db) if r["role_code"] == code)


@router.patch("/roles/{code}")
async def edit_role(code: str, body: RolePatch, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    role = await _role(db, code)
    before = {"role_name": role.role_name, "description": role.description, "is_tenant_scoped": role.is_tenant_scoped}
    data = body.model_dump(exclude_unset=True)
    if data.get("is_tenant_scoped") and not role.is_tenant_scoped:
        missing = (await db.execute(select(func.count(User.id)).where(User.role_id == role.role_id,
                                                                      User.tenant_id.is_(None)))).scalar()
        if missing:
            raise _conflict(f"{missing} user(s) with this role have no tenant - give them one first")
    if data.get("is_tenant_scoped") is False and role.role_code == "TENANT_VIEWER":
        raise _conflict("TENANT_VIEWER must stay tenant-scoped")
    if "role_name" in data:
        data["role_name"] = data["role_name"].strip()
        clash = (await db.execute(select(Role.role_id).where(Role.role_name == data["role_name"],
                                                             Role.role_id != role.role_id))).first()
        if clash:
            raise _conflict("Another role already has this name")
    for k, v in data.items():
        setattr(role, k, v)
    if "is_tenant_scoped" in data and data["is_tenant_scoped"] != before["is_tenant_scoped"]:
        await _bump_roles(db, {role.role_id})  # the tenant_id claim changes
    await _change(db, who, "role", "update", role.role_code, before,
                  {"role_name": role.role_name, "description": role.description, "is_tenant_scoped": role.is_tenant_scoped})
    await _commit(db)
    return next(r for r in await _roles_out(db) if r["role_code"] == role.role_code)


@router.delete("/roles/{code}")
async def delete_role(code: str, who: Principal = Depends(DELETE), db: AsyncSession = Depends(get_async_session)):
    role = await _role(db, code)
    if role.is_system:
        raise _conflict(f"{code} is a system role and can't be deleted")
    users = (await db.execute(select(func.count(User.id)).where(User.role_id == role.role_id))).scalar()
    if users:
        raise _conflict(f"{users} user(s) still have the role {code} - move them to another role first")
    pending = (await db.execute(text("SELECT count(*) FROM battery_users.access_request WHERE role_id = :r"),
                                {"r": role.role_id})).scalar()
    if pending:
        raise _conflict(f"{pending} access request(s) refer to {code}")
    grants = (await db.execute(select(Privilege.code).join(RolePrivilege, RolePrivilege.privilege_id == Privilege.privilege_id)
                               .where(RolePrivilege.role_id == role.role_id))).scalars().all()
    await db.execute(delete(RolePrivilege).where(RolePrivilege.role_id == role.role_id))
    await db.delete(role)
    await _change(db, who, "role", "delete", code, before={"role_name": role.role_name, "privileges": sorted(grants)})
    await _commit(db)
    return {"deleted": code}


# ================================================================ RBAC matrix
class MatrixChange(BaseModel):
    added: list[tuple[str, str]] = Field(default_factory=list, max_length=2000)
    removed: list[tuple[str, str]] = Field(default_factory=list, max_length=2000)


async def _grants(db: AsyncSession) -> dict[str, list[str]]:
    rows = await db.execute(select(Role.role_code, Privilege.code)
                            .join(RolePrivilege, RolePrivilege.role_id == Role.role_id)
                            .join(Privilege, Privilege.privilege_id == RolePrivilege.privilege_id))
    out: dict[str, list[str]] = {}
    for role, code in rows:
        out.setdefault(role, []).append(code)
    return {k: sorted(v) for k, v in out.items()}


async def _matrix(db: AsyncSession) -> dict:
    privs = (await db.execute(select(Privilege).order_by(Privilege.resource, Privilege.action))).scalars().all()
    admin_codes = [p.code for p in privs if p.resource == ADMIN_RESOURCE]
    return {"roles": await _roles_out(db),
            "privileges": [_priv_out(p, []) for p in privs],
            "grants": await _grants(db),
            "locked": [[ADMIN_ROLE, c] for c in admin_codes]}


@router.get("/rbac-matrix", dependencies=[Depends(READ)])
async def get_matrix(db: AsyncSession = Depends(get_async_session)):
    return await _matrix(db)


@router.put("/rbac-matrix")
async def save_matrix(body: MatrixChange, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    roles = {r.role_code: r for r in (await db.execute(select(Role))).scalars()}
    privs = {p.code: p for p in (await db.execute(select(Privilege))).scalars()}
    for role, code in [*body.added, *body.removed]:
        if role not in roles:
            raise HTTPException(status_code=422, detail=f"Unknown role {role}")
        if code not in privs:
            raise HTTPException(status_code=422, detail=f"Unknown privilege {code}")
    locked = [f"{r} / {c}" for r, c in body.removed if r == ADMIN_ROLE and privs[c].resource == ADMIN_RESOURCE]
    if locked:
        raise _conflict("ADMIN always keeps its admin privileges: " + ", ".join(locked))
    before = await _grants(db)
    touched: set[int] = set()
    for role, code in body.added:
        key = (roles[role].role_id, privs[code].privilege_id)
        if code not in before.get(role, []):
            db.add(RolePrivilege(role_id=key[0], privilege_id=key[1]))
            touched.add(key[0])
    for role, code in body.removed:
        if code in before.get(role, []):
            await db.execute(delete(RolePrivilege).where(RolePrivilege.role_id == roles[role].role_id,
                                                         RolePrivilege.privilege_id == privs[code].privilege_id))
            touched.add(roles[role].role_id)
    if not touched:
        return {"changed_roles": [], "affected_users": 0, **(await _matrix(db))}
    await db.flush()
    if await _admins_left(db) < 1:
        await db.rollback()
        raise _conflict("This would leave no active user with admin:write")
    await _bump_roles(db, touched)
    after = await _grants(db)
    changed = sorted(code for code, r in roles.items() if r.role_id in touched)
    for code in changed:
        old, new = set(before.get(code, [])), set(after.get(code, []))
        await _change(db, who, "role_privilege", "update", code,
                      {"revoked": sorted(old - new)}, {"granted": sorted(new - old)})
    users = (await db.execute(select(func.count(User.id)).where(User.role_id.in_(touched)))).scalar()
    await _commit(db)
    return {"changed_roles": changed, "affected_users": users, **(await _matrix(db))}


@router.get("/token-preview/{code}", dependencies=[Depends(READ)])
async def token_preview(code: str, db: AsyncSession = Depends(get_async_session)):
    role = await _role(db, code)
    return {"role": role.role_code, "role_name": role.role_name, "rv": role.version,
            "tenant_scoped": role.is_tenant_scoped, "perms": (await _grants(db)).get(role.role_code, [])}


@router.get("/rbac-changes", dependencies=[Depends(require("audit:read"))])
async def rbac_changes(entity: Optional[Literal["role", "privilege", "role_privilege", "user"]] = None,
                       actor: Optional[str] = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                       db: AsyncSession = Depends(get_async_session)):
    q = select(RbacChange)
    if entity:
        q = q.where(RbacChange.entity == entity)
    if actor:
        q = q.where(RbacChange.actor_email.ilike(f"%{actor.strip()}%"))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    rows = (await db.execute(q.order_by(RbacChange.ts.desc()).limit(limit).offset(offset))).scalars()
    return {"total": total, "items": [{"change_id": r.change_id, "ts": r.ts, "actor_email": r.actor_email,
                                       "request_id": r.request_id, "entity": r.entity, "action": r.action,
                                       "target": r.target, "before": r.before, "after": r.after} for r in rows]}


# ================================================================ users
class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=2, max_length=120)
    role_code: str
    tenant_id: Optional[int] = None


class UserPatch(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    role_code: Optional[str] = None
    tenant_id: Optional[int] = None
    is_active: Optional[bool] = None


EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


async def _user_out(db: AsyncSession, u: User) -> dict:
    role = await db.get(Role, u.role_id)
    tenant = None
    if u.tenant_id:
        tenant = (await db.execute(text("SELECT name FROM battery_master.tenant WHERE tenant_id = :t"),
                                   {"t": u.tenant_id})).scalar()
    return {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role_code": role.role_code,
            "role_name": role.role_name, "tenant_id": u.tenant_id, "tenant_name": tenant, "is_active": u.is_active,
            "is_service_account": u.is_service_account, "must_change_password": u.must_change_password,
            "locked": bool(u.locked_until and u.locked_until > _now()), "failed_logins": u.failed_logins,
            "last_login_at": u.last_login_at, "created_at": u.created_at}


async def _user(db: AsyncSession, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")
    u = await db.get(User, uid)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return u


async def _check_tenant(db: AsyncSession, role: Role, tenant_id: Optional[int]) -> Optional[int]:
    if not role.is_tenant_scoped:
        return None  # only tenant-scoped roles carry a tenant
    if tenant_id is None:
        raise HTTPException(status_code=422, detail=f"{role.role_name} is tenant-scoped - choose a tenant")
    if not await _tenant_exists(db, tenant_id):
        raise HTTPException(status_code=422, detail=f"Tenant {tenant_id} not found")
    return tenant_id


@router.get("/users", dependencies=[Depends(READ)])
async def list_users(db: AsyncSession = Depends(get_async_session)):
    users = (await db.execute(select(User).order_by(User.is_service_account, User.email))).scalars().all()
    return [await _user_out(db, u) for u in users]


@router.get("/tenants", dependencies=[Depends(READ)])
async def list_tenants(db: AsyncSession = Depends(get_async_session)):
    rows = await db.execute(text("SELECT tenant_id, name FROM battery_master.tenant ORDER BY name"))
    return [{"tenant_id": t, "name": n} for t, n in rows]


@router.post("/users", status_code=201)
async def create_user(body: UserIn, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid e-mail address")
    if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
        raise _conflict("A user with this e-mail already exists")
    role = await _role(db, body.role_code)
    if role.role_code == "BATCH_SERVICE":
        raise _conflict("Service accounts are created by backend/setup/bootstrap_auth.py")
    tenant = await _check_tenant(db, role, body.tenant_id)
    temp = _temp_password(email)
    u = User(id=uuid.uuid4(), email=email, hashed_password=password_helper.hash(temp), full_name=body.full_name.strip(),
             role_id=role.role_id, tenant_id=tenant, is_active=True, is_superuser=role.role_code == ADMIN_ROLE,
             is_verified=True, is_service_account=False, must_change_password=True, failed_logins=0, token_version=1)
    db.add(u)
    await db.flush()
    await _change(db, who, "user", "create", email, after={"role": role.role_code, "tenant_id": tenant})
    await _commit(db)
    return {"user": await _user_out(db, u), "temporary_password": temp}


@router.patch("/users/{user_id}")
async def edit_user(user_id: str, body: UserPatch, who: Principal = Depends(WRITE),
                    db: AsyncSession = Depends(get_async_session)):
    u = await _user(db, user_id)
    data = body.model_dump(exclude_unset=True)
    old_role = await db.get(Role, u.role_id)
    before = {"full_name": u.full_name, "role": old_role.role_code, "tenant_id": u.tenant_id, "is_active": u.is_active}
    self_edit = str(u.id) == who.user_id
    if self_edit and ("role_code" in data and data["role_code"] != old_role.role_code or data.get("is_active") is False):
        raise _conflict("You can't change your own role or disable your own account")
    role = old_role
    if "role_code" in data and data["role_code"] != old_role.role_code:
        role = await _role(db, data["role_code"])
        if (role.role_code == "BATCH_SERVICE") != u.is_service_account:
            raise _conflict("BATCH_SERVICE is for service accounts only")
        u.role_id = role.role_id
        u.is_superuser = role.role_code == ADMIN_ROLE
    if role.is_tenant_scoped:
        u.tenant_id = await _check_tenant(db, role, data.get("tenant_id", u.tenant_id))
    else:
        u.tenant_id = None
    if "full_name" in data:
        u.full_name = data["full_name"].strip()
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
    access_changed = (role.role_id != old_role.role_id or u.tenant_id != before["tenant_id"]
                      or u.is_active != before["is_active"])
    if access_changed:
        await db.flush()
        if await _admins_left(db) < 1:
            await db.rollback()
            raise _conflict("This would leave no active user with admin:write")
        # disabled -> signed out everywhere; role / tenant change -> the next token carries the new claims
        await _bump_user(db, u, revoke=not u.is_active)
    after = {"full_name": u.full_name, "role": role.role_code, "tenant_id": u.tenant_id, "is_active": u.is_active}
    await _change(db, who, "user", "update", u.email, before, after)
    await _commit(db)
    return await _user_out(db, u)


@router.post("/users/{user_id}/unlock")
async def unlock_user(user_id: str, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    u = await _user(db, user_id)
    before = {"failed_logins": u.failed_logins, "locked_until": u.locked_until.isoformat() if u.locked_until else None}
    u.failed_logins, u.locked_until = 0, None
    await _change(db, who, "user", "unlock", u.email, before, {"failed_logins": 0, "locked_until": None})
    await _commit(db)
    return await _user_out(db, u)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, who: Principal = Depends(WRITE), db: AsyncSession = Depends(get_async_session)):
    u = await _user(db, user_id)
    if u.is_service_account:
        raise _conflict("Service-account passwords are rotated with backend/setup/bootstrap_auth.py")
    if str(u.id) == who.user_id:  # would replace your own password with a one-time one and sign you out
        raise _conflict("Use Change password for your own account")
    temp = _temp_password(u.email)
    u.hashed_password = password_helper.hash(temp)
    u.must_change_password = True
    u.failed_logins, u.locked_until = 0, None
    await _bump_user(db, u, revoke=True)  # signs the user out everywhere
    await _change(db, who, "user", "reset_password", u.email, after={"must_change_password": True})
    await _commit(db)
    return {"user": await _user_out(db, u), "temporary_password": temp}
