"""Ancillary-service prices (battery_master.as_price): list / filter, read, add, edit, delete and bulk load, plus the
AS products they are quoted for. A price is keyed by (product_id, delivery_start)."""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.as_price import AsPrice, AsProduct
from app.models.dam_price import Market
from app.schemas.as_price import (
    AsPriceCreate,
    AsPriceOut,
    AsPricePage,
    AsPriceStats,
    AsPriceUpdate,
    AsProductOut,
    BulkAsPriceResult,
    BulkAsPriceRowError,
)
from app.services.as_price_import import AsPriceImportError, first_last, parse_as_price_file, upsert_as_prices

router = APIRouter(prefix="/api/as-prices", tags=["market data"])

PLANT_TZ = ZoneInfo("Asia/Kolkata")


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _out(row: AsPrice, code: str) -> AsPriceOut:
    return AsPriceOut(product_id=row.product_id, product_code=code, delivery_start=row.delivery_start,
                      block_minutes=row.block_minutes, capacity_price_mw=_f(row.capacity_price_mw),
                      performance_price=_f(row.performance_price))


def _local(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=PLANT_TZ)


def _get(db: Session, product_id: int, delivery_start: datetime) -> tuple[AsPrice, str]:
    found = (db.query(AsPrice, AsProduct.product_code).join(AsProduct, AsProduct.product_id == AsPrice.product_id)
             .filter(AsPrice.product_id == product_id, AsPrice.delivery_start == _local(delivery_start)).first())
    if not found:
        raise HTTPException(status_code=404,
                            detail=f"No AS price for product {product_id} at {delivery_start.isoformat()}")
    return found


def _product_code(db: Session, product_id: int) -> str:
    code = db.query(AsProduct.product_code).filter(AsProduct.product_id == product_id).scalar()
    if code is None:
        raise HTTPException(status_code=422, detail=f"AS product {product_id} does not exist")
    return code


def _check_boundary(start: datetime, block_minutes: int):
    if (start.minute * 60 + start.second) % (block_minutes * 60) or start.microsecond:
        raise HTTPException(status_code=422,
                            detail=f"delivery_start {start:%H:%M} is not on a {block_minutes}-minute block boundary")


@router.get("/products", response_model=list[AsProductOut])
def list_products(db: Session = Depends(get_db)):
    """AS products with their market and how many price blocks each has."""
    counts = dict(db.query(AsPrice.product_id, func.count()).group_by(AsPrice.product_id).all())
    rows = (db.query(AsProduct, Market).join(Market, Market.market_id == AsProduct.market_id)
            .order_by(AsProduct.product_id).all())
    return [AsProductOut(product_id=p.product_id, product_code=p.product_code, name=p.name, direction=p.direction,
                         min_bid_mw=_f(p.min_bid_mw), sustain_minutes=p.sustain_minutes,
                         response_seconds=p.response_seconds, settlement=p.settlement, description=p.description,
                         market_code=m.market_code, currency=m.currency, blocks=counts.get(p.product_id, 0))
            for p, m in rows]


@router.get("", response_model=AsPricePage)
def list_prices(product_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
                min_capacity: Optional[float] = None, max_capacity: Optional[float] = None,
                order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                page_size: int = Query(48, ge=1, le=2000), db: Session = Depends(get_db)):
    """AS prices in a plant-time date range (end inclusive), with statistics over the whole filtered range."""
    q = db.query(AsPrice, AsProduct.product_code).join(AsProduct, AsProduct.product_id == AsPrice.product_id)
    if product_id is not None:
        q = q.filter(AsPrice.product_id == product_id)
    if start:
        q = q.filter(AsPrice.delivery_start >= datetime.combine(start, time(), PLANT_TZ))
    if end:
        q = q.filter(AsPrice.delivery_start < datetime.combine(end + timedelta(days=1), time(), PLANT_TZ))
    if min_capacity is not None:
        q = q.filter(AsPrice.capacity_price_mw >= min_capacity)
    if max_capacity is not None:
        q = q.filter(AsPrice.capacity_price_mw <= max_capacity)

    agg = q.with_entities(
        func.count(), func.min(AsPrice.delivery_start), func.max(AsPrice.delivery_start),
        func.avg(AsPrice.capacity_price_mw), func.min(AsPrice.capacity_price_mw), func.max(AsPrice.capacity_price_mw),
        func.avg(AsPrice.performance_price), func.max(AsPrice.performance_price)).one()
    r2 = lambda v: round(float(v), 2) if v is not None else None  # noqa: E731
    stats = AsPriceStats(blocks=agg[0], first_start=agg[1], last_start=agg[2], avg_capacity=r2(agg[3]),
                         min_capacity=r2(agg[4]), max_capacity=r2(agg[5]), avg_performance=r2(agg[6]),
                         max_performance=r2(agg[7]))

    ts_col = AsPrice.delivery_start.asc() if order == "asc" else AsPrice.delivery_start.desc()
    rows = q.order_by(ts_col, AsProduct.product_code).offset((page - 1) * page_size).limit(page_size).all()
    return AsPricePage(items=[_out(r, c) for r, c in rows], total=agg[0], page=page, page_size=page_size,
                       stats=stats)


@router.get("/{product_id}/{delivery_start}", response_model=AsPriceOut)
def get_price(product_id: int, delivery_start: datetime, db: Session = Depends(get_db)):
    return _out(*_get(db, product_id, delivery_start))


@router.post("", response_model=AsPriceOut, status_code=201)
def add_price(payload: AsPriceCreate, db: Session = Depends(get_db)):
    """Add a block; one already priced for that product and start is refused (edit it instead)."""
    code = _product_code(db, payload.product_id)
    start = _local(payload.delivery_start)
    _check_boundary(start, payload.block_minutes)
    if db.get(AsPrice, (payload.product_id, start)):
        raise HTTPException(status_code=409, detail=f"{code} already has an AS price at {start.isoformat()}")
    row = AsPrice(**{**payload.model_dump(), "delivery_start": start})
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc.orig).splitlines()[0])
    db.refresh(row)
    return _out(row, code)


@router.put("/{product_id}/{delivery_start}", response_model=AsPriceOut)
def update_price(product_id: int, delivery_start: datetime, payload: AsPriceUpdate, db: Session = Depends(get_db)):
    """Edit prices or block length; product and delivery start are the key and stay fixed."""
    row, code = _get(db, product_id, delivery_start)
    _check_boundary(row.delivery_start.astimezone(PLANT_TZ), payload.block_minutes)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, code)


@router.delete("/{product_id}/{delivery_start}", status_code=204)
def delete_price(product_id: int, delivery_start: datetime, db: Session = Depends(get_db)):
    row, _ = _get(db, product_id, delivery_start)
    db.delete(row)
    db.commit()
    return None


@router.post("/bulk", response_model=BulkAsPriceResult)
async def bulk_load(file: UploadFile = File(...), product_id: Optional[int] = Form(None),
                    db: Session = Depends(get_db)):
    """Load a .csv / .xlsx of AS prices; existing (product, delivery_start) blocks are updated. product_id applies
    to rows without a product_code (or to the whole file when it has no product_code column)."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        valid, errors, total, ignored, products = parse_as_price_file(db, file.filename or "upload", content,
                                                                      product_id)
    except AsPriceImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    inserted, updated = upsert_as_prices(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, BulkAsPriceRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    first, last = first_last(valid)
    return BulkAsPriceResult(filename=file.filename or "upload", total_rows=total, valid_rows=len(valid),
                             inserted=inserted, updated=updated, error_count=n_errors, errors=errors[:200],
                             products=products, first_start=first, last_start=last)
