"""Primary: gradient boosting on lag + calendar + TOU + stress features, stacked "direct" multi-horizon (the horizon
is a feature), with conformalised quantile regression (CQR) for the interval.

  anchor    the models learn the change from the price at the same hour on the last known day (y - anchor) and add
            it back: the trees then correct a strong baseline instead of rebuilding the TOU level from scratch
  P50       a Huber-loss model (robust: a few spike hours don't drag the median; plain L2 / quantile P50 over-fitted
            the day-to-day level of the peak band on this data)
  P10, P90  quantile-loss (pinball) models, strongly regularised: the training rows overlap (each hour is a target
            of up to H origins), so small leaves memorise single days
  CQR       the models are first fitted without the last `calibration_share` of each EMS's training origins; on those
            held-out origins the conformity score max(P10 - y, y - P90) gives the margin that makes P10-P90 cover
            80 %, per horizon bucket. The models are then refitted on all training rows with that margin kept.
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb

from usecases.price_forecast.models.base import Forecaster, TrainData, frame

COVERAGE = 0.8
H_BUCKETS = [(1, 6), (7, 24), (25, 1000)]

COMMON = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 5000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "huber_delta", "label": "Huber δ for P50 ($/MWh)", "type": "float", "default": 1.0, "min": 0.1, "max": 200, "step": 0.5,
     "help": "Errors beyond δ count linearly: small δ ≈ median regression, large δ ≈ least squares."},
    {"name": "anchor", "label": "Anchor on same hour, last known day (1 = yes)", "type": "int", "default": 1, "min": 0, "max": 1, "step": 1,
     "help": "Learn the change from the seasonal-naïve value instead of the price level."},
    {"name": "calibration_share", "label": "Calibration share (CQR)", "type": "float", "default": 0.15, "min": 0, "max": 0.4, "step": 0.05,
     "help": "Latest share of each EMS's training origins held out to calibrate P10-P90 to 80 % coverage (0 = raw quantiles)."},
]


def calibration_mask(rows: pd.DataFrame, share: float) -> np.ndarray:
    """True for the rows of the latest `share` of each EMS's training origins."""
    if share <= 0:
        return np.zeros(len(rows), bool)
    cut = rows.groupby("ems_id")["origin_pos"].transform(lambda o: o.quantile(1 - share))
    return (rows["origin_pos"] > cut).to_numpy()


def cqr_margins(y, lo, hi, horizon) -> dict[str, float]:
    out = {}
    score = np.maximum(lo - y, y - hi)
    for a, b in H_BUCKETS:
        m = (horizon >= a) & (horizon <= b)
        if m.sum() < 20:
            continue
        n = m.sum()
        q = min(1.0, np.ceil((n + 1) * COVERAGE) / n)
        out[f"{a}-{b}"] = float(np.quantile(score[m], q))
    return out


def apply_margins(lo, hi, horizon, margins):
    e = np.zeros(len(lo))
    for a, b in H_BUCKETS:
        e[(horizon >= a) & (horizon <= b)] = margins.get(f"{a}-{b}", 0.0)
    return lo - e, hi + e


class _CqrBooster(Forecaster):
    family = "primary"

    def _fit_models(self, X, y):  # -> (p50 model, quantile model(s))
        raise NotImplementedError

    def _predict_models(self, X):  # -> p10, p50, p90
        raise NotImplementedError

    def _anchor(self, rows) -> np.ndarray:
        return rows["same_hour_day"].to_numpy() if int(self.params.get("anchor", 1)) else np.zeros(len(rows))

    def fit(self, data: TrainData, rows: pd.DataFrame | None = None) -> "_CqrBooster":
        r = data.rows if rows is None else rows
        self.features = data.features
        target = r["y"].to_numpy() - self._anchor(r)
        share = float(self.params["calibration_share"])
        cal = calibration_mask(r, share)
        self.margins = {}
        if cal.any() and (~cal).sum() > 100:
            self._fit_models(r.loc[~cal, self.features], target[~cal])
            lo, _, hi = self._predict_models(r.loc[cal, self.features])
            self.margins = cqr_margins(target[cal], lo, hi, r.loc[cal, "horizon"].to_numpy())
        self._fit_models(r[self.features], target)
        return self

    def quantiles(self, rows):
        lo, p50, hi = self._predict_models(rows[self.features])
        lo, hi = apply_margins(lo, hi, rows["horizon"].to_numpy(), self.margins)
        a = self._anchor(rows)
        return lo + a, p50 + a, hi + a

    def predict(self, rows, series):
        lo, p50, hi = self.quantiles(rows)
        return frame(rows, lo, p50, hi)


class LightGBMQuantile(_CqrBooster):
    key = "lightgbm"
    label = "LightGBM (Huber P50 + quantile P10/P90, CQR)"
    param_specs = COMMON + [
        {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 31, "min": 2, "max": 512, "step": 1},
        {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 300, "min": 1, "max": 20000, "step": 10},
    ]

    def _kw(self):
        p = self.params
        return dict(n_estimators=int(p["n_estimators"]), learning_rate=p["learning_rate"], subsample=p["subsample"],
                    colsample_bytree=p["colsample_bytree"], num_leaves=int(p["num_leaves"]),
                    min_child_samples=int(p["min_child_samples"]), subsample_freq=1, random_state=self.seed,
                    verbose=-1, n_jobs=4)

    def _fit_models(self, X, y):
        kw = self._kw()
        self.models = {
            0.5: lgb.LGBMRegressor(objective="huber", alpha=self.params["huber_delta"], **kw).fit(X, y),
            0.1: lgb.LGBMRegressor(objective="quantile", alpha=0.1, **kw).fit(X, y),
            0.9: lgb.LGBMRegressor(objective="quantile", alpha=0.9, **kw).fit(X, y),
        }

    def _predict_models(self, X):
        return self.models[0.1].predict(X), self.models[0.5].predict(X), self.models[0.9].predict(X)

    def importance(self):
        b = self.models[0.5].booster_
        return dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float)))


class XGBoostQuantile(_CqrBooster):
    key = "xgboost"
    label = "XGBoost (pseudo-Huber P50 + quantile P10/P90, CQR)"
    param_specs = COMMON + [
        {"name": "max_depth", "label": "Max tree depth", "type": "int", "default": 5, "min": 1, "max": 16, "step": 1},
        {"name": "min_child_weight", "label": "Min child weight", "type": "float", "default": 100, "min": 0, "max": 20000, "step": 10},
    ]

    def _kw(self):
        p = self.params
        return dict(n_estimators=int(p["n_estimators"]), learning_rate=p["learning_rate"], subsample=p["subsample"],
                    colsample_bytree=p["colsample_bytree"], max_depth=int(p["max_depth"]),
                    min_child_weight=p["min_child_weight"], random_state=self.seed, n_jobs=4, tree_method="hist")

    def _fit_models(self, X, y):
        kw = self._kw()
        self.p50 = xgb.XGBRegressor(objective="reg:pseudohubererror", huber_slope=self.params["huber_delta"], **kw).fit(X, y)
        # one booster, two quantile outputs
        self.band = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=np.array([0.1, 0.9]), **kw).fit(X, y)

    def _predict_models(self, X):
        b = self.band.predict(X)
        return b[:, 0], self.p50.predict(X), b[:, 1]

    def importance(self):
        return {f: float(v) for f, v in self.p50.get_booster().get_score(importance_type="gain").items()}
