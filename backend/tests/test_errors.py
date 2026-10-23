"""Exception management (bess_common/errors.py, phase 1): the error body shape, safe 5xx messages with the stack trace
in the log, no echo of submitted values on 422, DB errors mapped without internals, credential scrubbing in logs,
run_guard / run_main, and /docs switched off in production. A throw-away app exercises the handlers; the real backend
is only asked for things that need no data (unknown route, an invalid sign-up body)."""
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import exc as sa_exc

from bess_common import errors
from bess_common.errors import (AppError, Conflict, InternalError, TrainingError, error_body, install_exception_handlers,
                                run_guard, run_main)
from bess_common.observability import RequestContextMiddleware, scrub

LEAKS = ("Traceback", "psycopg2", "sqlalchemy", "SELECT ", "INSERT ", "constraint", "C:\\", "/home/", "hunter2",
         "S3cr3t")


class _PgDiag:
    def __init__(self, constraint=None, primary="", column=None):
        self.constraint_name, self.message_primary, self.column_name = constraint, primary, column
        self.schema_name, self.table_name = "battery_master", "site"
        self.message_detail = "Key (site_code)=(S3cr3t) already exists."


class _PgError(Exception):
    def __init__(self, pgcode, **diag):
        super().__init__(f'duplicate key value violates unique constraint "uq_site_code" password=hunter2')
        self.pgcode, self.diag = pgcode, _PgDiag(**diag)


def _integrity(pgcode, **diag):
    return sa_exc.IntegrityError("INSERT INTO battery_master.site VALUES (%(code)s)", {"code": "S3cr3t"},
                                 _PgError(pgcode, **diag))


class Body(BaseModel):
    name: str = Field(min_length=3)
    password: str = Field(min_length=12)


def _app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("connect to postgresql://bess:S3cr3t@db failed at C:\\bess\\secret.py")

    @app.get("/wrapped")
    def wrapped():
        try:
            raise ValueError("SELECT * FROM battery_master.site WHERE password=hunter2")
        except ValueError as exc:
            raise HTTPException(status_code=500, detail={"message": f"Training failed: {exc}", "run_id": 7})

    @app.get("/http4xx")
    def http4xx():
        raise HTTPException(status_code=404, detail="Site 99 not found")

    @app.get("/dict4xx")
    def dict4xx():
        raise HTTPException(status_code=400, detail={"message": "Only 3 days of data", "run_id": 5})

    @app.get("/app-error")
    def app_error():
        raise Conflict("A site with this code already exists.", code="SITE_CODE_DUPLICATE",
                       fields=[{"field": "site_code", "message": "Already in use"}])

    @app.get("/unique")
    def unique():
        raise _integrity("23505", constraint="uq_site_code")

    @app.get("/fk-insert")
    def fk_insert():
        raise _integrity("23503", constraint="site_tenant_id_fkey", primary='insert or update on table "site"')

    @app.get("/fk-delete")
    def fk_delete():
        raise _integrity("23503", constraint="bs_site_fkey", primary='update or delete on table "site"')

    @app.get("/db-down")
    def db_down():
        raise sa_exc.OperationalError("SELECT 1", {}, Exception("could not connect password=hunter2"))

    @app.get("/timeout")
    def timeout():
        raise TimeoutError("slow")

    @app.get("/run")
    def run():
        failed = []
        with run_guard(fail=failed.append, context={"run_id": 11}):
            raise KeyError("feature_x missing in C:\\bess\\models")

    @app.get("/run-user")
    def run_user():
        with run_guard(context={"run_id": 12}):
            raise TrainingError("Only 12 days of data; at least 30 are required.")

    @app.post("/body")
    def body(payload: Body):
        return {"ok": True}

    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.fixture(scope="module")
def client():
    with TestClient(_app(), raise_server_exceptions=False) as c:
        yield c


def _no_leaks(response):
    text = response.text
    for marker in LEAKS:
        assert marker not in text, f"{marker!r} leaked: {text}"


def _shape(r, status, code):
    assert r.status_code == status
    body = r.json()
    assert body["error"]["code"] == code
    assert body["error"]["status"] == status
    assert body["request_id"] == r.headers["x-request-id"]
    return body


