"""Temperature forecasting: one run = per target and asset an RC model, per target LightGBM quantile models on its
residual (direct multi-horizon: the horizon is a feature), the backtest and the scores.

Families: battery thermal (cell max, coolant return, enclosure - asset: battery system / HVAC unit) and power
electronics (IGBT - asset: PCS). Each target has its own models; the features are shared within a family.

Methods (P10 / P50 / P90 at each horizon):
  persistence   T(t + h) = T(t); band from the training errors per horizon
  seasonal      T(t + h - 24 h) (same time yesterday); band from the training errors
  rc            the grey-box RC model on the planned load and the ambient forecast; band from its training errors
  hybrid        rc + LightGBM quantile models of its residual

Planned load: the dispatch schedule (dispatch_event; the typical-day setpoint where no command covers a step) or the
typical day alone. Ambient forecast (no weather feed yet): ambient now + the typical daily swing between now and t + h.

Scores per target, horizon and method on the test period (time split per system, no leakage): MAE, RMSE, pinball
over P10 / P50 / P90, P10-P90 coverage and - the operational payoff - threshold exceedance: an event is a reading at
t + h at or above the threshold while T(t) was below it; recall / precision of alerting when P50 (or the more cautious
P90) reaches the threshold.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from core.metrics import finite, shares
from usecases.soc_forecast.features import schedule, schedule_grid  # the dispatch schedule (dispatch_event)
from usecases.thermal_forecast import features as F
from usecases.thermal_forecast.physics import RCModel

METHODS = ["persistence", "seasonal", "rc", "hybrid"]
QUANTILES = (0.1, 0.5, 0.9)
ROW_FEATURES = ["h_min", "T0", "dT_5", "dT_15", "roll_1h", "stale_min", "ambient0", "amb_fc", "ref0", "c_rate_abs",
                "load_abs", "s_abs", "cooling_mode", "compressor_pct", "flow_lpm", "hvac_kw", "soc0", "plan_h",
                "plan_mean", "plan_max", "plan_cov", "ss0", "ss_h", "rc", "rc_delta", "hour_o", "hour_t", "asset_code"]
GBM_PARAMS = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 5000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 31, "min": 2, "max": 512, "step": 1},
    {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 100, "min": 5, "max": 20000, "step": 5},
    {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
]
STALE_LIMIT_MIN = 15


class ThermalForecastError(Exception):
    """Bad training / forecast input (the API answers 400)."""


@dataclass
class RunConfig:
    selection: F.Selection
    targets: list[str]
    horizons_min: list[int] = field(default_factory=lambda: [5, 15, 30, 60])
    thresholds: dict[str, float] = field(default_factory=dict)
    plan_source: str = "scheduled"
    test_fraction: float = 0.2
    train_origin_step: int = 2  # every n-th 5-min origin in training
    store_origin_step: int = 3  # every n-th test origin stored for the viewer
    gbm_params: dict = field(default_factory=dict)
    seed: int = 42


@dataclass
class System:
    system_id: int
    info: dict
    df: pd.DataFrame
    drv: pd.DataFrame
    ratings: tuple[float, float, float]  # rated kW, rated kVA, kWh per unit C-rate
    amb_profile: np.ndarray
    typical_plan: np.ndarray
    sched_sp: np.ndarray
    cut: int
    rc: dict[str, RCModel] = field(default_factory=dict)


def clean_gbm(params: dict) -> dict:
    out = {}
    for s in GBM_PARAMS:
        v = params.get(s["name"], s["default"])
        v = s["default"] if v in (None, "") else v
        v = int(v) if s["type"] == "int" else float(v)
        if not s["min"] <= v <= s["max"]:
            raise ThermalForecastError(f"{s['label']} must be between {s['min']} and {s['max']}")
        out[s["name"]] = v
    return out


def ratings(info: dict, df: pd.DataFrame) -> tuple[float, float, float]:
    kw = info.get("pcs_rated_kw") or (info.get("rated_power_mw") or 1) * 1000
    kva = info.get("pcs_rated_kva") or kw
    # kWh per unit C-rate from the data (|P| / |C-rate| while active), else the rated energy
    act = (df["c_rate"].abs() > 0.05) & df["power_kw"].notna()
    kwh = float((df.loc[act, "power_kw"].abs() / df.loc[act, "c_rate"].abs()).median()) if act.sum() > 20 else \
        (info.get("rated_energy_mwh") or 1) * 1000
    return float(kw), float(kva), kwh


def load_systems(engine: Engine, cfg: RunConfig, warnings: list[str]) -> list[System]:
    infos = {s["battery_system_id"]: s for s in F.systems(engine)}
    out = []
    for sid in cfg.selection.system_ids:
        info = infos.get(sid)
        if not info:
            warnings.append(f"Battery system {sid} not found")
            continue
        df = F.series(engine, sid, cfg.selection.date_from, cfg.selection.date_to)
        if len(df) < 2 * F.STEPS_PER_DAY:
            warnings.append(f"System {sid}: only {len(df)} readings - left out")
            continue
        rk = ratings(info, df)
        cut = int(round(len(df) * (1 - cfg.test_fraction)))
        train = df.iloc[:cut]
        sched = schedule(engine, int(info["ems_id"])) if info.get("ems_id") else pd.DataFrame()
        sched_sp, _ = schedule_grid(sched, df.index)
        out.append(System(sid, info, df, F.derived(df, *rk), rk, F.daily_profile(train["ambient_temp_c"]),
                          F.daily_profile(train["p_setpoint_kw"].fillna(0)), sched_sp, cut))
    if not out:
        raise ThermalForecastError("No battery system with enough thermal history in the selection")
    return out


# ---------------------------------------------------------------- rows


def plan_matrix(s: System, origins: np.ndarray, max_steps: int, source: str, future_ts=None, sched_future=None):
    """Planned setpoint (kW) for steps 0..max_steps-1 after each origin, and whether the schedule covers it."""
    if future_ts is None:
        idx = np.minimum(origins[:, None] + np.arange(max_steps)[None, :], len(s.df) - 1)
        slots = F.slot_of(s.df.index)[idx]
        sched = s.sched_sp[idx]
    else:
        slots = F.slot_of(future_ts)[None, :]
        sched = sched_future[None, :]
    typical = s.typical_plan[slots]
    now = s.df["p_setpoint_kw"].to_numpy()[np.minimum(origins, len(s.df) - 1)]
    plan = typical.copy() if source == "typical" else np.where(np.isnan(sched), typical, sched)
    plan[:, 0] = np.where(np.isnan(now), plan[:, 0], now)  # the current command is known
    cover = np.zeros_like(plan) if source == "typical" else (~np.isnan(sched)).astype(float)
    return plan, cover


def rows_for(s: System, target: str, origins: np.ndarray, horizons: list[int], source: str, with_target: bool = True,
             future=None) -> pd.DataFrame:
    """One row per origin and horizon with the features, the RC forecast and (training / backtest) the actual."""
    spec = F.TARGETS[target]
    df, drv = s.df, s.drv
    T = df[target].to_numpy()
    steps = np.array([h // F.STEP_MIN for h in horizons])
    max_steps = int(steps.max())
    plan, cover = plan_matrix(s, origins, max_steps, source, *(future or (None, None)))
    kw, kva, kwh = s.ratings
    n, m = len(origins), len(steps)
    o = np.repeat(origins, m)
    k = np.tile(steps, n)
    r = np.repeat(np.arange(n), m)
    ts0 = df.index[o]
    t_target = ts0 + pd.to_timedelta(k * F.STEP_MIN, unit="min")
    amb0 = df["ambient_temp_c"].to_numpy()[o]
    amb_fc = amb0 + s.amb_profile[F.slot_of(t_target)] - s.amb_profile[F.slot_of(ts0)]
    ref0 = df[spec["ref"]].to_numpy()[o]
    # the load leading into t + h, and its mean / max over (t, t + h]
    p_h = plan[r, k - 1]
    csum = np.cumsum(np.abs(plan), axis=1)
    p_mean = csum[r, k - 1] / k
    p_max = np.maximum.accumulate(np.abs(plan), axis=1)[r, k - 1]
    qh = F.plan_drivers(p_h, kw, kva, kwh)
    q0 = {d: drv[d].to_numpy()[o] for d in spec["drivers"]}
    rc = s.rc[target]
    ss0 = rc.steady(ref0, amb0, q0)
    ss_h = rc.steady(ref0, amb_fc, qh)  # coolant / inlet reference held at its current value
    rc_pred = rc.predict(T[o], ss0, ss_h, k)
    cool = pd.Categorical(df["cooling_mode"].to_numpy()[o], categories=F.COOLING_MODES).codes.astype(float)
    roll_col = F.ROLLING.get(target)
    out = pd.DataFrame({
        "h_min": k * F.STEP_MIN, "T0": T[o], "dT_5": T[o] - T[o - 1], "dT_15": T[o] - T[o - 3],
        "roll_1h": df[roll_col].to_numpy()[o] if roll_col else np.nan,
        "stale_min": df[f"stale_min_{target}"].to_numpy()[o],
        "ambient0": amb0, "amb_fc": amb_fc, "ref0": ref0,
        "c_rate_abs": drv["c_rate_abs"].to_numpy()[o], "load_abs": drv["load_abs"].to_numpy()[o],
        "s_abs": drv["s_abs"].to_numpy()[o], "cooling_mode": cool,
        "compressor_pct": df["compressor_speed_pct"].to_numpy()[o], "flow_lpm": df["coolant_flow_lpm"].to_numpy()[o],
        "hvac_kw": df["hvac_power_kw"].to_numpy()[o], "soc0": df["soc_pct"].to_numpy()[o],
        "plan_h": np.abs(p_h) / kw, "plan_mean": p_mean / kw, "plan_max": p_max / kw,
        "plan_cov": cover[r, :].mean(axis=1) if cover.size else 0.0,
        "ss0": ss0, "ss_h": ss_h, "rc": rc_pred, "rc_delta": rc_pred - T[o],
        "hour_o": ts0.hour.to_numpy().astype(float), "hour_t": t_target.hour.to_numpy().astype(float),
        "asset_code": float(s.system_id),
    })
    out["pos"], out["step"], out["system_id"] = o, k, s.system_id
    out["origin_ts"], out["target_ts"] = ts0, t_target
    if with_target:
        out["actual"] = T[o + k]
        lag = o + k - F.STEPS_PER_DAY
        out["seasonal"] = np.where(lag >= 0, T[np.maximum(lag, 0)], np.nan)
        out["ok"] = df[f"ok_{target}"].to_numpy()[o] & df[f"ok_{target}"].to_numpy()[o + k]
    return out


def valid_origins(s: System, target: str, lo: int, hi: int, max_steps: int, step: int) -> np.ndarray:
    ok = s.df[f"ok_{target}"].to_numpy()
    o = np.arange(max(lo, 3), min(hi, len(ok) - max_steps), step)
    return o[ok[o] & ok[o - 1] & ok[o - 3]]


# ---------------------------------------------------------------- quantile models


class Residual:
    def __init__(self, params: dict, seed: int):
        self.params, self.seed, self.models = params, seed, {}

    def fit(self, rows: pd.DataFrame) -> "Residual":
        X, y = rows[ROW_FEATURES], (rows["actual"] - rows["rc"]).to_numpy()
        for q in QUANTILES:
            self.models[q] = lgb.LGBMRegressor(objective="quantile", alpha=q, random_state=self.seed, verbose=-1,
                                               n_jobs=4, subsample_freq=1, **self.params).fit(X, y)
        return self

    def predict(self, rows: pd.DataFrame) -> dict[float, np.ndarray]:
        return {q: m.predict(rows[ROW_FEATURES]) for q, m in self.models.items()}

    def importance(self) -> dict[str, float]:
        b = self.models[0.5].booster_
        return shares(dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float))))


def error_bands(rows: pd.DataFrame, pred_col: str) -> dict[int, tuple[float, float]]:
    out = {}
    for h, g in rows.groupby("h_min"):
        e = (g["actual"] - g[pred_col]).dropna().to_numpy()
        out[int(h)] = (float(np.quantile(e, 0.1)), float(np.quantile(e, 0.9))) if len(e) > 10 else (0.0, 0.0)
    return out


def with_band(p50: np.ndarray, h: np.ndarray, bands: dict) -> tuple[np.ndarray, np.ndarray]:
    lo = np.array([bands.get(int(x), (0.0, 0.0))[0] for x in h])
    hi = np.array([bands.get(int(x), (0.0, 0.0))[1] for x in h])
    return p50 + lo, p50 + hi


# ---------------------------------------------------------------- training


def train(engine: Engine, cfg: RunConfig) -> tuple[dict, dict, pd.DataFrame, list[str]]:
    started = time.perf_counter()
    warnings: list[str] = []
    unknown = [t for t in cfg.targets if t not in F.TARGETS]
    if unknown:
        raise ThermalForecastError(f"Unknown target(s): {', '.join(unknown)}")
    if not cfg.horizons_min or any(h % F.STEP_MIN or h <= 0 or h > 360 for h in cfg.horizons_min):
        raise ThermalForecastError("Horizons must be multiples of 5 minutes up to 360")
    horizons = sorted(set(cfg.horizons_min))
    gbm = clean_gbm(cfg.gbm_params)
    systems = load_systems(engine, cfg, warnings)
    max_steps = max(horizons) // F.STEP_MIN
    catalog = F.thresholds(engine)
    thr = {t: float(cfg.thresholds.get(t, F.TARGETS[t]["threshold"])) for t in cfg.targets}

    # RC models per target and asset, on the training period
    for s in systems:
        tr = slice(0, s.cut)
        for t in cfg.targets:
            spec = F.TARGETS[t]
            q = {d: s.drv[d].to_numpy()[tr] for d in spec["drivers"]}
            s.rc[t] = RCModel.fit(s.df[t].to_numpy()[tr], s.df[spec["ref"]].to_numpy()[tr],
                                  s.df["ambient_temp_c"].to_numpy()[tr], q, spec["drivers"])

    models, bands, importance, metrics, points, n_train, n_test = {}, {}, {}, {}, [], 0, 0
    for t in cfg.targets:
        tr_parts, te_parts = [], []
        for s in systems:
            tr_o = valid_origins(s, t, 0, s.cut - max_steps, max_steps, cfg.train_origin_step)
            te_o = valid_origins(s, t, s.cut, len(s.df), max_steps, 1)
            if len(tr_o) < 100 or not len(te_o):
                warnings.append(f"{F.TARGETS[t]['label']}: system {s.system_id} has too few gap-free origins - left out")
                continue
            tr_parts.append(rows_for(s, t, tr_o, horizons, cfg.plan_source))
            te_parts.append(rows_for(s, t, te_o, horizons, cfg.plan_source))
        if not tr_parts:
            warnings.append(f"{F.TARGETS[t]['label']}: no system with enough data - target skipped")
            continue
        tr = pd.concat(tr_parts, ignore_index=True)
        tr = tr[tr["ok"]]
        te = pd.concat(te_parts, ignore_index=True)
        te = te[te["ok"]].reset_index(drop=True)
        n_train += len(tr)
        n_test += len(te)
        tr["persistence"] = tr["T0"]
        b = {"persistence": error_bands(tr, "persistence"), "seasonal": error_bands(tr.dropna(subset=["seasonal"]), "seasonal"),
             "rc": error_bands(tr, "rc")}
        model = Residual(gbm, cfg.seed).fit(tr)
        models[t], bands[t], importance[t] = model, b, model.importance()

        h = te["h_min"].to_numpy()
        preds = {}
        for mth, p50 in (("persistence", te["T0"].to_numpy()), ("seasonal", te["seasonal"].to_numpy()), ("rc", te["rc"].to_numpy())):
            lo, hi = with_band(p50, h, b[mth])
            preds[mth] = (lo, p50, hi)
        q = model.predict(te)
        preds["hybrid"] = tuple(np.sort(np.vstack([te["rc"] + q[0.1], te["rc"] + q[0.5], te["rc"] + q[0.9]]), axis=0))
        metrics[t] = {}
        for hz in horizons:
            mh = h == hz
            metrics[t][str(hz)] = {mth: score(te["actual"].to_numpy()[mh], te["T0"].to_numpy()[mh],
                                              *(arr[mh] for arr in preds[mth]), thr[t]) for mth in METHODS}
        keep = (te["pos"] % max(1, cfg.store_origin_step)) == 0
        for mth in METHODS:
            lo, p50, hi = preds[mth]
            points.append(pd.DataFrame({
                "target": t, "system_id": te["system_id"][keep], "origin_ts": te["origin_ts"][keep],
                "horizon_min": te["h_min"][keep], "method": mth, "p10": lo[keep], "p50": p50[keep], "p90": hi[keep],
                "actual": te["actual"][keep], "now_c": te["T0"][keep]}))

    if not models:
        raise ThermalForecastError("No target could be trained")
    artifact = {
        "targets": list(models), "horizons": horizons, "plan_source": cfg.plan_source, "thresholds": thr,
        "models": models, "bands": bands,
        "systems": {s.system_id: {"info": s.info, "ratings": s.ratings, "amb_profile": s.amb_profile,
                                  "typical_plan": s.typical_plan, "rc": s.rc} for s in systems},
    }
    summary = {
        "n_train_rows": int(n_train), "n_test_rows": int(n_test), "metrics": metrics,
        "results": {
            "importance": importance, "thresholds": thr, "catalog_thresholds": catalog,
            "rc": {str(s.system_id): {t: m.to_dict() for t, m in s.rc.items()} for s in systems},
            "split": {str(s.system_id): {"test_from": s.df.index[s.cut].isoformat(), "to": s.df.index[-1].isoformat()}
                      for s in systems},
            "summary": headline(metrics, horizons),
        },
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return artifact, summary, pd.concat(points, ignore_index=True), warnings


def score(actual, now, p10, p50, p90, thr) -> dict:
    ok = np.isfinite(actual) & np.isfinite(p50)
    a, n0, lo, md, hi = actual[ok], now[ok], p10[ok], p50[ok], p90[ok]
    if not len(a):
        return {"n": 0}
    err = a - md
    pin = np.mean([np.mean(np.maximum(q * (a - p), (q - 1) * (a - p))) for q, p in zip(QUANTILES, (lo, md, hi))])
    below = n0 < thr
    event = below & (a >= thr)
    out = {"n": int(len(a)), "mae": finite(np.mean(np.abs(err))), "rmse": finite(np.sqrt(np.mean(err ** 2))),
           "pinball": finite(pin), "coverage_pct": finite(100 * np.mean((a >= lo) & (a <= hi))),
           "threshold_c": thr, "events": int(event.sum())}
    for name, p in (("p50", md), ("p90", hi)):
        alert = below & (p >= thr)
        out[f"recall_{name}"] = finite(np.sum(alert & event) / event.sum()) if event.sum() else None
        out[f"precision_{name}"] = finite(np.sum(alert & event) / alert.sum()) if alert.sum() else None
    return out


def headline(metrics: dict, horizons: list[int]) -> dict:
    """Per target: the longest horizon's MAE per method and the hybrid's exceedance recall."""
    out = {}
    for t, by_h in metrics.items():
        h = str(max(horizons))
        out[t] = {"horizon_min": int(h), "mae": {m: by_h[h][m].get("mae") for m in METHODS},
                  "events": by_h[h]["hybrid"].get("events"), "recall_p90": by_h[h]["hybrid"].get("recall_p90"),
                  "recall_p50": by_h[h]["hybrid"].get("recall_p50")}
    return out


# ---------------------------------------------------------------- serving


def predict_live(engine: Engine, art: dict, system_id: int, plan_source: Optional[str] = None,
                 targets: Optional[list[str]] = None, horizons: Optional[list[int]] = None, history_hours: int = 6,
                 max_data_age_min: Optional[float] = None) -> dict:
    """{target, asset_id, horizon_min, pred_c, p10_c, p90_c} from the newest reading of a system (online fetch from
    v_thermal_features); NULL predictions with flags when a target's inputs are stale or missing, or - with
    max_data_age_min - when the newest reading is older than that (otherwise it forecasts as of the newest reading)."""
    reg = art["systems"].get(system_id)
    if reg is None:
        raise ThermalForecastError(f"Battery system {system_id} is not part of this model")
    targets = [t for t in (targets or art["targets"]) if t in art["targets"]]
    horizons = sorted(set(horizons or art["horizons"]))
    if any(h % F.STEP_MIN or h <= 0 or h > max(art["horizons"]) * 2 for h in horizons):
        raise ThermalForecastError("Horizons must be multiples of 5 minutes")
    source = plan_source or art["plan_source"]
    df = F.series(engine, system_id, (pd.Timestamp.now(tz=F.TZ) - pd.Timedelta(days=400)).date())
    if df.empty:
        raise ThermalForecastError(f"System {system_id} has no thermal readings")
    df = df.iloc[-(history_hours * 12 + 6):]
    info = reg["info"]
    s = System(system_id, info, df, F.derived(df, *reg["ratings"]), reg["ratings"], reg["amb_profile"],
               reg["typical_plan"], np.full(len(df), np.nan), len(df), reg["rc"])
    origin = len(df) - 1
    origin_ts = df.index[origin]
    max_steps = max(horizons) // F.STEP_MIN
    future_ts = pd.date_range(origin_ts, periods=max_steps, freq=f"{F.STEP_MIN}min", tz=F.TZ)
    sched = schedule(engine, int(info["ems_id"])) if info.get("ems_id") else pd.DataFrame()
    sched_future, _ = schedule_grid(sched, future_ts)
    forecasts, flags = [], {}
    data_age = (pd.Timestamp.now(tz=F.TZ) - origin_ts).total_seconds() / 60
    too_old = max_data_age_min is not None and data_age > max_data_age_min
    for t in targets:
        spec = F.TARGETS[t]
        stale = data_age if too_old else float(df[f"stale_min_{t}"].iloc[-1])
        missing = [c for c in [t, spec["ref"], "ambient_temp_c"] if not np.isfinite(df[c].iloc[-1])]
        flags[t] = {"stale_min": stale, "stale": too_old or stale > STALE_LIMIT_MIN, "missing_inputs": missing}
        asset_id = int(df[spec["asset"]].iloc[-1]) if np.isfinite(df[spec["asset"]].iloc[-1]) else None
        if flags[t]["stale"] or missing:
            forecasts += [{"target": t, "asset_type": spec["asset_type"], "asset_id": asset_id, "horizon_min": h,
                           "pred_c": None, "p10_c": None, "p90_c": None, "flag": "stale" if flags[t]["stale"] else "missing_inputs"}
                          for h in horizons]
            continue
        rows = rows_for(s, t, np.array([origin]), horizons, source, with_target=False, future=(future_ts, sched_future))
        q = art["models"][t].predict(rows)
        rc = rows["rc"].to_numpy()
        trio = np.sort(np.vstack([rc + q[0.1], rc + q[0.5], rc + q[0.9]]), axis=0)
        for i, h in enumerate(horizons):
            forecasts.append({"target": t, "asset_type": spec["asset_type"], "asset_id": asset_id, "horizon_min": h,
                              "pred_c": finite(trio[1][i]), "p10_c": finite(trio[0][i]), "p90_c": finite(trio[2][i]),
                              "rc_c": finite(rc[i]), "now_c": finite(rows["T0"].iloc[i]),
                              "threshold_c": art["thresholds"].get(t), "flag": None})
    hist = df.iloc[-history_hours * 12:]
    return {
        "system_id": system_id, "origin_ts": origin_ts.isoformat(), "plan_source": source,
        "data_age_min": finite((pd.Timestamp.now(tz=F.TZ) - origin_ts).total_seconds() / 60),
        "forecasts": forecasts, "flags": flags,
        "history": {t: [{"ts": ts.isoformat(), "v": finite(v) if v == v else None} for ts, v in hist[t].items()] for t in targets},
        "ambient": [{"ts": ts.isoformat(), "v": finite(v) if v == v else None} for ts, v in hist["ambient_temp_c"].items()],
        "plan_kw": [finite(v) for v in plan_matrix(s, np.array([origin]), max_steps, source, future_ts, sched_future)[0][0]],
        "plan_times": [ts.isoformat() for ts in future_ts],
    }


VECTOR_REQUIRED = ["ambient_temp_c", "power_kw"]


def predict_vector(art: dict, system_id: int, target: str, inputs: dict, horizons: Optional[list[int]] = None,
                   plan_kw: Optional[list[float]] = None, origin_ts: Optional[str] = None) -> dict:
    """Stateless predict(features): the forecast from a feature vector alone (no database). `inputs` holds the
    current readings - the target now (and optionally 5 / 15 min ago and its 1 h max), its reference temperature,
    ambient, power, C-rate, apparent power, cooling mode, compressor, coolant flow, HVAC power, SOC, setpoint and
    stale_min; `plan_kw` the planned setpoint per 5-min step ahead (else the typical day). Missing required inputs or
    stale_min above the limit give NULL predictions with a flag."""
    reg = art["systems"].get(system_id)
    if reg is None or target not in art["targets"]:
        raise ThermalForecastError("Unknown system or target for this model")
    spec = F.TARGETS[target]
    horizons = sorted(set(horizons or art["horizons"]))
    required = [target, spec["ref"], *VECTOR_REQUIRED]
    missing = [k for k in required if inputs.get(k) is None]
    stale = float(inputs.get("stale_min") or 0.0)
    base = {"target": target, "asset_type": spec["asset_type"], "asset_id": inputs.get("asset_id")}
    if missing or stale > STALE_LIMIT_MIN:
        flag = "missing_inputs" if missing else "stale"
        return {"forecasts": [{**base, "horizon_min": h, "pred_c": None, "p10_c": None, "p90_c": None, "flag": flag}
                              for h in horizons], "missing_inputs": missing, "stale_min": stale}
    t0 = pd.Timestamp(origin_ts or pd.Timestamp.now(tz=F.TZ)).tz_convert(F.TZ).floor(f"{F.STEP_MIN}min")
    idx = pd.date_range(t0 - pd.Timedelta(minutes=15), t0, freq=f"{F.STEP_MIN}min", tz=F.TZ)
    df = pd.DataFrame(index=idx)
    for c in F.NUMERIC:
        df[c] = float(inputs[c]) if inputs.get(c) is not None else np.nan
    now = float(inputs[target])
    hist = [inputs.get(f"{target}_15m_ago", now), np.nan, inputs.get(f"{target}_5m_ago", now), now]
    df[target] = pd.Series(hist, index=idx, dtype=float).interpolate()
    roll = F.ROLLING.get(target)
    if roll:
        df[roll] = float(inputs.get("roll_1h_max", max(v for v in hist if v == v)))
    df["cooling_mode"] = inputs.get("cooling_mode")
    for t in F.TARGETS:
        df[f"ok_{t}"] = True
        df[f"stale_min_{t}"] = stale
    rk = reg["ratings"]
    s = System(system_id, reg["info"], df, F.derived(df, *rk), rk, reg["amb_profile"], reg["typical_plan"],
               np.full(len(df), np.nan), len(df), reg["rc"])
    max_steps = max(horizons) // F.STEP_MIN
    future = pd.date_range(t0, periods=max_steps, freq=f"{F.STEP_MIN}min", tz=F.TZ)
    sched = np.full(max_steps, np.nan)
    if plan_kw:
        sched[:min(max_steps, len(plan_kw))] = np.asarray(plan_kw[:max_steps], float)
    rows = rows_for(s, target, np.array([len(df) - 1]), horizons, "scheduled" if plan_kw else "typical",
                    with_target=False, future=(future, sched))
    q = art["models"][target].predict(rows)
    rc = rows["rc"].to_numpy()
    trio = np.sort(np.vstack([rc + q[0.1], rc + q[0.5], rc + q[0.9]]), axis=0)
    return {"forecasts": [{**base, "horizon_min": h, "pred_c": finite(trio[1][i]), "p10_c": finite(trio[0][i]),
                           "p90_c": finite(trio[2][i]), "rc_c": finite(rc[i]), "threshold_c": art["thresholds"].get(target),
                           "flag": None} for i, h in enumerate(horizons)], "missing_inputs": [], "stale_min": stale}
