"""Day-ahead market prices (battery_master.dam_price): list / filter, read, add, edit, delete and bulk load,
plus the price nodes they are quoted at. A price is keyed by (node_id, delivery_start)."""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models  # noqa: F401 - registers site for the price_node foreign key
from app.database import get_db
from app.models.dam_price import DamPrice, Market, PriceNode
from app.schemas.dam_price import (
    BulkDamPriceResult,
    BulkDamPriceRowError,
    DamPriceCreate,
    DamPriceOut,
    DamPricePage,
    DamPriceStats,
    DamPriceUpdate,
    PriceNodeOut,
)
from app.services.dam_price_import import DamPriceImportError, first_last, parse_dam_price_file, upsert_dam_prices

router = APIRouter(prefix="/api/dam-prices", tags=["market data"])

PLANT_TZ = ZoneInfo("Asia/Kolkata")


def _out(row: DamPrice, code: str) -> DamPriceOut:
    return DamPriceOut(node_id=row.node_id, node_code=code, delivery_start=row.delivery_start,
                       block_minutes=row.block_minutes, price_mwh=float(row.price_mwh),
                       cleared_mw=float(row.cleared_mw) if row.cleared_mw is not None else None)


def _local(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=PLANT_TZ)


def _get(db: Session, node_id: int, delivery_start: datetime) -> tuple[DamPrice, str]:
    found = (db.query(DamPrice, PriceNode.node_code).join(PriceNode, PriceNode.node_id == DamPrice.node_id)
             .filter(DamPrice.node_id == node_id, DamPrice.delivery_start == _local(delivery_start)).first())
    if not found:
        raise HTTPException(status_code=404, detail=f"No DAM price for node {node_id} at {delivery_start.isoformat()}")
    return found


def _node_code(db: Session, node_id: int) -> str:
    code = db.query(PriceNode.node_code).filter(PriceNode.node_id == node_id).scalar()
    if code is None:
        raise HTTPException(status_code=422, detail=f"Price node {node_id} does not exist")
    return code


def _check_boundary(start: datetime, block_minutes: int):
    if (start.minute * 60 + start.second) % (block_minutes * 60) or start.microsecond:
        raise HTTPException(status_code=422,
                            detail=f"delivery_start {start:%H:%M} is not on a {block_minutes}-minute block boundary")


@router.get("/nodes", response_model=list[PriceNodeOut])
def list_nodes(db: Session = Depends(get_db)):
    """Price nodes with their market, site and how many DAM blocks each has."""
    counts = dict(db.query(DamPrice.node_id, func.count()).group_by(DamPrice.node_id).all())
    rows = (db.query(PriceNode, Market, models.Site.site_code)
            .join(Market, Market.market_id == PriceNode.market_id)
            .outerjoin(models.Site, models.Site.site_id == PriceNode.site_id)
            .order_by(PriceNode.node_code).all())
    return [PriceNodeOut(node_id=n.node_id, node_code=n.node_code, name=n.name, node_type=n.node_type,
                         market_code=m.market_code, currency=m.currency, timezone=m.timezone, site_id=n.site_id,
                         site_code=sc, blocks=counts.get(n.node_id, 0)) for n, m, sc in rows]


