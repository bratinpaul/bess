"""One training run, and scanning a window with a trained run.

train():
  1. examples   episode windows (one per episode, or sliding windows across its development) + matched F-NONE windows
                from healthy periods (the scoring log's healthy timestamps first, then random quiet intervals)
  2. features   telemetry / signature / alarm / context families (features.py)
  3. OOF        grouped, stratified k-fold (every window of an episode in one fold): signature engine, ML, fused
  4. calibrate  temperature on the OOF fused probabilities
  5. forward    time-ordered holdout (train on the earlier episodes, test on the later ones)
  6. final      refit on everything -> artifact for scanning
scan():
  sliding windows over a system / date range -> fused, calibrated top-3 per window -> merged candidate events
"""
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from core.base import UseCaseError
from usecases.fault_diag import data as D
from usecases.fault_diag import engine as E
from usecases.fault_diag import features as F
from usecases.fault_diag import model as M

NONE = M.NONE


@dataclass
class RunConfig:
    leakage_mode: str = "triage"          # triage | early
    granularity: str = "episode"          # episode | window
    lookback_min: int = 60
    post_min: int = 15                    # triage only: minutes after detection inside the window
    step_min: int = 15                    # window granularity: slide step
    max_span_min: int = 120               # window granularity: how far after detection windows go (triage)
    n_none: int = 40                      # healthy F-NONE windows
    none_guard_h: float = 2.0             # healthy windows stay this far from any alarm / episode
    families: list = field(default_factory=lambda: list(F.FAMILIES))
    soft_pct: float = 0.05                # soft threshold width as a fraction of |threshold|
    folds: int = 5
    train_frac: float = 0.7               # forward (time) holdout
    alpha: float = 0.6                    # fusion weight of the ML posterior
    calibrate: bool = True
    alert_threshold: float = 0.5
    top_contrib: int = 8
    engine: E.EngineSettings = field(default_factory=E.EngineSettings)
    ml: M.MLSettings = field(default_factory=M.MLSettings)


class FaultDiagError(UseCaseError):
    code = "FAULT_DIAG_INPUT_REJECTED"


# --------------------------------------------------------------------------------------------------- examples
def _episode_windows(ep: pd.Series, cfg: RunConfig) -> list[F.Window]:
    look = pd.Timedelta(minutes=cfg.lookback_min)
    det, onset = ep["detected_ts"], ep["onset_ts"]
    hide = set(ep["alarm_ids"]) if cfg.leakage_mode == "early" else set()
    base = dict(group=ep["episode_id"], system_id=int(ep["telemetry_system_id"]), label=ep["fault_code"],
                episode_id=ep["episode_id"], kind="episode", exclude_alarms=hide)
    if cfg.granularity == "episode":
        end = det + pd.Timedelta(minutes=cfg.post_min) if cfg.leakage_mode == "triage" else det - pd.Timedelta(seconds=1)
        return [F.Window(key=ep["episode_id"], start=det - look, end=end, **base)]
    step = pd.Timedelta(minutes=cfg.step_min)
    if cfg.leakage_mode == "triage":
        stop = det + pd.Timedelta(minutes=cfg.max_span_min)
        if pd.notna(ep["resolved_ts"]):
            stop = min(stop, max(ep["resolved_ts"], det + step))
        first = det
    else:
        stop = det - pd.Timedelta(seconds=1)
        first = min(onset + step, stop)
    ends = []
    t = first
    while t <= stop:
        ends.append(t)
        t += step
    if not ends:
        ends = [stop]
    return [F.Window(key=f"{ep['episode_id']}@{e:%Y%m%d%H%M}", start=e - look, end=e, **base) for e in ends]


def _busy_intervals(eps: pd.DataFrame, al: pd.DataFrame, system_id: int, guard: pd.Timedelta) -> list[tuple]:
    out = []
    for r in eps[eps["telemetry_system_id"] == system_id].itertuples():
        end = r.resolved_ts if pd.notna(r.resolved_ts) else r.detected_ts + pd.Timedelta(hours=2)
        out.append((r.onset_ts - guard, end + guard))
    for t in al["time"]:
        out.append((t - guard, t + guard))
    return out


