"""Logging and observability shared by the backend, the ML service and the batch loaders.

    setup_logging(service)      JSON lines (python-json-logger) to stdout and a daily-rotated file
                                <project>/logs/<service>/<service>.log (14 days); one logger per module via
                                logging.getLogger(__name__); uvicorn's loggers are routed through the same handlers
    request context             a contextvar holding request_id / user / role, added to every log line by a filter
    redaction                   keys such as password, token, authorization, cookie are masked; request / response
                                bodies are never logged (only metadata and row counts)
    operation(kind, name)       context manager: <kind>.start / <kind>.end with duration_ms, outcome and counts
                                (loads, KPI runs, training) - also written to the activity log
    RequestContextMiddleware    ASGI: accepts or creates X-Request-ID, returns it in the response header and in every
                                4xx/5xx JSON body ("request_id"), logs one access line per request, logs start/end of
                                loads / KPI runs / training recognised by path, and records changing or failed requests
    activity log                battery_ops.activity_log, written by a background thread (never blocks a request);
                                rows older than 90 days are purged once a day
"""
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

from pythonjsonlogger.json import JsonFormatter

ROOT = Path(__file__).resolve().parents[2]
SENSITIVE = {"password", "new_password", "current_password", "token", "access_token", "refresh_token", "authorization",
             "cookie", "set-cookie", "secret", "client_secret", "hashed_password", "api_key", "x-api-key"}
RID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
COUNT_KEYS = {
    "rows_total": ("rows_total", "total_rows", "total", "rows"),
    "rows_inserted": ("rows_inserted", "inserted", "created", "inserted_rows"),
    "rows_updated": ("rows_updated", "updated", "updated_rows"),
    "rows_rejected": ("rows_rejected", "rejected", "error_count", "invalid_rows", "skipped", "rows_skipped"),
}

_ctx: ContextVar[Optional[dict]] = ContextVar("bess_request_ctx", default=None)
_op: ContextVar[Optional["Operation"]] = ContextVar("bess_operation", default=None)
_service = "app"
log = logging.getLogger("bess.observability")


# ------------------------------------------------------------------ context + redaction
def current_context() -> dict:
    return _ctx.get() or {}


def set_user(email: Optional[str], role: Optional[str]) -> None:
    """Called by the auth dependency once the caller is known (the context dict is shared with the request task)."""
    ctx = _ctx.get()
    if ctx is not None:
        ctx["user"], ctx["role"] = email, role


@contextmanager
def request_context(request_id: Optional[str] = None, **fields):
    """Bind a request / run id (and optional user) for a block - used by the middleware and by batch loaders."""
    token = _ctx.set({"request_id": request_id or uuid.uuid4().hex, "user": None, "role": None, **fields})
    try:
        yield _ctx.get()
    finally:
        _ctx.reset(token)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if str(k).lower() in SENSITIVE else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _ctx.get() or {}
        record.service = _service
        for key in ("request_id", "user", "role"):
            if not hasattr(record, key):
                setattr(record, key, ctx.get(key))
        for key in list(record.__dict__):
            if key.lower() in SENSITIVE:
                record.__dict__[key] = "***"
            elif isinstance(record.__dict__[key], dict) and key not in ("args",):
                record.__dict__[key] = redact(record.__dict__[key])
        return True


