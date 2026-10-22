from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.system_telemetry import StateSegment

# net load must equal gross load - behind-the-meter generation within this tolerance (kW)
NET_TOLERANCE_KW = Decimal("1.0")


class DemandTelemetryBase(BaseModel):
    gross_load_kw: Optional[Decimal] = Field(default=None, ge=0, le=1_000_000)
    behind_meter_gen_kw: Optional[Decimal] = Field(default=None, ge=0, le=1_000_000)
    net_load_kw: Optional[Decimal] = Field(default=None, ge=-1_000_000, le=1_000_000)
    load_reactive_kvar: Optional[Decimal] = Field(default=None, ge=-1_000_000, le=1_000_000)

    @model_validator(mode="after")
    def consistent_net(self):
        """net = gross - behind-the-meter generation: derived when missing, checked when given."""
        g, b, n = self.gross_load_kw, self.behind_meter_gen_kw, self.net_load_kw
        if n is None and g is not None:
            self.net_load_kw = g - (b or Decimal(0))
        elif n is not None and g is not None and b is not None and abs(n - (g - b)) > NET_TOLERANCE_KW:
            raise ValueError(f"net_load_kw {n} is not gross_load_kw - behind_meter_gen_kw ({g - b})")
        if self.gross_load_kw is None and self.net_load_kw is None:
            raise ValueError("Give at least gross_load_kw or net_load_kw")
        return self


class DemandTelemetryCreate(DemandTelemetryBase):
    metering_point_id: int
    ts: datetime


class DemandTelemetryUpdate(DemandTelemetryBase):
    pass


class DemandTelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metering_point_id: int
    ts: datetime
    mp_code: Optional[str] = None
    gross_load_kw: Optional[Decimal] = None
    behind_meter_gen_kw: Optional[Decimal] = None
    net_load_kw: Optional[Decimal] = None
    load_reactive_kvar: Optional[Decimal] = None
    power_factor: Optional[float] = None


class DemandTelemetryPage(BaseModel):
    items: list[DemandTelemetryOut]
    total: int
    page: int
    page_size: int


class MeteringPointOut(BaseModel):
    metering_point_id: int
    mp_code: str
    mp_type: str
    site_id: int
    site_name: Optional[str] = None
    voltage_kv: Optional[float] = None
    description: Optional[str] = None
    readings: int = 0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None


class BulkDemandTelemetryRowError(BaseModel):
    row: int
    errors: list[str]


class BulkDemandTelemetryResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkDemandTelemetryRowError]
    metering_points: list[str] = []


class DemandStateTimeline(BaseModel):
    states: list[str]
    segments: list[StateSegment]


class DemandTelemetrySeries(BaseModel):
    metering_point_id: int
    mp_code: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    points: list[dict[str, Any]]
    timelines: dict[str, DemandStateTimeline]
    # reference values for the charts: window peak, billing-window peak, ratchet level
    refs: dict[str, Optional[float]] = {}
    tariff: Optional[dict[str, Any]] = None
