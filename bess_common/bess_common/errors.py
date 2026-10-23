"""Exception management shared by the backend, the ML service and the batch loaders.

    AppError + subclasses       raise these from routers / services: an HTTP status, a stable code and a public message
                                that is safe to show; log_message and the chained cause go to the log only
    error_body(...)             the one error response shape:
                                  {"detail": <message - kept for older pages>,
                                   "error": {"code", "message", "status", "fields"?, "context"?}}
                                (RequestContextMiddleware adds "request_id" to every 4xx/5xx JSON body)
    install_exception_handlers(app)
                                AppError, HTTPException, RequestValidationError (submitted values are never echoed),
                                SQLAlchemy / psycopg2 integrity, data and connection errors, timeouts -> error_body.
                                4xx keep their message; 5xx always answer the generic message with the reference and are
                                logged once at ERROR with the stack trace (also of the exception a router wrapped in an
                                HTTPException(500, ...)). Any other exception is answered by RequestContextMiddleware.
    run_guard(fail, context)    model training / scoring / KPI runs: records the run as failed with a public text and
                                re-raises as an AppError (unexpected errors -> InternalError with the original chained)
    run_main(job, fn)           batch entry point: binds a run id, catches everything, returns a defined exit code
    api_docs_kwargs()           /docs, /redoc and /openapi.json are switched off when APP_ENV=prod
"""
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Optional

from bess_common.db_settings import setting
from bess_common.observability import current_context, request_context, scrub

log = logging.getLogger("bess.errors")

GENERIC_MESSAGE = "An unexpected error occurred."
MAX_MESSAGE = 500
# ids a 5xx body may still carry (the page needs the run it started); everything else in a 5xx detail is dropped
CONTEXT_KEYS = ("run_id", "study_id", "batch_id", "job", "entity", "filename")

# status -> (code, message) for errors raised without one of their own
STATUS_DEFAULTS = {
    400: ("BAD_REQUEST", "The request is not valid."),
    401: ("UNAUTHENTICATED", "Please sign in again."),
    403: ("FORBIDDEN", "You do not have permission for this action."),
    404: ("NOT_FOUND", "The requested item was not found."),
    405: ("METHOD_NOT_ALLOWED", "This action is not supported."),
    409: ("CONFLICT", "This change conflicts with existing data."),
    413: ("PAYLOAD_TOO_LARGE", "The upload is too large."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "This file or content type is not supported."),
    422: ("VALIDATION_FAILED", "Some fields are invalid."),
    429: ("RATE_LIMITED", "Too many requests - please wait and retry."),
    500: ("INTERNAL_ERROR", GENERIC_MESSAGE),
    502: ("BAD_GATEWAY", "A dependent service returned an invalid answer. Please retry."),
    503: ("SERVICE_UNAVAILABLE", "The service is temporarily unavailable. Please retry."),
    504: ("DEPENDENCY_TIMEOUT", "The operation timed out. Please retry."),
}

# batch exit codes (run_main)
EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_CONFIG, EXIT_UNEXPECTED = 0, 1, 2, 3, 4


# ------------------------------------------------------------------ exception hierarchy
class AppError(Exception):
    """Base of every expected error. `public` is shown to the user - never put exception text or SQL in it."""
    status = 500
    code = "INTERNAL_ERROR"
    public = GENERIC_MESSAGE
    log_level = logging.ERROR

    def __init__(self, public: Optional[str] = None, *, code: Optional[str] = None, status: Optional[int] = None,
                 fields: Optional[list[dict]] = None, context: Optional[dict] = None, log_message: Optional[str] = None):
        if public is not None:
            self.public = _clip(public)  # str() of whatever was passed, credentials scrubbed, length capped
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        self.fields = fields
        self.context = context
        self.log_message = log_message
        super().__init__(log_message or self.public)


class InternalError(AppError):
    """An unexpected failure, already logged or to be logged with its chained cause."""


class BadRequest(AppError):
    status, code, public, log_level = 400, "BAD_REQUEST", "The request is not valid.", logging.WARNING


class ValidationFailed(BadRequest):
    status, code, public = 422, "VALIDATION_FAILED", "Some fields are invalid."


class FileFormatError(BadRequest):
    code, public = "FILE_FORMAT_INVALID", "The file is not in the expected format."


class NotFound(AppError):
    status, code, public, log_level = 404, "NOT_FOUND", "The requested item was not found.", logging.INFO


class Conflict(AppError):
    status, code, public, log_level = 409, "CONFLICT", "This change conflicts with existing data.", logging.WARNING


