"""The interfaces a use case implements: one BaseRegressor subclass per algorithm, one BaseTrainer subclass.

BaseRegressor wraps one algorithm (fit with a per-round error curve, predict, gain importance, save / load).
The trainer is algorithm-agnostic: it only talks to this interface.

BaseTrainer holds the training flow every regression use case shares:
  1. split the rows into training and test rows (chronological: the most recent share is the test - of each group,
     e.g. each battery system, when the trainer names a group column; random: a seeded random share);
  2. feature selection: with a significance threshold, a screening fit on the training rows (no test rows, no
     early stopping) ranks the candidate features by their share of the importance; only features at or above
     the threshold are kept. Importance is the split gain, or permutation importance (how much the training
     error grows when a feature is shuffled) - needed for models whose leaves use features in linear formulas
     (LightGBM linear trees), which gain doesn't see;
  3. the final fit on the kept features, with both sets as evaluation sets (the curve per boosting round);
  4. scores on the test rows (and on the training rows, to spot over-fitting; per group too), predictions for the
     chart and the feature ranges the estimator checks inputs against.
Fine-tuning: with an init model (e.g. a base model) the fit continues from its trees on the new rows, with the
init model's features (no feature selection).
A use case's trainer sets the target and its algorithms, and adds its own data warnings.
"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional

import numpy as np
import pandas as pd

from bess_common import errors as E
from core.metrics import finite, permutation_shares, regression_scores, shares

IMPORTANCE_METHODS = ("auto", "gain", "permutation")


# ---------------------------------------------------------------- errors (bess_common/errors.py answers them)
class UseCaseError(E.BusinessRuleViolation):
    """Base of the use cases' input errors: authored messages meant for the user (the API answers 400 with the text).
    Anything that is not a UseCaseError / AppError is answered with the generic message and logged with its trace."""
    status, code = 400, "ML_INPUT_REJECTED"


class TrainingError(UseCaseError):
    """Bad training input (the API answers 400)."""
    code = "TRAINING_REJECTED"


class ArtifactMissing(E.ModelNotReady):
    """A completed run whose model files are gone (the path stays in the log)."""
    code, public = "MODEL_ARTIFACT_MISSING", "The model files of this run are missing. Retrain the model."


# ---------------------------------------------------------------- algorithm


@dataclass
class FitReport:
    # error per boosting round: {iteration, train_rmse, valid_rmse, train_mae, valid_mae}
    curve: list[dict] = field(default_factory=list)
    best_iteration: Optional[int] = None


class BaseRegressor(ABC):
    """One regression algorithm. Subclasses set the class attributes and implement the abstract methods."""

    key: ClassVar[str]  # stored in model_run.model_type
    label: ClassVar[str]
    file_suffix: ClassVar[str]  # model file extension
    # parameter specs: the training page builds its form from these
    # {name, label, type: int|float|bool, default, min, max, step, help?}
    param_specs: ClassVar[list[dict]]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        self.params = dict(params or {})
        self.seed = seed

    @classmethod
    def clean_params(cls, params: dict) -> dict:
        """Defaults for missing values, types and ranges enforced."""
        out = {}
        for spec in cls.param_specs:
            value = params.get(spec["name"], spec["default"])
            if value in (None, ""):
                value = spec["default"]
            if spec["type"] == "bool":
                value = bool(value)
            else:
                value = int(value) if spec["type"] == "int" else float(value)
                if not spec["min"] <= value <= spec["max"]:
                    raise TrainingError(f"{spec['label']} must be between {spec['min']} and {spec['max']}")
            out[spec["name"]] = value
        unknown = set(params) - set(out)
        if unknown:
            raise TrainingError(f"Unknown parameter(s) for {cls.label}: {', '.join(sorted(unknown))}")
        return out

    @property
    def extrapolates(self) -> bool:
        """True when predictions can go beyond the training target range (e.g. linear trees)."""
        return False

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: np.ndarray, X_valid: Optional[pd.DataFrame] = None,
            y_valid: Optional[np.ndarray] = None, early_stopping_rounds: int = 0,
            init_model: Optional["BaseRegressor"] = None) -> FitReport:
        """Fit on X. With validation rows, record the error per round for both sets (and stop early if asked).
        With init_model (same algorithm and features), continue boosting from its trees (fine-tuning)."""

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...

    @abstractmethod
    def gain_importance(self) -> dict[str, float]:
        """Raw total split gain per feature of the fitted model."""

    @property
    @abstractmethod
    def estimator(self) -> Any:
        """The fitted scikit-learn compatible estimator (for permutation importance)."""

    @abstractmethod
    def save(self, path: Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> "BaseRegressor":
        """A model that can predict (training-only features such as the estimator may be missing)."""


# ---------------------------------------------------------------- training


@dataclass
class TrainingResult:
    model: BaseRegressor
    metrics: dict[str, Optional[float]]
    curve: list[dict]
    importance: dict[str, float]
    predictions: list[dict]
    feature_ranges: dict[str, dict]
    split: dict[str, Any]
    iterations: int
    best_iteration: Optional[int]
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0
    # feature selection: the candidates, their screening importance, and the ones kept
    candidates: list[str] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    screening_importance: dict[str, float] = field(default_factory=dict)
    min_importance_pct: float = 0.0
    importance_method: str = "gain"
    # test scores per group (e.g. per battery system): {group: {n, r2, rmse, mae, ...}}
    metrics_by_group: dict[str, dict] = field(default_factory=dict)


def split(df: pd.DataFrame, method: str, test_fraction: float, seed: int,
          group_col: Optional[str] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    n_test = max(1, int(round(len(df) * test_fraction)))
    if n_test >= len(df):
        raise TrainingError("The test share leaves no training rows")
    if method == "chronological" and group_col and group_col in df and df[group_col].nunique() > 1:
        # the latest share of each group's own timeline (every group is in both sets)
        train_parts, test_parts = [], []
        for _, g in df.sort_values("ts").groupby(group_col, sort=False):
            k = max(1, int(round(len(g) * test_fraction))) if len(g) > 1 else 0
            train_parts.append(g.iloc[:len(g) - k])
            test_parts.append(g.iloc[len(g) - k:])
        return pd.concat(train_parts), pd.concat(test_parts)
    if method == "chronological":
        ordered = df.sort_values("ts")
        return ordered.iloc[:-n_test], ordered.iloc[-n_test:]
    if method == "random":
        test = df.sample(n=n_test, random_state=seed)
        return df.drop(test.index), test
    raise TrainingError("split_method must be chronological or random")


class BaseTrainer:
    """Train and score a regressor on a feature dataset (columns: ts, the target, the features)."""

    target: ClassVar[str]
    models: ClassVar[dict[str, type[BaseRegressor]]]
    min_rows: ClassVar[int] = 10  # below this there is nothing sensible to split
    default_min_importance_pct: ClassVar[float] = 1.0  # a feature must bring this share of the importance
    # rows belong to groups (e.g. battery systems): the chronological split and the per-group scores use it
    group_col: ClassVar[Optional[str]] = None

    def model_class(self, model_type: str) -> type[BaseRegressor]:
        if model_type not in self.models:
            raise TrainingError(f"Unknown model '{model_type}' ({' or '.join(self.models)})")
        return self.models[model_type]

    def clean_params(self, model_type: str, params: dict) -> dict:
        return self.model_class(model_type).clean_params(params)

    def data_warnings(self, df: pd.DataFrame, y_train: np.ndarray, y_test: np.ndarray, split_method: str,
                      model: BaseRegressor) -> list[str]:
        """Use-case warnings about the data (before training)."""
        return []

    def evaluate(self, model: BaseRegressor, df: pd.DataFrame, features: list[str]) -> dict:
        """Scores of a fitted model on other rows (e.g. a held-out battery system)."""
        if df.empty:
            return {"n": 0}
        y = df[self.target].to_numpy()
        pred = model.predict(df[features])
        return {"n": int(len(df)), "from": df["ts"].min().isoformat(), "to": df["ts"].max().isoformat(),
                "actual_mean": float(y.mean()), "predicted_mean": float(pred.mean()), **regression_scores(y, pred)}

    def train(self, df: pd.DataFrame, features: list[str], model_type: str, params: dict, split_method: str,
              test_fraction: float, seed: int, min_importance_pct: Optional[float] = None,
              importance_method: str = "auto", init_model: Optional[BaseRegressor] = None) -> TrainingResult:
        """Train and score a model; with min_importance_pct > 0 only features with at least that share of the
        importance (in a screening fit on the training rows) are used. With init_model the fit continues from it
        on exactly its features (fine-tuning)."""
        if init_model is not None:
            min_importance_pct = 0.0
        if min_importance_pct is None:
            min_importance_pct = self.default_min_importance_pct
        if len(df) < self.min_rows:
            raise TrainingError(f"Only {len(df)} rows match the selection; at least {self.min_rows} are needed")
        if not features:
            raise TrainingError("Choose at least one feature group")
        if not 0 <= min_importance_pct < 100:
            raise TrainingError("The importance threshold must be between 0 and 100 %")
        if importance_method not in IMPORTANCE_METHODS:
            raise TrainingError(f"importance_method must be one of {', '.join(IMPORTANCE_METHODS)}")
        cls = self.model_class(model_type)
        params = cls.clean_params(params)
        early = params.pop("early_stopping_rounds", 0)

        train_df, test_df = split(df, split_method, test_fraction, seed, self.group_col)
        y_tr, y_te = train_df[self.target].to_numpy(), test_df[self.target].to_numpy()
        model = cls(params, seed)
        warnings = self.data_warnings(df, y_tr, y_te, split_method, model)
        if len(test_df) < 5:
            warnings.append(f"Only {len(test_df)} test rows: the scores are very uncertain")
        started = time.perf_counter()

        # 1. feature selection: screening fit on the training rows, keep the significant features
        candidates = list(features)
        screening: dict[str, float] = {}
        selected = candidates
        method = importance_method
        if method == "auto":
            method = "permutation" if model.extrapolates else "gain"
        if min_importance_pct > 0:
            screen = cls(params, seed)
            screen.fit(train_df[candidates], y_tr)
            screening = (permutation_shares(screen.estimator, train_df[candidates], y_tr, seed)
                         if method == "permutation" else _shares(screen.gain_importance(), candidates))
            selected = [f for f in candidates if screening.get(f, 0.0) * 100 >= min_importance_pct]
            if not selected:  # nothing reaches the threshold: keep the strongest feature
                selected = [max(candidates, key=lambda f: screening.get(f, 0.0))]
            selected.sort(key=lambda f: -screening.get(f, 0.0))
        empty = [f for f in selected if df[f].isna().all()]
        if empty:
            warnings.append(f"No values for {', '.join(empty)} in the selected rows")

        # 2. the model, on the kept features only
        X_tr, X_te = train_df[selected], test_df[selected]
        report = model.fit(X_tr, y_tr, X_te, y_te, early, init_model)
        importance = _shares(model.gain_importance(), selected)
        duration_ms = int((time.perf_counter() - started) * 1000)

        pred_tr, pred_te = model.predict(X_tr), model.predict(X_te)
        metrics = regression_scores(y_te, pred_te)
        train_scores = regression_scores(y_tr, pred_tr)
        metrics.update(train_r2=train_scores["r2"], train_mae=train_scores["mae"], train_rmse=train_scores["rmse"])
        if metrics["rmse"] and train_scores["rmse"] is not None and metrics["rmse"] > 3 * max(train_scores["rmse"], 1e-6):
            warnings.append("The test error is far above the training error: the model over-fits the training rows")
        by_group: dict[str, dict] = {}
        if self.group_col and self.group_col in test_df:
            for key, idx in test_df.groupby(self.group_col).indices.items():
                yt, yp = y_te[idx], pred_te[idx]
                by_group[str(key)] = {"n": int(len(idx)), "actual_mean": float(yt.mean()),
                                      "predicted_mean": float(yp.mean()), **regression_scores(yt, yp)}

        # predictions for the chart: every test row, and at most ~1500 training rows
        step = max(1, len(train_df) // 1500)
        predictions = (
            [{"ts": ts.isoformat(), "actual": float(a), "predicted": float(p), "set": "train"}
             for ts, a, p in list(zip(train_df["ts"], y_tr, pred_tr))[::step]]
            + [{"ts": ts.isoformat(), "actual": float(a), "predicted": float(p), "set": "test"}
               for ts, a, p in zip(test_df["ts"], y_te, pred_te)]
        )
        predictions.sort(key=lambda r: r["ts"])
        ranges = {f: {"min": finite(df[f].min()) if df[f].notna().any() else None,
                      "max": finite(df[f].max()) if df[f].notna().any() else None,
                      "mean": finite(df[f].mean()) if df[f].notna().any() else None} for f in selected}
        y_all = df[self.target]
        return TrainingResult(
            model=model, metrics=metrics, curve=report.curve, importance=importance, predictions=predictions,
            feature_ranges=ranges, iterations=len(report.curve), best_iteration=report.best_iteration,
            warnings=warnings, duration_ms=duration_ms,
            split={"n_rows": len(df), "n_train": len(train_df), "n_test": len(test_df),
                   "train_from": train_df["ts"].min(), "train_to": train_df["ts"].max(),
                   "test_from": test_df["ts"].min(), "test_to": test_df["ts"].max(),
                   "target_min": float(y_all.min()), "target_max": float(y_all.max()),
                   "target_std": float(y_all.std())},
            candidates=candidates, selected=selected, screening_importance=screening,
            min_importance_pct=min_importance_pct, importance_method=method, metrics_by_group=by_group,
        )


def _shares(raw: dict[str, float], features: list[str]) -> dict[str, float]:
    return shares({f: float(raw.get(f, 0.0)) for f in features})
