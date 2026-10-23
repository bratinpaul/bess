"""SOC estimation / correction: one run = EKF per system (tuned on the training period), LightGBM quantile
corrections, time-split evaluation against the soc_reference anchors, and the live per-system estimator.

Methods (each a SOC per 5-min row, P10 / P50 / P90 where it has a band):
  coulomb       raw coulomb-counted SOC (soc_coulomb_pct) - must beat
  ocv_lookup    naive OCV lookup: the MEAN-curve SOC of the rested OCV where there is one, coulomb otherwise - must beat
  bms           the BMS's own reported SOC (soc_bms_pct) - reference
  ekf           extended Kalman filter (ekf.py): coulomb propagation with bias + capacity-gain states, rested-OCV
                updates, FULL_CHARGE hard recalibration; band from its SOC variance
  gbm           coulomb + LightGBM quantile models of the drift (truth - coulomb) from the features below
  hybrid        EKF + LightGBM quantile models of the EKF residual (truth - EKF) - the recommended estimator

Labels (training): the soc_reference anchors in the training period, or - sample data only - the dense synthetic
truth (battery_raw.soc_estimation_data.soc_true_pct) which covers the flat mid-SOC region the anchors never reach.
Scores (test period): anchors (all / REST_OCV / FULL_CHARGE) and, where the dense truth exists, every row, the flat
25-80 % region and the rows under current. Note: REST_OCV anchors are themselves OCV lookups, so the naive lookup
is nearly exact on them, and FULL_CHARGE anchors are exact for the EKF when it recalibrates on them - the flat-region
score is the one that tells the estimators apart.
"""
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import UseCaseError
from core.metrics import finite, shares
from usecases.soc_estimation import ekf as E
from usecases.soc_estimation import features as F

METHODS = ["coulomb", "ocv_lookup", "bms", "ekf", "gbm", "hybrid"]
BANDED = {"ekf", "gbm", "hybrid"}
SCOPES = ["anchors", "anchors_rest", "anchors_full", "dense", "dense_flat", "dense_active"]
QUANTILES = (0.1, 0.5, 0.9)
FLAT = (25.0, 80.0)
BASE_FEATURES = ["soc_coulomb_pct", "measured_current_a", "current_sensor_offset_a", "i_corr_a", "pack_voltage_v",
                 "cell_v_avg_v", "ocv_rested_v", "ocv_soc", "ocv_minus_coulomb", "cell_temp_avg_c",
                 "usable_capacity_ah", "c_rate", "coulombic_efficiency", "at_rest", "rest_duration_min",
                 "min_since_recal", "ah_since_recal", "direction_code"]
EKF_FEATURES = ["ekf_soc", "ekf_sigma", "ekf_bias", "ekf_gain", "ekf_minus_coulomb"]
GBM_PARAMS = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 5000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 15, "min": 2, "max": 512, "step": 1},
    {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 40, "min": 2, "max": 20000, "step": 1},
    {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
]
EKF_PARAMS = [
    {"name": "r_mv", "label": "OCV noise (mV)", "type": "float", "default": 3.0, "min": 0.1, "max": 50, "step": 0.5,
     "help": "Rested-OCV measurement noise per cell; larger = trust the voltage less"},
    {"name": "q_soc", "label": "SOC process noise (%/5 min)", "type": "float", "default": 0.02, "min": 0, "max": 2, "step": 0.01,
     "help": "Unmodelled SOC change per step"},
    {"name": "q_rel", "label": "Step-relative noise (share)", "type": "float", "default": 0.05, "min": 0, "max": 1, "step": 0.01,
     "help": "SOC uncertainty added per step as a share of the coulomb-counted change - widens the band under current"},
    {"name": "q_bias", "label": "Bias drift (A/5 min)", "type": "float", "default": 0.02, "min": 0, "max": 5, "step": 0.005,
     "help": "How fast the current-sensor offset may wander"},
    {"name": "q_gain", "label": "Capacity-gain drift (/5 min)", "type": "float", "default": 0.00001, "min": 0, "max": 0.01, "step": 0.00001,
     "help": "How fast the capacity scale may wander"},
    {"name": "hysteresis", "label": "Hysteresis weight (0-1)", "type": "float", "default": 1.0, "min": 0, "max": 1, "step": 0.25,
     "help": "0 = MEAN OCV curve, 1 = the charge / discharge branch of the last current direction"},
    {"name": "min_rest_min", "label": "Min rest before OCV (min)", "type": "float", "default": 30, "min": 0, "max": 600, "step": 5,
     "help": "Relaxation time before a rested OCV is used"},
    {"name": "ocv_every_min", "label": "OCV update every (min)", "type": "float", "default": 60, "min": 5, "max": 1440, "step": 5,
     "help": "At most one OCV update per this many minutes of rest (the readings are correlated)"},
]
TUNE_GRID = {"r_mv": [1.0, 3.0, 10.0], "q_bias": [0.005, 0.02, 0.1], "hysteresis": [0.0, 0.5, 1.0]}


