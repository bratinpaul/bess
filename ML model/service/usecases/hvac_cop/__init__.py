"""HVAC COP & cooling-performance modeling: measured COP three ways (logged, cooling / power, coolant-loop first law) with
the closure audit, steady-state performance maps (DOE-2-style COP / capacity biquadratics + part-load curve), a
Carnot-anchored η_2nd_law grey-box and a GBM residual; the scorecard (seasonal COP, IPLV-style index, kW/ton, capacity
ratio, cycling), the daily degradation trend with EWMA / CUSUM, setpoint / pre-cool sensitivities and a what-if predictor.

  model.py    data, derived quantities, steady-state filter, models and scores
  monitor.py  closure, scorecard, cycling, daily trend + control charts, sensitivities, map grid
  run.py      one run over several HVAC units
  store.py    battery_ml.hvac_cop_run / hvac_cop_point, v_hvac_cop_daily
  router.py   the API (URL prefix /hvac-cop)
"""
from usecases.hvac_cop.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
