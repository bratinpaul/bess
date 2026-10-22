from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BatteryProvenanceUpdate(BaseModel):
    """The editable fields of a system's provenance (the system itself is fixed)."""

    manufacturer: Optional[str] = Field(default=None, max_length=120)
    cell_model: Optional[str] = Field(default=None, max_length=120)
    chemistry: str = Field(min_length=1, max_length=40)
    batch_lot: Optional[str] = Field(default=None, max_length=120)
    cell_format: Optional[str] = Field(default=None, max_length=60)
    build_date: Optional[date] = None
    nameplate_kwh: Optional[float] = Field(default=None, gt=0)
    bol_capacity_kwh: Optional[float] = Field(default=None, gt=0)
    bol_resistance_mohm: Optional[float] = Field(default=None, gt=0)
    usage_cycles_per_day: Optional[float] = Field(default=None, ge=0, le=50)
    climate_avg_temp_c: Optional[float] = Field(default=None, ge=-40, le=70)

    @field_validator("manufacturer", "cell_model", "batch_lot", "cell_format", mode="before")
    @classmethod
    def blank_is_none(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v

    @field_validator("chemistry", mode="before")
    @classmethod
    def chemistry_code(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class BatteryProvenanceOut(BatteryProvenanceUpdate):
    model_config = ConfigDict(from_attributes=True)

    system_id: int
    system_code: Optional[str] = None
    # read-only context: the lifecycle COMMISSION event and the chemistry's end-of-life criteria
    commissioned_on: Optional[date] = None
    soh_eol_pct: Optional[float] = None
    resistance_eol_pct: Optional[float] = None


class ProvenanceOptions(BaseModel):
    chemistries: list[str]
    batch_lots: list[str]
    manufacturers: list[str]
    cell_models: list[str]
    cell_formats: list[str]
    eol_criteria: list[dict]
