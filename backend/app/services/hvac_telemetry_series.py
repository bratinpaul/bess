"""Chart series for the HVAC telemetry graphs (hvac_telemetry)."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

HVAC_SERIES = SeriesSpec(
    table="hvac_telemetry",
    id_column="hvac_id",
    columns=[
        SeriesColumn("coolant_supply_temp_c", "avg"),
        SeriesColumn("coolant_return_temp_c", "avg"),
        SeriesColumn("coolant_delta_t_c", "avg"),
        SeriesColumn("coolant_flow_lpm", "avg"),
        SeriesColumn("enclosure_temp_c", "avg"),
        SeriesColumn("ambient_temp_c", "avg"),
        SeriesColumn("enclosure_humidity_pct", "avg"),
        SeriesColumn("battery_heat_load_kw", "avg"),
        SeriesColumn("cooling_capacity_kw", "avg"),
        SeriesColumn("heat_rejected_kw", "avg"),
        SeriesColumn("hvac_power_kw", "avg"),
        SeriesColumn("cop", "avg"),
        SeriesColumn("compressor_speed_pct", "avg"),
        SeriesColumn("condenser_fan_pct", "avg"),
        SeriesColumn("units_running", "max"),
        SeriesColumn("refrig_suction_bar", "avg"),
        SeriesColumn("refrig_discharge_bar", "avg"),
        SeriesColumn("filter_dp_pa", "avg"),
        SeriesColumn("cum_energy_kwh", "max"),
        SeriesColumn("energy_kwh_step", "step", source="cum_energy_kwh"),
        SeriesColumn("compressor_runtime_h", "max"),
    ],
    state_columns=["cooling_mode"],
)


def get_hvac_series(
    db: Session,
    hvac_id: int,
    start: Optional[datetime],
    end: Optional[datetime],
    max_points: int,
) -> dict:
    return build_series(db, HVAC_SERIES, hvac_id, start, end, max_points)
