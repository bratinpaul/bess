from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

COMMAND_CODES = ("SET_MODE", "SET_POWER", "SET_SERVICE")
DISPATCH_STATUSES = ("Active", "Completed", "Aborted")

CommandCode = Literal["SET_MODE", "SET_POWER", "SET_SERVICE"]
DispatchStatus = Literal["Active", "Completed", "Aborted"]
Percent = Optional[Decimal]


class DispatchEventBase(BaseModel):
    effective_from: datetime
    effective_to: Optional[datetime] = None
    # effective_from when left out
    issued_at: Optional[datetime] = None
    ems_id: int
    command_code: CommandCode
    dispatch_mode: str = Field(min_length=1, max_length=50)
    grid_service: str = Field(default="NONE", min_length=1, max_length=50)
    source: Optional[str] = Field(default=None, max_length=100)
    # > 0 charge / import, < 0 discharge / export
    p_setpoint_kw: Decimal = Decimal(0)
    target_soc_pct: Percent = Field(default=None, ge=0, le=100)
    soc_start_pct: Percent = Field(default=None, ge=0, le=100)
    soc_end_pct: Percent = Field(default=None, ge=0, le=100)
    ramp_rate_kw_s: Optional[Decimal] = Field(default=None, ge=0)
    import_kwh: Decimal = Field(default=Decimal(0), ge=0)
    export_kwh: Decimal = Field(default=Decimal(0), ge=0)
    avg_price_mwh: Optional[Decimal] = None
    revenue_usd: Optional[Decimal] = None
    accepted: bool = True
    # Active when there is no end, else Completed, when left out
    status: Optional[DispatchStatus] = None
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("dispatch_mode", "grid_service")
    @classmethod
    def upper_code(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def check_consistency(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("the dispatch can't end before it takes effect")
        if self.issued_at and self.issued_at > self.effective_from:
            raise ValueError("the command can't be issued after it takes effect")
        if self.status is None:
            self.status = "Active" if self.effective_to is None else "Completed"
        elif self.status == "Active" and self.effective_to is not None:
            raise ValueError("an Active dispatch has no end time; clear 'effective to' or change the status")
        elif self.status != "Active" and self.effective_to is None:
            raise ValueError(f"a {self.status} dispatch needs an end time")
        return self


class DispatchEventCreate(DispatchEventBase):
    # generated (DSP-00358 ...) when left out
    dispatch_id: Optional[str] = Field(default=None, max_length=50)


class DispatchEventUpdate(DispatchEventBase):
    pass


class DispatchEventOut(BaseModel):
    dispatch_id: str
    effective_from: datetime
    effective_to: Optional[datetime] = None
    issued_at: datetime
    # derived
    duration_min: Optional[float] = None
    net_energy_kwh: Decimal
    issued_date: date
    ems_id: int
    ems_code: Optional[str] = None
    battery_system_id: Optional[int] = None
    system_name: Optional[str] = None
    command_code: str
    dispatch_mode: str
    dispatch_mode_description: Optional[str] = None
    grid_service: str
    grid_service_description: Optional[str] = None
    source: Optional[str] = None
    p_setpoint_kw: Decimal
    target_soc_pct: Optional[Decimal] = None
    soc_start_pct: Optional[Decimal] = None
    soc_end_pct: Optional[Decimal] = None
    ramp_rate_kw_s: Optional[Decimal] = None
    import_kwh: Decimal
    export_kwh: Decimal
    avg_price_mwh: Optional[Decimal] = None
    revenue_usd: Optional[Decimal] = None
    accepted: bool
    status: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DispatchEventStats(BaseModel):
    """The workbook's Summary 'Overview', over the filtered set."""

    total: int
    active: int
    aborted: int
    avg_duration_min: Optional[float] = None
    import_mwh: float
    export_mwh: float
    revenue_usd: float
    by_mode: dict[str, int]
    by_service: dict[str, int]


class DispatchEventPage(BaseModel):
    items: list[DispatchEventOut]
    total: int
    page: int
    page_size: int
    stats: DispatchEventStats


class DispatchCodeOption(BaseModel):
    code: str
    description: Optional[str] = None


class DispatchEmsOption(BaseModel):
    ems_id: int
    ems_code: str
    battery_system_id: Optional[int] = None
    system_name: Optional[str] = None


class DispatchEventLookups(BaseModel):
    ems: list[DispatchEmsOption]
    modes: list[DispatchCodeOption]
    services: list[DispatchCodeOption]
    command_codes: list[str]
    statuses: list[str]
    # issuers already in use (Scheduler, Market optimizer, AGC, ...)
    sources: list[str]


class BulkDispatchEventRowError(BaseModel):
    row: int
    dispatch_id: Optional[str] = None
    errors: list[str]


class BulkDispatchEventResult(BaseModel):
    filename: str
    sheet: Optional[str] = None
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkDispatchEventRowError]
    ignored_columns: list[str] = []
    # running dispatches ended by a newer one in the file, e.g. "DSP-00357 ended at 2026-09-28 18:20"
    closed_dispatches: list[str] = []


# ---------------------------------------------------------------- analytics (graphical tab)


class DispatchDay(BaseModel):
    date: date
    # by issued date, like the workbook's Summary 'Daily' table
    events: int
    events_by_mode: dict[str, int]
    revenue_usd: float
    import_kwh: float
    export_kwh: float
    # minutes spent in each mode on this calendar day (windows split at midnight)
    minutes_by_mode: dict[str, float]


class DispatchModeSummary(BaseModel):
    mode: str
    description: Optional[str] = None
    events: int
    minutes: float
    import_kwh: float
    export_kwh: float
    revenue_usd: float
    mean_duration_min: Optional[float] = None
    max_duration_min: Optional[float] = None


class DispatchHour(BaseModel):
    hour: int
    # energy spread over the minutes each dispatch ran in this hour of the day
    import_kwh: float
    export_kwh: float
    # time-weighted average of the dispatches' average prices
    avg_price_mwh: Optional[float] = None


class DispatchCount(BaseModel):
    key: str
    count: int


class DispatchPoint(BaseModel):
    dispatch_id: str
    effective_from: datetime
    effective_to: Optional[datetime] = None
    dispatch_mode: str
    p_setpoint_kw: float
    soc_start_pct: Optional[float] = None
    soc_end_pct: Optional[float] = None
    target_soc_pct: Optional[float] = None
    avg_price_mwh: Optional[float] = None
    revenue_usd: Optional[float] = None
    duration_min: Optional[float] = None


class DispatchEventAnalytics(BaseModel):
    total: int
    # running dispatches have no end yet, so they're left out of the time-based charts
    open_dispatches: int
    modes: list[DispatchModeSummary]
    days: list[DispatchDay]
    hours: list[DispatchHour]
    sources: list[DispatchCount]
    dispatches: list[DispatchPoint]
