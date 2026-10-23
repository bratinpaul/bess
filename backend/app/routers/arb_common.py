"""Shared pieces of the arbitrage decision-table routers (Core -> Dispatch): the lookups endpoint the pages fill their
pickers from, plant-time helpers, code resolvers for bulk loads and the bulk-result builder."""
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.battery_system import BatterySystem
from app.models.arbitrage import OptimizationRun, PriceScenario
from app.models.as_price import AsProduct
from app.models.dam_price import PriceNode
from app.schemas.arbitrage import BulkResult, Lookups, Option, RowError, RunOption

PLANT_TZ = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/api/arbitrage", tags=["dispatch"])


def local(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=PLANT_TZ)


def in_days(q, col, start: Optional[date], end: Optional[date]):
    """Plant-time date range on a timestamptz column, end inclusive."""
    if start:
        q = q.filter(col >= datetime.combine(start, time(), PLANT_TZ))
    if end:
        q = q.filter(col < datetime.combine(end + timedelta(days=1), time(), PLANT_TZ))
    return q


def fmt(v, nd: int = 2, unit: str = "", sign: bool = False) -> Optional[str]:
    if v is None:
        return None
    f = float(v)
    s = f"{f:+,.{nd}f}" if sign else f"{f:,.{nd}f}"
    return f"{s} {unit}".strip()


def resolvers(db: Session) -> dict[str, dict[str, int]]:
    return {
        "system": {c: i for i, c in db.query(BatterySystem.battery_system_id, BatterySystem.system_name)},
        "node": {c: i for i, c in db.query(PriceNode.node_id, PriceNode.node_code)},
        "product": {c: i for i, c in db.query(AsProduct.product_id, AsProduct.product_code)},
    }


def system_code(db: Session, system_id: int) -> str:
    code = db.query(BatterySystem.system_name).filter(BatterySystem.battery_system_id == system_id).scalar()
    if code is None:
        raise HTTPException(status_code=422, detail=f"System {system_id} does not exist")
    return code


def commit_or_409(db: Session):
    """Commit; a constraint violation reaches the shared handler (bess_common/errors.py), which answers 409 / 422 with
    the constraint's catalog message - never the database text."""
    db.commit()


def sync_run_sequence(db: Session):
    """Runs can be loaded with explicit ids; keep the identity sequence after the highest one."""
    db.execute(text("SELECT setval(pg_get_serial_sequence('battery_master.optimization_run', 'run_id'), "
                    "GREATEST((SELECT max(run_id) FROM battery_master.optimization_run), 1))"))


def bulk_result(filename: str, total: int, valid: list[dict], inserted: int, updated: int, errors: list[RowError],
                ignored: list[str], warnings: Optional[list[str]] = None,
                span: tuple = (None, None)) -> BulkResult:
    n_errors = len(errors)
    if ignored:
        errors.insert(0, RowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    return BulkResult(filename=filename, total_rows=total, valid_rows=len(valid), inserted=inserted, updated=updated,
                      error_count=n_errors, errors=errors[:200], warnings=warnings or [], first_ts=span[0],
                      last_ts=span[1])


@router.get("/lookups", response_model=Lookups)
def lookups(db: Session = Depends(get_db)):
    """Systems, price nodes, AS products, optimizer runs, scenario vintages and the allowed enum values."""
    runs = (db.query(OptimizationRun, BatterySystem.system_name)
            .join(BatterySystem, BatterySystem.battery_system_id == OptimizationRun.system_id)
            .order_by(OptimizationRun.run_id.desc()).all())
    return Lookups(
        systems=[Option(id=i, code=c) for i, c in db.query(BatterySystem.battery_system_id, BatterySystem.system_name)
                 .order_by(BatterySystem.system_name)],
        nodes=[Option(id=i, code=c, label=n) for i, c, n in db.query(PriceNode.node_id, PriceNode.node_code,
                                                                     PriceNode.name).order_by(PriceNode.node_code)],
        products=[Option(id=i, code=c, label=n) for i, c, n in db.query(AsProduct.product_id, AsProduct.product_code,
                                                                        AsProduct.name).order_by(AsProduct.product_id)],
        runs=[RunOption(run_id=r.run_id, system_id=r.system_id, system_code=c, issued_at=r.issued_at,
                        horizon_start=r.horizon_start, horizon_end=r.horizon_end, resolution_min=r.resolution_min)
              for r, c in runs],
        scenario_vintages=[v for (v,) in db.query(PriceScenario.issued_at).distinct()
                           .order_by(PriceScenario.issued_at.desc())])
