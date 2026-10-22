"""One heat-load run per battery system: ledger, calibration, sub-models, operational forecast backtest and design."""
import time
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from usecases.heatload import balance as B
from usecases.heatload import data as D
from usecases.heatload.design import DesignSettings, size
from usecases.heatload.forecast import ForecastSettings, Forecaster
from usecases.loss.data import ocv_table
from usecases.soc_forecast.features import schedule, schedule_grid


@dataclass
class RunConfig:
    system_ids: list[int]
    date_from: date
    date_to: date
    balance: B.BalanceSettings
    forecast: ForecastSettings
    design: DesignSettings


@dataclass
class SystemResult:
    system_id: int
    ledger: pd.DataFrame
    points: pd.DataFrame
    summary: dict
    models: dict
    warnings: list[str]


def _direction_table(df: pd.DataFrame) -> dict:
    """Which half-cycle runs hotter - with and without the entropic term - and what the measured reference says."""
    out = {}
    for d, g in df.groupby("direction"):
        out[d] = {"intervals": int(len(g)), **{c: float(g[c].mean()) for c in
                  B.TERMS + ["q_storage_kw", "q_total_kw", "q_model_kw", "measured_kw", "residual_kw"]},
                  "q_total_no_entropic_kw": float((g["q_total_kw"] - g["q_batt_rev_kw"]).mean()),
                  "c_rate_abs_mean": float(g["c_rate"].abs().mean()) if g["c_rate"].notna().any() else None}
    return out


def run_system(engine: Engine, sid: int, cfg: RunConfig) -> SystemResult:
    m = D.master(engine, sid)
    name = m.base.system_name
    warnings = [f"{name}: {n}" for n in m.base.notes]
    raw = D.series(engine, m, cfg.date_from, cfg.date_to)
    if len(raw) < 500:
        raise D.HeatLoadError(f"{name} has too few time-aligned BMS / PCS / EMS / HVAC rows in {cfg.date_from} → {cfg.date_to}")
    ocv = ocv_table(engine, m.base.chemistry)
    df, info = B.build(raw, m, ocv, cfg.balance)
    warnings += [f"{name}: {n}" for n in info["notes"]]
    cal = B.calibrate(df, info)
    batt = B.fit_battery_heat(df)
    pcs = B.fit_pcs_loss(df, m.base.rated_kva)

    # audits
    act = df[df["direction"] != "IDLE"]
    corr = act[["q_batt_irr_kw", "q_batt_rev_kw", "q_pcs_kw"]].abs().corr().to_numpy()
    if len(act) > 10 and np.nanmin(corr) > 0.9:
        warnings.append(f"{name}: battery ohmic, entropic and PCS heat all scale with the current (|r| > 0.9) - the "
                        "calibration pins down their sum; the individual factors (and the design split) are weakly identified")
    dirs = _direction_table(df)
    rev = {d: dirs.get(d, {}).get("q_batt_rev_kw", 0.0) for d in ("CHARGE", "DISCHARGE")}
    meas = {d: dirs.get(d, {}).get("measured_kw") for d in ("CHARGE", "DISCHARGE")}
    if abs(rev["CHARGE"]) > 2 and meas["CHARGE"] is not None and meas["DISCHARGE"] is not None:
        hotter_model = "charge" if dirs["CHARGE"]["q_total_kw"] > dirs["DISCHARGE"]["q_total_kw"] else "discharge"
        hotter_meas = "charge" if meas["CHARGE"] > meas["DISCHARGE"] else "discharge"
        if hotter_model != hotter_meas:
            warnings.append(f"{name}: with the OCV curve's entropic coefficient ({1000 * float(df['dudt_v_k'].mean()):.2f} mV/K) "
                            f"the physics makes {hotter_model} the hotter half-cycle (entropic {rev['CHARGE']:+.1f} / "
                            f"{rev['DISCHARGE']:+.1f} kW), the measured reference says {hotter_model == 'charge' and 'discharge' or 'charge'} - "
                            f"the calibration keeps {100 * cal['coef']['rev']:.0f} % of the entropic term")
    closure = {
        "mean_residual_kw": float(df["residual_kw"].mean()), "mean_abs_residual_kw": float(df["residual_kw"].abs().mean()),
        "residual_pct_of_measured": float(100 * df["residual_kw"].mean() / df["measured_kw"].mean()) if df["measured_kw"].mean() else None,
        "by_direction": {d: dirs[d]["residual_kw"] for d in dirs},
        "cooling_over_heat_sensor": float(df.loc[df["cooling_kw"] > 1, "cooling_kw"].sum() / max(df.loc[df["cooling_kw"] > 1, "heat_load_sensor_kw"].sum(), 1e-9)),
    }
    if closure["residual_pct_of_measured"] is not None and abs(closure["residual_pct_of_measured"]) > 15:
        warnings.append(f"{name}: the nameplate heat balance misses the measured reference by {closure['residual_pct_of_measured']:+.0f} % "
                        "on average - a missing or mis-sized source (solar, envelope, internal resistance); the calibrated "
                        "model absorbs it")
    if closure["cooling_over_heat_sensor"] > 1.5:
        warnings.append(f"{name}: while cooling, the delivered cooling (cooling_capacity_kw) is {closure['cooling_over_heat_sensor']:.1f}× "
                        "the HVAC's own battery heat-load reading - the two can't both close the balance")

    # forecast
    sched = schedule(engine, m.base.ems_id)
    sched_sp, _ = schedule_grid(sched, pd.DatetimeIndex(df["ts"]))
    if cfg.forecast.plan_source == "scheduled" and np.isnan(sched_sp).all():
        warnings.append(f"{name}: no dispatch_event schedule - the forecast falls back to the typical day")
    fc = Forecaster(df, info, cal, batt, pcs, m, sched_sp, D.weather_forecast(engine, m.station_id), cfg.forecast)
    fit_info = fc.fit()
    points, scores = fc.backtest()
    if scores and fit_info["tau_min"] >= 240:
        warnings.append(f"{name}: the fitted RC time constant sits at the grid's upper bound (240 min) - the gain comes from "
                        "carrying the current model error forward (a slowly varying bias), not from thermal lag")
    if scores and fit_info["tau_min"] == 0:
        warnings.append(f"{name}: the fitted thermal time constant is 0 - the measured heat load follows the load without "
                        "lag in this data, so the RC pre-cooling lead time can't be estimated from it")

    design = size(df, info, cal, batt, pcs, m, cfg.design, cfg.balance.measured_reference)
    if cal.get("at_upper_bound"):
        warnings.append(f"{name}: calibration factor(s) {', '.join(cal['at_upper_bound'])} hit their plausibility bound - "
                        "that term is absorbing an effect it doesn't model")
    obs = design["observed"]
    if obs.get("installed_capacity_kw") and design["required_capacity_kw"] > obs["installed_capacity_kw"]:
        warnings.append(f"{name}: the design heat load ({design['required_capacity_kw']:.1f} kW with margin) exceeds the "
                        f"installed capacity ({obs['master_unit_capacity_kw']:.0f} kW per unit × up to "
                        f"{obs['units_running_max']:.0f} units running = {obs['installed_capacity_kw']:.0f} kW)")

    daily = (df.assign(day=df["ts"].dt.date).groupby("day")
             .agg(q_total_peak_kw=("q_total_kw", "max"), q_model_peak_kw=("q_model_kw", "max"),
                  measured_peak_kw=("measured_kw", "max"), measured_mean_kw=("measured_kw", "mean"),
                  q_batt_kw=("q_batt_irr_kw", "mean"), q_rev_kw=("q_batt_rev_kw", "mean"), q_pcs_kw=("q_pcs_kw", "mean"),
                  q_aux_kw=("q_aux_kw", "mean"), q_solar_kw=("q_solar_kw", "mean"), q_env_kw=("q_env_kw", "mean"),
                  t_amb_max_c=("t_amb_c", "max"), dt_cell_max_c=("dt_cell_c", "max"))
             .reset_index())
    daily["day"] = daily["day"].astype(str)
    summary = {
        "system_id": sid, "system_name": name, "site_name": m.base.site_name, "rated_kw": info["rated_kw"],
        "usable_kwh": m.base.usable_kwh, "cells_series": info["cells_series"], "measured_reference": cfg.balance.measured_reference,
        "nameplate": {"alpha_a_m2": info["alpha_a_m2"], "ua_kw_per_k": info["ua_kw_per_k"], "c_kwh_per_k": info["c_kwh_per_k"]},
        "calibration": cal, "closure": closure, "direction": dirs, "design": design, "forecast": {**fit_info, **scores},
        "daily": daily.to_dict(orient="records"),
        "train_to": df.loc[df["is_train"], "ts"].max().isoformat(), "test_from": df.loc[~df["is_train"], "ts"].min().isoformat(),
        "ghi_measured_share": float(df["ghi_source"].eq("measured").mean()),
    }
    models = {"battery_heat": batt, "pcs_loss": pcs, "calibration": cal["coef"], "tau_min": fc.tau}
    return SystemResult(sid, df, points, summary, models, warnings)


