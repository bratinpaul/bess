"""Bulk load of weather forecasts (weather_forecast_data.csv / .xlsx) into battery_telemetry.weather_forecast.

Columns: issued_at (run time), valid_at (the hour the value is for), station_code (optional when one station is chosen
for the whole file), temp_c, ghi_wm2. Header case and spaces are ignored; unknown columns are reported and skipped.

Row validation: parseable issued_at / valid_at with valid_at after issued_at (at most 16 days ahead), a known station,
temperature -60..65 °C, GHI 0..1500 W/m², at least one value, no duplicate (station, issued_at, valid_at) in the file
(the last one wins). Existing (station, issued_at, valid_at) values are updated, new ones inserted.
Timestamps without a zone are plant time (Asia/Kolkata).
"""
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import models, schemas
from app.services.demand_telemetry_import import MAX_ROWS, _dec, _read_csv, _read_xlsx, _ts

ISSUED_HEADERS = ("issued_at", "issue_time", "run_time", "issued")
VALID_HEADERS = ("valid_at", "valid_time", "target_time", "ts")
CODE_HEADERS = ("station_code", "station", "weather_station")
VALUE_FIELDS = ("temp_c", "ghi_wm2")


class WeatherForecastImportError(Exception):
    """File-level problems: bad format, missing columns, empty file."""


def parse_forecast_file(filename: str, content: bytes, db: Session, default_station_id: Optional[int] = None):
    """Returns (valid rows, row errors, total data rows, unknown columns, station codes seen)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise WeatherForecastImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except WeatherForecastImportError:
        raise
    except Exception as exc:  # the shared readers raise their own error type
        raise WeatherForecastImportError(str(exc)) from exc
    if len(raw_rows) > MAX_ROWS:
        raise WeatherForecastImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    issued_h = next((h for h in ISSUED_HEADERS if h in idx), None)
    valid_h = next((h for h in VALID_HEADERS if h in idx), None)
    missing = [n for n, h in (("issued_at", issued_h), ("valid_at", valid_h)) if h is None]
    if missing:
        raise WeatherForecastImportError(f"Missing required column(s): {', '.join(missing)}")
    code_h = next((h for h in CODE_HEADERS if h in idx), None)
    if code_h is None and default_station_id is None:
        raise WeatherForecastImportError("The file has no station_code column: choose the weather station for it")
    present = [f for f in VALUE_FIELDS if f in idx]
    if not present:
        raise WeatherForecastImportError("No forecast columns found (expected temp_c and / or ghi_wm2)")
    known = {issued_h, valid_h, code_h, *present}
    ignored = [h for h, n in zip(headers, norm) if n and n not in known]

    stations = {s.station_code.upper(): s.station_id for s in db.query(models.WeatherStation)}
    valid, errors, seen = {}, [], set()
    for i, raw in enumerate(raw_rows):
        row_no = i + 2
        problems: list[str] = []
        cell = lambda j: raw[j] if j < len(raw) else None  # noqa: E731
        stamps = {}
        for label, h in (("issued_at", issued_h), ("valid_at", valid_h)):
            try:
                stamps[label] = _ts(cell(idx[h]))
            except (ValueError, OverflowError) as exc:
                problems.append(f"Invalid {label}: {exc}")
        sid = default_station_id
        if code_h is not None:
            code = str(cell(idx[code_h]) or "").strip()
            if code:
                sid = stations.get(code.upper())
                seen.add(code)
                if sid is None:
                    problems.append(f"Unknown weather station '{code}'")
            elif default_station_id is None:
                problems.append("Missing station_code")
        values = {}
        for f in present:
            try:
                values[f] = _dec(cell(idx[f]))
            except ValueError as exc:
                problems.append(f"{f}: {exc}")
        if problems:
            errors.append(schemas.BulkWeatherForecastRowError(row=row_no, errors=problems))
            continue
        try:
            rec = schemas.WeatherForecastCreate(station_id=sid, **stamps, **values)
        except ValidationError as exc:
            msgs = [(".".join(str(p) for p in e["loc"]) + ": " if e["loc"] else "") + e["msg"].replace("Value error, ", "")
                    for e in exc.errors()]
            errors.append(schemas.BulkWeatherForecastRowError(row=row_no, errors=msgs))
            continue
        valid[(sid, rec.issued_at, rec.valid_at)] = rec
    return list(valid.values()), errors, len(raw_rows), ignored, sorted(seen)


def upsert_forecast_rows(db: Session, rows: list["schemas.WeatherForecastCreate"]) -> tuple[int, int]:
    """Insert new (station, issued_at, valid_at) values and update existing ones in the columns the rows carry."""
    if not rows:
        return 0, 0
    table = models.WeatherForecast.__table__
    sent = set().union(*(r.model_fields_set for r in rows)) & set(VALUE_FIELDS)
    data = [r.model_dump() for r in rows]
    inserted = updated = 0
    for start in range(0, len(data), 1000):
        stmt = pg_insert(table).values(data[start:start + 1000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["station_id", "issued_at", "valid_at"],
            set_={f: getattr(stmt.excluded, f) for f in (sent or VALUE_FIELDS)},
        ).returning(literal_column("(xmax = 0)").label("was_insert"))
        for r in db.execute(stmt):
            if r.was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated
