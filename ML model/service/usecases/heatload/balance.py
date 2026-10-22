"""The enclosure heat balance per interval, and its calibration against a measured reference.

    Q_reject = Q_batt + Q_pcs + Q_aux  +  Q_solar + Q_env  -  C · dT/dt

  Q_batt,irr = I·(V - U_ocv)                 ohmic + overpotential (Bernardi), always heating; I + on charge
  Q_batt,rev = I·T·dU/dT                     entropic; dU/dT per cell from the OCV curve at 10 / 25 / 40 °C; its sign
                                             flips between charge and discharge
  Q_pcs      = |P_dc - P_ac| · pcs_inside    conversion loss (when the PCS sits in the cooled enclosure)
  Q_aux      = (aux_load - hvac) · aux_inside  controls / comms electronics
  Q_solar    = α · A_sun · G                 G = measured GHI where the site has a station, else clear-sky
  Q_env      = UA · (T_amb - T_setpoint)     a gain on hot afternoons, a loss at night (enclosure held at setpoint)
  Q_storage  = C · dT_cell/dt                C = thermal mass of the cells (kJ/K per kWh of capacity x capacity)

Q_total (generation + gains) with the nameplate parameters is the physics prediction; the balance residual is
Q_total - Q_storage - measured. The calibrated grey-box scales each term (k >= 0, charge and discharge battery heat
apart) to the measured reference on the training rows - the fitted k say which nameplate assumption is off.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear

from usecases.heatload import data as D
from usecases.loss.data import ocv_lookup

TERMS = ["q_batt_irr_kw", "q_batt_rev_kw", "q_pcs_kw", "q_aux_kw", "q_solar_kw", "q_env_kw"]
REFERENCES = {"heat_load_sensor": "heat_load_sensor_kw", "cooling_delivered": "cooling_kw"}


@dataclass
class BalanceSettings:
    measured_reference: str = "heat_load_sensor"   # heat_load_sensor | cooling_delivered
    envelope_area_m2: float = 74.0                # 20 ft ISO container, all six faces
    u_value_w_m2k: float = 0.5                    # insulated panel
    sunlit_area_m2: float = 22.0                  # roof + half of one long side
    absorptivity: float = 0.6                     # light-grey paint
    pcs_inside: bool = True
    aux_inside: bool = True
    thermal_mass_kj_k_per_kwh: float = 7.0        # ≈ 7 kg of cell per kWh × 1 kJ/kg·K
    solar_source: str = "auto"                    # auto (measured, else clear-sky) | clear_sky | none
    idle_frac: float = 0.01
    train_frac: float = 0.75
    internal_setpoint_c: float = 25.0             # the enclosure setpoint the HVAC holds


def entropic_dudt(ocv: Optional[pd.DataFrame], soc: np.ndarray) -> np.ndarray:
    """dU/dT per cell (V/K) at each SOC: least-squares slope of the OCV across the table's temperatures."""
    if ocv is None or ocv.shape[1] < 2:
        return np.zeros(len(soc))
    temps = ocv.columns.to_numpy(dtype=float)
    socs = ocv.index.to_numpy(dtype=float)
    s = np.clip(np.nan_to_num(soc, nan=50.0), socs[0], socs[-1])
    vals = np.stack([np.interp(s, socs, ocv[t].to_numpy(dtype=float)) for t in temps], axis=1)
    tc = temps - temps.mean()
    return (vals - vals.mean(axis=1, keepdims=True)) @ tc / np.sum(tc ** 2)


