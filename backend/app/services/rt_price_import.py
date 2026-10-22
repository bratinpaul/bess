"""Bulk load of real-time / imbalance prices (BESS_Arbitrage_DataPack/rt_price.csv / .xlsx) into battery_master.rt_price.

Columns: node_code (or node; optional when one node is chosen for the whole file), interval_start (or ts / timestamp),
price_mwh (or price) - required; block_minutes (default 15) - optional. Header case and surrounding spaces are ignored;
unknown columns are reported and skipped.

Row validation: a known price node, a parseable interval start aligned to its block (a 15-minute interval starts at
:00 / :15 / :30 / :45), block_minutes in 5 / 15 / 30 / 60, price within -1000..20000 USD/MWh, and no duplicate
(node, interval_start) in the file (the last one wins). Existing (node, interval_start) prices are updated, new ones
inserted. Timestamps without a zone are plant / market time (Asia/Kolkata), no UTC conversion.
"""
from datetime import datetime
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.dam_price import PriceNode, RtPrice
from app.schemas.rt_price import BulkRtPriceRowError, RtPriceCreate
from app.services.dam_price_import import NODE_HEADERS, PRICE_HEADERS, _num, _pick
from app.services.demand_telemetry_import import _read_csv, _read_xlsx, _ts

MAX_ROWS = 300_000
TS_HEADERS = ("interval_start", "ts", "timestamp", "time")


class RtPriceImportError(Exception):
    """File-level problems: bad format, missing columns, unknown node, empty file."""


def parse_rt_price_file(db: Session, filename: str, content: bytes, node_id: Optional[int] = None):
    """Returns (valid rows as dicts, row errors, total data rows, unknown columns, node codes used)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise RtPriceImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except RtPriceImportError:
        raise
    except Exception as exc:  # the shared readers raise their own error type
        raise RtPriceImportError(str(exc)) from exc
    if len(raw_rows) > MAX_ROWS:
        raise RtPriceImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    node_h, ts_h, price_h = _pick(idx, NODE_HEADERS), _pick(idx, TS_HEADERS), _pick(idx, PRICE_HEADERS)
    missing = [label for label, h in (("interval_start", ts_h), ("price_mwh", price_h)) if h is None]
    if node_h is None and node_id is None:
        missing.insert(0, "node_code (or choose a node for the whole file)")
    if missing:
        raise RtPriceImportError(f"Missing required column(s): {', '.join(missing)}")
    block_h = "block_minutes" if "block_minutes" in idx else None
    known = {node_h, ts_h, price_h, block_h} - {None}
    ignored = [h for h, n in zip(headers, norm) if n and n not in known]

    codes = {n.node_code: n.node_id for n in db.query(PriceNode.node_code, PriceNode.node_id)}
    by_id = {v: k for k, v in codes.items()}
    if node_id is not None and node_id not in by_id:
        raise RtPriceImportError(f"Price node {node_id} does not exist")

    valid: dict[tuple, dict] = {}
    errors: list[BulkRtPriceRowError] = []
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
            problems.append(f"interval_start: {exc}")
            start = None
        values = {}
        try:
            values["price_mwh"] = _num(cell(idx[price_h]), "price_mwh")
            if values["price_mwh"] is None:
                problems.append("price_mwh: missing")
            if block_h is not None:
                bm = _num(cell(idx[block_h]), "block_minutes")
                if bm is not None:
                    if bm != int(bm):
                        raise ValueError(f"block_minutes: '{bm}' is not a whole number")
                    values["block_minutes"] = int(bm)
        except ValueError as exc:
            problems.append(str(exc))
        if problems:
            errors.append(BulkRtPriceRowError(row=row_no, errors=problems))
            continue
        try:
            rec = RtPriceCreate(node_id=nid, interval_start=start, **{k: v for k, v in values.items() if v is not None})
        except ValidationError as exc:
            errors.append(BulkRtPriceRowError(row=row_no, errors=[
                ".".join(str(p) for p in e["loc"]) + ": " + e["msg"].replace("Value error, ", "") for e in exc.errors()]))
            continue
        if (start.minute * 60 + start.second) % (rec.block_minutes * 60) or start.microsecond:
            errors.append(BulkRtPriceRowError(row=row_no, errors=[
                f"interval_start: {start:%H:%M:%S} is not on a {rec.block_minutes}-minute interval boundary"]))
            continue
        valid[(nid, start)] = rec.model_dump()
    rows = [valid[k] for k in sorted(valid, key=lambda k: (k[0], k[1]))]
    return rows, errors, len(raw_rows), ignored, sorted({by_id[r["node_id"]] for r in rows})


def upsert_rt_prices(db: Session, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    table = RtPrice.__table__
    inserted = updated = 0
    for start in range(0, len(rows), 2000):
        stmt = pg_insert(table).values(rows[start:start + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["node_id", "interval_start"],
            set_={c: getattr(stmt.excluded, c) for c in ("block_minutes", "price_mwh")},
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
    starts = [r["interval_start"] for r in rows]
    return min(starts), max(starts)
