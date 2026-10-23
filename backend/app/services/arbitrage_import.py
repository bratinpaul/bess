"""Shared bulk-load plumbing for the arbitrage decision tables (BESS_Arbitrage_DataPack: optimization_run,
decision_state, dispatch_schedule, dispatch_outcome, as_award, price_scenario).

A loader declares its columns (output field, accepted header names, kind, required, code lookup); parse_upload reads
the .csv / .xlsx, converts every cell, resolves business codes (system_code -> system_id, node_code -> node_id,
product_code -> product_id) and reports per-row problems. validate_rows then runs the table's pydantic schema plus
any cross-row check, and upsert writes the survivors with ON CONFLICT ... DO UPDATE on the table's key.
Timestamps without a zone are plant / market time (Asia/Kolkata), no UTC conversion. Header case and surrounding
spaces are ignored; unknown columns are reported and skipped.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional

from pydantic import BaseModel, ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from bess_common.errors import AppError, FileFormatError
from app.schemas.arbitrage import RowError
from app.services.demand_telemetry_import import _read_csv, _read_xlsx, _ts

MAX_ROWS = 300_000


class ArbitrageImportError(FileFormatError):
    """File-level problems: bad format, missing columns, empty file."""


@dataclass(frozen=True)
class Col:
    field: str                       # output key (model attribute)
    headers: tuple[str, ...]         # accepted header names, first is the canonical one
    kind: str = "num"                # ts | num | int | text | code
    required: bool = False
    lookup: Optional[str] = None     # for kind "code": key into the resolvers mapping


def _cell_value(col: Col, value, resolvers: dict[str, dict[str, int]]):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if col.kind == "ts":
        return _ts(value)
    if col.kind == "text":
        return str(value).strip()
    if col.kind == "code":
        code = str(value).strip()
        found = resolvers[col.lookup].get(code)
        if found is None:
            raise ValueError(f"'{code}' is not a known {col.lookup}")
        return found
    text = str(value).strip()
    try:
        num = float(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a number")
    if col.kind == "int":
        if num != int(num):
            raise ValueError(f"'{text}' is not a whole number")
        return int(num)
    return num


def parse_upload(filename: str, content: bytes, cols: list[Col], resolvers: dict[str, dict[str, int]]):
    """Returns ([(row_no, {field: value})], row errors, total data rows, unknown columns)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise ArbitrageImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except ArbitrageImportError:
        raise
    except AppError as exc:  # a reader's own file-level error
        raise ArbitrageImportError(exc.public, log_message=exc.log_message) from exc
    except Exception as exc:  # noqa: BLE001 - any other parser failure means an unreadable file
        raise ArbitrageImportError("The file could not be read. Please upload a valid .csv or .xlsx file.",
                                       log_message=f"upload not readable: {type(exc).__name__}: {exc}") from exc
    if len(raw_rows) > MAX_ROWS:
        raise ArbitrageImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    where = {c.field: next((idx[h] for h in c.headers if h in idx), None) for c in cols}
    missing = [c.headers[0] for c in cols if c.required and where[c.field] is None]
    if missing:
        raise ArbitrageImportError(f"Missing required column(s): {', '.join(missing)}")
    used = {norm[i] for i in where.values() if i is not None}
    ignored = [h for h, n in zip(headers, norm) if n and n not in used]

    records, errors = [], []
    for i, raw in enumerate(raw_rows):
        row_no = i + 2
        rec, problems = {}, []
        for c in cols:
            j = where[c.field]
            if j is None:
                continue
            try:
                rec[c.field] = _cell_value(c, raw[j] if j < len(raw) else None, resolvers)
            except (ValueError, OverflowError) as exc:
                problems.append(f"{c.headers[0]}: {exc}")
                continue
            if c.required and rec[c.field] is None:
                problems.append(f"{c.headers[0]}: missing")
        if problems:
            errors.append(RowError(row=row_no, errors=problems))
        else:
            records.append((row_no, rec))
    return records, errors, len(raw_rows), ignored


def pydantic_messages(exc: ValidationError) -> list[str]:
    return [(".".join(str(p) for p in e["loc"]) + ": " if e["loc"] else "") + e["msg"].replace("Value error, ", "")
            for e in exc.errors()]


def validate_rows(records, schema: type[BaseModel], errors: list[RowError],
                  check: Optional[Callable[[BaseModel], Optional[str]]] = None,
                  key: Optional[Callable[[BaseModel], tuple]] = None) -> list[dict]:
    """Schema-validate each record, run the optional cross-row check (returns a message when the row is wrong) and
    keep the last row per key (duplicates in a file: the last one wins)."""
    valid: dict = {}
    for row_no, rec in records:
        try:
            model = schema(**{k: v for k, v in rec.items() if v is not None})
        except ValidationError as exc:
            errors.append(RowError(row=row_no, errors=pydantic_messages(exc)))
            continue
        problem = check(model) if check else None
        if problem:
            errors.append(RowError(row=row_no, errors=[problem]))
            continue
        valid[key(model) if key else row_no] = model.model_dump()
    return list(valid.values())


def upsert(db: Session, table, rows: list[dict], conflict: list[str], update: list[str]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    inserted = updated = 0
    for start in range(0, len(rows), 2000):
        stmt = pg_insert(table).values(rows[start:start + 2000])
        stmt = stmt.on_conflict_do_update(index_elements=conflict,
                                          set_={c: getattr(stmt.excluded, c) for c in update}) \
            .returning(literal_column("(xmax = 0)").label("was_insert"))
        for r in db.execute(stmt):
            if r.was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated


def ts_span(rows: list[dict], field: str) -> tuple[Optional[datetime], Optional[datetime]]:
    values = [r[field] for r in rows if r.get(field) is not None]
    return (min(values), max(values)) if values else (None, None)


def num(v, nd: Optional[int] = None) -> Optional[float]:
    """Numeric / Decimal -> float (rounded when nd is given); None stays None."""
    if v is None:
        return None
    f = float(v) if isinstance(v, (Decimal, int, float)) else float(str(v))
    return round(f, nd) if nd is not None else f