def run(engine: Engine, cfg: RunConfig) -> dict:
    started = time.perf_counter()
    results, warnings = [], []
    for sid in cfg.system_ids:
        r = run_system(engine, sid, cfg)
        results.append(r)
        warnings += r.warnings
    fleet = []
    for r in results:
        s = r.summary
        d, f = s["design"], s["forecast"].get("by_horizon", {})
        h60 = f.get(60) or f.get(min(f) if f else 0) or {}
        fleet.append({"system_id": r.system_id, "system_name": s["system_name"], "site_name": s["site_name"],
                      "calibrated_r2": s["calibration"]["test"].get("r2"), "calibrated_mae_kw": s["calibration"]["test"].get("mae_kw"),
                      "nameplate_mae_kw": s["calibration"]["nameplate_test"].get("mae_kw"),
                      "closure_pct": s["closure"]["residual_pct_of_measured"], "q_peak_kw": d["q_peak_kw"],
                      "required_kw": d["required_capacity_kw"], "units": d.get("units_installed_n_plus"),
                      "measured_peak_kw": d["observed"]["measured_peak_kw"],
                      "installed_kw": d["observed"].get("installed_capacity_kw"),
                      "annual_chiller_mwh": d["duty"]["annual_chiller_mwh"],
                      "fc60_mae_kw": h60.get("p50_mae"), "fc60_persistence_mae_kw": h60.get("persistence_mae"),
                      "fc60_coverage": h60.get("coverage_p10_p90"), "tau_min": s["forecast"].get("tau_min")})
    return {"results": results, "warnings": warnings, "fleet": fleet, "duration_ms": int((time.perf_counter() - started) * 1000)}
