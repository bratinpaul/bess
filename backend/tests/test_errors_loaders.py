"""Exception management, phase 4: backend upload errors and the batch loaders.

- Upload / import errors are FileFormatError (400) with a fixed message; the parser's text stays in the log.
- Loader and controller errors are AppErrors; a batch that can't start is a generic 500 and a timeout is 504.
- The run-now output shown on the page has no stack traces.
- battery_raw.batchlog rows carry error_code and request_id. Every batchlog INSERT here is rolled back.
- Activity-log rows carry error_code.
Nothing is loaded and no batch is started (loads only run from the user's button click).
"""
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.users import password_helper
from app.database import SessionLocal
from bess_common import errors as E
from bess_common.db_settings import psycopg2_dsn
from bess_common.observability import activity, display_lines

PROJECT = Path(__file__).resolve().parents[2]
for folder in ("snapshot_loader", "static_data_loader", "historical_loader", "historical_generator"):
    if str(PROJECT / folder) not in sys.path:
        sys.path.insert(0, str(PROJECT / folder))

PW = "Pytest-ErrLoad-2026x"
REAL_CONNECT = psycopg2.connect  # tests replace psycopg2.connect (a module-wide name)
ADMIN = "pytest.errload.admin@bess.local"


class _Cursor:
    """Records the parameters of the batchlog INSERT and passes everything to the real cursor."""

    def __init__(self, cur, seen: dict):
        self.cur, self.seen = cur, seen

    def execute(self, sql, params=None):
        if "RETURNING batch_id" in sql:
            self.seen["params"] = params
        return self.cur.execute(sql, params)

    def fetchone(self):
        return self.cur.fetchone()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cur.close()
        return False


class _RolledBack:
    """Stands in for a psycopg2 connection: commit is a no-op, and the `with` block ends with a rollback."""

    def __init__(self, seen: dict | None = None, **dsn):
        self.conn = REAL_CONNECT(**dsn)
        self.seen = seen if seen is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.conn.rollback()
        return False

    def cursor(self):
        return _Cursor(self.conn.cursor(), self.seen)

    def commit(self):
        pass

    def close(self):
        self.conn.close()


def _row(batch_id: int):
    with REAL_CONNECT(**psycopg2_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT job_name, status, error_code, request_id, error_message FROM battery_raw.batchlog "
                    "WHERE batch_id = %s", (batch_id,))
        return cur.fetchone()


# ------------------------------------------------------------------ errors are AppErrors
def test_loader_errors_are_app_errors():
    import batch_control
    import generator_control
    import historical_control
    import historical_load
    import load_snapshot
    import static_control
    import static_load
    from snapshot_simulator import simulator
    import generator
    expected = {load_snapshot.SnapshotError: 400, static_load.StaticDataError: 400, historical_load.LoadError: 400,
                historical_control.HistoricalLoadError: 400, generator.GenerationError: 400,
                generator_control.GeneratorControlError: 400, simulator.SimulatorError: 400,
                batch_control.BatchError: 500, static_control.StaticBatchError: 500,
                batch_control.BatchTimeout: 504, static_control.StaticBatchTimeout: 504}
    for cls, status in expected.items():
        assert issubclass(cls, E.AppError) and cls("x").status == status, cls.__name__
    # a batch that can't start: generic message, the path only in log_message
    err = batch_control.BatchError(log_message="batch script not found: C:\\bess\\x.py")
    assert err.public == E.GENERIC_MESSAGE and "C:\\" in err.log_message


def test_run_now_output_has_no_stack_traces():
    lines = ['{"ts": "t", "level": "INFO", "logger": "x", "message": "2 file(s) to load"}',
             "Traceback (most recent call last):",
             '  File "C:\\bess\\snapshot_loader\\realtime_batch.py", line 9, in <module>',
             "    main()",
             "KeyError: 'password=hunter2'",
             "plain line with postgresql://u:hunter2@db/x"]
    shown = display_lines(lines)
    assert shown[0] == "INFO 2 file(s) to load"
    assert shown[1].startswith("ERROR the process stopped with an unexpected error")
    assert len(shown) == 3 and "hunter2" not in " ".join(shown) and "File " not in " ".join(shown)


# ------------------------------------------------------------------ loader error codes (no API, nothing loaded)
def test_snapshot_loader_error_codes(tmp_path):
    import load_snapshot
    outcome, report = load_snapshot.run(tmp_path / "missing.json", "http://127.0.0.1:9", out_dir=tmp_path / "out",
                                        log=lambda m: None)
    assert outcome == load_snapshot.FAILED and report["error_code"] == "FILE_NOT_FOUND"
    assert str(tmp_path) not in report["error"]  # the file name only, not the folder
    bad = tmp_path / "2026-10-23-00-00-00.json"
    bad.write_text("{not json", encoding="utf-8")
    outcome, report = load_snapshot.run(bad, "http://127.0.0.1:9", out_dir=tmp_path / "out", log=lambda m: None)
    assert outcome == load_snapshot.FAILED and report["error_code"] == "SNAPSHOT_INVALID"


