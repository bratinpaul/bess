"""Expected loss per stage at the operating conditions of every interval - the benchmark the actual loss is compared to.

Each stage has a small physics-shaped (grey-box) model, fitted on a baseline window (the commissioning reference;
default the first days of the run) with bounded least squares, then applied to every interval:

  battery   overpotential per cell  dV = r0 + R·|I| + kT·|I|·(25 - T_cell) + s1·u + s2·u²,  u = (SOC - 50) / 50
            per direction (R >= 0; the SOC terms carry the OCV-curve shape the telemetry doesn't follow)
            expected loss = cells · dV · |I|, scaled by resistance growth (1 + g·(SOH_baseline - SOH)) so the
            benchmark ages with the battery (g = % resistance growth per SOH point lost)
  PCS       P_loss = a + b·s + c·s² + d·s·(T_igbt - 25),   s = |S| / rated kVA       per direction (a, b, c >= 0);
            idle intervals: the baseline idle mean
  xfmr      nameplate core + copper·(S/S_rated)²; when the POI meter shows a transformer residual, core and copper
            are also fitted to it (reported next to the nameplate)
  aux       aux_kw = c0 + c1·|P_dc| + c2·T_amb + c3·max(T_amb - 25, 0)            (HVAC heat load + ambient)
  standby   self_discharge_pct_day x kWh per % over the rest hours

The temperature terms (kT, d) are kept only when they lower the error on the last 30 % of the baseline (time hold-out):
fitted on a week they easily pick up day-to-day noise and then bias the benchmark for the rest of the window.

The excess (actual - expected) is the benchmark residual: persistently positive on one stage = a fault signature.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear

from usecases.loss.ledger import Ledger, LedgerSettings


@dataclass
class BenchmarkSettings:
    baseline_days: int = 7                    # first N days of the run; 0 = the whole window
    resistance_growth_pct_per_soh: float = 3.3  # R doubles at SOH 70 % (LFP EOL criterion)
    self_discharge_pct_day: Optional[float] = None  # None -> battery_opt_param, else 0.03
    ref_load_frac: float = 0.5                # reference conditions for normalized efficiencies
    ref_temp_c: float = 25.0
    ref_ambient_c: float = 30.0


def _r2(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    if len(y) < 3 or np.var(y) <= 0:
        return None
    return float(1 - np.sum((y - p) ** 2) / np.sum((y - np.mean(y)) ** 2))


def _fit(X: np.ndarray, y: np.ndarray, lower: list[float]) -> np.ndarray:
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 2:
        return np.zeros(X.shape[1])
    return lsq_linear(X[ok], y[ok], bounds=(np.array(lower), np.full(X.shape[1], np.inf)), method="bvls").x


def _fit_select(X: np.ndarray, y: np.ndarray, lower: list[float], optional: list[int],
                ts: np.ndarray) -> tuple[np.ndarray, bool]:
    """Fit with and without the optional columns on the first 70 % of the rows (in time), keep the variant with the
    lower MAE on the last 30 %, refit it on all rows. Returns the coefficients (dropped columns = 0) and whether the
    optional terms were kept."""
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y, ts = X[ok], y[ok], ts[ok]
    keep = [i for i in range(X.shape[1]) if i not in optional]
    if len(y) < 2 * (X.shape[1] + 2):
        coef = np.zeros(X.shape[1])
        coef[keep] = _fit(X[:, keep], y, [lower[i] for i in keep])
        return coef, False
    order = np.argsort(ts)
    cut = order[: int(len(order) * 0.7)]
    val = order[int(len(order) * 0.7):]
    full = _fit(X[cut], y[cut], lower)
    red = _fit(X[cut][:, keep], y[cut], [lower[i] for i in keep])
    mae_full = np.mean(np.abs(X[val] @ full - y[val]))
    mae_red = np.mean(np.abs(X[val][:, keep] @ red - y[val]))
    use_full = bool(mae_full < 0.98 * mae_red)  # the extra terms must earn their place
    coef = np.zeros(X.shape[1])
    if use_full:
        coef = _fit(X, y, lower)
    else:
        coef[keep] = _fit(X[:, keep], y, [lower[i] for i in keep])
    return coef, use_full


def _scores(y: np.ndarray, p: np.ndarray) -> dict:
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() == 0:
        return {"n": 0}
    return {"n": int(ok.sum()), "r2": _r2(y[ok], p[ok]), "mae_kw": float(np.mean(np.abs(y[ok] - p[ok]))),
            "bias_kw": float(np.mean(p[ok] - y[ok]))}


def baseline_mask(df: pd.DataFrame, days: int) -> pd.Series:
    if days <= 0:
        return pd.Series(True, index=df.index)
    first = df["ts"].dt.normalize().min()
    return df["ts"] < first + pd.Timedelta(days=days)


def fit_and_apply(led: Ledger, lcfg: LedgerSettings, bcfg: BenchmarkSettings, self_discharge_master: Optional[float],
                  rated_kva: float) -> dict:
    """Fits the stage models on the baseline rows, writes exp_*_kw (and the fixed / variable split) into led.df and
    returns the models with their fit scores."""
    df = led.df
    base = baseline_mask(df, bcfg.baseline_days)
    models: dict = {"baseline": {"days": bcfg.baseline_days, "from": df.loc[base, "ts"].min().isoformat(),
                                 "to": df.loc[base, "ts"].max().isoformat(), "rows": int(base.sum())}}
    ts_num = df["ts"].astype("int64").to_numpy()
    soh_base = float(df.loc[base, "soh_pct"].mean()) if df.loc[base, "soh_pct"].notna().any() else None
    models["baseline"]["soh_pct"] = soh_base

    # ---- battery: overpotential per cell vs current and temperature
    cells = led.cells_series or 0
    i_abs = df["pack_current_a"].abs()
    dv = np.where(df["pack_current_a"] != 0, (df["cell_v_avg_v"] - df["ocv_cell_v"]) * np.sign(df["pack_current_a"]), np.nan)
    growth = 1 + bcfg.resistance_growth_pct_per_soh / 100 * ((soh_base - df["soh_pct"]) if soh_base is not None else 0)
    growth = growth.fillna(1.0).clip(lower=0.5) if isinstance(growth, pd.Series) else pd.Series(1.0, index=df.index)
    exp_batt = np.zeros(len(df))
    batt_models = {}
    for d in ("CHARGE", "DISCHARGE"):
        rows = (df["direction"] == d).to_numpy()
        u = (df["soc_pct"].fillna(50) - 50) / 50
        X = np.column_stack([np.ones(len(df)), i_abs, i_abs * (bcfg.ref_temp_c - df["cell_temp_avg_c"]), u, u ** 2])
        fit_rows = rows & base.to_numpy() & np.isfinite(dv)
        temp_kept = False
        if cells and df["ocv_cell_v"].notna().any():
            coef, temp_kept = _fit_select(X[fit_rows], dv[fit_rows], [-np.inf, 0.0, -np.inf, -np.inf, -np.inf], [2],
                                          ts_num[fit_rows])
        else:
            coef = np.zeros(5)
        dv_hat = np.clip(X @ coef, 0, None)
        exp_batt[rows] = (cells * dv_hat * i_abs / 1000 * growth)[rows]
        act = df["loss_batt_kw"].to_numpy()
        batt_models[d] = {"r0_v": float(coef[0]), "r_ohm_pack": float(coef[1] * cells),
                          "r_mohm_cell_equiv": float(coef[1] * 1000), "kt_per_c": float(coef[2]),
                          "soc_lin_v": float(coef[3]), "soc_quad_v": float(coef[4]), "temperature_term": temp_kept,
                          "fit": _scores(act[fit_rows], exp_batt[fit_rows]),
                          "out_of_baseline": _scores(act[rows & ~base.to_numpy()], exp_batt[rows & ~base.to_numpy()])}
    models["battery"] = {"cells_series": cells, "soh_growth_pct_per_pt": bcfg.resistance_growth_pct_per_soh,
                         "directions": batt_models}
    df["exp_batt_kw"] = exp_batt

    # ---- PCS: a + b s + c s^2 + d s (T - 25)
    s = df["s_kva"] / rated_kva
    t_igbt = df["igbt_temp_c"].fillna(df["igbt_temp_c"].median() if df["igbt_temp_c"].notna().any() else 25.0)
    exp_pcs = np.zeros(len(df))
    fixed_pcs = np.zeros(len(df))
    pcs_models = {}
    for d in ("CHARGE", "DISCHARGE"):
        rows = (df["direction"] == d).to_numpy()
        X = np.column_stack([np.ones(len(df)), s, s ** 2, s * (t_igbt - bcfg.ref_temp_c)])
        fit_rows = rows & base.to_numpy()
        coef, temp_kept = _fit_select(X[fit_rows], df["loss_pcs_kw"].to_numpy()[fit_rows], [0.0, 0.0, 0.0, -np.inf], [3],
                                      ts_num[fit_rows])
        exp_pcs[rows] = (X @ coef)[rows]
        fixed_pcs[rows] = coef[0]
        act = df["loss_pcs_kw"].to_numpy()
        ref_s = bcfg.ref_load_frac
        ref_loss = coef[0] + coef[1] * ref_s + coef[2] * ref_s ** 2
        pcs_models[d] = {"a_kw": float(coef[0]), "b_kw": float(coef[1]), "c_kw": float(coef[2]), "d_kw_per_c": float(coef[3]),
                         "temperature_term": temp_kept,
                         "eta_ref_pct": float(100 * (1 - ref_loss / (ref_s * rated_kva))) if ref_s > 0 else None,
                         "fit": _scores(act[fit_rows], exp_pcs[fit_rows]),
                         "out_of_baseline": _scores(act[rows & ~base.to_numpy()], exp_pcs[rows & ~base.to_numpy()])}
    idle = (df["direction"] == "IDLE").to_numpy()
    idle_mean = float(df.loc[idle & base.to_numpy(), "loss_pcs_kw"].mean()) if (idle & base.to_numpy()).any() else 0.0
    exp_pcs[idle] = idle_mean
    fixed_pcs[idle] = df.loc[idle, "loss_pcs_kw"].clip(lower=0)
    models["pcs"] = {"rated_kva": rated_kva, "idle_kw": idle_mean, "directions": pcs_models}
    df["exp_pcs_kw"] = exp_pcs

    # ---- transformer: nameplate (expected) + a core / copper fit to the metered residual
    core_np, cu_np = df["xfmr_core_model_kw"].to_numpy(), df["xfmr_cu_model_kw"].to_numpy()
    resid = df["xfmr_residual_kw"].to_numpy()
    metered = led.stats["xfmr_residual_abs_mean_kw"] > 0.05
    Xx = np.column_stack([np.ones(len(df)), (df["s_kva"] / led.xfmr_kva) ** 2])
    fit = _fit(Xx[base.to_numpy()], resid[base.to_numpy()], [0.0, 0.0]) if metered else np.zeros(2)
    if lcfg.transformer_mode == "metered" and not metered:
        df["exp_xfmr_kw"] = 0.0  # nothing is metered, so nothing is expected on this boundary
        fixed_x, var_x = np.zeros(len(df)), np.zeros(len(df))
    else:
        df["exp_xfmr_kw"] = core_np + cu_np
        if lcfg.transformer_mode == "model":
            fixed_x, var_x = core_np, cu_np
        else:  # metered residual split with the fitted core / copper shares
            tot = fit[0] + fit[1] * (df["s_kva"] / led.xfmr_kva) ** 2
            share = np.where(tot > 0, fit[0] / tot, 1.0)
            fixed_x = df["loss_xfmr_kw"].clip(lower=0).to_numpy() * share
            var_x = df["loss_xfmr_kw"].clip(lower=0).to_numpy() - fixed_x
    models["transformer"] = {"mode": lcfg.transformer_mode, "rating_kva": led.xfmr_kva, "rating_source": led.xfmr_source,
                             "nameplate_core_kw": float(core_np[0]) if len(core_np) else 0.0,
                             "nameplate_cu_at_rated_kw": lcfg.xfmr_cu_pct / 100 * led.xfmr_kva,
                             "metered_residual": bool(metered),
                             "fitted_core_kw": float(fit[0]) if metered else None,
                             "fitted_cu_at_rated_kw": float(fit[1]) if metered else None,
                             "residual_abs_mean_kw": led.stats["xfmr_residual_abs_mean_kw"]}

    # ---- auxiliaries: heat load + ambient
    amb = df["ambient_c"].fillna(df["pcs_ambient_c"])
    amb = amb.fillna(amb.median() if amb.notna().any() else 25.0)
    p_dc = df["p_dc_kw"].abs()
    Xa = np.column_stack([np.ones(len(df)), p_dc, amb, np.maximum(amb - 25.0, 0)])
    ca = _fit(Xa[base.to_numpy()], df["aux_kw"].to_numpy()[base.to_numpy()], [0.0, 0.0, -np.inf, -np.inf])
    df["exp_aux_kw"] = np.clip(Xa @ ca, 0, None)
    var_aux = np.minimum(df["aux_kw"].clip(lower=0), ca[1] * p_dc).to_numpy()
    ctrl = float(df.loc[base, "aux_ctrl_kw"].median()) if df.loc[base, "aux_ctrl_kw"].notna().any() else None
    models["aux"] = {"c0_kw": float(ca[0]), "c1_kw_per_kw": float(ca[1]), "c2_kw_per_c": float(ca[2]),
                     "c3_kw_per_c_above_25": float(ca[3]), "controls_base_kw": ctrl,
                     "ref_aux_kw": float(ca[0] + ca[1] * bcfg.ref_load_frac * rated_kva + ca[2] * bcfg.ref_ambient_c
                                         + ca[3] * max(bcfg.ref_ambient_c - 25, 0)),
                     "fit": _scores(df.loc[base, "aux_kw"].to_numpy(), df.loc[base, "exp_aux_kw"].to_numpy()),
                     "out_of_baseline": _scores(df.loc[~base, "aux_kw"].to_numpy(), df.loc[~base, "exp_aux_kw"].to_numpy())}

    # ---- standby
    sd = bcfg.self_discharge_pct_day if bcfg.self_discharge_pct_day is not None else (
        self_discharge_master if self_discharge_master is not None else 0.03)
    rest = (df["direction"] == "IDLE") & (df["pack_current_a"].abs().fillna(0) < 1.0)
    df["exp_standby_kw"] = np.where(rest, sd * led.kwh_per_pct / 24.0, 0.0)
    models["standby"] = {"self_discharge_pct_day": sd, "source": "parameter" if bcfg.self_discharge_pct_day is not None
                         else ("battery_opt_param" if self_discharge_master is not None else "default"),
                         "kwh_per_pct": led.kwh_per_pct, "expected_kw_at_rest": sd * led.kwh_per_pct / 24.0}

    # ---- fixed (load-independent) vs variable (load-dependent) loss, kW
    fixed = fixed_pcs.clip(min=0) + fixed_x + df["aux_kw"].clip(lower=0).to_numpy() - var_aux + df["standby_kw"].to_numpy()
    total = (df[["loss_batt_kw", "loss_dc_kw", "loss_pcs_kw", "loss_xfmr_kw"]].clip(lower=0).sum(axis=1)
             + df["aux_kw"].clip(lower=0) + df["standby_kw"]).to_numpy()
    fixed = np.minimum(fixed, total)
    df["fixed_kw"], df["variable_kw"] = fixed, total - fixed
    df["is_baseline"] = base.to_numpy()

    # ---- reference conditions (for the normalized efficiencies)
    models["reference"] = {"load_frac": bcfg.ref_load_frac, "temp_c": bcfg.ref_temp_c, "ambient_c": bcfg.ref_ambient_c}
    return models