@router.get("", response_model=DamPricePage)
def list_prices(node_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
                min_price: Optional[float] = None, max_price: Optional[float] = None,
                order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                page_size: int = Query(48, ge=1, le=2000), db: Session = Depends(get_db)):
    """DAM prices in a plant-time date range (end inclusive), with price statistics over the whole filtered range."""
    q = db.query(DamPrice, PriceNode.node_code).join(PriceNode, PriceNode.node_id == DamPrice.node_id)
    if node_id is not None:
        q = q.filter(DamPrice.node_id == node_id)
    if start:
        q = q.filter(DamPrice.delivery_start >= datetime.combine(start, time(), PLANT_TZ))
    if end:
        q = q.filter(DamPrice.delivery_start < datetime.combine(end + timedelta(days=1), time(), PLANT_TZ))
    if min_price is not None:
        q = q.filter(DamPrice.price_mwh >= min_price)
    if max_price is not None:
        q = q.filter(DamPrice.price_mwh <= max_price)

    agg = q.with_entities(
        func.count(), func.min(DamPrice.delivery_start), func.max(DamPrice.delivery_start),
        func.avg(DamPrice.price_mwh), func.min(DamPrice.price_mwh), func.max(DamPrice.price_mwh),
        func.sum(DamPrice.cleared_mw * DamPrice.block_minutes / 60.0)).one()
    f = lambda v: round(float(v), 2) if v is not None else None  # noqa: E731
    stats = DamPriceStats(blocks=agg[0], first_start=agg[1], last_start=agg[2], avg_price=f(agg[3]),
                          min_price=f(agg[4]), max_price=f(agg[5]), total_cleared_mwh=f(agg[6]))

    cols = (DamPrice.delivery_start.asc(), PriceNode.node_code) if order == "asc" else \
        (DamPrice.delivery_start.desc(), PriceNode.node_code)
    rows = q.order_by(*cols).offset((page - 1) * page_size).limit(page_size).all()
    return DamPricePage(items=[_out(r, c) for r, c in rows], total=agg[0], page=page, page_size=page_size,
                        stats=stats)


@router.get("/{node_id}/{delivery_start}", response_model=DamPriceOut)
def get_price(node_id: int, delivery_start: datetime, db: Session = Depends(get_db)):
    return _out(*_get(db, node_id, delivery_start))


@router.post("", response_model=DamPriceOut, status_code=201)
def add_price(payload: DamPriceCreate, db: Session = Depends(get_db)):
    """Add a block; one already priced for that node and start is refused (edit it instead)."""
    code = _node_code(db, payload.node_id)
    start = _local(payload.delivery_start)
    _check_boundary(start, payload.block_minutes)
    if db.get(DamPrice, (payload.node_id, start)):
        raise HTTPException(status_code=409, detail=f"{code} already has a DAM price at {start.isoformat()}")
    row = DamPrice(**{**payload.model_dump(), "delivery_start": start})
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc.orig).splitlines()[0])
    db.refresh(row)
    return _out(row, code)


@router.put("/{node_id}/{delivery_start}", response_model=DamPriceOut)
def update_price(node_id: int, delivery_start: datetime, payload: DamPriceUpdate, db: Session = Depends(get_db)):
    """Edit price, volume or block length; node and delivery start are the key and stay fixed."""
    row, code = _get(db, node_id, delivery_start)
    _check_boundary(row.delivery_start.astimezone(PLANT_TZ), payload.block_minutes)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row, code)


@router.delete("/{node_id}/{delivery_start}", status_code=204)
def delete_price(node_id: int, delivery_start: datetime, db: Session = Depends(get_db)):
    row, _ = _get(db, node_id, delivery_start)
    db.delete(row)
    db.commit()
    return None


@router.post("/bulk", response_model=BulkDamPriceResult)
async def bulk_load(file: UploadFile = File(...), node_id: Optional[int] = Form(None), db: Session = Depends(get_db)):
    """Load a .csv / .xlsx of DAM prices; existing (node, delivery_start) blocks are updated. node_id applies to rows
    without a node_code (or to the whole file when it has no node_code column)."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        valid, errors, total, ignored, nodes = parse_dam_price_file(db, file.filename or "upload", content, node_id)
    except DamPriceImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    inserted, updated = upsert_dam_prices(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, BulkDamPriceRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    first, last = first_last(valid)
    return BulkDamPriceResult(filename=file.filename or "upload", total_rows=total, valid_rows=len(valid),
                              inserted=inserted, updated=updated, error_count=n_errors, errors=errors[:200],
                              nodes=nodes, first_start=first, last_start=last)

