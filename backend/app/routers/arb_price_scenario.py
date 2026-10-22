"""Price scenarios (battery_master.price_scenario): sampled price paths with weights for stochastic / robust dispatch,
per node, issue vintage, scenario and target hour. Each row shows the point forecast (P50) of the same vintage / hour
and the realized DAM price. The weights of one node / vintage / hour should sum to 1: bulk loads warn when they
don't, and the list counts such hours."""
from collections import defaultdict
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.arbitrage import PriceScenario
from app.models.dam_price import DamPrice, PriceForecast, PriceNode
from app.routers.arb_common import bulk_result, commit_or_409, fmt, in_days, local, resolvers
from app.schemas.arbitrage import BulkResult, Page, PriceScenarioCreate, PriceScenarioOut, PriceScenarioUpdate, Stat
from app.services.arbitrage_import import ArbitrageImportError, Col, num, parse_upload, ts_span, upsert, validate_rows

router = APIRouter(prefix="/api/price-scenarios", tags=["dispatch"])

PS = PriceScenario
KEY = ["node_id", "issued_at", "scenario_id", "target_ts"]
PROB_TOL = 0.01
COLS = [
    Col("node_id", ("node_code", "node"), "code", True, "node"),
    Col("issued_at", ("issued_at",), "ts", True),
    Col("scenario_id", ("scenario_id", "scenario"), "int", True),
    Col("target_ts", ("target_ts", "target"), "ts", True),
    Col("price_mwh", ("price_mwh", "price"), "num", True),
    Col("probability", ("probability", "weight")),
]


def _base(db: Session):
    return (db.query(PS, PriceNode.node_code, PriceForecast.p50_mwh, DamPrice.price_mwh)
            .join(PriceNode, PriceNode.node_id == PS.node_id)
            .outerjoin(PriceForecast, and_(PriceForecast.node_id == PS.node_id, PriceForecast.issued_at == PS.issued_at,
                                           PriceForecast.target_ts == PS.target_ts))
            .outerjoin(DamPrice, and_(DamPrice.node_id == PS.node_id, DamPrice.delivery_start == PS.target_ts)))


def _out(s: PS, code, p50, actual) -> PriceScenarioOut:
    return PriceScenarioOut(node_id=s.node_id, node_code=code, issued_at=s.issued_at, scenario_id=s.scenario_id,
                            target_ts=s.target_ts, price_mwh=float(s.price_mwh), probability=num(s.probability),
                            horizon_h=round((s.target_ts - s.issued_at).total_seconds() / 3600, 2),
                            forecast_p50=num(p50), actual_mwh=num(actual))


def _get(db: Session, node_id: int, issued_at: datetime, scenario_id: int, target_ts: datetime):
    found = _base(db).filter(PS.node_id == node_id, PS.issued_at == local(issued_at), PS.scenario_id == scenario_id,
                             PS.target_ts == local(target_ts)).first()
    if not found:
        raise HTTPException(status_code=404, detail=f"No scenario {scenario_id} for node {node_id} issued "
                                                    f"{issued_at.isoformat()} at {target_ts.isoformat()}")
    return found


@router.get("", response_model=Page[PriceScenarioOut])
def list_scenarios(node_id: Optional[int] = None, issued_at: Optional[datetime] = None,
                   scenario_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None,
                   order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
                   page_size: int = Query(100, ge=1, le=5000), db: Session = Depends(get_db)):
    """Scenario rows by target hour (plant-time date range, end inclusive), optionally one vintage / scenario."""
    q = _base(db)
    if node_id is not None:
        q = q.filter(PS.node_id == node_id)
    if issued_at is not None:
        q = q.filter(PS.issued_at == local(issued_at))
    if scenario_id is not None:
        q = q.filter(PS.scenario_id == scenario_id)
    q = in_days(q, PS.target_ts, start, end)
    agg = q.with_entities(func.count(), func.count(func.distinct(PS.issued_at)), func.max(PS.scenario_id),
                          func.avg(PS.price_mwh), func.min(PS.price_mwh), func.max(PS.price_mwh),
                          func.count(func.distinct(func.concat(PS.node_id, "|", PS.issued_at, "|", PS.target_ts)))
                          ).one()
    # weight sums per node / vintage / hour (over the filtered hours, all scenarios of each hour)
    hours = q.with_entities(PS.node_id, PS.issued_at, PS.target_ts).distinct().subquery()
    sums = (db.query(func.sum(PS.probability).label("s"))
            .join(hours, and_(hours.c.node_id == PS.node_id, hours.c.issued_at == PS.issued_at,
                              hours.c.target_ts == PS.target_ts))
            .group_by(PS.node_id, PS.issued_at, PS.target_ts).subquery())
    bad_hours = db.query(func.count()).select_from(sums).filter(func.abs(sums.c.s - 1) > PROB_TOL).scalar()
    stats = [Stat(label=f"Rows · {agg[1]} vintage(s)", value=str(agg[0])),
             Stat(label="Hours", value=str(agg[6])),
             Stat(label="Scenarios per hour (max id)", value=str(agg[2]) if agg[2] else None),
             Stat(label="Mean scenario price", value=fmt(agg[3], 2, "USD/MWh")),
             Stat(label="Scenario price range", value=f"{fmt(agg[4], 2)} – {fmt(agg[5], 2)}" if agg[4] is not None else None),
             Stat(label="Hours whose weights don't sum to 1", value=str(bad_hours), warn=bad_hours > 0)]
    direction = (lambda c: c.asc()) if order == "asc" else (lambda c: c.desc())
    rows = (q.order_by(direction(PS.target_ts), direction(PS.issued_at), PS.scenario_id)
            .offset((page - 1) * page_size).limit(page_size).all())
    return Page[PriceScenarioOut](items=[_out(*r) for r in rows], total=agg[0], page=page, page_size=page_size,
                                  stats=stats)


