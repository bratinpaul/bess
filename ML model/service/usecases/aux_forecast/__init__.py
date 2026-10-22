"""Auxiliary / HVAC energy forecasting: the site's parasitic draw (aux_load_kw = HVAC + controls, always a positive
consumption) at 5-min steps 5 min - 24 h ahead (P10 / P50 / P90), with the derived aux energy per interval and day.

  features.py   battery_telemetry.v_aux_features (5-min join of the EMS / HVAC / BMS / PCS hypertables with the rolling
                features of the ems_aux_15m / hvac_thermal_15m continuous aggregates), input guards, the ambient forecast
                as known at an origin (weather_forecast run, else the daily profile)
  physics.py    grey-box per site: controls + (battery heat + envelope + solar gain) / COP(ambient)
  trainer.py    rows per origin and horizon step (direct multi-horizon), pooled LightGBM quantile models on the grey-box
                residual, baselines (persistence, same time yesterday), scores per horizon bucket incl. daily aux kWh,
                online and stateless predict
  store.py      battery_ml.aux_forecast_run / _score / _point / _daily and the model files (per-site registry inside)
  router.py     the API (URL prefix /aux-forecast)
"""
from usecases.aux_forecast.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