class BusinessRuleViolation(AppError):
    status, code, public, log_level = 422, "RULE_VIOLATION", "This action is not allowed in the current state.", \
        logging.WARNING


class Unauthorized(AppError):
    status, code, public, log_level = 401, "UNAUTHENTICATED", "Please sign in again.", logging.WARNING


class Forbidden(AppError):
    status, code, public, log_level = 403, "FORBIDDEN", "You do not have permission for this action.", logging.WARNING


class DependencyUnavailable(AppError):
    status, code, public = 503, "DEPENDENCY_UNAVAILABLE", "A required service is temporarily unavailable. Please retry."


class DependencyTimeout(AppError):
    status, code, public = 504, "DEPENDENCY_TIMEOUT", "The operation timed out. Please retry."


class ConfigError(AppError):
    """Missing / invalid configuration (batch jobs exit with EXIT_CONFIG)."""
    code, public = "CONFIG_ERROR", "The service is not configured correctly."


class TrainingError(BusinessRuleViolation):
    code, public = "TRAINING_FAILED", "The model could not be trained with these settings."


class ModelNotReady(Conflict):
    code, public = "MODEL_NOT_READY", "No trained model is available yet."


# ------------------------------------------------------------------ response body
def _clip(text: Any) -> str:
    text = scrub(str(text))
    return text if len(text) <= MAX_MESSAGE else text[:MAX_MESSAGE - 1] + "…"


def error_body(code: str, message: str, status: int, fields: Optional[list[dict]] = None,
               context: Optional[dict] = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message, "status": status}
    if fields:
        error["fields"] = fields
    if context:
        error["context"] = context
    return {"detail": message, "error": error}


def generic_message() -> str:
    rid = current_context().get("request_id")
    return f"{GENERIC_MESSAGE} Reference: {rid}" if rid else GENERIC_MESSAGE


def _safe_context(detail: Any) -> Optional[dict]:
    if not isinstance(detail, dict):
        return None
    ctx = {k: detail[k] for k in CONTEXT_KEYS if isinstance(detail.get(k), (int, str)) and detail.get(k) != ""}
    return ctx or None


def _exc_info(exc: Optional[BaseException]):
    return (type(exc), exc, exc.__traceback__) if exc is not None else None


def _json(body: dict, status: int, headers: Optional[dict] = None):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=body, headers=headers)


def _request_fields(request) -> dict:
    return {"method": request.method, "path": request.url.path}


# ------------------------------------------------------------------ handlers
async def _app_error(request, exc: AppError):
    status = exc.status
    if status >= 500:
        cause = exc.__cause__ or exc.__context__
        log.error(exc.log_message or f"{exc.code} {request.method} {request.url.path}",
                  exc_info=_exc_info(cause or exc),
                  extra={"event": "error.server", "error_code": exc.code, "status_code": status,
                         "error": type(cause).__name__ if cause else type(exc).__name__, **_request_fields(request)})
        message = exc.public if exc.public != GENERIC_MESSAGE else generic_message()
    else:
        log.log(exc.log_level, exc.log_message or exc.public,
                extra={"event": "error.client", "error_code": exc.code, "status_code": status, **_request_fields(request)})
        message = exc.public
    body = error_body(exc.code, message, status, exc.fields, exc.context)
    if exc.context:  # older pages read detail.message / detail.run_id
        body["detail"] = {"message": message, **exc.context}
    return _json(body, status)


async def _http_error(request, exc):
    """HTTPException raised by routers, auth and the framework (404 / 405). 4xx bodies keep their `detail` (pages still
    read it); a 5xx never repeats its detail - the wrapped exception is logged with its stack trace instead."""
    status = exc.status_code
    code, default = STATUS_DEFAULTS.get(status, ("INTERNAL_ERROR" if status >= 500 else "BAD_REQUEST", GENERIC_MESSAGE))
    headers = getattr(exc, "headers", None)
    detail = exc.detail
    context = _safe_context(detail)
    if status >= 500:
        cause = exc.__cause__ or exc.__context__
        log.error(f"{code} {request.method} {request.url.path}", exc_info=_exc_info(cause),
                  extra={"event": "error.server", "error_code": code, "status_code": status,
                         "error": type(cause).__name__ if cause else None, **_request_fields(request)})
        message = generic_message() if status == 500 else default
        body = error_body(code, message, status, context=context)
        if context:  # older pages read detail.message / detail.run_id
            body["detail"] = {"message": message, **context}
        return _json(body, status, headers)
    if isinstance(detail, str):
        message = detail
    elif isinstance(detail, dict) and isinstance(detail.get("message"), str):
        message = detail["message"]
    else:
        message = default
    body = error_body(code, _clip(message), status, context=context)
    body["detail"] = detail
    return _json(body, status, headers)


