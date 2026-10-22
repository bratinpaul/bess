"""One price forecasting run: build the rows, split per EMS in time, fit every chosen model (the seasonal naïve
always - it's the skill reference), backtest them on the same test origins and score them.

Split per EMS: the latest `test_fraction` of its hours is the test period. Training origins only use targets
before it (no leakage); test origins start at the cut-off every `origin_step_h` hours, each forecasting
h = 1..horizon hours ahead.

Scores per model on the test forecasts (P50 is the point forecast; the spike hybrid's mean is scored too):
  MAE, RMSE, sMAPE; pinball loss over P10 / P50 / P90; P10-P90 coverage (target 80 %) and width; skill vs the
  seasonal naïve (1 - MAE / MAE naïve); MAE per horizon and per TOU band; spike hours: MAE, and for a model with a
  spike probability AUC, Brier and recall / precision of its top-5 % riskiest hours; spread capture: per origin,
  charge in the 3 cheapest and discharge in the 3 dearest forecast hours of the next 24 h - the realised spread as a
  share of the perfect-foresight spread (what the arbitrage optimizer would earn).
"""
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sqlalchemy.engine import Engine

from core.metrics import finite, shares
from usecases.price_forecast import features as F
from usecases.price_forecast.models import BASELINE, FORECASTERS, QUANTILES, ForecastError, TrainData

SPREAD_HOURS = 3


@dataclass
class RunConfig:
    selection: F.Selection
    models: list[str]
    params: dict[str, dict]
    horizon: int = 48
    test_fraction: float = 0.2
    origin_step_h: int = 6
    train_origin_step_h: int = 2
    seed: int = 42


@dataclass
class RunResult:
    artifact: dict
    summary: dict
    points: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def load_series(engine: Engine, sel: F.Selection, warnings: list[str], horizon: int) -> tuple[dict, dict]:
    series, bands = {}, {}
    for ems in sel.ems_ids:
        df = F.hourly(engine, ems, sel.date_from, sel.date_to)
        if len(df) < F.HISTORY_H + horizon + 48:
            warnings.append(f"EMS {ems}: only {len(df)} hours of prices - left out (needs {F.HISTORY_H + horizon + 48})")
            continue
        if df["price"].isna().any():
            # gaps longer than the interpolation limit: keep the longest stretch of continuous hours
            run = df["price"].notna()
            seg = (run != run.shift()).cumsum()[run]
            longest = seg.value_counts().idxmax()
            kept = df.loc[seg.index[seg == longest]]
            warnings.append(f"EMS {ems}: {int(df['price'].isna().sum())} hours without prices; using its longest "
                            f"continuous stretch {kept.index[0]:%d %b %H:%M} – {kept.index[-1]:%d %b %H:%M} ({len(kept)} h)")
            df = kept
            if len(df) < F.HISTORY_H + horizon + 48:
                warnings.append(f"EMS {ems}: that stretch is too short - left out")
                continue
        elif df["gap"].sum():
            warnings.append(f"EMS {ems}: {int(df['gap'].sum())} hours without a price were interpolated")
        b = F.tariff(engine, ems)
        if not b:
            raise ForecastError("No TOU bands in battery_master.ems_tariff_period")
        bands[ems] = b
        series[ems] = F.Series.of(ems, df, b)
    if not series:
        raise ForecastError("No EMS with enough price history in the selection")
    return series, bands


def _fill(rows: pd.DataFrame) -> pd.DataFrame:
    if "band_ref" in rows:
        rows["band_ref"] = rows["band_ref"].fillna(rows["band_recent_mean"])
    return rows


