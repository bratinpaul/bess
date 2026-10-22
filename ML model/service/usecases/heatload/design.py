"""Thermal design: size the cooling plant for the coincident worst case, and the annual duty from the observed profile.

Design condition (both half-cycles evaluated, the hotter one sizes the plant):
  battery    sustained rated power at the design SOC; R / overpotential at END OF LIFE (eol_criteria resistance %, e.g.
             LFP 200 % of BOL, scaled from the current SOH) - BOL sizing under-provisions; entropic term at the design SOC
  PCS        conversion loss at rated power (fitted loss curve)
  aux        controls electronics
  solar      design irradiance x α·A (nameplate or calibrated)
  envelope   UA · (design ambient - internal setpoint); design ambient = the site's 0.4 %-exceedance dry-bulb from the
             HVAC ambient sensor unless given
Q_peak · (1 + margin) = required capacity; unit capacity derated above its 35 °C rating point; N + 1 units.
Annual duty: the calibrated model over the observed window -> load-duration curve, histogram, heat and chiller energy
(COP(T_amb) fitted on the cooling intervals), annualized by hours (the window is shorter than a year - flagged).
"""
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from usecases.heatload import balance as B
from usecases.heatload import data as D


@dataclass
class DesignSettings:
    design_ambient_c: Optional[float] = None    # None -> 99.6th percentile of the observed ambient
    design_ghi_wm2: float = 1000.0
    design_soc_pct: float = 15.0                # low SOC: higher resistance / overpotential
    design_cell_temp_c: float = 35.0
    internal_setpoint_c: float = 25.0
    eol_resistance_pct: Optional[float] = None  # None -> eol_criteria of the chemistry, else 200
    resistance_growth_pct_per_soh: float = 3.3  # to back out today's resistance relative to BOL
    margin_pct: float = 15.0
    redundancy: int = 1                         # N + redundancy
    unit_capacity_kw: Optional[float] = None    # None -> hvac_unit.cooling_capacity_kw
    unit_rating_ambient_c: float = 35.0
    capacity_derate_pct_per_c: float = 1.0
    coincidence: float = 1.0                    # share of the design solar + envelope gain assumed coincident
    use_calibrated: bool = True                 # calibrated k for the battery / PCS / solar / envelope terms


