"""Heat-load prediction (thermal design): the heat the HVAC / TMS must reject - the enclosure heat balance (battery
ohmic + entropic, PCS, aux electronics, solar, envelope, thermal mass), calibrated to a measured reference; an operational
forecast by issue vintage (dispatch plan + weather -> RC grey-box + LightGBM quantile residual); and the design sizing
(coincident worst case at end-of-life resistance, margin, N + 1, duty curve).

  data.py      time-aligned BMS / PCS / EMS / HVAC streams, weather (measured GHI or clear-sky), master data
  balance.py   heat terms per interval, closure residual, calibration, battery-heat and PCS-loss sub-models
  forecast.py  issue-vintage forecast: plan, drivers, RC physics, quantile residual, backtest scores
  design.py    sizing at the design condition, load-duration / duty, hot-spot check
  run.py       one run over several battery systems
  store.py     battery_ml.heatload_run / heatload_ledger / heatload_forecast_point, v_heatload_daily
  router.py    the API (URL prefix /heatload)
"""
from usecases.heatload.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
