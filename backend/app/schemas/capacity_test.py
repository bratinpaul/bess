from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CapacityTestUpdate(BaseModel):
    """The editable fields of a test (the system it belongs to is fixed)."""

    test_date: date
    age_days: Optional[int] = Field(default=None, ge=0)
    equiv_full_cycles: Optional[float] = Field(default=None, ge=0)
    measured_capacity_kwh: Optional[float] = Field(default=None, ge=0)
    soh_pct: Optional[float] = Field(default=None, ge=0, le=110)  # chk_rpt_soh
    internal_resistance_mohm: Optional[float] = Field(default=None, ge=0)
    test_temp_c: Optional[float] = Field(default=None, ge=-40, le=100)
    method: Optional[str] = Field(default=None, max_length=200)


class CapacityTestOut(CapacityTestUpdate):
    model_config = ConfigDict(from_attributes=True)

    test_id: int
    system_id: int
    system_code: Optional[str] = None


class CapacityTestPage(BaseModel):
    items: list[CapacityTestOut]
    total: int
    page: int
    page_size: int


class CapacityTestSystem(BaseModel):
    system_id: int
    system_code: str
    tests: int
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    first_capacity_kwh: Optional[float] = None
    latest_capacity_kwh: Optional[float] = None
    latest_soh_pct: Optional[float] = None
