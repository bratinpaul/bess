from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SystemTelemetryBase(BaseModel):
    mode_code: Optional[str] = None
    soc_bms_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    soh_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    pack_voltage_v: Optional[Decimal] = None
    pack_current_a: Optional[Decimal] = None
    power_kw: Optional[Decimal] = None
    c_rate: Optional[Decimal] = None
    cell_v_avg_v: Optional[Decimal] = None
    cell_v_min_v: Optional[Decimal] = None
    cell_v_max_v: Optional[Decimal] = None
    cell_v_delta_mv: Optional[Decimal] = None
    cell_temp_avg_c: Optional[Decimal] = None
    cell_temp_min_c: Optional[Decimal] = None
    cell_temp_max_c: Optional[Decimal] = None
    coolant_temp_c: Optional[Decimal] = None
    ambient_temp_c: Optional[Decimal] = None
    insulation_res_kohm: Optional[Decimal] = None
    avail_charge_kw: Optional[Decimal] = None
    avail_discharge_kw: Optional[Decimal] = None
    cum_charge_kwh: Optional[Decimal] = None
    cum_discharge_kwh: Optional[Decimal] = None
    equiv_full_cycles: Optional[Decimal] = None
    contactor_state: Optional[str] = None
    alarm_level: Optional[int] = None
    # current sensing and SOC estimation
    measured_current_a: Optional[Decimal] = None
    current_sensor_offset_a: Optional[Decimal] = None
    soc_coulomb_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    soc_battery_telemetry_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    usable_capacity_ah: Optional[Decimal] = Field(default=None, ge=0)
    coulombic_efficiency: Optional[Decimal] = Field(default=None, ge=0, le=100)
    at_rest: Optional[bool] = None
    rest_duration_min: Optional[Decimal] = Field(default=None, ge=0)
    ocv_rested_v: Optional[Decimal] = None

    @model_validator(mode="after")
    def check_ordered_ranges(self):
        if (
            self.cell_v_min_v is not None
            and self.cell_v_max_v is not None
            and self.cell_v_min_v > self.cell_v_max_v
        ):
            raise ValueError("cell_v_min_v cannot be greater than cell_v_max_v")
        if (
            self.cell_temp_min_c is not None
            and self.cell_temp_max_c is not None
            and self.cell_temp_min_c > self.cell_temp_max_c
        ):
            raise ValueError("cell_temp_min_c cannot be greater than cell_temp_max_c")
        return self


class SystemTelemetryCreate(SystemTelemetryBase):
    system_id: int
    ts: datetime


class SystemTelemetryOut(SystemTelemetryBase):
    model_config = ConfigDict(from_attributes=True)

    system_id: int
    ts: datetime
    system_name: Optional[str] = None


class SystemTelemetryPage(BaseModel):
    items: list[SystemTelemetryOut]
    total: int
    page: int
    page_size: int


class BulkTelemetryRowError(BaseModel):
    row: int
    errors: list[str]


class BulkTelemetryResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkTelemetryRowError]


class TelemetrySeriesPoint(BaseModel):
    ts: datetime
    soc_bms_pct: Optional[float] = None
    soh_pct: Optional[float] = None
    pack_voltage_v: Optional[float] = None
    pack_current_a: Optional[float] = None
    power_kw: Optional[float] = None
    c_rate: Optional[float] = None
    cell_v_avg_v: Optional[float] = None
    cell_v_min_v: Optional[float] = None
    cell_v_max_v: Optional[float] = None
    cell_v_delta_mv: Optional[float] = None
    cell_temp_avg_c: Optional[float] = None
    cell_temp_min_c: Optional[float] = None
    cell_temp_max_c: Optional[float] = None
    coolant_temp_c: Optional[float] = None
    ambient_temp_c: Optional[float] = None
    insulation_res_kohm: Optional[float] = None
    avail_charge_kw: Optional[float] = None
    avail_discharge_kw: Optional[float] = None
    cum_charge_kwh: Optional[float] = None
    cum_discharge_kwh: Optional[float] = None
    charge_kwh_step: Optional[float] = None
    discharge_kwh_step: Optional[float] = None
    equiv_full_cycles: Optional[float] = None
    measured_current_a: Optional[float] = None
    current_sensor_offset_a: Optional[float] = None
    soc_coulomb_pct: Optional[float] = None
    soc_battery_telemetry_pct: Optional[float] = None
    usable_capacity_ah: Optional[float] = None
    coulombic_efficiency: Optional[float] = None
    rest_duration_min: Optional[float] = None
    ocv_rested_v: Optional[float] = None


class StateSegment(BaseModel):
    state: Optional[str] = None
    start: datetime
    end: datetime


class SystemTelemetrySeries(BaseModel):
    system_id: int
    system_name: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    points: list[TelemetrySeriesPoint]
    contactor_segments: list[StateSegment]
    contactor_states: list[str]
    rest_segments: list[StateSegment] = []
