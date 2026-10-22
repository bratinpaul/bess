"""Module telemetry summary for the Daily Module Summary page.

Mirrors the Summary / ByModule / Daily sheets of BESS_ModuleTelemetry_30d_5min.xlsx, computed
from module_telemetry for a date range:
  imbalance (mV)           = (cell_v_max_v - cell_v_min_v) * 1000
  balancing duty (%)       = share of samples with balancing_active
  balancing module-hours   = balancing samples * sample interval
"""
import re
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

# optional scope: only modules in one pack and/or one battery system (NULL = no filter)
_SCOPE = """
    module_id IN (
        SELECT m.module_id
        FROM battery_module m
        JOIN battery_pack p ON p.pack_id = m.pack_id
        JOIN battery_container c ON c.container_id = p.container_id
        WHERE (CAST(:pack_id AS bigint) IS NULL OR m.pack_id = CAST(:pack_id AS bigint))
          AND (CAST(:system_id AS bigint) IS NULL OR c.battery_system_id = CAST(:system_id AS bigint))
    )
"""

_RANGE_SQL = text(
    "SELECT MIN(ts)::date AS first_day, MAX(ts)::date AS last_day FROM module_telemetry WHERE " + _SCOPE
)

# median gap between consecutive samples of the same module, in hours
_INTERVAL_SQL = text(
    """
    SELECT EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY gap)) / 3600.0
    FROM (
        SELECT ts - LAG(ts) OVER (PARTITION BY module_id ORDER BY ts) AS gap
        FROM module_telemetry
        WHERE ts::date BETWEEN :start_date AND :end_date AND """ + _SCOPE + """
    ) g
    WHERE gap IS NOT NULL
    """
)

_BASE = """
    WITH t AS (
        SELECT module_id, ts, ts::date AS day, cell_v_avg_v, cell_v_min_v, cell_v_max_v,
               (cell_v_max_v - cell_v_min_v) * 1000 AS imbalance_mv, cell_temp_max_c, balancing_active
        FROM module_telemetry
        WHERE ts::date BETWEEN :start_date AND :end_date AND """ + _SCOPE + """
    )
"""

_TOTALS_SQL = text(
    _BASE
    + """
    SELECT COUNT(DISTINCT module_id) AS modules,
           COUNT(*) AS samples,
           MIN(cell_v_min_v) AS cell_v_min,
           MAX(cell_v_max_v) AS cell_v_max,
           AVG(imbalance_mv) AS mean_imbalance_mv,
           MAX(imbalance_mv) AS max_imbalance_mv,
           MAX(cell_temp_max_c) AS max_temp_c,
           COUNT(*) FILTER (WHERE balancing_active) AS balancing_samples,
           COUNT(balancing_active) AS balancing_reported
    FROM t
    """
)

_BY_MODULE_SQL = text(
    _BASE
    + """
    SELECT t.module_id, m.serial_number,
           AVG(cell_v_avg_v) AS avg_cell_v,
           MIN(cell_v_min_v) AS min_cell_v,
           MAX(cell_v_max_v) AS max_cell_v,
           AVG(imbalance_mv) AS mean_imbalance_mv,
           MAX(imbalance_mv) AS max_imbalance_mv,
           MAX(cell_temp_max_c) AS max_temp_c,
           COUNT(*) FILTER (WHERE balancing_active) AS balancing_samples,
           COUNT(*) AS samples
    FROM t JOIN battery_module m ON m.module_id = t.module_id
    GROUP BY t.module_id, m.serial_number
    """
)

_DAILY_SQL = text(
    _BASE
    + """
    SELECT day,
           MAX(imbalance_mv) AS max_imbalance_mv,
           AVG(imbalance_mv) AS avg_imbalance_mv,
           MAX(cell_temp_max_c) AS max_temp_c,
           COUNT(*) FILTER (WHERE balancing_active) AS balancing_samples,
           COUNT(*) AS samples
    FROM t
    GROUP BY day
    ORDER BY day
    """
)


