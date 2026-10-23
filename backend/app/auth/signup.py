"""Self-service sign-up and the Admin review of access requests.

POST /api/auth/signup                              public: name, e-mail, organisation, reason, password -> PENDING request
GET  /api/auth/access-requests?status=             admin:read  - requests (newest first) with the assignable roles
POST /api/auth/access-requests/{id}/approve        admin:write - role (+ tenant for tenant-scoped roles) -> app_user
POST /api/auth/access-requests/{id}/reject         admin:write - optional note

A new request e-mails the addresses in ACCESS_REQUEST_NOTIFY_TO (backend/.env; SMTP settings in
app/services/mailer.py). The mail goes out after the response, so a mail problem never fails the sign-up.

The requester chooses the password at sign-up (same policy as change-password); only its argon2 hash is stored and it
becomes the account's password on approval, so nothing has to be sent to the user. Sign-up is rate-limited per IP and
an e-mail that already has an account or an open request is refused.
"""
import html
import os
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AccessRequest, Role, User, get_async_session
from app.auth.security import Principal, require
from app.auth.service import audit, password_problems
from app.auth.users import password_helper
from app.services.mailer import recipients, send_mail

router = APIRouter(prefix="/api/auth", tags=["auth"])
NON_ASSIGNABLE = {"BATCH_SERVICE"}  # service accounts only
SIGNUPS_PER_HOUR = 5
_recent: dict[str, deque] = defaultdict(deque)
EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


class SignupBody(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    organisation: Optional[str] = Field(default=None, max_length=160)
    reason: str = Field(min_length=10, max_length=2000)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        # plain format check: intranet domains (e.g. @bess.local) are valid on this self-hosted platform
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid e-mail address")
        return v

    @field_validator("full_name", "reason", "organisation")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class ApproveBody(BaseModel):
    role_code: str = Field(min_length=2, max_length=40)
    tenant_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=1000)


