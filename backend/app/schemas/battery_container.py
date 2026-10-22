from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BatteryContainerBase(BaseModel):
    battery_system_id: int
    container_number: Optional[str] = None
    manufacturer: Optional[str] = None
    installation_date: Optional[date] = None
    status: Optional[str] = None
    container_type: Optional[str] = None
    ip_rating: Optional[str] = None
    fire_suppression: Optional[str] = None


class BatteryContainerCreate(BatteryContainerBase):
    pass


class BatteryContainerUpdate(BatteryContainerBase):
    pass


class BatteryContainerOut(BatteryContainerBase):
    model_config = ConfigDict(from_attributes=True)

    container_id: int
    source_uuid: Optional[UUID] = None
