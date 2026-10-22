"""Temperature forecasting: cell max, IGBT, coolant return and enclosure temperature 5-60 min ahead (P10 / P50 / P90)
per asset, with threshold-exceedance evaluation.

  features.py   battery_telemetry.v_thermal_features (5-min join of the BMS / PCS / HVAC / EMS hypertables with the
                rolling 1 h features of the *_thermal_15m continuous aggregates), input guards, target definitions
  physics.py    grey-box first-order RC model per target and asset (steady state + exponential approach)
  trainer.py    rows per origin and horizon (direct multi-horizon), LightGBM quantile models on the RC residual,
                baselines (persistence, seasonal naïve), scores incl. exceedance recall, online and stateless predict
  store.py      battery_ml.thermal_forecast_run / _score / _point and the model files (per-asset registry inside)
  router.py     the API (URL prefix /thermal-forecast)
"""
from usecases.thermal_forecast.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
