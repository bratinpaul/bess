"""Baselines - the bar to beat: seasonal naïve (same hour, last known day) and SARIMA."""
import warnings

import numpy as np
import pandas as pd

from usecases.price_forecast.models.base import Forecaster, TrainData, apply_offsets, frame, residual_offsets


class SeasonalNaive(Forecaster):
    """P50 = the price at the same hour on the last known day; P10 / P90 from its training residuals per horizon."""
    key = "seasonal_naive"
    label = "Seasonal naïve"
    family = "baseline"

    def fit(self, data: TrainData) -> "SeasonalNaive":
        r = data.rows
        self.offsets = residual_offsets(r["horizon"].to_numpy(), (r["y"] - r["same_hour_day"]).to_numpy(), data.horizon)
        return self

    def predict(self, rows, series):
        p50 = rows["same_hour_day"].to_numpy()
        lo, hi = apply_offsets(p50, rows["horizon"].to_numpy(), self.offsets)
        return frame(rows, lo, p50, hi)


class Sarima(Forecaster):
    """SARIMA(p,0,q)(P,1,Q)24 per EMS on the hourly price, fitted once on the training hours (spikes clipped so a
    few extreme hours don't dominate the fit); each forecast re-filters the fitted model on the history up to the
    origin (no refit). P10 / P90 = its 80 % prediction interval."""
    key = "sarima"
    label = "SARIMA"
    family = "baseline"
    param_specs = [
        {"name": "p", "label": "AR order p", "type": "int", "default": 1, "min": 0, "max": 3, "step": 1},
        {"name": "q", "label": "MA order q", "type": "int", "default": 1, "min": 0, "max": 3, "step": 1},
        {"name": "P", "label": "Seasonal AR P", "type": "int", "default": 1, "min": 0, "max": 2, "step": 1},
        {"name": "Q", "label": "Seasonal MA Q", "type": "int", "default": 1, "min": 0, "max": 2, "step": 1},
        {"name": "fit_days", "label": "Days of history to fit on", "type": "int", "default": 21, "min": 7, "max": 120, "step": 1,
         "help": "The latest training days per EMS; longer is slower."},
    ]

    def fit(self, data: TrainData) -> "Sarima":
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        self.clip = data.spike_threshold
        self.models = {}
        p = self.params
        for ems, s in data.series.items():
            end = data.train_end[ems] + 1
            start = max(0, end - int(p["fit_days"]) * 24)
            y = np.minimum(s.y[start:end], self.clip)
            if len(y) < 24 * 7:
                data.warnings.append(f"SARIMA: EMS {ems} has under 7 training days; seasonal naïve used instead")
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = SARIMAX(y, order=(p["p"], 0, p["q"]), seasonal_order=(p["P"], 1, p["Q"], 24),
                                enforce_stationarity=False, enforce_invertibility=False)
                res = model.fit(disp=False, maxiter=60)
            self.models[ems] = res
        return self

    def predict(self, rows, series):
        out = []
        H = int(rows["horizon"].max())
        for (ems, opos), g in rows.groupby(["ems_id", "origin_pos"], sort=False):
            res = self.models.get(int(ems))
            if res is None:
                p50 = g["same_hour_day"].to_numpy()
                out.append(frame(g, p50 * 0.8, p50, p50 * 1.25))
                continue
            s = series[int(ems)]
            hist = np.minimum(s.y[max(0, opos + 1 - 24 * 21):opos + 1], self.clip)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fc = res.apply(hist).get_forecast(H)
            mean = np.asarray(fc.predicted_mean)
            ci = np.asarray(fc.conf_int(alpha=0.2))
            hs = g["horizon"].to_numpy().astype(int) - 1
            out.append(frame(g, ci[hs, 0], mean[hs], ci[hs, 1]))
        return pd.concat(out).set_index(rows.index) if out else frame(rows, [], [], [])
