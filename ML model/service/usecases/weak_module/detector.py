"""Weak module detection: run Isolation Forest and DBSCAN on the module feature rows and turn the row results into
a verdict per module.

  1. scale the features (RobustScaler: median / IQR, so the anomalies themselves don't set the scale);
  2. each model flags rows (module-days): IF by its score threshold (contamination), DBSCAN by noise;
  3. per module: the share of its rows each model flagged. A model flags the module when that share reaches
     min_anomalous_share. WEAK = flagged by both models, SUSPECT = by one, NORMAL = by none;
  4. combined score = 0.4 x IF share + 0.4 x DBSCAN share + 0.2 x the module's mean IF score (scaled 0-1 over the
     modules) - the ranking;
  5. reasons: the module's features compared with all modules (z-score of its mean); the strongest deviations,
     in words ("12.3 mV below its pack").
A train run keeps the scaler and both detectors; a score run applies them to another window.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import RobustScaler

from usecases.weak_module.features import FEATURES
from usecases.weak_module.models import DbscanDetector, DetectionError, IsolationForestDetector

MIN_ROWS = 20
DEFAULT_MIN_SHARE = 0.4


@dataclass
class DetectionResult:
    points: pd.DataFrame  # module_id, bucket, features..., if_score, if_flag, db_label
    modules: pd.DataFrame  # per-module verdicts
    stats: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    scaler: Any = None
    iforest: Optional[IsolationForestDetector] = None
    dbscan: Optional[DbscanDetector] = None
    duration_ms: int = 0


def _reasons(means: pd.DataFrame, features: list[str]) -> dict[int, list[dict]]:
    mu, sd = means[features].mean(), means[features].std().replace(0, np.nan)
    z = ((means[features] - mu) / sd).fillna(0)
    out = {}
    for module_id, row in z.iterrows():
        top = row.abs().sort_values(ascending=False)
        items = []
        for f in top.index[:3]:
            if abs(row[f]) < 1.0 and items:
                break
            meta = FEATURES[f]
            value = float(means.loc[module_id, f])
            diff = value - float(mu[f])
            unit = meta["unit"]
            amount = f"{abs(diff) * 100:.1f} pp" if unit == "share" else f"{abs(diff):.2f} {unit}" if unit in ("°C", "σ") \
                else f"{abs(diff):.1f} {unit}"
            items.append({"feature": f, "label": meta["label"], "value": round(value, 3), "z": round(float(row[f]), 2),
                          "text": f"{amount} {meta['up'] if diff > 0 else meta['down']}"})
        out[module_id] = items
    return out


def _verdicts(points: pd.DataFrame, features: list[str], min_share: float, module_info: pd.DataFrame) -> pd.DataFrame:
    g = points.groupby("module_id")
    mods = pd.DataFrame({
        "n_points": g.size(),
        "if_score_mean": g.if_score.mean(),
        "if_anomaly_share": g.if_flag.mean(),
        "db_noise_share": g.db_label.apply(lambda s: float((s == -1).mean())),
    })
    means = g[features].mean()
    mods["if_flag"] = mods.if_anomaly_share >= min_share
    mods["db_flag"] = mods.db_noise_share >= min_share
    both, one = mods.if_flag & mods.db_flag, mods.if_flag ^ mods.db_flag
    mods["verdict"] = np.where(both, "WEAK", np.where(one, "SUSPECT", "NORMAL"))
    s = mods.if_score_mean
    norm = (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else s * 0
    mods["combined_score"] = (0.4 * mods.if_anomaly_share + 0.4 * mods.db_noise_share + 0.2 * norm).round(4)
    mods = mods.sort_values("combined_score", ascending=False)
    mods["rank"] = np.arange(1, len(mods) + 1)
    flagged = points[(points.if_flag) | (points.db_label == -1)]
    mods["first_anomaly"] = flagged.groupby("module_id").bucket.min()
    reasons = _reasons(means, features)
    mods["reasons"] = [reasons.get(m, []) for m in mods.index]
    mods["feature_means"] = [{f: round(float(means.loc[m, f]), 4) for f in features} for m in mods.index]
    info = module_info.set_index("module_id")
    for c in ("serial_number", "pack_id", "pack_number", "position"):
        mods[c] = info[c].reindex(mods.index).to_numpy()
    return mods.reset_index()


def _run(df: pd.DataFrame, features: list[str], scaler, iforest: IsolationForestDetector, dbscan: DbscanDetector,
         fit: bool, min_share: float, module_info: pd.DataFrame) -> DetectionResult:
    if len(df) < MIN_ROWS:
        raise DetectionError(f"Only {len(df)} module rows in the window; at least {MIN_ROWS} are needed")
    started = time.perf_counter()
    warnings: list[str] = []
    X = df[features].to_numpy(dtype=float)
    if fit:
        scaler = RobustScaler().fit(X)
        if dbscan.params["min_samples"] == 0:  # auto: two modules' worth of rows
            dbscan.params["min_samples"] = max(5, int(2 * df.groupby("module_id").size().median()))
    Xs = scaler.transform(X)
    r_if = iforest.detect(Xs) if fit else iforest.score_new(Xs)
    r_db = dbscan.detect(Xs) if fit else dbscan.score_new(Xs)

    points = df[["module_id", "bucket"] + features].copy()
    points["if_score"], points["if_flag"], points["db_label"] = r_if.score.round(5), r_if.flag, r_db.label
    modules = _verdicts(points, features, min_share, module_info)

    noise_share = float((r_db.label == -1).mean())
    both = np.logical_and(r_if.flag, r_db.flag).sum()
    either = np.logical_or(r_if.flag, r_db.flag).sum()
    sil = None
    clustered = r_db.label != -1
    if r_db.info["clusters"] >= 2 and clustered.sum() > r_db.info["clusters"]:
        sil = float(silhouette_score(Xs[clustered], r_db.label[clustered]))
    stats = {
        "rows": len(df), "modules": int(df.module_id.nunique()), "packs": int(df.pack_id.nunique()),
        "if_anomalies": int(r_if.flag.sum()), "if_threshold": r_if.info["threshold"],
        "db_noise": int((r_db.label == -1).sum()), "db_clusters": r_db.info["clusters"], "eps_used": r_db.info["eps"],
        "min_samples_used": dbscan.params["min_samples"],
        "silhouette": sil, "agreement": round(both / either, 3) if either else None,
        "n_weak": int((modules.verdict == "WEAK").sum()), "n_suspect": int((modules.verdict == "SUSPECT").sum()),
        "feature_stats": {f: {"mean": round(float(df[f].mean()), 4), "std": round(float(df[f].std()), 4),
                              "min": round(float(df[f].min()), 4), "max": round(float(df[f].max()), 4)} for f in features},
    }
    if stats["packs"] < 2 and any(f.startswith(("v_dev_sys", "t_dev_sys")) for f in features):
        warnings.append("The system has a single pack: per-module (system) and per-pack deviations are the same")
    if noise_share > 0.3:
        warnings.append(f"DBSCAN marks {noise_share:.0%} of the rows as noise: raise eps (or the auto eps multiplier)")
    if r_db.info["clusters"] == 0:
        warnings.append("DBSCAN found no cluster: every row is noise - raise eps or lower min_samples")
    constant = [f for f in features if df[f].std() < 1e-9]
    if constant:
        warnings.append(f"No variation in {', '.join(constant)} (these features can't separate modules)")
    if stats["agreement"] is not None and stats["agreement"] < 0.2:
        warnings.append("The two models agree on few rows: compare the IF contamination with DBSCAN's noise share")
    return DetectionResult(points=points, modules=modules, stats=stats, warnings=warnings, scaler=scaler,
                           iforest=iforest, dbscan=dbscan, duration_ms=int((time.perf_counter() - started) * 1000))


def train(df: pd.DataFrame, features: list[str], if_params: dict, db_params: dict, min_share: float,
          module_info: pd.DataFrame, seed: int = 42) -> DetectionResult:
    if not features:
        raise DetectionError("Choose at least one feature group")
    if not 0 < min_share <= 1:
        raise DetectionError("The anomalous-share threshold must be between 0 and 1")
    return _run(df, features, None, IsolationForestDetector(if_params, seed), DbscanDetector(db_params, seed), True,
                min_share, module_info)


def score(df: pd.DataFrame, artifact: dict, module_info: pd.DataFrame) -> DetectionResult:
    """Apply a train run's scaler and detectors to a new window."""
    return _run(df, artifact["features"], artifact["scaler"], IsolationForestDetector.restore(artifact["iforest"]),
                DbscanDetector.restore(artifact["dbscan"]), False, artifact["min_share"], module_info)


def artifact_of(result: DetectionResult, features: list[str], min_share: float) -> dict:
    return {"features": features, "min_share": min_share, "scaler": result.scaler,
            "iforest": result.iforest.state(), "dbscan": result.dbscan.state()}
