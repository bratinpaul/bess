"""Daily billing-peak forecasts and the peak-exceedance classifier.

From a 5-min forecast path: for every target day whose billing-peak window lies wholly inside the horizon, the peak
is the highest P50 in the window and its interval; the band is the highest P10 / P90 in the window (the max of a
quantile path - exact when errors move together across the window, which is how load errors behave). The
exceedance probability treats the peak as normal with that P50 and the P10-P90 spread (P90 - P10 = 2 x 1.2816 sd).

The classifier (logistic regression, standardised inputs, L2) answers "will today's billing peak exceed the
threshold" from day-level inputs known at the origin: workday / holiday, the anchor profile's peak (the
same-type-day mean, the naïve peak), the newest same-type and newest day's actual peak, the forecast temperature
peak and the day's mean forecast GHI, and the lead time - all relative to the threshold. Its reference is the
training exceedance rate per day class (workday / non-workday): beating it means the classifier knows *which*
workdays breach, not just that workdays do.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from usecases.netload_forecast.features import PER_HOUR

Z80 = 1.2816
CLF_FEATURES = ["workday", "holiday", "anchor_peak_m", "peak_last_class_m", "peak_last_day_m", "temp_fc_max",
                "ghi_fc_mean", "lead_h"]


def window_steps(window: tuple[float, float]) -> int:
    return int(round((window[1] - window[0]) * PER_HOUR))


def day_groups(rows: pd.DataFrame, window: tuple[float, float]) -> pd.DataFrame:
    """Index of the rows in a complete billing window, per (mp, origin, target day)."""
    w = rows[rows["in_window"] == 1]
    full = window_steps(window)
    g = w.groupby(["mp_id", "origin_pos", "target_date"]).size()
    return g[g >= full].reset_index()[["mp_id", "origin_pos", "target_date"]]


def peaks_from_forecast(rows: pd.DataFrame, fc: pd.DataFrame, window, threshold: float) -> pd.DataFrame:
    """Forecast daily peaks per (mp, origin, target day) with a complete window in the horizon."""
    df = rows[["mp_id", "origin_pos", "origin_ts", "target_ts", "target_date", "in_window", "horizon_h"]].copy()
    df[["p10", "p50", "p90"]] = fc[["p10", "p50", "p90"]].to_numpy()
    if "y" in rows:
        df["y"] = rows["y"].to_numpy()
    w = df[df["in_window"] == 1]
    full = window_steps(window)
    out = []
    for (mp, opos, d), g in w.groupby(["mp_id", "origin_pos", "target_date"], sort=False):
        if len(g) < full:
            continue
        i = g["p50"].to_numpy().argmax()
        p50, p10, p90 = float(g["p50"].max()), float(g["p10"].max()), float(g["p90"].max())
        sd = max((p90 - p10) / (2 * Z80), 1e-6)
        rec = {"mp_id": int(mp), "origin_pos": int(opos), "origin_ts": g["origin_ts"].iloc[0], "target_date": d,
               "lead_h": float(g["horizon_h"].iloc[0]), "p10": p10, "p50": p50, "p90": p90,
               "peak_ts": g["target_ts"].iloc[i], "prob_exceed": float(1 - norm.cdf((threshold - p50) / sd))}
        if "y" in g and np.isfinite(g["y"]).all():
            j = g["y"].to_numpy().argmax()
            rec["actual"] = float(g["y"].iloc[j])
            rec["actual_ts"] = g["target_ts"].iloc[j]
        out.append(rec)
    return pd.DataFrame(out)


MIN_CAL_PEAKS = 6


def peak_calibration(cal_peaks: pd.DataFrame) -> dict:
    """How far the actual billing peak sits from the highest P50 of the window, on held-out training days: the
    highest point of a smooth P50 path is not the expected highest 5-min reading (that one includes the reading-to-
    reading noise), so the raw peak runs low."""
    if cal_peaks.empty or "actual" not in cal_peaks:
        return {"n": 0}
    off = (cal_peaks["actual"] - cal_peaks["p50"]).dropna().to_numpy()
    if len(off) < MIN_CAL_PEAKS:
        return {"n": int(len(off))}
    q10, med, q90 = np.quantile(off, [0.1, 0.5, 0.9])
    return {"n": int(len(off)), "days": int(cal_peaks["target_date"].nunique()), "median": float(med),
            "q10": float(q10), "q90": float(q90)}


def calibrate_peaks(pf: pd.DataFrame, cal: dict, threshold: float) -> pd.DataFrame:
    """Peak P10 / P50 / P90 = highest P50 of the window + the held-out offsets' 10 / 50 / 90 % quantiles; the
    exceedance probability from a normal with that median and spread. Without enough held-out peaks: unchanged."""
    if pf.empty or not cal or cal.get("n", 0) < MIN_CAL_PEAKS:
        return pf
    pf = pf.copy()
    raw = pf["p50"].to_numpy()
    pf["p50_raw"] = raw
    pf["p10"] = raw + cal["q10"]
    pf["p50"] = raw + cal["median"]
    pf["p90"] = raw + cal["q90"]
    sd = max((cal["q90"] - cal["q10"]) / (2 * Z80), 1.0)
    pf["prob_exceed"] = 1 - norm.cdf((threshold - pf["p50"].to_numpy()) / sd)
    return pf


def day_rows(rows: pd.DataFrame, window, threshold: float, with_target: bool = True) -> pd.DataFrame:
    """Day-level classifier inputs (and label) per (mp, origin, target day) with a complete window."""
    full = window_steps(window)
    out = []
    for (mp, opos, d), g in rows.groupby(["mp_id", "origin_pos", "target_date"], sort=False):
        w = g[g["in_window"] == 1]
        if len(w) < full:
            continue
        rec = {"mp_id": int(mp), "origin_pos": int(opos), "origin_ts": g["origin_ts"].iloc[0], "target_date": d,
               "workday": float(g["workday"].iloc[0]), "holiday": float(g["holiday"].iloc[0]),
               "anchor_peak_m": float(w["anchor"].max()) - threshold,
               "peak_last_class_m": float(g["peak_last_class"].iloc[0]) - threshold,
               "peak_last_day_m": float(g["peak_last_day"].iloc[0]) - threshold,
               "temp_fc_max": float(w["temp_fc"].max()), "ghi_fc_mean": float(g["ghi_fc"].mean()),
               "lead_h": float(w["horizon_h"].iloc[0])}
        if with_target and "y" in w:
            rec["actual"] = float(w["y"].max())
            rec["exceed"] = int(rec["actual"] > threshold)
        out.append(rec)
    return pd.DataFrame(out)


class PeakClassifier:
    key = "peak_classifier"
    label = "Peak-exceedance classifier (logistic)"
    family = "peak"
    param_specs = [
        {"name": "C", "label": "Inverse regularisation C", "type": "float", "default": 0.5, "min": 0.001, "max": 100, "step": 0.1,
         "help": "Smaller = stronger L2 shrinkage; keep it small with few training days."},
    ]

    def __init__(self, params=None, seed: int = 42):
        self.params = {s["name"]: s["default"] for s in self.param_specs}
        self.params.update(params or {})
        self.seed = seed
        self.clf = None

    def fit(self, days: pd.DataFrame, warnings: list[str]) -> "PeakClassifier":
        days = days.dropna(subset=CLF_FEATURES + ["exceed"])
        self.class_rate = days.groupby("workday")["exceed"].mean().to_dict() if len(days) else {}
        self.base_rate = float(days["exceed"].mean()) if len(days) else 0.0
        self.n_days = int(days["target_date"].nunique()) if len(days) else 0
        if days["exceed"].nunique() < 2 if len(days) else True:
            warnings.append("Peak classifier: the training days are all on one side of the threshold - not fitted "
                            "(its probability is the training rate)")
            return self
        self.scaler = StandardScaler().fit(days[CLF_FEATURES])
        self.clf = LogisticRegression(C=float(self.params["C"]), max_iter=500).fit(
            self.scaler.transform(days[CLF_FEATURES]), days["exceed"])
        if self.n_days < 30:
            warnings.append(f"Peak classifier: only {self.n_days} distinct training days - its probabilities are "
                            "rough; more history makes it useful")
        return self

    def predict_proba(self, days: pd.DataFrame) -> np.ndarray:
        if self.clf is None:
            return np.full(len(days), self.base_rate)
        X = days[CLF_FEATURES].fillna(0.0)
        return self.clf.predict_proba(self.scaler.transform(X))[:, 1]

    def reference(self, days: pd.DataFrame) -> np.ndarray:
        return days["workday"].map(self.class_rate).fillna(self.base_rate).to_numpy(float)

    def coefficients(self) -> dict[str, float]:
        if self.clf is None:
            return {}
        return {f: float(c) for f, c in zip(CLF_FEATURES, self.clf.coef_[0])}