def _none_windows(eps: pd.DataFrame, frames: dict, alarms: dict, anchors: pd.DataFrame, cfg: RunConfig,
                  rng: np.random.Generator) -> list[F.Window]:
    """Healthy windows: the scoring log's healthy timestamps (when they are quiet here), then random quiet intervals,
    spread over the systems that carry the episodes."""
    guard = pd.Timedelta(hours=cfg.none_guard_h)
    look = pd.Timedelta(minutes=cfg.lookback_min)
    sys_ids = sorted(frames)
    picks: list[tuple[int, pd.Timestamp]] = []
    busy = {s: _busy_intervals(eps, alarms[s], s, guard) for s in sys_ids}

    def quiet(s, t):
        fx = frames[s]
        if fx.t0 is None or t - look < fx.t0 or t > fx.t1:
            return False
        return not any(a <= t and t - look <= b for a, b in busy[s])

    for a in anchors.itertuples():
        # the log files them under the episode system; their telemetry is wherever that system's episodes live
        cand = [s for s in sys_ids if s == a.system_id] or sys_ids
        for s in cand:
            t = a.predicted_at.floor("5min")
            if quiet(s, t):
                picks.append((s, t))
                break
    tries = 0
    while len(picks) < cfg.n_none and tries < cfg.n_none * 200:
        tries += 1
        s = sys_ids[rng.integers(len(sys_ids))]
        fx = frames[s]
        if fx.t0 is None:
            continue
        span = (fx.t1 - fx.t0 - look).total_seconds()
        if span <= 0:
            continue
        t = (fx.t0 + look + pd.Timedelta(seconds=float(rng.uniform(0, span)))).floor("5min")
        if quiet(s, t) and all(abs((t - p).total_seconds()) > 3 * 3600 for q, p in picks if q == s):
            picks.append((s, t))
    out = []
    step = pd.Timedelta(minutes=cfg.step_min)
    n_sub = 1 if cfg.granularity == "episode" else max(1, int(cfg.max_span_min / cfg.step_min) // 2)
    for k, (s, t) in enumerate(picks[: cfg.n_none]):
        for j in range(n_sub):
            e = t + j * step
            out.append(F.Window(key=f"NONE-{k + 1:03d}" + (f"@{j}" if n_sub > 1 else ""), group=f"NONE-{k + 1:03d}",
                                system_id=s, start=e - look, end=e, label=NONE, kind="none"))
    return out


def build_dataset(engine, cfg: RunConfig, date_from: Optional[date] = None, date_to: Optional[date] = None) -> dict:
    cat = D.catalog(engine)
    sigs = D.signatures(engine)
    eps = D.episodes(engine)
    if date_from:
        eps = eps[eps["detected_ts"] >= pd.Timestamp(date_from, tz=D.TZ)]
    if date_to:
        eps = eps[eps["detected_ts"] < pd.Timestamp(date_to, tz=D.TZ) + pd.Timedelta(days=1)]
    if len(eps) < 10:
        raise FaultDiagError(f"Only {len(eps)} confirmed episodes in the window - at least 10 are needed")
    codes = D.alarm_codes(engine)
    frames, alarms = {}, {}
    for s, g in eps.groupby("telemetry_system_id"):
        t0, t1 = D.frame_bounds(list(g["onset_ts"]) + list(g["detected_ts"]), cfg.lookback_min + cfg.max_span_min)
        fr = D.load_telemetry(engine, int(s), t0, t1)
        if fr.empty:
            continue
        frames[int(s)] = F.FrameIndex(fr)
        alarms[int(s)] = D.alarms(engine, int(s), t0, t1)
    if not frames:
        raise FaultDiagError("No telemetry was found for the episodes' systems")
    eps = eps[eps["telemetry_system_id"].isin(frames)]
    rng = np.random.default_rng(cfg.ml.seed)
    wins: list[F.Window] = []
    for _, ep in eps.iterrows():
        wins += _episode_windows(ep, cfg)
    wins += _none_windows(eps, frames, alarms, D.healthy_anchors(engine), cfg, rng)

    rows, evid = [], []
    for w in wins:
        f, ev = F.build_vector(frames[w.system_id], w, alarms[w.system_id], sigs, codes, cfg.soft_pct)
        rows.append(f)
        evid.append(ev)
    X = pd.DataFrame(rows)
    ep_ix = eps.set_index("episode_id")
    meta = pd.DataFrame([{
        "key": w.key, "group": w.group, "system_id": w.system_id, "start": w.start, "end": w.end, "label": w.label,
        "episode_id": w.episode_id, "kind": w.kind,
        "conf": float(ep_ix.at[w.episode_id, "label_confidence"]) if w.episode_id and pd.notna(ep_ix.at[w.episode_id, "label_confidence"]) else 1.0,
        "confirmed": bool(ep_ix.at[w.episode_id, "fault_confirmed"]) if w.episode_id and ep_ix.at[w.episode_id, "fault_confirmed"] is True else False,
        "detected_ts": ep_ix.at[w.episode_id, "detected_ts"] if w.episode_id else w.end,
        "onset_ts": ep_ix.at[w.episode_id, "onset_ts"] if w.episode_id else w.end,
    } for w in wins])
    coverage = {s.signal: (s.signal in D.UNAVAILABLE and "unavailable") or
                ("alarm" if (s.signal_kind == "ALARM" or s.operator == "PRESENT") else
                 ("available" if any(s.signal in fx.available for fx in frames.values()) else "unavailable"))
                for s in sigs.itertuples()}
    return {"catalog": cat, "signatures": sigs, "episodes": eps, "codes": codes, "X": X, "meta": meta,
            "evidence": evid, "coverage": coverage, "frames": frames, "alarms": alarms}


# ------------------------------------------------------------------------------------------------------ train
def _select_columns(X: pd.DataFrame, families: list[str]) -> list[str]:
    cols = [c for c in X.columns if F.family_of(c) in families]
    keep = []
    for c in cols:
        v = X[c]
        if v.notna().sum() == 0 or v.nunique(dropna=True) <= 1:
            continue
        keep.append(c)
    return keep


def _engine_proba(evidence: list, classes: list[str], prior: np.ndarray, s: E.EngineSettings,
                  muted: frozenset = frozenset()) -> np.ndarray:
    if not evidence:
        return np.zeros((0, len(classes)))
    return np.vstack([E.posterior(ev, classes, prior, s, muted) for ev in evidence])


def _contrib_rows(clf: M.Classifier, X: np.ndarray, labels: list[str], cols: list[str], sig_lookup: dict, k: int) -> list:
    out = []
    by_label: dict[str, list[int]] = {}
    for i, lab in enumerate(labels):
        by_label.setdefault(lab, []).append(i)
    res: dict[int, list] = {}
    for lab, idx in by_label.items():
        c = clf.contributions(X[idx], lab)
        for r, i in enumerate(idx):
            o = np.argsort(-np.abs(c[r]))[:k]
            res[i] = [{"feature": cols[j], "label": F.feature_label(cols[j], sig_lookup), "family": F.family_of(cols[j]),
                       "value": D._num(X[i, j]), "contribution": float(c[r, j])} for j in o if c[r, j] != 0]
    return [res.get(i, []) for i in range(len(labels))]


def train(engine, cfg: RunConfig, date_from: Optional[date] = None, date_to: Optional[date] = None) -> dict:
    t_start = time.time()
    warnings.filterwarnings("ignore", category=UserWarning)
    ds = build_dataset(engine, cfg, date_from, date_to)
    cat, meta, X_all = ds["catalog"], ds["meta"], ds["X"]
    classes = list(cat["fault_code"])
    if NONE not in classes:
        raise FaultDiagError("fault_catalog has no F-NONE class")
    sub_of = dict(zip(cat["fault_code"], cat["subsystem"]))
    cols = _select_columns(X_all, cfg.families)
    if not cols:
        raise FaultDiagError("No usable features in the chosen families")
    X = X_all[cols].to_numpy(dtype=float)
    binary_cols = np.array([c.startswith("alarm__") for c in cols])
    y = meta["label"].to_numpy()
    groups = meta["group"].to_numpy()
    w_base = M.sample_weights(y, meta["conf"].to_numpy(), meta["confirmed"].to_numpy(), cfg.ml)
    ix = {c: i for i, c in enumerate(classes)}
    yi = np.array([ix[v] for v in y])
    sig_lookup = {int(s.signature_id): {"signal": s.signal, "operator": s.operator, "threshold": D._num(s.threshold),
                                        "fault_code": s.fault_code} for s in ds["signatures"].itertuples()}
    warns = []
    thin = [c for c, n in pd.Series(meta.drop_duplicates("group")["label"]).value_counts().items() if n < 3 and c != NONE]
    if thin:
        warns.append(f"{len(thin)} classes have fewer than 3 episodes ({', '.join(sorted(thin))}) - their ML metrics are provisional")
    missing_cls = [c for c in classes if c not in set(y)]
    if missing_cls:
        warns.append(f"{len(missing_cls)} catalog classes have no episode ({', '.join(missing_cls)}); only the signature engine can name them")
    unavailable = sorted({k for k, v in ds["coverage"].items() if v == "unavailable"})
    if unavailable:
        warns.append("Signature signals with no telemetry here: " + ", ".join(unavailable))
    sys_ids = sorted(meta.loc[meta["kind"] == "episode", "system_id"].unique())
    filed = sorted(ds["episodes"]["system_id"].unique())
    if sys_ids != filed:
        warns.append(f"Episodes are filed under system(s) {filed} but their alarms and telemetry are on {sys_ids}; "
                     "the telemetry system was used")

    muted, sig_health = E.always_on(ds["evidence"], list(meta["kind"] == "none"), cfg.engine.mute_rate)
    if muted:
        warns.append("Signatures muted in the engine (match most healthy windows): " +
                     ", ".join(f"{r['signal']} {r['operator']} {r['threshold']} → {r['fault_code']} "
                               f"({r['healthy_match_rate']:.0%})" for r in sig_health if r["muted"]))

    # ---------------------------------------------------------------- out-of-fold
    n_groups_per_class = meta.drop_duplicates("group")["label"].value_counts()
    k = int(min(cfg.folds, max(2, n_groups_per_class.max())))
    sgkf = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=cfg.ml.seed)
    p_ml = np.zeros((len(y), len(classes)))
    p_sig = np.zeros((len(y), len(classes)))
    contrib: list = [None] * len(y)
    rng = np.random.default_rng(cfg.ml.seed)
    fold_of = np.zeros(len(y), int)
    for f, (tr, te) in enumerate(sgkf.split(X, y, groups)):
        fold_of[te] = f
        Xa, ya, wa = M.augment(X[tr], y[tr], w_base[tr], groups[tr], binary_cols, cfg.ml, rng)
        clf = M.Classifier(cfg.ml, classes, sub_of).fit(Xa, ya, wa)
        p_ml[te] = clf.proba(X[te])
        prior = E.priors(classes, pd.Series(y[tr]), cfg.engine.prior, cfg.engine.none_prior)
        p_sig[te] = _engine_proba([ds["evidence"][i] for i in te], classes, prior, cfg.engine, muted)
        fused_te = M.fuse(p_ml[te], p_sig[te], cfg.alpha)
        pred = [classes[i] for i in fused_te.argmax(axis=1)]
        for r, c in zip(te, _contrib_rows(clf, X[te], pred, cols, sig_lookup, cfg.top_contrib)):
            contrib[r] = c
    p_fused_raw = M.fuse(p_ml, p_sig, cfg.alpha)
    temp = M.fit_temperature(p_fused_raw, yi) if cfg.calibrate else 1.0
    p_fused = M.apply_temperature(p_fused_raw, temp)

    def cards(mask=None):
        m = np.ones(len(y), bool) if mask is None else mask
        return {"engine": M.scorecard(list(y[m]), p_sig[m], classes, cat),
                "ml": M.scorecard(list(y[m]), p_ml[m], classes, cat),
                "fused": M.scorecard(list(y[m]), p_fused[m], classes, cat)}
    oof = cards()
    oof["fused"]["ece_uncalibrated"] = M.ece(p_fused_raw, yi)
    episode_level = None
    if cfg.granularity == "window":
        # one vote per episode / healthy anchor: mean probability over its windows
        g = pd.DataFrame(p_fused, columns=classes)
        g["group"], g["label"] = groups, y
        agg = g.groupby("group").agg({**{c: "mean" for c in classes}, "label": "first"})
        episode_level = M.scorecard(list(agg["label"]), agg[classes].to_numpy(), classes, cat)

    # time-to-detect (window granularity): first OOF window naming the right fault with p >= alert threshold
    ttd = []
    if cfg.granularity == "window":
        for gid, idx in meta[meta["kind"] == "episode"].groupby("group").groups.items():
            idx = sorted(idx, key=lambda i: meta.at[i, "end"])
            r0 = meta.loc[idx[0]]
            hit = next((i for i in idx if classes[p_fused[i].argmax()] == y[i] and p_fused[i].max() >= cfg.alert_threshold), None)
            row = {"episode_id": gid, "fault_code": r0["label"],
                   "alarm_ttd_min": (r0["detected_ts"] - r0["onset_ts"]).total_seconds() / 60}
            if hit is not None:
                row["model_ttd_min"] = (meta.at[hit, "end"] - r0["onset_ts"]).total_seconds() / 60
                row["lead_vs_alarm_min"] = (r0["detected_ts"] - meta.at[hit, "end"]).total_seconds() / 60
            ttd.append(row)

    # ---------------------------------------------------------------- forward (time-ordered) holdout
    order = meta.groupby("group")["end"].min().sort_values()
    cut = order.index[: max(1, int(len(order) * cfg.train_frac))]
    tr_m = meta["group"].isin(cut).to_numpy()
    te_m = ~tr_m
    forward = None
    if te_m.sum() >= 5 and len(set(y[tr_m])) >= 2:
        Xa, ya, wa = M.augment(X[tr_m], y[tr_m], w_base[tr_m], groups[tr_m], binary_cols, cfg.ml, rng)
        clf_f = M.Classifier(cfg.ml, classes, sub_of).fit(Xa, ya, wa)
        pm = clf_f.proba(X[te_m])
        ps = _engine_proba([ds["evidence"][i] for i in np.where(te_m)[0]], classes,
                           E.priors(classes, pd.Series(y[tr_m]), cfg.engine.prior, cfg.engine.none_prior), cfg.engine, muted)
        pf = M.apply_temperature(M.fuse(pm, ps, cfg.alpha), temp)
        yt = list(y[te_m])
        forward = {"split_at": str(meta.loc[te_m, "end"].min()), "n_train": int(tr_m.sum()), "n_test": int(te_m.sum()),
                   "unseen_classes": sorted(set(yt) - set(y[tr_m])),
                   "engine": M.scorecard(yt, ps, classes, cat), "ml": M.scorecard(yt, pm, classes, cat),
                   "fused": M.scorecard(yt, pf, classes, cat)}

    # ---------------------------------------------------------------- final model
    Xa, ya, wa = M.augment(X, y, w_base, groups, binary_cols, cfg.ml, rng)
    final = M.Classifier(cfg.ml, classes, sub_of).fit(Xa, ya, wa)
    imp = final.importance()
    order_imp = np.argsort(-imp)[:30]
    importance = [{"feature": cols[j], "label": F.feature_label(cols[j], sig_lookup), "family": F.family_of(cols[j]),
                   "importance": float(imp[j])} for j in order_imp if imp[j] > 0]
    fam_imp = {}
    for j, c in enumerate(cols):
        fam_imp[F.family_of(c)] = fam_imp.get(F.family_of(c), 0.0) + float(imp[j])
    prior_all = E.priors(classes, pd.Series(y), cfg.engine.prior, cfg.engine.none_prior)

    # per-example OOF results (the viewer's episode diagnosis)
    examples = []
    for i in range(len(y)):
        r = meta.iloc[i]
        top = M.top_k(p_fused[i], classes, 3)
        examples.append({
            "key": r["key"], "group": r["group"], "episode_id": r["episode_id"], "kind": r["kind"],
            "system_id": int(r["system_id"]), "start": r["start"], "end": r["end"], "label": r["label"], "fold": int(fold_of[i]),
            "predicted": top[0]["fault_code"], "probability": top[0]["p"], "correct": top[0]["fault_code"] == r["label"],
            "top3": top, "top3_ml": M.top_k(p_ml[i], classes, 3), "top3_engine": M.top_k(p_sig[i], classes, 3),
            "contributions": contrib[i] or [],
            "evidence": [e for e in ds["evidence"][i] if e["match"] is not None and
                         (e["match"] >= 0.5 or e["fault_code"] in {t["fault_code"] for t in top})],
        })
    per_class_fused = {p["fault_code"]: p for p in oof["fused"]["per_class"]}
    support = meta.drop_duplicates("group")["label"].value_counts().to_dict()
    artifact = {"classes": classes, "sub_of": sub_of, "cols": cols, "clf": final, "temperature": temp, "prior": prior_all,
                "config": cfg, "codes": ds["codes"], "signatures": ds["signatures"], "sig_lookup": sig_lookup,
                "muted": muted}
    summary = {
        "n_examples": int(len(y)), "n_episodes": int(meta.loc[meta["kind"] == "episode", "group"].nunique()),
        "n_none": int(meta.loc[meta["kind"] == "none", "group"].nunique()), "n_features": len(cols),
        "n_classes_trained": int(len(set(y))), "folds": k, "temperature": temp,
        "class_support": support, "telemetry_systems": [int(s) for s in sys_ids],
        "families": {f: int(sum(F.family_of(c) == f for c in cols)) for f in F.FAMILIES},
        "family_importance": fam_imp, "signature_coverage": ds["coverage"], "signature_health": sig_health,
        "time_to_detect": ttd,
        "ttd_summary": {
            "episodes_detected": sum(1 for r in ttd if "model_ttd_min" in r), "episodes": len(ttd),
            "median_lead_vs_alarm_min": float(np.median([r["lead_vs_alarm_min"] for r in ttd if "lead_vs_alarm_min" in r]))
            if any("lead_vs_alarm_min" in r for r in ttd) else None} if ttd else None,
    }
    metrics = {"oof": oof, "episode_level": episode_level, "forward": forward, "importance": importance,
               "per_class_fused": per_class_fused}
    return {"artifact": artifact, "summary": summary, "metrics": metrics, "examples": examples, "warnings": warns,
            "duration_ms": int((time.time() - t_start) * 1000)}


