"""Bulk load of day-ahead market prices (BESS_Arbitrage_DataPack/dam_price.csv / .xlsx) into battery_master.dam_price.

Columns: node_code (or node; optional when one node is chosen for the whole file), delivery_start (or ts / timestamp),
price_mwh (or price) - required; block_minutes (default 60), cleared_mw - optional. Header case and surrounding spaces
are ignored; unknown columns are reported and skipped.

Row validation: a known price node, a parseable delivery start aligned to its block (an hourly block starts on the
hour), block_minutes in 5 / 15 / 30 / 60, price within -1000..20000 USD/MWh, cleared volume >= 0, and no duplicate
(node, delivery_start) in the file (the last one wins). Existing (node, delivery_start) prices are updated, new ones
inserted. Timestamps without a zone are plant / market time (Asia/Kolkata), no UTC conversion.
"""
from datetime import datetime
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from bess_common.errors import AppError, FileFormatError
from app.models.dam_price import DamPrice, PriceNode
from app.schemas.dam_price import BulkDamPriceRowError, DamPriceCreate
from app.services.demand_telemetry_import import _read_csv, _read_xlsx, _ts

MAX_ROWS = 300_000
NODE_HEADERS = ("node_code", "node", "price_node")
TS_HEADERS = ("delivery_start", "ts", "timestamp", "time")
PRICE_HEADERS = ("price_mwh", "price", "price_usd_mwh")
OPTIONAL = ("block_minutes", "cleared_mw")


class DamPriceImportError(FileFormatError):
    """File-level problems: bad format, missing columns, unknown node, empty file."""


def _num(value, field: str) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        raise ValueError(f"{field}: '{value}' is not a number")


def _pick(idx: dict, names: tuple) -> Optional[str]:
    return next((h for h in names if h in idx), None)


def parse_dam_price_file(db: Session, filename: str, content: bytes, node_id: Optional[int] = None):
    """Returns (valid rows as dicts, row errors, total data rows, unknown columns, node codes used)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise DamPriceImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except DamPriceImportError:
        raise
    except AppError as exc:  # a reader's own file-level error
        raise DamPriceImportError(exc.public, log_message=exc.log_message) from exc
    except Exception as exc:  # noqa: BLE001 - any other parser failure means an unreadable file
        raise DamPriceImportError("The file could not be read. Please upload a valid .csv or .xlsx file.",
                                      log_message=f"upload not readable: {type(exc).__name__}: {exc}") from exc
    if len(raw_rows) > MAX_ROWS:
        raise DamPriceImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    node_h, ts_h, price_h = _pick(idx, NODE_HEADERS), _pick(idx, TS_HEADERS), _pick(idx, PRICE_HEADERS)
    missing = [label for label, h in (("delivery_start", ts_h), ("price_mwh", price_h)) if h is None]
    if node_h is None and node_id is None:
        missing.insert(0, "node_code (or choose a node for the whole file)")
    if missing:
        raise DamPriceImportError(f"Missing required column(s): {', '.join(missing)}")
    present = [f for f in OPTIONAL if f in idx]
    known = {node_h, ts_h, price_h, *present} - {None}
    ignored = [h for h, n in zip(headers, norm) if n and n not in known]

    codes = {n.node_code: n.node_id for n in db.query(PriceNode.node_code, PriceNode.node_id)}
    by_id = {v: k for k, v in codes.items()}
    if node_id is not None and node_id not in by_id:
        raise DamPriceImportError(f"Price node {node_id} does not exist")

    valid: dict[tuple, dict] = {}
    errors: list[BulkDamPriceRowError] = []
    for i, raw in enumerate(raw_rows):
        row_no = i + 2
        cell = lambda j: raw[j] if j < len(raw) else None  # noqa: E731
        problems: list[str] = []

        nid = node_id
        if node_h is not None:
            code = str(cell(idx[node_h]) or "").strip()
            if code:
                if code in codes:
                    nid = codes[code]
                else:
                    problems.append(f"node_code: '{code}' is not a known price node")
                    nid = None
            elif node_id is None:
                problems.append("node_code: missing")
        try:
            start = _ts(cell(idx[ts_h]))
        except (ValueError, OverflowError) as exc:
            problems.append(f"delivery_start: {exc}")
            start = None
        values = {}
        try:
            values["price_mwh"] = _num(cell(idx[price_h]), "price_mwh")
            if values["price_mwh"] is None:
                problems.append("price_mwh: missing")
            if "cleared_mw" in present:
                values["cleared_mw"] = _num(cell(idx["cleared_mw"]), "cleared_mw")
            if "block_minutes" in present:
                bm = _num(cell(idx["block_minutes"]), "block_minutes")
                if bm is not None:
                    if bm != int(bm):
                        raise ValueError(f"block_minutes: '{bm}' is not a whole number")
                    values["block_minutes"] = int(bm)
        except ValueError as exc:
            problems.append(str(exc))
        if problems:
            errors.append(BulkDamPriceRowError(row=row_no, errors=problems))
            continue
        try:
            rec = DamPriceCreate(node_id=nid, delivery_start=start, **{k: v for k, v in values.items() if v is not None})
        except ValidationError as exc:
            errors.append(BulkDamPriceRowError(row=row_no, errors=[
                ".".join(str(p) for p in e["loc"]) + ": " + e["msg"].replace("Value error, ", "") for e in exc.errors()]))
            continue
        if (start.minute * 60 + start.second) % (rec.block_minutes * 60) or start.microsecond:
            errors.append(BulkDamPriceRowError(row=row_no, errors=[
                f"delivery_start: {start:%H:%M:%S} is not on a {rec.block_minutes}-minute block boundary"]))
            continue
        valid[(nid, start)] = rec.model_dump()
    rows = [valid[k] for k in sorted(valid, key=lambda k: (k[0], k[1]))]
    return rows, errors, len(raw_rows), ignored, sorted({by_id[r["node_id"]] for r in rows})


def upsert_dam_prices(db: Session, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    table = DamPrice.__table__
    inserted = updated = 0
    for start in range(0, len(rows), 2000):
        stmt = pg_insert(table).values(rows[start:start + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["node_id", "delivery_start"],
            set_={c: getattr(stmt.excluded, c) for c in ("block_minutes", "price_mwh", "cleared_mw")},
        ).returning(literal_column("(xmax = 0)").label("was_insert"))
        for r in db.execute(stmt):
            if r.was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated


def first_last(rows: list[dict]) -> tuple[Optional[datetime], Optional[datetime]]:
    if not rows:
        return None, None
    starts = [r["delivery_start"] for r in rows]
    return min(starts), max(starts)
