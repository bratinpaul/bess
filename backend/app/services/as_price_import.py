"""Bulk load of ancillary-service prices (BESS_Arbitrage_DataPack/as_price.csv / .xlsx) into battery_master.as_price.

Columns: product_code (or product; optional when one product is chosen for the whole file), delivery_start (or ts /
timestamp) - required; capacity_price_mw (or capacity_price), performance_price - at least one per row; block_minutes
(default 60) - optional. Header case and surrounding spaces are ignored; unknown columns are reported and skipped.

Row validation: a known AS product, a parseable delivery start aligned to its block (an hourly block starts on the
hour), block_minutes in 5 / 15 / 30 / 60, prices within 0..100000 USD/MW, and no duplicate (product, delivery_start)
in the file (the last one wins). Existing (product, delivery_start) prices are updated, new ones inserted.
Timestamps without a zone are plant / market time (Asia/Kolkata), no UTC conversion.
"""
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.as_price import AsPrice, AsProduct
from app.schemas.as_price import AsPriceCreate, BulkAsPriceRowError
from app.services.dam_price_import import _num, _pick, first_last  # noqa: F401 - first_last re-exported
from app.services.demand_telemetry_import import _read_csv, _read_xlsx, _ts

MAX_ROWS = 300_000
PRODUCT_HEADERS = ("product_code", "product", "as_product")
TS_HEADERS = ("delivery_start", "ts", "timestamp", "time")
CAPACITY_HEADERS = ("capacity_price_mw", "capacity_price", "cap")
PERFORMANCE_HEADERS = ("performance_price", "performance_price_mw", "perf")


class AsPriceImportError(Exception):
    """File-level problems: bad format, missing columns, unknown product, empty file."""


def parse_as_price_file(db: Session, filename: str, content: bytes, product_id: Optional[int] = None):
    """Returns (valid rows as dicts, row errors, total data rows, unknown columns, product codes used)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise AsPriceImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except AsPriceImportError:
        raise
    except Exception as exc:  # the shared readers raise their own error type
        raise AsPriceImportError(str(exc)) from exc
    if len(raw_rows) > MAX_ROWS:
        raise AsPriceImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    prod_h, ts_h = _pick(idx, PRODUCT_HEADERS), _pick(idx, TS_HEADERS)
    cap_h, perf_h = _pick(idx, CAPACITY_HEADERS), _pick(idx, PERFORMANCE_HEADERS)
    missing = []
    if prod_h is None and product_id is None:
        missing.append("product_code (or choose a product for the whole file)")
    if ts_h is None:
        missing.append("delivery_start")
    if cap_h is None and perf_h is None:
        missing.append("capacity_price_mw or performance_price")
    if missing:
        raise AsPriceImportError(f"Missing required column(s): {', '.join(missing)}")
    block_h = "block_minutes" if "block_minutes" in idx else None
    known = {prod_h, ts_h, cap_h, perf_h, block_h} - {None}
    ignored = [h for h, n in zip(headers, norm) if n and n not in known]

    codes = {p.product_code: p.product_id for p in db.query(AsProduct.product_code, AsProduct.product_id)}
    by_id = {v: k for k, v in codes.items()}
    if product_id is not None and product_id not in by_id:
        raise AsPriceImportError(f"AS product {product_id} does not exist")

    valid: dict[tuple, dict] = {}
    errors: list[BulkAsPriceRowError] = []
    for i, raw in enumerate(raw_rows):
        row_no = i + 2
        cell = lambda j: raw[j] if j < len(raw) else None  # noqa: E731
        problems: list[str] = []

        pid = product_id
        if prod_h is not None:
            code = str(cell(idx[prod_h]) or "").strip()
            if code:
                if code in codes:
                    pid = codes[code]
                else:
                    problems.append(f"product_code: '{code}' is not a known AS product")
                    pid = None
            elif product_id is None:
                problems.append("product_code: missing")
        try:
            start = _ts(cell(idx[ts_h]))
        except (ValueError, OverflowError) as exc:
            problems.append(f"delivery_start: {exc}")
            start = None
        values = {}
        try:
            if cap_h is not None:
                values["capacity_price_mw"] = _num(cell(idx[cap_h]), "capacity_price_mw")
            if perf_h is not None:
                values["performance_price"] = _num(cell(idx[perf_h]), "performance_price")
            if block_h is not None:
                bm = _num(cell(idx[block_h]), "block_minutes")
                if bm is not None:
                    if bm != int(bm):
                        raise ValueError(f"block_minutes: '{bm}' is not a whole number")
                    values["block_minutes"] = int(bm)
        except ValueError as exc:
            problems.append(str(exc))
        if problems:
            errors.append(BulkAsPriceRowError(row=row_no, errors=problems))
            continue
        try:
            rec = AsPriceCreate(product_id=pid, delivery_start=start, **{k: v for k, v in values.items() if v is not None})
        except ValidationError as exc:
            errors.append(BulkAsPriceRowError(row=row_no, errors=[
                (".".join(str(p) for p in e["loc"]) + ": " if e["loc"] else "") + e["msg"].replace("Value error, ", "")
                for e in exc.errors()]))
            continue
        if (start.minute * 60 + start.second) % (rec.block_minutes * 60) or start.microsecond:
            errors.append(BulkAsPriceRowError(row=row_no, errors=[
                f"delivery_start: {start:%H:%M:%S} is not on a {rec.block_minutes}-minute block boundary"]))
            continue
        valid[(pid, start)] = rec.model_dump()
    rows = [valid[k] for k in sorted(valid, key=lambda k: (k[0], k[1]))]
    return rows, errors, len(raw_rows), ignored, sorted({by_id[r["product_id"]] for r in rows})


def upsert_as_prices(db: Session, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    table = AsPrice.__table__
    inserted = updated = 0
    for start in range(0, len(rows), 2000):
        stmt = pg_insert(table).values(rows[start:start + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["product_id", "delivery_start"],
            set_={c: getattr(stmt.excluded, c) for c in ("block_minutes", "capacity_price_mw", "performance_price")},
        ).returning(literal_column("(xmax = 0)").label("was_insert"))
        for r in db.execute(stmt):
            if r.was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated
