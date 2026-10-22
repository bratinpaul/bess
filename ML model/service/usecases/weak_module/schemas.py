"""Request bodies of the weak module use case."""
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class WindowIn(BaseModel):
    battery_system_id: int
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    grain: Literal["day", "hour"] = "day"


class DetectRequest(WindowIn):
    feature_groups: list[str] = Field(default_factory=lambda: ["module_deviation", "pack_deviation", "imbalance",
                                                               "under_load", "balancing"])
    if_params: dict[str, Any] = Field(default_factory=dict)
    db_params: dict[str, Any] = Field(default_factory=dict)
    # a model flags a module when at least this share of its rows (days) is anomalous
    min_anomalous_share: float = Field(default=0.4, gt=0, le=1)
    run_name: Optional[str] = Field(default=None, max_length=120)
    random_state: int = 42


class ScoreRequest(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    run_name: Optional[str] = Field(default=None, max_length=120)
