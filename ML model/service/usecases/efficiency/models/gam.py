"""GAM: η = β0 + f_dir(load) + Σ f_j(x_j) + linear terms, fitted as a penalised regression spline model.

Each continuous input gets a cubic B-spline basis (knots at quantiles of the training rows, constant beyond
them so it extrapolates flat), the load fraction gets one smooth curve per direction (the vendor efficiency
curve shape), binary inputs and the unit identity enter linearly. A ridge penalty on the spline coefficients
keeps the curves smooth. Each term's partial-dependence curve is the term's contribution over its range,
which is how vendors publish efficiency maps.
"""
from typing import ClassVar, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import SplineTransformer

BINARY = ("is_charge", "gs_freq_watt", "gs_volt_var")
# |S| / rated is ~ the load fraction / PF (correlation 0.9995): as a second smooth term it double-counts the load
# when the curve leaves the data, so the GAM takes reactive loading from the power factor only
EXCLUDED = ("s_frac",)


class GamEfficiencyModel:
    key: ClassVar[str] = "gam"
    label: ClassVar[str] = "GAM (additive splines)"
    param_specs: ClassVar[list[dict]] = [
        {"name": "n_knots", "label": "Knots per smooth term", "type": "int", "default": 8, "min": 3, "max": 30, "step": 1},
        {"name": "load_knots", "label": "Knots for the load curve", "type": "int", "default": 12, "min": 4, "max": 40, "step": 1,
         "help": "The load fraction drives efficiency the most; it gets its own (finer) curve per direction."},
        {"name": "alpha", "label": "Smoothing penalty (ridge α)", "type": "float", "default": 1.0, "min": 0.0001, "max": 1000, "step": 0.1},
        {"name": "unit_terms", "label": "Per-unit offset (asset identity)", "type": "bool", "default": True},
    ]

    def __init__(self, params: Optional[dict] = None):
        p = {s["name"]: s["default"] for s in self.param_specs}
        p.update(params or {})
        self.params = p
        self.features: list[str] = []
        self.splines: dict[str, SplineTransformer] = {}
        self.ranges: dict[str, tuple[float, float]] = {}
        self.units: list[int] = []
        self.ridge: Optional[Ridge] = None
        self.blocks: list[tuple[str, int, int]] = []  # (term, start, end) columns of the design

    def _smooth_features(self) -> list[str]:
        return [f for f in self.features if f not in BINARY and f not in EXCLUDED and f != "load_frac"]

    def _design(self, X: pd.DataFrame) -> np.ndarray:
        cols, self.blocks, at = [], [], 0

        def add(term: str, M: np.ndarray):
            nonlocal at
            cols.append(M)
            self.blocks.append((term, at, at + M.shape[1]))
            at += M.shape[1]

        chg = X["is_charge"].to_numpy(float)[:, None]
        load = self.splines["load_frac"].transform(X[["load_frac"]].clip(*self.ranges["load_frac"]))
        add("load_frac|charge", load * chg)
        add("load_frac|discharge", load * (1 - chg))
        for f in self._smooth_features():
            add(f, self.splines[f].transform(X[[f]].clip(*self.ranges[f])))
        for f in BINARY:
            if f in self.features and f != "is_charge":
                add(f, X[[f]].to_numpy(float))
        add("is_charge", chg)
        if self.params["unit_terms"] and len(self.units) > 1:
            pcs = X["pcs_id"].to_numpy()
            add("unit", np.column_stack([(pcs == u).astype(float) for u in self.units[1:]]))
        return np.hstack(cols)

    def fit(self, X: pd.DataFrame, y: np.ndarray, features: list[str]) -> "GamEfficiencyModel":
        self.features = [f for f in features if f in X]
        self.units = sorted(int(u) for u in X["pcs_id"].unique())
        for f in ["load_frac"] + self._smooth_features():
            lo, hi = np.nanpercentile(X[f], [0.5, 99.5])
            if hi <= lo:
                hi = lo + 1e-3
            self.ranges[f] = (float(lo), float(hi))
            n = self.params["load_knots"] if f == "load_frac" else self.params["n_knots"]
            n = int(max(3, min(n, X[f].nunique())))
            # quantile knots for the load (sparse at light load), evenly spaced for the rest (quantile knots bunch
            # up where readings pile up, e.g. PF ≈ 1, and make the curve wiggle there)
            self.splines[f] = SplineTransformer(n_knots=n, degree=3, knots="quantile" if f == "load_frac" else "uniform",
                                                extrapolation="constant",
                                                include_bias=False).fit(X[[f]].clip(lo, hi))
        self.ridge = Ridge(alpha=float(self.params["alpha"])).fit(self._design(X), y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(self.ridge.predict(self._design(X)), 50.0, 100.0)

    def term_contributions(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Each term's contribution to the prediction (percentage points)."""
        A = self._design(X)
        return {t: A[:, s:e] @ self.ridge.coef_[s:e] for t, s, e in self.blocks}

    def partial_dependence(self, X: pd.DataFrame, n: int = 40) -> dict[str, list[dict]]:
        """Each term's shape function: its contribution (percentage points of η) over its training range, centred on
        its mean over the training rows - the GAM's partial dependence. The load term per direction."""
        out: dict[str, list[dict]] = {}
        for term in ["load_frac|charge", "load_frac|discharge"] + self._smooth_features():
            f = term.split("|")[0]
            lo, hi = self.ranges[f]
            grid = np.linspace(lo, hi, n)
            _, s, e = next(b for b in self.blocks if b[0] == term)
            coef = self.ridge.coef_[s:e]
            basis = lambda v: self.splines[f].transform(pd.DataFrame({f: np.clip(v, lo, hi)}))  # noqa: E731
            if "|" in term:
                mask = (X["is_charge"] == (1.0 if term.endswith("charge") and not term.endswith("discharge") else 0.0))
                ref = float((basis(X.loc[mask, f].to_numpy()) @ coef).mean()) if mask.any() else 0.0
            else:
                ref = float((basis(X[f].to_numpy()) @ coef).mean())
            out[term] = [{"x": float(x), "y": float(v - ref)} for x, v in zip(grid, basis(grid) @ coef)]
        return out
