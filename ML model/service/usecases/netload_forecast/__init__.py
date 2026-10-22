"""Net-load & demand / peak forecasting: P10 / P50 / P90 of the site's 5-min net load (gross load - behind-the-meter
generation) up to 48 h ahead per metering point, and the daily billing-window peak (size, time, exceedance of a
threshold) - to position the BESS for peak shaving and demand-charge cuts.

  features.py   demand_telemetry -> 5-min net / gross / BTM series; weather actuals and forecast runs; calendar day
                types; demand tariff window; direct multi-horizon rows (history, calendar, weather-as-forecast, BTM)
  models/       baselines.py (seasonal naïve on the same day type, SARIMAX with workday + weather), gbm.py (LightGBM
                Huber P50 + quantile P10/P90, anchored, CQR), nbeats.py (N-BEATS-style hourly MLP with covariates),
                peak.py (daily peaks from a path, held-out peak calibration, peak-exceedance classifier)
  trainer.py    split per metering point in time, fit, backtest from common origins, load + peak scores, live forecast
  store.py      battery_ml.netload_forecast_run / _score / _point / _peak and the model files
  router.py     the API (URL prefix /netload-forecast)
"""
from usecases.netload_forecast.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
