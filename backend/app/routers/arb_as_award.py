"""Ancillary-service awards (battery_master.as_award): committed AS capacity per system, product and delivery window -
each reserves power / SOC headroom the optimizer must respect. Keyed by award_id; (system, product, delivery_start)
is unique, so bulk loads update instead of duplicating. Revenue is derived (MW x price x hours) when empty."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.battery_system import BatterySystem
from app.models.arbitrage import AsAward
from app.models.as_price import AsProduct
from app.routers.arb_common import bulk_result, commit_or_409, fmt, in_days, local, resolvers, system_code
from app.schemas.arbitrage import AsAwardCreate, AsAwardOut, AsAwardUpdate, BulkResult, Page, Stat
from app.services.arbitrage_import import ArbitrageImportError, Col, num, parse_upload, ts_span, upsert, validate_rows

router = APIRouter(prefix="/api/as-awards", tags=["dispatch"])

AW = AsAward
COLS = [
    Col("system_id", ("system_code", "system"), "code", True, "system"),
    Col("product_id", ("product_code", "product"), "code", True, "product"),
    Col("delivery_start", ("delivery_start",), "ts", True),
    Col("delivery_end", ("delivery_end",), "ts", True),
    Col("awarded_mw", ("awarded_mw", "mw"), "num", True),
    Col("capacity_price_mw", ("capacity_price_mw", "cap")),
    Col("revenue_usd", ("revenue_usd", "revenue")),
]
DURATION_MIN = func.extract("epoch", AW.delivery_end - AW.delivery_start) / 60.0


def _base(db: Session):
    return (db.query(AW, BatterySystem.system_name, AsProduct.product_code, AsProduct.min_bid_mw)
            .join(BatterySystem, BatterySystem.battery_system_id == AW.system_id)
            .join(AsProduct, AsProduct.product_id == AW.product_id))


def _out(a: AW, scode, pcode, _min_bid=None) -> AsAwardOut:
    return AsAwardOut(award_id=a.award_id, system_id=a.system_id, system_code=scode, product_id=a.product_id,
                      product_code=pcode, delivery_start=a.delivery_start, delivery_end=a.delivery_end,
                      duration_min=round((a.delivery_end - a.delivery_start).total_seconds() / 60, 1),
                      awarded_mw=float(a.awarded_mw), capacity_price_mw=num(a.capacity_price_mw),
                      revenue_usd=num(a.revenue_usd))


def _get(db: Session, award_id: int):
    found = _base(db).filter(AW.award_id == award_id).first()
    if not found:
        raise HTTPException(status_code=404, detail=f"AS award {award_id} does not exist")
    return found


def _min_bid(db: Session, product_id: int, mw: float) -> Optional[str]:
    p = db.get(AsProduct, product_id)
    if p is None:
        return f"product {product_id} does not exist"
    if p.min_bid_mw is not None and mw < float(p.min_bid_mw):
        return f"awarded_mw {mw} is below {p.product_code}'s minimum bid of {float(p.min_bid_mw)} MW"
    return None


def _overlap(db: Session, system_id: int, product_id: int, start, end, award_id: Optional[int] = None):
    q = db.query(AW.award_id).filter(AW.system_id == system_id, AW.product_id == product_id,
                                     AW.delivery_start < end, AW.delivery_end > start)
    if award_id is not None:
        q = q.filter(AW.award_id != award_id)
    other = q.first()
    return f"overlaps award {other[0]} for the same system and product" if other else None


@router.get("", response_model=Page[AsAwardOut])
def list_awards(system_id: Optional[int] = None, product_id: Optional[int] = None, start: Optional[date] = None,
                end: Optional[date] = None, order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=2000), db: Session = Depends(get_db)):
    """Awards starting in the plant-time date range, with commitment and revenue totals."""
    q = _base(db)
    if system_id is not None:
        q = q.filter(AW.system_id == system_id)
    if product_id is not None:
        q = q.filter(AW.product_id == product_id)
    q = in_days(q, AW.delivery_start, start, end)
    agg = q.with_entities(func.count(), func.sum(AW.awarded_mw * DURATION_MIN / 60.0), func.sum(AW.revenue_usd),
                          func.avg(AW.capacity_price_mw), func.sum(DURATION_MIN) / 60.0,
                          func.max(AW.awarded_mw)).one()
    stats = [Stat(label="Awards", value=str(agg[0])),
             Stat(label="Committed", value=fmt(agg[1], 3, "MW·h")),
             Stat(label="Time committed", value=fmt(agg[4], 2, "h")),
             Stat(label="Largest award", value=fmt(agg[5], 3, "MW")),
             Stat(label="Avg capacity price", value=fmt(agg[3], 2, "USD/MW")),
             Stat(label="Total revenue", value=fmt(agg[2], 2, "USD"))]
    col = AW.delivery_start.asc() if order == "asc" else AW.delivery_start.desc()
    rows = q.order_by(col, AW.award_id).offset((page - 1) * page_size).limit(page_size).all()
    return Page[AsAwardOut](items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size, stats=stats)


@router.get("/{award_id}", response_model=AsAwardOut)
def get_award(award_id: int, db: Session = Depends(get_db)):
    return _out(*_get(db, award_id))


@router.post("", response_model=AsAwardOut, status_code=201)
def add_award(payload: AsAwardCreate, db: Session = Depends(get_db)):
    system_code(db, payload.system_id)
    start, end = local(payload.delivery_start), local(payload.delivery_end)
    problem = _min_bid(db, payload.product_id, payload.awarded_mw) or _overlap(db, payload.system_id,
                                                                              payload.product_id, start, end)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    row = AW(**{**payload.model_dump(), "delivery_start": start, "delivery_end": end})
    db.add(row)
    commit_or_409(db)
    return _out(*_get(db, row.award_id))


@router.put("/{award_id}", response_model=AsAwardOut)
def update_award(award_id: int, payload: AsAwardUpdate, db: Session = Depends(get_db)):
    """Edit the window end, MW, price or revenue; system, product and start identify the award."""
    row = _get(db, award_id)[0]
    end = local(payload.delivery_end)
    if end <= row.delivery_start:
        raise HTTPException(status_code=422, detail="delivery_end must be after delivery_start")
    problem = (_min_bid(db, row.product_id, payload.awarded_mw)
               or _overlap(db, row.system_id, row.product_id, row.delivery_start, end, award_id))
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    data = payload.model_dump()
    data["delivery_end"] = end
    if data["revenue_usd"] is None and data["capacity_price_mw"] is not None:
        hours = (end - row.delivery_start).total_seconds() / 3600
        data["revenue_usd"] = round(data["awarded_mw"] * data["capacity_price_mw"] * hours, 2)
    for field, value in data.items():
        setattr(row, field, value)
    commit_or_409(db)
    return _out(*_get(db, award_id))


@router.delete("/{award_id}", status_code=204)
def delete_award(award_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, award_id)[0])
    db.commit()
    return None


@router.post("/bulk", response_model=BulkResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load as_award.csv / .xlsx; an award for the same system, product and delivery start is updated."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        records, errors, total, ignored = parse_upload(file.filename or "upload", content, COLS, resolvers(db))
    except ArbitrageImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    min_bid = {p.product_id: (p.product_code, p.min_bid_mw) for p in db.query(AsProduct)}

    def check(m: AsAwardCreate):
        code, mb = min_bid[m.product_id]
        if mb is not None and m.awarded_mw < float(mb):
            return f"awarded_mw {m.awarded_mw} is below {code}'s minimum bid of {float(mb)} MW"
        return None

    valid = validate_rows(records, AsAwardCreate, errors, check,
                          key=lambda m: (m.system_id, m.product_id, local(m.delivery_start)))
    for r in valid:
        r["delivery_start"], r["delivery_end"] = local(r["delivery_start"]), local(r["delivery_end"])
    # overlapping windows inside the file (same system + product)
    warnings, last = [], {}
    for r in sorted(valid, key=lambda r: (r["system_id"], r["product_id"], r["delivery_start"])):
        k = (r["system_id"], r["product_id"])
        if k in last and r["delivery_start"] < last[k]:
            warnings.append(f"award at {r['delivery_start']:%Y-%m-%d %H:%M} overlaps the previous one for the "
                            "same system and product")
        last[k] = max(last.get(k, r["delivery_end"]), r["delivery_end"])
    inserted, updated = upsert(db, AW.__table__, valid, ["system_id", "product_id", "delivery_start"],
                               ["delivery_end", "awarded_mw", "capacity_price_mw", "revenue_usd"])
    db.commit()
    return bulk_result(file.filename or "upload", total, valid, inserted, updated, errors, ignored, warnings[:20],
                       ts_span(valid, "delivery_start"))
