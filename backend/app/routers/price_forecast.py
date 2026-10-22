"""Probabilistic price forecasts (battery_master.price_forecast): list / filter, read, add, edit, delete and bulk load,
plus the issue vintages. A row is keyed by (node_id, issued_at, target_ts); every vintage is kept so models can be
trained on what was known at the time. Each row is scored against the realized day-ahead price of its target hour
(dam_price at the same node and delivery_start = target_ts). Price nodes come from GET /api/dam-prices/nodes."""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import Integer, and_, case, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dam_price import DamPrice, PriceForecast, PriceNode
from app.schemas.price_forecast import (
    BulkPriceForecastResult,
    BulkPriceForecastRowError,
    ForecastVintage,
    PriceForecastCreate,
    PriceForecastOut,
    PriceForecastPage,
    PriceForecastStats,
    PriceForecastUpdate,
)
from app.services.price_forecast_import import (
    PriceForecastImportError,
    parse_price_forecast_file,
    target_range,
    upsert_price_forecasts,
)

router = APIRouter(prefix="/api/price-forecasts", tags=["market data"])

PLANT_TZ = ZoneInfo("Asia/Kolkata")
PF = PriceForecast

ACTUAL_JOIN = and_(DamPrice.node_id == PF.node_id, DamPrice.delivery_start == PF.target_ts)
ERROR = PF.p50_mwh - DamPrice.price_mwh
# 1 / 0 when the actual is known and both band edges are set, NULL otherwise (so AVG gives coverage over scored rows)
IN_BAND = case(
    (and_(DamPrice.price_mwh.isnot(None), PF.p10_mwh.isnot(None), PF.p90_mwh.isnot(None)),
     cast(and_(DamPrice.price_mwh >= PF.p10_mwh, DamPrice.price_mwh <= PF.p90_mwh), Integer)),
    else_=None)


def _f(v, nd: int = 2) -> Optional[float]:
    return round(float(v), nd) if v is not None else None


def _out(row: PriceForecast, code: str, actual) -> PriceForecastOut:
    a = _f(actual)
    p10, p50, p90 = _f(row.p10_mwh), float(row.p50_mwh), _f(row.p90_mwh)
    return PriceForecastOut(
        node_id=row.node_id, node_code=code, issued_at=row.issued_at, target_ts=row.target_ts,
        horizon_h=_f(row.horizon_h), p10_mwh=p10, p50_mwh=p50, p90_mwh=p90, model=row.model, actual_mwh=a,
        error_mwh=_f(p50 - a) if a is not None else None,
        in_band=(p10 <= a <= p90) if a is not None and p10 is not None and p90 is not None else None)


def _local(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=PLANT_TZ)


def _base(db: Session):
    return (db.query(PF, PriceNode.node_code, DamPrice.price_mwh)
            .join(PriceNode, PriceNode.node_id == PF.node_id)
            .outerjoin(DamPrice, ACTUAL_JOIN))


def _get(db: Session, node_id: int, issued_at: datetime, target_ts: datetime):
    found = _base(db).filter(PF.node_id == node_id, PF.issued_at == _local(issued_at),
                             PF.target_ts == _local(target_ts)).first()
    if not found:
        raise HTTPException(status_code=404, detail=(f"No forecast for node {node_id} issued {issued_at.isoformat()} "
                                                     f"for {target_ts.isoformat()}"))
    return found


def _filtered(db: Session, node_id, issued_at, start, end, model):
    q = _base(db)
    if node_id is not None:
        q = q.filter(PF.node_id == node_id)
    if issued_at is not None:
        q = q.filter(PF.issued_at == _local(issued_at))
    if start:
        q = q.filter(PF.target_ts >= datetime.combine(start, time(), PLANT_TZ))
    if end:
        q = q.filter(PF.target_ts < datetime.combine(end + timedelta(days=1), time(), PLANT_TZ))
    if model:
        q = q.filter(PF.model == model)
    return q


