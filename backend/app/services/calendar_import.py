"""Bulk load of the reference calendar (calendar_data.csv / .xlsx) into battery_master.calendar_day.

Columns: calendar_date (or date) - required; is_holiday, holiday_name, day_of_week, is_weekend, day_type - optional.
Header case and spaces are ignored; unknown columns are reported and skipped.

Day of week, weekend (Saturday / Sunday) and day type (Holiday > Weekend > Weekday) follow from the date and the
holiday flag: they are filled in when a column is missing or empty, and a row is refused when the file contradicts
them. A holiday_name without is_holiday marks the day a holiday. Duplicate dates in the file: the last one wins.
Existing dates are updated, new ones inserted.
"""
from datetime import date, datetime

from pydantic import ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import models, schemas
from app.services.demand_telemetry_import import _read_csv, _read_xlsx

MAX_ROWS = 50_000
DATE_HEADERS = ("calendar_date", "date", "day")
OPTIONAL = ("is_holiday", "holiday_name", "day_of_week", "is_weekend", "day_type")
TRUE = {"true", "t", "yes", "y", "1"}
FALSE = {"false", "f", "no", "n", "0"}


class CalendarImportError(Exception):
    """File-level problems: bad format, missing columns, empty file."""


def _date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"'{text}' is not a date (use YYYY-MM-DD)")


def _bool(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE:
        return True
    if text in FALSE:
        return False
    raise ValueError(f"'{value}' is not true / false")


def parse_calendar_file(filename: str, content: bytes):
    """Returns (valid rows as dicts, row errors, total data rows, unknown columns)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise CalendarImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except CalendarImportError:
        raise
    except Exception as exc:  # the shared readers raise their own error type
        raise CalendarImportError(str(exc)) from exc
    if len(raw_rows) > MAX_ROWS:
        raise CalendarImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    date_h = next((h for h in DATE_HEADERS if h in idx), None)
    if date_h is None:
        raise CalendarImportError("Missing required column: calendar_date")
    present = [f for f in OPTIONAL if f in idx]
    ignored = [h for h, n in zip(headers, norm) if n and n not in {date_h, *present}]

    valid, errors = {}, []
    for i, raw in enumerate(raw_rows):
        row_no = i + 2
        cell = lambda j: raw[j] if j < len(raw) else None  # noqa: E731
        problems: list[str] = []
        try:
            d = _date(cell(idx[date_h]))
        except ValueError as exc:
            problems.append(f"calendar_date: {exc}")
            d = None
        fields = {}
        for f in present:
            v = cell(idx[f])
            if f in ("is_holiday", "is_weekend"):
                try:
                    fields[f] = _bool(v)
                except ValueError as exc:
                    problems.append(f"{f}: {exc}")
            else:
                s = str(v).strip() if v is not None else ""
                fields[f] = s or None
        if problems:
            errors.append(schemas.BulkCalendarRowError(row=row_no, errors=problems))
            continue
        try:
            rec = schemas.CalendarDayCreate(calendar_date=d, **fields)
            valid[d] = rec.complete(d)
        except (ValidationError, ValueError) as exc:
            msgs = ([(".".join(str(p) for p in e["loc"]) + ": " if e["loc"] else "") + e["msg"].replace("Value error, ", "")
                     for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)])
            errors.append(schemas.BulkCalendarRowError(row=row_no, errors=msgs))
    return [valid[k] for k in sorted(valid)], errors, len(raw_rows), ignored


def upsert_calendar_rows(db: Session, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    table = models.CalendarDay.__table__
    inserted = updated = 0
    for start in range(0, len(rows), 1000):
        stmt = pg_insert(table).values(rows[start:start + 1000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["calendar_date"],
            set_={c: getattr(stmt.excluded, c) for c in ("day_of_week", "is_weekend", "is_holiday", "holiday_name", "day_type")},
        ).returning(literal_column("(xmax = 0)").label("was_insert"))
        for r in db.execute(stmt):
            if r.was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated
