"""The interface every price forecaster implements, and the shared helpers (residual-quantile intervals)."""
from dataclasses import dataclass, field
from typing import ClassVar, Optional

import numpy as np
import pandas as pd

from usecases.price_forecast.features import Series

QUANTILES = (0.1, 0.5, 0.9)
OUT_COLS = ["ems_id", "origin_ts", "target_ts", "horizon", "p10", "p50", "p90", "mean", "spike_prob"]


class ForecastError(Exception):
    """Bad training / forecast input (the API answers 400)."""


@dataclass
class TrainData:
    rows: pd.DataFrame  # training rows (features, y, spike, ems_id, origin_pos, horizon)
    series: dict[int, Series]
    features: list[str]
    horizon: int
    spike_threshold: float
    train_end: dict[int, int]  # per EMS: the last series position whose price may be used for training
    seed: int = 42
    warnings: list[str] = field(default_factory=list)


class Forecaster:
    key: ClassVar[str]
    label: ClassVar[str]
    family: ClassVar[str]  # baseline | primary | deep | spike
    param_specs: ClassVar[list[dict]] = []

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        p = {s["name"]: s["default"] for s in self.param_specs}
        p.update(params or {})
        self.params = p
        self.seed = seed

    def fit(self, data: TrainData) -> "Forecaster":
        return self

    def predict(self, rows: pd.DataFrame, series: dict[int, Series]) -> pd.DataFrame:
        """Forecast for the rows (one per EMS, origin and horizon); returns OUT_COLS in the rows' order."""
        raise NotImplementedError

    def importance(self) -> dict[str, float]:
        return {}


def frame(rows: pd.DataFrame, p10, p50, p90, mean=None, spike=None) -> pd.DataFrame:
    p50 = np.asarray(p50, float)
    q = np.sort(np.vstack([np.asarray(p10, float), p50, np.asarray(p90, float)]), axis=0)  # no quantile crossing
    return pd.DataFrame({
        "ems_id": rows["ems_id"].to_numpy(), "origin_ts": rows["origin_ts"].to_numpy(),
        "target_ts": rows["target_ts"].to_numpy(), "horizon": rows["horizon"].to_numpy().astype(int),
        "p10": q[0], "p50": q[1], "p90": q[2], "mean": p50 if mean is None else np.asarray(mean, float),
        "spike_prob": np.full(len(rows), np.nan) if spike is None else np.asarray(spike, float),
    })


def residual_offsets(horizon: np.ndarray, resid: np.ndarray, max_h: int) -> dict[int, tuple[float, float]]:
    """P10 / P90 offsets of the residual (actual - P50) per horizon, smoothed by pooling neighbouring horizons."""
    out = {}
    for h in range(1, max_h + 1):
        m = np.abs(horizon - h) <= 2
        r = resid[m] if m.sum() >= 20 else resid
        out[h] = (float(np.quantile(r, 0.1)), float(np.quantile(r, 0.9)))
    return out


def apply_offsets(p50: np.ndarray, horizon: np.ndarray, offsets: dict[int, tuple[float, float]]):
    lo = np.array([offsets.get(int(h), (0.0, 0.0))[0] for h in horizon])
    hi = np.array([offsets.get(int(h), (0.0, 0.0))[1] for h in horizon])
    return p50 + lo, p50 + hi