def build(raw: pd.DataFrame, m: D.HeatMaster, ocv: Optional[pd.DataFrame], cfg: BalanceSettings) -> tuple[pd.DataFrame, dict]:
    df = raw.copy()
    b = m.base
    notes: list[str] = []
    step_h = D.STEP_MIN / 60
    rated = b.rated_kw or float(df["p_ac_kw"].abs().max())
    idle = cfg.idle_frac * rated
    df["direction"] = np.where(df["p_ac_kw"] > idle, "CHARGE", np.where(df["p_ac_kw"] < -idle, "DISCHARGE", "IDLE"))
    ratio = (df["pack_voltage_v"] / df["cell_v_avg_v"]).replace([np.inf, -np.inf], np.nan)
    cells = int(round(float(ratio.median()))) if ratio.notna().any() else (b.series_cells_master or 0)
    i = df["pack_current_a"].fillna(0.0)
    t_k = df["cell_temp_avg_c"].fillna(25.0) + 273.15

    # battery
    if ocv is not None and cells:
        u = ocv_lookup(ocv, df["soc_pct"].to_numpy(), df["cell_temp_avg_c"].to_numpy())
        df["ocv_cell_v"] = u
        df["q_batt_irr_kw"] = (df["cell_v_avg_v"] - u) * cells * i / 1000
        df["dudt_v_k"] = entropic_dudt(ocv, df["soc_pct"].to_numpy())
        df["q_batt_rev_kw"] = i * t_k * df["dudt_v_k"] * cells / 1000
    else:
        df["ocv_cell_v"], df["dudt_v_k"] = np.nan, 0.0
        df["q_batt_irr_kw"], df["q_batt_rev_kw"] = 0.0, 0.0
        notes.append("No OCV curve for the chemistry: battery heat can't be derived from the voltages (set to 0)")
    df.loc[i.abs() < 0.5, ["q_batt_irr_kw", "q_batt_rev_kw"]] = 0.0

    # PCS, auxiliary electronics
    df["q_pcs_kw"] = (df["p_dc_kw"] - df["p_ac_kw"]).abs() * (1.0 if cfg.pcs_inside else 0.0)
    ctrl = (df["aux_load_kw"] - df["hvac_kw"]).clip(lower=0)
    df["q_aux_kw"] = ctrl.fillna(ctrl.median() if ctrl.notna().any() else 0.0) * (1.0 if cfg.aux_inside else 0.0)

    # solar
    clear = D.clear_sky_ghi(df["ts"], m.latitude, m.longitude)
    if cfg.solar_source == "none":
        df["ghi_wm2"], df["ghi_source"] = 0.0, "none"
    elif cfg.solar_source == "clear_sky" or df["ghi_wm2"].isna().all():
        df["ghi_wm2"], df["ghi_source"] = clear, "clear_sky"
    else:
        measured = df["ghi_wm2"].notna()
        df["ghi_source"] = np.where(measured, "measured", "clear_sky")
        df["ghi_wm2"] = df["ghi_wm2"].where(measured, clear)
    df["ghi_clear_wm2"] = clear
    alpha_a = cfg.absorptivity * cfg.sunlit_area_m2           # m²
    df["q_solar_kw"] = alpha_a * df["ghi_wm2"] / 1000

    # envelope and storage
    ua = cfg.u_value_w_m2k * cfg.envelope_area_m2 / 1000      # kW/K
    gaps = int(df["t_amb_c"].isna().sum())
    df["t_amb_c"] = df["t_amb_c"].fillna(df["wx_temp_c"]).interpolate(limit_direction="both")
    if gaps:
        notes.append(f"{gaps} intervals have no HVAC ambient reading - filled from the weather station / interpolated")
    # the cooling plant holds the enclosure at its setpoint, so the envelope gain it must remove is UA·(T_amb - T_set)
    # (the measured enclosure temperature tracks the ambient in the sample and is kept in the ledger)
    df["q_env_kw"] = ua * (df["t_amb_c"] - cfg.internal_setpoint_c)
    cap_kwh = b.usable_kwh or 0.0
    c_kwh_per_k = cfg.thermal_mass_kj_k_per_kwh * cap_kwh / 3600
    dtdt = df["cell_temp_avg_c"].diff() / step_h               # K/h
    df["q_storage_kw"] = (c_kwh_per_k * dtdt).fillna(0.0)
    df["q_total_kw"] = df[TERMS].sum(axis=1)
    ref = REFERENCES.get(cfg.measured_reference, "heat_load_sensor_kw")
    df["measured_kw"] = df[ref]
    df["residual_kw"] = df["q_total_kw"] - df["q_storage_kw"] - df["measured_kw"]
    df["dt_cell_c"] = df["cell_temp_max_c"] - df["cell_temp_min_c"]
    df["t_cell_max_c"] = df["cell_temp_max_c"]
    n_train = int(len(df) * cfg.train_frac)
    df["is_train"] = np.arange(len(df)) < n_train
    if df["ghi_source"].eq("clear_sky").any() and cfg.solar_source == "auto":
        share = float(df["ghi_source"].eq("clear_sky").mean())
        notes.append(f"{100 * share:.0f} % of intervals use a clear-sky GHI estimate (no measured irradiance for the site / "
                     "period) - solar gain is an upper bound there")
    if cells and b.series_cells_master and cells != b.series_cells_master:
        notes.append(f"Pack ÷ cell voltage gives {cells} cells in series (master data {b.series_cells_master})")
    info = {"cells_series": cells, "alpha_a_m2": alpha_a, "ua_kw_per_k": ua, "c_kwh_per_k": c_kwh_per_k,
            "setpoint_c": cfg.internal_setpoint_c,
            "rated_kw": rated, "measured_column": ref, "n_train": n_train, "notes": notes}
    return df, info


def _fit(X: np.ndarray, y: np.ndarray, lower: list[float], upper: Optional[list[float]] = None) -> np.ndarray:
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 2:
        return np.zeros(X.shape[1])
    hi = np.array(upper, dtype=float) if upper is not None else np.full(X.shape[1], np.inf)
    return lsq_linear(X[ok], y[ok], bounds=(np.array(lower, dtype=float), hi), method="bvls").x



def _scores(y: np.ndarray, p: np.ndarray) -> dict:
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 3:
        return {"n": int(ok.sum())}
    y, p = y[ok], p[ok]
    var = np.var(y)
    return {"n": int(len(y)), "r2": float(1 - np.mean((y - p) ** 2) / var) if var > 0 else None,
            "mae_kw": float(np.mean(np.abs(y - p))), "rmse_kw": float(np.sqrt(np.mean((y - p) ** 2))),
            "bias_kw": float(np.mean(p - y))}


# One scale factor per heat term (battery ohmic heat per direction, entropic, PCS, solar, envelope, thermal mass),
# bounded to a plausible range. The battery and PCS terms all scale with the current, so their individual factors are
# only weakly identifiable (the run says so); their sum is what the fit pins down. The auxiliary electronics are (near)
# constant - collinear with the intercept - so they enter at their measured value (k = 1).
CAL_COLS = ["const", "irr_chg", "irr_dis", "rev", "pcs", "solar", "env", "storage"]
CAL_UPPER = {"const": np.inf, "irr_chg": 5.0, "irr_dis": 5.0, "rev": 3.0, "pcs": 5.0, "solar": 3.0, "env": 10.0,
             "storage": 3.0}


def calibration_matrix(df: pd.DataFrame) -> np.ndarray:
    chg = (df["direction"] == "CHARGE").to_numpy()
    irr = df["q_batt_irr_kw"].to_numpy()
    return np.column_stack([np.ones(len(df)), np.where(chg, irr, 0.0), np.where(chg, 0.0, irr), df["q_batt_rev_kw"],
                            df["q_pcs_kw"], df["q_solar_kw"], df["q_env_kw"], -df["q_storage_kw"]])


def calibrate(df: pd.DataFrame, info: dict) -> dict:
    """Scale factors k per term (>= 0; constant free) fitted to the measured reference on the training rows."""
    X = calibration_matrix(df)
    aux = df["q_aux_kw"].to_numpy()
    y = df["measured_kw"].to_numpy()
    tr = df["is_train"].to_numpy()
    k = _fit(X[tr], (y - aux)[tr], [-np.inf] + [0.0] * (X.shape[1] - 1), [CAL_UPPER[c] for c in CAL_COLS])
    df["q_model_kw"] = X @ k + aux
    pred = df["q_model_kw"].to_numpy()
    phys = (df["q_total_kw"] - df["q_storage_kw"]).to_numpy()
    at_bound = [c for c, v in zip(CAL_COLS, k) if np.isfinite(CAL_UPPER[c]) and v >= CAL_UPPER[c] - 1e-6]
    out = {"coef": dict(zip(CAL_COLS, map(float, k))), "at_upper_bound": at_bound,
           "fitted_alpha_a_m2": float(k[5] * info["alpha_a_m2"]), "fitted_ua_kw_per_k": float(k[6] * info["ua_kw_per_k"]),
           "fitted_c_kwh_per_k": float(k[7] * info["c_kwh_per_k"]),
           "train": _scores(y[tr], pred[tr]), "test": _scores(y[~tr], pred[~tr]),
           "nameplate_train": _scores(y[tr], phys[tr]), "nameplate_test": _scores(y[~tr], phys[~tr])}
    # the share of the calibrated load each source carries (window means)
    contrib = {c: float(np.nanmean(X[:, j] * k[j])) for j, c in enumerate(CAL_COLS)}
    contrib["aux"] = float(np.nanmean(aux))
    out["contribution_kw"] = contrib
    return out


