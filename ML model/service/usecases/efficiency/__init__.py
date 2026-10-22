"""PCS conversion efficiency at every operating point and round-trip efficiency over charge-discharge cycles.

  features.py   pcs_telemetry + pcs master -> operating points (load fraction, direction, |S|, PF, DC voltage,
                temperatures, AC voltage / frequency, grid service, asset age); target efficiency_pct
  models/       greybox.py (P_loss = a + b·I + c·I², the backbone), gam.py (additive splines), residual.py
                (LightGBM / XGBoost on the grey-box residual, TreeSHAP)
  cycles.py     cycles per unit -> measured DC / AC / system RTE; Ridge regression of the DC RTE
  trainer.py    one run: the three models on one split, scores, health (a / b / c, weekly loss index), curves,
                cycles with the AC / system RTE composed from the PCS model
  estimator.py  one operating point (η per model, loss breakdown, SHAP) and one cycle (DC / AC / system RTE)
  store.py      battery_ml.efficiency_run / efficiency_score / efficiency_cycle and the model files
  router.py     the API (URL prefix /efficiency)
"""
from usecases.efficiency.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
