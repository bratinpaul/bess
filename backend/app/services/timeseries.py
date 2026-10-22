"""Generic chart-series extraction for TimescaleDB telemetry hypertables.

Long ranges are averaged into time buckets so a chart stays around `max_points`
points. Each output column declares how it aggregates within a bucket:

- "avg": mean of the readings
- "min" / "max": extremes (used for band edges and monotonic cumulative counters)
- "step": per-reading increase of a cumulative counter, summed per bucket. A drop
  in the counter is treated as a meter reset, not negative energy.
- "delta": per-reading signed change of a cumulative counter, summed per bucket
  (for counters that legitimately go down, e.g. revenue while buying energy).
- "sum": the readings summed per bucket (e.g. energy per interval from kW x interval hours).

State columns (text codes such as a breaker state) are returned as run-length
segments of the raw readings instead of being bucketed.

Table and column names come from trusted per-endpoint specs, never from requests.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_WINDOW = timedelta(days=7)
# bucket widths offered, in seconds (1 min .. 1 day)
NICE_BUCKETS = [60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]


@dataclass(frozen=True)
class SeriesColumn:
    name: str
    agg: str  # "avg" | "min" | "max" | "step" | "delta" | "sum"
    source: Optional[str] = None  # raw column; defaults to `name`
    null_when: Optional[str] = None  # SQL condition that turns the reading into a gap


@dataclass(frozen=True)
class SeriesSpec:
    table: str
    id_column: str
    columns: list[SeriesColumn]
    state_columns: list[str] = field(default_factory=list)
    # optional SQL expression per state column (e.g. to turn a boolean into a label); defaults to the column
    state_exprs: dict[str, str] = field(default_factory=dict)


def pick_bucket_seconds(start: datetime, end: datetime, max_points: int, raw_interval: Optional[int]) -> int:
    span = max((end - start).total_seconds(), 1)
    wanted = max(span / max_points, raw_interval or 0)
    for size in NICE_BUCKETS:
        if size >= wanted:
            return size
    return int(math.ceil(wanted / 86400) * 86400)


def _raw_expr(col: SeriesColumn) -> str:
    src = col.source or col.name
    if col.agg == "step":
        return f"GREATEST({src} - LAG({src}) OVER w, 0)"
    if col.agg == "delta":
        return f"{src} - LAG({src}) OVER w"
    if col.null_when:
        return f"CASE WHEN {col.null_when} THEN NULL ELSE {src} END"
    return src


def _series_sql(spec: SeriesSpec) -> str:
    raw_cols = ",\n            ".join(f"{_raw_expr(c)} AS {c.name}" for c in spec.columns)
    agg_fn = {"avg": "AVG", "min": "MIN", "max": "MAX", "step": "SUM", "delta": "SUM", "sum": "SUM"}
    bucket_cols = ",\n        ".join(f"{agg_fn[c.agg]}({c.name}) AS {c.name}" for c in spec.columns)
    return f"""
    WITH raw AS (
        SELECT
            ts,
            {raw_cols}
        FROM {spec.table}
        -- one extra hour before the window so the first step has a predecessor
        WHERE {spec.id_column} = :entity_id AND ts >= :start - INTERVAL '1 hour' AND ts <= :end
        WINDOW w AS (ORDER BY ts)
    )
    SELECT
        time_bucket(make_interval(secs => :bucket), ts) AS ts,
        {bucket_cols}
    FROM raw
    WHERE ts >= :start
    GROUP BY 1
    ORDER BY 1
    """


def state_segments(rows, sample_seconds: int) -> list[dict]:
    """Collapse consecutive readings with the same state into segments."""
    segments: list[dict] = []
    for ts, state in rows:
        if segments and segments[-1]["state"] == state:
            segments[-1]["end"] = ts
            continue
        if segments:
            segments[-1]["end"] = ts
        segments.append({"state": state, "start": ts, "end": ts})
    if segments:
        # the last reading holds its state for one sample period
        segments[-1]["end"] = segments[-1]["end"] + timedelta(seconds=sample_seconds)
    return segments


def _to_float(value):
    return None if value is None else float(value)


def build_series(
    db: Session,
    spec: SeriesSpec,
    entity_id,
    start: Optional[datetime],
    end: Optional[datetime],
    max_points: int,
) -> dict:
    extent = db.execute(
        text(f"SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM {spec.table} WHERE {spec.id_column} = :entity_id"),
        {"entity_id": entity_id},
    ).one()
    if extent.last_ts is None:
        return {"start": start, "end": end, "bucket_seconds": 0, "raw_interval_seconds": None,
                "points": [], "states": {c: [] for c in spec.state_columns}}

    end = end or extent.last_ts
    start = start or max(extent.first_ts, end - DEFAULT_WINDOW)
    params = {"entity_id": entity_id, "start": start, "end": end}

    raw_interval = db.execute(
        text(f"""
            SELECT EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY gap))::int
            FROM (
                SELECT ts - LAG(ts) OVER (ORDER BY ts) AS gap
                FROM {spec.table}
                WHERE {spec.id_column} = :entity_id AND ts >= :start AND ts <= :end
            ) g
            WHERE gap IS NOT NULL
        """),
        params,
    ).scalar()
    bucket = pick_bucket_seconds(start, end, max_points, raw_interval)

    rows = db.execute(text(_series_sql(spec)), {**params, "bucket": bucket}).mappings().all()
    points = [{k: (v if k == "ts" else _to_float(v)) for k, v in row.items()} for row in rows]

    states: dict[str, list[dict]] = {}
    if spec.state_columns:
        cols = ", ".join(f"{spec.state_exprs.get(c, c)} AS {c}" for c in spec.state_columns)
        state_rows = db.execute(
            text(f"""
                SELECT ts, {cols} FROM {spec.table}
                WHERE {spec.id_column} = :entity_id AND ts >= :start AND ts <= :end
                ORDER BY ts
            """),
            params,
        ).all()
        for i, col in enumerate(spec.state_columns):
            states[col] = state_segments(((r[0], r[i + 1]) for r in state_rows), raw_interval or bucket)

    return {
        "start": start,
        "end": end,
        "bucket_seconds": bucket,
        "raw_interval_seconds": raw_interval,
        "points": points,
        "states": states,
    }
