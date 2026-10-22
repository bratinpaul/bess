"""One net-load forecasting run: build the rows, split per metering point in time, fit every chosen model (the
seasonal naïve always - it's the skill reference), backtest them from the same origins, derive the daily billing
peaks and score both.

Split per metering point: the newest `test_fraction` of its readings is the test period. Training origins only use
targets before it (no leakage); test origins start at the cut-off every `origin_step_h` hours (on whole hours: the
origin is the hh:55 reading), each forecasting k = 1..S 5-min steps ahead.

Scores (P50 is the point forecast), on the test forecasts:
  load    MAE, RMSE, MAPE, bias; pinball loss over P10 / P50 / P90; P10-P90 coverage (target 80 %) and width; skill
          vs the seasonal naïve (1 - MAE / MAE naïve); MAE inside the billing-peak window; MAE per hour of lead and
          per hour of day
  peaks   per (origin, target day) with the whole billing window in the horizon: peak MAE and bias (kW), timing
          error (minutes), and for "peak above the threshold": Brier score, AUC, recall and precision at p >= 0.5 -
          for every regressor (probability from its band) and the peak classifier (vs its per-day-class reference)
"""
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sqlalchemy.engine import Engine

from core.metrics import finite, shares
from usecases.netload_forecast import features as F
from usecases.netload_forecast.models import BASELINE, FORECASTERS, PEAK, QUANTILES, ForecastError, TrainData
from usecases.netload_forecast.models.gbm import calibration_mask
from usecases.netload_forecast.models.peak import (PeakClassifier, calibrate_peaks, day_rows, peak_calibration,
                                                    peaks_from_forecast)

MIN_TRAIN_ORIGINS = 24
PEAK_CAL_SHARE = 0.2  # newest share of the training origins whose daily peaks calibrate each model's peak


@dataclass
class RunConfig:
    selection: F.Selection
    models: list[str]
    params: dict[str, dict]
    horizon_hours: int = 48
    test_fraction: float = 0.25
    origin_step_h: int = 3
    train_origin_step_h: int = 2
    seed: int = 42


@dataclass
class RunResult:
    artifact: dict
    summary: dict
    points: pd.DataFrame
    peaks: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def hour_ends(s: F.Series, lo: int, hi: int, every_h: int) -> np.ndarray:
    """Origin positions in [lo, hi] on hh:55 readings, every `every_h` hours."""
    lo, hi = max(lo, 0), min(hi, s.n - 1)
    if hi < lo:
        return np.array([], dtype=np.int64)
    pos = np.arange(lo, hi + 1)
    m = s.ts(pos).minute == 60 - F.STEP_MIN
    pos = pos[m]
    return pos[::max(1, every_h)].astype(np.int64)


def fit_pv_ratio(s: F.Series, end: int) -> float:
    g, r = s.gen[:end + 1], s.ghi[:end + 1]
    m = np.isfinite(g) & np.isfinite(r) & (r > 100)
    return float(np.median(g[m] / r[m])) if m.sum() > 20 else 0.0


def load_series(engine: Engine, sel: F.Selection, steps: int, warnings: list[str]) -> tuple[dict, dict]:
    points = {m["mp_id"]: m for m in F.metering_points(engine)}
    cal = F.calendar(engine)
    series, info = {}, {}
    need = F.HISTORY + steps + 2 * F.PER_DAY
    for mp in sel.mp_ids:
        meta = points.get(mp)
        if meta is None:
            raise ForecastError(f"Metering point {mp} does not exist")
        df = F.demand(engine, mp, sel.date_from, sel.date_to)
        if len(df) < need:
            warnings.append(f"{meta['mp_code']}: only {len(df)} readings ({len(df) / F.PER_DAY:.1f} days) - left out "
                            f"(needs {need / F.PER_DAY:.0f} days: 7 days of history, the horizon and a test period)")
            continue
        if df["net"].isna().any():
            warnings.append(f"{meta['mp_code']}: {int(df['net'].isna().sum())} readings missing after interpolation "
                            "- those targets are skipped")
        elif df["gap"].sum():
            warnings.append(f"{meta['mp_code']}: {int(df['gap'].sum())} missing 5-min readings were interpolated")
        t = F.tariff(engine, meta["site_id"])
        if t is None:
            warnings.append(f"{meta['mp_code']}: no demand tariff for its site - billing window "
                            f"{F.DEFAULT_WINDOW[0]:g}-{F.DEFAULT_WINDOW[1]:g} h assumed")
        if meta.get("station_id") is None:
            warnings.append(f"{meta['mp_code']}: its site has no weather station - weather features are empty")
        series[mp] = F.Series.build(engine, meta, df, cal, t)
        info[mp] = meta
    if not series:
        raise ForecastError("No metering point with enough demand history in the selection")
    return series, info