@router.get("/{node_id}/{issued_at}/{scenario_id}/{target_ts}", response_model=PriceScenarioOut)
def get_scenario(node_id: int, issued_at: datetime, scenario_id: int, target_ts: datetime,
                 db: Session = Depends(get_db)):
    return _out(*_get(db, node_id, issued_at, scenario_id, target_ts))


@router.post("", response_model=PriceScenarioOut, status_code=201)
def add_scenario(payload: PriceScenarioCreate, db: Session = Depends(get_db)):
    if not db.get(PriceNode, payload.node_id):
        raise HTTPException(status_code=422, detail=f"Price node {payload.node_id} does not exist")
    issued, target = local(payload.issued_at), local(payload.target_ts)
    if db.get(PS, (payload.node_id, issued, payload.scenario_id, target)):
        raise HTTPException(status_code=409, detail=f"Scenario {payload.scenario_id} already exists for that vintage "
                                                    "and hour")
    db.add(PS(**{**payload.model_dump(), "issued_at": issued, "target_ts": target}))
    commit_or_409(db)
    return _out(*_get(db, payload.node_id, issued, payload.scenario_id, target))


@router.put("/{node_id}/{issued_at}/{scenario_id}/{target_ts}", response_model=PriceScenarioOut)
def update_scenario(node_id: int, issued_at: datetime, scenario_id: int, target_ts: datetime,
                    payload: PriceScenarioUpdate, db: Session = Depends(get_db)):
    row = _get(db, node_id, issued_at, scenario_id, target_ts)[0]
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    commit_or_409(db)
    return _out(*_get(db, node_id, issued_at, scenario_id, target_ts))


@router.delete("/{node_id}/{issued_at}/{scenario_id}/{target_ts}", status_code=204)
def delete_scenario(node_id: int, issued_at: datetime, scenario_id: int, target_ts: datetime,
                    db: Session = Depends(get_db)):
    db.delete(_get(db, node_id, issued_at, scenario_id, target_ts)[0])
    db.commit()
    return None


@router.post("/bulk", response_model=BulkResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load price_scenario.csv / .xlsx; existing (node, vintage, scenario, hour) rows are updated. Warns about hours
    whose weights in the file don't sum to 1."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        records, errors, total, ignored = parse_upload(file.filename or "upload", content, COLS, resolvers(db))
    except ArbitrageImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    valid = validate_rows(records, PriceScenarioCreate, errors,
                          key=lambda m: (m.node_id, local(m.issued_at), m.scenario_id, local(m.target_ts)))
    for r in valid:
        r["issued_at"], r["target_ts"] = local(r["issued_at"]), local(r["target_ts"])
    sums = defaultdict(float)
    weighted = set()
    for r in valid:
        k = (r["node_id"], r["issued_at"], r["target_ts"])
        if r["probability"] is not None:
            sums[k] += r["probability"]
            weighted.add(k)
    off = sorted(k for k in weighted if abs(sums[k] - 1) > PROB_TOL)
    warnings = ([f"{len(off)} hour(s) have weights that don't sum to 1, e.g. target "
                 f"{off[0][2]:%Y-%m-%d %H:%M} (vintage {off[0][1]:%Y-%m-%d %H:%M}) sums to {sums[off[0]]:.4f}"]
                if off else [])
    inserted, updated = upsert(db, PS.__table__, valid, KEY, ["price_mwh", "probability"])
    db.commit()
    return bulk_result(file.filename or "upload", total, valid, inserted, updated, errors, ignored, warnings,
                       ts_span(valid, "target_ts"))
