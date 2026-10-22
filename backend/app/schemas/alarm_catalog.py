from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

AlarmSource = Literal["BMS", "PCS", "HVAC", "EMS"]

REQUIRED_TEXT = ("alarm_code", "alarm_type", "description")


class AlarmCatalogBase(BaseModel):
    alarm_code: str = Field(min_length=1, max_length=100)
    source: AlarmSource
    alarm_type: str = Field(min_length=1, max_length=50)
    severity_level: int = Field(ge=0, le=3)
    asset_type: Optional[str] = Field(default=None, max_length=50)
    description: str = Field(min_length=1, max_length=500)
    probable_cause: Optional[str] = Field(default=None, max_length=500)
    threshold: Optional[Decimal] = None
    unit: Optional[str] = Field(default=None, max_length=20)

    @field_validator("*", mode="before")
    @classmethod
    def trim(cls, value, info):
        """Trim text; empty optional fields become NULL."""
        if isinstance(value, str):
            value = value.strip()
            if value == "" and info.field_name not in REQUIRED_TEXT:
                return None
        return value

    @field_validator("source", mode="before")
    @classmethod
    def upper_source(cls, value):
        return value.upper() if isinstance(value, str) else value


class AlarmCatalogCreate(AlarmCatalogBase):
    pass


class AlarmCatalogUpdate(AlarmCatalogBase):
    pass


class AlarmCatalogOut(AlarmCatalogBase):
    model_config = ConfigDict(from_attributes=True)

    alarm_catalog_id: int
    severity_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AlarmSeverityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    severity_level: int
    severity_name: str


class AlarmCatalogLookups(BaseModel):
    sources: list[str]
    severities: list[AlarmSeverityOut]
    alarm_types: list[str]
    asset_types: list[str]


class BulkAlarmCatalogRowError(BaseModel):
    row: int
    errors: list[str]


class BulkAlarmCatalogResult(BaseModel):
    filename: str
    sheet: Optional[str] = None
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkAlarmCatalogRowError]
    ignored_columns: list[str] = []
