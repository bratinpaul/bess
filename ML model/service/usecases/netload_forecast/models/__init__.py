"""The net-load forecasters: baselines (seasonal naïve on the same day type, SARIMAX), primary (LightGBM quantile,
anchored, CQR), deep (N-BEATS-style MLP) - and the peak-exceedance classifier on daily billing peaks."""
from usecases.netload_forecast.models.base import QUANTILES, ForecastError, Forecaster, TrainData
from usecases.netload_forecast.models.baselines import Sarima, SeasonalNaive
from usecases.netload_forecast.models.gbm import LightGBMQuantile
from usecases.netload_forecast.models.nbeats import NBeatsMLP
from usecases.netload_forecast.models.peak import PeakClassifier

FORECASTERS: dict[str, type[Forecaster]] = {cls.key: cls for cls in (SeasonalNaive, Sarima, LightGBMQuantile, NBeatsMLP)}
BASELINE = SeasonalNaive.key  # always trained: the skill reference
PEAK = PeakClassifier.key
ALL_MODELS = {**FORECASTERS, PEAK: PeakClassifier}


def clean_params(cls, params: dict) -> dict:
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


__all__ = ["ALL_MODELS", "BASELINE", "FORECASTERS", "PEAK", "QUANTILES", "ForecastError", "Forecaster", "TrainData",
           "clean_params"]
