"""User management API: admin-only access, custom privileges, roles, the RBAC matrix and its effect on tokens (role /
user versions), user accounts, safeguards and the change history. Works on its own PYTEST_* role, privilege and users,
so the real roles are never changed; everything is removed afterwards."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.users import password_helper
from app.database import SessionLocal
from app.main import app
from bess_common.auth import enforced_permissions

PW = "Pytest-Admin-2026x"
ADMIN = "pytest.ua.admin@bess.local"
OPERATOR = "pytest.ua.operator@bess.local"
ROLE = "PYTEST_UA_ROLE"
RES = "pytest_ua.report"


def _cleanup(db):
    db.execute(text("DELETE FROM battery_users.refresh_token WHERE user_id IN (SELECT id FROM battery_users.app_user WHERE email LIKE 'pytest.ua.%')"))
    db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.ua.%'"))
    db.execute(text("DELETE FROM battery_users.role_privilege WHERE role_id IN (SELECT role_id FROM battery_users.role WHERE role_code LIKE 'PYTEST_UA%') "
                    "OR privilege_id IN (SELECT privilege_id FROM battery_users.privilege WHERE resource LIKE 'pytest_ua%')"))
    db.execute(text("DELETE FROM battery_users.role WHERE role_code LIKE 'PYTEST_UA%'"))
    db.execute(text("DELETE FROM battery_users.privilege WHERE resource LIKE 'pytest_ua%'"))
    db.execute(text("DELETE FROM battery_users.rbac_change WHERE actor_email LIKE 'pytest.ua.%'"))
    db.execute(text("DELETE FROM battery_users.auth_audit WHERE email LIKE 'pytest.ua.%'"))


@pytest.fixture(scope="module", autouse=True)
def setup():
    with SessionLocal() as db:
        _cleanup(db)
        for email, role in ((ADMIN, "ADMIN"), (OPERATOR, "OPERATOR")):
            db.execute(text("""INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id, must_change_password)
                               SELECT :id, :e, :pw, 'ua test', role_id, false FROM battery_users.role WHERE role_code = :r"""),
                       {"id": str(uuid.uuid4()), "e": email, "pw": password_helper.hash(PW), "r": role})
        db.commit()
    yield
    with SessionLocal() as db:
        _cleanup(db)
        db.commit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, password=PW) -> str:
    r = client.post("/api/auth/token", data={"grant_type": "password", "username": email, "password": password,
                                             "client_id": "bess-batch"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin(client):
    return h(login(client, ADMIN))


def test_admin_api_is_admin_only(client, admin):
    op = h(login(client, OPERATOR))
    for method, path in (("get", "/api/admin/privileges"), ("get", "/api/admin/rbac-matrix"), ("get", "/api/admin/users"),
                         ("post", "/api/admin/roles"), ("put", "/api/admin/rbac-matrix"), ("delete", "/api/admin/roles/X")):
        assert getattr(client, method)(path, headers=op).status_code == 403, path
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/api/admin/rbac-matrix", headers=admin).status_code == 200


def test_registry_and_catalogue(client, admin):
    assert {"admin:read", "admin:write", "admin:delete", "master.asset:write"} <= enforced_permissions()
    privs = {p["code"]: p for p in client.get("/api/admin/privileges", headers=admin).json()}
    assert privs["admin:read"]["source"] == "system" and privs["admin:read"]["enforced"]
    assert "backend" in privs["admin:read"]["registered_by"]


def test_custom_privilege_role_matrix_and_token(client, admin):
    # custom privilege: not enforced, duplicate refused
    r = client.post("/api/admin/privileges", headers=admin, json={"resource": RES, "action": "read", "module_label": "Pytest"})
    assert r.status_code == 201 and r.json()["source"] == "custom" and r.json()["enforced"] is False
    pid = r.json()["privilege_id"]
    assert client.post("/api/admin/privileges", headers=admin, json={"resource": RES, "action": "read"}).status_code == 409
    assert client.post("/api/admin/privileges", headers=admin, json={"resource": "Bad Name", "action": "read"}).status_code == 422

    # role copied from ANALYST
    r = client.post("/api/admin/roles", headers=admin, json={"role_code": ROLE, "role_name": "Pytest UA role", "copy_from": "ANALYST"})
    assert r.status_code == 201
    analyst = client.get("/api/admin/token-preview/ANALYST", headers=admin).json()["perms"]
    assert client.get(f"/api/admin/token-preview/{ROLE}", headers=admin).json()["perms"] == analyst

    # a user of that role (temporary password, must change it)
    r = client.post("/api/admin/users", headers=admin, json={"email": "pytest.ua.member@bess.local", "full_name": "UA Member", "role_code": ROLE})
    assert r.status_code == 201
    temp, uid = r.json()["temporary_password"], r.json()["user"]["id"]
    assert r.json()["user"]["must_change_password"] is True
    old_token = login(client, "pytest.ua.member@bess.local", temp)
    assert f"{RES}:read" not in client.get("/api/auth/me", headers=h(old_token)).json()["permissions"]

    # grant through the matrix -> role version bumped -> the old token is stale, a new one carries the code
    v0 = next(x for x in client.get("/api/admin/roles", headers=admin).json() if x["role_code"] == ROLE)["version"]
    r = client.put("/api/admin/rbac-matrix", headers=admin, json={"added": [[ROLE, f"{RES}:read"]], "removed": []})
    assert r.status_code == 200 and r.json()["changed_roles"] == [ROLE] and r.json()["affected_users"] == 1
    v1 = next(x for x in client.get("/api/admin/roles", headers=admin).json() if x["role_code"] == ROLE)["version"]
    assert v1 == v0 + 1
    stale = client.get("/api/auth/me", headers=h(old_token))
    assert stale.status_code == 401 and "out of date" in stale.json()["detail"]
    fresh = login(client, "pytest.ua.member@bess.local", temp)
    assert f"{RES}:read" in client.get("/api/auth/me", headers=h(fresh)).json()["permissions"]

    # in-use deletes are refused; ADMIN's admin privileges are locked
    assert client.delete(f"/api/admin/privileges/{pid}", headers=admin).status_code == 409
    assert client.delete(f"/api/admin/roles/{ROLE}", headers=admin).status_code == 409
    assert client.delete("/api/admin/roles/ADMIN", headers=admin).status_code == 409
    assert client.put("/api/admin/rbac-matrix", headers=admin, json={"added": [], "removed": [["ADMIN", "admin:write"]]}).status_code == 409

    # user changes: role change makes the token stale; disable blocks sign-in; self-disable refused
    r = client.patch(f"/api/admin/users/{uid}", headers=admin, json={"role_code": "ANALYST"})
    assert r.status_code == 200 and r.json()["role_code"] == "ANALYST"
    assert client.get("/api/auth/me", headers=h(fresh)).status_code == 401
    assert client.patch(f"/api/admin/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    bad = client.post("/api/auth/token", data={"grant_type": "password", "username": "pytest.ua.member@bess.local",
                                               "password": temp, "client_id": "bess-batch"})
    assert bad.status_code in (400, 401)
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.patch(f"/api/admin/users/{me['user_id']}", headers=admin, json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/admin/users/{me['user_id']}", headers=admin, json={"role_code": "ANALYST"}).status_code == 409
    assert client.post(f"/api/admin/users/{me['user_id']}/reset-password", headers=admin).status_code == 409

    # reset password -> new temporary password works
    r = client.post(f"/api/admin/users/{uid}/reset-password", headers=admin)
    assert r.status_code == 200
    client.patch(f"/api/admin/users/{uid}", headers=admin, json={"is_active": True})
    login(client, "pytest.ua.member@bess.local", r.json()["temporary_password"])

    # clean-up through the API: revoke, then delete privilege and role
    assert client.put("/api/admin/rbac-matrix", headers=admin, json={"added": [], "removed": [[ROLE, f"{RES}:read"]]}).status_code == 200
    assert client.delete(f"/api/admin/privileges/{pid}", headers=admin).status_code == 200
    assert client.delete(f"/api/admin/roles/{ROLE}", headers=admin).status_code == 200


def test_history_records_every_change(client, admin):
    r = client.get("/api/admin/rbac-changes?limit=500", headers=admin)
    assert r.status_code == 200
    mine = [c for c in r.json()["items"] if c["actor_email"] == ADMIN]
    kinds = {(c["entity"], c["action"]) for c in mine}
    assert {("privilege", "create"), ("role", "create"), ("role_privilege", "update"), ("user", "create"),
            ("user", "update"), ("user", "reset_password"), ("privilege", "delete"), ("role", "delete")} <= kinds
    grant = next(c for c in mine if c["entity"] == "role_privilege" and c["after"]["granted"])
    assert grant["after"]["granted"] == [f"{RES}:read"]


def test_token_without_versions_is_stale():
    from bess_common.auth import Principal
    from app.auth.freshness import freshness
    p = Principal(user_id=str(uuid.uuid4()), email="x@bess.local", name=None, role="ADMIN", role_name="Admin")
    assert freshness(p) == "token_without_versions"