def _field_name(loc: tuple) -> str:
    parts = [str(p) for p in loc]
    if parts and parts[0] in ("body", "query", "path", "header", "cookie") and len(parts) > 1:
        parts = parts[1:]
    return ".".join(parts)


async def _validation_error(request, exc):
    """422 with the field locations and messages only - Pydantic's `input` / `ctx` (the submitted values, passwords
    included) are dropped."""
    errors, fields = [], []
    for e in exc.errors():
        loc = tuple(e.get("loc") or ())
        msg = _clip(e.get("msg") or "Invalid value")
        errors.append({"type": e.get("type"), "loc": list(loc), "msg": msg})
        fields.append({"field": _field_name(loc), "message": msg})
    shown = "; ".join(f"{f['field']}: {f['message']}" if f["field"] else f["message"] for f in fields[:3])
    more = f" (+{len(fields) - 3} more)" if len(fields) > 3 else ""
    message = f"Some fields are invalid - {shown}{more}" if shown else "Some fields are invalid."
    log.warning("request validation failed", extra={"event": "error.validation", "error_code": "VALIDATION_FAILED",
                                                    "fields": [f["field"] for f in fields], **_request_fields(request)})
    body = error_body("VALIDATION_FAILED", message, 422, fields=fields)
    body["detail"] = errors  # same list shape as before, minus the echoed input
    return _json(body, 422)


async def _integrity_error(request, exc):
    from bess_common.errors_db import integrity_to_error
    err, constraint = integrity_to_error(exc)
    log.warning("integrity violation", extra={"event": "error.integrity", "error_code": err.code,
                                              "constraint": constraint, **_request_fields(request)})
    return _json(error_body(err.code, err.public, err.status, err.fields), err.status)


async def _data_error(request, exc):
    from bess_common.errors_db import db_summary
    log.warning("data error", extra={"event": "error.data", "error_code": "DATA_INVALID", "error": db_summary(exc),
                                     **_request_fields(request)})
    message = "A value is out of range or in the wrong format."
    return _json(error_body("DATA_INVALID", message, 422), 422)


async def _db_unavailable(request, exc):
    code, message = "DATABASE_UNAVAILABLE", "The database is temporarily unavailable. Please retry."
    log.error("database unavailable", exc_info=_exc_info(exc),
              extra={"event": "error.server", "error_code": code, "status_code": 503, "error": type(exc).__name__,
                     **_request_fields(request)})
    return _json(error_body(code, message, 503), 503)


async def _timeout(request, exc):
    code, message = STATUS_DEFAULTS[504]
    log.error("operation timed out", exc_info=_exc_info(exc),
              extra={"event": "error.server", "error_code": code, "status_code": 504, "error": type(exc).__name__,
                     **_request_fields(request)})
    return _json(error_body(code, message, 504), 504)


def install_exception_handlers(app) -> None:
    """Register the handlers on a FastAPI app. Unknown exceptions are left to RequestContextMiddleware (generic 500)."""
    from fastapi.exceptions import RequestValidationError
    from sqlalchemy import exc as sa_exc
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(sa_exc.IntegrityError, _integrity_error)
    app.add_exception_handler(sa_exc.DataError, _data_error)
    app.add_exception_handler(sa_exc.OperationalError, _db_unavailable)
    app.add_exception_handler(sa_exc.DisconnectionError, _db_unavailable)
    app.add_exception_handler(TimeoutError, _timeout)
    try:
        import psycopg2
        app.add_exception_handler(psycopg2.IntegrityError, _integrity_error)
        app.add_exception_handler(psycopg2.DataError, _data_error)
        app.add_exception_handler(psycopg2.OperationalError, _db_unavailable)
    except ImportError:
        pass
    try:
        import httpx
        app.add_exception_handler(httpx.TimeoutException, _timeout)
        app.add_exception_handler(httpx.ConnectError, _dependency_unavailable)
    except ImportError:
        pass


async def _dependency_unavailable(request, exc):
    err = DependencyUnavailable()
    log.error("dependency unavailable", exc_info=_exc_info(exc),
              extra={"event": "error.server", "error_code": err.code, "status_code": 503, "error": type(exc).__name__,
                     **_request_fields(request)})
    return _json(error_body(err.code, err.public, 503), 503)



