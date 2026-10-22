"""ML classifiers, the two-stage hierarchy, fusion with the signature engine, calibration and the scorecard.

    Booster       one multiclass LightGBM / XGBoost over the labels it was trained on (+ SHAP-style contributions)
    Hierarchical  stage 1 = subsystem (BMS / PCS / EMS / HVAC / PLANT), stage 2 = fault within the subsystem;
                  P(fault) = P(subsystem) · P(fault | subsystem)
    Flat          one multiclass booster over every fault
    fuse()        weighted geometric mean  p ∝ p_ml^α · p_sig^(1−α)  (p_ml smoothed so classes the ML never saw
                  fall back to the signature engine)
    temperature   one-parameter calibration fitted on the out-of-fold fused probabilities (Platt-style; per-class
                  isotonic needs far more than 70 episodes)
"""
from dataclasses import dataclass
from typing import Optional

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

NONE = "F-NONE"


@dataclass
class MLSettings:
    algorithm: str = "lightgbm"        # lightgbm | xgboost
    structure: str = "flat"            # flat | hierarchical (subsystem -> fault)
    n_estimators: int = 200
    learning_rate: float = 0.05
    max_depth: int = 4
    num_leaves: int = 7
    min_child_samples: int = 2
    class_weight_power: float = 1.0    # 0 = none, 1 = fully balanced
    confirmed_boost: float = 0.5       # extra weight for repair-confirmed labels
    augment: bool = True               # signature-driven synthetic windows for minority classes
    augment_min: int = 4               # top classes up to this many examples
    augment_noise: float = 0.15        # noise as a fraction of each feature's std
    seed: int = 42


class Booster:
    def __init__(self, s: MLSettings):
        self.s = s
        self.labels: list[str] = []
        self.model = None
        self.const: Optional[str] = None

    def fit(self, X: np.ndarray, y: np.ndarray, w: np.ndarray):
        self.labels = sorted(set(y))
        if len(self.labels) == 1:
            self.const = self.labels[0]
            return self
        yi = np.array([self.labels.index(v) for v in y])
        s = self.s
        if s.algorithm == "xgboost":
            from xgboost import XGBClassifier
            self.model = XGBClassifier(
                n_estimators=s.n_estimators, learning_rate=s.learning_rate, max_depth=s.max_depth,
                min_child_weight=max(s.min_child_samples * 0.1, 0.1), subsample=0.9, colsample_bytree=0.6,
                reg_lambda=1.0, tree_method="hist", random_state=s.seed, n_jobs=4, verbosity=0,
                objective="multi:softprob" if len(self.labels) > 2 else "binary:logistic")
        else:
            from lightgbm import LGBMClassifier
            self.model = LGBMClassifier(
                n_estimators=s.n_estimators, learning_rate=s.learning_rate, num_leaves=s.num_leaves,
                max_depth=s.max_depth, min_child_samples=s.min_child_samples, min_split_gain=0.0,
                subsample=0.9, subsample_freq=1, colsample_bytree=0.6, reg_lambda=1.0, random_state=s.seed,
                n_jobs=4, verbose=-1)
        self.model.fit(X, yi, sample_weight=w)
        return self

    def proba(self, X: np.ndarray) -> np.ndarray:
        if self.const is not None:
            return np.ones((len(X), 1))
        return self.model.predict_proba(X)

    def contrib(self, X: np.ndarray) -> np.ndarray:
        """(n, n_labels, n_features) contributions to each label's raw score."""
        n, f = X.shape
        if self.const is not None:
            return np.zeros((n, 1, f))
        k = len(self.labels)
        if self.s.algorithm == "xgboost":
            import xgboost as xgb
            c = self.model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)
            if c.ndim == 2:   # binary: contributions to the positive class
                c = np.stack([-c, c], axis=1)
            return c[:, :, :f]
        c = self.model.predict(X, pred_contrib=True)
        c = np.asarray(c)
        if k == 2:
            c = c.reshape(n, f + 1)
            c = np.stack([-c, c], axis=1)
        else:
            c = c.reshape(n, k, f + 1)
        return c[:, :, :f]

    def importance(self) -> np.ndarray:
        if self.const is not None or self.model is None:
            return None
        return np.asarray(self.model.feature_importances_, dtype=float)