def setup_logging(service: str, level: Optional[str] = None, log_dir: Optional[Path] = None) -> None:
    """Idempotent: JSON to stdout + daily file; uvicorn and bess.* loggers routed through the same handlers."""
    global _service
    _service = service
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    if getattr(root, "_bess_configured", None) == service:
        return
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = JsonFormatter("{asctime}{levelname}{name}{message}", style="{",
                        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
                        datefmt="%Y-%m-%dT%H:%M:%S%z", json_ensure_ascii=False)
    flt = _ContextFilter()
    stream = logging.StreamHandler(sys.stdout)
    handlers: list[logging.Handler] = [stream]
    directory = Path(log_dir or os.getenv("LOG_DIR", ROOT / "logs")) / service
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(TimedRotatingFileHandler(directory / f"{service}.log", when="midnight", backupCount=14,
                                                 encoding="utf-8"))
    except OSError as exc:  # read-only location: stdout only
        print(f"log file disabled: {exc}", file=sys.stderr)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(flt)
        root.addHandler(h)
    root.setLevel(level)
    # uvicorn: server messages through our JSON handlers; its access log is replaced by the middleware's
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
    access = logging.getLogger("uvicorn.access")
    access.handlers, access.propagate, access.disabled = [], False, True
    for name in ("bess.auth",):
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
    for noisy in ("sqlalchemy.engine", "httpx", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._bess_configured = service


# ------------------------------------------------------------------ activity log (battery_ops.activity_log)
class _ActivityWriter:
    COLUMNS = ("service", "kind", "event", "outcome", "request_id", "user_email", "role", "method", "path", "status_code",
               "duration_ms", "operation", "rows_total", "rows_inserted", "rows_updated", "rows_rejected", "ip", "detail")

    def __init__(self) -> None:
        self.engine = None
        self.q: "queue.Queue[dict]" = queue.Queue(maxsize=10_000)
        self.thread: Optional[threading.Thread] = None
        self.last_purge = 0.0

    def start(self, engine) -> None:
        self.engine = engine
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="activity-log-writer", daemon=True)
            self.thread.start()

    def put(self, row: dict) -> None:
        if self.engine is None:
            return
        try:
            self.q.put_nowait(row)
        except queue.Full:
            log.warning("activity log queue full - row dropped", extra={"event": "activity.dropped"})

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until queued rows are written (tests / loader shutdown)."""
        end = time.monotonic() + timeout
        while not self.q.empty() and time.monotonic() < end:
            time.sleep(0.05)
        time.sleep(0.1)

    def _run(self) -> None:
        from sqlalchemy import text
        sql = text(f"""INSERT INTO battery_ops.activity_log ({', '.join(self.COLUMNS)})
                       VALUES ({', '.join(':' + c for c in self.COLUMNS)})""")
        while True:
            batch = [self.q.get()]
            try:
                while len(batch) < 200:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            rows = [{c: (json.dumps(redact(r.get(c)), default=str) if c == "detail" and r.get(c) is not None else r.get(c))
                     for c in self.COLUMNS} for r in batch]
            try:
                with self.engine.begin() as conn:
                    conn.execute(sql, rows)
                    if time.time() - self.last_purge > 86_400:
                        conn.execute(text("DELETE FROM battery_ops.activity_log WHERE ts < now() - interval '90 days'"))
                        self.last_purge = time.time()
            except Exception as exc:  # noqa: BLE001 - logging must never take the service down
                print(f"activity log write failed: {exc}", file=sys.stderr)
            finally:
                for _ in batch:
                    self.q.task_done()


activity = _ActivityWriter()


def enable_activity_log(engine) -> None:
    activity.start(engine)


def record_activity(kind: str, event: str, outcome: str, **fields) -> None:
    ctx = current_context()
    activity.put({"service": _service, "kind": kind, "event": event, "outcome": outcome,
                  "request_id": fields.pop("request_id", ctx.get("request_id")),
                  "user_email": fields.pop("user_email", ctx.get("user")), "role": fields.pop("role", ctx.get("role")),
                  **fields})


def counts_from(payload: Any) -> dict:
    """Row counts from a load / KPI result (whatever the endpoint calls them)."""
    out: dict[str, int] = {}
    if isinstance(payload, dict):
        for target, names in COUNT_KEYS.items():
            for n in names:
                v = payload.get(n)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[target] = int(v)
                    break
                if isinstance(v, list) and target == "rows_rejected" and n in ("errors",):
                    out[target] = len(v)
                    break
        if "rows_rejected" not in out and isinstance(payload.get("errors"), list):
            out["rows_rejected"] = len(payload["errors"])
    return out


# ------------------------------------------------------------------ operations (loads, KPI runs, training)
class Operation:
    def __init__(self, kind: str, name: str, logger: logging.Logger, fields: dict):
        self.kind, self.name, self.logger, self.fields = kind, name, logger, dict(fields)
        self.counts: dict[str, int] = {}

    def set(self, **values) -> None:
        for k, v in values.items():
            if k in COUNT_KEYS:
                self.counts[k] = int(v or 0)
            else:
                self.fields[k] = v


@contextmanager
def operation(kind: str, name: str, logger: Optional[logging.Logger] = None, **fields):
    """with operation("load", "realtime_snapshot", file=...) as op: ...; op.set(rows_total=..., rows_inserted=...)"""
    lg = logger or log
    op = Operation(kind, name, lg, fields)
    op_token = _op.set(op)
    t0 = time.perf_counter()
    lg.info(f"{kind} {name} started", extra={"event": f"{kind}.start", "operation": name, **redact(op.fields)})
    try:
        yield op
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        lg.exception(f"{kind} {name} failed", extra={"event": f"{kind}.end", "operation": name, "outcome": "failed",
                                                     "duration_ms": ms, "error": type(exc).__name__, **op.counts})
        record_activity(kind.upper(), f"{kind}.end", "failed", operation=name, duration_ms=ms, **op.counts,
                        detail={"error": type(exc).__name__, "message": str(exc)[:300], **redact(op.fields)})
        raise
    finally:
        _op.reset(op_token)
    ms = int((time.perf_counter() - t0) * 1000)
    outcome = op.fields.pop("outcome", "success")
    lg.info(f"{kind} {name} finished", extra={"event": f"{kind}.end", "operation": name, "outcome": outcome,
                                              "duration_ms": ms, **op.counts, **redact(op.fields)})
    record_activity(kind.upper(), f"{kind}.end", outcome, operation=name, duration_ms=ms, **op.counts,
                    detail=redact(op.fields) or None)


def op_set(**values) -> None:
    """Report counts / fields to the innermost running operation (no-op outside one) - for code deep inside a load."""
    op = _op.get()
    if op is not None:
        op.set(**values)


def engine_from_dsn(dsn: dict):
    """SQLAlchemy engine from psycopg2-style settings (host, port, dbname, user, password) - for the batch loaders."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    url = URL.create("postgresql+psycopg2", username=dsn.get("user"), password=dsn.get("password"),
                     host=dsn.get("host"), port=dsn.get("port"), database=dsn.get("dbname"))
    return create_engine(url, pool_size=1, max_overflow=1, pool_pre_ping=True)


