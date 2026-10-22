"""LightGBM regressor for SOH estimation (optionally with linear trees, which can follow a trend)."""
from pathlib import Path
from typing import Any, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd

from core.base import BaseRegressor, FitReport


class LightGBMSohModel(BaseRegressor):
    key = "lightgbm"
    label = "LightGBM"
    file_suffix = ".txt"
    param_specs = [
        {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 10, "max": 5000, "step": 10},
        {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
        {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 15, "min": 2, "max": 512, "step": 1},
        {"name": "max_depth", "label": "Max tree depth (-1 = no limit)", "type": "int", "default": -1, "min": -1, "max": 16, "step": 1},
        {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 5, "min": 1, "max": 500, "step": 1},
        {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
        {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
        {"name": "reg_alpha", "label": "L1 regularisation", "type": "float", "default": 0, "min": 0, "max": 100, "step": 0.1},
        {"name": "reg_lambda", "label": "L2 regularisation", "type": "float", "default": 0, "min": 0, "max": 100, "step": 0.1},
        {"name": "linear_tree", "label": "Linear trees", "type": "bool", "default": False,
         "help": "Fits a linear model in each leaf, so predictions can follow a trend beyond the training range."},
        {"name": "early_stopping_rounds", "label": "Early stopping (0 = off)", "type": "int", "default": 0, "min": 0, "max": 500, "step": 5,
         "help": "Stops when the test error hasn't improved for this many rounds (the test rows then also steer training)."},
    ]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        super().__init__(params, seed)
        self._model: Optional[lgb.LGBMRegressor] = None  # while training
        self._booster: Optional[lgb.Booster] = None  # loaded from a model file

    @property
    def extrapolates(self) -> bool:
        return bool(self.params.get("linear_tree"))

    def fit(self, X: pd.DataFrame, y: np.ndarray, X_valid: Optional[pd.DataFrame] = None,
            y_valid: Optional[np.ndarray] = None, early_stopping_rounds: int = 0,
            init_model: Optional[BaseRegressor] = None) -> FitReport:
        self._model = lgb.LGBMRegressor(**self.params, random_state=self.seed, verbose=-1, subsample_freq=1, n_jobs=4)
        report = FitReport()
        # fine-tuning: continue boosting from the init model's trees
        init = None
        if init_model is not None:
            init = init_model._model.booster_ if init_model._model is not None else init_model._booster
        if X_valid is None:
            self._model.fit(X, y, init_model=init)
            return report
        callbacks = [lgb.early_stopping(early_stopping_rounds, verbose=False)] if early_stopping_rounds else []
        self._model.fit(X, y, eval_set=[(X, y), (X_valid, y_valid)], eval_names=["train", "valid"],
                        eval_metric=["rmse", "mae"], callbacks=callbacks, init_model=init)
        ev = self._model.evals_result_
        report.curve = [{"iteration": i + 1, "train_rmse": ev["train"]["rmse"][i], "valid_rmse": ev["valid"]["rmse"][i],
                         "train_mae": ev["train"]["l1"][i], "valid_mae": ev["valid"]["l1"][i]}
                        for i in range(len(ev["train"]["rmse"]))]
        report.best_iteration = self._model.best_iteration_ if early_stopping_rounds and self._model.best_iteration_ else None
        return report

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._model.predict(X) if self._model is not None else self._booster.predict(X)

    def gain_importance(self) -> dict[str, float]:
        booster = self._model.booster_ if self._model is not None else self._booster
        return dict(zip(booster.feature_name(), booster.feature_importance(importance_type="gain").astype(float)))

    @property
    def estimator(self) -> Any:
        return self._model

    def save(self, path: Path) -> None:
        self._model.booster_.save_model(str(path))

    @classmethod
    def load(cls, path: Path) -> "LightGBMSohModel":
        model = cls()
        model._booster = lgb.Booster(model_file=str(path))
        return model