class RejectBody(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _throttle(ip: str) -> None:
    q, now = _recent[ip], time.monotonic()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= SIGNUPS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many sign-up requests from this address - try again later")
    q.append(now)


def _out(r: AccessRequest, roles: dict[int, Role]) -> dict:
    role = roles.get(r.role_id) if r.role_id else None
    return {"request_id": r.request_id, "full_name": r.full_name, "email": r.email, "organisation": r.organisation,
            "reason": r.reason, "status": r.status, "requested_at": r.requested_at, "reviewed_at": r.reviewed_at,
            "reviewed_by": r.reviewed_by, "role_code": role.role_code if role else None,
            "role_name": role.role_name if role else None, "tenant_id": r.tenant_id, "decision_note": r.decision_note,
            "user_id": str(r.user_id) if r.user_id else None}


def notify_admins(full_name: str, email: str, organisation: Optional[str], reason: str, requested_at: datetime) -> bool:
    """Tell the configured reviewers about a new access request (runs after the response; never raises)."""
    to = recipients(os.getenv("ACCESS_REQUEST_NOTIFY_TO"))
    link = os.getenv("APP_BASE_URL", "http://localhost:4300").rstrip("/") + "/admin/access-requests"
    when = requested_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    org = organisation or "-"
    text = (f"A new access request is waiting for review.\n\n"
            f"Name:          {full_name}\nE-mail:        {email}\nOrganisation:  {org}\nRequested:     {when}\n\n"
            f"Reason:\n{reason}\n\nReview it (assign a role, approve or reject): {link}\n")
    e = html.escape
    page = (f"<p>A new access request is waiting for review.</p><table cellpadding='4'>"
            f"<tr><td><b>Name</b></td><td>{e(full_name)}</td></tr><tr><td><b>E-mail</b></td><td>{e(email)}</td></tr>"
            f"<tr><td><b>Organisation</b></td><td>{e(org)}</td></tr><tr><td><b>Requested</b></td><td>{e(when)}</td></tr>"
            f"</table><p><b>Reason</b><br>{e(reason).replace(chr(10), '<br>')}</p>"
            f"<p><a href='{e(link)}'>Review the request</a> - assign a role, approve or reject.</p>")
    return send_mail(to, f"BESS access request: {full_name}", text, page)


@router.post("/signup", status_code=202)
async def signup(body: SignupBody, request: Request, background: BackgroundTasks,
                 db: AsyncSession = Depends(get_async_session)):
    ip = request.client.host if request.client else "?"
    email = body.email.strip().lower()
    problems = password_problems(body.password, email)
    if problems:
        raise HTTPException(status_code=400, detail="Password needs: " + "; ".join(problems))
    _throttle(ip)
    if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
        raise HTTPException(status_code=409, detail="An account with this e-mail already exists - sign in instead")
    if (await db.execute(select(AccessRequest.request_id).where(func.lower(AccessRequest.email) == email,
                                                                AccessRequest.status == "PENDING"))).first():
        raise HTTPException(status_code=409, detail="A request for this e-mail is already waiting for approval")
    db.add(AccessRequest(full_name=body.full_name, email=email, organisation=body.organisation or None, reason=body.reason,
                         hashed_password=password_helper.hash(body.password), request_ip=ip))
    await audit(db, "SIGNUP_REQUESTED", True, email=email, ip=ip, agent=request.headers.get("user-agent"))
    await db.commit()
    background.add_task(notify_admins, body.full_name, email, body.organisation, body.reason, _now())
    return {"message": "Request received. An administrator will review it; you can sign in once it is approved."}


@router.get("/access-requests", dependencies=[Depends(require("admin:read"))])
async def list_requests(status_filter: Optional[Literal["PENDING", "APPROVED", "REJECTED"]] = Query(None, alias="status"),
                        db: AsyncSession = Depends(get_async_session)):
    roles = {r.role_id: r for r in (await db.execute(select(Role))).scalars()}
    q = select(AccessRequest).order_by(AccessRequest.status != "PENDING", AccessRequest.requested_at.desc())
    if status_filter:
        q = q.where(AccessRequest.status == status_filter)
    rows = (await db.execute(q)).scalars().all()
    return {"requests": [_out(r, roles) for r in rows],
            "roles": [{"role_code": r.role_code, "role_name": r.role_name, "is_tenant_scoped": r.is_tenant_scoped,
                       "description": r.description}
                      for r in sorted(roles.values(), key=lambda x: x.role_id) if r.role_code not in NON_ASSIGNABLE],
            "pending": sum(1 for r in rows if r.status == "PENDING") if not status_filter or status_filter == "PENDING"
            else None}


async def _pending(db: AsyncSession, request_id: int) -> AccessRequest:
    r = await db.get(AccessRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Access request not found")
    if r.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"This request was already {r.status.lower()}")
    return r


@router.post("/access-requests/{request_id}/approve")
async def approve(request_id: int, body: ApproveBody, request: Request,
                  principal: Principal = Depends(require("admin:write")), db: AsyncSession = Depends(get_async_session)):
    r = await _pending(db, request_id)
    role = (await db.execute(select(Role).where(Role.role_code == body.role_code))).scalar_one_or_none()
    if role is None or role.role_code in NON_ASSIGNABLE:
        raise HTTPException(status_code=400, detail=f"Role {body.role_code} can't be assigned")
    if role.is_tenant_scoped and not body.tenant_id:
        raise HTTPException(status_code=400, detail=f"{role.role_name} needs a tenant")
    if (await db.execute(select(User.id).where(func.lower(User.email) == r.email.lower()))).first():
        raise HTTPException(status_code=409, detail="An account with this e-mail already exists")
    user = User(id=uuid.uuid4(), email=r.email, hashed_password=r.hashed_password, full_name=r.full_name,
                role_id=role.role_id, tenant_id=body.tenant_id if role.is_tenant_scoped else None, is_active=True,
                is_superuser=False, is_verified=True, must_change_password=False)
    db.add(user)
    await db.flush()  # insert the user before the request row references it
    r.status, r.reviewed_at, r.reviewed_by = "APPROVED", _now(), principal.email
    r.role_id, r.tenant_id, r.decision_note, r.user_id = role.role_id, user.tenant_id, body.note, user.id
    await audit(db, "SIGNUP_APPROVED", True, email=r.email, ip=request.client.host if request.client else None,
                detail={"by": principal.email, "role": role.role_code, "tenant_id": user.tenant_id})
    await db.commit()
    roles = {role.role_id: role}
    return _out(r, roles)


@router.post("/access-requests/{request_id}/reject")
async def reject(request_id: int, body: RejectBody, request: Request,
                 principal: Principal = Depends(require("admin:write")), db: AsyncSession = Depends(get_async_session)):
    r = await _pending(db, request_id)
    r.status, r.reviewed_at, r.reviewed_by, r.decision_note = "REJECTED", _now(), principal.email, body.note
    await audit(db, "SIGNUP_REJECTED", True, email=r.email, ip=request.client.host if request.client else None,
                detail={"by": principal.email, "note": body.note})
    await db.commit()
    return _out(r, {})


async def request_status_for_login(db: AsyncSession, email: str, password: str) -> Optional[str]:
    """Called when a sign-in fails: if the e-mail has a sign-up request AND the password matches it, explain why."""
    r = (await db.execute(select(AccessRequest).where(func.lower(AccessRequest.email) == email.lower())
                          .order_by(AccessRequest.requested_at.desc()).limit(1))).scalar_one_or_none()
    if r is None or r.status == "APPROVED":
        return None
    ok, _ = password_helper.verify_and_update(password, r.hashed_password)
    if not ok:
        return None
    if r.status == "PENDING":
        return "Your access request is waiting for an administrator's approval"
    return "Your access request was declined" + (f": {r.decision_note}" if r.decision_note else "")
