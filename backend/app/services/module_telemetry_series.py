"""Chart series for the module telemetry graphs (module_telemetry)."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.timeseries import SeriesColumn, SeriesSpec, build_series

MODULE_SERIES = SeriesSpec(
    table="module_telemetry",
    id_column="module_id",
    columns=[
        SeriesColumn("cell_v_avg_v", "avg"),
        SeriesColumn("cell_v_min_v", "min"),
        SeriesColumn("cell_v_max_v", "max"),
        # worst imbalance and temperature spread per bucket
        SeriesColumn("imbalance_mv", "max", source="(cell_v_max_v - cell_v_min_v) * 1000"),
        SeriesColumn("cell_temp_min_c", "min"),
        SeriesColumn("cell_temp_max_c", "max"),
        SeriesColumn("temp_spread_c", "max", source="(cell_temp_max_c - cell_temp_min_c)"),
    ],
)


def get_module_series(
    db: Session,
    module_id: int,
    start: Optional[datetime],
    end: Optional[datetime],
    max_points: int,
) -> dict:
    return build_series(db, MODULE_SERIES, module_id, start, end, max_points)
