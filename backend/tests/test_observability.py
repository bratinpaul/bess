"""Logging / observability: X-Request-ID, request ids in error bodies, JSON log lines, redaction, the activity log for
failed and changing requests, loads and KPI runs, and the activity viewer's permission. Nothing is loaded for real:
the load is an empty file (rejected) and the KPI run is a dry run (rolled back)."""
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.users import password_helper
from app.database import SessionLocal
from app.main import app
from bess_common.observability import ROOT, activity

PW = "Pytest-Obs-2026x"
USERS = {"ADMIN": "pytest.obs.admin@bess.local", "OPERATOR": "pytest.obs.operator@bess.local"}


@pytest.fixture(scope="module", autouse=True)
def users():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.obs.%'"))
        for role, email in USERS.items():
            db.execute(text("""INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id, must_change_password)
                               SELECT :id, :e, :pw, :n, role_id, false FROM battery_users.role WHERE role_code = :r"""),
                       {"id": str(uuid.uuid4()), "e": email, "pw": password_helper.hash(PW), "n": f"obs {role}", "r": role})
        db.commit()
    yield
    activity.flush()
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email LIKE 'pytest.obs.%'"))
        db.execute(text("DELETE FROM battery_users.auth_audit WHERE email LIKE 'pytest.obs.%'"))
        db.execute(text("DELETE FROM battery_itops.activity_log WHERE user_email LIKE 'pytest.obs.%' OR request_id LIKE 'pytest-%'"))
        db.commit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def tokens(client):
    out = {}
    for role, email in USERS.items():
        r = client.post("/api/auth/token", data={"grant_type": "password", "username": email, "password": PW,
                                                 "client_id": "bess-batch"})
        out[role] = r.json()["access_token"]
    return out


def h(token, rid=None):
    out = {"Authorization": f"Bearer {token}"}
    if rid:
        out["X-Request-ID"] = rid
    return out


def activity_rows(rid: str) -> list[dict]:
    activity.flush()
    with SessionLocal() as db:
        return [dict(r) for r in db.execute(text("SELECT * FROM battery_itops.activity_log WHERE request_id = :r ORDER BY activity_id"),
                                            {"r": rid}).mappings()]


def test_request_id_echoed_generated_and_sanitised(client):
    assert client.get("/api/health", headers={"X-Request-ID": "pytest-abc-12345"}).headers["x-request-id"] == "pytest-abc-12345"
    generated = client.get("/api/health").headers["x-request-id"]
    assert len(generated) == 32
    bad = client.get("/api/health", headers={"X-Request-ID": "x<script>"}).headers["x-request-id"]
    assert bad != "x<script>" and len(bad) == 32


def test_error_bodies_carry_the_request_id(client, tokens):
    r404 = client.get("/api/sites/99999999", headers=h(tokens["ADMIN"], "pytest-err-404x"))
    assert r404.status_code == 404 and r404.json()["request_id"] == "pytest-err-404x" and "detail" in r404.json()
    r403 = client.delete("/api/sites/99999999", headers=h(tokens["OPERATOR"], "pytest-err-403x"))
    assert r403.status_code == 403 and r403.json()["request_id"] == "pytest-err-403x"
    r401 = client.get("/api/sites", headers={"X-Request-ID": "pytest-err-401x"})
    assert r401.status_code == 401 and r401.json()["request_id"] == "pytest-err-401x"


def test_failed_and_changing_requests_are_recorded(client, tokens):
    client.delete("/api/sites/99999999", headers=h(tokens["OPERATOR"], "pytest-act-denied"))
    rows = activity_rows("pytest-act-denied")
    assert rows and rows[0]["outcome"] == "failed" and rows[0]["status_code"] == 403
    assert rows[0]["user_email"] == USERS["OPERATOR"] and rows[0]["role"] == "OPERATOR" and rows[0]["method"] == "DELETE"
    client.get("/api/sites", headers=h(tokens["ADMIN"], "pytest-act-getok"))
    assert activity_rows("pytest-act-getok") == []  # successful GETs only go to the access log file


def test_load_is_logged_with_counts(client, tokens):
    r = client.post("/api/alarm-catalog/bulk", headers=h(tokens["ADMIN"], "pytest-load-empty"),
                    files={"file": ("empty.csv", b"", "text/csv")})
    assert r.status_code == 400
    rows = activity_rows("pytest-load-empty")
    assert rows and rows[0]["kind"] == "LOAD" and rows[0]["operation"] == "alarm-catalog_bulk" and rows[0]["outcome"] == "failed"


def test_kpi_run_is_logged(client, tokens):
    with SessionLocal() as db:  # a system that has BMS telemetry
        sid = db.execute(text("SELECT system_id FROM battery_telemetry.system_telemetry LIMIT 1")).scalar()
    r = client.post("/api/bms-kpi/calculate", headers=h(tokens["ADMIN"], "pytest-kpi-dryrun"),
                    json={"system_id": sid, "start_date": "2026-08-01", "end_date": "2026-08-02", "dry_run": True})
    assert r.status_code == 200, r.text
    rows = [x for x in activity_rows("pytest-kpi-dryrun") if x["kind"] == "KPI"]
    assert rows and rows[0]["operation"] == "bms_kpi" and rows[0]["outcome"] == "success"
    assert rows[0]["rows_inserted"] == r.json()["rows_written"] and rows[0]["duration_ms"] is not None


def test_log_file_is_json_with_context_and_no_secrets(client, tokens):
    client.post("/api/auth/token", data={"grant_type": "password", "username": USERS["OPERATOR"], "password": PW,
                                         "client_id": "bess-batch"}, headers={"X-Request-ID": "pytest-log-login"})
    client.get("/api/sites", headers=h(tokens["OPERATOR"], "pytest-log-line1"))
    path = Path(ROOT) / "logs" / "backend" / "backend.log"
    text_ = path.read_text(encoding="utf-8")
    assert PW not in text_ and tokens["OPERATOR"] not in text_  # never passwords or tokens
    lines = [json.loads(l) for l in text_.splitlines() if "pytest-log-line1" in l]
    access = next(l for l in lines if l.get("event") == "request")
    assert access["user"] == USERS["OPERATOR"] and access["status_code"] == 200 and access["level"] == "INFO"
    assert {"ts", "logger", "service", "request_id", "duration_ms"} <= set(access)


def test_activity_viewer_needs_audit_read(client, tokens):
    assert client.get("/api/admin/activity", headers=h(tokens["OPERATOR"])).status_code == 403
    r = client.get("/api/admin/activity?request_id=pytest-act-denied", headers=h(tokens["ADMIN"]))
    assert r.status_code == 200 and r.json()["total"] >= 1
