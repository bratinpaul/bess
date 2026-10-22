"""Regression scores and feature-importance shares."""
import math
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    explained_variance_score,
    max_error,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
)


def finite(v) -> Optional[float]:
    v = float(v)
    return v if math.isfinite(v) else None


def regression_scores(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Optional[float]]:
    many = len(y_true) > 1 and np.std(y_true) > 0  # R^2 / explained variance need spread in the actual values
    return {
        "r2": finite(r2_score(y_true, y_pred)) if many else None,
        "mae": finite(mean_absolute_error(y_true, y_pred)),
        "rmse": finite(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mape_pct": finite(mean_absolute_percentage_error(y_true, y_pred) * 100),
        "max_error": finite(max_error(y_true, y_pred)),
        "median_ae": finite(median_absolute_error(y_true, y_pred)),
        "explained_variance": finite(explained_variance_score(y_true, y_pred)) if many else None,
    }


def shares(raw: dict[str, float]) -> dict[str, float]:
    """Importance values as shares of their total, largest first."""
    total = sum(raw.values()) or 1.0
    return {f: v / total for f, v in sorted(raw.items(), key=lambda kv: -kv[1])}


def permutation_shares(estimator, X: pd.DataFrame, y: np.ndarray, seed: int) -> dict[str, float]:
    """Share of the RMSE increase when each feature is shuffled (negative effects count as 0)."""
    result = permutation_importance(estimator, X, y, n_repeats=5, random_state=seed, scoring="neg_root_mean_squared_error")
    return shares({f: max(0.0, float(v)) for f, v in zip(X.columns, result.importances_mean)})