# ------------------------------------------------------------------------------------------------------- scan
def score_windows(engine, art: dict, system_id: int, d0: date, d1: date, step_min: int) -> pd.DataFrame:
    cfg: RunConfig = art["config"]
    t0, t1 = D.day_bounds(d0, d1)
    look = pd.Timedelta(minutes=cfg.lookback_min)
    fr = D.load_telemetry(engine, system_id, t0 - look, t1)
    if fr.empty:
        raise FaultDiagError(f"No telemetry for system {system_id} between {d0} and {d1}")
    fx = F.FrameIndex(fr)
    al = D.alarms(engine, system_id, t0 - look, t1)
    ends = pd.date_range(max(t0, fx.t0 + look), min(t1, fx.t1 + pd.Timedelta(minutes=5)), freq=f"{step_min}min", tz=D.TZ)
    if len(ends) == 0:
        raise FaultDiagError("The window is shorter than the model's lookback")
    rows, evid = [], []
    for e in ends:
        w = F.Window(key=str(e), group="scan", system_id=system_id, start=e - look, end=e, kind="scan")
        f, ev = F.build_vector(fx, w, al, art["signatures"], art["codes"], cfg.soft_pct)
        rows.append(f)
        evid.append(ev)
    X = pd.DataFrame(rows).reindex(columns=art["cols"]).to_numpy(dtype=float)
    classes = art["classes"]
    p_ml = art["clf"].proba(X)
    p_sig = _engine_proba(evid, classes, art["prior"], cfg.engine, art.get("muted", frozenset()))
    p = M.apply_temperature(M.fuse(p_ml, p_sig, cfg.alpha), art["temperature"])
    pred = [classes[i] for i in p.argmax(axis=1)]
    contrib = _contrib_rows(art["clf"], X, pred, art["cols"], art["sig_lookup"], cfg.top_contrib)
    out = []
    for i, e in enumerate(ends):
        in_w = al[(al["time"] >= e - look) & (al["time"] <= e)]
        out.append({"end": e, "predicted": pred[i], "probability": float(p[i].max()), "top3": M.top_k(p[i], classes, 3),
                    "p_none": float(p[i][classes.index(NONE)]), "contributions": contrib[i],
                    "evidence": [x for x in evid[i] if x["match"] is not None and x["match"] >= 0.5],
                    "alarms": sorted(set(in_w["alarm_code"].dropna())), "asset_code": in_w["asset_code"].dropna().iloc[-1]
                    if not in_w.empty and in_w["asset_code"].notna().any() else None})
    return pd.DataFrame(out)


