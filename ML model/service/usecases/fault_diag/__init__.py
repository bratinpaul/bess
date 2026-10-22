"""Fault classification / diagnosis: a signature / Bayesian diagnosis engine (zero training data, explainable) fused with a
LightGBM / XGBoost classifier (flat or subsystem -> fault hierarchy) trained on the confirmed fault episodes, calibrated,
scored out-of-fold and forward in time; windowed scans write candidates to fault_prediction for operator confirmation;
plus the reliability analytics (Pareto, fishbone) behind the viewer.

  data.py      labelled layer, alarms, 5-min telemetry frame + derived signature signals
  features.py  windows -> telemetry / signature / alarm / context features
  engine.py    signature posterior
  model.py     classifiers, hierarchy, fusion, calibration, scorecard
  run.py       training run, scanning
  analysis.py  overview, Pareto, fishbone
  store.py     battery_ml.fault_diag_*, fault_prediction writes
  router.py    the API (URL prefix /fault-diag)
"""
from usecases.fault_diag.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