# ------------------------------------------------------------------ runs and batch jobs
@contextmanager
def run_guard(fail: Optional[Callable[[str], Any]] = None, context: Optional[dict] = None,
              user_errors: tuple[type[BaseException], ...] = ()):
    """Wrap a training / scoring / KPI run. On failure `fail(public_text)` records the run (e.g. registry.fail_run) and
    the error is re-raised as an AppError carrying `context` (run_id ...):
      AppError            its public message is recorded; re-raised with the context added
      HTTPException 4xx   its detail is recorded; re-raised unchanged
      user_errors         exception types whose text is meant for the user (recorded and shown, scrubbed)
      anything else       "Unexpected error (ref <request id>)" is recorded; InternalError (generic 500) is raised with
                          the original chained, so the handler logs its stack trace"""
    try:
        yield
    except AppError as exc:
        exc.context = {**(context or {}), **(exc.context or {})} or None
        _record_failure(fail, exc.public if exc.status < 500 else _unexpected_text())
        raise
    except Exception as exc:
        if _is_client_http_error(exc):
            detail = getattr(exc, "detail", None)
            _record_failure(fail, _clip(detail) if isinstance(detail, str) else "Rejected")
            raise
        if user_errors and isinstance(exc, user_errors):
            public = _clip(exc) or BusinessRuleViolation.public
            _record_failure(fail, public)
            raise BusinessRuleViolation(public, context=context) from exc
        _record_failure(fail, _unexpected_text())
        raise InternalError(context=context, log_message=f"run failed: {type(exc).__name__}") from exc


def _is_client_http_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and hasattr(exc, "detail")


def run_failure_text(exc: BaseException) -> str:
    """What a run table's error_message may show: an AppError's public text, else "Unexpected error (ref <id>)"
    (the exception itself goes to the log)."""
    if isinstance(exc, AppError) and exc.status < 500:
        return exc.public
    return _unexpected_text()


def _unexpected_text() -> str:
    rid = current_context().get("request_id")
    return f"Unexpected error (ref {rid})" if rid else "Unexpected error"


def _record_failure(fail: Optional[Callable[[str], Any]], text: str) -> None:
    if fail is None:
        return
    try:
        fail(text)
    except Exception:  # noqa: BLE001 - recording the failure must not hide the original error
        log.exception("could not record the failed run", extra={"event": "error.record_failure"})


def run_main(job: str, fn: Callable[..., Any], *args, **kwargs) -> int:
    """Batch entry point: sys.exit(run_main("static_data_load", main)). fn may return an exit code (int) or anything
    else (EXIT_OK). AppError -> EXIT_FAILED (ConfigError -> EXIT_CONFIG); any other exception -> EXIT_UNEXPECTED;
    every failure is logged with its stack trace under the job's run id."""
    rid = current_context().get("request_id")
    with request_context(rid or f"{job}-{uuid.uuid4().hex[:12]}", job=job):
        try:
            result = fn(*args, **kwargs)
            return result if isinstance(result, int) and not isinstance(result, bool) else EXIT_OK
        except KeyboardInterrupt:
            log.warning(f"{job} interrupted", extra={"event": "batch.interrupted", "job": job})
            return 130
        except ConfigError as exc:
            log.error(f"{job} configuration error: {exc.public}", exc_info=True,
                      extra={"event": "batch.failed", "job": job, "error_code": exc.code})
            return EXIT_CONFIG
        except AppError as exc:
            log.error(f"{job} failed: {exc.public}", exc_info=True,
                      extra={"event": "batch.failed", "job": job, "error_code": exc.code})
            return EXIT_FAILED
        except Exception as exc:  # noqa: BLE001 - the batch entry point is the last line of defence
            log.exception(f"{job} failed unexpectedly", extra={"event": "batch.failed", "job": job,
                                                               "error_code": "INTERNAL_ERROR",
                                                               "error": type(exc).__name__})
            return EXIT_UNEXPECTED


def batch_error_code(status: str, code: Optional[str] = None) -> Optional[str]:
    """battery_raw.batchlog.error_code of a run: None on SUCCESS, else the cause the loader recorded (e.g.
    API_UNAVAILABLE, SNAPSHOT_INVALID) or LOAD_PARTIAL / LOAD_FAILED."""
    if status == "SUCCESS":
        return None
    return code or ("LOAD_PARTIAL" if status == "PARTIAL" else "LOAD_FAILED")


# ------------------------------------------------------------------ API docs
def app_env() -> str:
    return (setting("APP_ENV", "dev") or "dev").strip().lower()


def api_docs_kwargs() -> dict:
    """FastAPI(...) keyword arguments: no Swagger UI / ReDoc / OpenAPI schema in production."""
    if app_env() in ("prod", "production"):
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}
