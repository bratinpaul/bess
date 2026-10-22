"""Baselines - the bar to beat.

Seasonal naïve: the same 5-min slot on the newest known day of the target's day class (workday vs weekend /
holiday). Plain "same slot yesterday" fails every Monday and Saturday (a weekend profile for a workday and back);
"same slot last week" is the classic alternative but a week stale. P10 / P90 from its training residuals per hour of
lead.

SARIMA: SARIMAX(p,0,q)(P,1,Q)24 on the hourly mean net load with exogenous workday flag, temperature and GHI (as
known at the origin - forecast or measured per the run's weather source), fitted once on the training hours; each
forecast re-filters the fitted model on the history up to the origin (no refit). The hourly path is interpolated to
5 minutes (each hourly mean sits at the half hour); P10 / P90 = its 80 % interval widened by the within-hour 5-min
spread measured on the training readings.
"""
import warnings

import numpy as np
import pandas as pd

from usecases.netload_forecast import features as F
from usecases.netload_forecast.models.base import Forecaster, TrainData, apply_offsets, frame, residual_offsets

Z80 = 1.2816


class SeasonalNaive(Forecaster):
    key = "seasonal_naive"
    label = "Seasonal naïve (same slot, last same-type day)"
    family = "baseline"

    def fit(self, data: TrainData) -> "SeasonalNaive":
        r = data.rows
        self.offsets = residual_offsets(r["step"].to_numpy(), (r["y"] - r["same_slot_class"]).to_numpy(), data.steps)
        return self

    def predict(self, rows, series):
        p50 = rows["same_slot_class"].to_numpy()
        lo, hi = apply_offsets(p50, rows["step"].to_numpy(), self.offsets)
        return frame(rows, lo, p50, hi)


class Sarima(Forecaster):
    key = "sarima"
    label = "SARIMAX (hourly, workday + weather)"
    family = "baseline"
    param_specs = [
        {"name": "p", "label": "AR order p", "type": "int", "default": 1, "min": 0, "max": 3, "step": 1},
        {"name": "q", "label": "MA order q", "type": "int", "default": 1, "min": 0, "max": 3, "step": 1},
        {"name": "P", "label": "Seasonal AR P", "type": "int", "default": 1, "min": 0, "max": 2, "step": 1},
        {"name": "Q", "label": "Seasonal MA Q", "type": "int", "default": 1, "min": 0, "max": 2, "step": 1},
        {"name": "fit_days", "label": "Days of history to fit on", "type": "int", "default": 21, "min": 7, "max": 120, "step": 1,
         "help": "The latest training days per metering point; longer is slower."},
    ]
    EXOG = ["workday", "temp", "ghi"]

    def fit(self, data: TrainData) -> "Sarima":
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        self.models, self.intra, self.source = {}, {}, data.weather_source
        p = self.params
        for mp, s in data.series.items():
            h = F.hourly(s, data.train_end[mp])
            h = h.iloc[-int(p["fit_days"]) * 24:]
            h[["temp", "ghi"]] = h[["temp", "ghi"]].interpolate().bfill().ffill()
            if len(h) < 24 * 7 or h["net"].isna().any():
                data.warnings.append(f"SARIMA: metering point {mp} has under 7 clean training days; seasonal naïve used")
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = SARIMAX(h["net"].to_numpy(), exog=h[self.EXOG].to_numpy(), order=(p["p"], 0, p["q"]),
                                seasonal_order=(p["P"], 1, p["Q"], 24), enforce_stationarity=False,
                                enforce_invertibility=False)
                self.models[mp] = model.fit(disp=False, maxiter=80)
            # within-hour spread of the 5-min readings around their hourly mean
            pos = np.arange(0, data.train_end[mp] + 1)
            ser = pd.Series(s.net[pos], index=s.ts(pos))
            self.intra[mp] = float((ser - ser.resample("h").transform("mean")).std())
        return self

    def predict(self, rows, series):
        out = []
        for (mp, opos), g in rows.groupby(["mp_id", "origin_pos"], sort=False):
            res = self.models.get(int(mp))
            if res is None:
                p50 = g["same_slot_class"].to_numpy()
                out.append(frame(g, p50 * 0.9, p50, p50 * 1.1))
                continue
            s = series[int(mp)]
            opos = int(opos)
            # history: whole hours up to the origin
            hist = F.hourly(s, opos).iloc[-24 * 21:]
            hist[["temp", "ghi"]] = hist[["temp", "ghi"]].interpolate().bfill().ffill()
            last_hour = hist.index[-1]
            # future hourly exog from the rows (as known at the origin): mean per target hour
            fut = g.assign(hour=pd.DatetimeIndex(g["target_ts"]).floor("h")).groupby("hour").agg(
                workday=("workday", "first"), temp=("temp_fc", "mean"), ghi=("ghi_fc", "mean"))
            hours = pd.date_range(last_hour + pd.Timedelta(hours=1), fut.index.max(), freq="h")
            fut = fut.reindex(hours)
            if fut[["temp", "ghi"]].isna().all().any():
                fut[["temp", "ghi"]] = fut[["temp", "ghi"]].fillna(hist[["temp", "ghi"]].iloc[-24:].mean())
            fut = fut.interpolate().bfill().ffill()
            fut["workday"] = fut["workday"].fillna(0)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fc = res.apply(hist["net"].to_numpy(), exog=hist[self.EXOG].to_numpy()).get_forecast(
                    len(hours), exog=fut[self.EXOG].to_numpy())
            mean = np.asarray(fc.predicted_mean)
            se = np.asarray(fc.se_mean)
            # hourly means sit at the half hour; interpolate to the 5-min targets
            centers = (hours + pd.Timedelta(minutes=30)).asi8.astype(float)
            prev = (last_hour + pd.Timedelta(minutes=30)).value
            xs = np.concatenate([[float(prev)], centers])
            ys = np.concatenate([[hist["net"].iloc[-1]], mean])
            ss = np.concatenate([[0.0], se])
            t = pd.DatetimeIndex(g["target_ts"]).asi8.astype(float)
            p50 = np.interp(t, xs, ys)
            sd = np.sqrt(np.interp(t, xs, ss) ** 2 + self.intra.get(int(mp), 0.0) ** 2)
            out.append(frame(g, p50 - Z80 * sd, p50, p50 + Z80 * sd))
        return pd.concat(out).loc[rows.index] if out else frame(rows, [], [], [])
