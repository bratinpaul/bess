"""Build and apply multivariate anomaly models.

train(): one battery system, one window.
    1. features      joined BMS / PCS / HVAC / EMS rows, derived signals, rule flags (frozen / missing sensors)
    2. split         chronological: the first (1 − eval_fraction) of the window trains, the rest evaluates
    3. clean rows    training rows minus alarm_event intervals (± pad), any alarm_level > 0, PCS FAULT, sensor-rule
                     hits and the commissioning period - "known good"; alarms are labels for evaluation only
    4. residuals     expected ΔV / cell-temperature rise / IGBT rise fitted on the clean rows
    5. inputs        selected feature groups; frozen / missing values masked and imputed (clean-train median per
                     regime); regime + SOC band one-hot (strategy 'feature') or one model set per regime ('separate')
    6. models        each detector fitted on the standardised clean rows (scaler fitted on train only)
    7. thresholds    raw score at the threshold percentile of the clean training scores -> score / threshold, so
                     1.0 is the limit for every model and regime; optional 'best_f1' moves the limit to the value that
                     best separates the alarm periods of the training window (never the evaluation window)
    8. flags         rolling-mean smoothing, then flag only after `debounce` consecutive intervals above the limit;
                     is_anomaly = model flag OR a sensor rule
    9. evaluation    on the evaluation window vs alarm_event intervals: precision / recall / F1, ROC AUC, alarm-event
                     recall, episode precision, flag rate - per model
   10. attribution   top contributing features of the primary model for every interval

score_window(): applies a built model (no refitting) to another window; drift warnings (SOH, ambient).
"""
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy.engine import Engine

from core.base import UseCaseError
from usecases.mv_anomaly import features as F
from usecases.mv_anomaly import models as M

STEP = pd.Timedelta(minutes=5)
POOLED = "all"


class MvAnomalyError(UseCaseError):
    code = "MV_ANOMALY_INPUT_REJECTED"


@dataclass
class RunConfig:
    system_id: int
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    models: list[str] = field(default_factory=lambda: ["pca", "iforest", "robust_cov", "autoencoder"])
    primary: str = "pca"
    model_params: dict = field(default_factory=dict)
    feature_groups: list[str] = field(default_factory=lambda: list(F.GROUPS))
    regime_strategy: str = "feature"  # feature | separate
    min_regime_rows: int = 300
    eval_fraction: float = 0.3
    threshold_pct: float = 99.5
    threshold_mode: str = "percentile"  # percentile | best_f1
    smooth_window: int = 3
    debounce: int = 3
    frozen_intervals: int = 6
    alarm_pad_min: float = 30.0
    commissioning_days: int = 7
    exclude_alarm_level: bool = True
    top_k: int = 3
    seed: int = 42


# --- helpers ---------------------------------------------------------------------------------------------------------

def _debounce(above: np.ndarray, n: int) -> np.ndarray:
    """True for every interval of a run of ≥ n consecutive True values."""
    out = np.zeros(len(above), dtype=bool)
    if n <= 1:
        return above.copy()
    i, a = 0, above
    while i < len(a):
        if a[i]:
            j = i
            while j < len(a) and a[j]:
                j += 1
            if j - i >= n:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