class SocEstimationError(UseCaseError):
    """Bad training / estimation input (the API answers 400)."""
    code = "SOC_ESTIMATION_INPUT_REJECTED"


@dataclass
class RunConfig:
    selection: F.Selection
    test_fraction: float = 0.25
    label_source: str = "anchors"   # anchors | dense
    tune_ekf: bool = True
    ekf_params: dict = field(default_factory=dict)
    full_charge_reset: bool = True
    gbm_params: dict = field(default_factory=dict)
    seed: int = 42


def _clean(specs: list[dict], params: dict) -> dict:
    out = {}
    for s in specs:
        v = params.get(s["name"], s["default"])
        v = s["default"] if v in (None, "") else v
        v = int(v) if s["type"] == "int" else float(v)
        if not s["min"] <= v <= s["max"]:
            raise SocEstimationError(f"{s['label']} must be between {s['min']} and {s['max']}")
        out[s["name"]] = v
    return out


def clean_gbm(params: dict) -> dict:
    return _clean(GBM_PARAMS, params)


def clean_ekf(params: dict) -> dict:
    return _clean(EKF_PARAMS, params)


# ---------------------------------------------------------------- data


def dense_truth(engine: Engine, system_id: int, index: pd.DatetimeIndex) -> pd.Series:
    """The synthetic per-row truth of the sample file (staging), aligned to the series; NaN where there is none."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT s.ts, s.soc_true_pct FROM battery_raw.soc_estimation_data s
            JOIN battery_master.battery_system b ON b.system_name = s.system_name
            WHERE b.battery_system_id = :s AND s.soc_true_pct IS NOT NULL"""), conn, params={"s": system_id})
    if df.empty:
        return pd.Series(np.nan, index=index)
    ts = pd.to_datetime(df["ts"]).dt.tz_localize(F.TZ)  # wall-clock plant time in the file
    return pd.Series(df["soc_true_pct"].astype(float).to_numpy(), index=ts).groupby(level=0).last().reindex(index)


