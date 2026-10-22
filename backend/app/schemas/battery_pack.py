from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BatteryPackBase(BaseModel):
    container_id: int
    pack_number: Optional[str] = None
    nominal_voltage: Optional[Decimal] = None
    nominal_capacity_ah: Optional[Decimal] = None
    status: Optional[str] = None
    module_count: Optional[int] = Field(default=None, ge=0)


class BatteryPackCreate(BatteryPackBase):
    pass


class BatteryPackUpdate(BatteryPackBase):
    pass


class BatteryPackOut(BatteryPackBase):
    model_config = ConfigDict(from_attributes=True)

    pack_id: int
    source_uuid: Optional[UUID] = None
