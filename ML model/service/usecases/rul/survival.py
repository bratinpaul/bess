"""Survival models on landmark rows: each snapshot is a landmark with its features, the time from it to the unit's end
of life (event = 1) or to its last observation (still in service: censored, event = 0). Both models give a survival
curve S(t | x) from the landmark; RUL quantiles are where it crosses 0.9 (P10), 0.5 (P50) and 0.1 (P90). Where a curve
does not fall that far within the observed follow-up the quantile is 'beyond' (capped at the longest follow-up).

CoxPH          proportional hazards, ridge-penalised Newton fit (Breslow ties), Breslow baseline hazard
RandomSurvival bootstrap (by unit) survival trees: random feature subsets, log-rank splits on binned time, Nelson-Aalen
Forest         cumulative hazard in the leaves, averaged over the trees
Implemented in numpy (no scikit-survival / lifelines dependency).
"""
from typing import Optional

import numpy as np


def quantile_times(times: np.ndarray, surv: np.ndarray, cap: float) -> tuple[dict, bool]:
    """RUL quantiles from S(t) on `times` (rows: subjects). Returns ({p10, p50, p90: array}, beyond flags for p50)."""
    out = {}
    beyond = None
    for q, level in (("p10", 0.9), ("p50", 0.5), ("p90", 0.1)):
        hit = surv <= level
        idx = np.argmax(hit, axis=1)
        found = hit[np.arange(len(surv)), idx]
        t = np.where(found, times[idx], cap)
        out[q] = t.astype(float)
        if q == "p50":
            beyond = ~found
    return out, beyond


class CoxPH:
    def __init__(self, penalizer: float = 0.1, max_iter: int = 60):
        self.penalizer, self.max_iter = penalizer, max_iter

    def fit(self, X: np.ndarray, durations: np.ndarray, events: np.ndarray) -> "CoxPH":
        X = np.asarray(X, float)
        self.mu = np.nanmean(X, axis=0)
        self.sd = np.nanstd(X, axis=0)
        self.sd[~(self.sd > 1e-9)] = 1.0
        Z = np.nan_to_num((X - self.mu) / self.sd)
        order = np.argsort(-durations, kind="stable")  # descending: risk sets are prefixes
        Z, t, e = Z[order], np.asarray(durations, float)[order], np.asarray(events, float)[order]
        beta = np.zeros(Z.shape[1])
        for _ in range(self.max_iter):
            eta = np.clip(Z @ beta, -30, 30)
            w = np.exp(eta)
            # risk-set sums at each subject (prefix sums over descending time; ties share the full risk set)
            s0 = np.cumsum(w)
            s1 = np.cumsum(w[:, None] * Z, axis=0)
            s2 = np.cumsum(w[:, None, None] * (Z[:, :, None] * Z[:, None, :]), axis=0)
            last = np.r_[np.flatnonzero(np.diff(t) != 0), len(t) - 1]  # last index of each tie group
            grp = np.searchsorted(last, np.arange(len(t)))
            S0, S1, S2 = s0[last][grp], s1[last][grp], s2[last][grp]
            ev = e > 0
            zbar = S1[ev] / S0[ev, None]
            grad = (Z[ev] - zbar).sum(axis=0) - self.penalizer * beta
            hess = -(S2[ev] / S0[ev, None, None] - zbar[:, :, None] * zbar[:, None, :]).sum(axis=0)
            hess -= self.penalizer * np.eye(len(beta))
            step = np.linalg.solve(hess, grad)
            beta = beta - step
            if np.max(np.abs(step)) < 1e-7:
                break
        self.beta = beta
        # Breslow baseline cumulative hazard at the event times
        eta = np.exp(np.clip(Z @ beta, -30, 30))
        ut = np.unique(t[e > 0])
        d = np.array([np.sum((t == u) & (e > 0)) for u in ut], float)
        risk = np.array([eta[t >= u].sum() for u in ut])
        self.times = ut
        self.H0 = np.cumsum(d / risk)
        self.max_t = float(t.max())
        return self

    def survival(self, X: np.ndarray, grid: np.ndarray) -> np.ndarray:
        Z = np.nan_to_num((np.asarray(X, float) - self.mu) / self.sd)
        r = np.exp(np.clip(Z @ self.beta, -30, 30))
        H0 = np.interp(grid, self.times, self.H0, left=0.0, right=self.H0[-1] if len(self.H0) else 0.0) \
            if len(self.times) else np.zeros_like(grid)
        return np.exp(-r[:, None] * H0[None, :])

    def coefficients(self, names: list[str]) -> dict:
        return {n: {"coef": float(b), "hazard_ratio_per_sd": float(np.exp(b))} for n, b in zip(names, self.beta)}


