from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.operations_summary import (
    get_bms_period_summary,
    get_latest_bms_reading,
    get_latest_pcs_reading,
    get_pcs_period_summary,
)
from app.services.telemetry_daily import get_telemetry_date_range

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/overview", response_model=schemas.OperationsOverview)
def operations_overview(system_id: int, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    system = db.get(models.BatterySystem, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="Battery system not found")

    site = db.get(models.Site, system.site_id)
    pcs_units = db.query(models.Pcs).filter(models.Pcs.system_id == system_id).all()
    pcs_ids = [p.pcs_id for p in pcs_units]

    date_range = get_telemetry_date_range(db, system_id)
    end_date = date_range.get("max_date")
    if not end_date:
        raise HTTPException(status_code=404, detail="No BMS telemetry data for this system")
    start_date = end_date - timedelta(days=days - 1)
    if date_range.get("min_date") and start_date < date_range["min_date"]:
        start_date = date_range["min_date"]

    bms_period = get_bms_period_summary(db, system_id, start_date, end_date)
    pcs_period = get_pcs_period_summary(db, pcs_ids, start_date, end_date)
    bms_latest = get_latest_bms_reading(db, system_id) or {}
    pcs_latest = get_latest_pcs_reading(db, pcs_ids) or {}

    bms_samples = bms_period.get("sample_count") or 0
    bms_alarms = bms_period.get("alarm_samples") or 0
    availability_pct = round(100 * (bms_samples - bms_alarms) / bms_samples, 2) if bms_samples else None

    charged = bms_period.get("total_energy_charged")
    discharged = bms_period.get("total_energy_discharged")
    efc_delta = bms_period.get("equiv_full_cycles_delta")
    period_days = (end_date - start_date).days + 1

    period = schemas.PeriodPerformance(
        start_date=start_date,
        end_date=end_date,
        days=period_days,
        avg_soc=bms_period.get("avg_soc"),
        min_soc=bms_period.get("min_soc"),
        max_soc=bms_period.get("max_soc"),
        soh_at_start=bms_period.get("soh_at_start"),
        energy_discharged_mwh=(discharged / 1000) if discharged is not None else None,
        energy_charged_mwh=(charged / 1000) if charged is not None else None,
        energy_throughput_mwh=(
            (charged + discharged) / 1000 if charged is not None and discharged is not None else None
        ),
        dc_round_trip_eff_pct=bms_period.get("round_trip_efficiency_pct"),
        ac_round_trip_eff_pct=pcs_period.get("ac_ac_round_trip_eff_pct"),
        equiv_full_cycles=efc_delta,
        cycles_per_day=(round(efc_delta / period_days, 3)) if efc_delta is not None else None,
        peak_charge_power_ac_kw=pcs_period.get("peak_charge_power_ac"),
        peak_discharge_power_ac_kw=pcs_period.get("peak_discharge_power_ac"),
        avg_conversion_eff_pct=pcs_period.get("avg_efficiency"),
        min_power_factor=pcs_period.get("min_power_factor"),
        max_cell_temp_c=bms_period.get("max_cell_temp"),
        max_igbt_temp_c=pcs_period.get("max_igbt_temp"),
        availability_pct=availability_pct,
        bms_alarm_samples=bms_alarms,
        pcs_alarm_samples=pcs_period.get("alarm_samples") or 0,
        bms_sample_count=bms_samples,
        pcs_sample_count=pcs_period.get("sample_count") or 0,
    )

    latest = schemas.LatestReading(
        ts=bms_latest.get("ts"),
        soc_pct=bms_latest.get("soc_pct"),
        soh_pct=bms_latest.get("soh_pct"),
        power_kw=pcs_latest.get("ac_active_power_kw"),
        mode_code=pcs_latest.get("mode_code"),
        bms_mode_code=bms_latest.get("mode_code"),
        contactor_state=bms_latest.get("contactor_state"),
        breaker_state=pcs_latest.get("breaker_state"),
        bms_alarm_level=bms_latest.get("alarm_level"),
        pcs_alarm_level=pcs_latest.get("alarm_level"),
    )

    return schemas.OperationsOverview(
        system_id=system_id,
        system_name=system.system_name,
        site_name=site.site_name if site else None,
        chemistry_code=system.chemistry_code,
        rated_power_mw=system.rated_power_mw,
        rated_energy_mwh=system.rated_energy_mwh,
        pcs_codes=[p.pcs_code for p in pcs_units],
        latest=latest,
        period=period,
    )