def candidates(scores: pd.DataFrame, threshold: float, step_min: int) -> list[dict]:
    """Merge consecutive windows naming the same fault (p >= threshold, not F-NONE) into one candidate event."""
    flagged = scores[(scores["predicted"] != NONE) & (scores["probability"] >= threshold)]
    events = []
    cur = None
    gap = pd.Timedelta(minutes=step_min * 1.5)
    for r in flagged.itertuples(index=False):
        if cur and r.predicted == cur["fault_code"] and r.end - cur["last"] <= gap:
            cur["last"] = r.end
            cur["n_windows"] += 1
            if r.probability > cur["probability"]:
                cur.update(probability=r.probability, peak=r.end, top3=r.top3, contributions=r.contributions,
                           evidence=r.evidence, alarms=r.alarms, asset_code=r.asset_code or cur["asset_code"])
            continue
        if cur:
            events.append(cur)
        cur = {"fault_code": r.predicted, "first": r.end, "last": r.end, "peak": r.end, "probability": r.probability,
               "n_windows": 1, "top3": r.top3, "contributions": r.contributions, "evidence": r.evidence,
               "alarms": r.alarms, "asset_code": r.asset_code}
    if cur:
        events.append(cur)
    return events


def config_dict(cfg: RunConfig) -> dict:
    return asdict(cfg)
