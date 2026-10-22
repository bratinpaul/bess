"""The interface every net-load forecaster implements, and the shared helpers (residual-quantile intervals)."""
from dataclasses import dataclass, field
from typing import ClassVar, Optional

import numpy as np
import pandas as pd

from usecases.netload_forecast.features import PER_HOUR, Series

QUANTILES = (0.1, 0.5, 0.9)


class ForecastError(Exception):
    """Bad training / forecast input (the API answers 400)."""


@dataclass
class TrainData:
    rows: pd.DataFrame  # training rows (features, y, mp_id, origin_pos, step)
    series: dict[int, Series]
    features: list[str]
    steps: int  # 5-min steps in the horizon
    train_end: dict[int, int]  # per metering point: the last position whose load may be used for training
    weather_source: str = "forecast"
    seed: int = 42
    warnings: list[str] = field(default_factory=list)


class Forecaster:
    key: ClassVar[str]
    label: ClassVar[str]
    family: ClassVar[str]  # baseline | primary | deep
    param_specs: ClassVar[list[dict]] = []

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        p = {s["name"]: s["default"] for s in self.param_specs}
        p.update(params or {})
        self.params = p
        self.seed = seed

    def fit(self, data: TrainData) -> "Forecaster":
        return self

    def predict(self, rows: pd.DataFrame, series: dict[int, Series]) -> pd.DataFrame:
        """Forecast for the rows (one per metering point, origin and step); returns frame() in the rows' order."""
        raise NotImplementedError

    def calibration_forecast(self, rows: pd.DataFrame, series: dict[int, Series]) -> pd.DataFrame:
        """Forecasts for held-out training rows (to calibrate the daily peak); a model that already made
        out-of-sample forecasts for them while fitting returns those."""
        return self.predict(rows, series)

    def importance(self) -> dict[str, float]:
        return {}


def frame(rows: pd.DataFrame, p10, p50, p90) -> pd.DataFrame:
    p50 = np.asarray(p50, float)
    q = np.sort(np.vstack([np.asarray(p10, float), p50, np.asarray(p90, float)]), axis=0)  # no quantile crossing
    return pd.DataFrame({
        "mp_id": rows["mp_id"].to_numpy(), "origin_ts": rows["origin_ts"].to_numpy(),
        "target_ts": rows["target_ts"].to_numpy(), "step": rows["step"].to_numpy().astype(int),
        "p10": q[0], "p50": q[1], "p90": q[2],
    }, index=rows.index)


def hour_bucket(step: np.ndarray) -> np.ndarray:
    return np.ceil(np.asarray(step) / PER_HOUR).astype(int)


def residual_offsets(step: np.ndarray, resid: np.ndarray, max_step: int) -> dict[int, tuple[float, float]]:
    """P10 / P90 offsets of the residual (actual - P50) per hour of lead, pooled over neighbouring hours."""
    hb = hour_bucket(step)
    out = {}
    ok = np.isfinite(resid)
    for h in range(1, int(np.ceil(max_step / PER_HOUR)) + 1):
        m = ok & (np.abs(hb - h) <= 1)
        r = resid[m] if m.sum() >= 50 else resid[ok]
        out[h] = (float(np.quantile(r, 0.1)), float(np.quantile(r, 0.9))) if len(r) else (0.0, 0.0)
    return out


def apply_offsets(p50: np.ndarray, step: np.ndarray, offsets: dict[int, tuple[float, float]]):
    hb = hour_bucket(step)
    lo = np.array([offsets.get(int(h), (0.0, 0.0))[0] for h in hb])
    hi = np.array([offsets.get(int(h), (0.0, 0.0))[1] for h in hb])
    return p50 + lo, p50 + hi
