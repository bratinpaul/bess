from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OcvPointUpdate(BaseModel):
    """The editable value of a curve point (chemistry, direction, temperature and SOC are its key)."""

    ocv_v: float = Field(gt=0, le=6)


class OcvPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chemistry: str
    direction: str
    temp_c: float
    soc_pct: float
    ocv_v: float


class OcvCurveSummary(BaseModel):
    """One curve (chemistry x direction x temperature) with its points in SOC order."""

    chemistry: str
    direction: str
    temp_c: float
    points: int
    soc_min: Optional[float] = None
    soc_max: Optional[float] = None
    ocv_min: Optional[float] = None
    ocv_max: Optional[float] = None
    monotonic: bool = True
    soc: list[float] = []
    ocv: list[float] = []
