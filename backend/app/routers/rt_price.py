"""Real-time / imbalance prices (battery_master.rt_price): list / filter, read, add, edit, delete and bulk load.
A price is keyed by (node_id, interval_start). Each interval is shown next to the day-ahead price of its hour
(dam_price at date_trunc('hour', interval_start), as v_arbitrage_features joins them) and the RT - DAM spread.
Price nodes come from GET /api/dam-prices/nodes."""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dam_price import DamPrice, PriceNode, RtPrice
from app.schemas.rt_price import (
    BulkRtPriceResult,
    BulkRtPriceRowError,
    RtPriceCreate,
    RtPriceOut,
    RtPricePage,
    RtPriceStats,
    RtPriceUpdate,
)
from app.services.rt_price_import import RtPriceImportError, first_last, parse_rt_price_file, upsert_rt_prices

router = APIRouter(prefix="/api/rt-prices", tags=["market data"])

PLANT_TZ = ZoneInfo("Asia/Kolkata")

# hour truncation runs in the session time zone (Asia/Kolkata), so the half-hour offset lands on plant-time hours
DAM_JOIN = and_(DamPrice.node_id == RtPrice.node_id,
                DamPrice.delivery_start == func.date_trunc("hour", RtPrice.interval_start))
SPREAD = RtPrice.price_mwh - DamPrice.price_mwh


def _r2(v) -> Optional[float]:
    return round(float(v), 2) if v is not None else None


def _out(row: RtPrice, code: str, dam) -> RtPriceOut:
    dam_f = _r2(dam)
    return RtPriceOut(node_id=row.node_id, node_code=code, interval_start=row.interval_start,
                      block_minutes=row.block_minutes, price_mwh=float(row.price_mwh), dam_price_mwh=dam_f,
                      spread_mwh=_r2(float(row.price_mwh) - dam_f) if dam_f is not None else None)


def _local(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=PLANT_TZ)


def _base(db: Session):
    return (db.query(RtPrice, PriceNode.node_code, DamPrice.price_mwh)
            .join(PriceNode, PriceNode.node_id == RtPrice.node_id)
            .outerjoin(DamPrice, DAM_JOIN))


def _get(db: Session, node_id: int, interval_start: datetime):
    found = _base(db).filter(RtPrice.node_id == node_id, RtPrice.interval_start == _local(interval_start)).first()
    if not found:
        raise HTTPException(status_code=404, detail=f"No RT price for node {node_id} at {interval_start.isoformat()}")
    return found


def _node_code(db: Session, node_id: int) -> str:
    code = db.query(PriceNode.node_code).filter(PriceNode.node_id == node_id).scalar()
    if code is None:
        raise HTTPException(status_code=422, detail=f"Price node {node_id} does not exist")
    return code


def _check_boundary(start: datetime, block_minutes: int):
    if (start.minute * 60 + start.second) % (block_minutes * 60) or start.microsecond:
        raise HTTPException(status_code=422,
                            detail=f"interval_start {start:%H:%M} is not on a {block_minutes}-minute interval boundary")


@router.get("", response_model=RtPricePage)
def list_prices(node_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
                min_price: Optional[float] = None, max_price: Optional[float] = None,
                order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                page_size: int = Query(96, ge=1, le=5000), db: Session = Depends(get_db)):
    """RT prices in a plant-time date range (end inclusive), with statistics over the whole filtered range."""
    q = _base(db)
    if node_id is not None:
        q = q.filter(RtPrice.node_id == node_id)
    if start:
        q = q.filter(RtPrice.interval_start >= datetime.combine(start, time(), PLANT_TZ))
    if end:
        q = q.filter(RtPrice.interval_start < datetime.combine(end + timedelta(days=1), time(), PLANT_TZ))
    if min_price is not None:
        q = q.filter(RtPrice.price_mwh >= min_price)
    if max_price is not None:
        q = q.filter(RtPrice.price_mwh <= max_price)

    agg = q.with_entities(
        func.count(), func.min(RtPrice.interval_start), func.max(RtPrice.interval_start),
        func.avg(RtPrice.price_mwh), func.min(RtPrice.price_mwh), func.max(RtPrice.price_mwh),
        func.stddev_samp(RtPrice.price_mwh), func.avg(SPREAD), func.count(DamPrice.price_mwh)).one()
    stats = RtPriceStats(intervals=agg[0], first_start=agg[1], last_start=agg[2], avg_price=_r2(agg[3]),
                         min_price=_r2(agg[4]), max_price=_r2(agg[5]), stddev_price=_r2(agg[6]),
                         avg_spread=_r2(agg[7]), matched_dam=agg[8])

    ts_col = RtPrice.interval_start.asc() if order == "asc" else RtPrice.interval_start.desc()
    rows = q.order_by(ts_col, PriceNode.node_code).offset((page - 1) * page_size).limit(page_size).all()
    return RtPricePage(items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size, stats=stats)


@router.get("/{node_id}/{interval_start}", response_model=RtPriceOut)
def get_price(node_id: int, interval_start: datetime, db: Session = Depends(get_db)):
    return _out(*_get(db, node_id, interval_start))


@router.post("", response_model=RtPriceOut, status_code=201)
def add_price(payload: RtPriceCreate, db: Session = Depends(get_db)):
    """Add an interval; one already priced for that node and start is refused (edit it instead)."""
    code = _node_code(db, payload.node_id)
    start = _local(payload.interval_start)
    _check_boundary(start, payload.block_minutes)
    if db.get(RtPrice, (payload.node_id, start)):
        raise HTTPException(status_code=409, detail=f"{code} already has an RT price at {start.isoformat()}")
    db.add(RtPrice(**{**payload.model_dump(), "interval_start": start}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc.orig).splitlines()[0])
    return _out(*_get(db, payload.node_id, start))


@router.put("/{node_id}/{interval_start}", response_model=RtPriceOut)
def update_price(node_id: int, interval_start: datetime, payload: RtPriceUpdate, db: Session = Depends(get_db)):
    """Edit price or interval length; node and interval start are the key and stay fixed."""
    row, _, _ = _get(db, node_id, interval_start)
    _check_boundary(row.interval_start.astimezone(PLANT_TZ), payload.block_minutes)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return _out(*_get(db, node_id, interval_start))


@router.delete("/{node_id}/{interval_start}", status_code=204)
def delete_price(node_id: int, interval_start: datetime, db: Session = Depends(get_db)):
    row, _, _ = _get(db, node_id, interval_start)
    db.delete(row)
    db.commit()
    return None


@router.post("/bulk", response_model=BulkRtPriceResult)
async def bulk_load(file: UploadFile = File(...), node_id: Optional[int] = Form(None), db: Session = Depends(get_db)):
    """Load a .csv / .xlsx of RT prices; existing (node, interval_start) intervals are updated. node_id applies to
    rows without a node_code (or to the whole file when it has no node_code column)."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        valid, errors, total, ignored, nodes = parse_rt_price_file(db, file.filename or "upload", content, node_id)
    except RtPriceImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    inserted, updated = upsert_rt_prices(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, BulkRtPriceRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    first, last = first_last(valid)
    return BulkRtPriceResult(filename=file.filename or "upload", total_rows=total, valid_rows=len(valid),
                             inserted=inserted, updated=updated, error_count=n_errors, errors=errors[:200],
                             nodes=nodes, first_start=first, last_start=last)
