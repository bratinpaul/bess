"""RUL model building: one shared model per chemistry (pooled over the fleet, with batch and unit effects), validated
leave-one-unit-out - every unit is predicted at each of its snapshots by models that never saw it.

Methods (P10 / P50 / P90 RUL in days; cycles = days x the unit's recent EFC per day):
  physics   empirical fade curve + knee, projected to the EOL criteria (physics.py); bands widened to the
            training units' errors (calibration)
  gbm       LightGBM quantile regression on the aging features -> RUL (retired units only: their labels are true)
  hybrid    physics + LightGBM quantile models of its residual (log scale)
  cox       Cox proportional hazards on landmark rows (censoring handled)
  rsf       Random Survival Forest on landmark rows (censoring handled)

Bands: the quantile models of gbm / hybrid are fitted on few units and come out too narrow, so their P10 / P90 are
widened to at least the physics band calibrated on the training units' errors (around their own P50).
Cox uses a compact covariate set (COX_FEATURES: health + recent duty / temperature + batch) - landmark rows of one unit
are strongly collinear in the accumulated-stress columns, which makes a proportional-hazards fit unstable.

Censoring: still-operating units only say "alive for at least N more days" at each snapshot. Regression methods train on
retired units only; survival methods use every unit. The synthetic forward labels of censored units in aging_snapshot
are never trained on - they give a separately reported "oracle" check.

Scores (leave-one-unit-out): on retired units MAE / RMSE / bias (days), MAE (cycles), P10-P90 coverage, pinball - overall
and per life-fraction bucket; on all units Harrell's C-index (risk = shorter P50); on censored units the violation rate
(P50 shorter than the time the unit is known to have survived) and the oracle MAE.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from core.base import UseCaseError
from core.metrics import finite, shares
from usecases.rul import features as F
from usecases.rul import physics as P
from usecases.rul.survival import CoxPH, RandomSurvivalForest, quantile_times

METHODS = ["physics", "gbm", "hybrid", "cox", "rsf"]
REGRESSION = {"physics", "gbm", "hybrid"}
LIFE_BUCKETS = [(0.0, 0.25, "0-25 %"), (0.25, 0.5, "25-50 %"), (0.5, 0.75, "50-75 %"), (0.75, 1.01, "75-100 %")]
QUANTS = (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))
COX_FEATURES = ["soh_pct", "r_ratio", "cpd_recent", "temp_mean", "batch_code"]
OFFSET = 30.0  # days added before taking logs (band calibration, hybrid residual)
GBM_PARAMS = [
    {"name": "n_estimators", "label": "Boosting rounds", "type": "int", "default": 300, "min": 20, "max": 3000, "step": 10},
    {"name": "learning_rate", "label": "Learning rate", "type": "float", "default": 0.05, "min": 0.001, "max": 1, "step": 0.005},
    {"name": "num_leaves", "label": "Leaves per tree", "type": "int", "default": 15, "min": 2, "max": 256, "step": 1},
    {"name": "min_child_samples", "label": "Min rows per leaf", "type": "int", "default": 20, "min": 3, "max": 500, "step": 1},
]
SURVIVAL_PARAMS = [
    {"name": "cox_penalizer", "label": "Cox ridge penalty", "type": "float", "default": 0.1, "min": 0.0, "max": 100, "step": 0.05},
    {"name": "rsf_trees", "label": "RSF trees", "type": "int", "default": 100, "min": 10, "max": 1000, "step": 10},
    {"name": "rsf_max_depth", "label": "RSF max depth", "type": "int", "default": 6, "min": 1, "max": 20, "step": 1},
    {"name": "rsf_min_leaf", "label": "RSF min rows per leaf", "type": "int", "default": 15, "min": 3, "max": 200, "step": 1},
]
PHYSICS_PARAMS = [
    {"name": "kappa", "label": "Unit-factor prior strength", "type": "float", "default": 6.0, "min": 0.0, "max": 200, "step": 1},
    {"name": "rpt_weight", "label": "RPT checkpoint weight", "type": "float", "default": 3.0, "min": 0.0, "max": 50, "step": 0.5},
]


class RulError(UseCaseError):
    """Bad training / prediction input (the API answers 400)."""
    code = "RUL_INPUT_REJECTED"


@dataclass
class RunConfig:
    system_ids: Optional[list[int]] = None
    methods: list[str] = field(default_factory=lambda: list(METHODS))
    feature_groups: list[str] = field(default_factory=lambda: list(F.FEATURE_GROUPS))
    failures_as: str = "event"
    arrhenius: bool = True
    knee: bool = True
    calibrate_bands: bool = True
    physics: dict = field(default_factory=dict)
    gbm: dict = field(default_factory=dict)
    survival: dict = field(default_factory=dict)
    seed: int = 42


def clean(specs: list[dict], params: dict) -> dict:
    out = {}
    for s in specs:
        v = params.get(s["name"], s["default"])
        v = s["default"] if v in (None, "") else v
        v = int(v) if s["type"] == "int" else float(v)
        if not s["min"] <= v <= s["max"]:
            raise RulError(f"{s['label']} must be between {s['min']} and {s['max']}")
        out[s["name"]] = v
    return out


def feature_columns(groups: list[str]) -> list[str]:
    cols = []
    for g in groups:
        cols += [c for c in F.FEATURE_GROUPS[g]["columns"] if c not in cols]
    return cols


# ---------------------------------------------------------------- per-method fit / predict


@dataclass
class ChemModels:
    chemistry: str
    physics: Optional[P.ChemistryModel] = None
    band: tuple = (0.0, 0.0)  # log-error quantiles (q10, q90) for the physics band
    gbm: dict = field(default_factory=dict)
    hybrid: dict = field(default_factory=dict)
    cox: Optional[CoxPH] = None
    rsf: Optional[RandomSurvivalForest] = None
    cap_days: float = 0.0


def physics_rows(model: P.ChemistryModel, rows: pd.DataFrame, rpt: pd.DataFrame, overrides: Optional[dict] = None,
                 keep_paths: bool = False) -> pd.DataFrame:
    """Physics RUL at every snapshot of the given units, each from its own history up to that snapshot."""
    out = []
    overrides = overrides or {}
    for sid, g in rows.groupby("system_id", sort=False):
        g = g.sort_values("snapshot_date")
        r_u = rpt[rpt["system_id"] == sid]
        for i in range(len(g)):
            h = g.iloc[: i + 1]
            st = P.unit_state(model, h, r_u[r_u["test_date"] <= h["snapshot_date"].iloc[-1]],
                              overrides.get("cpd"), overrides.get("temp"))
            pr = P.project(model, st)
            rec = {"idx": g.index[i], **{f"{q}_days": pr["rul_days"][q] for q, _ in QUANTS},
                   "beyond": pr["beyond"], "trigger": pr["trigger"]["p50"], "cpd": st.cpd}
            if keep_paths:
                rec["proj"] = pr
            out.append(rec)
    return pd.DataFrame(out).set_index("idx")


def calibrate(pred: pd.Series, actual: pd.Series) -> tuple[float, float]:
    e = np.log((actual + OFFSET) / (pred + OFFSET)).dropna()
    return (float(np.quantile(e, 0.1)), float(np.quantile(e, 0.9))) if len(e) >= 10 else (-0.15, 0.15)


def banded(p50: np.ndarray, band: tuple) -> tuple[np.ndarray, np.ndarray]:
    return (np.maximum((p50 + OFFSET) * np.exp(band[0]) - OFFSET, 0.0),
            np.maximum((p50 + OFFSET) * np.exp(band[1]) - OFFSET, 0.0))


def fit_quantile_gbm(X: pd.DataFrame, y: np.ndarray, params: dict, seed: int) -> dict:
    return {q: lgb.LGBMRegressor(objective="quantile", alpha=a, random_state=seed, verbose=-1, n_jobs=4,
                                 **params).fit(X, y) for q, a in QUANTS}


def predict_gbm(models: dict, X: pd.DataFrame) -> dict:
    trio = np.sort(np.vstack([models[q].predict(X) for q, _ in QUANTS]), axis=0)
    return {q: trio[i] for i, (q, _) in enumerate(QUANTS)}


def survival_frame(rows: pd.DataFrame) -> pd.DataFrame:
    s = rows[(rows["duration"] > 0) & rows["duration"].notna()]
    return s


def fit_chem(cfg: RunConfig, chem: str, rows: pd.DataFrame, rpt: pd.DataFrame, eol: dict, cols: list[str],
             phys_cache: Optional[pd.DataFrame] = None) -> tuple[ChemModels, pd.DataFrame]:
    """All selected methods on the given (training) units of one chemistry. Returns the models and the physics
    predictions of the training rows (for calibration / the hybrid)."""
    m = ChemModels(chem)
    pp = clean(PHYSICS_PARAMS, cfg.physics)
    sp = clean(SURVIVAL_PARAMS, cfg.survival)
    gp = clean(GBM_PARAMS, cfg.gbm)
    need_phys = bool({"physics", "hybrid"} & set(cfg.methods))
    phys = None
    if need_phys:
        m.physics = P.fit_chemistry(chem, rows, rpt, eol, arrhenius=cfg.arrhenius, kappa=pp["kappa"],
                                    rpt_weight=pp["rpt_weight"], knee=cfg.knee)
        phys = physics_rows(m.physics, rows, rpt)
        ret = rows["retired"]
        if cfg.calibrate_bands:
            m.band = calibrate(phys.loc[ret, "p50_days"], rows.loc[ret, "rul_days"])
    train = rows[rows["retired"]]
    X = train[cols]
    if "gbm" in cfg.methods and len(train) >= 20:
        m.gbm = fit_quantile_gbm(X, train["rul_days"].to_numpy(), gp, cfg.seed)
    if "hybrid" in cfg.methods and len(train) >= 20 and phys is not None:
        Xh = X.assign(phys_p50=phys.loc[train.index, "p50_days"].to_numpy())
        res = np.log1p(train["rul_days"].to_numpy()) - np.log1p(Xh["phys_p50"].to_numpy())
        m.hybrid = fit_quantile_gbm(Xh, res, gp, cfg.seed)
    surv = survival_frame(rows)
    m.cap_days = float(surv["duration"].max()) if len(surv) else 0.0
    if surv["event"].sum() >= 2:
        if "cox" in cfg.methods:
            m.cox = CoxPH(sp["cox_penalizer"]).fit(surv[COX_FEATURES].to_numpy(float), surv["duration"].to_numpy(),
                                                   surv["event"].to_numpy())
        if "rsf" in cfg.methods:
            m.rsf = RandomSurvivalForest(sp["rsf_trees"], sp["rsf_max_depth"], sp["rsf_min_leaf"], 0.5,
                                         seed=cfg.seed).fit(surv[cols].to_numpy(float), surv["duration"].to_numpy(),
                                                            surv["event"].to_numpy(), surv["system_id"].to_numpy())
    return m, phys


def predict_chem(m: ChemModels, cfg: RunConfig, rows: pd.DataFrame, rpt: pd.DataFrame, cols: list[str],
                 overrides: Optional[dict] = None, keep_paths: bool = False, ml_rows: Optional[pd.DataFrame] = None) -> dict:
    """{method: DataFrame(p10_days, p50_days, p90_days, beyond, trigger)} for the given rows. Physics reads the
    unit history in `rows` (overrides act forward only); the ML / survival models read `ml_rows` (default `rows`)."""
    out = {}
    X = (ml_rows if ml_rows is not None else rows)[cols]
    phys = None
    if m.physics is not None:
        phys = physics_rows(m.physics, rows, rpt, overrides, keep_paths)
    if "physics" in cfg.methods and phys is not None:
        lo, hi = banded(phys["p50_days"].to_numpy(), m.band)
        out["physics"] = pd.DataFrame({"p10_days": np.minimum(lo, phys["p50_days"]), "p50_days": phys["p50_days"],
                                       "p90_days": np.maximum(hi, phys["p50_days"]), "beyond": phys["beyond"],
                                       "trigger": phys["trigger"]}, index=rows.index)
    def floor_band(q: dict) -> dict:
        """P10 / P90 at least as wide as the calibrated physics band around the method's own P50."""
        if not cfg.calibrate_bands or m.physics is None:
            return q
        lo, hi = banded(q["p50"], m.band)
        return {"p10": np.minimum(q["p10"], lo), "p50": q["p50"], "p90": np.maximum(q["p90"], hi)}

    if m.gbm:
        q = floor_band({k: np.maximum(v, 0.0) for k, v in predict_gbm(m.gbm, X).items()})
        out["gbm"] = pd.DataFrame({f"{k}_days": v for k, v in q.items()}, index=rows.index)
        out["gbm"]["beyond"], out["gbm"]["trigger"] = False, "regression"
    if m.hybrid and phys is not None:
        Xh = X.assign(phys_p50=phys["p50_days"].to_numpy())
        base = np.log1p(phys["p50_days"].to_numpy())
        q = floor_band({k: np.maximum(np.expm1(base + v), 0.0) for k, v in predict_gbm(m.hybrid, Xh).items()})
        out["hybrid"] = pd.DataFrame({f"{k}_days": v for k, v in q.items()}, index=rows.index)
        out["hybrid"]["beyond"], out["hybrid"]["trigger"] = phys["beyond"].to_numpy(), phys["trigger"].to_numpy()
    grid = np.arange(0, max(m.cap_days, 30) + 15, 15.0)
    for name, model in (("cox", m.cox), ("rsf", m.rsf)):
        if model is None:
            continue
        Xs = (ml_rows if ml_rows is not None else rows)[COX_FEATURES].to_numpy(float) if name == "cox" else X.to_numpy(float)
        if name == "cox":
            S, t = model.survival(Xs, grid), grid
        else:
            S, t = model.survival(Xs), model.grid
        q, beyond = quantile_times(t, S, m.cap_days)
        df = pd.DataFrame({f"{k}_days": v for k, v in q.items()}, index=rows.index)
        df["beyond"], df["trigger"] = beyond, "hazard"
        if keep_paths:
            df["surv_t"] = [t.tolist()] * len(df)
            df["surv_s"] = [s.tolist() for s in S]
        out[name] = df
    cpd = rows["cpd_recent"].fillna(rows["usage_cycles_per_day"]).to_numpy()
    if overrides and overrides.get("cpd") is not None:
        cpd = np.full(len(rows), float(overrides["cpd"]))
    for df in out.values():
        for q, _ in QUANTS:
            df[f"{q}_cycles"] = df[f"{q}_days"].to_numpy() * cpd
    if keep_paths and phys is not None:
        out["_paths"] = phys["proj"]
    return out


