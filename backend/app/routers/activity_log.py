"""Activity log viewer API (battery_ops.activity_log, written by bess_common.observability) - audit:read.

GET /api/admin/activity          filtered, newest first, paged; with counts by kind / outcome for the filtered range
GET /api/admin/activity/lookups  the services, kinds and operations present (filter options)
"""
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/api/admin/activity", tags=["activity-log"])
COLUMNS = """activity_id, ts, service, kind, event, outcome, request_id, user_email, role, method, path, status_code,
    duration_ms, operation, rows_total, rows_inserted, rows_updated, rows_rejected, ip, detail"""


@router.get("")
def list_activity(kind: Optional[Literal["REQUEST", "AUTH", "LOAD", "KPI", "TRAINING", "ERROR"]] = None,
                  outcome: Optional[Literal["success", "failed"]] = None, service: Optional[str] = None,
                  user: Optional[str] = None, request_id: Optional[str] = None, q: Optional[str] = None,
                  date_from: Optional[date] = None, date_to: Optional[date] = None,
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    where, params = ["true"], {}
    if kind:
        where.append("kind = :kind"); params["kind"] = kind
    if outcome:
        where.append("outcome = :outcome"); params["outcome"] = outcome
    if service:
        where.append("service = :service"); params["service"] = service
    if user:
        where.append("user_email ILIKE :user"); params["user"] = f"%{user.strip()}%"
    if request_id:
        where.append("request_id = :rid"); params["rid"] = request_id.strip()
    if q:
        where.append("(path ILIKE :q OR operation ILIKE :q OR event ILIKE :q OR detail::text ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if date_from:
        where.append("ts >= :d0"); params["d0"] = date_from
    if date_to:
        where.append("ts < :d1"); params["d1"] = date_to + timedelta(days=1)
    clause = " AND ".join(where)  # fixed fragments only; every value is a bound parameter
    total = db.execute(text(f"SELECT count(*) FROM battery_ops.activity_log WHERE {clause}"), params).scalar()
    rows = db.execute(text(f"""SELECT {COLUMNS} FROM battery_ops.activity_log WHERE {clause}
                               ORDER BY ts DESC, activity_id DESC LIMIT :lim OFFSET :off"""),
                      {**params, "lim": page_size, "off": (page - 1) * page_size}).mappings().all()
    by = db.execute(text(f"""SELECT kind, outcome, count(*) AS n FROM battery_ops.activity_log WHERE {clause}
                             GROUP BY kind, outcome"""), params).mappings().all()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size,
            "counts": [dict(r) for r in by]}


@router.get("/lookups")
def lookups(db: Session = Depends(get_db)):
    def distinct(col: str) -> list[str]:
        return [r[0] for r in db.execute(text(
            f"SELECT DISTINCT {col} FROM battery_ops.activity_log WHERE {col} IS NOT NULL ORDER BY 1"))]
    return {"services": distinct("service"), "kinds": ["REQUEST", "AUTH", "LOAD", "KPI", "TRAINING", "ERROR"],
            "operations": distinct("operation")}
