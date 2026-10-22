from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.system_telemetry import StateSegment


class WeatherActualBase(BaseModel):
    temp_c: Optional[Decimal] = Field(default=None, ge=-60, le=65)
    ghi_wm2: Optional[Decimal] = Field(default=None, ge=0, le=1500)
    humidity_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    wind_ms: Optional[Decimal] = Field(default=None, ge=0, le=80)
    cloud_fraction: Optional[Decimal] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def has_a_value(self):
        if all(v is None for v in (self.temp_c, self.ghi_wm2, self.humidity_pct, self.wind_ms, self.cloud_fraction)):
            raise ValueError("Give at least one weather value")
        return self


class WeatherActualCreate(WeatherActualBase):
    station_id: int
    ts: datetime


class WeatherActualUpdate(WeatherActualBase):
    pass


class WeatherActualOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    station_id: int
    ts: datetime
    station_code: Optional[str] = None
    temp_c: Optional[Decimal] = None
    ghi_wm2: Optional[Decimal] = None
    humidity_pct: Optional[Decimal] = None
    wind_ms: Optional[Decimal] = None
    cloud_fraction: Optional[Decimal] = None
    dew_point_c: Optional[float] = None


class WeatherActualPage(BaseModel):
    items: list[WeatherActualOut]
    total: int
    page: int
    page_size: int


class WeatherStationOut(BaseModel):
    station_id: int
    station_code: str
    provider: Optional[str] = None
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    readings: int = 0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None


class BulkWeatherRowError(BaseModel):
    row: int
    errors: list[str]


class BulkWeatherResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkWeatherRowError]
    stations: list[str] = []


class WeatherStateTimeline(BaseModel):
    states: list[str]
    segments: list[StateSegment]


class WeatherSeries(BaseModel):
    station_id: int
    station_code: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int
    raw_interval_seconds: Optional[int] = None
    points: list[dict[str, Any]]
    timelines: dict[str, WeatherStateTimeline]
    refs: dict[str, Optional[float]] = {}
