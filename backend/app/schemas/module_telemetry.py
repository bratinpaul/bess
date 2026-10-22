from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.system_telemetry import BulkTelemetryRowError

# plausible bounds for a lithium-ion cell; readings outside are rejected as bad data
CELL_V_MIN, CELL_V_MAX = 2.0, 4.5
CELL_TEMP_MIN, CELL_TEMP_MAX = -40, 100


class ModuleTelemetryBase(BaseModel):
    cell_v_avg_v: Optional[Decimal] = Field(default=None, ge=CELL_V_MIN, le=CELL_V_MAX)
    cell_v_min_v: Optional[Decimal] = Field(default=None, ge=CELL_V_MIN, le=CELL_V_MAX)
    cell_v_max_v: Optional[Decimal] = Field(default=None, ge=CELL_V_MIN, le=CELL_V_MAX)
    cell_temp_max_c: Optional[Decimal] = Field(default=None, ge=CELL_TEMP_MIN, le=CELL_TEMP_MAX)
    cell_temp_min_c: Optional[Decimal] = Field(default=None, ge=CELL_TEMP_MIN, le=CELL_TEMP_MAX)
    balancing_active: Optional[bool] = None

    @model_validator(mode="after")
    def check_ordered_ranges(self):
        lo, hi, avg = self.cell_v_min_v, self.cell_v_max_v, self.cell_v_avg_v
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("cell_v_min_v cannot be greater than cell_v_max_v")
        if avg is not None and ((lo is not None and avg < lo) or (hi is not None and avg > hi)):
            raise ValueError("cell_v_avg_v must lie between cell_v_min_v and cell_v_max_v")
        if (
            self.cell_temp_min_c is not None
            and self.cell_temp_max_c is not None
            and self.cell_temp_min_c > self.cell_temp_max_c
        ):
            raise ValueError("cell_temp_min_c cannot be greater than cell_temp_max_c")
        return self


class ModuleTelemetryCreate(ModuleTelemetryBase):
    module_id: int
    ts: datetime


class ModuleTelemetryOut(ModuleTelemetryBase):
    model_config = ConfigDict(from_attributes=True)

    module_id: int
    ts: datetime
    serial_number: Optional[str] = None
    imbalance_mv: Optional[Decimal] = None


class ModuleTelemetryPage(BaseModel):
    items: list[ModuleTelemetryOut]
    total: int
    page: int
    page_size: int


class ModuleOption(BaseModel):
    module_id: int
    serial_number: Optional[str] = None
    pack_number: Optional[str] = None


class BulkModuleTelemetryResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkTelemetryRowError]


class ModuleTelemetrySeries(BaseModel):
    module_id: int
    serial_number: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    # one dict per bucket: "ts" plus every series column (see services/module_telemetry_series.py)
    points: list[dict[str, Any]]


class ModuleSummaryKpis(BaseModel):
    modules: int
    samples_per_module: Optional[int] = None
    cell_v_min: Optional[float] = None
    cell_v_max: Optional[float] = None
    mean_imbalance_mv: Optional[float] = None
    max_imbalance_mv: Optional[float] = None
    max_temp_c: Optional[float] = None
    balancing_duty_pct: Optional[float] = None
    balancing_module_hours: Optional[float] = None
    highest_imbalance_module: Optional[str] = None
    highest_imbalance_mv: Optional[float] = None


class ModuleSummaryByModule(BaseModel):
    module_id: int
    serial_number: Optional[str] = None
    label: str
    avg_cell_v: Optional[float] = None
    min_cell_v: Optional[float] = None
    max_cell_v: Optional[float] = None
    mean_imbalance_mv: Optional[float] = None
    max_imbalance_mv: Optional[float] = None
    max_temp_c: Optional[float] = None
    balancing_hours: float
    samples: int


class ModuleSummaryDaily(BaseModel):
    day: date
    max_imbalance_mv: Optional[float] = None
    avg_imbalance_mv: Optional[float] = None
    max_temp_c: Optional[float] = None
    balancing_module_hours: float
    samples: int


class ModuleTelemetrySummary(BaseModel):
    start_date: date
    end_date: date
    sample_interval_minutes: float
    kpis: ModuleSummaryKpis
    by_module: list[ModuleSummaryByModule]
    daily: list[ModuleSummaryDaily]


class ModuleTelemetryDateRange(BaseModel):
    first_date: Optional[date] = None
    last_date: Optional[date] = None
