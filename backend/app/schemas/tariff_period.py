from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PriceLevel = Literal["SUPER_OFF_PEAK", "OFF_PEAK", "SHOULDER", "SHOULDER_HIGH", "PEAK"]
DayType = Literal["ALL", "WEEKDAY", "WEEKEND"]


class TariffPeriodBase(BaseModel):
    ems_id: Optional[int] = None  # None = every EMS
    band_code: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z0-9_]+$")
    band_name: str = Field(min_length=1, max_length=100)
    price_level: PriceLevel
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    day_type: DayType = "ALL"
    season: str = Field(default="ALL", min_length=1, max_length=30)
    reference_price_mwh: Optional[Decimal] = Field(default=None, ge=0)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("band_code", "season", mode="before")
    @classmethod
    def upper(cls, value):
        return value.strip().upper().replace(" ", "_") if isinstance(value, str) else value

    @field_validator("band_name", "note", mode="before")
    @classmethod
    def trim(cls, value, info):
        if isinstance(value, str):
            value = value.strip()
            if value == "" and info.field_name == "note":
                return None
        return value

    @model_validator(mode="after")
    def check_ranges(self):
        if self.end_hour <= self.start_hour:
            raise ValueError("End hour must be after the start hour (the band covers [start, end), up to 24)")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Valid to must be on or after valid from")
        return self


class TariffPeriodCreate(TariffPeriodBase):
    pass


class TariffPeriodUpdate(TariffPeriodBase):
    pass


class TariffPeriodOut(TariffPeriodBase):
    model_config = ConfigDict(from_attributes=True)

    tariff_period_id: int
    ems_code: Optional[str] = None
    site_name: Optional[str] = None
    created_at: datetime


class TariffEmsOption(BaseModel):
    ems_id: int
    ems_code: str
    site_name: Optional[str] = None


class TariffPeriodLookups(BaseModel):
    price_levels: list[str]
    day_types: list[str]
    seasons: list[str]
    ems: list[TariffEmsOption]
