"""SOH estimation: XGBoost / LightGBM regressors of battery state of health, trained on BMS and module features.

  features.py   training dataset (feature groups, time grain) from system_telemetry and module_telemetry
  models/       one BaseRegressor per algorithm (xgboost_model.py, lightgbm_model.py)
  trainer.py    SohTrainer: the shared training flow on the SOH target, plus SOH data warnings
  schemas.py    request / response bodies
  router.py     the API (SOH Estimator and Model Training endpoints)

The package interface main.py uses: NAME (URL prefix and model_run.use_case), router, status().
"""
from usecases.soh.router import USE_CASE as NAME, router, status

__all__ = ["NAME", "router", "status"]