class RandomSurvivalForest:
    def __init__(self, n_trees: int = 100, max_depth: int = 6, min_leaf: int = 15, max_features: Optional[float] = 0.5,
                 n_bins: int = 60, seed: int = 42):
        self.n_trees, self.max_depth, self.min_leaf = n_trees, max_depth, min_leaf
        self.max_features, self.n_bins, self.seed = max_features, n_bins, seed

    def fit(self, X: np.ndarray, durations: np.ndarray, events: np.ndarray, groups: np.ndarray) -> "RandomSurvivalForest":
        X = np.nan_to_num(np.asarray(X, float), nan=np.nanmedian(X) if np.isfinite(X).any() else 0.0)
        t, e = np.asarray(durations, float), np.asarray(events, int)
        self.edges = np.linspace(0, t.max() * 1.0001, self.n_bins + 1)
        self.grid = self.edges[1:]
        self.max_t = float(t.max())
        tb = np.clip(np.searchsorted(self.edges, t, side="right") - 1, 0, self.n_bins - 1)
        rng = np.random.default_rng(self.seed)
        units = np.unique(groups)
        n_feat = X.shape[1]
        k = max(1, int(round(n_feat * self.max_features))) if self.max_features else n_feat
        self.trees, self.importance_ = [], np.zeros(n_feat)
        for _ in range(self.n_trees):
            pick = rng.choice(units, size=len(units), replace=True)  # bootstrap units, not rows
            idx = np.concatenate([np.flatnonzero(groups == u) for u in pick])
            self.trees.append(self._grow(X, tb, e, idx, 0, rng, k))
        total = self.importance_.sum()
        self.importance_ = self.importance_ / total if total > 0 else self.importance_
        return self

    def _chf(self, tb, e):
        d = np.bincount(tb[e > 0], minlength=self.n_bins).astype(float)
        n_out = np.bincount(tb, minlength=self.n_bins).astype(float)
        at_risk = n_out[::-1].cumsum()[::-1]
        return np.cumsum(np.where(at_risk > 0, d / np.maximum(at_risk, 1), 0.0))

    def _logrank(self, tb, e, left):
        """Log-rank statistic of a split, on binned times."""
        d = np.bincount(tb[e > 0], minlength=self.n_bins).astype(float)
        dl = np.bincount(tb[(e > 0) & left], minlength=self.n_bins).astype(float)
        n = np.bincount(tb, minlength=self.n_bins).astype(float)[::-1].cumsum()[::-1]
        nl = np.bincount(tb[left], minlength=self.n_bins).astype(float)[::-1].cumsum()[::-1]
        ok = n > 1
        exp = np.where(ok, d * nl / np.maximum(n, 1), 0.0)
        var = np.where(ok, d * (nl / np.maximum(n, 1)) * (1 - nl / np.maximum(n, 1)) * (n - d) / np.maximum(n - 1, 1), 0.0)
        v = var.sum()
        return (dl.sum() - exp.sum()) ** 2 / v if v > 0 else 0.0

    def _grow(self, X, tb, e, idx, depth, rng, k):
        node_tb, node_e = tb[idx], e[idx]
        if depth >= self.max_depth or len(idx) < 2 * self.min_leaf or node_e.sum() == 0:
            return ("leaf", self._chf(node_tb, node_e))
        best = (0.0, None, None)
        for f in rng.choice(X.shape[1], size=k, replace=False):
            vals = X[idx, f]
            for thr in np.unique(np.quantile(vals, np.linspace(0.1, 0.9, 9))):
                left = vals <= thr
                nl = left.sum()
                if nl < self.min_leaf or len(idx) - nl < self.min_leaf:
                    continue
                stat = self._logrank(node_tb, node_e, left)
                if stat > best[0]:
                    best = (stat, f, thr)
        if best[1] is None:
            return ("leaf", self._chf(node_tb, node_e))
        stat, f, thr = best
        self.importance_[f] += stat
        left = X[idx, f] <= thr
        return ("split", f, thr, self._grow(X, tb, e, idx[left], depth + 1, rng, k),
                self._grow(X, tb, e, idx[~left], depth + 1, rng, k))

    def _leaf(self, node, x):
        while node[0] == "split":
            node = node[3] if x[node[1]] <= node[2] else node[4]
        return node[1]

    def survival(self, X: np.ndarray) -> np.ndarray:
        X = np.nan_to_num(np.asarray(X, float))
        chf = np.zeros((len(X), self.n_bins))
        for tree in self.trees:
            chf += np.array([self._leaf(tree, x) for x in X])
        return np.exp(-chf / len(self.trees))
