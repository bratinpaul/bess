from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

_DAILY_AGGREGATE_SQL = text(
    """
    SELECT
        bucket::date AS day,
        energy_kwh,
        peak_power_kw,
        max_heat_load_kw,
        avg_cop,
        max_return_temp_c,
        max_enclosure_temp_c,
        max_humidity_pct,
        avg_ambient_c,
        cooling_hours,
        free_cooling_hours,
        ROUND((cooling_hours / 24.0) * 100, 2) AS compressor_duty_cycle_pct,
        (cooling_hours + free_cooling_hours) AS cooling_time_hours,
        sample_count
    FROM hvac_telemetry_daily
    WHERE hvac_id = :hvac_id AND bucket::date >= :start_date AND bucket::date <= :end_date
    ORDER BY bucket
    """
)

_DATE_RANGE_SQL = text(
    """
    SELECT MIN(ts::date) AS min_date, MAX(ts::date) AS max_date
    FROM hvac_telemetry
    WHERE hvac_id = :hvac_id
    """
)

_LATEST_SQL = text(
    """
    SELECT hvac_id, hvac_code, ts, cooling_mode, coolant_supply_temp_c, coolant_return_temp_c,
           battery_heat_load_kw, hvac_power_kw, cop, enclosure_temp_c, alarm_level, alarm_flags
    FROM v_hvac_latest
    WHERE hvac_id = :hvac_id
    """
)


def get_hvac_daily_aggregates(db: Session, hvac_id: int, start_date: date, end_date: date) -> list[dict]:
    rows = db.execute(
        _DAILY_AGGREGATE_SQL, {"hvac_id": hvac_id, "start_date": start_date, "end_date": end_date}
    ).mappings().all()
    return [dict(row) for row in rows]


def get_hvac_telemetry_date_range(db: Session, hvac_id: int) -> dict:
    row = db.execute(_DATE_RANGE_SQL, {"hvac_id": hvac_id}).mappings().first()
    return dict(row) if row else {"min_date": None, "max_date": None}


def get_hvac_latest(db: Session, hvac_id: int) -> dict | None:
    row = db.execute(_LATEST_SQL, {"hvac_id": hvac_id}).mappings().first()
    return dict(row) if row else None
