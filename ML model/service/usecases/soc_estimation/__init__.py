"""SOC estimation / correction: a trustworthy SOC with P10 / P90 per battery system - coulomb-counting drift removed,
especially through LFP's flat mid-SOC region.

  features.py   the 5-min series from battery_master.v_soc_features (+ the reported BMS estimate), anchors
                (soc_reference) and the OCV curve (direction / temperature, slope and inverse)
  ekf.py        extended Kalman filter: coulomb propagation with bias + capacity-gain states, rested-OCV updates
                (hysteresis branch by current direction), FULL_CHARGE hard recalibration
  trainer.py    EKF tuning on the training period, LightGBM quantile corrections (coulomb drift / EKF residual),
                time-split scores vs anchors and the dense sample truth, the live / replay estimator
  store.py      battery_ml.soc_estimation_run / _score / _point / _state and the model files
  router.py     the API (URL prefix /soc-estimation)
"""
from usecases.soc_estimation.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
