"""RBAC rollout across every backend router: enforcement must equal the matrix stored in battery_users.role_privilege.

For each resource a sample read / write / delete call is made as each of the 8 roles (temporary pytest.rbac.* users).
Expected: a role holding the permission is NOT refused (it reaches 200 / 404 / 422 - non-existent ids and empty bodies,
so nothing changes); a role without it gets 403. Also: tenant scoping of master data and the batch service role.
"""
import json
import uuid
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.users import password_helper
from app.database import SessionLocal
from app.main import app

PW = "Pytest-Rbac-2026"
ROLES = ["ADMIN", "ASSET_ENGINEER", "OPERATOR", "DATA_ENGINEER", "DATA_SCIENTIST", "ANALYST", "TENANT_VIEWER", "BATCH_SERVICE"]
TENANT = "Tata Power Renewable Energy Limited"
PUBLIC = {"/api/health", "/api/auth/token", "/api/auth/revoke", "/api/auth/password-policy", "/api/auth/signup", "/api/auth/me",
          "/api/auth/change-password"}

# (method, path, json body, permission it needs)
SAMPLES = [
    ("GET", "/api/tenants", None, "master.tenant:read"),
    ("DELETE", "/api/tenants/99999999", None, "master.tenant:delete"),
    ("GET", "/api/battery-systems", None, "master.asset:read"),
    ("POST", "/api/battery-systems", {}, "master.asset:write"),
    ("DELETE", "/api/battery-systems/99999999", None, "master.asset:delete"),
    ("GET", "/api/pcs", None, "master.asset:read"),
    ("GET", "/api/asset-hierarchy/tree", None, "master.hierarchy:read"),
    ("DELETE", "/api/asset-hierarchy/site/99999999", None, "master.hierarchy:delete"),
    ("GET", "/api/alarm-catalog/lookups", None, "master.reference:read"),
    ("POST", "/api/alarm-catalog", {}, "master.reference:write"),
    ("DELETE", "/api/alarm-catalog/99999999", None, "master.reference:delete"),
    ("GET", "/api/arbitrage/lookups", None, "market:read"),
    ("DELETE", "/api/optimization-runs/99999999", None, "market:delete"),
    ("GET", "/api/fault/lookups", None, "fault:read"),
    ("GET", "/api/alarm-events/lookups", None, "telemetry:read"),
    ("POST", "/api/alarm-events", {}, "telemetry:write"),
    ("DELETE", "/api/alarm-events/ALM-NOPE-0", None, "telemetry:delete"),
    ("GET", "/api/bms-kpi/config", None, "kpi:read"),
    ("POST", "/api/bms-kpi/calculate", {}, "kpi:execute"),
    ("GET", "/api/analytics/telemetry-date-range", None, "reports:read"),
    ("GET", "/api/dashboard/summary", None, "dashboard:read"),
    ("GET", "/api/batch/realtime/status", None, "batch:read"),
    ("POST", "/api/batch/historical/scan", {}, "batch:execute"),
    ("POST", "/api/master-bulk/tenant", None, "master.tenant:write"),
    ("POST", "/api/master-bulk/site", None, "master.asset:write"),
]


def _email(role: str) -> str:
    return f"pytest.rbac.{role.lower()}@bess.local"


@pytest.fixture(scope="module", autouse=True)
def users():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.rbac.%'"))
        for role in ROLES:
            db.execute(text("""
                INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id, tenant_id, must_change_password)
                SELECT :id, :email, :pw, :name, r.role_id,
                       CASE WHEN r.is_tenant_scoped THEN (SELECT tenant_id FROM battery_master.tenant WHERE name = :tenant) END, false
                FROM battery_users.role r WHERE r.role_code = :role"""),
                {"id": str(uuid.uuid4()), "email": _email(role), "pw": password_helper.hash(PW), "name": f"pytest {role}",
                 "tenant": TENANT, "role": role})
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.rbac.%'"))
        db.execute(text("DELETE FROM battery_users.auth_audit WHERE email LIKE 'pytest.rbac.%'"))
        db.commit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def tokens(client):
    out = {}
    for role in ROLES:
        client.cookies.clear()
        r = client.post("/api/auth/token", data={"grant_type": "password", "username": _email(role), "password": PW,
                                                 "client_id": "bess-batch"})
        assert r.status_code == 200, (role, r.text)
        out[role] = r.json()["access_token"]
    return out


@pytest.fixture(scope="module")
def matrix():
    with SessionLocal() as db:
        rows = db.execute(text("""SELECT r.role_code, p.code FROM battery_users.role_privilege rp
                                  JOIN battery_users.role r ON r.role_id = rp.role_id
                                  JOIN battery_users.privilege p ON p.privilege_id = rp.privilege_id""")).all()
    m: dict[str, set] = {}
    for role, code in rows:
        m.setdefault(role, set()).add(code)
    return m


def _rbac_deps(dependant, found=None):
    found = [] if found is None else found
    for d in dependant.dependencies:
        if hasattr(d.call, "rbac_rules") or hasattr(d.call, "required_permissions"):
            found.append(d.call)
        _rbac_deps(d, found)
    return found