def feature_frame(df: pd.DataFrame, filt: pd.DataFrame, curve: F.OcvCurve, hysteresis: float) -> pd.DataFrame:
    """The model features of every row (base + EKF), causal."""
    X = pd.DataFrame(index=df.index)
    for c in ("soc_coulomb_pct", "measured_current_a", "current_sensor_offset_a", "pack_voltage_v", "cell_v_avg_v",
              "ocv_rested_v", "cell_temp_avg_c", "usable_capacity_ah", "c_rate", "coulombic_efficiency",
              "rest_duration_min"):
        X[c] = df[c].astype(float)
    X["i_corr_a"] = X["measured_current_a"] - X["current_sensor_offset_a"]
    X["at_rest"] = df["at_rest"].astype(float)
    X["ocv_soc"] = [E.ocv_soc(curve, v, d, t, hysteresis)
                    for v, d, t in zip(df["ocv_rested_v"], filt["direction"], df["cell_temp_avg_c"])]
    X["ocv_minus_coulomb"] = X["ocv_soc"] - X["soc_coulomb_pct"]
    X["min_since_recal"] = filt["min_since_recal"].to_numpy()
    # |Ah| moved since the last recalibration (drift grows with the integrated offset error and throughput)
    dt_h = df["gap_min"].to_numpy() / 60.0
    ah = np.abs(np.nan_to_num(X["i_corr_a"].to_numpy())) * dt_h
    seg = np.cumsum(filt["recalibrated"].to_numpy())
    X["ah_since_recal"] = pd.Series(ah).groupby(seg).cumsum().to_numpy()
    X["direction_code"] = filt["direction"].map({"CHARGE": 1.0, "DISCHARGE": -1.0}).fillna(0.0).to_numpy()
    X["ekf_soc"] = filt["ekf_soc"].to_numpy()
    X["ekf_sigma"] = filt["ekf_sigma"].to_numpy()
    X["ekf_bias"] = filt["ekf_bias"].to_numpy()
    X["ekf_gain"] = filt["ekf_gain"].to_numpy()
    X["ekf_minus_coulomb"] = X["ekf_soc"] - X["soc_coulomb_pct"]
    return X


def naive_ocv(df: pd.DataFrame, curve: F.OcvCurve) -> np.ndarray:
    v = np.array([curve.soc(o, "MEAN", t) if o == o else np.nan for o, t in zip(df["ocv_rested_v"], df["cell_temp_avg_c"])])
    return np.where(np.isnan(v), df["soc_coulomb_pct"].to_numpy(), v)


# ---------------------------------------------------------------- EKF tuning


def _label_rmse(est: np.ndarray, label: np.ndarray, mask: np.ndarray) -> float:
    m = mask & ~np.isnan(label) & ~np.isnan(est)
    return float(np.sqrt(np.mean((est[m] - label[m]) ** 2))) if m.any() else float("inf")


def tune_ekf(df: pd.DataFrame, curve: F.OcvCurve, base: dict, label: np.ndarray, mask: np.ndarray) -> tuple[dict, list[dict]]:
    """Grid over OCV noise x bias drift x hysteresis weight on the training rows; lowest label RMSE wins."""
    trials = []
    for r_mv, q_bias, hyst in itertools.product(*TUNE_GRID.values()):
        p = {**base, "r_mv": r_mv, "q_bias": q_bias, "hysteresis": hyst}
        res, _ = E.run(df, curve, E.EkfParams(**p))
        trials.append({"r_mv": r_mv, "q_bias": q_bias, "hysteresis": hyst,
                       "rmse": finite(_label_rmse(res["ekf_soc"].to_numpy(), label, mask))})
    best = min(trials, key=lambda t: t["rmse"] if t["rmse"] is not None else 1e9)
    return {**base, **{k: best[k] for k in TUNE_GRID}}, trials


def band_scale(filt: pd.DataFrame, label: np.ndarray, mask: np.ndarray) -> float:
    """Factor on the EKF SOC sd so that ~80 % of the training labels fall inside P10-P90 (never narrower than 1).
    The filter's own variance ignores model errors (OCV curve, capacity), so it is over-confident."""
    est, sig = filt["ekf_soc"].to_numpy(), filt["ekf_sigma"].to_numpy()
    m = mask & ~np.isnan(label)
    if m.sum() < 5:
        return 1.0
    r = np.abs(est[m] - label[m]) / np.maximum(sig[m], 1e-3)
    return float(min(50.0, max(1.0, np.quantile(r, 0.8) / E.Z90)))


# ---------------------------------------------------------------- quantile models


class QuantileModel:
    def __init__(self, features: list[str], params: dict, seed: int):
        self.features, self.params, self.seed = features, params, seed
        self.models: dict[float, Any] = {}

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "QuantileModel":
        for q in QUANTILES:
            self.models[q] = lgb.LGBMRegressor(objective="quantile", alpha=q, random_state=self.seed, verbose=-1,
                                               n_jobs=4, subsample_freq=1, **self.params).fit(X[self.features], y)
        return self

    def predict(self, X: pd.DataFrame) -> dict[float, np.ndarray]:
        return {q: m.predict(X[self.features]) for q, m in self.models.items()}

    def importance(self) -> dict[str, float]:
        b = self.models[0.5].booster_
        return shares(dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float))))


