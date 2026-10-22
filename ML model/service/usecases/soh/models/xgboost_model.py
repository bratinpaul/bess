"""XGBoost regressor for SOH estimation."""
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import xgboost as xgb

from core.base import BaseRegressor, FitReport


class XGBoostSohModel(BaseRegressor):
    key = "xgboost"
    label = "XGBoost"
    file_suffix = ".json"
    param_specs = [
        {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 10, "max": 5000, "step": 10},
        {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
        {"name": "max_depth", "label": "Max tree depth", "type": "int", "default": 4, "min": 1, "max": 16, "step": 1},
        {"name": "min_child_weight", "label": "Min child weight", "type": "float", "default": 1, "min": 0, "max": 100, "step": 0.5},
        {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
        {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
        {"name": "gamma", "label": "Min split loss (gamma)", "type": "float", "default": 0, "min": 0, "max": 10, "step": 0.01},
        {"name": "reg_alpha", "label": "L1 regularisation", "type": "float", "default": 0, "min": 0, "max": 100, "step": 0.1},
        {"name": "reg_lambda", "label": "L2 regularisation", "type": "float", "default": 1, "min": 0, "max": 100, "step": 0.1},
        {"name": "early_stopping_rounds", "label": "Early stopping (0 = off)", "type": "int", "default": 0, "min": 0, "max": 500, "step": 5,
         "help": "Stops when the test error hasn't improved for this many rounds (the test rows then also steer training)."},
    ]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        super().__init__(params, seed)
        self._model: Optional[xgb.XGBRegressor] = None

    def fit(self, X: pd.DataFrame, y: np.ndarray, X_valid: Optional[pd.DataFrame] = None,
            y_valid: Optional[np.ndarray] = None, early_stopping_rounds: int = 0,
            init_model: Optional[BaseRegressor] = None) -> FitReport:
        validating = X_valid is not None
        eval_set = [(X, y), (X_valid, y_valid)] if validating else [(X, y)]
        self._model = xgb.XGBRegressor(**self.params, random_state=self.seed, eval_metric=["rmse", "mae"],
                                       early_stopping_rounds=(early_stopping_rounds or None) if validating else None,
                                       n_jobs=4)
        # fine-tuning: continue boosting from the init model's trees
        base = init_model._model.get_booster() if init_model is not None else None
        self._model.fit(X, y, eval_set=eval_set, verbose=False, xgb_model=base)
        report = FitReport()
        if validating:
            ev = self._model.evals_result()
            tr, va = ev["validation_0"], ev["validation_1"]
            report.curve = [{"iteration": i + 1, "train_rmse": tr["rmse"][i], "valid_rmse": va["rmse"][i],
                             "train_mae": tr["mae"][i], "valid_mae": va["mae"][i]} for i in range(len(tr["rmse"]))]
            best = getattr(self._model, "best_iteration", None) if early_stopping_rounds else None
            report.best_iteration = best + 1 if best is not None else None
        return report

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._model.predict(X)

    def gain_importance(self) -> dict[str, float]:
        return {f: float(v) for f, v in self._model.get_booster().get_score(importance_type="gain").items()}

    @property
    def estimator(self) -> Any:
        return self._model

    def save(self, path: Path) -> None:
        self._model.save_model(str(path))

    @classmethod
    def load(cls, path: Path) -> "XGBoostSohModel":
        model = cls()
        model._model = xgb.XGBRegressor()
        model._model.load_model(str(path))
        return model
