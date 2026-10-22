from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class LatestReading(BaseModel):
    ts: Optional[datetime] = None
    soc_pct: Optional[Decimal] = None
    soh_pct: Optional[Decimal] = None
    power_kw: Optional[Decimal] = None
    mode_code: Optional[str] = None
    bms_mode_code: Optional[str] = None
    contactor_state: Optional[str] = None
    breaker_state: Optional[str] = None
    bms_alarm_level: Optional[int] = None
    pcs_alarm_level: Optional[int] = None


class PeriodPerformance(BaseModel):
    start_date: date
    end_date: date
    days: int
    avg_soc: Optional[Decimal] = None
    min_soc: Optional[Decimal] = None
    max_soc: Optional[Decimal] = None
    soh_at_start: Optional[Decimal] = None
    energy_discharged_mwh: Optional[Decimal] = None
    energy_charged_mwh: Optional[Decimal] = None
    energy_throughput_mwh: Optional[Decimal] = None
    dc_round_trip_eff_pct: Optional[Decimal] = None
    ac_round_trip_eff_pct: Optional[Decimal] = None
    equiv_full_cycles: Optional[Decimal] = None
    cycles_per_day: Optional[Decimal] = None
    peak_charge_power_ac_kw: Optional[Decimal] = None
    peak_discharge_power_ac_kw: Optional[Decimal] = None
    avg_conversion_eff_pct: Optional[Decimal] = None
    min_power_factor: Optional[Decimal] = None
    max_cell_temp_c: Optional[Decimal] = None
    max_igbt_temp_c: Optional[Decimal] = None
    availability_pct: Optional[Decimal] = None
    bms_alarm_samples: int = 0
    pcs_alarm_samples: int = 0
    bms_sample_count: int = 0
    pcs_sample_count: int = 0


class OperationsOverview(BaseModel):
    system_id: int
    system_name: str
    site_name: Optional[str] = None
    chemistry_code: Optional[str] = None
    rated_power_mw: Optional[Decimal] = None
    rated_energy_mwh: Optional[Decimal] = None
    pcs_codes: list[str] = []
    latest: LatestReading
    period: PeriodPerformance