def _f(value) -> Optional[float]:
    return None if value is None else float(value)


def module_label(serial: Optional[str], module_id: int) -> str:
    """Short label like the workbook's MOD-07, from the module number at the end of the serial."""
    m = re.search(r"(\d+)\s*$", serial or "")
    return f"MOD-{int(m.group(1)):02d}" if m else (serial or f"Module {module_id}")


def _module_number(serial: Optional[str]) -> int:
    m = re.search(r"(\d+)\s*$", serial or "")
    return int(m.group(1)) if m else 10**6


def get_date_range(db: Session, pack_id: Optional[int] = None, system_id: Optional[int] = None) -> dict:
    row = db.execute(_RANGE_SQL, {"pack_id": pack_id, "system_id": system_id}).one()
    return {"first_date": row.first_day, "last_date": row.last_day}


def get_summary(
    db: Session,
    start_date: date,
    end_date: date,
    pack_id: Optional[int] = None,
    system_id: Optional[int] = None,
) -> dict:
    params = {"start_date": start_date, "end_date": end_date, "pack_id": pack_id, "system_id": system_id}
    interval_h = db.execute(_INTERVAL_SQL, params).scalar()
    interval_h = float(interval_h) if interval_h else 5 / 60  # the files are 5-minute data

    totals = db.execute(_TOTALS_SQL, params).mappings().one()
    modules = sorted(
        db.execute(_BY_MODULE_SQL, params).mappings().all(), key=lambda r: _module_number(r["serial_number"])
    )
    daily = db.execute(_DAILY_SQL, params).mappings().all()

    by_module = [
        {
            "module_id": r["module_id"],
            "serial_number": r["serial_number"],
            "label": module_label(r["serial_number"], r["module_id"]),
            "avg_cell_v": _f(r["avg_cell_v"]),
            "min_cell_v": _f(r["min_cell_v"]),
            "max_cell_v": _f(r["max_cell_v"]),
            "mean_imbalance_mv": _f(r["mean_imbalance_mv"]),
            "max_imbalance_mv": _f(r["max_imbalance_mv"]),
            "max_temp_c": _f(r["max_temp_c"]),
            "balancing_hours": r["balancing_samples"] * interval_h,
            "samples": r["samples"],
        }
        for r in modules
    ]

    worst = max(
        (m for m in by_module if m["max_imbalance_mv"] is not None),
        key=lambda m: m["max_imbalance_mv"],
        default=None,
    )
    n_modules = totals["modules"] or 0
    kpis = {
        "modules": n_modules,
        "samples_per_module": round(totals["samples"] / n_modules) if n_modules else None,
        "cell_v_min": _f(totals["cell_v_min"]),
        "cell_v_max": _f(totals["cell_v_max"]),
        "mean_imbalance_mv": _f(totals["mean_imbalance_mv"]),
        "max_imbalance_mv": _f(totals["max_imbalance_mv"]),
        "max_temp_c": _f(totals["max_temp_c"]),
        "balancing_duty_pct": (
            100.0 * totals["balancing_samples"] / totals["balancing_reported"] if totals["balancing_reported"] else None
        ),
        "balancing_module_hours": totals["balancing_samples"] * interval_h if n_modules else None,
        "highest_imbalance_module": worst["label"] if worst else None,
        "highest_imbalance_mv": worst["max_imbalance_mv"] if worst else None,
    }

    return {
        "start_date": start_date,
        "end_date": end_date,
        "sample_interval_minutes": round(interval_h * 60, 2),
        "kpis": kpis,
        "by_module": by_module,
        "daily": [
            {
                "day": r["day"],
                "max_imbalance_mv": _f(r["max_imbalance_mv"]),
                "avg_imbalance_mv": _f(r["avg_imbalance_mv"]),
                "max_temp_c": _f(r["max_temp_c"]),
                "balancing_module_hours": r["balancing_samples"] * interval_h,
                "samples": r["samples"],
            }
            for r in daily
        ],
    }
