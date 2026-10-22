"""Gradient boosting on the grey-box residual: r = η_measured - η_greybox (percentage points).

The hybrid prediction is η_greybox + r̂: the physics carries the shape (and extrapolates safely), the trees
learn the interactions it misses (grid service, unit quirks, thermal cross-effects). TreeSHAP contributions
(LightGBM pred_contrib / XGBoost pred_contribs, exact for trees) attribute the residual to the inputs.
"""
from typing import Any, ClassVar, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb

COMMON = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 10, "max": 5000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "reg_lambda", "label": "L2 regularisation", "type": "float", "default": 1, "min": 0, "max": 100, "step": 0.1},
]


class ResidualBooster:
    key: ClassVar[str]
    label: ClassVar[str]
    param_specs: ClassVar[list[dict]]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        p = {s["name"]: s["default"] for s in self.param_specs}
        p.update(params or {})
        self.params = p
        self.seed = seed
        self.model: Any = None
        self.features: list[str] = []
        self.curve: list[dict] = []

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[self.features])

    def gain_importance(self) -> dict[str, float]:
        raise NotImplementedError

    def shap(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Per-row SHAP values (rows × features) and the base value per row."""
        raise NotImplementedError


class LightGBMResidual(ResidualBooster):
    key = "lightgbm"
    label = "LightGBM"
    param_specs = COMMON + [
        {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 15, "min": 2, "max": 512, "step": 1},
        {"name": "max_depth", "label": "Max tree depth (-1 = no limit)", "type": "int", "default": 5, "min": -1, "max": 16, "step": 1},
        {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 40, "min": 1, "max": 2000, "step": 1},
    ]

    def fit(self, X, y, X_valid=None, y_valid=None) -> "LightGBMResidual":
        self.features = list(X.columns)
        self.model = lgb.LGBMRegressor(**self.params, random_state=self.seed, verbose=-1, subsample_freq=1, n_jobs=4)
        if X_valid is None:
            self.model.fit(X, y)
            return self
        self.model.fit(X, y, eval_set=[(X, y), (X_valid, y_valid)], eval_names=["train", "valid"], eval_metric=["rmse"])
        ev = self.model.evals_result_
        self.curve = [{"iteration": i + 1, "train_rmse": ev["train"]["rmse"][i], "valid_rmse": ev["valid"]["rmse"][i]}
                      for i in range(len(ev["train"]["rmse"]))]
        return self

    def gain_importance(self) -> dict[str, float]:
        b = self.model.booster_
        return dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float)))

    def shap(self, X):
        c = self.model.predict(X[self.features], pred_contrib=True)
        return c[:, :-1], c[:, -1]


class XGBoostResidual(ResidualBooster):
    key = "xgboost"
    label = "XGBoost"
    param_specs = COMMON + [
        {"name": "max_depth", "label": "Max tree depth", "type": "int", "default": 4, "min": 1, "max": 16, "step": 1},
        {"name": "min_child_weight", "label": "Min child weight", "type": "float", "default": 20, "min": 0, "max": 1000, "step": 1},
        {"name": "gamma", "label": "Min split loss (gamma)", "type": "float", "default": 0, "min": 0, "max": 10, "step": 0.01},
    ]

    def fit(self, X, y, X_valid=None, y_valid=None) -> "XGBoostResidual":
        self.features = list(X.columns)
        self.model = xgb.XGBRegressor(**self.params, random_state=self.seed, eval_metric=["rmse"], n_jobs=4)
        eval_set = [(X, y)] + ([(X_valid, y_valid)] if X_valid is not None else [])
        self.model.fit(X, y, eval_set=eval_set, verbose=False)
        if X_valid is not None:
            ev = self.model.evals_result()
            tr, va = ev["validation_0"]["rmse"], ev["validation_1"]["rmse"]
            self.curve = [{"iteration": i + 1, "train_rmse": tr[i], "valid_rmse": va[i]} for i in range(len(tr))]
        return self

    def gain_importance(self) -> dict[str, float]:
        return {f: float(v) for f, v in self.model.get_booster().get_score(importance_type="gain").items()}

    def shap(self, X):
        c = self.model.get_booster().predict(xgb.DMatrix(X[self.features]), pred_contribs=True)
        return c[:, :-1], c[:, -1]


BOOSTERS: dict[str, type[ResidualBooster]] = {LightGBMResidual.key: LightGBMResidual, XGBoostResidual.key: XGBoostResidual}
