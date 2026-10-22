"""Request bodies of the net-load forecasting use case."""
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from usecases.netload_forecast.features import FEATURE_GROUPS


class SelectionIn(BaseModel):
    mp_ids: list[int] = Field(min_length=1)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    feature_groups: list[str] = Field(default_factory=lambda: list(FEATURE_GROUPS))
    weather_source: Literal["forecast", "actual"] = "forecast"
    peak_threshold_kw: Optional[float] = Field(default=None, gt=0, le=10_000_000,
                                               description="billing-peak threshold; empty = 75th percentile of training peaks")


class TrainRequest(SelectionIn):
    models: list[str] = Field(default_factory=lambda: ["sarima", "lightgbm", "nbeats", "peak_classifier"])
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    horizon_hours: int = Field(default=48, ge=1, le=48)
    test_fraction: float = Field(default=0.25, gt=0.05, lt=0.6)
    origin_step_h: int = Field(default=3, ge=1, le=48, description="hours between backtest origins")
    train_origin_step_h: int = Field(default=2, ge=1, le=24, description="hours between training origins")
    random_state: int = 42
    run_name: Optional[str] = Field(default=None, max_length=120)
    make_default: bool = False
