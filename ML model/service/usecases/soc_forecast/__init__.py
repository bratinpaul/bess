"""SOC trajectory forecasting: P10 / P50 / P90 SOC paths at 5-min steps for the next hours, per EMS.

  features.py   SOC series (ems / system / hvac telemetry), dispatch schedule (dispatch_event), typical-day plan,
                coulomb-counting physics (%/kWh charge / discharge, SOC limits) fitted per EMS
  trainer.py    plans per origin, physics roll-forward, LightGBM quantile residual models per plan source, backtest
                (hold / physics / hybrid x typical / scheduled), scores, live forecast with derived energy and
                time to limits
  store.py      battery_ml.soc_forecast_run / _score / _point and the model files
  router.py     the API (URL prefix /soc-forecast)
"""
from usecases.soc_forecast.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
