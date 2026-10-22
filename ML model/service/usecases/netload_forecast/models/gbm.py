"""Primary: LightGBM on lag + weather + calendar + BTM features, stacked "direct" multi-horizon (the lead time is a
feature), with conformalised quantile regression (CQR) for the interval.

  anchor    the models learn the change from the anchor - the mean of the same slot on the three newest known days
            of the target's day class - and add it back: the trees correct a strong, already day-type-aware profile
            (weather, PV and recent level) instead of rebuilding the daily shape from scratch
  P50       Huber loss (robust: a few odd 5-min readings don't drag the median)
  P10, P90  quantile (pinball) loss, regularised with large leaves: the training rows overlap (each reading is the
            target of many origins), so small leaves memorise single days
  CQR       first fitted without the newest `calibration_share` of each metering point's training origins; on those
            the conformity score max(P10 - y, y - P90) gives the margin that makes P10-P90 cover 80 %, per lead
            bucket; then refitted on all training rows with that margin kept
"""
import lightgbm as lgb
import numpy as np
import pandas as pd

from usecases.netload_forecast.models.base import Forecaster, TrainData, frame

COVERAGE = 0.8
H_BUCKETS = [(0, 1), (1, 6), (6, 24), (24, 1000)]  # lead hours (lo, hi]


def calibration_mask(rows: pd.DataFrame, share: float) -> np.ndarray:
    if share <= 0:
        return np.zeros(len(rows), bool)
    cut = rows.groupby("mp_id")["origin_pos"].transform(lambda o: o.quantile(1 - share))
    return (rows["origin_pos"] > cut).to_numpy()


def _bucket_masks(lead):
    return [((lead > a) & (lead <= b), f"{a}-{b}") for a, b in H_BUCKETS]


def cqr_margins(y, lo, hi, lead) -> dict[str, float]:
    out = {}
    score = np.maximum(lo - y, y - hi)
    for m, key in _bucket_masks(lead):
        n = int(m.sum())
        if n < 50:
            continue
        q = min(1.0, np.ceil((n + 1) * COVERAGE) / n)
        out[key] = float(np.quantile(score[m], q))
    return out


def apply_margins(lo, hi, lead, margins):
    e = np.zeros(len(lo))
    for m, key in _bucket_masks(lead):
        e[m] = margins.get(key, 0.0)
    return lo - e, hi + e


class LightGBMQuantile(Forecaster):
    key = "lightgbm"
    label = "LightGBM (Huber P50 + quantile P10/P90, CQR)"
    family = "primary"
    param_specs = [
        {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 400, "min": 20, "max": 5000, "step": 10},
        {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
        {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 31, "min": 2, "max": 512, "step": 1},
        {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 400, "min": 1, "max": 50000, "step": 10},
        {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
        {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
        {"name": "huber_delta", "label": "Huber δ for P50 (kW)", "type": "float", "default": 100, "min": 1, "max": 5000, "step": 10,
         "help": "Errors beyond δ count linearly: small δ ≈ median regression, large δ ≈ least squares."},
        {"name": "anchor", "label": "Anchor on the same-type-day profile (1 = yes)", "type": "int", "default": 1, "min": 0, "max": 1, "step": 1,
         "help": "Learn the change from the mean of the same slot on the last three same-type days instead of the load level."},
        {"name": "calibration_share", "label": "Calibration share (CQR)", "type": "float", "default": 0.2, "min": 0, "max": 0.4, "step": 0.05,
         "help": "Newest share of each metering point's training origins held out to calibrate P10-P90 to 80 % (0 = raw quantiles)."},
    ]

    def _kw(self):
        p = self.params
        return dict(n_estimators=int(p["n_estimators"]), learning_rate=p["learning_rate"], num_leaves=int(p["num_leaves"]),
                    min_child_samples=int(p["min_child_samples"]), subsample=p["subsample"], subsample_freq=1,
                    colsample_bytree=p["colsample_bytree"], random_state=self.seed, verbose=-1, n_jobs=4)

    def _anchor(self, rows) -> np.ndarray:
        return rows["anchor"].to_numpy() if int(self.params.get("anchor", 1)) else np.zeros(len(rows))

    def _fit_models(self, X, y):
        kw = self._kw()
        self.models = {
            0.5: lgb.LGBMRegressor(objective="huber", alpha=self.params["huber_delta"], **kw).fit(X, y),
            0.1: lgb.LGBMRegressor(objective="quantile", alpha=0.1, **kw).fit(X, y),
            0.9: lgb.LGBMRegressor(objective="quantile", alpha=0.9, **kw).fit(X, y),
        }

    def _predict_models(self, X):
        return self.models[0.1].predict(X), self.models[0.5].predict(X), self.models[0.9].predict(X)

    def fit(self, data: TrainData) -> "LightGBMQuantile":
        r = data.rows
        self._cal_fc = None
        self.features = data.features
        target = r["y"].to_numpy() - self._anchor(r)
        cal = calibration_mask(r, float(self.params["calibration_share"]))
        self.margins = {}
        if cal.any() and (~cal).sum() > 1000:
            self._fit_models(r.loc[~cal, self.features], target[~cal])
            lo, mid, hi = self._predict_models(r.loc[cal, self.features])
            self.margins = cqr_margins(target[cal], lo, hi, r.loc[cal, "horizon_h"].to_numpy())
            # out-of-sample forecasts of the held-out rows (with the margin), for the peak calibration
            clo, chi = apply_margins(lo, hi, r.loc[cal, "horizon_h"].to_numpy(), self.margins)
            a = self._anchor(r.loc[cal])
            self._cal_fc = frame(r.loc[cal], clo + a, mid + a, chi + a)
        self._fit_models(r[self.features], target)
        return self

    def calibration_forecast(self, rows, series):
        stored = getattr(self, "_cal_fc", None)
        if stored is None:
            return self.predict(rows, series)
        have = rows.index.intersection(stored.index)
        rest = rows.index.difference(stored.index)
        parts = [stored.loc[have]]
        if len(rest):
            parts.append(self.predict(rows.loc[rest], series))
        return pd.concat(parts).loc[rows.index]

    def quantiles(self, rows):
        lo, p50, hi = self._predict_models(rows[self.features])
        lo, hi = apply_margins(lo, hi, rows["horizon_h"].to_numpy(), self.margins)
        a = self._anchor(rows)
        return lo + a, p50 + a, hi + a

    def predict(self, rows, series):
        lo, p50, hi = self.quantiles(rows)
        return frame(rows, lo, p50, hi)

    def importance(self):
        b = self.models[0.5].booster_
        return dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float)))
