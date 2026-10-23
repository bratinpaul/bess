"""One efficiency run: the three PCS conversion models on the same split, the cycles and their round-trip
efficiencies, the DC round-trip regression, and everything the pages show.

  1. operating points (features.build) -> train / test split (chronological per unit, or random);
  2. grey-box loss model on the training rows (the backbone; per-unit a / b / c too, as the health signal);
  3. GAM on the same rows;
  4. LightGBM / XGBoost on the grey-box residual -> the hybrid (grey-box + residual), TreeSHAP attribution;
  5. scores of each model (test and train, per unit, per direction, per load band);
  6. cycles of every unit: measured DC / AC / system RTE, and the AC / system RTE composed from the measured
     DC RTE and the hybrid model's conversion efficiency over the cycle's own readings;
  7. Ridge regression of the DC RTE on the cycle features (k-fold cross-validated).
"""
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from core.base import UseCaseError, split
from core.metrics import finite, regression_scores, shares
from usecases.efficiency import cycles as C
from usecases.efficiency import features as F
from usecases.efficiency.models import (BOOSTERS, EfficiencyError, GamEfficiencyModel, GreyBoxLossModel,
                                        loss_from_eta)

MODEL_KEYS = ("greybox", "gam", "hybrid")
LOAD_BANDS = [(0.0, 0.1, "< 10 %"), (0.1, 0.3, "10-30 %"), (0.3, 0.6, "30-60 %"), (0.6, 10.0, "≥ 60 %")]
MIN_ROWS = 200


@dataclass
class RunConfig:
    selection: F.Selection
    split_method: str = "chronological"
    test_fraction: float = 0.2
    seed: int = 42
    greybox_params: dict = field(default_factory=dict)
    gam_params: dict = field(default_factory=dict)
    booster: str = "lightgbm"
    booster_params: dict = field(default_factory=dict)
    cycle_options: C.CycleOptions = field(default_factory=C.CycleOptions)


@dataclass
class RunResult:
    artifact: dict
    summary: dict  # columns of battery_ml.efficiency_run
    cycles: pd.DataFrame
    warnings: list[str]


def _scores(y: np.ndarray, pred: np.ndarray, df: pd.DataFrame) -> dict:
    s = regression_scores(y, pred)
    loss_true = df["loss_kw"].to_numpy()
    loss_pred = loss_from_eta(df["load_frac"].to_numpy(), pred, df["is_charge"].to_numpy()) * df["rated_kw"].to_numpy()
    s["loss_mae_kw"] = finite(np.mean(np.abs(loss_pred - loss_true)))
    s["bias_pp"] = finite(np.mean(pred - y))
    s["n"] = int(len(y))
    return s


