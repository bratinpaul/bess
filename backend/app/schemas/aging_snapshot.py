from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AgingSnapshotUpdate(BaseModel):
    """The editable values of a snapshot (the key - system and snapshot date - is fixed)."""

    age_days: Optional[int] = Field(default=None, ge=0)
    calendar_age_years: Optional[float] = Field(default=None, ge=0)
    cum_throughput_mwh: Optional[float] = Field(default=None, ge=0)
    equiv_full_cycles: Optional[float] = Field(default=None, ge=0)
    avg_dod_pct: Optional[float] = Field(default=None, ge=0, le=100)
    avg_cell_temp_c: Optional[float] = Field(default=None, ge=-40, le=100)
    days_at_high_soc: Optional[float] = Field(default=None, ge=0)
    soh_pct: Optional[float] = Field(default=None, ge=0, le=120)
    internal_resistance_mohm: Optional[float] = Field(default=None, ge=0)
    rul_cycles: Optional[float] = Field(default=None, ge=0)
    rul_days: Optional[int] = Field(default=None, ge=0)
    is_censored: Optional[bool] = None
    eol_reached: Optional[bool] = None


class AgingSnapshotOut(AgingSnapshotUpdate):
    model_config = ConfigDict(from_attributes=True)

    system_id: int
    system_code: Optional[str] = None
    snapshot_date: date


class AgingSnapshotPage(BaseModel):
    items: list[AgingSnapshotOut]
    total: int
    page: int
    page_size: int


class AgingSystemSummary(BaseModel):
    system_id: int
    system_code: str
    snapshots: int
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    latest_soh_pct: Optional[float] = None
    latest_rul_days: Optional[int] = None
    eol_reached: Optional[bool] = None