def train(engine: Engine, cfg: RunConfig) -> RunResult:
    started = time.perf_counter()
    sel = cfg.selection
    H = cfg.horizon
    warnings: list[str] = []
    series, bands = load_series(engine, sel, warnings, H)

    train_parts, test_parts, train_end = [], [], {}
    for ems, s in series.items():
        n = len(s.y)
        cut = int(round(n * (1 - cfg.test_fraction)))
        train_end[ems] = cut - 1
        tr_o = np.arange(F.HISTORY_H - 1, cut - H, cfg.train_origin_step_h)
        te_o = np.arange(cut - 1, n - H, cfg.origin_step_h)
        if len(tr_o) < 24 or len(te_o) < 1:
            warnings.append(f"EMS {ems}: too short for a {H} h horizon with this test share - left out")
            continue
        train_parts.append(F.rows(s, tr_o, H, sel.spike_threshold))
        test_parts.append(F.rows(s, te_o, H, sel.spike_threshold))
    if not train_parts:
        raise ForecastError("No EMS has enough history for training and testing")
    tr = _fill(pd.concat(train_parts, ignore_index=True))
    te = _fill(pd.concat(test_parts, ignore_index=True)).sort_values(["ems_id", "origin_pos", "horizon"]).reset_index(drop=True)
    features = [f for f in sel.features if f in tr]
    data = TrainData(tr, series, features, H, sel.spike_threshold, train_end, cfg.seed, warnings)
    if int(tr["spike"].sum()) == 0:
        warnings.append(f"No hour in the training rows has a 5-min price above {sel.spike_threshold:g} $/MWh")

    keys = [BASELINE] + [k for k in cfg.models if k != BASELINE]
    fitted, forecasts, timings, importance = {}, {}, {}, {}
    for k in keys:
        t0 = time.perf_counter()
        m = FORECASTERS[k](cfg.params.get(k, {}), cfg.seed).fit(data)
        forecasts[k] = m.predict(te, series)
        timings[k] = int((time.perf_counter() - t0) * 1000)
        fitted[k] = m
        imp = m.importance()
        if imp:
            importance[k] = shares({f: imp.get(f, 0.0) for f in features})

    # scores
    y = te["y"].to_numpy()
    spike = te["spike"].to_numpy()
    _, _, codes = F.band_lookup(next(iter(bands.values())))
    band = te["band_idx"].to_numpy() if "band_idx" in te else np.full(len(te), -1)
    naive_mae = float(np.mean(np.abs(y - forecasts[BASELINE]["p50"].to_numpy())))
    metrics, by_h, by_band = {}, {}, {}
    for k, fc in forecasts.items():
        metrics[k] = score(y, spike, fc, te, naive_mae)
        err = np.abs(y - fc["p50"].to_numpy())
        by_h[k] = [finite(err[te["horizon"].to_numpy() == h].mean()) for h in range(1, H + 1)]
        by_band[k] = {codes[b]: finite(err[band == b].mean()) for b in range(len(codes)) if (band == b).any()}
        if "PEAK" in codes:
            metrics[k]["peak_mae"] = by_band[k].get("PEAK")
    best = min(metrics, key=lambda k: metrics[k]["pinball"] if metrics[k]["pinball"] is not None else 1e9)
    # reference for the spike classifier: the training spike rate per hour of day
    spike_reference = None
    hybrid = fitted.get("spike_hybrid")
    if hybrid is not None and getattr(hybrid, "hour_rate", None) and 0 < spike.sum() < len(spike):
        ref = te["hour"].map(hybrid.hour_rate).fillna(0).to_numpy()
        spike_reference = {"auc": finite(roc_auc_score(spike, ref)), "brier": finite(np.mean((ref - spike) ** 2)),
                           "hour_rate": {int(h): finite(v) for h, v in hybrid.hour_rate.items()}}

    points = []
    for k, fc in forecasts.items():
        p = fc.copy()
        p["model"] = k
        p["actual"] = y
        points.append(p)
    points = pd.concat(points, ignore_index=True)

    n_spike_hours = int(sum((s.ymax5 > sel.spike_threshold).sum() for s in series.values()))
    if n_spike_hours and n_spike_hours / sum(len(s.y) for s in series.values()) < 0.01:
        warnings.append(f"Spikes are rare ({n_spike_hours} hours over all EMS, "
                        f"{100 * n_spike_hours / sum(len(s.y) for s in series.values()):.2f} %): spike probability is "
                        "low everywhere and mostly says *when* spikes can happen (the TOU band), not *which* hour.")
    warnings.append("No exogenous drivers (load / renewable / weather / fuel) are in the data: the models learn the TOU "
                    "pattern and recent history only - add the external feeds for real forecasting skill.")

    artifact: dict[str, Any] = {
        "models": fitted, "features": features, "horizon": H, "spike_threshold": sel.spike_threshold,
        "feature_groups": sel.feature_groups, "bands": bands, "ems_ids": list(series), "codes": codes,
    }
    summary = {
        "n_hours": int(sum(len(s.y) for s in series.values())), "n_train_rows": int(len(tr)),
        "n_test_origins": int(te.groupby(["ems_id", "origin_pos"]).ngroups), "n_spikes": n_spike_hours,
        "features": features, "best_model": best, "metrics": metrics,
        "results": {
            "mae_by_horizon": by_h, "mae_by_band": by_band, "importance": importance, "timings_ms": timings,
            "bands": {str(e): b for e, b in bands.items()}, "codes": codes,
            "split": {str(e): {"train_to": series[e].ts[train_end[e]].isoformat(),
                               "test_from": series[e].ts[train_end[e] + 1].isoformat(),
                               "test_to": series[e].ts[-1].isoformat()} for e in train_end if e in series},
            "nbeats_loss": getattr(fitted.get("nbeats"), "loss_curve", None),
            "train_spike_rows": int(tr["spike"].sum()), "test_spike_rows": int(te["spike"].sum()),
            "spike_reference": spike_reference,
        },
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return RunResult(artifact, summary, points, warnings)


def score(y: np.ndarray, spike: np.ndarray, fc: pd.DataFrame, rows: pd.DataFrame, naive_mae: float) -> dict:
    p10, p50, p90 = (fc[c].to_numpy() for c in ("p10", "p50", "p90"))
    err = y - p50
    pin = np.mean([np.mean(np.maximum(q * (y - p), (q - 1) * (y - p))) for q, p in zip(QUANTILES, (p10, p50, p90))])
    out = {
        "n": int(len(y)), "mae": finite(np.mean(np.abs(err))), "rmse": finite(np.sqrt(np.mean(err ** 2))),
        "smape_pct": finite(100 * np.mean(2 * np.abs(err) / np.maximum(np.abs(y) + np.abs(p50), 1e-6))),
        "bias": finite(np.mean(p50 - y)), "pinball": finite(pin),
        "coverage_pct": finite(100 * np.mean((y >= p10) & (y <= p90))), "width_mwh": finite(np.mean(p90 - p10)),
        "skill_mae_pct": finite(100 * (1 - np.mean(np.abs(err)) / naive_mae)) if naive_mae else None,
        "spike_hour_mae": finite(np.mean(np.abs(err[spike == 1]))) if spike.any() else None,
        "spread_capture_pct": spread_capture(rows, y, p50),
    }
    mean = fc["mean"].to_numpy()
    if not np.allclose(mean, p50):
        out["mean_mae"] = finite(np.mean(np.abs(y - mean)))
    prob = fc["spike_prob"].to_numpy()
    if np.isfinite(prob).all():
        out["spike_brier"] = finite(np.mean((prob - spike) ** 2))
        if 0 < spike.sum() < len(spike):
            out["spike_auc"] = finite(roc_auc_score(spike, prob))
            top = prob >= np.quantile(prob, 0.95)
            out["spike_recall"] = finite(spike[top].sum() / spike.sum())
            out["spike_precision"] = finite(spike[top].mean())
    return out


def spread_capture(rows: pd.DataFrame, y: np.ndarray, p50: np.ndarray) -> float | None:
    """Realised / perfect-foresight spread of charging in the k cheapest and discharging in the k dearest forecast
    hours of each origin's next 24 h."""
    got, best = 0.0, 0.0
    df = pd.DataFrame({"g": rows["ems_id"].astype(str) + "|" + rows["origin_pos"].astype(str),
                       "h": rows["horizon"].to_numpy(), "y": y, "f": p50})
    for _, g in df[df["h"] <= 24].groupby("g"):
        if len(g) < 2 * SPREAD_HOURS:
            continue
        by_f = g.sort_values("f")
        by_y = g.sort_values("y")
        got += by_f["y"].iloc[-SPREAD_HOURS:].mean() - by_f["y"].iloc[:SPREAD_HOURS].mean()
        best += by_y["y"].iloc[-SPREAD_HOURS:].mean() - by_y["y"].iloc[:SPREAD_HOURS].mean()
    return finite(100 * got / best) if best > 0 else None


# ---------------------------------------------------------------- live forecast


def forecast(engine: Engine, art: dict, ems_id: int, model_keys: list[str], history_hours: int = 72) -> dict:
    """Forecast the next `horizon` hours from the newest complete hour of an EMS's prices, with every model."""
    if ems_id not in art["ems_ids"]:
        raise ForecastError(f"EMS {ems_id} is not part of this model (trained on EMS {', '.join(map(str, art['ems_ids']))})")
    H = art["horizon"]
    df = F.hourly(engine, ems_id)
    if len(df) < F.HISTORY_H + 1:
        raise ForecastError(f"EMS {ems_id} has only {len(df)} hours of prices")
    # the newest hour may be incomplete (fewer than 12 readings): forecast from the hour before it
    if df["n"].iloc[-1] < 12 and len(df) > F.HISTORY_H + 1:
        df = df.iloc[:-1]
    if df["price"].iloc[-F.HISTORY_H:].isna().any():
        raise ForecastError(f"EMS {ems_id} has gaps in its last {F.HISTORY_H} hours of prices: no forecast")
    bands = F.tariff(engine, ems_id) or art["bands"][ems_id]
    s = F.Series.of(ems_id, df, bands)
    origin = len(s.y) - 1
    rows = _fill(F.rows(s, np.array([origin]), H, art["spike_threshold"], with_target=False))
    out = {}
    for k in model_keys:
        m = art["models"].get(k)
        if m is None:
            continue
        fc = m.predict(rows, {ems_id: s})
        out[k] = [{"target_ts": pd.Timestamp(t).isoformat(), "horizon": int(h), "p10": finite(a), "p50": finite(b),
                   "p90": finite(c), "mean": finite(d), "spike_prob": finite(e) if e == e else None}
                  for t, h, a, b, c, d, e in zip(fc["target_ts"], fc["horizon"], fc["p10"], fc["p50"], fc["p90"],
                                                 fc["mean"], fc["spike_prob"])]
    hist = df.iloc[-history_hours:]
    origin_ts = s.ts[origin]
    return {
        "ems_id": ems_id, "origin_ts": origin_ts.isoformat(), "horizon": H,
        "history": [{"ts": t.isoformat(), "price": finite(p), "price_max5": finite(m)}
                    for t, p, m in zip(hist.index, hist["price"], hist["price_max5"])],
        "history_5min": F.five_min(engine, ems_id, hist.index[0], origin_ts + pd.Timedelta(hours=1)),
        "forecasts": out, "bands": bands,
    }