def train(engine: Engine, cfg: RunConfig) -> RunResult:
    started = time.perf_counter()
    sel = cfg.selection
    warnings: list[str] = []
    df = F.build(engine, sel)
    if len(df) < MIN_ROWS:
        raise EfficiencyError(f"Only {len(df)} active readings match the selection; at least {MIN_ROWS} are needed")
    features = sel.features
    booster_cls = BOOSTERS.get(cfg.booster)
    if booster_cls is None:
        raise EfficiencyError(f"Unknown residual model '{cfg.booster}' ({' or '.join(BOOSTERS)})")
    try:
        train_df, test_df = split(df, cfg.split_method, cfg.test_fraction, cfg.seed, "pcs_id")
    except UseCaseError as exc:  # the split's own messages are user-facing
        raise EfficiencyError(exc.public) from exc
    for d, label in ((1.0, "charge"), (0.0, "discharge")):
        if (train_df["is_charge"] == d).sum() < 20:
            warnings.append(f"Few {label} readings in the training rows: the {label} curve is uncertain")
    y_tr, y_te = train_df[F.TARGET].to_numpy(), test_df[F.TARGET].to_numpy()

    # 2. grey-box (pooled with unit offsets) + one per unit for the a / b / c health signal
    gb = GreyBoxLossModel(cfg.greybox_params).fit(train_df, (train_df["loss_kw"] / train_df["rated_kw"]).to_numpy())
    per_unit: dict[str, dict] = {}
    for unit, g in train_df.groupby("pcs_id"):
        if len(g) < 50:
            continue
        # plain a / b / c per unit (no temperature / voltage terms: with one unit's readings they trade off against b, c)
        m = GreyBoxLossModel({**cfg.greybox_params, "unit_offsets": False, "temp_dependence": False,
                              "voltage_dependence": False}).fit(g, (g["loss_kw"] / g["rated_kw"]).to_numpy())
        per_unit[str(unit)] = m.coefficients()["directions"]

    # 3. GAM
    gam = GamEfficiencyModel(cfg.gam_params).fit(train_df, y_tr, features)

    # 4. residual booster on the grey-box
    res_features = features + (["pcs_id"] if "age_years" in features else [])
    gb_tr, gb_te = gb.predict_eta_pct(train_df), gb.predict_eta_pct(test_df)
    booster = booster_cls(cfg.booster_params, cfg.seed).fit(train_df[res_features], y_tr - gb_tr,
                                                            test_df[res_features], y_te - gb_te)
    preds = {
        "greybox": (gb_tr, gb_te),
        "gam": (gam.predict(train_df), gam.predict(test_df)),
        "hybrid": (np.clip(gb_tr + booster.predict(train_df), 50, 100), np.clip(gb_te + booster.predict(test_df), 50, 100)),
    }

    # 5. scores
    metrics = {k: {"test": _scores(y_te, p_te, test_df), "train": _scores(y_tr, p_tr, train_df)}
               for k, (p_tr, p_te) in preds.items()}
    by_unit, by_dir, by_band = {}, {}, {}
    for unit, idx in test_df.groupby("pcs_id").indices.items():
        by_unit[str(unit)] = {k: _scores(y_te[idx], preds[k][1][idx], test_df.iloc[idx]) for k in MODEL_KEYS}
    for d, label in ((1.0, "charge"), (0.0, "discharge")):
        idx = np.flatnonzero(test_df["is_charge"].to_numpy() == d)
        if len(idx):
            by_dir[label] = {k: _scores(y_te[idx], preds[k][1][idx], test_df.iloc[idx]) for k in MODEL_KEYS}
    lf = test_df["load_frac"].to_numpy()
    for lo, hi, label in LOAD_BANDS:
        idx = np.flatnonzero((lf >= lo) & (lf < hi))
        if len(idx):
            by_band[label] = {k: _scores(y_te[idx], preds[k][1][idx], test_df.iloc[idx]) for k in MODEL_KEYS}
    best = min(MODEL_KEYS, key=lambda k: metrics[k]["test"]["rmse"] or 1e9)

    # SHAP on the residual (test rows, at most 3000)
    sample = test_df.sample(n=min(3000, len(test_df)), random_state=cfg.seed)
    sv, _ = booster.shap(sample)
    shap_global = shares({f: float(np.mean(np.abs(sv[:, j]))) for j, f in enumerate(booster.features)})
    shap_mean_abs = {f: float(np.mean(np.abs(sv[:, j]))) for j, f in enumerate(booster.features)}

    # health: weekly loss index per unit = measured loss / pooled grey-box loss (1.0 = as modelled)
    all_df = pd.concat([train_df.assign(set="train"), test_df.assign(set="test")])
    all_df["gb_loss_kw"] = gb.predict_loss_pu(all_df) * all_df["rated_kw"]
    week = all_df["ts"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time
    weekly = all_df.assign(week=week).groupby(["pcs_id", "week"]).agg(
        loss=("loss_kw", "sum"), gb=("gb_loss_kw", "sum"), n=("loss_kw", "size"), eta=(F.TARGET, "mean")).reset_index()
    health = {
        "per_unit": per_unit,
        "loss_index": [{"pcs_id": int(r.pcs_id), "week": r.week.date().isoformat(), "index": float(r.loss / r.gb),
                        "n": int(r.n), "eta_mean": float(r.eta)} for r in weekly.itertuples() if r.gb > 0 and r.n >= 20],
    }

    # model curves: η vs load per direction at each unit's median conditions
    units = F.units(engine)
    unit_rows = {int(u.pcs_id): F.unit_info(u) for _, u in units.iterrows() if int(u.pcs_id) in sel.pcs_ids}
    medians = {int(u): g[features].median().to_dict() for u, g in df.groupby("pcs_id")}
    art: dict[str, Any] = {
        "profiles": {int(u): operating_profile(g, features) for u, g in df.groupby("pcs_id")},
        "greybox": gb, "gam": gam, "booster": booster, "features": features, "residual_features": res_features,
        "units": unit_rows, "medians": medians, "ranges": {f: {"min": float(df[f].min()), "max": float(df[f].max())}
                                                           for f in features},
        "min_load_frac": sel.min_load_frac,
    }
    curves = {str(u): model_curves(art, u) for u in medians}

    # 6. cycles with the composed RTEs
    split_at = {int(u): g["ts"].min() for u, g in test_df.groupby("pcs_id")} if cfg.split_method == "chronological" else {}
    cyc_parts = []
    for u in sel.pcs_ids:
        info = unit_rows.get(u)
        if not info or not info.get("rated_power_kw"):
            continue
        s = C.series(engine, info, sel.date_from, sel.date_to)
        cyc = C.extract(s, info, cfg.cycle_options)
        if cyc.empty:
            continue
        eta_c, eta_d = _cycle_conversion(art, s, units, cyc)
        cyc = C.composed(cyc, eta_c, eta_d)
        cyc["set"] = np.where(cyc["start_ts"] >= split_at[u], "test", "train") if u in split_at else "all"
        cyc_parts.append(cyc)
    cyc = pd.concat(cyc_parts, ignore_index=True) if cyc_parts else pd.DataFrame()

    # 7. DC round-trip regression
    rte: dict[str, Any] = {"n_cycles": int(len(cyc))}
    dc_art = None
    if not cyc.empty:
        closed = cyc[cyc["closed"] & cyc["complete"]]
        rte["n_closed"] = int(len(closed))
        for k in ("rte_dc_pct", "rte_ac_pct", "rte_sys_pct", "rte_ac_comp_pct", "rte_sys_comp_pct"):
            v = closed[k].dropna()
            rte[k] = {"mean": finite(v.mean()) if len(v) else None, "median": finite(v.median()) if len(v) else None,
                      "min": finite(v.min()) if len(v) else None, "max": finite(v.max()) if len(v) else None}
        ok = closed.dropna(subset=["rte_ac_pct", "rte_ac_comp_pct"])
        if len(ok) > 1:
            rte["ac_composition_scores"] = regression_scores(ok["rte_ac_pct"].to_numpy(), ok["rte_ac_comp_pct"].to_numpy())
        ok = closed.dropna(subset=["rte_sys_pct", "rte_sys_comp_pct"])
        if len(ok) > 1:
            rte["sys_composition_scores"] = regression_scores(ok["rte_sys_pct"].to_numpy(), ok["rte_sys_comp_pct"].to_numpy())
        rte["per_unit"] = {str(u): {"kwh_per_pct": finite(g["kwh_per_pct"].iloc[0]),
                                    "aux_kw_avg": finite(g["aux_kw_avg"].mean()),
                                    "hvac_kw_avg": finite(g["hvac_kw_avg"].mean()),
                                    "rte_dc_median": finite(g.loc[g["closed"], "rte_dc_pct"].median()),
                                    "cycles": int(len(g))} for u, g in cyc.groupby("pcs_id")}
        dc_art, w = C.fit_dc_rte(cyc, seed=cfg.seed)
        warnings += w
        if dc_art:
            cyc["rte_dc_pred_pct"] = cyc.index.map(dc_art.pop("cv_pred")).astype(float)
            rte["dc_model"] = {k: v for k, v in dc_art.items() if k not in ("model",)}
            rte["dc_model"]["labels"] = {f: C.CYCLE_FEATURES[f] for f in dc_art["features"]}
        med = rte["rte_dc_pct"]["median"]
        if med is not None and med >= 100:
            warnings.append(
                f"The measured DC round-trip is {med:.1f} % (median of closed cycles), above 100 %: the BMS charge / "
                "discharge counters return more energy than they take in, so they carry no battery losses. The AC and "
                "system RTE inherit it; the PCS conversion models are not affected.")
    else:
        warnings.append("No complete charge-discharge cycle was found in the selection")
    art["dc_rte"] = dc_art
    art["rte_units"] = rte.get("per_unit", {})

    # predictions for the chart: all test rows up to 2500, and up to 1500 training rows
    def pick(frame: pd.DataFrame, p: dict[str, np.ndarray], n: int, label: str) -> list[dict]:
        idx = np.arange(len(frame))
        if len(idx) > n:
            idx = np.sort(np.random.default_rng(cfg.seed).choice(idx, n, replace=False))
        return [{"ts": frame["ts"].iloc[i].isoformat(), "pcs_id": int(frame["pcs_id"].iloc[i]),
                 "load_frac": round(float(frame["load_frac"].iloc[i]), 4), "charge": bool(frame["is_charge"].iloc[i] > 0),
                 "actual": float(frame[F.TARGET].iloc[i]),
                 **{k: round(float(p[k][i]), 4) for k in MODEL_KEYS}, "set": label} for i in idx]

    predictions = pick(train_df, {k: v[0] for k, v in preds.items()}, 1500, "train") + \
        pick(test_df, {k: v[1] for k, v in preds.items()}, 2500, "test")

    gain = booster.gain_importance()
    if (y_te.std() < 0.05):
        warnings.append("The measured efficiency hardly varies in the test rows: R² is not meaningful, read MAE / RMSE")
    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = {
        "features": features, "residual_features": res_features, "n_points": int(len(df)),
        "n_train": int(len(train_df)), "n_test": int(len(test_df)), "n_cycles": int(len(cyc)),
        "split": {"train_from": train_df["ts"].min().isoformat(), "train_to": train_df["ts"].max().isoformat(),
                  "test_from": test_df["ts"].min().isoformat(), "test_to": test_df["ts"].max().isoformat(),
                  "eta_min": float(df[F.TARGET].min()), "eta_max": float(df[F.TARGET].max()),
                  "eta_std": float(df[F.TARGET].std())},
        "metrics": metrics, "best_model": best,
        "metrics_detail": {"by_unit": by_unit, "by_direction": by_dir, "by_load_band": by_band},
        "greybox": {**gb.coefficients(), "params": gb.params},
        "gam": {"params": gam.params, "partial_dependence": gam.partial_dependence(train_df)},
        "shap": {"share": shap_global, "mean_abs_pp": shap_mean_abs, "gain_share": shares(gain), "n": int(len(sample))},
        "health": health, "curves": curves, "rte": rte, "boost_curve": booster.curve,
        "predictions": predictions, "duration_ms": duration_ms,
    }
    return RunResult(artifact=art, summary=summary, cycles=cyc, warnings=warnings)


def _cycle_conversion(art: dict, s: pd.DataFrame, units: pd.DataFrame, cyc: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Energy-weighted predicted conversion efficiency of each cycle's charge and discharge readings."""
    unit = int(s["pcs_id"].iloc[0])
    rows = F.derive(s.drop(columns=["efficiency_pct"]), units)
    rows = rows[rows["load_frac"] >= art["min_load_frac"]].copy()
    for f in art["features"]:
        if rows[f].isna().any():
            rows[f] = rows[f].fillna(art["medians"].get(unit, {}).get(f, 0.0))
    eta_c, eta_d = pd.Series(np.nan, index=cyc.index), pd.Series(np.nan, index=cyc.index)
    if rows.empty:
        return eta_c, eta_d
    rows["eta"] = predict_frame(art, rows)["hybrid"]
    for i, c in cyc.iterrows():
        w = rows[(rows["ts"] >= c["start_ts"]) & (rows["ts"] < c["end_ts"])]
        ch, di = w[w["is_charge"] > 0], w[w["is_charge"] == 0]
        if len(ch):
            eta_c[i] = 100 * (ch["p_ac_kw"] * ch["eta"] / 100).sum() / ch["p_ac_kw"].sum()
        if len(di):
            eta_d[i] = 100 * di["p_ac_kw"].sum() / (di["p_ac_kw"] / (di["eta"] / 100)).sum()
    return eta_c, eta_d


# ---------------------------------------------------------------- inference


def predict_frame(art: dict, X: pd.DataFrame) -> dict[str, np.ndarray]:
    """η (%) of every model for model rows (features.derive output, or built by the estimator)."""
    gb: GreyBoxLossModel = art["greybox"]
    gb_eta = gb.predict_eta_pct(X)
    res = art["booster"].predict(X)
    return {"greybox": gb_eta, "gam": art["gam"].predict(X), "hybrid": np.clip(gb_eta + res, 50, 100), "residual": res}


def s_frac_of(art: dict, unit: int, load_frac, pf: float):
    """|S| / rated kVA of a load fraction at a power factor."""
    info = art["units"].get(unit, {})
    ratio = (info.get("rated_power_kw") or 1.0) / (info.get("rated_kva") or info.get("rated_power_kw") or 1.0)
    return np.asarray(load_frac) * ratio / np.clip(np.abs(pf), 0.5, None)


PROFILE_BIN = 0.05


def operating_profile(g: pd.DataFrame, features: list[str]) -> dict:
    """Per direction, the median of every input per 5 % load bin: how temperatures, voltage and PF go with the load
    on this unit. Curves drawn along it stay inside the data (a light-load point at full-load temperatures is not
    an operating point)."""
    out = {}
    for direction, flag in (("charge", 1.0), ("discharge", 0.0)):
        d = g[g["is_charge"] == flag]
        if len(d) < 10:
            continue
        b = (d["load_frac"] // PROFILE_BIN).astype(int)
        med = d.groupby(b)[features].median()
        med = med[d.groupby(b).size() >= 5]
        if med.empty:
            continue
        out[direction] = {"load": med["load_frac"].tolist(), **{f: med[f].tolist() for f in features},
                          "observed": [float(d["load_frac"].quantile(0.01)), float(d["load_frac"].quantile(0.99))]}
    return out


def model_curves(art: dict, unit: int, conditions: Optional[dict] = None, n: int = 41) -> dict:
    """η vs load fraction, per direction and model. Without conditions: along the unit's operating profile (the
    inputs as they go with the load in its data); with conditions: those inputs held fixed at every load."""
    lo = max(0.02, art["min_load_frac"])
    grid = np.linspace(lo, 1.0, n)
    profiles = art.get("profiles", {}).get(unit, {})
    out = {}
    for direction, flag in (("charge", 1.0), ("discharge", 0.0)):
        prof = profiles.get(direction)
        if conditions is None and prof:
            frame = pd.DataFrame({f: np.interp(grid, prof["load"], prof[f]) for f in art["features"]})
        else:
            base = {**art["medians"].get(unit, {}), **(conditions or {})}
            frame = pd.DataFrame([base] * n)
        frame["pcs_id"] = unit
        frame["load_frac"] = grid
        frame["is_charge"] = flag
        frame["s_frac"] = s_frac_of(art, unit, grid, frame["pf_abs"].to_numpy() if "pf_abs" in frame else 1.0)
        p = predict_frame(art, frame)
        out[direction] = {"observed": prof["observed"] if prof else None,
                          "points": [{"load_frac": float(x), **{k: float(p[k][i]) for k in MODEL_KEYS}}
                                     for i, x in enumerate(grid)]}
    return out
