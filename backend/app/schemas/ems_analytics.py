from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EmsDailySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    ems_id: int
    ems_code: str
    sample_count: int
    peak_grid_import_kw: Optional[Decimal] = None
    peak_grid_export_kw: Optional[Decimal] = None
    energy_imported_kwh: Optional[Decimal] = None
    energy_exported_kwh: Optional[Decimal] = None
    net_market_revenue_usd: Optional[Decimal] = None
    avg_market_price: Optional[Decimal] = None
    max_market_price: Optional[Decimal] = None
    avg_realized_export_price: Optional[Decimal] = None
    rms_tracking_error_kw: Optional[Decimal] = None
    aux_energy_kwh: Optional[Decimal] = None
    availability_pct: Optional[Decimal] = None
    avg_plant_soc: Optional[Decimal] = None


class EmsTelemetryDateRange(BaseModel):
    min_date: Optional[date] = None
    max_date: Optional[date] = None
