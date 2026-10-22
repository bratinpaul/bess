"""Chart series for the PCS telemetry graphs (pcs_telemetry)."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

# with the breaker open the AC side is not measured and the meter reports 0
AC_NOT_MEASURED = "breaker_state = 'OPEN'"

PCS_SERIES = SeriesSpec(
    table="pcs_telemetry",
    id_column="pcs_id",
    columns=[
        SeriesColumn("ac_voltage_ab_v", "avg", null_when=AC_NOT_MEASURED),
        SeriesColumn("ac_voltage_bc_v", "avg", null_when=AC_NOT_MEASURED),
        SeriesColumn("ac_voltage_ca_v", "avg", null_when=AC_NOT_MEASURED),
        SeriesColumn("dc_voltage_v", "avg"),
        SeriesColumn("ac_current_a_a", "avg"),
        SeriesColumn("ac_current_b_a", "avg"),
        SeriesColumn("ac_current_c_a", "avg"),
        SeriesColumn("dc_current_a", "avg"),
        SeriesColumn("ac_frequency_hz", "avg", null_when=AC_NOT_MEASURED),
        # |PF| per reading: the sign follows reactive power, which hovers around zero, so a signed
        # line flips between +1 and -1. Worst (lowest) value per bucket for the min-PF limit check.
        SeriesColumn("power_factor_abs", "min", source="ABS(power_factor)"),
        SeriesColumn("ac_active_power_kw", "avg"),
        SeriesColumn("ac_reactive_power_kvar", "avg"),
        SeriesColumn("ac_apparent_power_kva", "avg"),
        SeriesColumn("dc_power_kw", "avg"),
        SeriesColumn("avail_charge_kw", "avg"),
        SeriesColumn("avail_discharge_kw", "avg"),
        SeriesColumn("thd_voltage_pct", "avg"),
        SeriesColumn("thd_current_pct", "avg"),
        SeriesColumn("efficiency_pct", "avg"),
        # the worst case matters when comparing against the IGBT warning limit
        SeriesColumn("igbt_temp_c", "max"),
        SeriesColumn("heatsink_temp_c", "avg"),
        SeriesColumn("inlet_coolant_temp_c", "avg"),
        SeriesColumn("ambient_temp_c", "avg"),
        SeriesColumn("ac_energy_import_kwh", "max"),
        SeriesColumn("ac_energy_export_kwh", "max"),
        SeriesColumn("import_kwh_step", "step", source="ac_energy_import_kwh"),
        SeriesColumn("export_kwh_step", "step", source="ac_energy_export_kwh"),
    ],
    state_columns=["breaker_state", "mode_code", "grid_service"],
)


def get_pcs_series(
    db: Session,
    pcs_id: int,
    start: Optional[datetime],
    end: Optional[datetime],
    max_points: int,
) -> dict:
    return build_series(db, PCS_SERIES, pcs_id, start, end, max_points)
