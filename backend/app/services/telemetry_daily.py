from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_DAILY_AGGREGATE_SQL = text(
    """
    WITH daily AS (
        SELECT
            ts::date AS day,
            MIN(soc_bms_pct) AS min_soc,
            MAX(soc_bms_pct) AS max_soc,
            ROUND(AVG(soc_bms_pct), 2) AS avg_soc,
            MIN(pack_voltage_v) AS min_pack_voltage,
            MAX(pack_voltage_v) AS max_pack_voltage,
            MAX(power_kw) AS peak_charge_power,
            MIN(power_kw) AS peak_discharge_power,
            MAX(cell_temp_max_c) AS max_cell_temp,
            MAX(cell_v_delta_mv) AS max_cell_imbalance,
            (MAX(cum_charge_kwh) - MIN(cum_charge_kwh)) AS total_energy_charged,
            (MAX(cum_discharge_kwh) - MIN(cum_discharge_kwh)) AS total_energy_discharged,
            MAX(equiv_full_cycles) AS equiv_full_cycles,
            COUNT(*) FILTER (WHERE alarm_level IS NOT NULL AND alarm_level <> 0) AS alarm_samples,
            COUNT(*) AS sample_count,
            ROUND(AVG(ambient_temp_c), 2) AS avg_ambient_temp
        FROM system_telemetry
        WHERE system_id = :system_id AND ts::date >= :start_date AND ts::date <= :end_date
        GROUP BY ts::date
    ),
    last_row AS (
        SELECT DISTINCT ON (ts::date)
            ts::date AS day,
            soh_pct AS ending_soh
        FROM system_telemetry
        WHERE system_id = :system_id AND ts::date >= :start_date AND ts::date <= :end_date
        ORDER BY ts::date, ts DESC
    )
    SELECT d.*, l.ending_soh
    FROM daily d
    JOIN last_row l ON l.day = d.day
    ORDER BY d.day
    """
)

_DATE_RANGE_SQL = text(
    """
    SELECT MIN(ts::date) AS min_date, MAX(ts::date) AS max_date
    FROM system_telemetry
    WHERE system_id = :system_id
    """
)


def _round_trip_efficiency(charged: Optional[Decimal], discharged: Optional[Decimal]) -> Optional[Decimal]:
    if not charged or not discharged or charged == 0:
        return None
    return round((discharged / charged) * 100, 2)


def get_daily_aggregates(db: Session, system_id: int, start_date: date, end_date: date) -> list[dict]:
    rows = db.execute(
        _DAILY_AGGREGATE_SQL,
        {"system_id": str(system_id), "start_date": start_date, "end_date": end_date},
    ).mappings().all()

    results = []
    for row in rows:
        data = dict(row)
        data["round_trip_efficiency_pct"] = _round_trip_efficiency(
            data["total_energy_charged"], data["total_energy_discharged"]
        )
        results.append(data)
    return results


def get_telemetry_date_range(db: Session, system_id: int) -> dict:
    row = db.execute(_DATE_RANGE_SQL, {"system_id": str(system_id)}).mappings().first()
    return dict(row) if row else {"min_date": None, "max_date": None}
