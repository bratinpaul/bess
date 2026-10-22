from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DashboardSummary(BaseModel):
    site_count: int
    total_power_mw: Decimal
    total_energy_mwh: Decimal


class SiteMapPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_id: int
    site_code: str
    site_name: str
    latitude: Decimal
    longitude: Decimal
    rated_power_mw: Optional[Decimal] = None
    rated_energy_mwh: Optional[Decimal] = None
