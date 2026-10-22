"""Deny-by-default and Fault Classifier RBAC tests for the ML service (run from "ML model/service":
..\\..\\.venv\\Scripts\\python -m pytest tests).

Tokens are minted with bess_common.auth (the same signer the backend's /api/auth/token uses), so the backend doesn't have
to run. Calls use non-existent ids / invalid bodies: permitted -> 404 / 422, forbidden -> 403. Nothing is trained.
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bess_common.auth import create_access_token, token_settings  # noqa: E402
from core.auth import authenticated  # noqa: E402
from core.db import engine  # noqa: E402
from main import app  # noqa: E402

TEST_UID = "00000000-0000-0000-0000-0000000000aa"
PERMS = {  # from battery_users.role_privilege (the RBAC matrix)
    "ADMIN": ["ml.results:read", "ml.run:read", "ml.run:execute", "ml.run:delete", "ml.model:approve", "fault.review:write"],
    "ASSET_ENGINEER": ["ml.results:read", "fault.review:write"],
    "OPERATOR": ["ml.results:read", "fault.review:write"],
    "DATA_SCIENTIST": ["ml.results:read", "ml.run:read", "ml.run:execute", "ml.run:delete", "ml.model:write", "fault.review:write"],
    "TENANT_VIEWER": ["ml.results:read"],
}


def token(role: str, mcp: bool = False) -> str:
    t, _ = create_access_token(user_id=TEST_UID, email=f"pytest.ml.{role.lower()}@bess.local", name=role, role=role,
                               role_name=role, perms=PERMS[role], tenant_id=None, must_change_password=mcp, is_service=False)
    return t


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM battery_users.auth_audit WHERE user_id = CAST(:u AS uuid)"), {"u": TEST_UID})


def _uses(dependant, fn) -> bool:
    return any(d.call is fn or _uses(d, fn) for d in dependant.dependencies)


def test_every_route_is_deny_by_default():
    open_routes = [r.path for r in app.routes if isinstance(r, APIRoute) and r.path != "/health"
                   and not _uses(r.dependant, authenticated)]
    assert open_routes == []


def test_anonymous_forged_expired_wrong_key(client):
    assert client.get("/fault-diag/runs").status_code == 401
    assert client.get("/fault-diag/runs", headers={"Authorization": "Bearer x.y.z"}).status_code == 401
    assert client.get("/health").status_code == 200
    s = token_settings()
    now = datetime.now(timezone.utc)
    claims = {"iss": s.issuer, "aud": s.audience, "sub": str(uuid.uuid4()), "typ": "access", "perms": PERMS["ADMIN"],
              "iat": now - timedelta(hours=1), "exp": now - timedelta(minutes=1)}
    expired = jwt.encode(claims, s.private_key, algorithm="RS256")
    assert client.get("/fault-diag/runs", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    wrong = jwt.encode({**claims, "exp": now + timedelta(minutes=5)}, other, algorithm="RS256")
    assert client.get("/fault-diag/runs", headers={"Authorization": f"Bearer {wrong}"}).status_code == 401


def test_must_change_password_token_is_blocked(client):
    r = client.get("/fault-diag/runs", headers={"Authorization": f"Bearer {token('ADMIN', mcp=True)}"})
    assert r.status_code == 403 and "password change required" in r.json()["detail"].lower()


# (list runs, train with invalid body, delete missing, default missing, publish missing, scan invalid, review missing)
MATRIX = {
    "ADMIN": (200, 422, 404, 404, 404, 422, 404),
    "ASSET_ENGINEER": (200, 403, 403, 403, 403, 403, 404),
    "OPERATOR": (200, 403, 403, 403, 403, 403, 404),
    "DATA_SCIENTIST": (200, 422, 404, 403, 403, 422, 404),
    "TENANT_VIEWER": (200, 403, 403, 403, 403, 403, 403),
}


@pytest.mark.parametrize("role", list(MATRIX))
def test_fault_classifier_rbac(client, role):
    h = {"Authorization": f"Bearer {token(role)}"}
    got = (client.get("/fault-diag/runs", headers=h).status_code,
           client.post("/fault-diag/runs", headers=h, json={"folds": 99}).status_code,
           client.delete("/fault-diag/runs/99999999", headers=h).status_code,
           client.post("/fault-diag/runs/99999999/default", headers=h).status_code,
           client.post("/fault-diag/runs/99999999/publish", headers=h).status_code,
           client.post("/fault-diag/runs/99999999/scan", headers=h, json={}).status_code,
           client.post("/fault-diag/candidates/99999999/review", headers=h, json={"status": "NEW"}).status_code)
    assert got == MATRIX[role]


def test_forbidden_is_audited(client):
    def count():
        with engine.connect() as conn:
            return conn.execute(text("""SELECT count(*) FROM battery_users.auth_audit WHERE event = 'FORBIDDEN'
                                        AND detail ->> 'service' = 'ml'""")).scalar()
    before = count()
    assert client.delete("/fault-diag/runs/99999999", headers={"Authorization": f"Bearer {token('OPERATOR')}"}).status_code == 403
    assert count() == before + 1


# ---------------------------------------------------------------- every use case (ML_RBAC at include level)
def test_every_route_has_a_permission():
    def rbac(dependant):
        return any(hasattr(d.call, "rbac_rules") or hasattr(d.call, "required_permissions") or rbac(d)
                   for d in dependant.dependencies)
    missing = [f"{sorted(r.methods)} {r.path}" for r in app.routes
               if isinstance(r, APIRoute) and r.path != "/health" and not rbac(r.dependant)]
    assert missing == []


ALL_PERMS = {"ml.results:read", "ml.run:execute", "ml.run:delete", "ml.model:approve"}
# (method, path, body, permission) - samples across use cases; non-existent ids / empty bodies, nothing is trained
ML_SAMPLES = [
    ("GET", "/hvac-cop/runs", None, "ml.results:read"),
    ("GET", "/rul/runs", None, "ml.results:read"),
    ("POST", "/hvac-cop/predict", {}, "ml.run:execute"),           # what-if: trainers only
    ("POST", "/soc-forecast/forecast", {}, "ml.results:read"),      # forecast viewer: every viewer
    ("POST", "/thermal-forecast/predict", {}, "ml.results:read"),   # live forecast panel: every viewer
    ("POST", "/thermal-forecast/predict/vector", {}, "ml.run:execute"),  # free what-if: trainers only
    ("POST", "/efficiency/runs", {}, "ml.run:execute"),
    ("POST", "/mv-anomaly/live/score", {"hours": 1, "system_id": 99999999}, "ml.run:execute"),
    ("DELETE", "/price-forecast/runs/99999999", None, "ml.run:delete"),
    ("POST", "/aux-forecast/runs/99999999/default", None, "ml.model:approve"),
    ("POST", "/soh/runs/99999999/activate", None, "ml.model:approve"),
]


@pytest.mark.parametrize("role", list(PERMS))
def test_all_use_cases_follow_the_matrix(client, role):
    h = {"Authorization": f"Bearer {token(role)}"}
    bad = []
    for method, path, body, perm in ML_SAMPLES:
        r = client.request(method, path, headers=h, json=body)
        allowed = perm in PERMS[role]
        if allowed == (r.status_code == 403) or r.status_code == 401:
            bad.append(f"{method} {path} needs {perm}: got {r.status_code} (allowed={allowed})")
    assert bad == [], "\n".join(bad)


# ---------------------------------------------------------------- live forecast panels, make_default, tenant scope
def test_live_forecast_panels_open_to_viewers(client):
    h = {"Authorization": f"Bearer {token('OPERATOR')}"}
    for path in ("/thermal-forecast/predict", "/aux-forecast/predict", "/soc-estimation/estimate"):
        assert client.post(path, headers=h, json={}).status_code != 403, path
    for path in ("/hvac-cop/predict", "/efficiency/predict", "/rul/predict", "/thermal-forecast/predict/vector"):
        assert client.post(path, headers=h, json={}).status_code == 403, path  # free what-if: trainers only


def test_make_default_needs_approve():
    from types import SimpleNamespace
    from bess_common.auth import decode_access_token
    from core.auth import can_approve
    req = lambda role: SimpleNamespace(state=SimpleNamespace(principal=decode_access_token(token(role))))
    assert can_approve(req("ADMIN")) is True
    assert can_approve(req("DATA_SCIENTIST")) is False  # may train, but its make_default flag is ignored


def tv_token() -> str:
    from core.db import engine
    with engine.connect() as conn:
        tenant = conn.execute(text("SELECT tenant_id FROM battery_master.tenant WHERE name = 'Tata Power Renewable Energy Limited'")).scalar()
    t, _ = create_access_token(user_id=TEST_UID, email="pytest.ml.tv@bess.local", name="TV", role="TENANT_VIEWER",
                               role_name="Tenant Viewer", perms=["ml.results:read"], tenant_id=tenant,
                               must_change_password=False, is_service=False)
    return t


def test_tenant_viewer_ml_is_scoped(client):
    tv = {"Authorization": f"Bearer {tv_token()}"}
    admin = {"Authorization": f"Bearer {token('ADMIN')}"}
    from core.db import engine
    with engine.connect() as conn:
        own = {r[0] for r in conn.execute(text("""SELECT b.battery_system_id FROM battery_master.battery_system b
                 JOIN battery_master.tenant_site ts ON ts.site_id = b.site_id JOIN battery_master.tenant t ON t.tenant_id = ts.tenant_id
                 WHERE t.name = 'Tata Power Renewable Energy Limited'"""))}
        other = conn.execute(text("SELECT min(battery_system_id) FROM battery_master.battery_system WHERE NOT battery_system_id = ANY(:o)"),
                             {"o": list(own)}).scalar()
    # an out-of-tenant id in the query string or a JSON body -> 404
    assert client.get(f"/fault-diag/analytics/overview?system_id={other}", headers=tv).status_code == 404
    assert client.post("/thermal-forecast/predict", headers=tv, json={"system_id": other}).status_code == 404
    # option lists keep only the tenant's units
    units_all = {u["hvac_id"] for u in client.get("/hvac-cop/options", headers=admin).json()["units"]}
    units_tv = {u["hvac_id"] for u in client.get("/hvac-cop/options", headers=tv).json()["units"]}
    assert units_tv < units_all
    # aggregates: fault analytics only count the tenant's episodes
    assert client.get("/fault-diag/analytics/overview", headers=tv).json()["episodes"] <= \
        client.get("/fault-diag/analytics/overview", headers=admin).json()["episodes"]


# ---------------------------------------------------------------- observability
def test_training_request_logged_with_request_id(client):
    from bess_common.observability import activity
    from core.db import engine
    r = client.post("/hvac-cop/runs", headers={"Authorization": f"Bearer {token('ADMIN')}", "X-Request-ID": "pytest-ml-train1"},
                    json={})  # invalid body: rejected before any training
    assert r.status_code == 422 and r.headers["x-request-id"] == "pytest-ml-train1" and r.json()["request_id"] == "pytest-ml-train1"
    activity.flush()
    with engine.begin() as conn:
        row = conn.execute(text("SELECT kind, operation, outcome, service FROM battery_ops.activity_log WHERE request_id = 'pytest-ml-train1'")).first()
        conn.execute(text("DELETE FROM battery_ops.activity_log WHERE request_id LIKE 'pytest-%' OR user_email LIKE 'pytest.ml.%'"))
    assert row is not None and tuple(row) == ("TRAINING", "hvac-cop_training", "failed", "ml")
