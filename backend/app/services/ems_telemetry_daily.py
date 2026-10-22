from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

_DAILY_AGGREGATE_SQL = text(
    """
    WITH global_steps AS (
        SELECT
            ts,
            ts::date AS day,
            market_price_mwh,
            cum_export_kwh - LAG(cum_export_kwh) OVER (ORDER BY ts) AS export_step
        FROM ems_telemetry
        WHERE ems_id = :ems_id
    ),
    export_steps AS (
        SELECT * FROM global_steps WHERE day >= :start_date AND day <= :end_date
    ),
    realized AS (
        SELECT day, SUM(market_price_mwh * export_step) / NULLIF(SUM(export_step), 0) AS avg_realized_export_price
        FROM export_steps
        WHERE export_step IS NOT NULL AND export_step > 0
        GROUP BY day
    ),
    daily AS (
        SELECT
            ts::date AS day,
            MAX(poi_active_power_kw) AS peak_grid_import_kw,
            MIN(poi_active_power_kw) AS peak_grid_export_kw,
            ROUND(AVG(market_price_mwh), 4) AS avg_market_price,
            MAX(market_price_mwh) AS max_market_price,
            ROUND(SQRT(AVG(tracking_error_kw ^ 2)), 4) AS rms_tracking_error_kw,
            ROUND(SUM(aux_load_kw) * (5.0 / 60), 3) AS aux_energy_kwh,
            ROUND(AVG(plant_available) * 100, 2) AS availability_pct,
            ROUND(AVG(plant_soc_pct), 2) AS avg_plant_soc,
            COUNT(*) AS sample_count
        FROM ems_telemetry
        WHERE ems_id = :ems_id AND ts::date >= :start_date AND ts::date <= :end_date
        GROUP BY ts::date
    ),
    first_rows AS (
        SELECT DISTINCT ON (ts::date)
            ts::date AS day, cum_import_kwh, cum_export_kwh, revenue_cum_usd
        FROM ems_telemetry
        WHERE ems_id = :ems_id AND ts::date >= :start_date AND ts::date <= :end_date
        ORDER BY ts::date, ts ASC
    ),
    last_rows AS (
        SELECT DISTINCT ON (ts::date)
            ts::date AS day, cum_import_kwh, cum_export_kwh, revenue_cum_usd
        FROM ems_telemetry
        WHERE ems_id = :ems_id AND ts::date >= :start_date AND ts::date <= :end_date
        ORDER BY ts::date, ts DESC
    )
    SELECT
        d.day,
        d.peak_grid_import_kw,
        d.peak_grid_export_kw,
        d.avg_market_price,
        d.max_market_price,
        d.rms_tracking_error_kw,
        d.aux_energy_kwh,
        d.availability_pct,
        d.avg_plant_soc,
        d.sample_count,
        (l.cum_import_kwh - f.cum_import_kwh) AS energy_imported_kwh,
        (l.cum_export_kwh - f.cum_export_kwh) AS energy_exported_kwh,
        (l.revenue_cum_usd - f.revenue_cum_usd) AS net_market_revenue_usd,
        r.avg_realized_export_price
    FROM daily d
    JOIN first_rows f ON f.day = d.day
    JOIN last_rows l ON l.day = d.day
    LEFT JOIN realized r ON r.day = d.day
    ORDER BY d.day
    """
)

_DATE_RANGE_SQL = text(
    """
    SELECT MIN(ts::date) AS min_date, MAX(ts::date) AS max_date
    FROM ems_telemetry
    WHERE ems_id = :ems_id
    """
)


def get_ems_daily_aggregates(db: Session, ems_id: int, start_date: date, end_date: date) -> list[dict]:
    rows = db.execute(
        _DAILY_AGGREGATE_SQL, {"ems_id": ems_id, "start_date": start_date, "end_date": end_date}
    ).mappings().all()
    return [dict(row) for row in rows]


def get_ems_telemetry_date_range(db: Session, ems_id: int) -> dict:
    row = db.execute(_DATE_RANGE_SQL, {"ems_id": ems_id}).mappings().first()
    return dict(row) if row else {"min_date": None, "max_date": None}
