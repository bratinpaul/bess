from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_BMS_PERIOD_SQL = text(
    """
    SELECT
        MIN(soc_bms_pct) AS min_soc,
        MAX(soc_bms_pct) AS max_soc,
        ROUND(AVG(soc_bms_pct), 2) AS avg_soc,
        MAX(cell_temp_max_c) AS max_cell_temp,
        MAX(power_kw) AS peak_charge_power,
        MIN(power_kw) AS peak_discharge_power,
        (MAX(cum_charge_kwh) - MIN(cum_charge_kwh)) AS total_energy_charged,
        (MAX(cum_discharge_kwh) - MIN(cum_discharge_kwh)) AS total_energy_discharged,
        (MAX(equiv_full_cycles) - MIN(equiv_full_cycles)) AS equiv_full_cycles_delta,
        COUNT(*) FILTER (WHERE alarm_level IS NOT NULL AND alarm_level <> 0) AS alarm_samples,
        COUNT(*) AS sample_count
    FROM system_telemetry
    WHERE system_id = :system_id AND ts::date >= :start_date AND ts::date <= :end_date
    """
)

_BMS_SOH_AT_START_SQL = text(
    """
    SELECT soh_pct
    FROM system_telemetry
    WHERE system_id = :system_id AND ts::date >= :start_date AND ts::date <= :end_date
    ORDER BY ts ASC
    LIMIT 1
    """
)

_BMS_LATEST_SQL = text(
    """
    SELECT soc_bms_pct AS soc_pct, soh_pct, power_kw, mode_code, contactor_state, alarm_level, ts
    FROM system_telemetry
    WHERE system_id = :system_id
    ORDER BY ts DESC
    LIMIT 1
    """
)

_PCS_PERIOD_SQL = text(
    """
    WITH per_pcs AS (
        SELECT
            pcs_id,
            MAX(ac_active_power_kw) AS peak_charge,
            MIN(ac_active_power_kw) AS peak_discharge,
            MIN(power_factor) AS min_pf,
            AVG(efficiency_pct) AS avg_eff,
            MAX(igbt_temp_c) AS max_igbt,
            (MAX(ac_energy_import_kwh) - MIN(ac_energy_import_kwh)) AS imported,
            (MAX(ac_energy_export_kwh) - MIN(ac_energy_export_kwh)) AS exported,
            COUNT(*) FILTER (WHERE alarm_level IS NOT NULL AND alarm_level > 0) AS alarms,
            COUNT(*) AS samples
        FROM pcs_telemetry
        WHERE pcs_id = ANY(:pcs_ids) AND ts::date >= :start_date AND ts::date <= :end_date
        GROUP BY pcs_id
    )
    SELECT
        MAX(peak_charge) AS peak_charge_power_ac,
        MIN(peak_discharge) AS peak_discharge_power_ac,
        MIN(min_pf) AS min_power_factor,
        ROUND(AVG(avg_eff), 2) AS avg_efficiency,
        MAX(max_igbt) AS max_igbt_temp,
        SUM(imported) AS total_energy_imported,
        SUM(exported) AS total_energy_exported,
        SUM(alarms) AS alarm_samples,
        SUM(samples) AS sample_count
    FROM per_pcs
    """
)

_PCS_LATEST_SQL = text(
    """
    SELECT pt.ac_active_power_kw, pt.mode_code, pt.breaker_state, pt.alarm_level, pt.ts, p.pcs_code
    FROM pcs_telemetry pt
    JOIN pcs p ON p.pcs_id = pt.pcs_id
    WHERE pt.pcs_id = ANY(:pcs_ids)
    ORDER BY pt.ts DESC
    LIMIT 1
    """
)


def _round_trip(numerator: Optional[Decimal], denominator: Optional[Decimal]) -> Optional[Decimal]:
    if not numerator or not denominator or denominator == 0:
        return None
    return round((numerator / denominator) * 100, 2)


def get_bms_period_summary(db: Session, system_id: int, start_date: date, end_date: date) -> dict:
    row = db.execute(
        _BMS_PERIOD_SQL, {"system_id": str(system_id), "start_date": start_date, "end_date": end_date}
    ).mappings().first()
    data = dict(row) if row else {}
    data["round_trip_efficiency_pct"] = _round_trip(
        data.get("total_energy_discharged"), data.get("total_energy_charged")
    )
    soh_row = db.execute(
        _BMS_SOH_AT_START_SQL, {"system_id": str(system_id), "start_date": start_date, "end_date": end_date}
    ).mappings().first()
    data["soh_at_start"] = soh_row["soh_pct"] if soh_row else None
    return data


def get_latest_bms_reading(db: Session, system_id: int) -> Optional[dict]:
    row = db.execute(_BMS_LATEST_SQL, {"system_id": str(system_id)}).mappings().first()
    return dict(row) if row else None


def get_pcs_period_summary(db: Session, pcs_ids: list[int], start_date: date, end_date: date) -> dict:
    if not pcs_ids:
        return {}
    row = db.execute(
        _PCS_PERIOD_SQL, {"pcs_ids": pcs_ids, "start_date": start_date, "end_date": end_date}
    ).mappings().first()
    data = dict(row) if row else {}
    data["ac_ac_round_trip_eff_pct"] = _round_trip(
        data.get("total_energy_exported"), data.get("total_energy_imported")
    )
    return data


def get_latest_pcs_reading(db: Session, pcs_ids: list[int]) -> Optional[dict]:
    if not pcs_ids:
        return None
    row = db.execute(_PCS_LATEST_SQL, {"pcs_ids": pcs_ids}).mappings().first()
    return dict(row) if row else None
