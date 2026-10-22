"""Deep sequence (no PyTorch): an N-BEATS-style multi-horizon MLP.

Like N-BEATS it maps a look-back window of the series straight to the whole forecast horizon in one shot, on a
window-normalised scale (each sample divided by its own look-back mean, so EMS with different price levels share
the network). Covariates ride along as extra inputs: the TOU reference price of every future hour (known ahead),
the origin's calendar and the grid-stress proxy. scikit-learn's MLPRegressor (multi-output) fits it.
P10 / P90 come from the residuals per horizon on the last share of the training origins (held out from the fit).
"""
import numpy as np
from sklearn.neural_network import MLPRegressor

from usecases.price_forecast.features import Series
from usecases.price_forecast.models.base import Forecaster, TrainData, apply_offsets, frame, residual_offsets

LOOKBACK = 168


def _inputs(s: Series, origins: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    win = s.y[origins[:, None] - np.arange(LOOKBACK - 1, -1, -1)[None, :]]
    scale = np.maximum(win.mean(axis=1), 1.0)
    hour0 = s.ts[origins].hour.to_numpy()
    fut_hours = (hour0[:, None] + np.arange(1, horizon + 1)[None, :]) % 24
    ref = s.band_ref[fut_hours]
    ref = np.where(np.isnan(ref), win.mean(axis=1, keepdims=True), ref)
    dow = s.ts[origins].dayofweek.to_numpy()
    cal = np.column_stack([np.sin(2 * np.pi * hour0 / 24), np.cos(2 * np.pi * hour0 / 24),
                           np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7), s.fdev[origins] * 10])
    return np.hstack([win / scale[:, None], ref / scale[:, None], cal]), scale


class NBeatsMLP(Forecaster):
    key = "nbeats"
    label = "N-BEATS-style MLP"
    family = "deep"
    param_specs = [
        {"name": "hidden_units", "label": "Units per layer", "type": "int", "default": 256, "min": 16, "max": 1024, "step": 16},
        {"name": "layers", "label": "Hidden layers", "type": "int", "default": 3, "min": 1, "max": 6, "step": 1},
        {"name": "alpha", "label": "L2 penalty", "type": "float", "default": 0.001, "min": 0, "max": 10, "step": 0.0005},
        {"name": "learning_rate_init", "label": "Learning rate", "type": "float", "default": 0.001, "min": 0.00001, "max": 0.1, "step": 0.0005},
        {"name": "max_iter", "label": "Max epochs", "type": "int", "default": 300, "min": 20, "max": 3000, "step": 10},
        {"name": "calibration_share", "label": "Calibration share of training origins", "type": "float", "default": 0.15,
         "min": 0.05, "max": 0.4, "step": 0.05, "help": "Held out from the fit to size the P10 / P90 band."},
    ]

    def _origins(self, data: TrainData):
        """Every hourly origin of the training period (independent of the boosted models' origin step)."""
        return {e: np.arange(LOOKBACK - 1, data.train_end[e] - data.horizon + 1) for e in data.series}

    def fit(self, data: TrainData) -> "NBeatsMLP":
        H = data.horizon
        self.horizon = H
        Xs, Ys, cal_X, cal_Y, cal_scale = [], [], [], [], []
        share = float(self.params["calibration_share"])
        for ems, origins in self._origins(data).items():
            s = data.series[ems]
            X, scale = _inputs(s, origins, H)
            Y = s.y[origins[:, None] + np.arange(1, H + 1)[None, :]] / scale[:, None]
            k = int(len(origins) * (1 - share))
            Xs.append(X[:k]), Ys.append(Y[:k])
            cal_X.append(X[k:]), cal_Y.append(Y[k:]), cal_scale.append(scale[k:])
        p = self.params
        self.model = MLPRegressor(hidden_layer_sizes=(int(p["hidden_units"]),) * int(p["layers"]), alpha=p["alpha"],
                                  learning_rate_init=p["learning_rate_init"], max_iter=int(p["max_iter"]),
                                  early_stopping=True, validation_fraction=0.1, n_iter_no_change=20, random_state=self.seed)
        self.model.fit(np.vstack(Xs), np.vstack(Ys))
        cX, cY, cs = np.vstack(cal_X), np.vstack(cal_Y), np.concatenate(cal_scale)
        resid = (cY - self.model.predict(cX)) * cs[:, None]
        hz = np.tile(np.arange(1, H + 1), len(cX))
        self.offsets = residual_offsets(hz, resid.ravel(), H)
        self.loss_curve = [float(v) for v in self.model.loss_curve_]
        return self

    def predict(self, rows, series):
        p50 = np.empty(len(rows))
        pos = {k: i for i, k in enumerate(zip(rows["ems_id"], rows["origin_pos"], rows["horizon"]))}
        for (ems, opos), _ in rows.groupby(["ems_id", "origin_pos"], sort=False):
            s = series[int(ems)]
            X, scale = _inputs(s, np.array([int(opos)]), self.horizon)
            pred = self.model.predict(X)[0] * scale[0]
            for h in range(1, self.horizon + 1):
                i = pos.get((ems, opos, float(h)))
                if i is not None:
                    p50[i] = pred[h - 1]
        lo, hi = apply_offsets(p50, rows["horizon"].to_numpy(), self.offsets)
        return frame(rows, lo, p50, hi)