def test_static_loader_error_code(tmp_path):
    import static_load
    bad = tmp_path / "bess_static_data.json"
    bad.write_text("{not json", encoding="utf-8")
    outcome, report = static_load.run(bad, "http://127.0.0.1:9", out_dir=tmp_path / "out", log=lambda m: None)
    assert outcome == static_load.FAILED and report["error_code"] == "STATIC_DATA_INVALID"
    assert report["error"].startswith("The file is not valid JSON")


def test_batch_error_code():
    assert E.batch_error_code("SUCCESS", "X") is None
    assert E.batch_error_code("PARTIAL") == "LOAD_PARTIAL" and E.batch_error_code("FAILED") == "LOAD_FAILED"
    assert E.batch_error_code("FAILED", "API_UNAVAILABLE") == "API_UNAVAILABLE"


# ------------------------------------------------------------------ batchlog rows (rolled back)
def test_realtime_batchlog_row_has_error_code_and_request_id():
    import realtime_batch
    from psycopg2.extras import Json
    run_id = str(uuid.uuid4())  # batchlog.run_id is a uuid
    now = datetime.now()
    row = dict(run_id=run_id, file_name="pytest.json", file_time=now, snapshot_time=None, status="FAILED",
               started_at=now, finished_at=now, duration_ms=0, feeds_total=0, feeds_loaded=0, feeds_failed=0,
               rows_total=0, rows_inserted=0, rows_updated=0, rows_skipped=0, feed_results=Json([]), warnings=Json([]),
               id_changes=Json([]), error_message="pytest.json can't be used", error_code="SNAPSHOT_INVALID",
               request_id=run_id, archive_path=None, api_url="http://127.0.0.1:9", host_name="pytest", report=Json({}))
    with _RolledBack(**psycopg2_dsn()) as conn:
        batch_id = realtime_batch.record(conn, row)
        with conn.cursor() as cur:  # visible inside the transaction
            cur.execute("SELECT error_code, request_id FROM battery_raw.batchlog WHERE batch_id = %s", (batch_id,))
            assert cur.fetchone() == ("SNAPSHOT_INVALID", run_id)
    assert _row(batch_id) is None  # rolled back


def test_generator_batchlog_row_has_codes(monkeypatch):
    import generate_queue
    seen: dict = {}
    monkeypatch.setattr(generate_queue.psycopg2, "connect", lambda **dsn: _RolledBack(seen, **dsn))
    run_id = str(uuid.uuid4())  # batchlog.run_id is a uuid
    jobs = {"run_id": run_id, "date_from": "2026-08-01", "date_to": "2026-08-02"}
    sites = [{"battery_system_id": 1, "site_name": "Pytest site", "system_name": "PYTEST", "folder_relative": "x",
              "status": "FAILED", "files": None, "rows": None, "warnings": [],
              "error": f"Unexpected error (ref {run_id}) - see the generator log"}]
    now = datetime.now().astimezone()
    batch_id = generate_queue.write_batchlog(jobs, sites, "FAILED", "1 of 1 site(s) failed", now, now, lambda m: None)
    assert batch_id is not None
    assert seen["params"]["error_code"] == "GENERATION_FAILED" and seen["params"]["run_id"] == run_id
    assert _row(batch_id) is None  # rolled back


# ------------------------------------------------------------------ through the API
@pytest.fixture(scope="module")
def api():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email = :e"), {"e": ADMIN})
        db.execute(text("""INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id,
                                                               must_change_password)
                           SELECT :id, :e, :pw, 'errload admin', role_id, false FROM battery_users.role
                            WHERE role_code = 'ADMIN'"""),
                   {"id": str(uuid.uuid4()), "e": ADMIN, "pw": password_helper.hash(PW)})
        db.commit()
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/auth/token", data={"grant_type": "password", "username": ADMIN, "password": PW,
                                            "client_id": "bess-batch"})
        yield c, {"Authorization": f"Bearer {r.json()['access_token']}"}
    activity.flush()
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.app_user WHERE email = :e"), {"e": ADMIN})
        db.execute(text("DELETE FROM battery_users.auth_audit WHERE email = :e"), {"e": ADMIN})
        db.commit()


def test_unreadable_upload_is_a_clean_400(api):
    client, headers = api
    r = client.post("/api/alarm-catalog/bulk", files={"file": ("broken.xlsx", b"this is not a workbook")},
                    headers={**headers, "X-Request-ID": "pytest-errload-0001"})
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"]["code"] == "FILE_FORMAT_INVALID"
    assert body["detail"] == "Could not read the Excel file. Please upload a valid .xlsx workbook."
    for marker in ("zip", "Zip", "BadZipFile", "openpyxl"):
        assert marker not in r.text


def test_unknown_master_entity_is_404(api):
    client, headers = api
    r = client.post("/api/master-bulk/nope", files={"file": ("x.csv", b"a,b\n1,2\n")}, headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "MASTER_ENTITY_UNKNOWN"


def test_activity_log_records_error_code(api):
    client, headers = api
    client.post("/api/alarm-catalog/bulk", files={"file": ("broken.xlsx", b"nope")},
                headers={**headers, "X-Request-ID": "pytest-errload-0002"})
    activity.flush()
    with SessionLocal() as db:
        code = db.execute(text("SELECT error_code FROM battery_itops.activity_log WHERE request_id = :r"),
                          {"r": "pytest-errload-0002"}).scalar()
    assert code == "FILE_FORMAT_INVALID"