def test_unhandled_exception_is_generic_and_logged_with_trace(client, caplog):
    with caplog.at_level(logging.ERROR):
        r = client.get("/boom", headers={"X-Request-ID": "pytest-err-boom-1"})
    body = _shape(r, 500, "INTERNAL_ERROR")
    assert body["detail"] == body["error"]["message"] == "An unexpected error occurred. Reference: pytest-err-boom-1"
    _no_leaks(r)
    assert any(rec.exc_info and rec.exc_info[0] is RuntimeError for rec in caplog.records)


def test_wrapped_500_hides_text_keeps_run_id_and_logs_cause(client, caplog):
    with caplog.at_level(logging.ERROR, logger="bess.errors"):
        r = client.get("/wrapped")
    body = _shape(r, 500, "INTERNAL_ERROR")
    assert body["error"]["context"] == {"run_id": 7}
    assert body["detail"]["run_id"] == 7 and body["detail"]["message"].startswith("An unexpected error occurred.")
    _no_leaks(r)
    logged = [rec for rec in caplog.records if rec.name == "bess.errors"]
    assert logged and logged[0].exc_info[0] is ValueError  # the stack trace of the wrapped exception is kept


def test_4xx_http_exception_keeps_detail(client):
    body = _shape(client.get("/http4xx"), 404, "NOT_FOUND")
    assert body["detail"] == body["error"]["message"] == "Site 99 not found"
    body = _shape(client.get("/dict4xx"), 400, "BAD_REQUEST")
    assert body["detail"] == {"message": "Only 3 days of data", "run_id": 5}  # older pages read detail.message
    assert body["error"]["message"] == "Only 3 days of data" and body["error"]["context"] == {"run_id": 5}


def test_app_error(client):
    body = _shape(client.get("/app-error"), 409, "SITE_CODE_DUPLICATE")
    assert body["error"]["fields"] == [{"field": "site_code", "message": "Already in use"}]


@pytest.mark.parametrize("path,status,code", [("/unique", 409, "DUPLICATE"), ("/fk-insert", 422, "REFERENCE_NOT_FOUND"),
                                              ("/fk-delete", 409, "IN_USE")])
def test_integrity_errors_are_mapped_without_internals(client, path, status, code):
    r = client.get(path)
    _shape(r, status, code)
    _no_leaks(r)
    assert "uq_site_code" not in r.text and "battery_master" not in r.text


def test_constraint_catalog_entry_wins(client, monkeypatch):
    from bess_common import errors_db
    monkeypatch.setitem(errors_db.CONSTRAINTS, "battery_master.uq_site_code",
                        {"kind": "unique", "code": "SITE_CODE_DUPLICATE", "status": 409,
                         "message": "A site with this code already exists.", "field": "site_code"})
    body = _shape(client.get("/unique"), 409, "SITE_CODE_DUPLICATE")
    assert body["error"]["fields"][0]["field"] == "site_code"


def test_db_unavailable_and_timeout(client):
    r = client.get("/db-down")
    _shape(r, 503, "DATABASE_UNAVAILABLE")
    _no_leaks(r)
    _shape(client.get("/timeout"), 504, "DEPENDENCY_TIMEOUT")


def test_validation_error_never_echoes_input(client):
    r = client.post("/body", json={"name": "x", "password": "hunter2"})
    body = _shape(r, 422, "VALIDATION_FAILED")
    _no_leaks(r)
    assert {f["field"] for f in body["error"]["fields"]} == {"name", "password"}
    assert all(set(e) == {"type", "loc", "msg"} for e in body["detail"])  # same list shape, minus input / ctx


def test_run_guard(client):
    failed = []
    with pytest.raises(InternalError) as info:
        with run_guard(fail=failed.append, context={"run_id": 3}):
            raise KeyError("secret column")
    assert info.value.context == {"run_id": 3} and isinstance(info.value.__cause__, KeyError)
    assert failed and failed[0].startswith("Unexpected error") and "secret" not in failed[0]

    failed.clear()
    with pytest.raises(TrainingError):
        with run_guard(fail=failed.append):
            raise TrainingError("Only 12 days of data.")
    assert failed == ["Only 12 days of data."]

    body = _shape(client.get("/run"), 500, "INTERNAL_ERROR")
    assert body["error"]["context"] == {"run_id": 11}
    body = _shape(client.get("/run-user"), 422, "TRAINING_FAILED")
    assert body["error"]["message"] == "Only 12 days of data; at least 30 are required."
    assert body["error"]["context"] == {"run_id": 12}


