"""Bulk load of probabilistic price forecasts (BESS_Arbitrage_DataPack/price_forecast.csv / .xlsx) into
battery_master.price_forecast.

Columns: node_code (or node; optional when one node is chosen for the whole file), issued_at, target_ts, p50_mwh
(or p50) - required; horizon_h, p10_mwh (or p10), p90_mwh (or p90), model - optional. Header case and surrounding
spaces are ignored; unknown columns are reported and skipped.

Row validation: a known price node, parseable issue and target times with the target after the issue (at most two
weeks ahead), horizon_h equal to target - issue (derived when empty), prices within -1000..20000 USD/MWh, quantiles in
order (p10 <= p50 <= p90), and no duplicate (node, issued_at, target_ts) in the file (the last one wins). Every issue
vintage is kept; existing (node, issued_at, target_ts) rows are updated, new ones inserted. Timestamps without a zone
are plant / market time (Asia/Kolkata), no UTC conversion.
"""
from datetime import datetime
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.dam_price import PriceForecast, PriceNode
from app.schemas.price_forecast import BulkPriceForecastRowError, PriceForecastCreate
from app.services.dam_price_import import NODE_HEADERS, _num, _pick
from app.services.demand_telemetry_import import _read_csv, _read_xlsx, _ts

MAX_ROWS = 300_000
ISSUED_HEADERS = ("issued_at", "issued", "issue_ts")
TARGET_HEADERS = ("target_ts", "target", "delivery_start")
QUANTILES = {"p10_mwh": ("p10_mwh", "p10"), "p50_mwh": ("p50_mwh", "p50"), "p90_mwh": ("p90_mwh", "p90")}


class PriceForecastImportError(Exception):
    """File-level problems: bad format, missing columns, unknown node, empty file."""


def parse_price_forecast_file(db: Session, filename: str, content: bytes, node_id: Optional[int] = None):
    """Returns (valid rows as dicts, row errors, total data rows, unknown columns, node codes used)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise PriceForecastImportError("Unsupported file type. Please upload a .csv or .xlsx file.")
    except PriceForecastImportError:
        raise
    except Exception as exc:  # the shared readers raise their own error type
        raise PriceForecastImportError(str(exc)) from exc
    if len(raw_rows) > MAX_ROWS:
        raise PriceForecastImportError(f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")

    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    node_h, iss_h, tgt_h = _pick(idx, NODE_HEADERS), _pick(idx, ISSUED_HEADERS), _pick(idx, TARGET_HEADERS)
    q_h = {f: _pick(idx, names) for f, names in QUANTILES.items()}
    hor_h = "horizon_h" if "horizon_h" in idx else None
    model_h = "model" if "model" in idx else None
    missing = [label for label, h in (("issued_at", iss_h), ("target_ts", tgt_h), ("p50_mwh", q_h["p50_mwh"]))
               if h is None]
    if node_h is None and node_id is None:
        missing.insert(0, "node_code (or choose a node for the whole file)")
    if missing:
        raise PriceForecastImportError(f"Missing required column(s): {', '.join(missing)}")
    known = {node_h, iss_h, tgt_h, hor_h, model_h, *q_h.values()} - {None}
    ignored = [h for h, n in zip(headers, norm) if n and n not in known]

    codes = {n.node_code: n.node_id for n in db.query(PriceNode.node_code, PriceNode.node_id)}
    by_id = {v: k for k, v in codes.items()}
    if node_id is not None and node_id not in by_id:
        raise PriceForecastImportError(f"Price node {node_id} does not exist")

    valid: dict[tuple, dict] = {}
    errors: list[BulkPriceForecastRowError] = []
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
        times = {}
        for field, h in (("issued_at", iss_h), ("target_ts", tgt_h)):
            try:
                times[field] = _ts(cell(idx[h]))
            except (ValueError, OverflowError) as exc:
                problems.append(f"{field}: {exc}")
        values = {}
        try:
            for field, h in q_h.items():
                if h is not None:
                    values[field] = _num(cell(idx[h]), field)
            if values.get("p50_mwh") is None:
                problems.append("p50_mwh: missing")
            if hor_h is not None:
                values["horizon_h"] = _num(cell(idx[hor_h]), "horizon_h")
        except ValueError as exc:
            problems.append(str(exc))
        if model_h is not None:
            values["model"] = str(cell(idx[model_h]) or "").strip() or None
        if problems:
            errors.append(BulkPriceForecastRowError(row=row_no, errors=problems))
            continue
        try:
            rec = PriceForecastCreate(node_id=nid, **times, **{k: v for k, v in values.items() if v is not None})
        except ValidationError as exc:
            errors.append(BulkPriceForecastRowError(row=row_no, errors=[
                (".".join(str(p) for p in e["loc"]) + ": " if e["loc"] else "") + e["msg"].replace("Value error, ", "")
                for e in exc.errors()]))
            continue
        valid[(nid, rec.issued_at, rec.target_ts)] = rec.model_dump()
    rows = [valid[k] for k in sorted(valid)]
    return rows, errors, len(raw_rows), ignored, sorted({by_id[r["node_id"]] for r in rows})


def upsert_price_forecasts(db: Session, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    table = PriceForecast.__table__
    inserted = updated = 0
    for start in range(0, len(rows), 2000):
        stmt = pg_insert(table).values(rows[start:start + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["node_id", "issued_at", "target_ts"],
            set_={c: getattr(stmt.excluded, c) for c in ("horizon_h", "p10_mwh", "p50_mwh", "p90_mwh", "model")},
        ).returning(literal_column("(xmax = 0)").label("was_insert"))
        for r in db.execute(stmt):
            if r.was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated


def target_range(rows: list[dict]) -> tuple[Optional[datetime], Optional[datetime]]:
    if not rows:
        return None, None
    targets = [r["target_ts"] for r in rows]
    return min(targets), max(targets)
