from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class CurrentSensorCalUpdate(BaseModel):
    """The editable values of a calibration (the system and calibration date are its key)."""

    offset_a: Optional[float] = Field(default=None, ge=-1000, le=1000)
    gain_error_pct: Optional[float] = Field(default=None, ge=-100, le=100)
    drift_a_per_day: Optional[float] = Field(default=None, ge=-100, le=100)


class CurrentSensorCalOut(CurrentSensorCalUpdate):
    system_id: int
    system_code: Optional[str] = None
    calibrated_on: date
    # read-only: days from this calibration to today (or to the system's next calibration) and the offset the drift
    # would give by then
    days_since: Optional[int] = None
    projected_offset_a: Optional[float] = None
    superseded_on: Optional[date] = None


class CalSystem(BaseModel):
    system_id: int
    system_code: str
    calibrations: int
