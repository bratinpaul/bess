"""Scorecard, closure audit, cycling, daily degradation trend with control charts, and setpoint / pre-cool sensitivities.

  seasonal COP      Σ cooling kWh / Σ HVAC kWh over the cooling intervals (and over all modes, idle parasitics included)
  IPLV-style index  map COP at the rating condition at PLR 100 / 75 / 50 / 25 % weighted 0.01 / 0.42 / 0.45 / 0.12 (AHRI),
                    and the observed index weighting the COP of the part-load bins the unit actually spent time in
  kW/ton            HVAC kW / (cooling kW / 3.517)
  capacity ratio    cooling delivered / rated capacity (capacity fade, separate from efficiency fade)
  η_2nd_law         COP / COP_carnot - the weather-free health metric
  normalized COP    COP at the reference condition (map) x the day's actual / expected ratio
Control charts on the daily mean residual (standardized on the training days): EWMA and CUSUM, lower-sided - COP below
the map is the fault signature (fouled condenser, low charge, clogged filter); corroborated by filter dp, discharge
pressure above its ambient-explained level and condenser fan saturation.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from usecases.hvac_cop.model import STEP_H, ModelSettings, eval_grey, eval_map


@dataclass
class MonitorSettings:
    ref_ambient_c: float = 35.0
    ref_supply_c: float = 25.0           # design coolant temperature
    ref_plr: float = 0.75
    rated_capacity_kw: float | None = None   # None -> hvac_unit rating x max units running
    ewma_lambda: float = 0.2
    ewma_l: float = 3.0
    cusum_k: float = 0.5
    cusum_h: float = 5.0
    sigma_floor: float = 0.02            # floor of the baseline σ of the daily mean residual (COP units)
    short_cycle_min: int = 15
    humid_pct: float = 60.0


def _te_tc(cfg: ModelSettings, ambient: float, supply: float) -> tuple[float, float]:
    return supply - cfg.evap_approach_k, ambient + cfg.cond_approach_k


def closure(df: pd.DataFrame) -> dict:
    c = df[df["cooling_mode"] == "COOLING"]
    ok = c["q_loop_kw"] > 0.5
    ratio = (c.loc[ok, "cooling_capacity_kw"] / c.loc[ok, "q_loop_kw"])
    dt_chk = (df["coolant_return_temp_c"] - df["coolant_supply_temp_c"] - df["coolant_delta_t_c"]).abs()
    return {
        "loop_vs_logged_ratio_median": float(ratio.median()) if len(ratio) else None,
        "loop_vs_logged_corr": float(np.corrcoef(c.loc[ok, "q_loop_kw"], c.loc[ok, "cooling_capacity_kw"])[0, 1]) if ok.sum() > 3 else None,
        "q_loop_mean_kw": float(c["q_loop_kw"].mean()) if len(c) else None,
        "cooling_logged_mean_kw": float(c["cooling_capacity_kw"].mean()) if len(c) else None,
        "heat_load_sensor_mean_kw": float(c["battery_heat_load_kw"].mean()) if len(c) else None,
        "cop_logged_minus_ratio_median": float((c["cop_logged"] - c["cop_ratio"]).median()) if len(c) else None,
        "cop_logged_vs_ratio_corr": float(c[["cop_logged", "cop_ratio"]].corr().iloc[0, 1]) if len(c) > 3 else None,
        "rej_closure_median_kw": float(c["rej_closure_kw"].median()) if len(c) else None,
        "rej_closure_p95_abs_kw": float(c["rej_closure_kw"].abs().quantile(0.95)) if len(c) else None,
        "rej_closure_pct_of_rejected": float(100 * c["rej_closure_kw"].median() / c["heat_rejected_kw"].median()) if len(c) else None,
        "dt_consistency_max_k": float(dt_chk.max()),
        "idle_hvac_power_kw": float(df.loc[df["cooling_mode"] == "IDLE", "hvac_power_kw"].mean()),
        "free_cooling_power_kw": float(df.loc[df["cooling_mode"] == "FREE_COOLING", "hvac_power_kw"].mean()),
        "steady_share_of_cooling": float(df["steady"].sum() / max(int((df["cooling_mode"] == "COOLING").sum()), 1)),
    }


def cycling(df: pd.DataFrame, cfg: MonitorSettings) -> dict:
    cooling = (df["cooling_mode"] == "COOLING").to_numpy()
    starts = np.flatnonzero(cooling & ~np.r_[False, cooling[:-1]])
    runs = []
    for s in starts:
        e = s
        while e + 1 < len(cooling) and cooling[e + 1]:
            e += 1
        runs.append((e - s + 1) * STEP_H * 60)
    days = max(df["ts"].dt.date.nunique(), 1)
    rt = df["compressor_runtime_h"].diff().clip(lower=0)
    rt = rt[rt < 1.0]  # counter resets / jumps
    return {"starts": int(len(starts)), "starts_per_day": len(starts) / days,
            "mean_run_min": float(np.mean(runs)) if runs else None,
            "short_cycles": int(sum(r <= cfg.short_cycle_min for r in runs)),
            "runtime_h_per_day": float(rt.sum()) / days, "cooling_hours_per_day": float(cooling.sum() * STEP_H) / days,
            "modes": {k: float(v) for k, v in df["cooling_mode"].value_counts(normalize=True).items()}}


def scorecard(df: pd.DataFrame, models: dict, mcfg: ModelSettings, cfg: MonitorSettings, rated_kw: float | None) -> dict:
    c = df[df["cooling_mode"] == "COOLING"]
    cool_kwh = float(c["cap_actual_kw"].sum() * STEP_H)
    hvac_cool_kwh = float(c["hvac_power_kw"].sum() * STEP_H)
    all_cool = float(df["cap_actual_kw"].fillna(0).sum() * STEP_H)
    all_hvac = float(df["hvac_power_kw"].sum() * STEP_H)
    cum = df["cum_energy_kwh"].ffill().diff().clip(lower=0).sum()
    te, tc = _te_tc(mcfg, cfg.ref_ambient_c, cfg.ref_supply_c)
    m = models["cop_map"]
    rating = {f"plr_{int(p * 100)}": float(eval_map(m, te, tc, p)[0]) for p in (1.0, 0.75, 0.5, 0.25)}
    iplv = 0.01 * rating["plr_100"] + 0.42 * rating["plr_75"] + 0.45 * rating["plr_50"] + 0.12 * rating["plr_25"]
    s = df[df["steady"]]
    bins = pd.cut(s["plr"], [0, 0.375, 0.625, 0.875, 1.01], labels=["25 %", "50 %", "75 %", "100 %"])
    by_bin = s.groupby(bins, observed=False).agg(share=("cop_actual", "size"), cop=("cop_actual", "mean"))
    by_bin["share"] = by_bin["share"] / max(len(s), 1)
    observed_index = float((by_bin["share"] * by_bin["cop"].fillna(0)).sum())
    cap_ratio = float(c["cap_actual_kw"].mean() / rated_kw) if rated_kw and len(c) else None
    # latent: coolant supply below the enclosure dew point (Magnus)
    t, rh = df["enclosure_temp_c"], df["enclosure_humidity_pct"].clip(1, 100)
    gamma = np.log(rh / 100) + 17.62 * t / (243.12 + t)
    dew = 243.12 * gamma / (17.62 - gamma)
    wet = (df["coolant_supply_temp_c"] < dew) & (df["cooling_mode"] == "COOLING")
    eta = s["eta_2nd_law"]
    return {
        "seasonal_cop_cooling": cool_kwh / hvac_cool_kwh if hvac_cool_kwh else None,
        "seasonal_cop_all_modes": all_cool / all_hvac if all_hvac else None,
        "cooling_mwh": cool_kwh / 1000, "hvac_mwh": all_hvac / 1000, "hvac_cooling_mwh": hvac_cool_kwh / 1000,
        "cum_energy_counter_mwh": float(cum) / 1000,
        "logged_cop_mean": float(c["cop_logged"].mean()) if len(c) else None,
        "kw_per_ton": (hvac_cool_kwh / (cool_kwh / 3.517)) if cool_kwh else None,
        "iplv_style": iplv, "rating_cop": rating, "rating_condition": {"ambient_c": cfg.ref_ambient_c, "supply_c": cfg.ref_supply_c},
        "observed_part_load_index": observed_index,
        "part_load_bins": [{"bin": str(k), "share": float(v["share"]), "cop": float(v["cop"]) if np.isfinite(v["cop"]) else None}
                           for k, v in by_bin.iterrows()],
        "capacity_ratio": cap_ratio, "rated_capacity_kw": rated_kw,
        "eta_2nd_law_mean": float(eta.mean()) if len(eta) else None,
        "eta_2nd_law_p10_p90": [float(eta.quantile(0.1)), float(eta.quantile(0.9))] if len(eta) else None,
        "latent_share_of_cooling": float(wet.sum() / max(len(c), 1)),
        "humid_share": float((df["enclosure_humidity_pct"] > cfg.humid_pct).mean()),
    }


def daily(df: pd.DataFrame, models: dict, mcfg: ModelSettings, cfg: MonitorSettings, rated_kw: float | None) -> list[dict]:
    te, tc = _te_tc(mcfg, cfg.ref_ambient_c, cfg.ref_supply_c)
    cop_ref = float(eval_map(models["cop_map"], te, tc, cfg.ref_plr)[0])
    # discharge pressure explained by ambient (training cooling rows) - a high-side rise above it is a condenser / charge signal
    c_tr = df[(df["cooling_mode"] == "COOLING") & df["is_train"]]
    slope, icpt = np.polyfit(c_tr["ambient_temp_c"], c_tr["refrig_discharge_bar"], 1) if len(c_tr) > 20 else (0.0, float("nan"))
    rows = []
    for d, g in df.groupby(df["ts"].dt.date):
        c = g[g["cooling_mode"] == "COOLING"]
        s = g[g["steady"]]
        act, exp = s["cop_actual"].sum(), s["cop_expected"].sum()
        row = {"day": d.isoformat(), "is_train": bool(g["is_train"].all()), "cooling_h": float(len(c) * STEP_H),
               "steady_n": int(len(s)),
               "weighted_cop": float(c["cap_actual_kw"].sum() / c["hvac_power_kw"].sum()) if len(c) and c["hvac_power_kw"].sum() > 0 else None,
               "kw_per_ton": float(c["hvac_power_kw"].sum() / (c["cap_actual_kw"].sum() / 3.517)) if len(c) and c["cap_actual_kw"].sum() > 0 else None,
               "cop_mean": float(s["cop_actual"].mean()) if len(s) else None,
               "cop_expected_mean": float(s["cop_expected"].mean()) if len(s) else None,
               "residual_mean": float(s["cop_residual"].mean()) if len(s) else None,
               "eta_2nd_law": float(s["eta_2nd_law"].mean()) if len(s) else None,
               "cop_normalized": cop_ref * act / exp if len(s) and exp else None,
               "capacity_ratio": float(c["cap_actual_kw"].mean() / rated_kw) if rated_kw and len(c) else None,
               "ambient_max_c": float(g["ambient_temp_c"].max()), "ambient_mean_c": float(g["ambient_temp_c"].mean()),
               "filter_dp_pa": float(g["filter_dp_pa"].mean()),
               "discharge_excess_bar": float((c["refrig_discharge_bar"] - (icpt + slope * c["ambient_temp_c"])).mean()) if len(c) else None,
               "fan_saturated_share": float((c["condenser_fan_pct"] >= 98).mean()) if len(c) else None,
               "hvac_kwh": float(g["hvac_power_kw"].sum() * STEP_H), "cooling_kwh": float(g["cap_actual_kw"].fillna(0).sum() * STEP_H)}
        rows.append(row)
    _control(rows, cfg)
    return rows


def _control(rows: list[dict], cfg: MonitorSettings) -> None:
    x = [r["residual_mean"] if r["steady_n"] >= 6 else None for r in rows]
    base = [v for v, r in zip(x, rows) if v is not None and r["is_train"]]
    if len(base) < 2:
        base = [v for v in x if v is not None]
    mu = float(np.mean(base)) if base else 0.0
    sigma = max(float(np.std(base, ddof=1)) if len(base) > 1 else 0.0, cfg.sigma_floor)
    lam, z, cn, t = cfg.ewma_lambda, mu, 0.0, 0
    for v, r in zip(x, rows):
        if v is None:
            r["control"] = None
            continue
        t += 1
        z = lam * v + (1 - lam) * z
        w = cfg.ewma_l * sigma * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * t)))
        u = (v - mu) / sigma
        cn = max(0.0, cn - u - cfg.cusum_k)
        ewma_alarm, cusum_alarm = bool(z < mu - w), bool(cn > cfg.cusum_h)
        r["control"] = {"ewma": z, "lcl": mu - w, "ucl": mu + w, "center": mu, "sigma": sigma, "cusum_neg": cn,
                        "ewma_alarm": ewma_alarm, "cusum_alarm": cusum_alarm,
                        "status": "both" if ewma_alarm and cusum_alarm else ("ewma" if ewma_alarm else ("cusum" if cusum_alarm else "ok"))}


def sensitivities(df: pd.DataFrame, models: dict, mcfg: ModelSettings) -> dict:
    """COP gain per +1 °C coolant setpoint and per -1 °C ambient at the median steady condition (map), and the diurnal
    profile: the hours where cooling is cheapest in electricity (highest expected COP)."""
    s = df[df["steady"]]
    if s.empty:
        return {}
    amb, sup, plr = float(s["ambient_temp_c"].median()), float(s["coolant_supply_temp_c"].median()), float(s["plr"].median())
    m = models["cop_map"]
    f = lambda a, su, p=plr: float(eval_map(m, su - mcfg.evap_approach_k, a + mcfg.cond_approach_k, p)[0])
    base = f(amb, sup)

    def grey(a, su, p=plr):  # Carnot-anchored: a warmer evaporator / cooler condenser always helps
        te, tc = su - mcfg.evap_approach_k, a + mcfg.cond_approach_k
        lift = tc - te
        return float(eval_grey(models["grey"], p, lift, (te + 273.15) / lift)[0]) if lift > 1 else float("nan")
    g0 = grey(amb, sup)
    hours = []
    for h, g in df.groupby(df["ts"].dt.hour):
        a = float(g["ambient_temp_c"].mean())
        st = g[g["steady"]]
        hours.append({"hour": int(h), "ambient_c": a, "cop_expected_at_median_load": f(a, sup),
                      "cop_actual_mean": float(st["cop_actual"].mean()) if len(st) else None, "steady_n": int(len(st))})
    best = sorted(hours, key=lambda x: -x["cop_expected_at_median_load"])[:4]
    return {"at": {"ambient_c": amb, "supply_c": sup, "plr": plr}, "cop_at_median": base,
            "per_setpoint_plus_1c": f(amb, sup + 1) - base, "per_setpoint_plus_1c_pct": 100 * (f(amb, sup + 1) / base - 1),
            "per_ambient_minus_1c": f(amb - 1, sup) - base, "per_ambient_minus_1c_pct": 100 * (f(amb - 1, sup) / base - 1),
            "per_plr_minus_10pct": f(amb, sup, max(plr - 0.1, 0.05)) - base,
            "grey_cop_at_median": g0, "grey_per_setpoint_plus_1c_pct": 100 * (grey(amb, sup + 1) / g0 - 1),
            "grey_per_ambient_minus_1c_pct": 100 * (grey(amb - 1, sup) / g0 - 1),
            "hourly": hours, "best_hours": [b["hour"] for b in best]}


def map_grid(models: dict, mcfg: ModelSettings, supply_c: float) -> dict:
    """COP and capacity vs ambient at four part-load ratios (for the performance-map chart)."""
    lo, hi = models["ranges"]["ambient_temp_c"]
    amb = np.linspace(min(lo, 15), max(hi, 45), 31)
    te = supply_c - mcfg.evap_approach_k
    out = {"ambient_c": amb.tolist(), "supply_c": supply_c, "cop": {}, "cap": {}}
    for p in (0.4, 0.6, 0.8, 1.0):
        out["cop"][str(p)] = eval_map(models["cop_map"], np.full(len(amb), te), amb + mcfg.cond_approach_k, np.full(len(amb), p)).tolist()
        out["cap"][str(p)] = eval_map(models["cap_map"], np.full(len(amb), te), amb + mcfg.cond_approach_k, np.full(len(amb), p)).tolist()
    plr = np.linspace(0.3, 1.0, 15)
    out["plr_curve"] = {"plr": plr.tolist(),
                        "f": (np.column_stack([plr ** k for k in range(len(models["cop_map"]["plr"]))]) @ np.array(models["cop_map"]["plr"])).tolist()}
    return out
