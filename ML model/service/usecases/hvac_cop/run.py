"""One COP run per HVAC unit: measured COP, steady-state filter, performance models, scorecard, closure, trend."""
import time
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from usecases.hvac_cop import model as M
from usecases.hvac_cop import monitor as Mon


@dataclass
class RunConfig:
    hvac_ids: list[int]
    date_from: date
    date_to: date
    model: M.ModelSettings
    monitor: Mon.MonitorSettings


@dataclass
class UnitResult:
    hvac_id: int
    points: pd.DataFrame
    summary: dict
    models: dict
    warnings: list[str]


def run_unit(engine: Engine, unit: dict, cfg: RunConfig) -> UnitResult:
    hid = unit["hvac_id"]
    name = f"{unit['hvac_code']}"
    warnings: list[str] = []
    raw = M.series(engine, hid, cfg.date_from, cfg.date_to)
    if len(raw) < 200:
        raise M.HvacCopError(f"{name} has too few HVAC rows in {cfg.date_from} → {cfg.date_to}")
    df = M.derive(raw, cfg.model)
    models, sc = M.fit_models(df, cfg.model)
    rated = cfg.monitor.rated_capacity_kw or (unit["rated_kw"] * float(np.nanmax(df["units_running"]))
                                               if unit["rated_kw"] and df["units_running"].notna().any() else None)
    clos = Mon.closure(df)
    card = Mon.scorecard(df, models, cfg.model, cfg.monitor, rated)
    days = Mon.daily(df, models, cfg.model, cfg.monitor, rated)
    cyc = Mon.cycling(df, cfg.monitor)
    sens = Mon.sensitivities(df, models, cfg.model)
    grid = Mon.map_grid(models, cfg.model, cfg.monitor.ref_supply_c)

    # audits -> notes
    r = clos["loop_vs_logged_ratio_median"]
    if r is not None and abs(r - 1) > 0.15:
        warnings.append(f"{name}: cooling_capacity_kw is {r:.2f}× the coolant-loop cooling (flow × ρ·cp × ΔT = "
                        f"{clos['q_loop_mean_kw']:.1f} vs {clos['cooling_logged_mean_kw']:.1f} kW while cooling; the HVAC "
                        f"heat-load reading is {clos['heat_load_sensor_mean_kw']:.1f} kW) - a flow / temperature / capacity "
                        "sensor problem, not efficiency; the loop and the logged capacity can't both be right")
    dc = clos["cop_logged_minus_ratio_median"]
    if dc is not None and abs(dc) > 0.1:
        warnings.append(f"{name}: the logged cop runs {dc:+.2f} above cooling ÷ power (median; correlation "
                        f"{clos['cop_logged_vs_ratio_corr']:.2f}) - the unit computes COP differently from the logged "
                        "capacity and power")
    if clos["rej_closure_median_kw"] is not None and abs(clos["rej_closure_pct_of_rejected"] or 0) > 2:
        warnings.append(f"{name}: condenser balance heat_rejected − (cooling + power) = {clos['rej_closure_median_kw']:+.1f} kW "
                        f"median ({clos['rej_closure_pct_of_rejected']:+.1f} % of the rejected heat; p95 |gap| "
                        f"{clos['rej_closure_p95_abs_kw']:.1f} kW)")
    eta = card["eta_2nd_law_mean"]
    if eta is not None and not 0.15 <= eta <= 0.8:
        warnings.append(f"{name}: η_2nd_law averages {eta:.2f} - outside the 0.15–0.8 a real unit shows; check the lift "
                        f"source / approach temperatures ({cfg.model.lift_source})")
    if rated and card["capacity_ratio"] and card["capacity_ratio"] > 1.5:
        warnings.append(f"{name}: the delivered cooling averages {card['capacity_ratio']:.1f}× the rated capacity "
                        f"({rated:.0f} kW = rating × units running) - the rating or the capacity reading is off")
    if card["latent_share_of_cooling"] > 0.05:
        warnings.append(f"{name}: in {100 * card['latent_share_of_cooling']:.0f} % of the cooling intervals the coolant runs "
                        "below the enclosure dew point - latent load makes the sensible COP read low there")
    best = sc["hybrid"]["test"].get("mae")
    if best is not None and sc["map"]["test"].get("mae") is not None and best > sc["map"]["test"]["mae"]:
        warnings.append(f"{name}: the GBM residual doesn't improve on the performance map out of sample "
                        f"(MAE {best:.3f} vs {sc['map']['test']['mae']:.3f}) - the map alone is the better expectation")
    if df["coolant_setpoint_c"].std() < 0.1:
        warnings.append(f"{name}: the coolant setpoint never changes ({df['coolant_setpoint_c'].median():.0f} °C) - the map's "
                        "setpoint sensitivity rests on the supply-temperature scatter only; the Carnot-anchored grey-box gives "
                        f"{sens.get('grey_per_setpoint_plus_1c_pct', float('nan')):+.1f} % COP per +1 °C")
    sup = cfg.monitor.ref_supply_c - cfg.model.evap_approach_k
    c20, c40 = (float(M.eval_map(models["cap_map"], sup, a + cfg.model.cond_approach_k, 1.0)[0]) for a in (20.0, 40.0))
    if c40 > c20:
        warnings.append(f"{name}: the capacity map rises with ambient ({c20:.0f} → {c40:.0f} kW at full speed, 20 → 40 °C) - "
                        "the capacity reading follows the cooling demand rather than what the unit can deliver, so the "
                        "capacity ratio and the heat-load → part-load mapping are indicative")
    alarms = [d["day"] for d in days if d.get("control") and d["control"]["status"] != "ok"]
    if alarms:
        warnings.append(f"{name}: COP below the expectation (EWMA / CUSUM) on {len(alarms)} day(s), first {alarms[0]}")
    s = df[df["steady"]]
    # the expected shape: COP highest on cool nights, sagging on hot afternoons and at full compressor load
    night = s[s["ts"].dt.hour.isin([0, 1, 2, 3, 4, 5])]["cop_actual"].mean()
    afternoon = s[s["ts"].dt.hour.isin([13, 14, 15, 16])]["cop_actual"].mean()
    full = s[s["plr"] >= 0.9]["cop_actual"].mean()
    part = s[(s["plr"] >= 0.4) & (s["plr"] < 0.7)]["cop_actual"].mean()
    shape = {"night_cop": float(night) if np.isfinite(night) else None, "afternoon_cop": float(afternoon) if np.isfinite(afternoon) else None,
             "full_load_cop": float(full) if np.isfinite(full) else None, "part_load_cop": float(part) if np.isfinite(part) else None}

    summary = {"hvac_id": hid, "hvac_code": unit["hvac_code"], "system_id": unit["system_id"], "system_name": unit["system_name"],
               "site_name": unit["site_name"], "model": unit["model"], "rated_capacity_kw": rated,
               "cop_definition": cfg.model.cop_definition, "capacity_definition": cfg.model.capacity_definition,
               "scores": sc, "closure": clos, "scorecard": card, "cycling": cyc, "sensitivities": sens, "map_grid": grid,
               "shape": shape, "daily": days, "alarm_days": alarms,
               "train_to": df.loc[df["is_train"], "ts"].max().isoformat(), "test_from": df.loc[~df["is_train"], "ts"].min().isoformat(),
               "steady_n": int(df["steady"].sum()), "cooling_n": int((df["cooling_mode"] == "COOLING").sum())}
    # scatter sample for the performance-map chart (steady rows)
    samp = s.iloc[:: max(1, len(s) // 1500)]
    summary["scatter"] = [{"amb": float(a), "cop": float(c), "plr": float(p), "exp": float(e) if np.isfinite(e) else None}
                          for a, c, p, e in zip(samp["ambient_temp_c"], samp["cop_actual"], samp["plr"], samp["cop_expected"])]
    return UnitResult(hid, df, summary, models, warnings)


def run(engine: Engine, cfg: RunConfig) -> dict:
    started = time.perf_counter()
    known = {u["hvac_id"]: u for u in M.units(engine)}
    results, warnings = [], []
    for hid in cfg.hvac_ids:
        if hid not in known:
            raise M.HvacCopError(f"HVAC unit {hid} has no telemetry")
        r = run_unit(engine, known[hid], cfg)
        results.append(r)
        warnings += r.warnings
    fleet = []
    for r in results:
        s = r.summary
        fleet.append({"hvac_id": r.hvac_id, "hvac_code": s["hvac_code"], "system_name": s["system_name"], "site_name": s["site_name"],
                      "seasonal_cop": s["scorecard"]["seasonal_cop_cooling"], "seasonal_cop_all": s["scorecard"]["seasonal_cop_all_modes"],
                      "logged_cop_mean": s["scorecard"]["logged_cop_mean"], "kw_per_ton": s["scorecard"]["kw_per_ton"],
                      "iplv_style": s["scorecard"]["iplv_style"], "eta_2nd_law": s["scorecard"]["eta_2nd_law_mean"],
                      "capacity_ratio": s["scorecard"]["capacity_ratio"], "map_test_mae": s["scores"]["map"]["test"].get("mae"),
                      "map_test_r2": s["scores"]["map"]["test"].get("r2"), "hybrid_test_mae": s["scores"]["hybrid"]["test"].get("mae"),
                      "loop_ratio": s["closure"]["loop_vs_logged_ratio_median"], "starts_per_day": s["cycling"]["starts_per_day"],
                      "alarm_days": len(s["alarm_days"])})
    return {"results": results, "warnings": warnings, "fleet": fleet, "duration_ms": int((time.perf_counter() - started) * 1000)}