def test_every_route_has_a_permission():
    """Stronger than login-only: each non-public route carries an RBAC dependency (router map or require())."""
    missing = [f"{sorted(r.methods)} {r.path}" for r in app.routes
               if isinstance(r, APIRoute) and r.path not in PUBLIC and not _rbac_deps(r.dependant)]
    assert missing == [], f"routes without an RBAC permission: {missing}"


@pytest.mark.parametrize("role", ROLES)
def test_enforcement_matches_matrix(client, tokens, matrix, role):
    h = {"Authorization": f"Bearer {tokens[role]}"}
    mismatches = []
    for method, path, body, perm in SAMPLES:
        r = client.request(method, path, headers=h, json=body)
        allowed = perm in matrix.get(role, set())
        refused = r.status_code == 403
        if allowed == refused or r.status_code == 401:
            mismatches.append(f"{method} {path} needs {perm}: got {r.status_code} (allowed={allowed})")
    assert mismatches == [], "\n".join(mismatches)


def test_tenant_viewer_master_data_is_scoped(client, tokens):
    admin = {"Authorization": f"Bearer {tokens['ADMIN']}"}
    tv = {"Authorization": f"Bearer {tokens['TENANT_VIEWER']}"}
    for path, key in [("/api/battery-systems", "battery_system_id"), ("/api/pcs", "pcs_id"), ("/api/ems-controllers", "ems_id"),
                      ("/api/hvac-units", "hvac_id"), ("/api/battery-containers", "container_id")]:
        all_rows = client.get(path, headers=admin).json()
        own = client.get(path, headers=tv).json()
        assert len(own) <= len(all_rows), path
        hidden = [r for r in all_rows if r[key] not in {o[key] for o in own}]
        if hidden:
            assert client.get(f"{path}/{hidden[0][key]}", headers=tv).status_code == 404, path
    systems_all = client.get("/api/battery-systems", headers=admin).json()
    systems_own = client.get("/api/battery-systems", headers=tv).json()
    assert 0 < len(systems_own) < len(systems_all)
    tree = client.get("/api/asset-hierarchy/tree", headers=tv).json()
    assert len(tree) == 1 and tree[0]["asset_type"] == "tenant"


def test_batch_service_account_role(client):
    creds = json.loads((Path(__file__).resolve().parents[2] / "keys" / "service_account.json").read_text(encoding="utf-8"))
    client.cookies.clear()
    r = client.post("/api/auth/token", data={"grant_type": "password", "username": creds["email"], "password": creds["password"],
                                             "client_id": "bess-batch"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=h).json()["role"] == "BATCH_SERVICE"
    assert client.post("/api/master-bulk/tenant", headers=h).status_code == 422  # allowed (no file sent)
    assert client.post("/api/alarm-events", headers=h, json={}).status_code == 422  # telemetry write allowed
    assert client.get("/api/dam-prices", headers=h).status_code == 403  # nothing outside the loaders' needs
    assert client.delete("/api/tenants/99999999", headers=h).status_code == 403


# ---------------------------------------------------------------- tenant scope beyond master data
def _systems(client, h):
    return {s["battery_system_id"] for s in client.get("/api/battery-systems", headers=h).json()}


def test_tenant_viewer_telemetry_reports_dashboard_are_scoped(client, tokens):
    admin = {"Authorization": f"Bearer {tokens['ADMIN']}"}
    tv = {"Authorization": f"Bearer {tokens['TENANT_VIEWER']}"}
    own, every = _systems(client, tv), _systems(client, admin)
    other = sorted(every - own)[0]
    mine = sorted(own)[0]
    # an id outside the tenant -> 404 on every kind of endpoint (telemetry, reports, KPI, operations)
    for path in (f"/api/system-telemetry?system_id={other}", f"/api/system-telemetry/series?system_id={other}",
                 f"/api/analytics/daily-series?system_id={other}", f"/api/bms-kpi?entity_id={other}",
                 f"/api/operations/overview?system_id={other}"):
        assert client.get(path, headers=tv).status_code == 404, path
    assert client.get(f"/api/system-telemetry?system_id={mine}&page_size=1", headers=tv).status_code == 200
    # lookups / dropdowns only list the tenant's systems
    lookup_ids = {s.get("system_id") or s.get("battery_system_id")
                  for s in client.get("/api/alarm-events/lookups", headers=tv).json()["systems"]}
    assert lookup_ids and lookup_ids <= own
    kpi_entities = {e["id"] for e in client.get("/api/bms-kpi/entities", headers=tv).json()}
    assert kpi_entities and kpi_entities <= own
    # alarm list: only the tenant's systems, totals computed on the scoped set
    a_all = client.get("/api/alarm-events?page_size=500", headers=admin).json()
    a_tv = client.get("/api/alarm-events?page_size=500", headers=tv).json()
    assert {i["battery_system_id"] for i in a_tv["items"]} <= own and a_tv["total"] < a_all["total"]
    foreign = next(i for i in a_all["items"] if i["battery_system_id"] not in own)
    assert client.get(f"/api/alarm-events/{foreign['alarm_id']}", headers=tv).status_code == 404
    # dashboard aggregates
    s_all = client.get("/api/dashboard/summary", headers=admin).json()
    s_tv = client.get("/api/dashboard/summary", headers=tv).json()
    assert 0 < s_tv["site_count"] < s_all["site_count"]
    assert len(client.get("/api/dashboard/site-map", headers=tv).json()) == s_tv["site_count"]
