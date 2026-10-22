from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.system_telemetry import StateSegment


class EmsTelemetryBase(BaseModel):
    dispatch_mode: Optional[str] = None
    grid_service: Optional[str] = None
    market_price_mwh: Optional[Decimal] = Field(default=None, ge=0)
    p_setpoint_kw: Optional[Decimal] = None
    poi_active_power_kw: Optional[Decimal] = None
    poi_reactive_power_kvar: Optional[Decimal] = None
    tracking_error_kw: Optional[Decimal] = None
    grid_frequency_hz: Optional[Decimal] = Field(default=None, ge=0, le=100)
    poi_voltage_kv: Optional[Decimal] = None
    agc_signal: Optional[Decimal] = Field(default=None, ge=-1, le=1)
    plant_soc_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    target_soc_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    avail_charge_kw: Optional[Decimal] = None
    avail_discharge_kw: Optional[Decimal] = None
    avail_charge_energy_kwh: Optional[Decimal] = None
    avail_discharge_energy_kwh: Optional[Decimal] = None
    aux_load_kw: Optional[Decimal] = None
    aux_load_pct: Optional[Decimal] = None
    cum_import_kwh: Optional[Decimal] = None
    cum_export_kwh: Optional[Decimal] = None
    revenue_cum_usd: Optional[Decimal] = None
    units_online: Optional[int] = None
    plant_available: Optional[int] = Field(default=None, ge=0, le=1)
    alarm_level: Optional[int] = Field(default=None, ge=0, le=3)


class EmsTelemetryCreate(EmsTelemetryBase):
    ems_id: int
    ts: datetime


class EmsTelemetryOut(EmsTelemetryBase):
    model_config = ConfigDict(from_attributes=True)

    ems_id: int
    ts: datetime
    ems_code: Optional[str] = None


class EmsTelemetryPage(BaseModel):
    items: list[EmsTelemetryOut]
    total: int
    page: int
    page_size: int


class BulkEmsTelemetryRowError(BaseModel):
    row: int
    errors: list[str]


class BulkEmsTelemetryResult(BaseModel):
    filename: str
    ems_code: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkEmsTelemetryRowError]


class EmsStateTimeline(BaseModel):
    states: list[str]
    segments: list[StateSegment]


class EmsTelemetrySeries(BaseModel):
    ems_id: int
    ems_code: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    # one dict per bucket: "ts" plus every series column (see services/ems_telemetry_series.py)
    points: list[dict[str, Any]]
    timelines: dict[str, EmsStateTimeline]
