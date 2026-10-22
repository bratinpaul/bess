"""Weak module detection: Isolation Forest and DBSCAN anomaly detection on per-module and per-pack module V/T
deviations (plus imbalance, deviation under load and balancing), one row per module per day or hour.

  features.py   module_telemetry -> module-bucket feature rows (deviation vs system and vs pack)
  models/       one detector per algorithm (isolation_forest.py, dbscan.py) behind models/base.py
  detector.py   runs both, per-module verdicts (WEAK = both models, SUSPECT = one), scores, reasons
  store.py      battery_ml.anomaly_run / anomaly_module_result / anomaly_point and the model files
  schemas.py    request bodies
  router.py     the API (URL prefix /weak-module)
"""
from usecases.weak_module.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