def test_run_main_exit_codes():
    assert run_main("pytest_job", lambda: None) == errors.EXIT_OK
    assert run_main("pytest_job", lambda: errors.EXIT_PARTIAL) == errors.EXIT_PARTIAL

    def config():
        raise errors.ConfigError("DATABASE_URL is missing")

    def failed():
        raise AppError("Load failed")

    def crash():
        raise ZeroDivisionError

    assert run_main("pytest_job", config) == errors.EXIT_CONFIG
    assert run_main("pytest_job", failed) == errors.EXIT_FAILED
    assert run_main("pytest_job", crash) == errors.EXIT_UNEXPECTED


def test_scrub():
    assert scrub("postgresql+psycopg2://bess:S3cr3t@localhost/battery") == "postgresql+psycopg2://bess:***@localhost/battery"
    assert scrub("password=hunter2 host=db") == "password=*** host=db"
    assert scrub("{'password': 'hunter2'}") == "{'password': '***'}"
    assert scrub("Authorization: Bearer abc.def") == "Authorization: Bearer ***"
    assert "eyJ" not in scrub("token eyJhbGciOiJSUzI1.eyJzdWIiOiJ4eXo.c2lnbmF0dXJl")
    assert scrub("x\n[parameters: {'pw': 'hunter2'}]\n(Background on this error at: y)") == \
        "x\n[parameters: ***]\n(Background on this error at: y)"
    assert scrub("token_expired, 5 tokens: ok") == "token_expired, 5 tokens: ok"


def test_log_lines_are_scrubbed(capsys):
    from bess_common.observability import _ContextFilter, _ScrubbingJsonFormatter
    record = logging.LogRecord("bess.test", logging.ERROR, __file__, 1, "connect %s failed", ("postgresql://u:hunter2@h/db",),
                               None)
    try:
        raise RuntimeError("password=hunter2")
    except RuntimeError:
        import sys
        record.exc_info = sys.exc_info()
    _ContextFilter().filter(record)
    line = _ScrubbingJsonFormatter("{message}", style="{").format(record)
    assert "hunter2" not in line and "***" in line


def test_error_body_shape():
    assert error_body("X", "msg", 400) == {"detail": "msg", "error": {"code": "X", "message": "msg", "status": 400}}


def test_api_docs_off_in_prod(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    assert errors.api_docs_kwargs() == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    monkeypatch.setenv("APP_ENV", "dev")
    assert errors.api_docs_kwargs() == {}


# ------------------------------------------------------------------ the real backend
@pytest.fixture(scope="module")
def backend():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_backend_unknown_route_has_error_shape(backend):
    _shape(backend.get("/api/health/nope", headers={"X-Request-ID": "pytest-err-404-01"}), 404, "NOT_FOUND")


def test_backend_signup_422_does_not_echo_password(backend):
    r = backend.post("/api/auth/signup", json={"full_name": "p", "email": "pytest.err@bess.local", "reason": "short",
                                               "password": ""}, headers={"X-Request-ID": "pytest-err-422-01"})
    _shape(r, 422, "VALIDATION_FAILED")
    r = backend.post("/api/auth/signup", json={"full_name": "p", "email": "x", "reason": "short", "password": "hunter2"},
                     headers={"X-Request-ID": "pytest-err-422-02"})
    _shape(r, 422, "VALIDATION_FAILED")
    _no_leaks(r)


def test_backend_401_has_error_shape(backend):
    body = _shape(backend.get("/api/sites", headers={"X-Request-ID": "pytest-err-401-01"}), 401, "UNAUTHENTICATED")
    assert body["detail"]


# ------------------------------------------------------------------ phase 3: routers don't build error text
def test_no_backend_router_returns_server_exception_text():
    """5xx answers never carry exception text, and routers don't swallow exceptions (the handlers answer them)."""
    import re
    from pathlib import Path
    pattern = re.compile(r"status_code=5\d\d[^)]*(str\(exc|\{exc)|except Exception(?!.*noqa: BLE001 - )")
    routers = Path(__file__).resolve().parents[1] / "app" / "routers"
    offenders = [f"{p.name}:{n}" for p in routers.glob("*.py")
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
    assert offenders == []
