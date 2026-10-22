from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

LinkedAssetType = Literal[
    "battery_system", "battery_container", "battery_pack", "battery_module", "pcs", "ems_controller", "hvac_unit"
]


class AlarmEventBase(BaseModel):
    start_time: datetime
    end_time: Optional[datetime] = None
    alarm_catalog_id: int
    # the catalog's severity when left out
    severity_level: Optional[int] = Field(default=None, ge=0, le=3)
    # only used when no asset is linked; a linked asset is named after its master-data record
    asset_type: Optional[str] = Field(default=None, max_length=50)
    asset_code: Optional[str] = Field(default=None, max_length=100)
    linked_asset_type: Optional[LinkedAssetType] = None
    linked_asset_id: Optional[int] = None
    trigger_value: Optional[Decimal] = None
    threshold_value: Optional[Decimal] = None
    unit: Optional[str] = Field(default=None, max_length=20)
    acknowledged_by: Optional[str] = Field(default=None, max_length=100)
    acknowledged_at: Optional[datetime] = None

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def check_times(self):
        if self.end_time and self.end_time < self.start_time:
            raise ValueError("end time can't be before the start time")
        if (self.acknowledged_by is None) != (self.acknowledged_at is None):
            raise ValueError("give both who acknowledged the alarm and when, or neither")
        if self.acknowledged_at and self.acknowledged_at < self.start_time:
            raise ValueError("an alarm can't be acknowledged before it started")
        if (self.linked_asset_type is None) != (self.linked_asset_id is None):
            raise ValueError("give both the linked asset type and id, or neither")
        return self


class AlarmEventCreate(AlarmEventBase):
    # generated (ALM-00073 ...) when left out
    alarm_id: Optional[str] = Field(default=None, max_length=50)


class AlarmEventUpdate(AlarmEventBase):
    pass


class AlarmEventOut(BaseModel):
    alarm_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    # derived
    status: Literal["Active", "Cleared"]
    duration_min: Optional[float] = None
    start_date: date
    # from the catalog
    alarm_catalog_id: int
    source: str
    alarm_code: str
    alarm_type: str
    description: str
    probable_cause: Optional[str] = None
    severity_level: int
    severity_name: Optional[str] = None
    # asset
    asset_type: Optional[str] = None
    asset_code: Optional[str] = None
    linked_asset_type: Optional[str] = None
    linked_asset_id: Optional[int] = None
    linked_asset_name: Optional[str] = None
    asset_match: Optional[str] = None
    battery_system_id: Optional[int] = None
    system_name: Optional[str] = None
    trigger_value: Optional[Decimal] = None
    threshold_value: Optional[Decimal] = None
    unit: Optional[str] = None
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AlarmEventStats(BaseModel):
    total: int
    active: int
    acknowledged: int
    critical: int
    mean_minutes_to_clear: Optional[float] = None
    by_source: dict[str, int]
    by_severity: dict[str, int]


class AlarmEventPage(BaseModel):
    items: list[AlarmEventOut]
    total: int
    page: int
    page_size: int
    stats: AlarmEventStats


class AlarmEventAssetOption(BaseModel):
    asset_type: str
    asset_id: int
    name: str
    battery_system_id: Optional[int] = None


class AlarmEventCatalogOption(BaseModel):
    alarm_catalog_id: int
    source: str
    alarm_code: str
    alarm_type: str
    severity_level: int
    asset_type: Optional[str] = None
    threshold: Optional[Decimal] = None
    unit: Optional[str] = None


class AlarmEventLookups(BaseModel):
    catalog: list[AlarmEventCatalogOption]
    assets: list[AlarmEventAssetOption]
    severities: list[dict]
    systems: list[dict]


class BulkAlarmEventRowError(BaseModel):
    row: int
    alarm_id: Optional[str] = None
    errors: list[str]


class BulkAlarmEventResult(BaseModel):
    filename: str
    sheet: Optional[str] = None
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkAlarmEventRowError]
    # rows whose asset was linked to a master-data record
    assets_linked: int
    ignored_columns: list[str] = []


# ---------------------------------------------------------------- analytics (graphical tab)


class AlarmCount(BaseModel):
    key: str
    count: int


class AlarmSeverityCount(BaseModel):
    severity_level: int
    severity_name: str
    count: int
    acknowledged: int
    mean_minutes_to_ack: Optional[float] = None


class AlarmDailyCount(BaseModel):
    date: date
    # alarms started that day, per severity level 0..3
    by_severity: list[int]


class AlarmCodeCount(BaseModel):
    source: str
    alarm_code: str
    description: Optional[str] = None
    count: int
    share_pct: float
    mean_duration_min: Optional[float] = None


class AlarmAssetCount(BaseModel):
    asset_type: Optional[str] = None
    asset_name: str
    source: str
    count: int


class AlarmSourceDuration(BaseModel):
    source: str
    cleared: int
    mean_duration_min: Optional[float] = None
    max_duration_min: Optional[float] = None


class AlarmDurationPoint(BaseModel):
    alarm_id: str
    start_time: datetime
    duration_min: float
    severity_level: int
    source: str
    alarm_code: str


class AlarmEventAnalytics(BaseModel):
    total: int
    by_source: list[AlarmCount]
    by_severity: list[AlarmSeverityCount]
    by_type: list[AlarmCount]
    daily: list[AlarmDailyCount]
    hour_of_day: list[int]
    top_codes: list[AlarmCodeCount]
    top_assets: list[AlarmAssetCount]
    duration_by_source: list[AlarmSourceDuration]
    durations: list[AlarmDurationPoint]