def size(df: pd.DataFrame, info: dict, cal: dict, batt: dict, pcs: dict, m: D.HeatMaster, cfg: DesignSettings,
         reference: str = "heat_load_sensor") -> dict:
    b = m.base
    k = cal["coef"] if cfg.use_calibrated else {c: 1.0 for c in B.CAL_COLS} | {"const": 0.0, "storage": 0.0}
    amb_design = cfg.design_ambient_c if cfg.design_ambient_c is not None else float(np.nanpercentile(df["t_amb_c"], 99.6))
    eol_pct = cfg.eol_resistance_pct or m.eol_resistance_pct or 200.0
    soh_now = float(df["soh_pct"].dropna().iloc[-1]) if df["soh_pct"].notna().any() else 100.0
    r_now = 1 + cfg.resistance_growth_pct_per_soh / 100 * (100 - soh_now)
    eol_mult = (eol_pct / 100) / r_now
    p_rated = info["rated_kw"]
    v_design = float(np.nanpercentile(df["pack_voltage_v"], 10)) if df["pack_voltage_v"].notna().any() else (m.nominal_dc_v or 1000)
    i_design = p_rated * 1000 / v_design
    dudt = float(B.entropic_dudt_at(df, cfg.design_soc_pct))
    cells = info["cells_series"]
    t_k = cfg.design_cell_temp_c + 273.15
    gain_solar = info["alpha_a_m2"] * cfg.design_ghi_wm2 / 1000
    gain_env = info["ua_kw_per_k"] * (amb_design - cfg.internal_setpoint_c)
    aux = float(df["q_aux_kw"].median())
    cases = {}
    for d, sign in (("CHARGE", 1), ("DISCHARGE", -1)):
        irr_bol = float(B.battery_irr(batt, np.array([d]), np.array([sign * i_design]), np.array([cfg.design_soc_pct]),
                                      np.array([cfg.design_cell_temp_c]))[0])
        irr = irr_bol * eol_mult
        rev = sign * i_design * t_k * dudt * cells / 1000
        q_pcs = float(B.pcs_loss(pcs, np.array([p_rated]), 0.0)[0])
        kb = k["irr_chg"] if d == "CHARGE" else k["irr_dis"]
        # external gains: the battery heat-load reading doesn't contain them (its calibrated solar / envelope factors
        # say nothing about the enclosure), so they come from the nameplate envelope unless the reference is the
        # delivered cooling
        ext = cfg.use_calibrated and reference == "cooling_delivered"
        k_sol, k_env = (k["solar"], k["env"]) if ext else (1.0, 1.0)
        terms = {"battery_irreversible": kb * irr, "battery_entropic": k["rev"] * rev, "pcs": k["pcs"] * q_pcs,
                 "aux": aux, "solar": cfg.coincidence * k_sol * gain_solar,
                 "envelope": cfg.coincidence * k_env * gain_env, "constant": k["const"]}
        terms = {t: max(v, 0.0) if t not in ("battery_entropic", "envelope", "constant") else v for t, v in terms.items()}
        cases[d] = {"terms": terms, "q_peak_kw": float(sum(terms.values())), "battery_irr_bol_kw": kb * irr_bol,
                    "nameplate_terms": {"battery_irreversible": irr, "battery_entropic": rev, "pcs": q_pcs, "aux": aux,
                                        "solar": cfg.coincidence * gain_solar, "envelope": cfg.coincidence * gain_env}}
    sizing_dir = max(cases, key=lambda d: cases[d]["q_peak_kw"])
    q_peak = cases[sizing_dir]["q_peak_kw"]
    q_bol = q_peak - cases[sizing_dir]["terms"]["battery_irreversible"] + cases[sizing_dir]["battery_irr_bol_kw"]
    required = q_peak * (1 + cfg.margin_pct / 100)
    unit = cfg.unit_capacity_kw or m.unit_capacity_kw
    derate = max(0.0, 1 - cfg.capacity_derate_pct_per_c / 100 * max(0.0, amb_design - cfg.unit_rating_ambient_c))
    out = {
        "condition": {"ambient_c": amb_design, "ambient_source": "parameter" if cfg.design_ambient_c is not None else "99.6th percentile of the HVAC ambient sensor",
                      "ghi_wm2": cfg.design_ghi_wm2, "soc_pct": cfg.design_soc_pct, "cell_temp_c": cfg.design_cell_temp_c,
                      "internal_setpoint_c": cfg.internal_setpoint_c, "power_kw": p_rated, "pack_voltage_v": v_design,
                      "current_a": i_design, "c_rate": p_rated / b.usable_kwh if b.usable_kwh else None,
                      "eol_resistance_pct": eol_pct, "soh_now_pct": soh_now, "eol_multiplier": eol_mult,
                      "coincidence": cfg.coincidence, "calibrated": cfg.use_calibrated, "dudt_mv_per_k": dudt * 1000,
                      "external_gains": "calibrated" if (cfg.use_calibrated and reference == "cooling_delivered") else "nameplate"},
        "cases": cases, "sizing_direction": sizing_dir, "q_peak_kw": q_peak, "q_peak_bol_kw": q_bol,
        "margin_pct": cfg.margin_pct, "required_capacity_kw": required,
        "unit_capacity_kw": unit, "unit_capacity_at_design_kw": unit * derate if unit else None, "derate_factor": derate,
    }
    if unit:
        n = math.ceil(required / (unit * derate)) if derate > 0 else None
        out.update(units_n=n, units_installed_n_plus=(n + cfg.redundancy) if n else None, redundancy=cfg.redundancy,
                   installed_capacity_kw=(n + cfg.redundancy) * unit if n else None)
    # what the sample already has
    observed = {
        "measured_peak_kw": float(np.nanmax(df["measured_kw"])), "measured_p99_kw": float(np.nanpercentile(df["measured_kw"], 99)),
        "heat_load_sensor_peak_kw": float(np.nanmax(df["heat_load_sensor_kw"])),
        "cooling_delivered_peak_kw": float(np.nanmax(df["cooling_kw"])),
        "units_running_max": float(np.nanmax(df["units_running"])) if df["units_running"].notna().any() else None,
        "master_units": m.hvac_units, "master_unit_capacity_kw": m.unit_capacity_kw, "hvac_model": m.hvac_model,
        "model_peak_kw": float(np.nanmax(df["q_model_kw"])), "physics_peak_kw": float(np.nanmax(df["q_total_kw"])),
    }
    if m.unit_capacity_kw and observed["units_running_max"]:
        observed["installed_capacity_kw"] = m.unit_capacity_kw * observed["units_running_max"]
    out["observed"] = observed
    out["duty"] = duty(df, required)
    out["hot_spot"] = hot_spot(df)
    return out


