from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_DAILY_AGGREGATE_SQL = text(
    """
    SELECT
        ts::date AS day,
        MAX(ac_active_power_kw) AS peak_charge_power_ac,
        MIN(ac_active_power_kw) AS peak_discharge_power_ac,
        MAX(ac_apparent_power_kva) AS peak_apparent_power,
        MIN(power_factor) AS min_power_factor,
        MAX(ac_reactive_power_kvar) AS max_reactive_power,
        MIN(ac_frequency_hz) FILTER (WHERE breaker_state = 'CLOSED') AS min_ac_frequency_closed,
        MAX(ac_frequency_hz) FILTER (WHERE breaker_state = 'CLOSED') AS max_ac_frequency,
        ROUND(AVG(efficiency_pct), 2) AS avg_efficiency,
        MAX(igbt_temp_c) AS max_igbt_temp,
        (MAX(ac_energy_import_kwh) - MIN(ac_energy_import_kwh)) AS total_energy_imported,
        (MAX(ac_energy_export_kwh) - MIN(ac_energy_export_kwh)) AS total_energy_exported,
        COUNT(*) FILTER (WHERE alarm_level IS NOT NULL AND alarm_level > 0) AS alarm_samples,
        COUNT(*) FILTER (WHERE grid_service = 'VOLT_VAR') AS volt_var_intervals,
        COUNT(*) FILTER (WHERE grid_service = 'FREQ_WATT') AS freq_watt_intervals,
        COUNT(*) AS sample_count
    FROM pcs_telemetry
    WHERE pcs_id = :pcs_id AND ts::date >= :start_date AND ts::date <= :end_date
    GROUP BY ts::date
    ORDER BY ts::date
    """
)

_DATE_RANGE_SQL = text(
    """
    SELECT MIN(ts::date) AS min_date, MAX(ts::date) AS max_date
    FROM pcs_telemetry
    WHERE pcs_id = :pcs_id
    """
)


def _round_trip_efficiency(imported: Optional[Decimal], exported: Optional[Decimal]) -> Optional[Decimal]:
    if not imported or not exported or imported == 0:
        return None
    return round((exported / imported) * 100, 2)


def get_pcs_daily_aggregates(db: Session, pcs_id: int, start_date: date, end_date: date) -> list[dict]:
    rows = db.execute(
        _DAILY_AGGREGATE_SQL,
        {"pcs_id": pcs_id, "start_date": start_date, "end_date": end_date},
    ).mappings().all()

    results = []
    for row in rows:
        data = dict(row)
        data["ac_ac_round_trip_eff_pct"] = _round_trip_efficiency(
            data["total_energy_imported"], data["total_energy_exported"]
        )
        results.append(data)
    return results


def get_pcs_telemetry_date_range(db: Session, pcs_id: int) -> dict:
    row = db.execute(_DATE_RANGE_SQL, {"pcs_id": pcs_id}).mappings().first()
    return dict(row) if row else {"min_date": None, "max_date": None}
