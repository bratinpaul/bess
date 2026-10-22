from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DailySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    system_id: int
    system_name: str
    sample_count: int
    min_soc: Optional[Decimal] = None
    max_soc: Optional[Decimal] = None
    avg_soc: Optional[Decimal] = None
    min_pack_voltage: Optional[Decimal] = None
    max_pack_voltage: Optional[Decimal] = None
    peak_charge_power: Optional[Decimal] = None
    peak_discharge_power: Optional[Decimal] = None
    max_cell_temp: Optional[Decimal] = None
    max_cell_imbalance: Optional[Decimal] = None
    total_energy_charged: Optional[Decimal] = None
    total_energy_discharged: Optional[Decimal] = None
    round_trip_efficiency_pct: Optional[Decimal] = None
    equiv_full_cycles: Optional[Decimal] = None
    alarm_samples: int
    ending_soh: Optional[Decimal] = None
    avg_ambient_temp: Optional[Decimal] = None


class TelemetryDateRange(BaseModel):
    min_date: Optional[date] = None
    max_date: Optional[date] = None
