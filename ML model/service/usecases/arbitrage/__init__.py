"""Energy arbitrage / dispatch optimization: a MILP that schedules charge / discharge (and FREQ_REG capacity) against
the day-ahead price forecast, backtested on what actually cleared, plus the Dispatch Viewer's read model.

  data.py       inputs from the arbitrage tables (battery_opt_param, efficiency / degradation curves, POI limits,
                grid_charge, as_price / as_award, decision_state, price_forecast / price_scenario, rt / dam prices)
  optimizer.py  the MILP on scipy.optimize.milp (HiGHS): deterministic or two-stage stochastic with CVaR
  backtest.py   a study = receding horizon day by day, executed at rt_price, perfect-foresight oracle, sanity checks
  store.py      battery_ml.arb_study / arb_study_day / arb_backtest + the decision chain (optimization_run.study_id)
  view.py       one day of the pack's run or a study for the viewer
  router.py     the API (URL prefix /arbitrage)
"""
from usecases.arbitrage.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
