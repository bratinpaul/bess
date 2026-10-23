"""Database errors (exception plan phase 2): the constraint catalog covers every constraint, real violations map to the
catalog's code / status / message without database internals, and the API answers them through the shared handler.
Every write here fails inside a transaction that is rolled back - nothing in the database changes."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth.users import password_helper
from app.database import SessionLocal
from bess_common.errors_db import CONSTRAINTS, OVERRIDES, integrity_to_error, lookup

SCHEMAS = ["battery_master", "battery_users", "battery_raw", "battery_telemetry", "battery_ml", "battery_itops"]
INTERNALS = ("battery_master", "_fkey", "_key", "pkey", "violates", "Key (", "DETAIL", "psycopg2")
PW = "Pytest-ErrDb-2026x"
ADMIN = "pytest.errdb.admin@bess.local"


def test_catalog_covers_every_constraint():
    """Fails after a schema change until `python db_docs/gen_constraint_catalog.py` is re-run."""
    with SessionLocal() as db:
        names = {f"{s}.{n}" for s, n in db.execute(text("""
            SELECT n.nspname, con.conname FROM pg_constraint con
              JOIN pg_class cl ON cl.oid = con.conrelid JOIN pg_namespace n ON n.oid = cl.relnamespace
             WHERE n.nspname = ANY(:s) AND con.contype IN ('p', 'u', 'f', 'c', 'x')
            UNION
            SELECT n.nspname, ic.relname FROM pg_index i
              JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_namespace n ON n.oid = ic.relnamespace
             WHERE n.nspname = ANY(:s) AND i.indisunique
               AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)"""), {"s": SCHEMAS})}
    missing, stale = names - CONSTRAINTS.keys(), CONSTRAINTS.keys() - names
    assert not missing, f"constraints without a catalog entry (re-run the generator): {sorted(missing)[:20]}"
    assert not stale, f"catalog entries for dropped constraints (re-run the generator): {sorted(stale)[:20]}"
    assert set(OVERRIDES) <= set(CONSTRAINTS), "OVERRIDES names a constraint that no longer exists"


def test_catalog_entries_are_safe_and_complete():
    for key, e in CONSTRAINTS.items():
        assert e["kind"] in ("unique", "fk", "check") and e["status"] in (409, 422) and e["code"].isupper(), key
        name = key.split(".", 1)[1]
        for msg in (e["message"], e.get("in_use_message") or ""):
            assert name not in msg and "battery_" not in msg.replace("battery ", ""), (key, msg)
        if e["kind"] == "fk":
            assert e["in_use_status"] == 409 and e["in_use_message"], key


def test_hypertable_chunk_constraints_resolve():
    assert lookup("_timescaledb_internal", "58_130_alarm_event_pkey") is CONSTRAINTS["battery_telemetry.alarm_event_pkey"]
    assert lookup(None, "unknown_constraint") is None


def _violation(sql: str, params: dict | None = None):
    with SessionLocal() as db:
        with pytest.raises(IntegrityError) as info:
            db.execute(text(sql), params or {})
            db.flush()
        db.rollback()
    return integrity_to_error(info.value)


def _site_with_systems(db) -> tuple[int, str]:
    row = db.execute(text("""SELECT s.site_id, s.site_code FROM battery_master.site s
                             WHERE EXISTS (SELECT 1 FROM battery_master.battery_system b WHERE b.site_id = s.site_id)
                             ORDER BY s.site_id LIMIT 1""")).first()
    if row is None:
        pytest.skip("no site with battery systems")
    return row[0], row[1]


def test_real_violations_map_to_the_catalog():
    with SessionLocal() as db:
        site_id, site_code = _site_with_systems(db)
    err, constraint = _violation("INSERT INTO battery_master.site (site_code, site_name) VALUES (:c, 'pytest dup')",
                                 {"c": site_code})
    assert (err.status, err.code, constraint) == (409, "SITE_CODE_DUPLICATE", "site_site_code_key")
    assert err.public == "A site with this code already exists." and err.fields[0]["field"] == "site_code"

    err, _ = _violation("""INSERT INTO battery_master.battery_system (site_id, system_name, chemistry_code, series_cells,
                           parallel_cells) VALUES (-1, 'pytest', 'LFP', 1, 1)""")
    assert (err.status, err.code) == (422, "SITE_NOT_FOUND") and err.fields[0]["field"] == "site_id"

    err, _ = _violation("DELETE FROM battery_master.site WHERE site_id = :id", {"id": site_id})
    assert (err.status, err.code) == (409, "SITE_IN_USE")
    assert err.public == "This site can't be deleted or changed: battery system records still refer to it."

    err, _ = _violation("INSERT INTO battery_master.site (site_code, site_name) VALUES (NULL, 'x')")
    assert (err.status, err.code) == (422, "REQUIRED_VALUE_MISSING") and err.fields[0]["field"] == "site_code"


# ------------------------------------------------------------------ through the API
@pytest.fixture(scope="module")
def admin_token():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email = :e"), {"e": ADMIN})
        db.execute(text("""INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id,
                                                               must_change_password)
                           SELECT :id, :e, :pw, 'errdb admin', role_id, false FROM battery_users.role
                            WHERE role_code = 'ADMIN'"""),
                   {"id": str(uuid.uuid4()), "e": ADMIN, "pw": password_helper.hash(PW)})
        db.commit()
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/auth/token", data={"grant_type": "password", "username": ADMIN, "password": PW,
                                            "client_id": "bess-batch"})
        yield c, r.json()["access_token"]
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email = :e"), {"e": ADMIN})
        db.execute(text("DELETE FROM battery_users.auth_audit WHERE email = :e"), {"e": ADMIN})
        db.commit()


def _no_internals(r):
    for marker in INTERNALS:
        assert marker not in r.text, f"{marker!r} leaked: {r.text}"


def test_api_duplicate_and_in_use(admin_token):
    client, token = admin_token
    headers = {"Authorization": f"Bearer {token}"}
    with SessionLocal() as db:
        site_id, site_code = _site_with_systems(db)
        before = db.execute(text("SELECT count(*) FROM battery_master.site")).scalar()

    r = client.post("/api/sites", json={"site_code": site_code, "site_name": "pytest duplicate"}, headers=headers)
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"]["code"] == "SITE_CODE_DUPLICATE" and body["detail"] == "A site with this code already exists."
    assert body["error"]["fields"] == [{"field": "site_code", "message": "A site with this code already exists."}]
    _no_internals(r)

    r = client.delete(f"/api/sites/{site_id}", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SITE_IN_USE"
    _no_internals(r)

    with SessionLocal() as db:  # both requests were rolled back
        assert db.execute(text("SELECT count(*) FROM battery_master.site")).scalar() == before
        assert db.execute(text("SELECT 1 FROM battery_master.site WHERE site_id = :id"), {"id": site_id}).scalar()