@router.get("/vintages", response_model=list[ForecastVintage])
def list_vintages(node_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Issue vintages (newest first) with their row count, target span and models."""
    q = (db.query(PF.node_id, PriceNode.node_code, PF.issued_at, func.count(), func.min(PF.target_ts),
                  func.max(PF.target_ts), func.array_agg(func.distinct(PF.model)))
         .join(PriceNode, PriceNode.node_id == PF.node_id))
    if node_id is not None:
        q = q.filter(PF.node_id == node_id)
    rows = q.group_by(PF.node_id, PriceNode.node_code, PF.issued_at).order_by(PF.issued_at.desc()).all()
    return [ForecastVintage(node_id=n, node_code=c, issued_at=i, rows=k, first_target=a, last_target=b,
                            models=[m for m in (ms or []) if m]) for n, c, i, k, a, b, ms in rows]


@router.get("/models", response_model=list[str])
def list_models(db: Session = Depends(get_db)):
    return [m for (m,) in db.query(PF.model).filter(PF.model.isnot(None)).distinct().order_by(PF.model)]


@router.get("", response_model=PriceForecastPage)
def list_forecasts(node_id: Optional[int] = None, issued_at: Optional[datetime] = None,
                   start: Optional[date] = None, end: Optional[date] = None, model: Optional[str] = None,
                   order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                   page_size: int = Query(48, ge=1, le=5000), db: Session = Depends(get_db)):
    """Forecast rows by target hour (plant-time date range, end inclusive), optionally one vintage, with accuracy
    statistics against the realized DAM price over the whole filtered range."""
    q = _filtered(db, node_id, issued_at, start, end, model)
    agg = q.with_entities(
        func.count(), func.count(func.distinct(PF.issued_at)), func.min(PF.target_ts), func.max(PF.target_ts),
        func.avg(PF.p50_mwh), func.avg(PF.p90_mwh - PF.p10_mwh), func.count(DamPrice.price_mwh),
        func.avg(func.abs(ERROR)), func.avg(ERROR), func.avg(IN_BAND)).one()
    stats = PriceForecastStats(rows=agg[0], vintages=agg[1], first_target=agg[2], last_target=agg[3],
                               avg_p50=_f(agg[4]), avg_band=_f(agg[5]), matched_actual=agg[6], mae=_f(agg[7]),
                               bias=_f(agg[8]), coverage_pct=_f(agg[9] * 100, 1) if agg[9] is not None else None)

    direction = (lambda c: c.asc()) if order == "asc" else (lambda c: c.desc())
    rows = (q.order_by(direction(PF.target_ts), direction(PF.issued_at), PriceNode.node_code)
            .offset((page - 1) * page_size).limit(page_size).all())
    return PriceForecastPage(items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size,
                             stats=stats)


@router.get("/{node_id}/{issued_at}/{target_ts}", response_model=PriceForecastOut)
def get_forecast(node_id: int, issued_at: datetime, target_ts: datetime, db: Session = Depends(get_db)):
    return _out(*_get(db, node_id, issued_at, target_ts))


@router.post("", response_model=PriceForecastOut, status_code=201)
def add_forecast(payload: PriceForecastCreate, db: Session = Depends(get_db)):
    """Add a forecast row; one already present for that node, vintage and target is refused (edit it instead)."""
    code = db.query(PriceNode.node_code).filter(PriceNode.node_id == payload.node_id).scalar()
    if code is None:
        raise HTTPException(status_code=422, detail=f"Price node {payload.node_id} does not exist")
    issued, target = _local(payload.issued_at), _local(payload.target_ts)
    if db.get(PF, (payload.node_id, issued, target)):
        raise HTTPException(status_code=409, detail=(f"{code} already has a forecast issued {issued.isoformat()} "
                                                     f"for {target.isoformat()}"))
    db.add(PF(**{**payload.model_dump(), "issued_at": issued, "target_ts": target}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc.orig).splitlines()[0])
    return _out(*_get(db, payload.node_id, issued, target))


@router.put("/{node_id}/{issued_at}/{target_ts}", response_model=PriceForecastOut)
def update_forecast(node_id: int, issued_at: datetime, target_ts: datetime, payload: PriceForecastUpdate,
                    db: Session = Depends(get_db)):
    """Edit the quantiles or model; node, vintage and target are the key (and fix the horizon)."""
    row, _, _ = _get(db, node_id, issued_at, target_ts)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return _out(*_get(db, node_id, issued_at, target_ts))


@router.delete("/{node_id}/{issued_at}/{target_ts}", status_code=204)
def delete_forecast(node_id: int, issued_at: datetime, target_ts: datetime, db: Session = Depends(get_db)):
    row, _, _ = _get(db, node_id, issued_at, target_ts)
    db.delete(row)
    db.commit()
    return None


@router.post("/bulk", response_model=BulkPriceForecastResult)
async def bulk_load(file: UploadFile = File(...), node_id: Optional[int] = Form(None), db: Session = Depends(get_db)):
    """Load a .csv / .xlsx of forecasts; existing (node, issued_at, target_ts) rows are updated. node_id applies to
    rows without a node_code (or to the whole file when it has no node_code column)."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        valid, errors, total, ignored, nodes = parse_price_forecast_file(db, file.filename or "upload", content,
                                                                         node_id)
    except PriceForecastImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    inserted, updated = upsert_price_forecasts(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, BulkPriceForecastRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    first, last = target_range(valid)
    return BulkPriceForecastResult(filename=file.filename or "upload", total_rows=total, valid_rows=len(valid),
                                   inserted=inserted, updated=updated, error_count=n_errors, errors=errors[:200],
                                   nodes=nodes, vintages=len({(r["node_id"], r["issued_at"]) for r in valid}),
                                   first_target=first, last_target=last)
