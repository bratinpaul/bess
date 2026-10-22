"""Chart series for the demand graphs (battery_telemetry.demand_telemetry), with derived signals:
power factor and apparent power from net load and reactive power, the behind-the-meter generation share, energy per
interval, and the demand-charge billing window (from the site's demand_tariff) as a state timeline."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

HOURS_PER_READING = 5.0 / 60.0  # 5-min readings
PF = "ABS(net_load_kw) / NULLIF(SQRT(net_load_kw * net_load_kw + load_reactive_kvar * load_reactive_kvar), 0)"
APPARENT = "SQRT(net_load_kw * net_load_kw + load_reactive_kvar * load_reactive_kvar)"


def demand_spec(window_start: Optional[float], window_end: Optional[float]) -> SeriesSpec:
    if window_start is not None and window_end is not None:
        lo, hi = float(window_start), float(window_end)  # numbers from the tariff table, never from a request
        window = (f"CASE WHEN EXTRACT(HOUR FROM ts AT TIME ZONE 'Asia/Kolkata') + EXTRACT(MINUTE FROM ts AT TIME ZONE "
                  f"'Asia/Kolkata') / 60.0 >= {lo} AND EXTRACT(HOUR FROM ts AT TIME ZONE 'Asia/Kolkata') + "
                  f"EXTRACT(MINUTE FROM ts AT TIME ZONE 'Asia/Kolkata') / 60.0 < {hi} THEN 'PEAK_WINDOW' "
                  f"ELSE 'OFF_PEAK' END")
    else:
        window = "'NO_TARIFF'"
    return SeriesSpec(
        table="battery_telemetry.demand_telemetry",
        id_column="metering_point_id",
        columns=[
            SeriesColumn("gross_load_kw", "avg"),
            SeriesColumn("net_load_kw", "avg"),
            SeriesColumn("behind_meter_gen_kw", "avg"),
            SeriesColumn("net_load_max_kw", "max", source="net_load_kw"),
            SeriesColumn("net_load_min_kw", "min", source="net_load_kw"),
            SeriesColumn("load_reactive_kvar", "avg"),
            SeriesColumn("apparent_kva", "avg", source=APPARENT),
            SeriesColumn("power_factor", "avg", source=PF),
            SeriesColumn("gen_share_pct", "avg", source="100.0 * behind_meter_gen_kw / NULLIF(gross_load_kw, 0)"),
            SeriesColumn("net_energy_kwh", "sum", source=f"net_load_kw * {HOURS_PER_READING}"),
            SeriesColumn("gross_energy_kwh", "sum", source=f"gross_load_kw * {HOURS_PER_READING}"),
            SeriesColumn("gen_energy_kwh", "sum", source=f"behind_meter_gen_kw * {HOURS_PER_READING}"),
        ],
        state_columns=["billing_window"],
        state_exprs={"billing_window": window},
    )


def get_demand_series(db: Session, mp_id: int, start: Optional[datetime], end: Optional[datetime], max_points: int,
                      window_start: Optional[float], window_end: Optional[float]) -> dict:
    return build_series(db, demand_spec(window_start, window_end), mp_id, start, end, max_points)
