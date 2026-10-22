"""The detectors. Each learns "normal" from standardised training rows and returns, per row, a raw anomaly score
(higher = more abnormal) and per-feature contributions (non-negative, the attribution shown to operators).

    pca         PCA reconstruction: Q-statistic (squared prediction error) and Hotelling's T² - score is the larger of
                the two, each divided by its training limit; contributions = per-feature squared residual (Q) or the
                per-feature share of T², whichever drives the score. The interpretable baseline.
    iforest     Isolation Forest; contributions = |robust z| of each feature vs training (no SHAP installed).
    robust_cov  Elliptic Envelope (Minimum Covariance Determinant): squared Mahalanobis distance; contributions =
                (x−μ)ᵢ · (Σ⁻¹(x−μ))ᵢ, clipped at 0 - an exact split of the distance.
    autoencoder Dense autoencoder (scikit-learn MLP, bottleneck): mean squared reconstruction error; contributions =
                per-feature squared error.
    window_ae   Temporal autoencoder on the last k intervals stacked (a lightweight stand-in for an LSTM-AE, no torch):
                window reconstruction error; contributions summed over the window per feature.
"""
from typing import Optional

import numpy as np
from sklearn.covariance import EllipticEnvelope
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor

MODEL_LABELS = {
    "pca": "PCA (Q / T²)",
    "iforest": "Isolation Forest",
    "robust_cov": "Robust covariance (Elliptic Envelope)",
    "autoencoder": "Autoencoder",
    "window_ae": "Temporal autoencoder (window)",
}
INTERPRETABLE = {"pca", "robust_cov", "autoencoder", "window_ae"}

DEFAULT_PARAMS = {
    "pca": {"variance": 0.95},
    "iforest": {"n_estimators": 300, "max_samples": 512},
    "robust_cov": {"support_fraction": 0.9, "max_rows": 6000},
    "autoencoder": {"bottleneck": 6, "hidden": 24, "max_iter": 300},
    "window_ae": {"window": 6, "bottleneck": 8, "hidden": 48, "max_iter": 200},
}
PARAM_SPECS = {
    "pca": [{"name": "variance", "label": "Explained variance kept", "min": 0.5, "max": 0.999, "step": 0.01}],
    "iforest": [{"name": "n_estimators", "label": "Trees", "min": 50, "max": 1000, "step": 50},
                {"name": "max_samples", "label": "Rows per tree", "min": 64, "max": 4096, "step": 64}],
    "robust_cov": [{"name": "support_fraction", "label": "Support fraction", "min": 0.5, "max": 1.0, "step": 0.05},
                   {"name": "max_rows", "label": "Max fit rows", "min": 1000, "max": 20000, "step": 1000}],
    "autoencoder": [{"name": "bottleneck", "label": "Bottleneck size", "min": 2, "max": 32, "step": 1},
                    {"name": "hidden", "label": "Hidden layer size", "min": 8, "max": 128, "step": 4},
                    {"name": "max_iter", "label": "Max epochs", "min": 50, "max": 2000, "step": 50}],
    "window_ae": [{"name": "window", "label": "Window (intervals)", "min": 2, "max": 24, "step": 1},
                  {"name": "bottleneck", "label": "Bottleneck size", "min": 2, "max": 64, "step": 1},
                  {"name": "hidden", "label": "Hidden layer size", "min": 8, "max": 256, "step": 8},
                  {"name": "max_iter", "label": "Max epochs", "min": 50, "max": 2000, "step": 50}],
}


def _shares(c: np.ndarray) -> np.ndarray:
    c = np.clip(np.nan_to_num(c, nan=0.0), 0, None)
    tot = c.sum(axis=1, keepdims=True)
    return np.divide(c, tot, out=np.zeros_like(c), where=tot > 0)


class Detector:
    key = ""
    window = 1  # rows of history a score needs (temporal models > 1)

    def __init__(self, params: dict, seed: int = 42):
        self.params = {**DEFAULT_PARAMS[self.key], **(params or {})}
        self.seed = seed

    def fit(self, x: np.ndarray, valid: Optional[np.ndarray] = None) -> "Detector":
        raise NotImplementedError

    def fit_rows(self, x_all: np.ndarray, rows: np.ndarray, valid: Optional[np.ndarray] = None) -> "Detector":
        """Fit on the rows of x_all selected by `rows` (temporal models also read the history before them)."""
        return self.fit(x_all[rows])

    def score(self, x: np.ndarray, valid: Optional[np.ndarray] = None) -> tuple[np.ndarray, np.ndarray]:
        """(raw score per row, contribution share per row x feature); NaN score where it can't be computed."""
        raise NotImplementedError


