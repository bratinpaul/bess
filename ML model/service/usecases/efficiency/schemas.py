"""Request bodies of the efficiency use case."""
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from usecases.efficiency.features import FEATURE_GROUPS


class SelectionIn(BaseModel):
    pcs_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    min_load_frac: float = Field(default=0.02, ge=0, le=0.5)
    exclude_snapshots: bool = True
    feature_groups: list[str] = Field(default_factory=lambda: list(FEATURE_GROUPS))


class TrainRequest(SelectionIn):
    split_method: Literal["chronological", "random"] = "chronological"
    test_fraction: float = Field(default=0.2, gt=0, lt=0.9)
    random_state: int = 42
    greybox_params: dict[str, Any] = Field(default_factory=dict)
    gam_params: dict[str, Any] = Field(default_factory=dict)
    booster: Literal["lightgbm", "xgboost"] = "lightgbm"
    booster_params: dict[str, Any] = Field(default_factory=dict)
    major_share: float = Field(default=0.25, gt=0, le=1)
    soc_tolerance_pct: float = Field(default=5.0, ge=0, le=50)
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False


class PointIn(BaseModel):
    """One operating point in plant units (as the telemetry reports it)."""
    pcs_id: int
    direction: Literal["charge", "discharge"]
    p_kw: float = Field(gt=0, description="|AC active power| (kW)")
    power_factor: float = Field(default=1.0, gt=0, le=1)
    dc_voltage_v: Optional[float] = Field(default=None, gt=0)
    igbt_temp_c: Optional[float] = None
    heatsink_temp_c: Optional[float] = None
    inlet_coolant_temp_c: Optional[float] = None
    ambient_temp_c: Optional[float] = None
    ac_voltage_v: Optional[float] = Field(default=None, gt=0)
    ac_frequency_hz: Optional[float] = Field(default=None, gt=0)
    grid_service: Literal["NONE", "FREQ_WATT", "VOLT_VAR"] = "NONE"
    age_years: Optional[float] = Field(default=None, ge=0, le=50)


class CycleIn(BaseModel):
    """A charge-discharge cycle to evaluate: the powers, the SOC window, the period and the conditions."""
    pcs_id: int
    charge_kw: float = Field(gt=0)
    discharge_kw: float = Field(gt=0)
    soc_min_pct: float = Field(default=10, ge=0, le=100)
    soc_max_pct: float = Field(default=85, ge=0, le=100)
    period_hours: float = Field(default=24, gt=0, le=240, description="charge start to next charge start")
    kwh_per_pct: Optional[float] = Field(default=None, gt=0, description="DC kWh per SOC %; default: the unit's")
    cell_temp_avg_c: Optional[float] = None
    fr_share: float = Field(default=0.0, ge=0, le=1)
    direction_changes: int = Field(default=1, ge=1, le=500)
    soh_pct: Optional[float] = Field(default=None, gt=0, le=110)
    aux_kw: Optional[float] = Field(default=None, ge=0, description="average auxiliary + HVAC load; default: the unit's")
    dc_rte_pct: Optional[float] = Field(default=None, gt=50, le=110,
                                        description="enter the battery DC round-trip instead of the regression")
    power_factor: float = Field(default=1.0, gt=0, le=1)
    grid_service: Literal["NONE", "FREQ_WATT", "VOLT_VAR"] = "NONE"
