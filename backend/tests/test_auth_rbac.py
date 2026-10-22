"""Login, token, password and RBAC tests for the backend (run from backend/: ..\\.venv\\Scripts\\python -m pytest tests).

A module fixture creates temporary accounts (pytest.*@bess.local, one per role plus lockout / password-change accounts)
and deletes them afterwards, so the seeded users are never locked or changed. Permission checks use non-existent ids /
invalid bodies: a permitted call stops at 404 / 422, a forbidden one at 403 - no business data is modified.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.security import authenticated, token_settings
from app.auth.users import password_helper
from app.database import SessionLocal
from app.main import app

PUBLIC = {"/api/health", "/api/auth/token", "/api/auth/revoke", "/api/auth/password-policy", "/api/auth/signup"}
PW = "Pytest-Pass-2026"
ROLES = ["ADMIN", "ASSET_ENGINEER", "OPERATOR", "DATA_SCIENTIST", "TENANT_VIEWER"]
TENANT = "Tata Power Renewable Energy Limited"


def _email(tag: str) -> str:
    return f"pytest.{tag.lower()}@bess.local"


@pytest.fixture(scope="module", autouse=True)
def temp_users():
    accounts = [(_email(r), r, False) for r in ROLES] + [(_email("lockout"), "OPERATOR", False),
                                                          (_email("mcp"), "OPERATOR", True)]
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.%@bess.local'"))
        for email, role, mcp in accounts:
            db.execute(text("""
                INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id, tenant_id, must_change_password)
                SELECT :id, :email, :pw, :name, r.role_id,
                       CASE WHEN r.is_tenant_scoped THEN (SELECT tenant_id FROM battery_master.tenant WHERE name = :tenant) END, :mcp
                FROM battery_users.role r WHERE r.role_code = :role"""),
                {"id": str(uuid.uuid4()), "email": email, "pw": password_helper.hash(PW), "name": f"pytest {role}",
                 "tenant": TENANT, "mcp": mcp, "role": role})
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.access_request WHERE email LIKE 'pytest.%'"))
        db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.%@bess.local'"))
        db.execute(text("DELETE FROM battery_users.auth_audit WHERE email LIKE 'pytest.%@bess.local' OR email IN ('%', '%@bess.local', 'admin%')"))
        db.commit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # one event loop for the async auth engine
        yield c


def login(client, email, password=PW, client_id="bess-batch"):
    client.cookies.clear()
    return client.post("/api/auth/token", data={"grant_type": "password", "username": email, "password": password,
                                                "client_id": client_id})


@pytest.fixture(scope="module")
def tokens(client):
    return {role: login(client, _email(role)).json()["access_token"] for role in ROLES}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _uses(dependant, fn) -> bool:
    return any(d.call is fn or _uses(d, fn) for d in dependant.dependencies)


def _forbidden_count() -> int:
    with SessionLocal() as db:
        return db.execute(text("SELECT count(*) FROM battery_users.auth_audit WHERE event = 'FORBIDDEN'")).scalar()


# ---------------------------------------------------------------- deny by default
def test_every_route_is_deny_by_default():
    open_routes = [r.path for r in app.routes if isinstance(r, APIRoute) and r.path not in PUBLIC
                   and not _uses(r.dependant, authenticated)]
    assert open_routes == [], f"routes without the authenticated dependency: {open_routes}"


def test_anonymous_is_rejected(client):
    client.cookies.clear()
    assert client.get("/api/sites").status_code == 401
    assert client.get("/api/tenants").status_code == 401
    assert client.get("/api/health").status_code == 200


# ---------------------------------------------------------------- login
def test_login_and_bad_password(client):
    r = login(client, _email("ADMIN"))
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 15 * 60 and body["refresh_expires_in"] > 7 * 3600
    bad = login(client, _email("ADMIN"), "wrong")
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"


def test_unknown_client_rejected(client):
    r = login(client, _email("ADMIN"), client_id="evil-app")
    assert r.status_code == 400 and r.json()["error"] == "invalid_client"


@pytest.mark.parametrize("pattern", ["%", "%@bess.local", "pytest.admin%", "pytest._dmin@bess.local"])
def test_wildcard_email_never_matches(client, pattern):
    with SessionLocal() as db:
        before = db.execute(text("SELECT failed_logins FROM battery_users.app_user WHERE email = :e"),
                            {"e": _email("ADMIN")}).scalar()
    r = login(client, pattern, "wrong")
    assert r.status_code == 400  # not 500, and no account matched
    with SessionLocal() as db:
        after = db.execute(text("SELECT failed_logins FROM battery_users.app_user WHERE email = :e"),
                           {"e": _email("ADMIN")}).scalar()
    assert after == before


def test_web_client_gets_refresh_cookie_not_body(client):
    r = login(client, _email("OPERATOR"), client_id="bess-web")
    assert r.status_code == 200
    assert "refresh_token" not in r.json()
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "bess_refresh=" in set_cookie and "httponly" in set_cookie and "samesite=strict" in set_cookie
    assert "path=/api/auth" in set_cookie


def test_cookie_refresh_rotation_and_logout(client):
    login(client, _email("OPERATOR"), client_id="bess-web")
    first = client.cookies.get("bess_refresh")
    r = client.post("/api/auth/token", data={"grant_type": "refresh_token", "client_id": "bess-web"})
    assert r.status_code == 200 and "refresh_token" not in r.json()
    second = client.cookies.get("bess_refresh")
    assert second and second != first
    out = client.post("/api/auth/revoke", data={"client_id": "bess-web"})
    assert out.status_code == 200
    client.cookies.set("bess_refresh", second, path="/api/auth")
    again = client.post("/api/auth/token", data={"grant_type": "refresh_token", "client_id": "bess-web"})
    assert again.status_code == 400


def test_body_refresh_rotation_and_revoke(client):
    first = login(client, _email("OPERATOR")).json()
    second = client.post("/api/auth/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"],
                                                  "client_id": "bess-batch"})
    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    reuse = client.post("/api/auth/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"],
                                                 "client_id": "bess-batch"})
    assert reuse.status_code == 400
    client.post("/api/auth/revoke", data={"token": second.json()["refresh_token"]})
    after = client.post("/api/auth/token", data={"grant_type": "refresh_token", "refresh_token": second.json()["refresh_token"],
                                                 "client_id": "bess-batch"})
    assert after.status_code == 400


def test_lockout_threshold_and_locked_refresh(client):
    email = _email("lockout")
    session = login(client, email).json()  # a live session from before the lockout
    for _ in range(5):
        assert login(client, email, "wrong").status_code == 400
    locked = login(client, email)  # right password, but locked
    assert locked.status_code == 400 and "locked" in locked.json()["error_description"].lower()
    r = client.post("/api/auth/token", data={"grant_type": "refresh_token", "refresh_token": session["refresh_token"],
                                             "client_id": "bess-batch"})
    assert r.status_code == 400 and "locked" in r.json()["error_description"].lower()


# ---------------------------------------------------------------- token validation
def test_forged_expired_and_wrong_key_tokens(client):
    s = token_settings()
    now = datetime.now(timezone.utc)
    claims = {"iss": s.issuer, "aud": s.audience, "sub": str(uuid.uuid4()), "typ": "access", "role": "ADMIN",
              "perms": ["master.asset:read"], "iat": now - timedelta(hours=1), "exp": now - timedelta(minutes=1)}
    expired = jwt.encode(claims, s.private_key, algorithm="RS256")
    r = client.get("/api/sites", headers=auth(expired))
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    wrong = jwt.encode({**claims, "exp": now + timedelta(minutes=5)}, other, algorithm="RS256")
    assert client.get("/api/sites", headers=auth(wrong)).status_code == 401
    assert client.get("/api/sites", headers=auth("abc.def.ghi")).status_code == 401


def test_me_claims(client, tokens):
    me = client.get("/api/auth/me", headers=auth(tokens["TENANT_VIEWER"])).json()
    assert me["role"] == "TENANT_VIEWER" and me["tenant_id"] is not None
    assert "master.asset:read" in me["permissions"] and "master.asset:write" not in me["permissions"]


# ---------------------------------------------------------------- password change
def test_must_change_password_blocks_until_changed(client):
    email = _email("mcp")
    tok = login(client, email).json()["access_token"]
    blocked = client.get("/api/sites", headers=auth(tok))
    assert blocked.status_code == 403 and "password change required" in blocked.json()["detail"].lower()
    assert client.get("/api/auth/me", headers=auth(tok)).status_code == 200  # auth endpoints stay reachable
    weak = client.post("/api/auth/change-password", headers=auth(tok), json={"current_password": PW, "new_password": "Password1"})
    assert weak.status_code == 400
    wrong = client.post("/api/auth/change-password", headers=auth(tok), json={"current_password": "nope", "new_password": "Grid-Battery-77x"})
    assert wrong.status_code == 400
    ok = client.post("/api/auth/change-password", headers=auth(tok),
                     json={"current_password": PW, "new_password": "Grid-Battery-77x", "client_id": "bess-batch"})
    assert ok.status_code == 200
    new = ok.json()["access_token"]
    assert client.get("/api/auth/me", headers=auth(new)).json()["must_change_password"] is False
    assert client.get("/api/sites", headers=auth(new)).status_code == 200
    assert login(client, email).status_code == 400  # old password gone
    assert login(client, email, "Grid-Battery-77x").status_code == 200


# ---------------------------------------------------------------- RBAC on Site
SITE_MATRIX = {  # (list, create-invalid-body, update-missing, delete-missing)
    "ADMIN": (200, 422, 404, 404),
    "ASSET_ENGINEER": (200, 422, 404, 403),
    "OPERATOR": (200, 403, 403, 403),
    "DATA_SCIENTIST": (200, 403, 403, 403),
    "TENANT_VIEWER": (200, 403, 403, 403),
}


@pytest.mark.parametrize("role", list(SITE_MATRIX))
def test_site_rbac(client, tokens, role):
    h = auth(tokens[role])
    got = (client.get("/api/sites", headers=h).status_code,
           client.post("/api/sites", headers=h, json={}).status_code,
           client.put("/api/sites/99999999", headers=h, json={"site_code": "X", "site_name": "X"}).status_code,
           client.delete("/api/sites/99999999", headers=h).status_code)
    assert got == SITE_MATRIX[role]


def test_forbidden_is_audited(client, tokens):
    before = _forbidden_count()
    assert client.delete("/api/sites/99999999", headers=auth(tokens["OPERATOR"])).status_code == 403
    assert _forbidden_count() == before + 1


def test_tenant_viewer_sees_only_own_sites(client, tokens):
    all_sites = client.get("/api/sites", headers=auth(tokens["ADMIN"])).json()
    own = client.get("/api/sites", headers=auth(tokens["TENANT_VIEWER"])).json()
    assert 0 < len(own) < len(all_sites)
    hidden = next(s for s in all_sites if s["site_id"] not in {o["site_id"] for o in own})
    assert client.get(f"/api/sites/{hidden['site_id']}", headers=auth(tokens["TENANT_VIEWER"])).status_code == 404


def test_other_modules_follow_the_matrix(client, tokens):
    # master.tenant:read is held by every role except Tenant Viewer (full matrix check: test_rbac_rollout.py)
    for role in ROLES:
        expected = 403 if role == "TENANT_VIEWER" else 200
        assert client.get("/api/tenants", headers=auth(tokens[role])).status_code == expected


def test_admin_endpoints(client, tokens):
    assert client.get("/api/auth/roles", headers=auth(tokens["ADMIN"])).status_code == 200
    assert client.get("/api/auth/users", headers=auth(tokens["OPERATOR"])).status_code == 403


# ---------------------------------------------------------------- self-service sign-up
def _signup(client, email, password="Wind-Storage-2026x", **extra):
    return client.post("/api/auth/signup", json={"full_name": "Py Test", "email": email, "organisation": "QA",
                                                 "reason": "Need read access to monitor the Bhadla site", "password": password,
                                                 **extra})


def _request_id(client, admin_token, email):
    rows = client.get("/api/auth/access-requests", headers=auth(admin_token)).json()["requests"]
    return next(r["request_id"] for r in rows if r["email"] == email)


def test_signup_approve_then_login(client, tokens):
    email = "pytest.signup.ok@bess.local"
    assert _signup(client, email).status_code == 202
    assert _signup(client, email).status_code == 409  # one open request per e-mail
    pending = login(client, email, "Wind-Storage-2026x")
    assert pending.status_code == 400 and "waiting" in pending.json()["error_description"]
    assert login(client, email, "wrong-pass").json()["error_description"] == "Invalid e-mail or password"  # no leak
    listing = client.get("/api/auth/access-requests?status=PENDING", headers=auth(tokens["ADMIN"])).json()
    assert "BATCH_SERVICE" not in {r["role_code"] for r in listing["roles"]}
    rid = _request_id(client, tokens["ADMIN"], email)
    assert client.post(f"/api/auth/access-requests/{rid}/approve", headers=auth(tokens["ADMIN"]),
                       json={"role_code": "TENANT_VIEWER"}).status_code == 400  # tenant-scoped role needs a tenant
    assert client.post(f"/api/auth/access-requests/{rid}/approve", headers=auth(tokens["ADMIN"]),
                       json={"role_code": "BATCH_SERVICE"}).status_code == 400
    ok = client.post(f"/api/auth/access-requests/{rid}/approve", headers=auth(tokens["ADMIN"]), json={"role_code": "OPERATOR"})
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    r = login(client, email, "Wind-Storage-2026x")
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=auth(r.json()["access_token"])).json()
    assert me["role"] == "OPERATOR" and me["must_change_password"] is False
    assert _signup(client, email).status_code == 409  # account exists now


def test_signup_reject_and_validation(client, tokens):
    email = "pytest.signup.no@bess.local"
    assert _signup(client, email, password="Password1").status_code == 400  # password policy
    assert _signup(client, "not-an-email").status_code == 422
    assert _signup(client, email).status_code == 202
    rid = _request_id(client, tokens["ADMIN"], email)
    rej = client.post(f"/api/auth/access-requests/{rid}/reject", headers=auth(tokens["ADMIN"]), json={"note": "Use your company SSO"})
    assert rej.status_code == 200 and rej.json()["status"] == "REJECTED"
    r = login(client, email, "Wind-Storage-2026x")
    assert r.status_code == 400 and "declined" in r.json()["error_description"]
    assert client.post(f"/api/auth/access-requests/{rid}/approve", headers=auth(tokens["ADMIN"]),
                       json={"role_code": "OPERATOR"}).status_code == 409  # already decided


def test_only_admin_reviews_requests(client, tokens):
    assert client.get("/api/auth/access-requests", headers=auth(tokens["OPERATOR"])).status_code == 403
    assert client.post("/api/auth/access-requests/99999999/approve", headers=auth(tokens["ASSET_ENGINEER"]),
                       json={"role_code": "OPERATOR"}).status_code == 403
