"""Bearer-token validation for the ML service - the shared implementation in bess_common.auth (the same code the backend
uses). Tokens are issued by the backend (/api/auth/token, RS256); this service only reads the PUBLIC key, so it can verify
tokens but never mint them.

    authenticated        router-include-level dependency (deny by default) - main.py mounts every use case with it
    require("res:act")   per-route permission check against the token's `perms` claim (battery_users RBAC matrix)

Refused requests (403) are logged and written to battery_users.auth_audit (service = "ml").
"""
import json

from fastapi import Request
from sqlalchemy import text

from bess_common.auth import Principal, authenticated, permission_by_method, require, set_forbidden_hook
from bess_common.tenant import ScopeResolver, tenant_guard
from core.db import engine

__all__ = ["ML_RBAC", "Principal", "TENANT_GUARD", "TENANT_SCOPE", "authenticated", "can_approve", "require", "tenant_system_ids"]

# tenant-scoped callers (Tenant Viewer): ids outside the tenant -> 404 (guard); GET responses narrowed (main.py middleware)
TENANT_SCOPE = ScopeResolver(engine)
TENANT_GUARD = tenant_guard(TENANT_SCOPE)


def can_approve(request: Request) -> bool:
    """A training request's make_default flag only counts for callers who may promote models (ml.model:approve)."""
    p = getattr(request.state, "principal", None)
    return bool(p and p.can("ml.model:approve"))


def tenant_system_ids(request: Request):
    """Battery systems a tenant-scoped caller may see (None = all) - for endpoints that aggregate across systems."""
    p = getattr(request.state, "principal", None)
    if p is None or p.tenant_id is None:
        return None
    return set(TENANT_SCOPE.get(p.tenant_id)["system"])

# one rule set for every use case (mounted at include level in main.py); per-route require() in a use case adds to it
ML_RBAC = permission_by_method(
    {"GET": "ml.results:read", "HEAD": "ml.results:read", "POST": "ml.run:execute", "PUT": "ml.run:execute",
     "PATCH": "ml.run:execute", "DELETE": "ml.run:delete"},
    (("POST", r"/(default|activate|deactivate|publish)/?$", "ml.model:approve"),
     # forecast views (SOC forecast draws its viewer with POST /forecast) are open to every viewer; interactive
     # what-if inference (/predict, /estimate, /cycle, /predict/vector) stays ml.run:execute
     ("POST", r"/forecast/?$", "ml.results:read"),
     # live forecast panels of the viewers (latest state -> forecast) are views too; /predict/vector what-if is not
     ("POST", r"^/thermal-forecast/predict/?$", "ml.results:read"),
     ("POST", r"^/aux-forecast/predict/?$", "ml.results:read"),
     ("POST", r"^/soc-estimation/estimate/?$", "ml.results:read"),
     ("POST", r"/candidates/\d+/review/?$", "fault.review:write")),
    name="ml")


def _audit_forbidden(principal: Principal, request: Request, reason: str, missing: list[str]) -> None:
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO battery_users.auth_audit (user_id, email, event, success, ip, user_agent, detail)
                             VALUES (CAST(:uid AS uuid), :email, 'FORBIDDEN', false, :ip, :ua, CAST(:detail AS jsonb))"""),
                     {"uid": principal.user_id, "email": principal.email,
                      "ip": request.client.host if request.client else None,
                      "ua": (request.headers.get("user-agent") or "")[:300],
                      "detail": json.dumps({"service": "ml", "reason": reason, "missing": missing, "role": principal.role,
                                            "method": request.method, "path": request.url.path})})


set_forbidden_hook(_audit_forbidden)
