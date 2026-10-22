from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SocMethod = Literal["FULL_CHARGE", "FULL_DISCHARGE", "LAB_RPT", "REST_OCV"]  # soc_reference_method_check
SOC_METHODS: tuple[str, ...] = SocMethod.__args__


class SocReferenceUpdate(BaseModel):
    """The editable values of a reference point (the system and timestamp are its key)."""

    soc_true_pct: float = Field(ge=0, le=100)
    method: Optional[SocMethod] = None
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def blank_note(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


class SocReferenceOut(BaseModel):
    system_id: int
    system_name: Optional[str] = None
    ts: datetime
    soc_true_pct: float
    method: Optional[str] = None
    note: Optional[str] = None
    # read-only: the system's telemetry at that moment and the estimators' error against the reference
    bms_soc_pct: Optional[float] = None
    coulomb_soc_pct: Optional[float] = None
    error_vs_bms: Optional[float] = None
    error_vs_coulomb: Optional[float] = None
    mode_code: Optional[str] = None


class SocRefSystem(BaseModel):
    system_id: int
    system_name: str
    site_name: Optional[str] = None
    points: int
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
