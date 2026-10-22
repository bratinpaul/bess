"""The algorithms the SOH use case can train, by model_run.model_type."""
from core.base import BaseRegressor
from usecases.soh.models.lightgbm_model import LightGBMSohModel
from usecases.soh.models.xgboost_model import XGBoostSohModel

MODELS: dict[str, type[BaseRegressor]] = {m.key: m for m in (XGBoostSohModel, LightGBMSohModel)}
