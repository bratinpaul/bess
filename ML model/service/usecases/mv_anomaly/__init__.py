"""Multivariate anomaly detection: abnormal operating states found by looking at BMS / PCS / HVAC / EMS signals
jointly (one wide row per system per 5-min interval), with per-flag attribution.

  features.py   time-aligned telemetry join, derived signals, residuals (ΔV vs SOC/regime, cell temperature vs I²R,
                IGBT vs load), regime / SOC band, frozen / missing sensor rules, alarm labels and training exclusions
  models.py     PCA (Q / T²), Isolation Forest, Elliptic Envelope, dense and windowed (temporal) autoencoders
  trainer.py    split, clean "known good" rows, fit, thresholds (percentile or tuned on training-window alarms),
                smoothing + debounce, evaluation vs alarm_event, attribution, episodes, scoring other windows
  store.py      battery_ml.mv_anomaly_run / mv_anomaly_score (hypertable) and the model files
  router.py     the API (URL prefix /mv-anomaly)
  batch.py      micro-batch: the systems' default models score the newest telemetry into their live runs
"""
from usecases.mv_anomaly.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