# ---------------------------------------------------------------- training run


def apply_overrides(rows: pd.DataFrame, overrides: Optional[dict]) -> pd.DataFrame:
    """What-if: duty (EFC per day) and temperature replace the features the ML / survival models read."""
    if not overrides:
        return rows
    rows = rows.copy()
    if overrides.get("cpd") is not None:
        rows["cpd_recent"] = rows["usage_cycles_per_day"] = float(overrides["cpd"])
    if overrides.get("temp") is not None:
        rows["temp_mean"] = rows["avg_cell_temp_c"] = float(overrides["temp"])
    return rows


def train(engine: Engine, cfg: RunConfig) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame, list[str]]:
    started = time.perf_counter()
    warnings: list[str] = []
    bad = [m for m in cfg.methods if m not in METHODS]
    if bad or not cfg.methods:
        raise RulError(f"Unknown or no method(s): {', '.join(bad)}")
    if not cfg.feature_groups or any(g not in F.FEATURE_GROUPS for g in cfg.feature_groups):
        raise RulError("Choose at least one valid feature group")
    if cfg.failures_as not in ("event", "censored"):
        raise RulError("failures_as must be 'event' or 'censored'")
    cols = feature_columns(cfg.feature_groups)
    fleet = F.load(engine, cfg.system_ids, cfg.failures_as)
    if fleet.rows.empty:
        raise RulError("No aging snapshots for the selected units")
    rows, rpt = fleet.rows, fleet.rpt
    backtest, forecasts, artifacts, params_out = [], [], {}, {}
    for chem, crow in rows.groupby("chemistry"):
        units = list(dict.fromkeys(crow["system_id"]))
        eol = F.eol_for(fleet.eol, chem)
        if chem not in fleet.eol:
            warnings.append(f"No eol_criteria for {chem} - using SOH {eol['soh_eol_pct']} % / R {eol['resistance_eol_pct']} %")
        n_retired = crow.groupby("system_id")["retired"].first().sum()
        if len(units) < 4 or n_retired < 2:
            warnings.append(f"{chem}: {len(units)} units, {n_retired} retired - too few to validate, left out")
            continue
        # leave-one-unit-out
        for u in units:
            tr = crow[crow["system_id"] != u]
            te = crow[crow["system_id"] == u]
            m, _ = fit_chem(cfg, chem, tr, rpt[rpt["system_id"].isin(tr["system_id"])], eol, cols)
            preds = predict_chem(m, cfg, te, rpt[rpt["system_id"] == u], cols)
            for meth, df in preds.items():
                if meth.startswith("_"):
                    continue
                backtest.append(df.assign(method=meth, system_id=u, fold=str(u)).join(
                    te[["snapshot_date", "rul_days", "rul_cycles", "known_alive_days", "retired", "life_fraction",
                        "duration", "event", "system_code"]]))
        # final model on every unit of the chemistry
        m, phys = fit_chem(cfg, chem, crow, rpt, eol, cols)
        artifacts[chem] = m
        latest = crow.sort_values("snapshot_date").groupby("system_id").tail(1)
        live = latest[~latest["retired"]]
        if len(live):
            preds = predict_chem(m, cfg, crow, rpt, cols)
            for meth, df in preds.items():
                if meth.startswith("_"):
                    continue
                forecasts.append(df.loc[live.index].assign(method=meth).join(
                    live[["system_id", "system_code", "snapshot_date", "soh_pct", "r_ratio"]]))
        params_out[chem] = {
            "physics": m.physics.to_dict() if m.physics else None, "band_log_q10_q90": list(m.band),
            "cox": m.cox.coefficients(COX_FEATURES) if m.cox else None,
            "rsf_importance": shares(dict(zip(cols, m.rsf.importance_.astype(float)))) if m.rsf else None,
            "gbm_importance": _gbm_importance(m.gbm, cols), "hybrid_importance": _gbm_importance(m.hybrid, cols + ["phys_p50"]),
            "eol": eol, "units": len(units), "retired_units": int(n_retired), "survival_cap_days": m.cap_days,
        }
    if not backtest:
        raise RulError("No chemistry had enough units to build a model")
    bt = pd.concat(backtest, ignore_index=True)
    fc = pd.concat(forecasts, ignore_index=True) if forecasts else pd.DataFrame()
    metrics = scores(bt, cfg.methods)
    artifact = {"cfg": cfg, "cols": cols, "models": artifacts, "eol": fleet.eol}
    summary = {
        "n_units": int(rows["system_id"].nunique()), "n_rows": int(len(rows)), "metrics": metrics,
        "results": {"params": params_out, "summary": headline(metrics, cfg.methods), "features": cols,
                    "units": fleet.units.assign(first_date=fleet.units["first_date"].dt.date.astype(str),
                                                last_date=fleet.units["last_date"].dt.date.astype(str))
                    [["system_id", "system_code", "chemistry", "batch_lot", "retired", "failed", "event_unit",
                      "snapshots", "first_date", "last_date"]].to_dict("records")},
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return artifact, summary, bt, fc, warnings


def _gbm_importance(models: dict, cols: list[str]) -> Optional[dict]:
    if not models:
        return None
    b = models["p50"].booster_
    return shares(dict(zip(b.feature_name(), b.feature_importance(importance_type="gain").astype(float))))


# ---------------------------------------------------------------- scores


def c_index(t: np.ndarray, e: np.ndarray, risk: np.ndarray) -> Optional[float]:
    """Harrell's C: among comparable pairs (the earlier time is an event), the share where the earlier one has the
    higher risk."""
    ok = np.isfinite(t) & np.isfinite(risk)
    t, e, r = t[ok], e[ok], risk[ok]
    if len(t) < 3:
        return None
    comp = (t[:, None] < t[None, :]) & (e[:, None] > 0)
    if not comp.any():
        return None
    conc = (r[:, None] > r[None, :]) & comp
    ties = (r[:, None] == r[None, :]) & comp
    return float((conc.sum() + 0.5 * ties.sum()) / comp.sum())


def _reg_scores(df: pd.DataFrame) -> dict:
    a = df["rul_days"].to_numpy()
    if not len(a):
        return {"n": 0}
    err = df["p50_days"].to_numpy() - a
    lo, md, hi = df["p10_days"].to_numpy(), df["p50_days"].to_numpy(), df["p90_days"].to_numpy()
    pin = np.mean([np.mean(np.maximum(q * (a - p), (q - 1) * (a - p))) for (_, q), p in zip(QUANTS, (lo, md, hi))])
    return {"n": int(len(a)), "mae_days": finite(np.mean(np.abs(err))), "rmse_days": finite(np.sqrt(np.mean(err ** 2))),
            "bias_days": finite(np.mean(err)),
            "mae_cycles": finite(np.mean(np.abs(df["p50_cycles"].to_numpy() - df["rul_cycles"].to_numpy()))),
            "coverage_pct": finite(100 * np.mean((a >= lo) & (a <= hi))), "pinball_days": finite(pin)}


def _censored_scores(df: pd.DataFrame) -> dict:
    c = df[~df["retired"] & (df["known_alive_days"] > 0)]
    if not len(c):
        return {}
    return {"censored_violation_pct": finite(100 * np.mean(c["p50_days"] < c["known_alive_days"])),
            "oracle_mae_days": finite(np.mean(np.abs(c["p50_days"] - c["rul_days"]))) if c["rul_days"].notna().any() else None}


def scores(bt: pd.DataFrame, methods: list[str]) -> dict:
    """{method: {scope: score}} - scope 'all', 'life:<bucket>', 'unit:<code>'."""
    out = {}
    for meth in methods:
        d = bt[bt["method"] == meth]
        if d.empty:
            continue
        ret = d[d["retired"]]
        s_all = {**_reg_scores(ret), **_censored_scores(d)}
        s_all["c_index"] = c_index(d["duration"].to_numpy(float), d["event"].to_numpy(float), -d["p50_days"].to_numpy(float))
        res = {"all": s_all}
        for lo, hi, name in LIFE_BUCKETS:
            k = (ret["life_fraction"] >= lo) & (ret["life_fraction"] < hi)
            res[f"life:{name}"] = _reg_scores(ret[k])
        for code, g in d.groupby("system_code"):
            res[f"unit:{code}"] = _reg_scores(g) if g["retired"].iloc[0] else {"n": int(len(g)), **_censored_scores(g)}
        out[meth] = res
    return out


def headline(metrics: dict, methods: list[str]) -> dict:
    keys = ("mae_days", "mae_cycles", "coverage_pct", "c_index", "censored_violation_pct", "oracle_mae_days", "bias_days")
    return {k: {m: metrics.get(m, {}).get("all", {}).get(k) for m in methods} for k in keys}


# ---------------------------------------------------------------- serving


def predict_unit(engine: Engine, art: dict, system_id: int, cpd: Optional[float] = None, temp: Optional[float] = None) -> dict:
    """What-if RUL of one unit at its latest snapshot (duty / temperature overrides), with the projected SOH and
    resistance paths, the survival curves and the unit's history."""
    cfg: RunConfig = art["cfg"]
    fleet = F.load(engine, None, cfg.failures_as)
    u = fleet.rows[fleet.rows["system_id"] == system_id]
    if u.empty:
        raise RulError(f"System {system_id} has no aging snapshots")
    chem = u["chemistry"].iloc[0]
    m: ChemModels = art["models"].get(chem)
    if m is None:
        raise RulError(f"No model for chemistry {chem} in this run")
    overrides = {"cpd": cpd, "temp": temp} if (cpd is not None or temp is not None) else None
    rows = u.sort_values("snapshot_date")
    last_idx = rows.index[-1]
    rows_last = rows.loc[[last_idx]]
    rpt = fleet.rpt[fleet.rpt["system_id"] == system_id]
    # physics reads the whole history up to the latest snapshot; the ML / survival models only the latest row (with
    # the what-if duty / temperature in place of the measured ones)
    preds = predict_chem(m, cfg, rows, rpt, art["cols"], overrides, keep_paths=True,
                         ml_rows=apply_overrides(rows, overrides))
    preds = {k: (v.loc[[last_idx]] if hasattr(v, "loc") else v) for k, v in preds.items()}
    last = rows.loc[last_idx]
    as_of = last["snapshot_date"]
    methods = {}
    for meth, df in preds.items():
        if meth.startswith("_"):
            continue
        r = df.loc[last_idx]
        methods[meth] = {
            **{f"{q}_days": finite(r[f"{q}_days"]) for q, _ in QUANTS},
            **{f"{q}_cycles": finite(r[f"{q}_cycles"]) for q, _ in QUANTS},
            "eol_date_p50": (as_of + pd.Timedelta(days=float(r["p50_days"]))).date().isoformat(),
            "beyond": bool(r["beyond"]), "trigger": r["trigger"],
        }
        if "surv_t" in df.columns:
            t, s = np.asarray(df.at[last_idx, "surv_t"]), np.asarray(df.at[last_idx, "surv_s"])
            step = max(1, len(t) // 120)
            methods[meth]["survival"] = [{"days": float(a), "s": float(b)} for a, b in zip(t[::step], s[::step])]
    paths = None
    if "_paths" in preds:
        pr = preds["_paths"].loc[last_idx]
        d = pr["days"]
        lim = int(min(len(d) - 1, np.searchsorted(d, max(methods.get("physics", methods.get("hybrid", {})).get("p90_days") or 0, 365) * 1.3)))
        sel = np.unique(np.linspace(0, lim, 160).astype(int))
        series = {k: np.asarray(pr[k]) for k in pr if k.startswith(("soh_", "r_"))}
        ph = methods.get("physics")
        if ph and ph["p50_days"]:
            # draw the band the RUL quantiles come from (calibrated): the P50 path run faster / slower in time
            for kind in ("soh", "r"):
                if f"{kind}_p50" not in series:
                    continue
                for q in ("p10", "p90"):
                    if ph[f"{q}_days"]:
                        k = ph["p50_days"] / ph[f"{q}_days"]
                        series[f"{kind}_{q}"] = np.interp(d * k, d, series[f"{kind}_p50"])
        paths = {"days": d[sel].tolist(), **{k: v[sel].tolist() for k, v in series.items()},
                 "factor_capacity": pr["factor_capacity"], "factor_resistance": pr["factor_resistance"]}
    unit = fleet.units[fleet.units["system_id"] == system_id].iloc[0]
    eol = F.eol_for(fleet.eol, chem)
    return {
        "system_id": system_id, "system_code": unit["system_code"], "chemistry": chem, "batch_lot": unit["batch_lot"],
        "retired": bool(unit["retired"]), "failed": bool(unit["failed"]), "as_of": as_of.date().isoformat(),
        "state": {"age_days": finite(last["age_days"]), "efc": finite(last["equiv_full_cycles"]),
                  "soh_pct": finite(last["soh_pct"]), "r_ratio": finite(last["r_ratio"]),
                  "cpd": finite(cpd if cpd is not None else last["cpd_recent"]),
                  "temp": finite(temp if temp is not None else last["temp_mean"]),
                  "cpd_actual": finite(u["cpd_recent"].iloc[-1]), "temp_actual": finite(u["temp_mean"].iloc[-1])},
        "eol": eol, "methods": methods, "paths": paths,
        "history": [{"date": r.snapshot_date.date().isoformat(), "age_days": finite(r.age_days),
                     "soh_pct": finite(r.soh_pct), "r_ratio": finite(r.r_ratio), "efc": finite(r.equiv_full_cycles)}
                    for r in u.itertuples()],
        "rpt": [{"date": r.test_date.date().isoformat(), "age_days": finite(r.age_days), "soh_pct": finite(r.soh_pct),
                 "r_ratio": finite(r.r_ratio)} for r in rpt.itertuples()],
    }
