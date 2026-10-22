from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.weather import WeatherStateTimeline

MAX_LEAD = timedelta(days=16)


class WeatherForecastBase(BaseModel):
    temp_c: Optional[Decimal] = Field(default=None, ge=-60, le=65)
    ghi_wm2: Optional[Decimal] = Field(default=None, ge=0, le=1500)

    @model_validator(mode="after")
    def has_a_value(self):
        if self.temp_c is None and self.ghi_wm2 is None:
            raise ValueError("Give the forecast temperature or GHI")
        return self


class WeatherForecastCreate(WeatherForecastBase):
    station_id: int
    issued_at: datetime
    valid_at: datetime

    @model_validator(mode="after")
    def lead_time(self):
        if self.valid_at <= self.issued_at:
            raise ValueError("valid_at must be after issued_at")
        if self.valid_at - self.issued_at > MAX_LEAD:
            raise ValueError("valid_at is more than 16 days after issued_at")
        return self


class WeatherForecastUpdate(WeatherForecastBase):
    pass


class WeatherForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    station_id: int
    issued_at: datetime
    valid_at: datetime
    station_code: Optional[str] = None
    lead_h: Optional[float] = None
    temp_c: Optional[Decimal] = None
    ghi_wm2: Optional[Decimal] = None
    actual_temp_c: Optional[float] = None
    actual_ghi_wm2: Optional[float] = None
    temp_error_c: Optional[float] = None
    ghi_error_wm2: Optional[float] = None


class WeatherForecastPage(BaseModel):
    items: list[WeatherForecastOut]
    total: int
    page: int
    page_size: int


class ForecastRunOut(BaseModel):
    station_id: int
    issued_at: datetime
    points: int
    first_valid: datetime
    last_valid: datetime


class BulkWeatherForecastRowError(BaseModel):
    row: int
    errors: list[str]


class BulkWeatherForecastResult(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkWeatherForecastRowError]
    stations: list[str] = []
    runs: int = 0


class WeatherForecastSeries(BaseModel):
    station_id: int
    station_code: Optional[str] = None
    issued_at: Optional[datetime] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bucket_seconds: int = 3600
    raw_interval_seconds: Optional[int] = 3600
    points: list[dict[str, Any]]
    timelines: dict[str, WeatherStateTimeline]
    refs: dict[str, Optional[float]] = {}


class LeadSkill(BaseModel):
    lead_h: int
    n: int
    temp_mae: Optional[float] = None
    temp_bias: Optional[float] = None
    ghi_mae: Optional[float] = None
    ghi_bias: Optional[float] = None
    ghi_n: int = 0


class WeatherForecastSkill(BaseModel):
    station_id: int
    runs: int
    matched: int
    forecasts: int
    temp_mae: Optional[float] = None
    temp_bias: Optional[float] = None
    temp_rmse: Optional[float] = None
    ghi_mae: Optional[float] = None
    ghi_bias: Optional[float] = None
    ghi_rmse: Optional[float] = None
    by_lead: list[LeadSkill]