class Classifier:
    """Flat or hierarchical, producing probabilities over the full class list."""

    def __init__(self, s: MLSettings, classes: list[str], subsystem_of: dict[str, str]):
        self.s, self.classes, self.sub_of = s, classes, subsystem_of
        self.ix = {c: i for i, c in enumerate(classes)}
        self.flat: Optional[Booster] = None
        self.stage1: Optional[Booster] = None
        self.stage2: dict[str, Booster] = {}
        self.n_features = 0

    def fit(self, X: np.ndarray, y: np.ndarray, w: np.ndarray):
        self.n_features = X.shape[1]
        if self.s.structure == "flat":
            self.flat = Booster(self.s).fit(X, y, w)
            return self
        subs = np.array([self.sub_of.get(v, "PLANT") for v in y])
        self.stage1 = Booster(self.s).fit(X, subs, w)
        for sub in sorted(set(subs)):
            m = subs == sub
            self.stage2[sub] = Booster(self.s).fit(X[m], y[m], w[m])
        return self

    def proba(self, X: np.ndarray) -> np.ndarray:
        out = np.zeros((len(X), len(self.classes)))
        if self.flat is not None:
            p = self.flat.proba(X)
            for j, lab in enumerate(self.flat.labels):
                out[:, self.ix[lab]] = p[:, j]
            return out
        p1 = self.stage1.proba(X)
        for j, sub in enumerate(self.stage1.labels):
            b = self.stage2[sub]
            p2 = b.proba(X)
            for k, lab in enumerate(b.labels):
                out[:, self.ix[lab]] += p1[:, j] * p2[:, k]
        return out

    def subsystem_proba(self, X: np.ndarray) -> Optional[dict]:
        if self.stage1 is None:
            return None
        p = self.stage1.proba(X)
        return {sub: p[:, j] for j, sub in enumerate(self.stage1.labels)}

    def contributions(self, X: np.ndarray, label: str) -> np.ndarray:
        """Per-row contributions towards `label` (stage 2 within its subsystem, plus stage 1 for the subsystem)."""
        n = len(X)
        total = np.zeros((n, X.shape[1]))
        if self.flat is not None:
            if label in self.flat.labels:
                total += self.flat.contrib(X)[:, self.flat.labels.index(label), :]
            return total
        sub = self.sub_of.get(label, "PLANT")
        if sub in self.stage1.labels:
            total += self.stage1.contrib(X)[:, self.stage1.labels.index(sub), :]
        b = self.stage2.get(sub)
        if b is not None and label in b.labels:
            total += b.contrib(X)[:, b.labels.index(label), :]
        return total

    def importance(self) -> np.ndarray:
        imps = []
        for b in ([self.flat] if self.flat else [self.stage1, *self.stage2.values()]):
            v = b.importance()
            if v is not None and v.sum() > 0:
                imps.append(v / v.sum())
        return np.mean(imps, axis=0) if imps else np.zeros(self.n_features)


def sample_weights(y: np.ndarray, conf: np.ndarray, confirmed: np.ndarray, s: MLSettings) -> np.ndarray:
    vc = pd.Series(y).value_counts()
    k = len(vc)
    cw = np.array([(len(y) / (k * vc[v])) ** s.class_weight_power for v in y])
    return cw * np.nan_to_num(conf, nan=1.0) * (1 + s.confirmed_boost * confirmed.astype(float))


def augment(X: np.ndarray, y: np.ndarray, w: np.ndarray, groups: np.ndarray, binary_cols: np.ndarray,
            s: MLSettings, rng: np.random.Generator):
    """Synthetic minority windows: jitter the continuous features of each minority example (alarm counts and other
    discrete columns stay as they are, so the signature pattern is preserved)."""
    if not s.augment:
        return X, y, w
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sd = np.nanstd(X, axis=0)
    sd = np.where(np.isfinite(sd), sd, 0.0)
    xs, ys, ws = [X], [y], [w]
    for lab, n in pd.Series(y).value_counts().items():
        if lab == NONE or n >= s.augment_min:
            continue
        idx = np.where(y == lab)[0]
        need = s.augment_min - n
        pick = rng.choice(idx, size=need, replace=True)
        noise = rng.normal(0, 1, size=(need, X.shape[1])) * sd * s.augment_noise
        noise[:, binary_cols] = 0.0
        xs.append(X[pick] + noise)
        ys.append(y[pick])
        ws.append(w[pick] * 0.5)
    return np.vstack(xs), np.concatenate(ys), np.concatenate(ws)


def fuse(p_ml: np.ndarray, p_sig: np.ndarray, alpha: float, eps: float = 0.02) -> np.ndarray:
    k = p_ml.shape[1]
    pm = (1 - eps) * p_ml + eps / k
    ps = np.clip(p_sig, 1e-9, 1)
    lg = alpha * np.log(pm) + (1 - alpha) * np.log(ps)
    lg -= lg.max(axis=1, keepdims=True)
    z = np.exp(lg)
    return z / z.sum(axis=1, keepdims=True)