def train(engine: Engine, cfg: RunConfig) -> RunResult:
    started = time.perf_counter()
    sel = cfg.selection
    S = cfg.horizon_hours * F.PER_HOUR
    warnings: list[str] = []
    series, info = load_series(engine, sel, S, warnings)

    train_parts, test_parts, train_end = [], [], {}
    thresholds = []
    for mp, s in series.items():
        cut = int(round(s.n * (1 - cfg.test_fraction)))
        train_end[mp] = cut - 1
        s.pv_ratio = fit_pv_ratio(s, cut - 1)
        tr_o = hour_ends(s, F.HISTORY - 1, cut - 1 - S, cfg.train_origin_step_h)
        te_o = hour_ends(s, cut - 1, s.n - 1 - S, cfg.origin_step_h)
        if len(tr_o) < MIN_TRAIN_ORIGINS or len(te_o) < 1:
            warnings.append(f"{info[mp]['mp_code']}: too short for a {cfg.horizon_hours} h horizon with this test share "
                            f"({len(tr_o)} training / {len(te_o)} test origins) - left out")
            continue
        train_parts.append(F.rows(s, tr_o, S, sel.weather_source))
        test_parts.append(F.rows(s, te_o, S, sel.weather_source))
        pk = s.daily_peaks()
        cut_ts = s.ts(cut - 1)[0]
        thresholds.extend(pk[pd.to_datetime(pk["peak_ts"]) <= cut_ts]["peak"].tolist())
    if not train_parts:
        raise ForecastError("No metering point has enough history for training and testing")
    tr = pd.concat(train_parts, ignore_index=True)
    te = pd.concat(test_parts, ignore_index=True).sort_values(["mp_id", "origin_pos", "step"]).reset_index(drop=True)
    tr = tr[np.isfinite(tr["y"])].reset_index(drop=True)
    te = te[np.isfinite(te["y"])].reset_index(drop=True)
    features = [f for f in sel.features if f in tr]

    # the peak threshold: given, else the 75th percentile of the training days' billing peaks
    auto_threshold = float(np.round(np.quantile(thresholds, 0.75), -1)) if thresholds else None
    threshold = float(sel.peak_threshold_kw) if sel.peak_threshold_kw else auto_threshold
    if threshold is None:
        raise ForecastError("No complete training day to set the peak threshold from - give one")
    window = next(iter(series.values())).window

    if sel.weather_source == "actual":
        warnings.append("Weather source = measured: the models saw the actual weather at each target (a perfect "
                        "weather forecast). Scores are an upper bound; live forecasts use the forecast runs.")
    else:
        share_fc = float(te["wx_forecast"].mean()) if "wx_forecast" in te else 0.0
        if share_fc < 0.99:
            warnings.append(f"Weather forecasts cover {100 * share_fc:.0f} % of the test targets; the rest use the "
                            "recent days' measured weather at the same time of day (wx_forecast = 0).")
    missing_cal = sorted({d for d in pd.concat([tr["target_date"], te["target_date"]]).unique()
                          if d not in next(iter(series.values())).cal})
    if missing_cal:
        warnings.append(f"{len(missing_cal)} target day(s) are not in battery_master.calendar_day "
                        f"({missing_cal[0]} … {missing_cal[-1]}): Saturday / Sunday counted as weekend, no holidays.")

    data = TrainData(tr, series, features, S, train_end, sel.weather_source, cfg.seed, warnings)
    keys = [BASELINE] + [k for k in cfg.models if k in FORECASTERS and k != BASELINE]
    fitted, forecasts, timings, importance, peak_cal = {}, {}, {}, {}, {}
    cal_rows = tr[calibration_mask(tr, PEAK_CAL_SHARE)]
    for k in keys:
        t0 = time.perf_counter()
        m = FORECASTERS[k](cfg.params.get(k, {}), cfg.seed).fit(data)
        forecasts[k] = m.predict(te, series)
        # the naïve's path is a real past day (noise included): its peak needs no calibration
        if len(cal_rows) and k != BASELINE:
            peak_cal[k] = peak_calibration(peaks_from_forecast(cal_rows, m.calibration_forecast(cal_rows, series),
                                                               window, threshold))
        timings[k] = int((time.perf_counter() - t0) * 1000)
        fitted[k] = m
        imp = m.importance()
        if imp:
            importance[k] = shares({f: imp.get(f, 0.0) for f in features})

    # daily peaks from every regressor
    peak_frames = {k: calibrate_peaks(peaks_from_forecast(te, fc, window, threshold), peak_cal.get(k, {}), threshold)
                   for k, fc in forecasts.items()}
    short = [k for k in forecasts if k != BASELINE and peak_cal.get(k, {}).get("n", 0) < 6]
    if short:
        warnings.append(f"Too few held-out training days to calibrate the daily peak of {', '.join(short)}: their "
                        "peak is the highest P50 of the window, which runs low (it misses the 5-min noise)")
    test_days = next(iter(peak_frames.values()))
    if test_days.empty:
        warnings.append("No test origin has a complete billing window in its horizon: no peak scores")

    # peak classifier
    clf, clf_days = None, None
    if PEAK in cfg.models:
        t0 = time.perf_counter()
        clf = PeakClassifier(cfg.params.get(PEAK, {}), cfg.seed).fit(day_rows(tr, window, threshold), warnings)
        clf_days = day_rows(te, window, threshold)
        if not clf_days.empty:
            clf_days["prob_exceed"] = clf.predict_proba(clf_days)
            clf_days["reference"] = clf.reference(clf_days)
        timings[PEAK] = int((time.perf_counter() - t0) * 1000)
        fitted[PEAK] = clf
        coef = clf.coefficients()
        if coef:
            importance[PEAK] = shares({f: abs(v) for f, v in coef.items()})

    # scores
    y = te["y"].to_numpy()
    lead = te["horizon_h"].to_numpy()
    in_win = te["in_window"].to_numpy() == 1
    hod = pd.DatetimeIndex(te["target_ts"]).hour.to_numpy()
    naive_mae = float(np.mean(np.abs(y - forecasts[BASELINE]["p50"].to_numpy())))
    metrics, by_lead, by_hod = {}, {}, {}
    n_lead = cfg.horizon_hours
    lead_h = np.ceil(lead).astype(int)
    for k, fc in forecasts.items():
        metrics[k] = score(y, fc, naive_mae, in_win)
        metrics[k].update(peak_scores(peak_frames[k], threshold))
        err = np.abs(y - fc["p50"].to_numpy())
        by_lead[k] = [finite(err[lead_h == h].mean()) if (lead_h == h).any() else None for h in range(1, n_lead + 1)]
        by_hod[k] = [finite(err[hod == h].mean()) if (hod == h).any() else None for h in range(24)]
    clf_reference = None
    if clf is not None and clf_days is not None and not clf_days.empty:
        metrics[PEAK] = {"n": int(len(clf_days)), **exceed_scores(clf_days["prob_exceed"].to_numpy(),
                                                                  clf_days["exceed"].to_numpy())}
        clf_reference = exceed_scores(clf_days["reference"].to_numpy(), clf_days["exceed"].to_numpy())
    best = min(forecasts, key=lambda k: metrics[k]["pinball"] if metrics[k]["pinball"] is not None else 1e18)

    points = []
    for k, fc in forecasts.items():
        p = fc.copy()
        p["model"] = k
        p["actual"] = y
        points.append(p)
    points = pd.concat(points, ignore_index=True)
    peaks = []
    for k, pf in peak_frames.items():
        if not pf.empty:
            peaks.append(pf.assign(model=k))
    if clf_days is not None and not clf_days.empty:
        peaks.append(clf_days[["mp_id", "origin_pos", "origin_ts", "target_date", "lead_h", "prob_exceed", "actual"]]
                     .assign(model=PEAK))
    peaks = pd.concat(peaks, ignore_index=True) if peaks else pd.DataFrame()
    if not peaks.empty:
        peaks["threshold_kw"] = threshold

    n_test_days = int(test_days["target_date"].nunique()) if not test_days.empty else 0
    exceed_days = (int((test_days.drop_duplicates(["mp_id", "target_date"])["actual"] > threshold).sum())
                   if not test_days.empty and "actual" in test_days else 0)
    if n_test_days and exceed_days in (0, n_test_days):
        warnings.append(f"Every test day is {'above' if exceed_days else 'below'} the {threshold:g} kW threshold: "
                        "AUC can't be computed - set a threshold between the typical peaks")
    t0 = next(iter(series.values()))
    charge = (t0.tariff or {}).get("demand_charge_per_kw")
    artifact: dict[str, Any] = {
        "models": fitted, "features": features, "horizon_hours": cfg.horizon_hours, "steps": S,
        "weather_source": sel.weather_source, "feature_groups": sel.feature_groups, "mp_ids": list(series),
        "threshold": threshold, "pv_ratio": {mp: s.pv_ratio for mp, s in series.items()}, "peak_cal": peak_cal,
    }
    summary = {
        "n_readings": int(sum(s.n for s in series.values())), "n_train_rows": int(len(tr)),
        "n_test_origins": int(te.groupby(["mp_id", "origin_pos"]).ngroups), "n_test_days": n_test_days,
        "features": features, "best_model": best, "metrics": metrics,
        "results": {
            "mae_by_lead": by_lead, "mae_by_hour": by_hod, "importance": importance, "timings_ms": timings,
            "threshold": {"kw": threshold, "auto_kw": auto_threshold, "given": bool(sel.peak_threshold_kw),
                          "test_days": n_test_days, "test_days_above": exceed_days},
            "window": list(window), "tariff": {str(mp): s.tariff for mp, s in series.items()},
            "demand_charge_per_kw": charge,
            "pv_ratio": {str(mp): finite(s.pv_ratio) for mp, s in series.items()},
            "split": {str(mp): {"train_to": series[mp].ts(train_end[mp])[0].isoformat(),
                                "test_from": series[mp].ts(train_end[mp] + 1)[0].isoformat(),
                                "test_to": series[mp].ts(series[mp].n - 1)[0].isoformat()} for mp in train_end},
            "nbeats_loss": getattr(fitted.get("nbeats"), "loss_curve", None),
            "classifier": ({"reference": clf_reference, "coefficients": clf.coefficients(),
                            "class_rate": {("workday" if k else "non-workday"): finite(v) for k, v in clf.class_rate.items()},
                            "train_days": clf.n_days} if clf is not None else None),
            "peak_calibration": {k: {a: finite(b) if isinstance(b, float) else b for a, b in v.items()}
                                 for k, v in peak_cal.items()},
            "weather_share": finite(float(te["wx_forecast"].mean())) if "wx_forecast" in te else None,
        },
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return RunResult(artifact, summary, points, peaks, warnings)


def score(y: np.ndarray, fc: pd.DataFrame, naive_mae: float, in_win: np.ndarray) -> dict:
    p10, p50, p90 = (fc[c].to_numpy() for c in ("p10", "p50", "p90"))
    err = y - p50
    pin = np.mean([np.mean(np.maximum(q * (y - p), (q - 1) * (y - p))) for q, p in zip(QUANTILES, (p10, p50, p90))])
    return {
        "n": int(len(y)), "mae": finite(np.mean(np.abs(err))), "rmse": finite(np.sqrt(np.mean(err ** 2))),
        "mape_pct": finite(100 * np.mean(np.abs(err) / np.maximum(np.abs(y), 1.0))),
        "bias": finite(np.mean(p50 - y)), "pinball": finite(pin),
        "coverage_pct": finite(100 * np.mean((y >= p10) & (y <= p90))), "width_kw": finite(np.mean(p90 - p10)),
        "skill_mae_pct": finite(100 * (1 - np.mean(np.abs(err)) / naive_mae)) if naive_mae else None,
        "window_mae": finite(np.mean(np.abs(err[in_win]))) if in_win.any() else None,
    }


def exceed_scores(prob: np.ndarray, hit: np.ndarray) -> dict:
    prob = np.asarray(prob, float)
    hit = np.asarray(hit, int)
    out = {"exceed_brier": finite(np.mean((prob - hit) ** 2))}
    if 0 < hit.sum() < len(hit):
        out["exceed_auc"] = finite(roc_auc_score(hit, prob))
    call = prob >= 0.5
    out["exceed_recall"] = finite(call[hit == 1].mean()) if hit.sum() else None
    out["exceed_precision"] = finite(hit[call].mean()) if call.any() else None
    return out


def peak_scores(pf: pd.DataFrame, threshold: float) -> dict:
    if pf.empty or "actual" not in pf:
        return {}
    pf = pf.dropna(subset=["actual"])
    if pf.empty:
        return {}
    err = pf["p50"].to_numpy() - pf["actual"].to_numpy()
    dt = (pd.to_datetime(pf["peak_ts"]) - pd.to_datetime(pf["actual_ts"])).dt.total_seconds().abs() / 60
    return {"peak_n": int(len(pf)), "peak_mae_kw": finite(np.mean(np.abs(err))), "peak_bias_kw": finite(np.mean(err)),
            "peak_time_mae_min": finite(dt.mean()),
            **exceed_scores(pf["prob_exceed"].to_numpy(), (pf["actual"] > threshold).astype(int).to_numpy())}


# ---------------------------------------------------------------- live forecast


def forecast(engine: Engine, art: dict, mp_id: int, history_hours: int = 48, threshold: Optional[float] = None) -> dict:
    """Forecast the next horizon from the newest reading of a metering point, with every model of the run."""
    if mp_id not in art["mp_ids"]:
        raise ForecastError(f"Metering point {mp_id} is not part of this model (trained on {art['mp_ids']})")
    S = art["steps"]
    meta = next((m for m in F.metering_points(engine) if m["mp_id"] == mp_id), None)
    df = F.demand(engine, mp_id)
    if len(df) < F.HISTORY + 1:
        raise ForecastError(f"Metering point {mp_id} has only {len(df)} readings (needs 7 days)")
    if df["net"].iloc[-F.PER_DAY:].isna().any():
        raise ForecastError("Gaps in the last 24 h of net load: no forecast")
    s = F.Series.build(engine, meta, df, F.calendar(engine), F.tariff(engine, meta["site_id"]))
    s.pv_ratio = art["pv_ratio"].get(mp_id, 0.0)
    origin = s.n - 1
    # live forecasts use the forecast runs whatever the training source was
    rows = F.rows(s, np.array([origin]), S, "forecast", with_target=False)
    T = float(threshold) if threshold else art["threshold"]
    out, peaks = {}, {}
    for k, m in art["models"].items():
        if k == PEAK:
            continue
        fc = m.predict(rows, {mp_id: s})
        out[k] = [{"target_ts": pd.Timestamp(t).isoformat(), "step": int(st), "p10": finite(a), "p50": finite(b),
                   "p90": finite(c)} for t, st, a, b, c in zip(fc["target_ts"], fc["step"], fc["p10"], fc["p50"], fc["p90"])]
        pf = calibrate_peaks(peaks_from_forecast(rows, fc, s.window, T), art.get("peak_cal", {}).get(k, {}), T)
        peaks[k] = [_peak_out(r) for r in pf.to_dict("records")]
    clf = art["models"].get(PEAK)
    if clf is not None:
        days = day_rows(rows, s.window, T, with_target=False)
        if not days.empty:
            days["prob_exceed"] = clf.predict_proba(days)
            days["reference"] = clf.reference(days)
            peaks[PEAK] = [{"target_date": str(r["target_date"]), "lead_h": finite(r["lead_h"]),
                            "prob_exceed": finite(r["prob_exceed"]), "reference": finite(r["reference"])}
                           for r in days.to_dict("records")]
    lo = max(0, origin - history_hours * F.PER_HOUR + 1)
    hist_pos = np.arange(lo, origin + 1)
    recent = s.daily_peaks().tail(14)
    target_dates = sorted(set(rows["target_date"]))
    origin_ts = s.ts(origin)[0]
    return {
        "mp_id": mp_id, "mp_code": meta["mp_code"], "origin_ts": origin_ts.isoformat(),
        "horizon_hours": art["horizon_hours"], "threshold_kw": T, "trained_threshold_kw": art["threshold"],
        "window": list(s.window), "tariff": s.tariff,
        "history": [{"ts": t.isoformat(), "net": finite(a), "gross": finite(b), "gen": finite(c)}
                    for t, a, b, c in zip(s.ts(hist_pos), s.net[hist_pos], s.gross[hist_pos], s.gen[hist_pos])],
        "inputs": [{"ts": pd.Timestamp(t).isoformat(), "temp_fc": finite(a), "ghi_fc": finite(b), "from_forecast": bool(c),
                    "workday": bool(w)} for t, a, b, c, w in zip(rows["target_ts"], rows["temp_fc"], rows["ghi_fc"],
                                                                  rows["wx_forecast"], rows["workday"])],
        "calendar_missing": [str(d) for d in target_dates if d not in s.cal],
        "recent_peaks": [{"date": str(d), "peak": finite(r["peak"]), "peak_ts": pd.Timestamp(r["peak_ts"]).isoformat()}
                         for d, r in recent.iterrows()],
        "forecasts": out, "peaks": peaks,
        "data_age_hours": finite((pd.Timestamp.now(tz=F.TZ) - origin_ts).total_seconds() / 3600),
    }


def _peak_out(r: dict) -> dict:
    return {"target_date": str(r["target_date"]), "lead_h": finite(r["lead_h"]), "p10": finite(r["p10"]),
            "p50": finite(r["p50"]), "p90": finite(r["p90"]), "peak_ts": pd.Timestamp(r["peak_ts"]).isoformat(),
            "prob_exceed": finite(r["prob_exceed"]), "p50_raw": finite(r.get("p50_raw", r["p50"]))}
