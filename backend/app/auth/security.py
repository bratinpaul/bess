"""Token checks for the backend: the shared implementation in bess_common.auth (also used by the ML service) plus the
backend's audit writer for refused requests.

    authenticated        router-include-level dependency (deny by default; must-change-password tokens limited to /api/auth)
    require("res:act")   per-route permission check against the token's `perms` claim
    create_access_token  RS256 signing (the private key never leaves the backend)
"""
import json

from fastapi import Request
from sqlalchemy import text

from bess_common.auth import (Principal, authenticated, create_access_token, decode_access_token, require,
                              set_forbidden_hook, token_settings)
from app.database import SessionLocal

__all__ = ["Principal", "authenticated", "create_access_token", "decode_access_token", "require", "token_settings"]


def _audit_forbidden(principal: Principal, request: Request, reason: str, missing: list[str]) -> None:
    with SessionLocal() as db:
        db.execute(text("""INSERT INTO battery_users.auth_audit (user_id, email, event, success, ip, user_agent, detail)
                           VALUES (CAST(:uid AS uuid), :email, 'FORBIDDEN', false, :ip, :ua, CAST(:detail AS jsonb))"""),
                   {"uid": principal.user_id, "email": principal.email,
                    "ip": request.client.host if request.client else None,
                    "ua": (request.headers.get("user-agent") or "")[:300],
                    "detail": json.dumps({"service": "backend", "reason": reason, "missing": missing, "role": principal.role,
                                          "method": request.method, "path": request.url.path})})
        db.commit()


set_forbidden_hook(_audit_forbidden)
