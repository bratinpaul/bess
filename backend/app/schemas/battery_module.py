from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BatteryModuleBase(BaseModel):
    pack_id: int
    serial_number: Optional[str] = None
    chemistry: Optional[str] = None
    nominal_voltage: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    capacity_ah: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    manufacture_date: Optional[date] = None
    installation_date: Optional[date] = None
    status: Optional[str] = None
    cell_count: Optional[int] = Field(default=None, ge=0)
    soh_pct: Optional[Decimal] = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)


class BatteryModuleCreate(BatteryModuleBase):
    pass


class BatteryModuleUpdate(BatteryModuleBase):
    pass


class BatteryModuleOut(BatteryModuleBase):
    model_config = ConfigDict(from_attributes=True)

    module_id: int
    source_uuid: Optional[UUID] = None
