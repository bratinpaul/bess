"""Chart series for the EMS telemetry graphs (ems_telemetry)."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

EMS_SERIES = SeriesSpec(
    table="ems_telemetry",
    id_column="ems_id",
    columns=[
        SeriesColumn("p_setpoint_kw", "avg"),
        SeriesColumn("poi_active_power_kw", "avg"),
        SeriesColumn("tracking_error_kw", "avg"),
        SeriesColumn("poi_reactive_power_kvar", "avg"),
        SeriesColumn("plant_soc_pct", "avg"),
        SeriesColumn("target_soc_pct", "avg"),
        SeriesColumn("avail_charge_kw", "avg"),
        SeriesColumn("avail_discharge_kw", "avg"),
        SeriesColumn("avail_charge_energy_kwh", "avg"),
        SeriesColumn("avail_discharge_energy_kwh", "avg"),
        SeriesColumn("market_price_mwh", "avg"),
        # revenue falls while buying energy, so the per-interval change is signed
        SeriesColumn("revenue_usd_step", "delta", source="revenue_cum_usd"),
        SeriesColumn("grid_frequency_hz", "avg"),
        SeriesColumn("agc_signal", "avg"),
        SeriesColumn("poi_voltage_kv", "avg"),
        SeriesColumn("cum_import_kwh", "max"),
        SeriesColumn("cum_export_kwh", "max"),
        SeriesColumn("import_kwh_step", "step", source="cum_import_kwh"),
        SeriesColumn("export_kwh_step", "step", source="cum_export_kwh"),
        SeriesColumn("aux_load_kw", "avg"),
        SeriesColumn("aux_load_pct", "avg"),
    ],
    state_columns=["dispatch_mode", "grid_service"],
)


def get_ems_series(
    db: Session,
    ems_id: int,
    start: Optional[datetime],
    end: Optional[datetime],
    max_points: int,
) -> dict:
    return build_series(db, EMS_SERIES, ems_id, start, end, max_points)
