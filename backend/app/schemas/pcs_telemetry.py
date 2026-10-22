from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.system_telemetry import StateSegment


class PcsTelemetryBase(BaseModel):
    mode_code: Optional[str] = None
    grid_service: Optional[str] = None
    ac_active_power_kw: Optional[Decimal] = None
    ac_reactive_power_kvar: Optional[Decimal] = None
    ac_apparent_power_kva: Optional[Decimal] = None
    power_factor: Optional[Decimal] = Field(default=None, ge=-1, le=1)
    ac_frequency_hz: Optional[Decimal] = Field(default=None, ge=0, le=100)
    ac_voltage_ab_v: Optional[Decimal] = None
    ac_voltage_bc_v: Optional[Decimal] = None
    ac_voltage_ca_v: Optional[Decimal] = None
    ac_current_a_a: Optional[Decimal] = None
    ac_current_b_a: Optional[Decimal] = None
    ac_current_c_a: Optional[Decimal] = None
    thd_voltage_pct: Optional[Decimal] = None
    thd_current_pct: Optional[Decimal] = None
    dc_voltage_v: Optional[Decimal] = None
    dc_current_a: Optional[Decimal] = None
    dc_power_kw: Optional[Decimal] = None
    efficiency_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    igbt_temp_c: Optional[Decimal] = None
    heatsink_temp_c: Optional[Decimal] = None
    inlet_coolant_temp_c: Optional[Decimal] = None
    ambient_temp_c: Optional[Decimal] = None
    avail_charge_kw: Optional[Decimal] = None
    avail_discharge_kw: Optional[Decimal] = None
    ac_energy_import_kwh: Optional[Decimal] = None
    ac_energy_export_kwh: Optional[Decimal] = None
    breaker_state: Optional[str] = None
    alarm_level: Optional[int] = None


class PcsTelemetryCreate(PcsTelemetryBase):
    pcs_id: int
    ts: datetime


class PcsTelemetryOut(PcsTelemetryBase):
    model_config = ConfigDict(from_attributes=True)

    pcs_id: int
    ts: datetime
    pcs_code: Optional[str] = None


class PcsTelemetryPage(BaseModel):
    items: list[PcsTelemetryOut]
    total: int
    page: int
    page_size: int


class BulkPcsTelemetryRowError(BaseModel):
    row: int
    errors: list[str]


class BulkPcsTelemetryResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkPcsTelemetryRowError]


class PcsStateTimeline(BaseModel):
    states: list[str]
    segments: list[StateSegment]


class PcsTelemetrySeries(BaseModel):
    pcs_id: int
    pcs_code: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    # one dict per bucket: "ts" plus every series column (see services/pcs_telemetry_series.py)
    points: list[dict[str, Any]]
    timelines: dict[str, PcsStateTimeline]
    min_power_factor: Optional[float] = None
    rated_apparent_kva: Optional[float] = None