def duty(df: pd.DataFrame, design_kw: float) -> dict:
    q = df["q_model_kw"].clip(lower=0).to_numpy()
    meas = df["measured_kw"].to_numpy()
    hours = len(q) * D.STEP_MIN / 60
    order = np.sort(q)[::-1]
    pct = np.linspace(0, 100, 101)
    ldc = [{"pct_time": float(p), "q_kw": float(order[min(len(order) - 1, int(p / 100 * (len(order) - 1)))]),
            "measured_kw": float(np.sort(meas[np.isfinite(meas)])[::-1][min(np.isfinite(meas).sum() - 1, int(p / 100 * (np.isfinite(meas).sum() - 1)))])}
           for p in pct]
    top = max(float(np.nanmax(q)), design_kw, 1.0)
    width = 5.0 if top <= 120 else 10.0
    edges = np.arange(0, top + width, width)
    hist, _ = np.histogram(q, bins=edges)
    histogram = [{"from_kw": float(edges[i]), "to_kw": float(edges[i + 1]), "hours": float(hist[i] * D.STEP_MIN / 60),
                  "share": float(hist[i] / len(q))} for i in range(len(hist))]
    # COP vs ambient from the cooling intervals (fallback 3.5)
    c = df[(df["cop"] > 0) & df["t_amb_c"].notna()]
    if len(c) > 50:
        slope, icpt = np.polyfit(c["t_amb_c"], c["cop"], 1)
    else:
        slope, icpt = 0.0, 3.5
    cop = np.clip(icpt + slope * df["t_amb_c"].fillna(df["t_amb_c"].median()).to_numpy(), 1.5, 8.0)
    heat_kwh = float(q.sum() * D.STEP_MIN / 60)
    elec_kwh = float((q / cop).sum() * D.STEP_MIN / 60)
    scale = 8760 / hours if hours else 0.0
    part = [{"band": lbl, "share": float(np.mean((q >= lo * design_kw) & (q < hi * design_kw)))}
            for lbl, lo, hi in (("< 25 %", 0, 0.25), ("25–50 %", 0.25, 0.5), ("50–75 %", 0.5, 0.75), ("75–100 %", 0.75, 1.0),
                                ("> 100 %", 1.0, 1e9))]
    return {"hours": hours, "load_duration": ldc, "histogram": histogram, "heat_kwh": heat_kwh, "chiller_kwh": elec_kwh,
            "mean_kw": float(np.mean(q)), "annual_heat_mwh": heat_kwh * scale / 1000,
            "annual_chiller_mwh": elec_kwh * scale / 1000, "annualization_factor": scale,
            "cop_fit": {"intercept": float(icpt), "slope_per_c": float(slope), "n": int(len(c))},
            "part_load_vs_design": part, "hours_above_design": float(np.sum(q > design_kw) * D.STEP_MIN / 60)}


def hot_spot(df: pd.DataFrame) -> dict:
    """Cell temperature spread (max - min) - a module hot spot the pack-average heat load hides."""
    dt = df["dt_cell_c"]
    if dt.notna().sum() < 10:
        return {}
    return {"dt_mean_c": float(dt.mean()), "dt_p99_c": float(np.nanpercentile(dt, 99)), "dt_max_c": float(dt.max()),
            "hours_dt_over_5c": float((dt > 5).sum() * D.STEP_MIN / 60),
            "corr_with_heat": float(np.corrcoef(dt.fillna(dt.mean()), df["measured_kw"].fillna(0))[0, 1]),
            "cell_max_peak_c": float(df["cell_temp_max_c"].max())}
