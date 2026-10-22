from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _code(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Code is required")
    return value


# ---------------------------------------------------------------- EMS controller


class EmsControllerBase(BaseModel):
    ems_code: str = Field(min_length=1, max_length=100)
    battery_system_id: int
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    control_mode: Optional[str] = None

    @field_validator("ems_code", mode="before")
    @classmethod
    def trim_code(cls, value):
        return _code(value) if isinstance(value, str) else value


class EmsControllerCreate(EmsControllerBase):
    pass


class EmsControllerUpdate(EmsControllerBase):
    pass


class EmsControllerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ems_id: int
    ems_code: str
    battery_system_id: Optional[int] = None
    system_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    control_mode: Optional[str] = None
    source_uuid: Optional[UUID] = None


# ---------------------------------------------------------------- HVAC unit


class HvacUnitBase(BaseModel):
    hvac_code: str = Field(min_length=1, max_length=100)
    battery_system_id: int
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    hvac_type: Optional[str] = None
    cooling_capacity_kw: Optional[Decimal] = Field(default=None, ge=0)
    status: Optional[str] = None

    @field_validator("hvac_code", mode="before")
    @classmethod
    def trim_code(cls, value):
        return _code(value) if isinstance(value, str) else value


class HvacUnitCreate(HvacUnitBase):
    pass


class HvacUnitUpdate(HvacUnitBase):
    pass


class HvacUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hvac_id: int
    hvac_code: str
    battery_system_id: Optional[int] = None
    system_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    hvac_type: Optional[str] = None
    cooling_capacity_kw: Optional[Decimal] = None
    status: Optional[str] = None
    source_uuid: Optional[UUID] = None