def apply_temperature(p: np.ndarray, t: float) -> np.ndarray:
    lg = np.log(np.clip(p, 1e-12, 1)) / t
    lg -= lg.max(axis=1, keepdims=True)
    z = np.exp(lg)
    return z / z.sum(axis=1, keepdims=True)


def fit_temperature(p: np.ndarray, y_ix: np.ndarray) -> float:
    def nll(t):
        q = apply_temperature(p, t)
        return -np.mean(np.log(np.clip(q[np.arange(len(y_ix)), y_ix], 1e-12, 1)))
    r = minimize_scalar(nll, bounds=(0.25, 8.0), method="bounded")
    return float(r.x)


def ece(p: np.ndarray, y_ix: np.ndarray, bins: int = 10) -> float:
    conf = p.max(axis=1)
    hit = (p.argmax(axis=1) == y_ix).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (conf > a) & (conf <= b)
        if m.any():
            e += m.mean() * abs(hit[m].mean() - conf[m].mean())
    return float(e)


def scorecard(y: list[str], p: np.ndarray, classes: list[str], catalog: pd.DataFrame, kinds: Optional[list[str]] = None) -> dict:
    """Macro-F1, per-class recall, top-3, F-NONE false positives, cost-weighted error, subsystem accuracy, log loss, ECE
    and the confusion matrix."""
    if len(y) == 0:
        return {}
    ix = {c: i for i, c in enumerate(classes)}
    y = list(y)
    yi = np.array([ix[v] for v in y])
    pred_i = p.argmax(axis=1)
    pred = [classes[i] for i in pred_i]
    top3 = np.argsort(-p, axis=1)[:, :3]
    cat = catalog.set_index("fault_code")
    sub = cat["subsystem"].to_dict()
    present = sorted(set(y) | set(pred), key=lambda c: (sub.get(c, "Z"), c))
    per = []
    f1s = []
    for c in sorted(set(y), key=lambda c: (sub.get(c, "Z"), c)):
        tp = sum(1 for a, b in zip(y, pred) if a == c and b == c)
        fn = sum(1 for a, b in zip(y, pred) if a == c and b != c)
        fp = sum(1 for a, b in zip(y, pred) if a != c and b == c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        f1s.append(f1)
        row = cat.loc[c] if c in cat.index else None
        per.append({"fault_code": c, "subsystem": sub.get(c), "support": tp + fn, "precision": prec, "recall": rec,
                    "f1": f1, "top3_recall": float(np.mean([ix[c] in top3[i] for i in range(len(y)) if y[i] == c])),
                    "is_safety_critical": bool(row["is_safety_critical"]) if row is not None else False})
    def cost(c):
        if c not in cat.index:
            return 1.0
        r = cat.loc[c]
        return 1.0 + float(r["default_severity"] or 0) + 2.0 * float(bool(r["is_safety_critical"]))
    costs = np.array([cost(v) for v in y])
    wrong = pred_i != yi
    none_mask = np.array([v == NONE for v in y])
    fault_mask = ~none_mask
    conf = {a: {} for a in present}
    for a, b in zip(y, pred):
        conf[a][b] = conf[a].get(b, 0) + 1
    return {
        "n": len(y), "accuracy": float((~wrong).mean()), "macro_f1": float(np.mean(f1s)) if f1s else 0.0,
        "top3_accuracy": float(np.mean([yi[i] in top3[i] for i in range(len(y))])),
        "subsystem_accuracy": float(np.mean([sub.get(a) == sub.get(b) for a, b in zip(y, pred)])),
        "none_fpr": float(np.mean([b != NONE for a, b in zip(y, pred) if a == NONE])) if none_mask.any() else None,
        "fault_miss_rate": float(np.mean([b == NONE for a, b in zip(y, pred) if a != NONE])) if fault_mask.any() else None,
        "safety_recall": float(np.mean([a == b for a, b in zip(y, pred) if cat["is_safety_critical"].get(a, False)]))
        if any(cat["is_safety_critical"].get(a, False) for a in y) else None,
        "cost_weighted_error": float((costs * wrong).sum() / costs.sum()),
        "log_loss": float(-np.mean(np.log(np.clip(p[np.arange(len(yi)), yi], 1e-12, 1)))),
        "ece": ece(p, yi),
        "per_class": per,
        "confusion": {"labels": present, "matrix": [[conf[a].get(b, 0) for b in present] for a in present]},
    }


def top_k(p_row: np.ndarray, classes: list[str], k: int = 3) -> list[dict]:
    o = np.argsort(-p_row)[:k]
    return [{"fault_code": classes[i], "p": float(p_row[i])} for i in o]
