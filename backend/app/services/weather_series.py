"""Chart series for the weather graphs (battery_telemetry.weather_actual), with derived signals: dew point (Magnus
formula from temperature and humidity), irradiation per interval (Wh/m² from GHI x interval) and day / night from GHI."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

HOURS_PER_READING = 5.0 / 60.0  # 5-min readings
# Magnus: gamma = ln(RH/100) + b T / (c + T);  Td = c gamma / (b - gamma),  b = 17.62, c = 243.12 °C
_GAMMA = "(LN(GREATEST(humidity_pct, 1) / 100.0) + 17.62 * temp_c / (243.12 + temp_c))"
DEW_POINT = f"(243.12 * {_GAMMA} / (17.62 - {_GAMMA}))"

WEATHER_SERIES = SeriesSpec(
    table="battery_telemetry.weather_actual",
    id_column="station_id",
    columns=[
        SeriesColumn("temp_c", "avg"),
        SeriesColumn("temp_max_c", "max", source="temp_c"),
        SeriesColumn("temp_min_c", "min", source="temp_c"),
        SeriesColumn("dew_point_c", "avg", source=DEW_POINT),
        SeriesColumn("ghi_wm2", "avg"),
        SeriesColumn("ghi_max_wm2", "max", source="ghi_wm2"),
        SeriesColumn("irradiation_whm2", "sum", source=f"ghi_wm2 * {HOURS_PER_READING}"),
        SeriesColumn("humidity_pct", "avg"),
        SeriesColumn("wind_ms", "avg"),
        SeriesColumn("wind_max_ms", "max", source="wind_ms"),
        SeriesColumn("wind_min_ms", "min", source="wind_ms"),
        SeriesColumn("cloud_fraction", "avg"),
        SeriesColumn("cloud_pct", "avg", source="100.0 * cloud_fraction"),
    ],
    state_columns=["daylight"],
    state_exprs={"daylight": "CASE WHEN ghi_wm2 > 5 THEN 'DAYLIGHT' WHEN ghi_wm2 IS NULL THEN NULL ELSE 'NIGHT' END"},
)


def get_weather_series(db: Session, station_id: int, start: Optional[datetime], end: Optional[datetime],
                       max_points: int) -> dict:
    return build_series(db, WEATHER_SERIES, station_id, start, end, max_points)
