from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PcsBase(BaseModel):
    system_id: int
    pcs_code: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    topology: Optional[str] = None
    cooling: Optional[str] = None
    rated_power_kw: Decimal = Field(gt=0)
    rated_apparent_kva: Optional[Decimal] = None
    max_charge_kw: Optional[Decimal] = None
    max_discharge_kw: Optional[Decimal] = None
    rated_ac_voltage_v: Decimal
    ac_frequency_hz: Decimal = Decimal("50.0")
    phases: Literal[1, 3] = 3
    dc_voltage_min_v: Optional[Decimal] = None
    dc_voltage_max_v: Optional[Decimal] = None
    dc_voltage_nom_v: Optional[Decimal] = None
    min_power_factor: Optional[Decimal] = None
    grid_code: Optional[str] = None
    firmware: Optional[str] = None
    commissioned_on: Optional[date] = None
    efficiency_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    grid_mode: Optional[str] = None


class PcsCreate(PcsBase):
    pass


class PcsUpdate(PcsBase):
    pass


class PcsOut(PcsBase):
    model_config = ConfigDict(from_attributes=True)

    pcs_id: int
    source_uuid: Optional[UUID] = None
    created_at: Optional[datetime] = None
