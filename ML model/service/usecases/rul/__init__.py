"""Remaining Useful Life: days and equivalent full cycles to end of life (P10 / P50 / P90) per fleet unit, with EOL
defined by battery_master.eol_criteria (LFP: SOH < 70 % of BOL or resistance > 2x BOL).

  features.py   the fleet from battery_master.v_rul_training + capacity_test (RPT) + lifecycle_event + eol_criteria;
                landmark survival targets (censored units: known-alive time)
  physics.py    empirical fade curve per chemistry (sqrt-t calendar + cycle power law + Arrhenius, batch and shrunk unit
                factors, SOH-band knee) projected to the EOL criteria
  survival.py   Cox PH and a Random Survival Forest in numpy
  trainer.py    leave-one-unit-out backtest of physics / LightGBM / hybrid / Cox / RSF, censoring-aware scores, final
                per-chemistry models, per-unit forecasts and the what-if predict
  store.py      battery_ml.rul_run / _score / _backtest / _forecast and the model files
  router.py     the API (URL prefix /rul)
"""
from usecases.rul.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