class PcaDetector(Detector):
    key = "pca"

    def fit(self, x, valid=None):
        self.pca = PCA(n_components=float(self.params["variance"]), svd_solver="full", random_state=self.seed).fit(x)
        q, t2, *_ = self._parts(x)
        # each statistic is scaled by its own training 99th percentile so the two are comparable
        self.q_ref = float(np.percentile(q, 99)) or 1.0
        self.t2_ref = float(np.percentile(t2, 99)) or 1.0
        return self

    def _parts(self, x):
        t = self.pca.transform(x)
        resid = x - self.pca.inverse_transform(t)
        q = (resid ** 2).sum(axis=1)
        lam = np.maximum(self.pca.explained_variance_, 1e-12)
        t2 = ((t ** 2) / lam).sum(axis=1)
        return q, t2, t, resid, lam

    def score(self, x, valid=None):
        q, t2, t, resid, lam = self._parts(x)
        qn, tn = q / self.q_ref, t2 / self.t2_ref
        # T² contribution of feature j: x_j · Σ_k p_jk t_k / λ_k (can be negative -> clipped)
        t2_contrib = x * ((t / lam) @ self.pca.components_)
        contrib = np.where((qn >= tn)[:, None], resid ** 2, t2_contrib)
        self.last_parts = {"pca_q": qn, "pca_t2": tn}
        return np.maximum(qn, tn), _shares(contrib)


class IsolationForestDetector(Detector):
    key = "iforest"

    def fit(self, x, valid=None):
        self.model = IsolationForest(n_estimators=int(self.params["n_estimators"]),
                                     max_samples=min(int(self.params["max_samples"]), len(x)),
                                     random_state=self.seed, n_jobs=-1).fit(x)
        self.med = np.median(x, axis=0)
        self.mad = np.median(np.abs(x - self.med), axis=0) * 1.4826 + 1e-6
        return self

    def score(self, x, valid=None):
        return -self.model.score_samples(x), _shares(np.abs((x - self.med) / self.mad))


class RobustCovDetector(Detector):
    key = "robust_cov"

    def fit(self, x, valid=None):
        rng = np.random.default_rng(self.seed)
        n = int(self.params["max_rows"])
        fit_x = x[rng.choice(len(x), n, replace=False)] if len(x) > n else x
        self.model = EllipticEnvelope(support_fraction=float(self.params["support_fraction"]),
                                      random_state=self.seed).fit(fit_x)
        self.loc = self.model.location_
        self.prec = self.model.precision_
        return self

    def score(self, x, valid=None):
        d = x - self.loc
        pd_ = d @ self.prec
        return (d * pd_).sum(axis=1), _shares(d * pd_)


class AutoencoderDetector(Detector):
    key = "autoencoder"

    def _net(self, n_in):
        h, b = int(self.params["hidden"]), int(self.params["bottleneck"])
        return MLPRegressor(hidden_layer_sizes=(h, min(b, n_in), h), activation="tanh", alpha=1e-4,
                            max_iter=int(self.params["max_iter"]), early_stopping=True, validation_fraction=0.1,
                            n_iter_no_change=15, random_state=self.seed)

    def fit(self, x, valid=None):
        self.net = self._net(x.shape[1]).fit(x, x)
        return self

    def score(self, x, valid=None):
        err = (x - self.net.predict(x)) ** 2
        return err.mean(axis=1), _shares(err)


class WindowAutoencoderDetector(AutoencoderDetector):
    """Rows are windows of the last k intervals (needs k consecutive 5-min rows: `valid` marks rows whose window has
    no gap)."""
    key = "window_ae"

    def __init__(self, params, seed=42):
        super().__init__(params, seed)
        self.window = int(self.params["window"])

    def _stack(self, x):
        k, n, f = self.window, len(x), x.shape[1]
        out = np.full((n, k * f), np.nan)
        for lag in range(k):
            out[lag:, lag * f:(lag + 1) * f] = x[: n - lag]
        return out

    def fit(self, x, valid=None):
        return self.fit_rows(x, np.ones(len(x), dtype=bool), valid)

    def fit_rows(self, x_all, rows, valid=None):
        x = x_all
        w = self._stack(x)
        ok = ~np.isnan(w).any(axis=1) & rows & (valid if valid is not None else True)
        if ok.sum() < 50:
            raise ValueError("too few gap-free windows to train the temporal autoencoder")
        self.n_features = x.shape[1]
        self.net = self._net(w.shape[1]).fit(w[ok], w[ok])
        return self

    def score(self, x, valid=None):
        w = self._stack(x)
        ok = ~np.isnan(w).any(axis=1) & (valid if valid is not None else True)
        score = np.full(len(x), np.nan)
        contrib = np.zeros_like(x)
        if ok.any():
            err = (w[ok] - self.net.predict(w[ok])) ** 2
            score[ok] = err.mean(axis=1)
            contrib[ok] = err.reshape(len(err), self.window, self.n_features).sum(axis=1)
        return score, _shares(contrib)


DETECTORS = {d.key: d for d in (PcaDetector, IsolationForestDetector, RobustCovDetector, AutoencoderDetector,
                                WindowAutoencoderDetector)}


def make(key: str, params: dict, seed: int = 42) -> Detector:
    return DETECTORS[key](params, seed)
