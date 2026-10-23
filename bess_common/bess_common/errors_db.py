"""Database errors -> safe AppErrors. The constraint name, table and key values stay in the log, never in a response.

    CONSTRAINTS             "schema.constraint" -> entry: the generated catalog (constraint_catalog.py, written by
                            db_docs/gen_constraint_catalog.py) with OVERRIDES merged over it. Entry keys: kind
                            (unique | fk | check), code, status, message, field; fk entries also in_use_code /
                            in_use_status / in_use_message (a parent that is still referenced can't be deleted)
    OVERRIDES               hand-written wording for rules the generator can't phrase (merged key by key)
    lookup(schema, name)    the entry for a violated constraint; TimescaleDB chunk copies ("58_130_alarm_event_pkey"
                            on _timescaledb_internal._hyper_58_130_chunk) resolve to the hypertable's constraint
    integrity_to_error(exc) -> (AppError, constraint name or None); constraints missing from the catalog are answered by
                            their SQLSTATE class (unique 409, FK 422 / 409, not-null / check 422)
    db_summary(exc)         short, parameter-free description of a DB error for the log

psycopg2 errors carry the details in exc.diag; asyncpg errors (the auth engine) as attributes of the driver exception.
"""
import re
from typing import Any, Optional

from bess_common.constraint_catalog import CATALOG
from bess_common.errors import AppError, BusinessRuleViolation, Conflict

OVERRIDES: dict[str, dict[str, Any]] = {
    "battery_master.alarm_catalog_source_code_key": {
        "code": "ALARM_CODE_DUPLICATE", "field": "alarm_code",
        "message": "An alarm with this source and code already exists."},
    "battery_master.pcs_system_id_pcs_code_key": {
        "field": "pcs_code", "message": "A PCS with this code already exists for this battery system."},
    "battery_master.ems_tariff_hours": {
        "message": "Start hour must be 0-23, end hour 1-24, and the end must be after the start."},
    "battery_ml.model_run_scope_system": {
        "message": "A base model must not name a battery system; a system model must name one."},
    "battery_ml.model_run_finetune_parent": {
        "message": "Fine-tuning is only possible for a battery-system model."},
    "battery_raw.batchlog_rows": {
        "message": "Inserted, updated and skipped rows can't add up to more than the total rows."},
    "battery_telemetry.dispatch_event_active_open": {
        "message": "An active dispatch event must not have an end time, and a finished one must have one."},
}

CONSTRAINTS: dict[str, dict[str, Any]] = {k: {**v, **OVERRIDES.get(k, {})} for k, v in CATALOG.items()}
_BY_NAME: dict[str, Optional[str]] = {}
for _key in CONSTRAINTS:
    _name = _key.split(".", 1)[1]
    _BY_NAME[_name] = None if _name in _BY_NAME else _key  # None: the name exists in more than one schema

CHUNK_PREFIX = re.compile(r"^(?:\d+_\d+_|_hyper_\d+_\d+_chunk_)")


def lookup(schema: Optional[str], name: Optional[str]) -> Optional[dict]:
    if not name:
        return None
    if schema and f"{schema}.{name}" in CONSTRAINTS:
        return CONSTRAINTS[f"{schema}.{name}"]
    for candidate in (name, CHUNK_PREFIX.sub("", name)):
        key = _BY_NAME.get(candidate)
        if key:
            return CONSTRAINTS[key]
    return None


def _orig(exc: BaseException):
    return getattr(exc, "orig", None) or exc


def _info(exc: BaseException) -> dict:
    """SQLSTATE, constraint, schema, table, column and primary message of a psycopg2 / asyncpg error."""
    orig = _orig(exc)
    diag = getattr(orig, "diag", None)
    if diag is not None:  # psycopg2
        return {"pgcode": getattr(orig, "pgcode", None), "constraint": diag.constraint_name, "schema": diag.schema_name,
                "table": diag.table_name, "column": diag.column_name, "primary": diag.message_primary or ""}
    driver = getattr(orig, "__cause__", None) or orig  # SQLAlchemy's asyncpg adapter wraps the asyncpg exception
    return {"pgcode": getattr(driver, "sqlstate", None) or getattr(orig, "pgcode", None),
            "constraint": getattr(driver, "constraint_name", None), "schema": getattr(driver, "schema_name", None),
            "table": getattr(driver, "table_name", None), "column": getattr(driver, "column_name", None),
            "primary": str(getattr(driver, "message", "") or "")}


def db_summary(exc: BaseException) -> str:
    info = _info(exc)
    code = info["pgcode"]
    return f"{type(_orig(exc)).__name__}{f' [{code}]' if code else ''}: {info['primary'].strip()[:200]}"


def _is_parent_delete(info: dict) -> bool:
    return info["primary"].startswith("update or delete")


def _error(entry: dict, info: dict) -> AppError:
    if entry["kind"] == "fk" and _is_parent_delete(info):
        return Conflict(entry["in_use_message"], code=entry["in_use_code"], status=entry["in_use_status"])
    fields = [{"field": entry["field"], "message": entry["message"]}] if entry.get("field") else None
    cls = Conflict if entry["status"] == 409 else BusinessRuleViolation
    return cls(entry["message"], code=entry["code"], status=entry["status"], fields=fields)


def _column_label(column: str) -> str:
    return column.removesuffix("_id").replace("_", " ")


def integrity_to_error(exc: BaseException) -> tuple[AppError, Optional[str]]:
    info = _info(exc)
    constraint, pgcode = info["constraint"], info["pgcode"]
    entry = lookup(info["schema"], constraint)
    if entry is not None and pgcode != "23502":
        return _error(entry, info), constraint
    if pgcode == "23505":
        err: AppError = Conflict("A record with these values already exists.", code="DUPLICATE")
    elif pgcode == "23503" and _is_parent_delete(info):
        err = Conflict("This record is still used by other records and can't be changed or deleted.", code="IN_USE")
    elif pgcode == "23503":
        err = BusinessRuleViolation("A referenced record does not exist.", code="REFERENCE_NOT_FOUND")
    elif pgcode == "23502":
        column = info["column"]
        message = f"{_column_label(column).capitalize()} is required." if column else "A required value is missing."
        fields = [{"field": column, "message": "Required"}] if column else None
        err = BusinessRuleViolation(message, code="REQUIRED_VALUE_MISSING", fields=fields)
    elif pgcode == "23514":
        err = BusinessRuleViolation("A value is outside the allowed range.", code="VALUE_NOT_ALLOWED")
    elif pgcode == "23P01":
        err = Conflict("This overlaps an existing record.", code="OVERLAP")
    else:
        err = Conflict()
    return err, constraint


def integrity_message(exc: BaseException) -> str:
    """The public message for a constraint violation - for row-level errors of bulk loads."""
    return integrity_to_error(exc)[0].public
