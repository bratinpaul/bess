from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.system_telemetry import StateSegment


class HvacTelemetryBase(BaseModel):
    cooling_mode: Optional[str] = None
    ambient_temp_c: Optional[Decimal] = None
    coolant_setpoint_c: Optional[Decimal] = None
    coolant_supply_temp_c: Optional[Decimal] = None
    coolant_return_temp_c: Optional[Decimal] = None
    coolant_delta_t_c: Optional[Decimal] = None
    coolant_flow_lpm: Optional[Decimal] = Field(default=None, ge=0)
    compressor_speed_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    condenser_fan_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    refrig_suction_bar: Optional[Decimal] = None
    refrig_discharge_bar: Optional[Decimal] = None
    battery_heat_load_kw: Optional[Decimal] = None
    cooling_capacity_kw: Optional[Decimal] = None
    heat_rejected_kw: Optional[Decimal] = None
    hvac_power_kw: Optional[Decimal] = None
    cop: Optional[Decimal] = Field(default=None, ge=0)
    enclosure_temp_c: Optional[Decimal] = None
    enclosure_humidity_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    filter_dp_pa: Optional[Decimal] = None
    cum_energy_kwh: Optional[Decimal] = None
    compressor_runtime_h: Optional[Decimal] = None
    units_running: Optional[int] = None
    alarm_level: Optional[int] = Field(default=None, ge=0, le=3)
    alarm_flags: Optional[str] = None


class HvacTelemetryCreate(HvacTelemetryBase):
    hvac_id: int
    ts: datetime


class HvacTelemetryOut(HvacTelemetryBase):
    model_config = ConfigDict(from_attributes=True)

    hvac_id: int
    ts: datetime
    hvac_code: Optional[str] = None


class HvacTelemetryPage(BaseModel):
    items: list[HvacTelemetryOut]
    total: int
    page: int
    page_size: int


class BulkHvacTelemetryRowError(BaseModel):
    row: int
    errors: list[str]


class BulkHvacTelemetryResult(BaseModel):
    filename: str
    hvac_code: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkHvacTelemetryRowError]


class HvacStateTimeline(BaseModel):
    states: list[str]
    segments: list[StateSegment]


class HvacTelemetrySeries(BaseModel):
    hvac_id: int
    hvac_code: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    # one dict per bucket: "ts" plus every series column (see services/hvac_telemetry_series.py)
    points: list[dict[str, Any]]
    timelines: dict[str, HvacStateTimeline]
    coolant_setpoint_c: Optional[float] = None
