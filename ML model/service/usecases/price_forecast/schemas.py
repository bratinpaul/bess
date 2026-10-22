"""Request bodies of the price forecasting use case."""
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

from usecases.price_forecast.features import FEATURE_GROUPS


class SelectionIn(BaseModel):
    ems_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    feature_groups: list[str] = Field(default_factory=lambda: list(FEATURE_GROUPS))
    spike_threshold: float = Field(default=150.0, gt=0, le=100000, description="5-min price ($/MWh) that marks a spike")


class TrainRequest(SelectionIn):
    models: list[str] = Field(default_factory=lambda: ["sarima", "lightgbm", "xgboost", "nbeats", "spike_hybrid"])
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    horizon_hours: int = Field(default=48, ge=1, le=48)
    test_fraction: float = Field(default=0.2, gt=0.05, lt=0.6)
    origin_step_h: int = Field(default=6, ge=1, le=48, description="hours between backtest origins")
    train_origin_step_h: int = Field(default=2, ge=1, le=24, description="hours between training origins (boosted models)")
    random_state: int = 42
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False
