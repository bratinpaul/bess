"""Spike handling: classifier (spike / no spike) + regressors.

  normal model   the primary LightGBM (Huber P50, quantile P10 / P90, CQR-calibrated) on the hours without a spike
                 (spikes don't bend the base curve), plus a least-squares model for the normal mean
  classifier     LightGBM binary on the same features, small and unweighted so its probability stays calibrated
                 (class weighting inflated it and let it memorise single spike days); probability that the target
                 hour holds a spike. The spike rate per hour of day (training) is kept as the reference it must beat.
  spike size     the hourly price of a spike hour: a regressor on the spike rows when there are enough, else the
                 median spike uplift over the normal P50 per TOU band
Combined: mean = (1 - p) x normal mean + p x spike price (what an expected-value optimizer wants); P50 / P10 stay the
normal ones (a rare spike doesn't move the median); P90 = the spike price where p >= 10 % (the upper tail is the spike).
"""
import lightgbm as lgb
import numpy as np

from usecases.price_forecast.models.base import Forecaster, TrainData, frame
from usecases.price_forecast.models.gbm import LightGBMQuantile

MIN_SPIKE_ROWS = 40


class SpikeHybrid(Forecaster):
    key = "spike_hybrid"
    label = "Spike hybrid (classifier + regressors)"
    family = "spike"
    param_specs = [
        {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 5000, "step": 10},
        {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
        {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 15, "min": 2, "max": 512, "step": 1},
        {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 300, "min": 1, "max": 20000, "step": 10},
        {"name": "clf_rounds", "label": "Classifier rounds", "type": "int", "default": 150, "min": 10, "max": 3000, "step": 10},
        {"name": "clf_leaves", "label": "Classifier leaves per tree", "type": "int", "default": 4, "min": 2, "max": 128, "step": 1},
        {"name": "clf_min_child", "label": "Classifier min rows per leaf", "type": "int", "default": 500, "min": 5, "max": 20000, "step": 5},
    ]

    def fit(self, data: TrainData) -> "SpikeHybrid":
        self.features = data.features
        r = data.rows
        p = self.params
        common = dict(n_estimators=int(p["n_estimators"]), learning_rate=p["learning_rate"], num_leaves=int(p["num_leaves"]),
                      min_child_samples=int(p["min_child_samples"]), random_state=self.seed, verbose=-1, n_jobs=4)
        normal = r[r["spike"] == 0]
        self.normal = LightGBMQuantile({"n_estimators": p["n_estimators"], "learning_rate": p["learning_rate"],
                                        "num_leaves": p["num_leaves"], "min_child_samples": p["min_child_samples"]},
                                       self.seed).fit(data, rows=normal)
        self.normal_mean = lgb.LGBMRegressor(objective="regression", **common).fit(normal[self.features], normal["y"])
        n_spike = int(r["spike"].sum())
        self.n_spike = n_spike
        self.base_rate = float(r["spike"].mean())
        if n_spike < 5:
            data.warnings.append(f"Only {n_spike} spike hours in the training rows: the spike classifier is not fitted")
            self.clf = None
        else:
            self.clf = lgb.LGBMClassifier(n_estimators=int(p["clf_rounds"]), learning_rate=p["learning_rate"],
                                          num_leaves=int(p["clf_leaves"]), min_child_samples=int(p["clf_min_child"]),
                                          random_state=self.seed, verbose=-1, n_jobs=4).fit(r[self.features], r["spike"])
        self.hour_rate = r.groupby("hour")["spike"].mean().to_dict() if "hour" in r else {}
        spikes = r[r["spike"] == 1]
        base = self.normal.quantiles(spikes)[1] if n_spike else np.array([])
        uplift = spikes["y"].to_numpy() - base
        self.uplift_by_band = ({int(b): float(np.median(uplift[spikes["band_idx"].to_numpy() == b]))
                                for b in np.unique(spikes["band_idx"])} if n_spike and "band_idx" in spikes else {})
        self.uplift_all = float(np.median(uplift)) if n_spike else 0.0
        self.size_model = None
        if n_spike >= MIN_SPIKE_ROWS:
            self.size_model = lgb.LGBMRegressor(objective="regression_l1", **{**common, "min_child_samples": 5}).fit(
                spikes[self.features], spikes["y"])
        else:
            data.warnings.append(f"{n_spike} spike hours (< {MIN_SPIKE_ROWS}): spike size = median uplift per TOU band")
        return self

    def spike_price(self, X, base):
        if self.size_model is not None:
            return np.maximum(self.size_model.predict(X), base)
        bands = X["band_idx"].to_numpy() if "band_idx" in X else np.full(len(X), -1)
        up = np.array([self.uplift_by_band.get(int(b), self.uplift_all) for b in bands])
        return base + np.maximum(up, 0)

    def predict(self, rows, series):
        X = rows[self.features]
        lo, p50, hi = self.normal.quantiles(rows)
        q = {0.1: lo, 0.5: p50, 0.9: hi}
        mean_n = self.normal_mean.predict(X)
        prob = self.clf.predict_proba(X)[:, 1] if self.clf is not None else np.zeros(len(X))
        size = self.spike_price(X, q[0.5])
        mean = (1 - prob) * mean_n + prob * size
        p90 = np.where(prob >= 0.10, np.maximum(size, q[0.9]), q[0.9])
        return frame(rows, q[0.1], q[0.5], p90, mean=mean, spike=prob)

    def importance(self):
        if self.clf is None:
            return {}
        b = self.clf.booster_
        return dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float)))
