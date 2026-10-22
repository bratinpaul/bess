"""Electricity-price forecasting: P10 / P50 / P90 of the hourly market price 1-48 h ahead per EMS, for the
arbitrage optimizer and bidding.

  features.py   ems_telemetry -> hourly price / spike / frequency-stress series; TOU bands (ems_tariff_period);
                direct multi-horizon rows (price history, calendar, TOU, grid stress)
  models/       baselines.py (seasonal naïve, SARIMA), gbm.py (LightGBM / XGBoost, Huber P50 + quantile P10/P90,
                anchored on yesterday, conformal calibration), nbeats.py (N-BEATS-style multi-horizon MLP),
                spike.py (spike classifier + regressors)
  trainer.py    split per EMS in time, fit, backtest on common origins, scores (MAE, pinball, coverage, skill vs
                naïve, spike AUC, spread capture), live forecast
  store.py      battery_ml.price_forecast_run / _score / _point and the model files
  router.py     the API (URL prefix /price-forecast)
"""
from usecases.price_forecast.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