# ---------------------------------------------------------------- sub-models for design and forecasting


def fit_battery_heat(df: pd.DataFrame, min_frac: float = 0.3) -> dict:
    """Effective resistance R_eff = q_irr / I² per direction and 10 % SOC band (median over the training intervals at
    >= min_frac of the peak current, so the overpotential is folded in at load). I² extrapolates conservatively to the
    rated current; a band without data takes its nearest neighbour."""
    out = {}
    for d in ("CHARGE", "DISCHARGE"):
        g = df[(df["direction"] == d) & df["is_train"]]
        ia = g["pack_current_a"].abs()
        g = g[ia >= min_frac * ia.max()] if len(g) else g
        ia = g["pack_current_a"].abs()
        r = (g["q_batt_irr_kw"] * 1000 / ia ** 2).replace([np.inf, -np.inf], np.nan)
        band = (g["soc_pct"].clip(0, 99.999) // 10).astype("Int64")
        table = r.groupby(band).median().clip(lower=0)
        all_r = float(r.median()) if r.notna().any() else 0.0
        bands = {}
        for b in range(10):
            if b in table.index and np.isfinite(table[b]):
                bands[b] = float(table[b])
        filled = {}
        for b in range(10):
            if b in bands:
                filled[b] = bands[b]
            elif bands:
                nb = min(bands, key=lambda x: abs(x - b))
                filled[b] = bands[nb]
            else:
                filled[b] = max(all_r, 0.0)
        pred = np.array([filled[int(x)] for x in band.fillna(5)]) * ia.to_numpy() ** 2 / 1000 if len(g) else np.array([])
        out[d] = {"r_ohm_by_soc_band": filled, "observed_bands": sorted(bands), "r_ohm_median": all_r,
                  "fit": _scores(g["q_batt_irr_kw"].to_numpy(), pred) if len(g) else {"n": 0}}
    return out


def battery_irr(model: dict, direction: np.ndarray, i: np.ndarray, soc: np.ndarray, temp: np.ndarray) -> np.ndarray:
    out = np.zeros(len(i))
    band = np.clip(np.nan_to_num(soc, nan=50.0), 0, 99.999) // 10
    for d, mm in model.items():
        rows = direction == d
        r = np.array([mm["r_ohm_by_soc_band"][int(b)] for b in band])
        out[rows] = (r * np.asarray(i, dtype=float) ** 2 / 1000)[rows]
    return np.clip(out, 0, None)


def fit_pcs_loss(df: pd.DataFrame, rated_kva: float) -> dict:
    """q_pcs ≈ a + b·s + c·s² (s = |S| / rated kVA, active intervals, a, b, c >= 0)."""
    g = df[(df["direction"] != "IDLE") & df["is_train"]]
    s = (g["s_kva"].fillna(g["p_ac_kw"].abs()) / rated_kva).to_numpy()
    X = np.column_stack([np.ones(len(g)), s, s ** 2])
    c = _fit(X, g["q_pcs_kw"].to_numpy(), [0.0, 0.0, 0.0])
    return {"a": float(c[0]), "b": float(c[1]), "c": float(c[2]), "rated_kva": rated_kva,
            "fit": _scores(g["q_pcs_kw"].to_numpy(), X @ c)}


def pcs_loss(model: dict, p_kw: np.ndarray, idle_kw: float) -> np.ndarray:
    s = np.abs(p_kw) / model["rated_kva"]
    q = model["a"] + model["b"] * s + model["c"] * s ** 2
    return np.where(np.abs(p_kw) > idle_kw, q, 0.0)


def entropic_dudt_at(df: pd.DataFrame, soc: float) -> float:
    """dU/dT per cell (V/K) at one SOC, read off the interval values (0 without an OCV curve)."""
    g = df[["soc_pct", "dudt_v_k"]].dropna().sort_values("soc_pct")
    if g.empty:
        return 0.0
    return float(np.interp(soc, g["soc_pct"].to_numpy(), g["dudt_v_k"].to_numpy()))
