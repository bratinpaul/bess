"""Request and response bodies of the SOH use case."""
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SohEstimateResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    predicted_soh_pct: float
    model_version: str
    # the run id the prediction came from
    model_key: str
    run_id: int
    # inputs outside the range seen in training: {feature, value, min, max}
    out_of_range: list[dict[str, Any]] = []


class FeatureRange(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None


class ModelInfo(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_version: str
    trained_at: str
    target: str
    features: list[str]
    feature_ranges: dict[str, FeatureRange]
    feature_importances: dict[str, float]
    metrics: dict[str, float]
    caveat: str
    # the training run (Model Training page) the model comes from
    run_id: int
    model_type: Optional[str] = None
    grain: Optional[str] = None
    feature_labels: dict[str, str] = {}
    run_name: Optional[str] = None
    # the model's hyper-parameters and the data it was trained on
    params: dict[str, Any] = {}
    data_selection: dict[str, Any] = {}
    warnings: list[str] = []
    is_active: bool = False
    # plant awareness: a base model (all / several plants) or a battery system (plant) model
    scope: Literal["base", "system"] = "base"
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    battery_system_id: Optional[int] = None
    system_name: Optional[str] = None
    training_mode: Literal["scratch", "finetune"] = "scratch"
    parent_run_id: Optional[int] = None
    # battery systems the run trained on (None = every system, runs from before)
    systems: Optional[list[int]] = None
    holdout_system_id: Optional[int] = None
    metrics_by_system: Optional[dict[str, Any]] = None
    holdout_metrics: Optional[dict[str, Any]] = None
    # why this model was chosen for "active": system default, base default, latest base run ...
    chosen_as: Optional[str] = None


class SampleReading(BaseModel):
    day: str
    system_name: Optional[str] = None
    values: dict[str, Optional[float]]
    # the SOH recorded for that reading (to compare with the prediction)
    actual_soh_pct: Optional[float] = None


class SystemAverage(BaseModel):
    """A battery system's mean of a model's features (SOH Estimator "Training averages")."""
    battery_system_id: int
    system_name: Optional[str] = None
    values: dict[str, Optional[float]]
    rows: int
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    # "training" = the system's rows inside the model's training data; "history" = all its rows (none were there)
    scope: Literal["training", "history"]
    # mean recorded SOH over the same rows
    actual_soh_pct: Optional[float] = None


# ---------------------------------------------------------------- training


class DataSelectionIn(BaseModel):
    grain: Literal["5min", "hour", "day"] = "hour"
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    feature_groups: list[str] = Field(default_factory=list)
    # train only on time buckets that have module telemetry
    module_rows_only: bool = True
    # include rows the realtime batch loaded from snapshot files (e.g. simulator output)
    include_snapshots: bool = False
    # base = plant-agnostic (several battery systems); system = one plant
    scope: Literal["base", "system"] = "base"
    # the plant of a system model
    battery_system_id: Optional[int] = None
    # base models: train on these battery systems only (None = every system with data)
    systems: Optional[list[int]] = None
    # base models: leave this battery system out of training and score the model on it
    holdout_system_id: Optional[int] = None


class TrainRequest(DataSelectionIn):
    model_config = ConfigDict(protected_namespaces=())

    model_type: Literal["xgboost", "lightgbm"]
    params: dict[str, Any] = Field(default_factory=dict)
    run_name: Optional[str] = Field(default=None, max_length=120)
    split_method: Literal["chronological", "random"] = "chronological"
    # keep only features with at least this share of the importance (0 = use every feature of the chosen groups)
    min_importance_pct: float = Field(default=1.0, ge=0, lt=100)
    # auto = permutation for LightGBM linear trees, gain otherwise
    importance_method: Literal["auto", "gain", "permutation"] = "auto"
    test_fraction: float = Field(default=0.2, ge=0.05, le=0.5)
    random_state: int = 42
    # system models: from scratch, or fine-tuned from a base run (parent_run_id) with this plant's rows
    training_mode: Literal["scratch", "finetune"] = "scratch"
    parent_run_id: Optional[int] = None
