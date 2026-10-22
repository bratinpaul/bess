from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PcsDailySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    pcs_id: int
    pcs_code: str
    sample_count: int
    peak_charge_power_ac: Optional[Decimal] = None
    peak_discharge_power_ac: Optional[Decimal] = None
    peak_apparent_power: Optional[Decimal] = None
    min_power_factor: Optional[Decimal] = None
    max_reactive_power: Optional[Decimal] = None
    min_ac_frequency_closed: Optional[Decimal] = None
    max_ac_frequency: Optional[Decimal] = None
    avg_efficiency: Optional[Decimal] = None
    max_igbt_temp: Optional[Decimal] = None
    total_energy_imported: Optional[Decimal] = None
    total_energy_exported: Optional[Decimal] = None
    ac_ac_round_trip_eff_pct: Optional[Decimal] = None
    alarm_samples: int
    volt_var_intervals: int
    freq_watt_intervals: int


class PcsTelemetryDateRange(BaseModel):
    min_date: Optional[date] = None
    max_date: Optional[date] = None
