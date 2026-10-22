from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class HvacDailySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    hvac_id: int
    hvac_code: str
    sample_count: int
    energy_kwh: Optional[Decimal] = None
    peak_power_kw: Optional[Decimal] = None
    max_heat_load_kw: Optional[Decimal] = None
    avg_cop: Optional[Decimal] = None
    max_return_temp_c: Optional[Decimal] = None
    max_enclosure_temp_c: Optional[Decimal] = None
    max_humidity_pct: Optional[Decimal] = None
    avg_ambient_c: Optional[Decimal] = None
    cooling_hours: Optional[Decimal] = None
    free_cooling_hours: Optional[Decimal] = None
    compressor_duty_cycle_pct: Optional[Decimal] = None
    cooling_time_hours: Optional[Decimal] = None


class HvacTelemetryDateRange(BaseModel):
    min_date: Optional[date] = None
    max_date: Optional[date] = None


class HvacLatestReading(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hvac_id: int
    hvac_code: str
    ts: datetime
    cooling_mode: Optional[str] = None
    coolant_supply_temp_c: Optional[Decimal] = None
    coolant_return_temp_c: Optional[Decimal] = None
    battery_heat_load_kw: Optional[Decimal] = None
    hvac_power_kw: Optional[Decimal] = None
    cop: Optional[Decimal] = None
    enclosure_temp_c: Optional[Decimal] = None
    alarm_level: Optional[int] = None
    alarm_flags: Optional[str] = None