def _smooth(x: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(x).rolling(max(1, window), min_periods=1).mean().to_numpy()


def _contiguous(ts: pd.Series, k: int) -> np.ndarray:
    """Rows whose previous k−1 rows are the consecutive 5-min intervals (a gap-free window)."""
    if k <= 1:
        return np.ones(len(ts), dtype=bool)
    span = ts - ts.shift(k - 1)
    return (span == STEP * (k - 1)).to_numpy()


def _prf(flag: np.ndarray, label: np.ndarray) -> dict:
    tp = int((flag & label).sum())
    fp = int((flag & ~label).sum())
    fn = int((~flag & label).sum())
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def _runs(mask: np.ndarray, max_gap: int = 1) -> list[tuple[int, int]]:
    """[start, end] index pairs of flagged runs, merging gaps of ≤ max_gap intervals."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    out, s, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > max_gap + 1:
            out.append((s, prev))
            s = i
        prev = i
    out.append((s, prev))
    return out


# --- feature matrix ----------------------------------------------------------------------------------------------------

def _feature_columns(cfg_groups: list[str]) -> list[str]:
    return [k for k, (_, g) in F.FEATURES.items() if g in cfg_groups]


def _mask_rules(df: pd.DataFrame) -> pd.DataFrame:
    """Frozen / missing sensor values are not trusted as model inputs."""
    out = df.copy()
    for i, flags in zip(out.index, out["rule_flags"]):
        for f in flags:
            col = f.split(":", 1)[1]
            if col in out.columns:
                out.at[i, col] = np.nan
    return out


def _context(df: pd.DataFrame) -> pd.DataFrame:
    cols = {}
    for r in F.REGIMES + ["Other"]:
        cols[f"ctx_regime_{r}"] = (df["regime"] == r).astype(float)
    for b in F.SOC_BAND_LABELS:
        cols[f"ctx_soc_{b}"] = (df["soc_band"] == b).astype(float)
    return pd.DataFrame(cols, index=df.index)


def _label(col: str) -> str:
    if col.startswith("ctx_regime_"):
        return F.CONTEXT_LABELS["regime"]
    if col.startswith("ctx_soc_"):
        return F.CONTEXT_LABELS["soc_band"]
    return F.FEATURES.get(col, (col,))[0]


class Preprocessor:
    """Imputation medians (per regime, fallback global) + optional context one-hot + per-group StandardScaler."""

    def __init__(self, columns: list[str], strategy: str):
        self.columns = columns
        self.strategy = strategy

    def fit(self, clean: pd.DataFrame, groups: pd.Series) -> "Preprocessor":
        self.global_med = clean[self.columns].median()
        self.regime_med = {r: g[self.columns].median() for r, g in clean.groupby("regime")}
        x = self._raw(clean)
        self.inputs = list(x.columns)
        self.scalers = {}
        for g in groups.unique():
            sel = (groups == g).to_numpy()
            sc = StandardScaler().fit(x[sel].to_numpy(float))
            sc.scale_[sc.scale_ < 1e-9] = 1.0
            self.scalers[g] = sc
        return self

    def _raw(self, df: pd.DataFrame) -> pd.DataFrame:
        x = df[self.columns].copy()
        for r, med in self.regime_med.items():
            sel = df["regime"] == r
            if sel.any():
                x.loc[sel] = x.loc[sel].fillna(med)
        x = x.fillna(self.global_med).fillna(0.0)
        if self.strategy == "feature":
            x = pd.concat([x, _context(df)], axis=1)
        return x

    def transform(self, df: pd.DataFrame, groups: np.ndarray) -> np.ndarray:
        x = self._raw(df).to_numpy(float)
        out = np.empty_like(x)
        for g in np.unique(groups):
            sel = groups == g
            sc = self.scalers[g] if g in self.scalers else self.scalers[POOLED]
            out[sel] = sc.transform(x[sel])
        return out


def _groups_for(df: pd.DataFrame, strategy: str, regime_models: list[str]) -> np.ndarray:
    if strategy != "separate":
        return np.full(len(df), POOLED, dtype=object)
    return np.where(df["regime"].isin(regime_models), df["regime"], POOLED).astype(object)


# --- scoring with fitted detectors -------------------------------------------------------------------------------------

def _score_all(art: dict, df: pd.DataFrame) -> dict:
    """Raw → normalised scores and contributions of every model for the rows of df (in time order)."""
    pre: Preprocessor = art["pre"]
    groups = _groups_for(df, art["cfg"]["regime_strategy"], art["regime_models"])
    x = pre.transform(df, groups)
    out = {}
    for key, by_group in art["detectors"].items():
        norm = np.full(len(df), np.nan)
        contrib = np.zeros((len(df), x.shape[1]))
        parts: dict[str, np.ndarray] = {}
        for g, det in by_group.items():
            sel = groups == g
            if not sel.any():
                continue
            valid = _contiguous(df["ts"], det.window)
            raw, c = det.score(x, valid)
            thr = art["thresholds"][key][g]
            norm[sel] = raw[sel] / thr
            contrib[sel] = c[sel]
            for name, v in getattr(det, "last_parts", {}).items():
                parts.setdefault(name, np.full(len(df), np.nan))[sel] = v[sel]
        out[key] = {"norm": norm, "contrib": contrib, "parts": parts}
    return out


def _flags(norm: np.ndarray, cfg: dict, limit: float) -> tuple[np.ndarray, np.ndarray]:
    smooth = _smooth(np.nan_to_num(norm, nan=0.0), cfg["smooth_window"])
    smooth[np.isnan(norm)] = np.nan
    return smooth, _debounce(np.nan_to_num(smooth, nan=0.0) >= limit, cfg["debounce"])


def _top(contrib: np.ndarray, inputs: list[str], k: int) -> list[list[dict]]:
    """Top-k signal features per row, shares renormalised over the signals: the regime / SOC-band context columns
    condition the model but are not something an operator can act on, so they are left out of the attribution."""
    sig = [i for i, c in enumerate(inputs) if not c.startswith("ctx_")]
    names = [inputs[i] for i in sig]
    labels = [_label(c) for c in names]
    c = contrib[:, sig]
    tot = c.sum(axis=1, keepdims=True)
    c = np.divide(c, tot, out=np.zeros_like(c), where=tot > 0)
    order = np.argsort(-c, axis=1)[:, :k]
    out = []
    for row, idx in zip(c, order):
        out.append([{"feature": names[j], "label": labels[j], "share": round(float(row[j]), 3)}
                    for j in idx if row[j] > 0.02])
    return out


def _rows(df: pd.DataFrame, art: dict, scored: dict, split: np.ndarray) -> pd.DataFrame:
    cfg = art["cfg"]
    primary = cfg["primary"]
    smooth_p, flag_p = _flags(scored[primary]["norm"], cfg, art["limits"][primary])
    above = np.zeros(len(df), dtype=int)
    model_scores = []
    smooth_by = {}
    for key in scored:
        s, _ = _flags(scored[key]["norm"], cfg, art["limits"][key])
        smooth_by[key] = s
        above += (np.nan_to_num(s, nan=0.0) >= art["limits"][key]).astype(int)
    for i in range(len(df)):
        d = {k: (None if np.isnan(v["norm"][i]) else round(float(v["norm"][i]), 4)) for k, v in scored.items()}
        for k, v in scored.items():
            for pn, pv in v["parts"].items():
                d[pn] = None if np.isnan(pv[i]) else round(float(pv[i]), 4)
        model_scores.append(d)
    rules = df["rule_flags"].tolist()
    return pd.DataFrame({
        "ts": df["ts"].to_numpy(), "split": split, "regime": df["regime"].to_numpy(),
        "anomaly_score": scored[primary]["norm"], "score_smooth": smooth_p, "model_flag": flag_p,
        "is_anomaly": flag_p | np.array([bool(r) for r in rules]), "rule_flags": rules,
        "model_scores": model_scores, "models_flagging": above,
        "top_contributors": _top(scored[primary]["contrib"], art["pre"].inputs, cfg["top_k"]),
    })


# --- evaluation ------------------------------------------------------------------------------------------------------

def _evaluate(df: pd.DataFrame, scored: dict, art: dict, sel: np.ndarray, al: pd.DataFrame) -> dict:
    cfg = art["cfg"]
    label = F.alarm_mask(df["ts"], al, 0.0)[sel]
    ts = df["ts"][sel].reset_index(drop=True)
    t0, t1 = ts.min(), ts.max() + STEP
    events = al[(al["start_ts"] < t1) & (al["end_ts"] > t0)]
    pad = pd.Timedelta(minutes=cfg["alarm_pad_min"])
    out = {}
    for key, v in scored.items():
        smooth, flag = _flags(v["norm"], cfg, art["limits"][key])
        smooth, flag = smooth[sel], flag[sel]
        m = _prf(flag, label)
        ok = ~np.isnan(smooth)
        m["auc"] = float(roc_auc_score(label[ok], smooth[ok])) if ok.any() and 0 < label[ok].sum() < ok.sum() else None
        hit = 0
        tsv = pd.DatetimeIndex(ts).asi8
        ev_s, ev_e = pd.DatetimeIndex(events["start_ts"]).asi8, pd.DatetimeIndex(events["end_ts"]).asi8
        pad_ns, step_ns = pad.value, STEP.value
        for s, e in zip(ev_s, ev_e):
            w = (tsv >= s - pad_ns) & (tsv < e + pad_ns)
            hit += bool(flag[w].any())
        m["alarm_events"] = int(len(events))
        m["event_recall"] = hit / len(events) if len(events) else None
        eps = _runs(flag)
        explained = 0
        for a, b in eps:
            s_, e_ = tsv[a] - pad_ns, tsv[b] + step_ns + pad_ns
            explained += bool(((ev_s < e_) & (ev_e > s_)).any())
        m["episodes"] = len(eps)
        m["episode_precision"] = explained / len(eps) if eps else None
        m["flag_rate"] = float(flag.mean()) if len(flag) else None
        m["label_rate"] = float(label.mean()) if len(label) else None
        out[key] = m
    return out


def _tune_limit(norm: np.ndarray, cfg: dict, label: np.ndarray) -> Optional[float]:
    """Limit (on the normalised, smoothed score) that maximises F1 against the alarm intervals."""
    if label.sum() == 0 or label.all():
        return None
    smooth = _smooth(np.nan_to_num(norm, nan=0.0), cfg["smooth_window"])
    cands = np.unique(np.quantile(smooth, np.linspace(0.80, 0.999, 60)))
    best, best_f1 = None, -1.0
    for c in cands:
        f1 = _prf(_debounce(smooth >= c, cfg["debounce"]), label)["f1"] or 0.0
        if f1 > best_f1:
            best, best_f1 = float(c), f1
    return best


# --- train -----------------------------------------------------------------------------------------------------------

def prepare(engine: Engine, cfg: RunConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    w = F.Window(cfg.system_id, cfg.date_from, cfg.date_to)
    raw = F.load_frame(engine, w)
    if raw.empty:
        raise MvAnomalyError("No BMS telemetry for this system in the window")
    df = F.derive(raw)
    df["rule_flags"] = F.rule_flags(df, cfg.frozen_intervals)
    cut = int(round(len(df) * (1 - cfg.eval_fraction)))
    if cut < 200 or len(df) - cut < 50:
        raise MvAnomalyError(f"The window has {len(df)} intervals - too few to train and evaluate "
                             "(need ≥ 200 training and ≥ 50 evaluation intervals)")
    df["split"] = np.where(np.arange(len(df)) < cut, "train", "eval")
    al = F.alarms(engine, w)
    reasons = F.exclusions(df, al, cfg.alarm_pad_min, F.commissioning(engine, cfg.system_id), cfg.commissioning_days)
    if not cfg.exclude_alarm_level:
        reasons.pop("alarm_level")
    train = df["split"].eq("train").to_numpy()
    any_excl = np.zeros(len(df), dtype=bool)
    for m in reasons.values():
        any_excl |= m
    df["clean"] = train & ~any_excl
    info = {
        "rows": int(len(df)), "train_rows": int(train.sum()), "eval_rows": int((~train).sum()),
        "clean_train_rows": int(df["clean"].sum()),
        "excluded": {k: int((m & train).sum()) for k, m in reasons.items()},
        "eval_from": df.loc[cut, "ts"], "regimes": df.loc[df["clean"], "regime"].value_counts().to_dict(),
        "alarm_events": {"train": int((al["start_ts"] < df.loc[cut, "ts"]).sum()),
                         "eval": int((al["start_ts"] >= df.loc[cut, "ts"]).sum())},
        "rule_rows": int(df["rule_flags"].map(bool).sum()),
        "subsystems": {k: bool(df[c].notna().any()) for k, c in
                       (("pcs", "igbt_temp_c"), ("hvac", "hvac_power_kw"), ("ems", "p_setpoint_kw"))},
    }
    return df, al, info


def train(engine: Engine, cfg: RunConfig) -> tuple[dict, dict, pd.DataFrame, list[str]]:
    started = time.perf_counter()
    if cfg.primary not in cfg.models:
        raise MvAnomalyError("The primary model must be one of the selected models")
    df, al, info = prepare(engine, cfg)
    warnings: list[str] = []
    clean = df["clean"].to_numpy()
    if clean.sum() < 200:
        raise MvAnomalyError(f"Only {int(clean.sum())} clean training intervals after exclusions - widen the window")
    for name, present in info["subsystems"].items():
        if not present:
            warnings.append(f"No {name.upper()} telemetry for this system - its features are left out")

    residuals = F.fit_residuals(df[clean])
    df = F.apply_residuals(df, residuals)
    masked = _mask_rules(df)

    columns = _feature_columns(cfg.feature_groups)
    keep = []
    for c in columns:
        v = masked.loc[clean, c]
        if v.notna().mean() < 0.05:
            warnings.append(f"Feature '{F.FEATURES[c][0]}' has no data in the clean training rows - left out")
        elif v.std(skipna=True) < 1e-9:
            warnings.append(f"Feature '{F.FEATURES[c][0]}' is constant in the clean training rows - left out")
        else:
            keep.append(c)
    if len(keep) < 3:
        raise MvAnomalyError("Fewer than 3 usable features - select more feature groups")

    counts = masked.loc[clean, "regime"].value_counts()
    regime_models = [r for r, n in counts.items() if n >= cfg.min_regime_rows] if cfg.regime_strategy == "separate" else []
    if cfg.regime_strategy == "separate":
        thin = [r for r, n in counts.items() if n < cfg.min_regime_rows]
        if thin:
            warnings.append(f"Regime(s) {', '.join(thin)} have < {cfg.min_regime_rows} clean rows - scored by the "
                            "pooled model")
    groups = _groups_for(masked, cfg.regime_strategy, regime_models)
    pre = Preprocessor(keep, cfg.regime_strategy).fit(masked[clean], pd.Series(groups[clean]))
    # every group also needs a scaler: the pooled scaler is fitted on all clean rows
    if POOLED not in pre.scalers:
        sc = StandardScaler().fit(pre._raw(masked[clean]).to_numpy(float))
        sc.scale_[sc.scale_ < 1e-9] = 1.0
        pre.scalers[POOLED] = sc
    x = pre.transform(masked, groups)

    detectors: dict = {}
    thresholds: dict = {}
    fit_groups = sorted(set(groups[clean]) | {POOLED})
    for key in cfg.models:
        detectors[key], thresholds[key] = {}, {}
        for g in fit_groups:
            rows = clean & ((groups == g) if g != POOLED or cfg.regime_strategy != "separate" else True)
            if g != POOLED and rows.sum() < 50:
                continue
            det = M.make(key, cfg.model_params.get(key, {}), cfg.seed)
            valid = _contiguous(masked["ts"], det.window)
            if det.window > 1:
                det.fit_rows(x, rows, valid)
            else:
                det.fit(x[rows])
            raw, _ = det.score(x, valid)
            fit_scores = raw[rows & ~np.isnan(raw)]
            thr = float(np.percentile(fit_scores, cfg.threshold_pct)) if len(fit_scores) else 1.0
            detectors[key][g] = det
            thresholds[key][g] = thr if thr > 0 else 1e-9

    art = {"cfg": asdict(cfg), "pre": pre, "residuals": residuals, "detectors": detectors, "thresholds": thresholds,
           "regime_models": regime_models, "limits": {k: 1.0 for k in cfg.models},
           "train_stats": {"soh_mean": float(df.loc[clean, "soh_pct"].mean()) if df["soh_pct"].notna().any() else None,
                           "ambient_mean": float(df.loc[clean, "ambient_temp_c"].mean())
                           if df["ambient_temp_c"].notna().any() else None,
                           "train_to": str(info["eval_from"])}}
    scored = _score_all(art, masked)

    if cfg.threshold_mode == "best_f1":
        train_sel = df["split"].eq("train").to_numpy()
        label = F.alarm_mask(df["ts"], al, 0.0)[train_sel]
        for key in cfg.models:
            lim = _tune_limit(scored[key]["norm"][train_sel], asdict(cfg), label)
            if lim is None:
                warnings.append(f"{M.MODEL_LABELS[key]}: no alarm periods in the training window to tune on - "
                                "kept the percentile limit")
            else:
                art["limits"][key] = lim

    eval_sel = df["split"].eq("eval").to_numpy()
    metrics = _evaluate(df, scored, art, eval_sel, al)
    if info["alarm_events"]["eval"] == 0:
        warnings.append("No alarm events in the evaluation window - precision / recall can't be measured")

    rows = _rows(masked, art, scored, df["split"].to_numpy())
    flagged = rows["model_flag"].to_numpy()
    summary = {**{k: v for k, v in info.items() if k != "eval_from"},
               "eval_from": info["eval_from"].isoformat(), "inputs": len(pre.inputs),
               "flagged_intervals": int(rows["is_anomaly"].sum()), "model_flag_intervals": int(flagged.sum()),
               "episodes": len(_runs(flagged)), "regime_models": regime_models or [POOLED],
               "duration_ms": int((time.perf_counter() - started) * 1000)}
    art["features"] = keep
    return art, {"summary": summary, "metrics": metrics, "thresholds": thresholds, "limits": art["limits"],
                 "features": pre.inputs, "eval_from": info["eval_from"]}, rows, warnings


# --- apply a built model -------------------------------------------------------------------------------------------

def score_window(engine: Engine, art: dict, w: F.Window, split: str = "score") -> tuple[pd.DataFrame, dict, list[str]]:
    cfg = art["cfg"]
    lookback = max(d.window for by_g in art["detectors"].values() for d in by_g.values()) + cfg["smooth_window"]
    raw = F.load_frame(engine, w, lookback_intervals=lookback)
    if raw.empty or not raw["in_window"].any():
        raise MvAnomalyError("No BMS telemetry for this system in the window")
    df = F.derive(raw)
    df["rule_flags"] = F.rule_flags(df, cfg["frozen_intervals"])
    df = F.apply_residuals(df, art["residuals"])
    masked = _mask_rules(df)
    scored = _score_all(art, masked)
    rows = _rows(masked, art, scored, np.full(len(df), split, dtype=object))
    inw = df["in_window"].to_numpy()
    rows = rows[inw].reset_index(drop=True)
    warnings = []
    ts_ = art.get("train_stats", {})
    win = df[inw]
    if ts_.get("soh_mean") is not None and win["soh_pct"].notna().any():
        d = float(win["soh_pct"].mean()) - ts_["soh_mean"]
        if abs(d) >= 1.0:
            warnings.append(f"SOH moved {d:+.2f} pts since the training window - re-baseline (retrain) the model")
    if ts_.get("ambient_mean") is not None and win["ambient_temp_c"].notna().any():
        d = float(win["ambient_temp_c"].mean()) - ts_["ambient_mean"]
        if abs(d) >= 5.0:
            warnings.append(f"Ambient is {d:+.1f} °C vs the training window - seasonal thermal drift may raise false "
                            "positives; retrain on recent data")
    al = F.alarms(engine, w)
    summary = {"rows": int(len(rows)), "flagged_intervals": int(rows["is_anomaly"].sum()),
               "model_flag_intervals": int(rows["model_flag"].sum()), "episodes": len(_runs(rows["model_flag"].to_numpy())),
               "rule_rows": int(rows["rule_flags"].map(bool).sum()), "alarm_events": int(len(al))}
    if len(al) and len(rows):
        label = F.alarm_mask(rows["ts"], al, 0.0)
        summary["vs_alarms"] = _prf(rows["model_flag"].to_numpy(), label)
    return rows, summary, warnings


def episodes(rows: pd.DataFrame, al: pd.DataFrame, pad_min: float) -> list[dict]:
    """Contiguous flagged stretches with their peak score, aggregated contributors, rule hits and the alarms they
    overlap (explained) - or none (a new finding the threshold alarms did not raise)."""
    if rows.empty:
        return []
    rows = rows.sort_values("ts").reset_index(drop=True)
    pad = pd.Timedelta(minutes=pad_min)
    out = []
    for a, b in _runs(rows["is_anomaly"].to_numpy()):
        seg = rows.iloc[a:b + 1]
        agg: dict[str, dict] = {}
        for lst in seg["top_contributors"]:
            for c in lst or []:
                e = agg.setdefault(c["feature"], {"feature": c["feature"], "label": c["label"], "share": 0.0})
                e["share"] += c["share"]
        tot = sum(e["share"] for e in agg.values()) or 1.0
        contrib = sorted(({**e, "share": round(e["share"] / tot, 3)} for e in agg.values()), key=lambda e: -e["share"])
        start, end = seg["ts"].iloc[0], seg["ts"].iloc[-1] + STEP
        hit = al[(al["start_ts"] < end + pad) & (al["end_ts"] > start - pad)] if len(al) else al
        rules = sorted({f for lst in seg["rule_flags"] for f in (lst or [])})
        sc = seg["score_smooth"].astype(float)
        out.append({
            "start": start.isoformat(), "end": end.isoformat(), "intervals": int(len(seg)),
            "peak_score": None if sc.isna().all() else round(float(sc.max()), 3),
            "mean_score": None if sc.isna().all() else round(float(sc.mean()), 3),
            "model_flag": bool(seg["model_flag"].any()), "rule_flags": rules,
            "regimes": sorted(set(seg["regime"].dropna())),
            "top_contributors": contrib[:5],
            "alarms": [{"alarm_code": r.alarm_code, "source": r.source, "severity": int(r.severity_level)
                        if pd.notna(r.severity_level) else None, "start": r.start_ts.isoformat()}
                       for r in hit.itertuples()],
            "explained": bool(len(hit)),
        })
    return out


def latest_ts(engine: Engine, system_id: int) -> Optional[datetime]:
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text("SELECT max(ts) FROM battery_telemetry.system_telemetry WHERE system_id = :s"),
                            {"s": system_id}).scalar()