def corrected(base: np.ndarray, q: dict[float, np.ndarray], floor: Optional[tuple[np.ndarray, np.ndarray]] = None
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """base + the P10 / P50 / P90 corrections, clipped to [0, 100]. floor = (lower, upper) half-widths the band may not
    be narrower than (the EKF band, when the corrections were learnt from anchors only - they never saw the flat
    mid-SOC region, so their own band says nothing there)."""
    s = np.sort(np.vstack([base + q[0.1], base + q[0.5], base + q[0.9]]), axis=0)
    if floor is not None:
        s[0] = np.minimum(s[0], s[1] - floor[0])
        s[2] = np.maximum(s[2], s[1] + floor[1])
    return np.clip(s[0], 0, 100), np.clip(s[1], 0, 100), np.clip(s[2], 0, 100)


def ekf_floor(out: pd.DataFrame, label_source: str) -> Optional[tuple[np.ndarray, np.ndarray]]:
    if label_source == "dense":
        return None
    return (out["ekf"] - out["ekf_p10"]).to_numpy(), (out["ekf_p90"] - out["ekf"]).to_numpy()


# ---------------------------------------------------------------- training


@dataclass
class SystemData:
    system_id: int
    name: str
    chemistry: str
    df: pd.DataFrame
    curve: F.OcvCurve
    truth: pd.Series
    cut: int
    params: dict = field(default_factory=dict)
    tuning: list = field(default_factory=list)
    filt: Optional[pd.DataFrame] = None
    X: Optional[pd.DataFrame] = None
    band_scale: float = 1.0
    train_end_state: Optional[E.EkfState] = None
    end_state: Optional[E.EkfState] = None


def load_systems(engine: Engine, cfg: RunConfig, warnings: list[str]) -> list[SystemData]:
    names = {s["system_id"]: s for s in F.systems(engine)}
    out = []
    for sid in cfg.selection.system_ids:
        df = F.series(engine, sid, cfg.selection.date_from, cfg.selection.date_to)
        name = names.get(sid, {}).get("system_name") or f"system {sid}"
        if len(df) < 288:
            warnings.append(f"{name}: only {len(df)} rows with SOC-estimation inputs - left out")
            continue
        chem = F.chemistry(engine, sid)
        try:
            curve = F.ocv_curve(engine, chem)
        except UseCaseError as exc:
            warnings.append(f"{name}: {exc} - left out")
            continue
        truth = dense_truth(engine, sid, df.index)
        cut = int(round(len(df) * (1 - cfg.test_fraction)))
        gaps = int((df["gap_min"] > 7.5).sum())
        if gaps:
            warnings.append(f"{name}: {gaps} gaps in the 5-min series - the EKF widens its band across them")
        if df["ocv_rested_v"].notna().sum() == 0:
            warnings.append(f"{name}: no rested-OCV readings - the EKF can only coulomb-count")
        out.append(SystemData(sid, name, chem, df, curve, truth, cut))
    if not out:
        raise SocEstimationError("No battery system in the selection has SOC-estimation inputs "
                                 "(soc_coulomb_pct ... in system_telemetry)")
    return out


def labels(sd: SystemData, source: str, reset: bool) -> tuple[np.ndarray, np.ndarray]:
    """(label, usable for training) per row. Anchors: FULL_CHARGE anchors are left out when the EKF resets on them."""
    anchor = sd.df["soc_true_pct"].to_numpy(float)
    method = sd.df["reference_method"].to_numpy(object)
    if source == "dense":
        lab = sd.truth.to_numpy(float)
        return lab, ~np.isnan(lab)
    ok = ~np.isnan(anchor)
    if reset:
        ok &= method != "FULL_CHARGE"
    return anchor, ok


def train(engine: Engine, cfg: RunConfig) -> tuple[dict, dict, pd.DataFrame, list[str]]:
    """Returns (artifact, summary, stored points, warnings)."""
    started = time.perf_counter()
    warnings: list[str] = []
    gbm_params = clean_gbm(cfg.gbm_params)
    base = {**clean_ekf(cfg.ekf_params), "full_charge_reset": cfg.full_charge_reset}
    systems = load_systems(engine, cfg, warnings)

    tr_X, tr_y_c, tr_y_e = [], [], []
    dense_systems = 0
    for sd in systems:
        lab, ok = labels(sd, cfg.label_source, cfg.full_charge_reset)
        train_mask = np.arange(len(sd.df)) < sd.cut
        if cfg.label_source == "dense" and not ok.any():
            warnings.append(f"{sd.name}: no dense truth in battery_raw.soc_estimation_data - trained on its anchors")
            lab, ok = labels(sd, "anchors", cfg.full_charge_reset)
        elif cfg.label_source == "dense":
            dense_systems += 1
        if cfg.tune_ekf:
            tr = sd.df.iloc[:sd.cut]
            if (ok & train_mask).sum() >= 3:
                sd.params, sd.tuning = tune_ekf(tr, sd.curve, base, lab[:sd.cut], ok[:sd.cut])
            else:
                sd.params = dict(base)
                warnings.append(f"{sd.name}: fewer than 3 training labels - EKF not tuned, settings as entered")
        else:
            sd.params = dict(base)
        p = E.EkfParams(**sd.params)
        f_train, sd.train_end_state = E.run(sd.df.iloc[:sd.cut], sd.curve, p)
        f_test, sd.end_state = E.run(sd.df.iloc[sd.cut:], sd.curve, p, sd.train_end_state)
        sd.filt = pd.concat([f_train, f_test])
        sd.X = feature_frame(sd.df, sd.filt, sd.curve, p.hysteresis)
        m = ok & train_mask
        sd.band_scale = band_scale(f_train, lab[:sd.cut], m[:sd.cut])
        tr_X.append(sd.X[m])
        tr_y_c.append(lab[m] - sd.df["soc_coulomb_pct"].to_numpy()[m])
        tr_y_e.append(lab[m] - sd.filt["ekf_soc"].to_numpy()[m])

    # dense only if some system had the dense truth (its band then comes from the quantile heads alone)
    label_source = "dense" if dense_systems else "anchors"
    X_train = pd.concat(tr_X)
    n_train = len(X_train)
    if n_train < 10:
        raise SocEstimationError(f"Only {n_train} labelled training rows - widen the window or lower the test share")
    params = dict(gbm_params)
    if n_train < 5 * params["min_child_samples"]:
        params["min_child_samples"] = max(2, n_train // 8)
        warnings.append(f"Only {n_train} labelled training rows - LightGBM min rows per leaf lowered to "
                        f"{params['min_child_samples']}")
    gbm = QuantileModel(BASE_FEATURES, params, cfg.seed).fit(X_train, np.concatenate(tr_y_c))
    hyb = QuantileModel(BASE_FEATURES + EKF_FEATURES, params, cfg.seed).fit(X_train, np.concatenate(tr_y_e))

    # ---- estimates for every row
    frames = []
    for sd in systems:
        df, filt, X = sd.df, sd.filt, sd.X
        out = pd.DataFrame(index=df.index)
        out["system_id"] = sd.system_id
        out["is_test"] = np.arange(len(df)) >= sd.cut
        out["truth"] = sd.truth.to_numpy()
        out["anchor"] = df["soc_true_pct"].to_numpy()
        out["anchor_method"] = df["reference_method"].to_numpy()
        out["coulomb"] = df["soc_coulomb_pct"].to_numpy()
        out["ocv_lookup"] = naive_ocv(df, sd.curve)
        out["bms"] = df["soc_bms_pct"].to_numpy()
        out["ekf"] = filt["ekf_soc"].to_numpy()
        out["ekf_p10"], out["ekf_p90"] = E.band(filt["ekf_soc"].to_numpy(), filt["ekf_sigma"].to_numpy() * sd.band_scale)
        out["gbm_p10"], out["gbm"], out["gbm_p90"] = corrected(out["coulomb"].to_numpy(), gbm.predict(X))
        out["hybrid_p10"], out["hybrid"], out["hybrid_p90"] = corrected(out["ekf"].to_numpy(), hyb.predict(X),
                                                                        ekf_floor(out, label_source))
        out["ekf_bias"] = filt["ekf_bias"].to_numpy()
        out["ekf_gain"] = filt["ekf_gain"].to_numpy()
        out["recal_kind"] = filt["recal_kind"].to_numpy()
        out["at_rest"] = df["at_rest"].to_numpy()
        out["ocv_soc"] = X["ocv_soc"].to_numpy()
        frames.append(out)
    points = pd.concat(frames)
    test = points[points["is_test"]]

    metrics = {m: {s: score(test, m, s) for s in SCOPES} for m in METHODS}
    for m in METHODS:  # skill vs coulomb counting per scope
        for s in SCOPES:
            ref = metrics["coulomb"][s].get("rmse")
            v = metrics[m][s].get("rmse")
            metrics[m][s]["skill_pct"] = finite(100 * (1 - v / ref)) if ref and v is not None else None
    primary = "dense_flat" if metrics["coulomb"]["dense_flat"]["n"] else "anchors"
    candidates = [m for m in METHODS if metrics[m][primary]["rmse"] is not None]
    best = min(candidates, key=lambda m: metrics[m][primary]["rmse"]) if candidates else None

    by_band = {}
    if test["truth"].notna().any():
        bands = np.arange(0, 101, 10)
        t = test[test["truth"].notna()]
        b = np.clip(np.digitize(t["truth"], bands) - 1, 0, 9)
        for m in METHODS:
            e = (t[m] - t["truth"]).to_numpy()
            by_band[m] = [finite(np.sqrt(np.nanmean(e[b == i] ** 2))) if (b == i).any() else None for i in range(10)]
    daily = {}
    for m in METHODS:
        t = test[test["truth"].notna()]
        g = (t[m] - t["truth"]).abs().groupby(t.index.date).max()
        daily[m] = {str(k): finite(v) for k, v in g.items()}

    artifact = {
        "systems": {sd.system_id: {"name": sd.name, "chemistry": sd.chemistry, "curve": sd.curve, "params": sd.params,
                                   "band_scale": sd.band_scale,
                                   "train_end_state": sd.train_end_state.to_dict(), "end_state": sd.end_state.to_dict()}
                    for sd in systems},
        "gbm": gbm, "hybrid": hyb, "label_source": label_source,
    }
    summary = {
        "n_train_rows": int(n_train), "n_test_rows": int(len(test)),
        "n_test_anchors": int(test["anchor"].notna().sum()), "best_method": best,
        "label_source": label_source, "primary_scope": primary,
        "metrics": metrics,
        "results": {
            "ekf": {str(sd.system_id): {"name": sd.name, "params": sd.params, "tuning": sd.tuning,
                                        "band_scale": finite(sd.band_scale),
                                        "end_bias_a": finite(sd.end_state.bias), "end_gain": finite(sd.end_state.gain),
                                        "train_end_bias_a": finite(sd.train_end_state.bias),
                                        "train_end_gain": finite(sd.train_end_state.gain),
                                        "ocv_updates": int((sd.filt["recal_kind"] == "REST_OCV").sum()),
                                        "full_charge_resets": int((sd.filt["recal_kind"] == "FULL_CHARGE").sum()),
                                        "split": {"train_from": sd.df.index[0].isoformat(),
                                                  "test_from": sd.df.index[sd.cut].isoformat(),
                                                  "to": sd.df.index[-1].isoformat()},
                                        "dense_truth_rows": int(sd.truth.notna().sum())}
                    for sd in systems},
            "importance": {"gbm": gbm.importance(), "hybrid": hyb.importance()},
            "rmse_by_band": by_band, "band_edges": list(range(0, 101, 10)), "max_error_by_day": daily,
            "gbm_params_used": params,
        },
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return artifact, summary, points, warnings


def _scope_mask(t: pd.DataFrame, scope: str) -> tuple[pd.Series, str]:
    if scope.startswith("anchors"):
        m = t["anchor"].notna()
        if scope == "anchors_rest":
            m &= t["anchor_method"] == "REST_OCV"
        elif scope == "anchors_full":
            m &= t["anchor_method"] == "FULL_CHARGE"
        return m, "anchor"
    m = t["truth"].notna()
    if scope == "dense_flat":
        m &= t["truth"].between(*FLAT)
    elif scope == "dense_active":
        m &= ~t["at_rest"].astype(bool)
    return m, "truth"


def score(t: pd.DataFrame, method: str, scope: str) -> dict:
    m, col = _scope_mask(t, scope)
    m &= t[method].notna()
    if not m.any():
        return {"n": 0}
    y, p = t.loc[m, col].to_numpy(float), t.loc[m, method].to_numpy(float)
    e = p - y
    out = {"n": int(m.sum()), "rmse": finite(np.sqrt(np.mean(e ** 2))), "mae": finite(np.mean(np.abs(e))),
           "bias": finite(np.mean(e)), "max_error": finite(np.max(np.abs(e))),
           "p95_abs": finite(np.quantile(np.abs(e), 0.95))}
    if method in BANDED:
        lo, hi = t.loc[m, f"{method}_p10"].to_numpy(float), t.loc[m, f"{method}_p90"].to_numpy(float)
        out["coverage_pct"] = finite(100 * np.mean((y >= lo - 1e-9) & (y <= hi + 1e-9)))
        out["width"] = finite(np.mean(hi - lo))
    return out


# ---------------------------------------------------------------- live / replay estimation


def estimate_rows(art: dict, system_id: int, df: pd.DataFrame, state: Optional[E.EkfState]) -> tuple[pd.DataFrame, E.EkfState]:
    """EKF + corrections over the rows of df from `state`; the per-row output frame and the state after."""
    s = art["systems"][system_id]
    p = E.EkfParams(**s["params"])
    filt, end = E.run(df, s["curve"], p, state)
    X = feature_frame(df, filt, s["curve"], p.hysteresis)
    out = pd.DataFrame(index=df.index)
    out["coulomb"] = df["soc_coulomb_pct"].to_numpy()
    out["bms"] = df["soc_bms_pct"].to_numpy()
    out["anchor"] = df["soc_true_pct"].to_numpy()
    out["anchor_method"] = df["reference_method"].to_numpy()
    out["ocv_soc"] = X["ocv_soc"].to_numpy()
    out["ekf"] = filt["ekf_soc"].to_numpy()
    out["ekf_p10"], out["ekf_p90"] = E.band(filt["ekf_soc"].to_numpy(), filt["ekf_sigma"].to_numpy() * s.get("band_scale", 1.0))
    out["ekf_sigma"] = filt["ekf_sigma"].to_numpy() * s.get("band_scale", 1.0)
    out["hybrid_p10"], out["hybrid"], out["hybrid_p90"] = corrected(out["ekf"].to_numpy(), art["hybrid"].predict(X),
                                                                    ekf_floor(out, art["label_source"]))
    out["gbm_p10"], out["gbm"], out["gbm_p90"] = corrected(out["coulomb"].to_numpy(), art["gbm"].predict(X))
    for c in ("ekf_bias", "ekf_gain", "recalibrated", "recal_kind", "direction", "min_since_recal", "innovation_mv"):
        out[c] = filt[c].to_numpy()
    out["at_rest"] = df["at_rest"].to_numpy()
    out["ocv_rested_v"] = df["ocv_rested_v"].to_numpy()
    return out, end


def seed_state(art: dict, system_id: int, soc: float) -> E.EkfState:
    """A fresh filter at `soc` carrying the bias / gain learned up to the end of the training period."""
    s = art["systems"][system_id]
    st = s["train_end_state"]
    return E.EkfState.initial(soc, E.EkfParams(**s["params"]), st["bias"], st["gain"])
