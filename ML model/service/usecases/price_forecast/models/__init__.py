"""The price forecasters: baselines (seasonal naïve, SARIMA), primary (LightGBM / XGBoost quantile), deep
(N-BEATS-style MLP) and spike handling (classifier + regressors)."""
from usecases.price_forecast.models.base import QUANTILES, ForecastError, Forecaster, TrainData
from usecases.price_forecast.models.baselines import Sarima, SeasonalNaive
from usecases.price_forecast.models.gbm import LightGBMQuantile, XGBoostQuantile
from usecases.price_forecast.models.nbeats import NBeatsMLP
from usecases.price_forecast.models.spike import SpikeHybrid

FORECASTERS: dict[str, type[Forecaster]] = {
    cls.key: cls for cls in (SeasonalNaive, Sarima, LightGBMQuantile, XGBoostQuantile, NBeatsMLP, SpikeHybrid)}
BASELINE = SeasonalNaive.key  # always trained: the skill reference


def clean_params(cls: type[Forecaster], params: dict) -> dict:
    """Defaults for missing values, types and ranges enforced."""
    out = {}
    for spec in cls.param_specs:
        value = params.get(spec["name"], spec["default"])
        if value in (None, ""):
            value = spec["default"]
        value = int(value) if spec["type"] == "int" else float(value)
        if not spec["min"] <= value <= spec["max"]:
            raise ForecastError(f"{cls.label}: {spec['label']} must be between {spec['min']} and {spec['max']}")
        out[spec["name"]] = value
    unknown = set(params) - set(out)
    if unknown:
        raise ForecastError(f"Unknown parameter(s) for {cls.label}: {', '.join(sorted(unknown))}")
    return out


__all__ = ["BASELINE", "FORECASTERS", "QUANTILES", "ForecastError", "Forecaster", "TrainData", "clean_params"]