# ------------------------------------------------------------------ request middleware
Classifier = Callable[[str, str], Optional[tuple[str, str]]]  # (method, path) -> (kind, operation name) or None


class RequestContextMiddleware:
    """Pure ASGI (bodies stream through untouched except 4xx/5xx JSON - and the JSON of recognised operations, which is
    read for row counts). `classify(method, path)` names loads / KPI runs / training."""

    def __init__(self, app, classify: Optional[Classifier] = None, auth_prefix: str = "/api/auth/"):
        self.app, self.classify, self.auth_prefix = app, classify, auth_prefix
        self.logger = logging.getLogger("bess.request")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if RID_RE.match(incoming) else uuid.uuid4().hex
        ip = (scope.get("client") or ("?",))[0]
        op = self.classify(method, path) if self.classify else None
        state: dict = {"status": None, "started": False, "held": None, "chunks": [], "body_json": None}
        t0 = time.perf_counter()
        token = _ctx.set({"request_id": rid, "user": None, "role": None})
        if op:
            self.logger.info(f"{op[0]} {op[1]} started", extra={"event": f"{op[0]}.start", "operation": op[1],
                                                                "method": method, "path": path})

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                state["status"] = status
                hdrs = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                hdrs.append((b"x-request-id", rid.encode()))
                ctype = next((v.decode() for k, v in hdrs if k.lower() == b"content-type"), "")
                message = {**message, "headers": hdrs}
                if "json" in ctype and (status >= 400 or op):
                    state["held"] = message  # read the body: inject request_id into errors / take counts from results
                    return
                state["started"] = True
                await send(message)
            elif message["type"] == "http.response.body" and state["held"] is not None:
                state["chunks"].append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(state["chunks"])
                try:
                    data = json.loads(body) if body else None
                except ValueError:
                    data = None
                state["body_json"] = data
                if state["status"] >= 400 and isinstance(data, dict):
                    data["request_id"] = rid
                    body = json.dumps(data, default=str).encode()
                start = state["held"]
                start["headers"] = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + \
                                   [(b"content-length", str(len(body)).encode())]
                state["held"], state["started"] = None, True
                await send(start)
                await send({"type": "http.response.body", "body": body, "more_body": False})
            else:
                await send(message)

        error: Optional[BaseException] = None
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # unhandled -> JSON 500 with the request id (no stack trace to the client)
            error = exc
            state["status"] = 500
            if not state["started"]:
                body = json.dumps({"detail": "Internal server error", "request_id": rid}).encode()
                await send({"type": "http.response.start", "status": 500,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                        (b"x-request-id", rid.encode())]})
                await send({"type": "http.response.body", "body": body, "more_body": False})
        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            ctx = _ctx.get() or {}
            principal = (scope.get("state") or {}).get("principal")
            user = ctx.get("user") or getattr(principal, "email", None)
            role = ctx.get("role") or getattr(principal, "role", None)
            status = state["status"] or 500
            outcome = "success" if status < 400 else "failed"
            query_keys = sorted({k for k, _, _ in (p.partition("=") for p in scope.get("query_string", b"").decode().split("&")) if k})
            base = {"method": method, "path": path, "status_code": status, "duration_ms": ms, "ip": ip,
                    "user": user, "role": role}
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            self.logger.log(level, f"{method} {path} {status} {ms}ms",
                            extra={"event": "request", "outcome": outcome, "query_keys": query_keys or None, **base},
                            exc_info=error if error else None)
            kind, name, counts, detail = None, None, {}, None
            if op:
                kind, name = op[0].upper(), op[1]
                counts = counts_from(state["body_json"])
                body = state["body_json"] if isinstance(state["body_json"], dict) else {}
                detail = {k: body.get(k) for k in ("run_id", "study_id", "status", "entity", "filename", "batch_id",
                                                   "model", "best_model") if body.get(k) is not None} or None
                self.logger.log(level, f"{op[0]} {name} finished",
                                extra={"event": f"{op[0]}.end", "operation": name, "outcome": outcome, **counts, **base})
            elif path.startswith(self.auth_prefix) and method == "POST":
                kind = None  # auth events are recorded by the auth service itself (it knows the e-mail and the outcome)
            elif status >= 400 or method in ("POST", "PUT", "PATCH", "DELETE"):
                kind, name = ("ERROR" if status >= 500 else "REQUEST"), None
            if kind and not (method == "GET" and status < 400):
                if status >= 400 and isinstance(state["body_json"], dict):
                    d = state["body_json"].get("detail")
                    detail = {**(detail or {}), "error": d if isinstance(d, str) else "validation" if d else None}
                if error is not None:
                    detail = {**(detail or {}), "error": type(error).__name__}
                activity.put({"service": _service, "kind": kind, "event": f"{kind.lower()}.end" if op else "request",
                              "outcome": outcome, "request_id": rid, "user_email": user, "role": role, "method": method,
                              "path": path, "status_code": status, "duration_ms": ms, "operation": name, "ip": ip,
                              "detail": detail, **counts})
            _ctx.reset(token)
