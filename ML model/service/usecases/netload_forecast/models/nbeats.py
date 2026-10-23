"""Deep multi-horizon (no PyTorch): an N-BEATS-style MLP on the hourly net load.

Like N-BEATS it maps a look-back window straight to the whole horizon in one shot, on a window-normalised scale
(each sample divided by its own look-back mean). Covariates known ahead ride along as extra inputs: the workday flag,
temperature and GHI (as known at the origin) of every future hour, plus the origin's time of day / week. A Temporal
Fusion Transformer or LSTM needs PyTorch, which this service doesn't use; scikit-learn's multi-output MLPRegressor
fits this one. The hourly path is interpolated to the 5-min targets; P10 / P90 come from the 5-min residuals per
hour of lead on the newest share of the training origins (held out from the fit).
"""
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPRegressor

from core.base import TrainingError
from usecases.netload_forecast import features as F
from usecases.netload_forecast.models.base import Forecaster, TrainData, apply_offsets, frame, residual_offsets


class NBeatsMLP(Forecaster):
    key = "nbeats"
    label = "N-BEATS-style MLP (hourly, with covariates)"
    family = "deep"
    param_specs = [
        {"name": "lookback_h", "label": "Look-back (hours)", "type": "int", "default": 72, "min": 24, "max": 168, "step": 12},
        {"name": "hidden_units", "label": "Units per layer", "type": "int", "default": 128, "min": 16, "max": 1024, "step": 16},
        {"name": "layers", "label": "Hidden layers", "type": "int", "default": 2, "min": 1, "max": 6, "step": 1},
        {"name": "alpha", "label": "L2 penalty", "type": "float", "default": 0.01, "min": 0, "max": 10, "step": 0.005},
        {"name": "learning_rate_init", "label": "Learning rate", "type": "float", "default": 0.001, "min": 0.00001, "max": 0.1, "step": 0.0005},
        {"name": "max_iter", "label": "Max epochs", "type": "int", "default": 400, "min": 20, "max": 3000, "step": 10},
        {"name": "calibration_share", "label": "Calibration share of training origins", "type": "float", "default": 0.2,
         "min": 0.05, "max": 0.4, "step": 0.05, "help": "Held out from the fit to size the P10 / P90 band."},
    ]

    def _sample(self, s: F.Series, hourly: pd.DataFrame, end_hour: int, origin_pos: int):
        """Inputs for a forecast whose last known whole hour is hourly row `end_hour` (positional)."""
        L, H = self.lookback, self.hours
        win = hourly["net"].to_numpy()[end_hour - L + 1:end_hour + 1]
        scale = max(float(np.nanmean(win)), 1.0)
        last = hourly.index[end_hour]
        fut = pd.date_range(last + pd.Timedelta(hours=1), periods=H, freq="h")
        wd, _ = s.day_info(np.array(fut.date))
        # weather of the future hours as known at the origin: the mean of its 5-min values per hour
        tgt5 = (origin_pos + 1 + np.arange(H * F.PER_HOUR)).astype(np.int64)
        t5 = s.ts(tgt5)
        temp, ghi, _ = F._weather_at(s, origin_pos, tgt5, self.source)
        wx = pd.DataFrame({"temp": temp, "ghi": ghi}, index=t5.floor("h")).groupby(level=0).mean().reindex(fut)
        wx = wx.interpolate().bfill().ffill().fillna({"temp": 25.0, "ghi": 0.0})
        tod = last.hour + 1
        cal = [np.sin(2 * np.pi * tod / 24), np.cos(2 * np.pi * tod / 24),
               np.sin(2 * np.pi * last.dayofweek / 7), np.cos(2 * np.pi * last.dayofweek / 7)]
        x = np.concatenate([win / scale, wd.astype(float), (wx["temp"].to_numpy() - 25) / 10,
                            wx["ghi"].to_numpy() / 1000, cal])
        return x, scale, fut

    def fit(self, data: TrainData) -> "NBeatsMLP":
        self.lookback = int(self.params["lookback_h"])
        self.hours = int(np.ceil(data.steps / F.PER_HOUR))
        self.source = data.weather_source
        share = float(self.params["calibration_share"])
        Xs, Ys, cal = [], [], []
        for mp, s in data.series.items():
            hourly = F.hourly(s, data.train_end[mp])
            net = hourly["net"].to_numpy()
            idx = np.arange(self.lookback - 1, len(hourly) - self.hours)
            if len(idx) < 48:
                data.warnings.append(f"N-BEATS: metering point {mp} has too few training hours")
                continue
            k = int(len(idx) * (1 - share))
            for j, e in enumerate(idx):
                if np.isnan(net[e - self.lookback + 1:e + 1 + self.hours]).any():
                    continue
                # the origin is the last 5-min reading of hour e
                opos = int((hourly.index[e] + pd.Timedelta(minutes=55) - s.t0) / pd.Timedelta(minutes=F.STEP_MIN))
                x, scale, _ = self._sample(s, hourly, e, opos)
                y = net[e + 1:e + 1 + self.hours] / scale
                if j < k:
                    Xs.append(x)
                    Ys.append(y)
                else:
                    cal.append((mp, opos))
        if not Xs:
            raise TrainingError("N-BEATS: no training samples")
        p = self.params
        self.model = MLPRegressor(hidden_layer_sizes=(int(p["hidden_units"]),) * int(p["layers"]), alpha=p["alpha"],
                                  learning_rate_init=p["learning_rate_init"], max_iter=int(p["max_iter"]),
                                  early_stopping=True, validation_fraction=0.15, n_iter_no_change=25,
                                  random_state=self.seed)
        self.model.fit(np.vstack(Xs), np.vstack(Ys))
        self.loss_curve = [float(v) for v in self.model.loss_curve_]
        self.offsets = {}
        # 5-min residuals on the held-out origins
        steps = data.steps
        res_k, res_v = [], []
        for mp, opos in cal:
            s = data.series[mp]
            if opos + steps >= s.n:
                continue
            tgt = opos + 1 + np.arange(steps)
            p50 = self._path(s, opos, s.ts(tgt))
            res_k.append(np.arange(1, steps + 1))
            res_v.append(s.net[tgt] - p50)
        if res_v:
            self.offsets = residual_offsets(np.concatenate(res_k), np.concatenate(res_v), steps)
        else:
            data.warnings.append("N-BEATS: no held-out origins to size P10 / P90")
        return self

    def _path(self, s: F.Series, origin_pos: int, targets: pd.DatetimeIndex) -> np.ndarray:
        hourly = F.hourly(s, origin_pos)
        e = len(hourly) - 1
        x, scale, fut = self._sample(s, hourly, e, origin_pos)
        pred = self.model.predict(x[None, :])[0] * scale
        last = hourly.index[e]
        xs = np.concatenate([[(last + pd.Timedelta(minutes=30)).value], (fut + pd.Timedelta(minutes=30)).asi8]).astype(float)
        ys = np.concatenate([[hourly["net"].iloc[-1]], pred])
        return np.interp(targets.asi8.astype(float), xs, ys)

    def predict(self, rows, series):
        out = []
        for (mp, opos), g in rows.groupby(["mp_id", "origin_pos"], sort=False):
            s = series[int(mp)]
            p50 = self._path(s, int(opos), pd.DatetimeIndex(g["target_ts"]))
            lo, hi = apply_offsets(p50, g["step"].to_numpy(), self.offsets)
            out.append(frame(g, lo, p50, hi))
        return pd.concat(out).loc[rows.index]
