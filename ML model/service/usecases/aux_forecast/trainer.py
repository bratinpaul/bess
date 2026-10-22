"""Auxiliary / HVAC energy forecasting: one run = per site a grey-box model, pooled LightGBM quantile models on its
residual (direct multi-horizon: the horizon is a feature), the backtest and the scores.

Methods (P10 / P50 / P90 at each 5-min step, 5 min .. 24 h ahead):
  persistence   aux(t + h) = aux(t); band from the training errors per horizon bucket
  seasonal      aux(t + h - 24 h) - same time yesterday, the baseline to beat; band from the training errors
  greybox       controls + (heat load + envelope + solar) / COP(ambient) on the planned dispatch and the ambient forecast
  hybrid        greybox + LightGBM quantile models of its residual

Planned dispatch: the dispatch schedule (dispatch_event; the typical-day setpoint where no command covers a step) or the
typical day alone. Ambient at the target: the newest weather_forecast run of the site's station (offset to the HVAC
sensor), else ambient now + the typical daily swing; 'actual' gives the oracle bound.

Training rows: origins every `train_origin_step` readings, each with `steps_per_origin` random horizon steps. Test rows:
origins on a clock grid (every 30 min, ending at :25 / :55) with every step; time split per site, no leakage.
Scores per site and horizon bucket: MAE, RMSE, bias, pinball over P10 / P50 / P90 and P10-P90 coverage - plus the
daily aux energy (kWh) from the forecasts issued at 23:55 for the next 24 h, which is what hits the economics.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from core.metrics import finite, shares
from usecases.aux_forecast import features as F
from usecases.aux_forecast.physics import AuxGreyBox
from usecases.soc_forecast.features import schedule, schedule_grid  # the dispatch schedule (dispatch_event)

METHODS = ["persistence", "seasonal", "greybox", "hybrid"]
QUANTILES = (0.1, 0.5, 0.9)
BUCKETS = [(0, 60, "0-1 h"), (60, 120, "1-2 h"), (120, 240, "2-4 h"), (240, 480, "4-8 h"), (480, 720, "8-12 h"),
           (720, 1440, "12-24 h")]
REPORT_HORIZONS = [60, 120, 240, 360, 720, 1440]
ROW_FEATURES = ["h_min", "aux0", "aux_d15", "aux_1h", "aux_max_1h", "aux_3h", "hvac0", "hvac_1h", "gb0", "gb_res0",
                "gb_res_1h", "seasonal", "seasonal_delta", "amb0", "amb_fc", "amb_delta", "amb_src", "ghi_fc",
                "plan_h", "plan_15", "plan_mean", "plan_cov", "absp0", "c_rate0", "kva0", "cooling_mode", "cop0",
                "compressor0", "setpoint_c", "cell_max0", "return0", "enclosure0", "humidity0", "heat0", "gb",
                "gb_delta", "hour_o", "hour_t", "dow_t", "site_code"]
GBM_PARAMS = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 5000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 31, "min": 2, "max": 512, "step": 1},
    {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 100, "min": 5, "max": 20000, "step": 5},
    {"name": "subsample", "label": "Row subsample", "type": "float", "default": 0.8, "min": 0.1, "max": 1, "step": 0.05},
    {"name": "colsample_bytree", "label": "Feature subsample", "type": "float", "default": 0.9, "min": 0.1, "max": 1, "step": 0.05},
]
STALE_LIMIT_MIN = 15
ORIGIN_GRID = 6  # test origins every 30 min, on readings ending at :25 / :55 (so 23:55 issues the next day)


class AuxForecastError(Exception):
    """Bad training / forecast input (the API answers 400)."""


@dataclass
class RunConfig:
    selection: F.Selection
    horizon_hours: int = 24
    plan_source: str = "scheduled"
    ambient_source: str = "forecast"
    test_fraction: float = 0.2
    train_origin_step: int = 6
    steps_per_origin: int = 24
    traj_every_hours: int = 6
    gbm_params: dict = field(default_factory=dict)
    seed: int = 42


@dataclass
class Site:
    ems_id: int
    info: dict
    df: pd.DataFrame
    gb: AuxGreyBox
    amb: F.Ambient
    typical_plan: np.ndarray
    aux_profile: np.ndarray
    sched_sp: np.ndarray
    cut: int
    rated_kw: float
    arr: dict = field(default_factory=dict)


def clean_gbm(params: dict) -> dict:
    out = {}
    for s in GBM_PARAMS:
        v = params.get(s["name"], s["default"])
        v = s["default"] if v in (None, "") else v
        v = int(v) if s["type"] == "int" else float(v)
        if not s["min"] <= v <= s["max"]:
            raise AuxForecastError(f"{s['label']} must be between {s['min']} and {s['max']}")
        out[s["name"]] = v
    return out


def bucket_of(h_min) -> np.ndarray:
    h = np.asarray(h_min)
    out = np.full(len(h), BUCKETS[-1][2], dtype=object)
    for lo, hi, name in reversed(BUCKETS):
        out[(h > lo) & (h <= hi)] = name
    return out


def fit_greybox(df: pd.DataFrame) -> AuxGreyBox:
    abs_p = df["power_kw"].abs().rolling(3, min_periods=1).mean()
    return AuxGreyBox.fit(df["aux_load_kw"], df["hvac_power_kw"], abs_p, df["ambient_temp_c"], F.solar_shape(df.index),
                          df["battery_heat_load_kw"], df["cop"], df["cooling_mode"].eq("COOLING").to_numpy())


def prepare(s: Site) -> None:
    """Per-reading arrays the rows are cut from (actual drivers -> the grey-box now and its residual)."""
    df = s.df
    abs_p = df["power_kw"].abs().fillna(df["p_setpoint_kw"].abs()).fillna(0.0)
    amb = df["ambient_temp_c"].to_numpy()
    gb_now = s.gb.aux(abs_p.rolling(3, min_periods=1).mean().to_numpy(), amb, F.solar_shape(df.index))
    aux = df["aux_load_kw"].to_numpy()
    res = pd.Series(aux - gb_now, index=df.index)
    cop = df["cop"].to_numpy()
    s.arr = {
        "aux": aux, "abs_p": abs_p.to_numpy(), "amb": amb, "gb0": gb_now, "gb_res0": res.to_numpy(),
        "gb_res_1h": res.rolling(12, min_periods=1).mean().to_numpy(),
        "cop": np.where(np.isfinite(cop), cop, s.gb.cop_at(amb)),
        "cool": pd.Categorical(df["cooling_mode"], categories=F.COOLING_MODES).codes.astype(float),
        "ok": df["ok"].to_numpy(), "slot": F.slot_of(df.index),
    }


def load_sites(engine: Engine, cfg: RunConfig, warnings: list[str]) -> list[Site]:
    infos = {s["ems_id"]: s for s in F.sites(engine)}
    out = []
    for eid in cfg.selection.ems_ids:
        info = infos.get(eid)
        if not info:
            warnings.append(f"EMS {eid} not found")
            continue
        df = F.series(engine, eid, cfg.selection.date_from, cfg.selection.date_to)
        if len(df) < 4 * F.STEPS_PER_DAY:
            warnings.append(f"{info['site_name']}: only {len(df)} readings - left out (needs 4 days)")
            continue
        # split on the real readings, not the grid (a long gap would otherwise swallow the test period)
        real = np.flatnonzero(df["ok"].to_numpy())
        cut = int(real[min(int(len(real) * (1 - cfg.test_fraction)), len(real) - 1)])
        train = df.iloc[:cut]
        try:
            gb = fit_greybox(train)
        except ValueError as exc:
            warnings.append(f"{info['site_name']}: {exc} - left out")
            continue
        if not gb.decomposed:
            warnings.append(f"{info['site_name']}: no HVAC telemetry - the grey-box models aux directly (no split)")
        if cfg.ambient_source == "forecast" and not info.get("wx_forecast_rows"):
            warnings.append(f"{info['site_name']}: no weather forecast for this site - ambient from the daily profile")
        rated = info.get("pcs_rated_kw") or (info.get("rated_power_mw") or 1) * 1000
        sched = schedule(engine, eid)
        sched_sp, _ = schedule_grid(sched, df.index)
        s = Site(eid, info, df, gb, F.ambient_for(engine, df["station_id"].iloc[0], train["ambient_temp_c"]),
                 F.daily_profile(train["p_setpoint_kw"].fillna(0)), F.daily_profile(train["aux_load_kw"]), sched_sp,
                 cut, float(rated))
        prepare(s)
        out.append(s)
    if not out:
        raise AuxForecastError("No site with enough aux-load history in the selection")
    return out


# ---------------------------------------------------------------- rows


def plan_matrix(s: Site, origins: np.ndarray, max_steps: int, source: str, future_ts=None, sched_future=None):
    """Planned setpoint (kW) for steps 0..max_steps after each origin (0 = the origin), and whether the schedule covers
    it. Live: future_ts / sched_future hold steps 0..max_steps."""
    if future_ts is None:
        idx = np.minimum(origins[:, None] + np.arange(max_steps + 1)[None, :], len(s.df) - 1)
        slots = s.arr["slot"][idx]
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


def rows_for(s: Site, origins: np.ndarray, steps: list[np.ndarray], plan_source: str, ambient_source: str,
             with_target: bool = True, future=None) -> pd.DataFrame:
    """One row per (origin, step) with the features, the grey-box forecast and (training / backtest) the actual.
    `steps[i]` are the horizon steps (1 = 5 min) of origin i."""
    df, a = s.df, s.arr
    max_steps = int(max(st.max() for st in steps))
    plan, cover = plan_matrix(s, origins, max_steps, plan_source, *(future or (None, None)))
    abs_plan = np.abs(plan)
    csum = np.cumsum(abs_plan, axis=1)
    n_per = np.array([len(st) for st in steps])
    o = np.repeat(origins, n_per)
    r = np.repeat(np.arange(len(origins)), n_per)
    k = np.concatenate(steps)
    ts0 = df.index[o]
    t_target = ts0 + pd.to_timedelta(k * F.STEP_MIN, unit="min")
    # ambient at the targets as known at each origin
    amb_fc = np.empty(len(k))
    ghi_fc = np.empty(len(k))
    src = np.empty(len(k))
    start = 0
    actual_amb = a["amb"]
    for i, (orig, st) in enumerate(zip(origins, steps)):
        sl = slice(start, start + len(st))
        tgt = t_target[sl]
        act = actual_amb[np.minimum(orig + st, len(actual_amb) - 1)] if with_target else None
        amb_fc[sl], ghi_fc[sl], src[sl] = s.amb.at(df.index[orig], a["amb"][orig], tgt, ambient_source, act)
        start += len(st)
    # the load leading into the target (15 min) and the mean over (t, t + h]
    lo = np.maximum(k - 2, 0)
    plan_15 = (csum[r, k] - np.where(lo > 0, csum[r, lo - 1], 0.0)) / (k - lo + 1)
    plan_mean = (csum[r, k] - csum[r, 0]) / k
    solar_t = F.solar_shape(t_target)
    gb = s.gb.aux(plan_15, amb_fc, solar_t)
    aux = a["aux"]
    lag = o + k - F.STEPS_PER_DAY
    seasonal = np.where(lag >= 0, aux[np.maximum(lag, 0)], np.nan)
    col = lambda c: df[c].to_numpy()[o]  # noqa: E731
    out = pd.DataFrame({
        "h_min": (k * F.STEP_MIN).astype(float), "aux0": aux[o], "aux_d15": aux[o] - aux[np.maximum(o - 3, 0)],
        "aux_1h": col("aux_1h_kw"), "aux_max_1h": col("aux_max_1h_kw"), "aux_3h": col("aux_3h_kw"),
        "hvac0": col("hvac_power_kw"), "hvac_1h": col("hvac_1h_kw"), "gb0": a["gb0"][o], "gb_res0": a["gb_res0"][o],
        "gb_res_1h": a["gb_res_1h"][o], "seasonal": seasonal,
        "seasonal_delta": aux[o] - aux[np.maximum(o - F.STEPS_PER_DAY, 0)] if len(df) > F.STEPS_PER_DAY else np.nan,
        "amb0": a["amb"][o], "amb_fc": amb_fc, "amb_delta": amb_fc - a["amb"][o], "amb_src": src, "ghi_fc": ghi_fc,
        "plan_h": abs_plan[r, k] / s.rated_kw, "plan_15": plan_15 / s.rated_kw, "plan_mean": plan_mean / s.rated_kw,
        "plan_cov": cover[r, 1:].mean(axis=1) if cover.shape[1] > 1 else 0.0,
        "absp0": a["abs_p"][o] / s.rated_kw, "c_rate0": col("c_rate"), "kva0": col("ac_apparent_power_kva") / s.rated_kw,
        "cooling_mode": a["cool"][o], "cop0": a["cop"][o], "compressor0": col("compressor_speed_pct"),
        "setpoint_c": col("coolant_setpoint_c"), "cell_max0": col("cell_temp_max_c"), "return0": col("coolant_return_temp_c"),
        "enclosure0": col("enclosure_temp_c"), "humidity0": col("enclosure_humidity_pct"), "heat0": col("battery_heat_load_kw"),
        "gb": gb, "gb_delta": gb - a["gb0"][o],
        "hour_o": ts0.hour.to_numpy() + ts0.minute.to_numpy() / 60.0,
        "hour_t": t_target.hour.to_numpy() + t_target.minute.to_numpy() / 60.0,
        "dow_t": t_target.dayofweek.to_numpy().astype(float), "site_code": float(s.ems_id),
    })
    out["pos"], out["step"], out["ems_id"] = o, k, s.ems_id
    out["origin_ts"], out["target_ts"] = ts0, t_target
    out["plan_kw"] = plan[r, k]
    if with_target:
        tgt = np.minimum(o + k, len(aux) - 1)
        out["actual"] = np.where(o + k < len(aux), aux[tgt], np.nan)
        out["ok"] = a["ok"][o] & a["ok"][tgt] & (o + k < len(aux))
    return out


# ---------------------------------------------------------------- quantile models


class Residual:
    def __init__(self, params: dict, seed: int):
        self.params, self.seed, self.models = params, seed, {}

    def fit(self, rows: pd.DataFrame) -> "Residual":
        X, y = rows[ROW_FEATURES], (rows["actual"] - rows["gb"]).to_numpy()
        for q in QUANTILES:
            self.models[q] = lgb.LGBMRegressor(objective="quantile", alpha=q, random_state=self.seed, verbose=-1,
                                               n_jobs=4, subsample_freq=1, **self.params).fit(X, y)
        return self

    def predict(self, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """P10 / P50 / P90 of aux (grey-box + residual quantiles), sorted and never negative."""
        gb = rows["gb"].to_numpy()
        trio = np.sort(np.vstack([gb + self.models[q].predict(rows[ROW_FEATURES]) for q in QUANTILES]), axis=0)
        return tuple(np.maximum(trio, 0.0))

    def importance(self) -> dict[str, float]:
        b = self.models[0.5].booster_
        return shares(dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float))))


def error_bands(rows: pd.DataFrame, pred_col: str) -> dict[str, tuple[float, float]]:
    out = {}
    for b, g in rows.groupby(bucket_of(rows["h_min"])):
        e = (g["actual"] - g[pred_col]).dropna().to_numpy()
        out[str(b)] = (float(np.quantile(e, 0.1)), float(np.quantile(e, 0.9))) if len(e) > 10 else (0.0, 0.0)
    return out


def with_band(p50: np.ndarray, h: np.ndarray, bands: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    b = bucket_of(h)
    lo = np.array([bands.get(x, (0.0, 0.0))[0] for x in b])
    hi = np.array([bands.get(x, (0.0, 0.0))[1] for x in b])
    return np.maximum(p50 + lo, 0.0), p50, np.maximum(p50 + hi, 0.0)


def baseline_preds(rows: pd.DataFrame, bands: dict) -> dict[str, tuple]:
    h = rows["h_min"].to_numpy()
    return {m: with_band(rows[c].to_numpy(), h, bands[m])
            for m, c in (("persistence", "aux0"), ("seasonal", "seasonal"), ("greybox", "gb"))}


# ---------------------------------------------------------------- training


def test_origins(s: Site, max_steps: int) -> np.ndarray:
    o = np.arange(max(s.cut, F.STEPS_PER_DAY), len(s.df) - max_steps)
    o = o[((s.arr["slot"][o] + 1) % ORIGIN_GRID) == 0]
    return o[s.arr["ok"][o]]


def train(engine: Engine, cfg: RunConfig) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame, list[str]]:
    started = time.perf_counter()
    warnings: list[str] = []
    if not 1 <= cfg.horizon_hours <= 24:
        raise AuxForecastError("The horizon must be 1 to 24 hours")
    if cfg.ambient_source not in ("forecast", "profile", "actual") or cfg.plan_source not in ("scheduled", "typical"):
        raise AuxForecastError("Unknown plan or ambient source")
    gbm = clean_gbm(cfg.gbm_params)
    max_steps = cfg.horizon_hours * 60 // F.STEP_MIN
    sites = load_sites(engine, cfg, warnings)
    rng = np.random.default_rng(cfg.seed)

    tr_parts, te_parts = [], []
    for s in sites:
        ok = s.arr["ok"]
        tr_o = np.arange(F.STEPS_PER_DAY, s.cut - max_steps, max(1, cfg.train_origin_step))
        tr_o = tr_o[ok[tr_o]]
        te_o = test_origins(s, max_steps)
        if len(tr_o) < 50 or not len(te_o):
            warnings.append(f"{s.info['site_name']}: too little history for a {cfg.horizon_hours} h horizon - left out")
            continue
        n_st = min(cfg.steps_per_origin, max_steps)
        tr_steps = [np.sort(rng.choice(np.arange(1, max_steps + 1), n_st, replace=False)) for _ in tr_o]
        tr_parts.append(rows_for(s, tr_o, tr_steps, cfg.plan_source, cfg.ambient_source))
        full = np.arange(1, max_steps + 1)
        te_parts.append(rows_for(s, te_o, [full] * len(te_o), cfg.plan_source, cfg.ambient_source))
    if not tr_parts:
        raise AuxForecastError("No site has enough history for this horizon")
    tr = pd.concat(tr_parts, ignore_index=True)
    tr = tr[tr["ok"]].reset_index(drop=True)
    te = pd.concat(te_parts, ignore_index=True)
    te = te[te["ok"]].reset_index(drop=True)

    tr["persistence"] = tr["aux0"]
    bands = {"persistence": error_bands(tr, "persistence"), "seasonal": error_bands(tr.dropna(subset=["seasonal"]), "seasonal"),
             "greybox": error_bands(tr, "gb")}
    model = Residual(gbm, cfg.seed).fit(tr)
    preds = baseline_preds(te, bands)
    preds["hybrid"] = model.predict(te)

    metrics = scores(te, preds)
    daily = daily_energy(te, preds)
    points = backtest_points(te, preds, cfg.traj_every_hours)
    trained = sorted(set(te["ems_id"]))
    artifact = {
        "horizon_hours": cfg.horizon_hours, "plan_source": cfg.plan_source, "ambient_source": cfg.ambient_source,
        "model": model, "bands": bands,
        "sites": {s.ems_id: {"info": s.info, "gb": s.gb, "amb_profile": s.amb.profile, "typical_plan": s.typical_plan,
                             "aux_profile": s.aux_profile, "rated_kw": s.rated_kw} for s in sites if s.ems_id in trained},
    }
    summary = {
        "n_train_rows": int(len(tr)), "n_test_rows": int(len(te)), "metrics": metrics,
        "results": {
            "importance": model.importance(),
            "greybox": {str(s.ems_id): s.gb.to_dict() for s in sites if s.ems_id in trained},
            "split": {str(s.ems_id): {"site_name": s.info["site_name"], "train_from": s.df.index[0].isoformat(),
                                      "test_from": s.df.index[s.cut].isoformat(), "to": s.df.index[-1].isoformat()}
                      for s in sites if s.ems_id in trained},
            "daily": daily["summary"],
            "summary": headline(metrics, daily["summary"]),
        },
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return artifact, summary, points, daily["rows"], warnings


def score(actual, p10, p50, p90) -> dict:
    ok = np.isfinite(actual) & np.isfinite(p50)
    a, lo, md, hi = actual[ok], p10[ok], p50[ok], p90[ok]
    if not len(a):
        return {"n": 0}
    err = a - md
    pin = np.mean([np.mean(np.maximum(q * (a - p), (q - 1) * (a - p))) for q, p in zip(QUANTILES, (lo, md, hi))])
    return {"n": int(len(a)), "mae": finite(np.mean(np.abs(err))), "rmse": finite(np.sqrt(np.mean(err ** 2))),
            "bias": finite(np.mean(md - a)), "pinball": finite(pin),
            "coverage_pct": finite(100 * np.mean((a >= lo) & (a <= hi)))}


def scores(te: pd.DataFrame, preds: dict) -> dict:
    """{ems_id or 'all': {bucket or 'all': {method: score}}}"""
    actual = te["actual"].to_numpy()
    bucket = bucket_of(te["h_min"])
    out = {}
    for key, mask in [("all", np.ones(len(te), bool))] + [(str(e), (te["ems_id"] == e).to_numpy()) for e in sorted(set(te["ems_id"]))]:
        out[key] = {}
        for b in ["all"] + [name for *_, name in BUCKETS if (bucket == name).any()]:
            m = mask if b == "all" else mask & (bucket == b)
            out[key][b] = {mth: score(actual[m], *(p[m] for p in preds[mth])) for mth in METHODS}
    return out


def daily_energy(te: pd.DataFrame, preds: dict) -> dict:
    """Aux energy of each test day from the forecasts issued at 23:55 the evening before (24 h ahead only)."""
    at_2355 = (te["origin_ts"].dt.hour == 23) & (te["origin_ts"].dt.minute == 55)
    rows, summary = [], {}
    if te["step"].max() < F.STEPS_PER_DAY or not at_2355.any():
        return {"rows": pd.DataFrame(), "summary": {"note": "needs a 24 h horizon"}}
    sel = te[at_2355].copy()
    for mth in METHODS:
        for i, q in enumerate(("p10", "p50", "p90")):
            sel[f"{mth}_{q}"] = preds[mth][i][at_2355.to_numpy()]
    kwh = F.STEP_MIN / 60.0
    for (eid, origin), g in sel.groupby(["ems_id", "origin_ts"]):
        if len(g) < F.STEPS_PER_DAY or g["actual"].isna().any():
            continue  # only complete days
        day = (origin + pd.Timedelta(minutes=5)).date()
        for mth in METHODS:
            rows.append({"ems_id": int(eid), "day": day, "method": mth, "actual_kwh": float(g["actual"].sum() * kwh),
                         **{f"{q}_kwh": float(g[f"{mth}_{q}"].sum() * kwh) for q in ("p10", "p50", "p90")}})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"rows": df, "summary": {"note": "no complete test day"}}
    for key, g0 in [("all", df)] + [(str(e), g) for e, g in df.groupby("ems_id")]:
        summary[key] = {}
        for mth, g in g0.groupby("method"):
            err = g["p50_kwh"] - g["actual_kwh"]
            summary[key][mth] = {"days": int(len(g)), "mae_kwh": finite(err.abs().mean()),
                                 "mape_pct": finite(100 * (err.abs() / g["actual_kwh"]).mean()),
                                 "bias_kwh": finite(err.mean()), "actual_kwh_avg": finite(g["actual_kwh"].mean()),
                                 "coverage_pct": finite(100 * ((g["actual_kwh"] >= g["p10_kwh"]) &
                                                               (g["actual_kwh"] <= g["p90_kwh"])).mean())}
    return {"rows": df, "summary": summary}


def backtest_points(te: pd.DataFrame, preds: dict, traj_hours: int) -> pd.DataFrame:
    """Full trajectories of the origins every `traj_hours` (ending at :55) and the report horizons of every origin."""
    slot = F.slot_of(pd.DatetimeIndex(te["origin_ts"]))
    traj = ((slot + 1) % max(1, traj_hours * 12)) == 0
    keep = traj | te["h_min"].isin(REPORT_HORIZONS).to_numpy()
    parts = []
    for mth in METHODS:
        lo, md, hi = preds[mth]
        parts.append(pd.DataFrame({"ems_id": te["ems_id"][keep], "origin_ts": te["origin_ts"][keep],
                                   "horizon_min": te["h_min"][keep].astype(int), "method": mth, "p10": lo[keep],
                                   "p50": md[keep], "p90": hi[keep], "actual": te["actual"][keep]}))
    return pd.concat(parts, ignore_index=True)


def headline(metrics: dict, daily: dict) -> dict:
    allm = metrics["all"]["all"]
    sea = allm["seasonal"].get("mae")
    out = {"mae": {m: allm[m].get("mae") for m in METHODS}, "pinball": {m: allm[m].get("pinball") for m in METHODS},
           "coverage_pct": {m: allm[m].get("coverage_pct") for m in METHODS},
           "skill_vs_seasonal_pct": {m: finite(100 * (1 - allm[m]["mae"] / sea)) if sea and allm[m].get("mae") is not None
                                     else None for m in METHODS}}
    if "all" in daily:
        out["daily_mae_kwh"] = {m: daily["all"].get(m, {}).get("mae_kwh") for m in METHODS}
        out["daily_mape_pct"] = {m: daily["all"].get(m, {}).get("mape_pct") for m in METHODS}
    return out


# ---------------------------------------------------------------- serving


def _site_from(art: dict, ems_id: int, df: pd.DataFrame, amb: F.Ambient, sched_sp: np.ndarray) -> Site:
    reg = art["sites"][ems_id]
    s = Site(ems_id, reg["info"], df, reg["gb"], amb, reg["typical_plan"], reg["aux_profile"], sched_sp, len(df),
             reg["rated_kw"])
    prepare(s)
    return s


def override_ambient(s: Site, rows: pd.DataFrame, amb: np.ndarray) -> None:
    """Replace the ambient at the targets (where `amb` is known) and recompute the grey-box from it."""
    ok = np.isfinite(amb)
    rows.loc[ok, "amb_fc"] = amb[ok]
    rows.loc[ok, "amb_src"] = 1.0
    rows["amb_delta"] = rows["amb_fc"] - rows["amb0"]
    rows["gb"] = s.gb.aux(rows["plan_15"].to_numpy() * s.rated_kw, rows["amb_fc"].to_numpy(),
                          F.solar_shape(pd.DatetimeIndex(rows["target_ts"])))
    rows["gb_delta"] = rows["gb"] - rows["gb0"]


def _forecast_records(rows: pd.DataFrame, trio, gb: AuxGreyBox, bands: dict) -> list[dict]:
    lo, md, hi = trio
    sea = with_band(rows["seasonal"].to_numpy(), rows["h_min"].to_numpy(), bands["seasonal"])[1]
    kwh = F.STEP_MIN / 60.0
    out = []
    for i in range(len(rows)):
        out.append({
            "ts_target": rows["target_ts"].iloc[i].isoformat(), "horizon_min": int(rows["h_min"].iloc[i]),
            "aux_kw_p50": finite(md[i]), "aux_kw_p10": finite(lo[i]), "aux_kw_p90": finite(hi[i]),
            "hvac_kw_p50": finite(max(md[i] - gb.controls_base, 0.0)) if gb.decomposed else None,
            "controls_kw": gb.controls_base if gb.decomposed else None,
            "aux_energy_kwh": finite(md[i] * kwh), "greybox_kw": finite(rows["gb"].iloc[i]),
            "seasonal_kw": finite(sea[i]) if np.isfinite(sea[i]) else None,
            "ambient_fc_c": finite(rows["amb_fc"].iloc[i]), "ambient_from_forecast": bool(rows["amb_src"].iloc[i] > 0),
            "plan_kw": finite(rows["plan_kw"].iloc[i]),
        })
    return out


def _daily(records: list[dict]) -> list[dict]:
    """aux_energy_kwh per calendar day of the horizon (the P10 / P90 sums assume fully correlated errors: a wide band)."""
    kwh = F.STEP_MIN / 60.0
    days: dict[str, dict] = {}
    for r in records:
        d = r["ts_target"][:10]
        x = days.setdefault(d, {"day": d, "intervals": 0, "aux_energy_kwh_p50": 0.0, "aux_energy_kwh_p10": 0.0,
                                "aux_energy_kwh_p90": 0.0, "actual_kwh": 0.0, "actual_intervals": 0})
        if r["aux_kw_p50"] is None:
            continue
        x["intervals"] += 1
        for q in ("p10", "p50", "p90"):
            x[f"aux_energy_kwh_{q}"] += r[f"aux_kw_{q}"] * kwh
        if r.get("actual_kw") is not None:
            x["actual_kwh"] += r["actual_kw"] * kwh
            x["actual_intervals"] += 1
    for x in days.values():
        x["hours"] = x["intervals"] * F.STEP_MIN / 60.0
        if not x["actual_intervals"]:
            x["actual_kwh"] = None
    return list(days.values())


def predict_live(engine: Engine, art: dict, ems_id: int, horizon_hours: Optional[int] = None,
                 plan_source: Optional[str] = None, ambient_source: Optional[str] = None, as_of: Optional[str] = None,
                 history_hours: int = 24, max_data_age_min: Optional[float] = None) -> dict:
    """{ts_target, horizon_min, aux_kw_p50, aux_kw_p10, aux_kw_p90} at 5-min steps from the newest reading of a site
    (or the newest at / before `as_of`, then with the actuals that followed) - online fetch from v_aux_features - plus
    aux_energy_kwh per interval and per day. NULL predictions with a staleness flag when inputs are stale / missing,
    or (max_data_age_min) when the newest reading is older than that."""
    if ems_id not in art["sites"]:
        raise AuxForecastError(f"EMS {ems_id} is not part of this model")
    horizon_hours = horizon_hours or art["horizon_hours"]
    if not 1 <= horizon_hours <= 24:
        raise AuxForecastError("The horizon must be 1 to 24 hours")
    plan_source = plan_source or art["plan_source"]
    ambient_source = ambient_source or art["ambient_source"]
    max_steps = horizon_hours * 12
    cutoff = pd.Timestamp(as_of).tz_convert(F.TZ) if as_of and pd.Timestamp(as_of).tzinfo else \
        (pd.Timestamp(as_of).tz_localize(F.TZ) if as_of else None)
    lo_day = ((cutoff or pd.Timestamp.now(tz=F.TZ)) - pd.Timedelta(days=3)).date()
    hi_day = (cutoff + pd.Timedelta(days=2)).date() if cutoff is not None else None
    full = F.series(engine, ems_id, lo_day if cutoff is not None else None, hi_day)
    if full.empty:
        raise AuxForecastError(f"EMS {ems_id} has no aux readings")
    df = full[full.index <= cutoff] if cutoff is not None else full
    if len(df) < 2:
        raise AuxForecastError("No readings at or before the requested time")
    df = df.iloc[-(F.STEPS_PER_DAY + 24):]
    origin_ts = df.index[-1]
    after = full["aux_load_kw"][full.index > origin_ts].iloc[:max_steps]
    reg = art["sites"][ems_id]
    station = df["station_id"].iloc[-1]
    amb = F.Ambient(F.ambient_for(engine, station, df["ambient_temp_c"]).runs, reg["amb_profile"])
    future_ts = pd.date_range(origin_ts, periods=max_steps + 1, freq=f"{F.STEP_MIN}min", tz=F.TZ)
    sched_future, _ = schedule_grid(schedule(engine, ems_id), future_ts)
    s = _site_from(art, ems_id, df, amb, np.full(len(df), np.nan))
    data_age = (pd.Timestamp.now(tz=F.TZ) - origin_ts).total_seconds() / 60
    stale_min = float(df["stale_min"].iloc[-1])
    missing = [c for c in ("aux_load_kw", "ambient_temp_c") if not np.isfinite(df[c].iloc[-1])]
    too_old = max_data_age_min is not None and data_age > max_data_age_min
    stale = too_old or stale_min > STALE_LIMIT_MIN
    origin = np.array([len(df) - 1])
    steps = [np.arange(1, max_steps + 1)]
    rows = rows_for(s, origin, steps, plan_source, "profile" if ambient_source == "actual" else ambient_source,
                    with_target=False, future=(future_ts, sched_future))
    if ambient_source == "actual":  # oracle: the measured ambient where it exists
        override_ambient(s, rows, full["ambient_temp_c"].reindex(future_ts[1:]).to_numpy())
    if stale or missing:
        records = [{"ts_target": t.isoformat(), "horizon_min": int(h), "aux_kw_p50": None, "aux_kw_p10": None,
                    "aux_kw_p90": None, "aux_energy_kwh": None}
                   for t, h in zip(rows["target_ts"], rows["h_min"])]
    else:
        records = _forecast_records(rows, art["model"].predict(rows), s.gb, art["bands"])
    act = after.reindex(pd.DatetimeIndex(rows["target_ts"]))
    for r, v in zip(records, act.to_numpy()):
        r["actual_kw"] = finite(v) if np.isfinite(v) else None
    hist = df.iloc[-history_hours * 12:]
    pts = lambda c: [{"ts": t.isoformat(), "v": finite(v) if v == v else None} for t, v in hist[c].items()]  # noqa: E731
    return {
        "ems_id": ems_id, "site_name": reg["info"].get("site_name"), "origin_ts": origin_ts.isoformat(),
        "horizon_hours": horizon_hours, "plan_source": plan_source, "ambient_source": ambient_source,
        "data_age_min": finite(data_age),
        "flags": {"stale": stale, "stale_min": stale_min, "too_old": too_old, "missing_inputs": missing},
        "greybox": s.gb.to_dict(), "forecasts": records, "daily": _daily(records),
        "history": {"aux_load_kw": pts("aux_load_kw"), "hvac_power_kw": pts("hvac_power_kw"),
                    "ambient_temp_c": pts("ambient_temp_c")},
    }


VECTOR_REQUIRED = ["aux_load_kw", "ambient_temp_c"]


def predict_vector(art: dict, ems_id: int, inputs: dict, horizon_hours: Optional[int] = None,
                   plan_kw: Optional[list[float]] = None, ambient_fc_c: Optional[list[float]] = None,
                   aux_yesterday_kw: Optional[list[float]] = None, origin_ts: Optional[str] = None) -> dict:
    """Stateless predict(features): the aux forecast from a feature vector alone (no database read).

    inputs            current readings: aux_load_kw and ambient_temp_c (required); hvac_power_kw, power_kw,
                      p_setpoint_kw, c_rate, ac_apparent_power_kva, cooling_mode, cop, compressor_speed_pct,
                      coolant_setpoint_c, cell_temp_max_c, coolant_return_temp_c, enclosure_temp_c,
                      enclosure_humidity_pct, battery_heat_load_kw, aux_1h_kw, aux_max_1h_kw, aux_3h_kw, hvac_1h_kw,
                      stale_min (optional)
    plan_kw           planned setpoint per 5-min step ahead (else the site's typical day)
    ambient_fc_c      ambient per 5-min step ahead (else ambient now + the typical daily swing)
    aux_yesterday_kw  aux 24 h before each step ahead (else the site's typical day) - for the seasonal features
    Missing required inputs or stale_min above the limit give NULL predictions with a flag."""
    if ems_id not in art["sites"]:
        raise AuxForecastError(f"EMS {ems_id} is not part of this model")
    reg = art["sites"][ems_id]
    horizon_hours = horizon_hours or art["horizon_hours"]
    if not 1 <= horizon_hours <= 24:
        raise AuxForecastError("The horizon must be 1 to 24 hours")
    max_steps = horizon_hours * 12
    t0 = pd.Timestamp(origin_ts) if origin_ts else pd.Timestamp.now(tz=F.TZ)
    t0 = (t0.tz_convert(F.TZ) if t0.tzinfo else t0.tz_localize(F.TZ)).floor(f"{F.STEP_MIN}min")
    missing = [k for k in VECTOR_REQUIRED if inputs.get(k) is None]
    stale = float(inputs.get("stale_min") or 0.0)
    future_ts = pd.date_range(t0, periods=max_steps + 1, freq=f"{F.STEP_MIN}min", tz=F.TZ)
    if missing or stale > STALE_LIMIT_MIN:
        return {"forecasts": [{"ts_target": t.isoformat(), "horizon_min": (i + 1) * F.STEP_MIN, "aux_kw_p50": None,
                               "aux_kw_p10": None, "aux_kw_p90": None, "aux_energy_kwh": None}
                              for i, t in enumerate(future_ts[1:])],
                "daily": [], "flags": {"stale": stale > STALE_LIMIT_MIN, "stale_min": stale, "missing_inputs": missing}}
    # a one-day history window: yesterday's aux (seasonal) and the current readings at its end
    idx = pd.date_range(t0 - pd.Timedelta(minutes=F.STEP_MIN * F.STEPS_PER_DAY), t0, freq=f"{F.STEP_MIN}min", tz=F.TZ)
    df = pd.DataFrame(index=idx)
    for c in F.NUMERIC:
        df[c] = float(inputs[c]) if inputs.get(c) is not None else np.nan
    yest = np.asarray(aux_yesterday_kw[:F.STEPS_PER_DAY], float) if aux_yesterday_kw else None
    prof = reg["aux_profile"][F.slot_of(idx)]
    aux = prof.copy()
    if yest is not None:
        aux[1:1 + len(yest)] = yest
    aux[-1] = float(inputs["aux_load_kw"])
    df["aux_load_kw"] = aux
    if inputs.get("power_kw") is None and inputs.get("p_setpoint_kw") is not None:
        df["power_kw"] = float(inputs["p_setpoint_kw"])
    df["cooling_mode"] = inputs.get("cooling_mode")
    df["ok"] = True
    df["stale_min"] = stale
    for c in ("aux_1h_kw", "aux_3h_kw", "aux_max_1h_kw"):
        if inputs.get(c) is None:
            df[c] = float(inputs["aux_load_kw"])
    amb = F.Ambient([], reg["amb_profile"])
    sched = np.full(max_steps + 1, np.nan)
    if plan_kw:
        sched[1:1 + min(max_steps, len(plan_kw))] = np.asarray(plan_kw[:max_steps], float)
    s = _site_from(art, ems_id, df, amb, np.full(len(df), np.nan))
    rows = rows_for(s, np.array([len(df) - 1]), [np.arange(1, max_steps + 1)], "scheduled" if plan_kw else "typical",
                    "profile", with_target=False, future=(future_ts, sched))
    if ambient_fc_c:
        fc = np.full(max_steps, np.nan)
        fc[:min(max_steps, len(ambient_fc_c))] = np.asarray(ambient_fc_c[:max_steps], float)
        override_ambient(s, rows, fc)
    records = _forecast_records(rows, art["model"].predict(rows), s.gb, art["bands"])
    return {"forecasts": records, "daily": _daily(records),
            "flags": {"stale": False, "stale_min": stale, "missing_inputs": []}}
