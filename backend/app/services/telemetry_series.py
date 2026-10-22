"""Chart series for the BMS telemetry graphs (system_telemetry)."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

BMS_SERIES = SeriesSpec(
    table="system_telemetry",
    id_column="system_id",
    columns=[
        SeriesColumn("soc_bms_pct", "avg"),
        SeriesColumn("soh_pct", "avg"),
        SeriesColumn("pack_voltage_v", "avg"),
        SeriesColumn("pack_current_a", "avg"),
        SeriesColumn("power_kw", "avg"),
        SeriesColumn("c_rate", "avg"),
        SeriesColumn("cell_v_avg_v", "avg"),
        SeriesColumn("cell_v_min_v", "min"),
        SeriesColumn("cell_v_max_v", "max"),
        SeriesColumn("cell_v_delta_mv", "max"),
        SeriesColumn("cell_temp_avg_c", "avg"),
        SeriesColumn("cell_temp_min_c", "min"),
        SeriesColumn("cell_temp_max_c", "max"),
        SeriesColumn("coolant_temp_c", "avg"),
        SeriesColumn("ambient_temp_c", "avg"),
        SeriesColumn("insulation_res_kohm", "avg"),
        SeriesColumn("avail_charge_kw", "avg"),
        SeriesColumn("avail_discharge_kw", "avg"),
        SeriesColumn("cum_charge_kwh", "max"),
        SeriesColumn("cum_discharge_kwh", "max"),
        SeriesColumn("charge_kwh_step", "step", source="cum_charge_kwh"),
        SeriesColumn("discharge_kwh_step", "step", source="cum_discharge_kwh"),
        SeriesColumn("equiv_full_cycles", "max"),
        SeriesColumn("measured_current_a", "avg"),
        SeriesColumn("current_sensor_offset_a", "avg"),
        SeriesColumn("soc_coulomb_pct", "avg"),
        SeriesColumn("soc_battery_telemetry_pct", "avg"),
        SeriesColumn("usable_capacity_ah", "avg"),
        SeriesColumn("coulombic_efficiency", "avg"),
        SeriesColumn("rest_duration_min", "max"),
        SeriesColumn("ocv_rested_v", "avg"),
    ],
    state_columns=["contactor_state", "at_rest"],
    state_exprs={"at_rest": "CASE WHEN at_rest THEN 'At rest' WHEN NOT at_rest THEN 'Active' END"},
)


def get_series(
    db: Session,
    system_id: int,
    start: Optional[datetime],
    end: Optional[datetime],
    max_points: int,
) -> dict:
    series = build_series(db, BMS_SERIES, system_id, start, end, max_points)
    states = series.pop("states")
    series["contactor_segments"] = states.get("contactor_state", [])
    series["rest_segments"] = states.get("at_rest", [])
    return series
