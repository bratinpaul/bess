from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BatterySystemBase(BaseModel):
    site_id: int
    system_name: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    rated_power_mw: Optional[Decimal] = None
    rated_energy_mwh: Optional[Decimal] = None
    nominal_dc_voltage: Optional[Decimal] = None
    status: Optional[str] = None
    chemistry_code: str
    series_cells: int = Field(gt=0)
    parallel_cells: int = Field(gt=0)
    commissioned_on: Optional[date] = None
    bms_firmware: Optional[str] = None


class BatterySystemCreate(BatterySystemBase):
    pass


class BatterySystemUpdate(BatterySystemBase):
    pass


class BatterySystemOut(BatterySystemBase):
    model_config = ConfigDict(from_attributes=True)

    battery_system_id: int
    created_at: Optional[datetime] = None
    source_uuid: Optional[UUID] = None


class BatteryChemistryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chemistry_code: str
    description: str
    nominal_cell_v: Decimal
    min_cell_v: Decimal
    max_cell_v: Decimal
