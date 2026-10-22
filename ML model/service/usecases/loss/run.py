"""One loss run: for every chosen battery system, the ledger, the fitted benchmark, the daily scorecard and the
window summary (energy balance, RTE chain, loss shares, closure audit, loading curve, direction split)."""
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from usecases.loss import data as D
from usecases.loss.benchmark import BenchmarkSettings, fit_and_apply
from usecases.loss.ledger import LedgerSettings, build
from usecases.loss.scorecard import STAGE_LABELS, ScoreSettings, daily, direction_split, loading_curve, window


@dataclass
class RunConfig:
    system_ids: list[int]
    date_from: date
    date_to: date
    ledger: LedgerSettings
    bench: BenchmarkSettings
    score: ScoreSettings


@dataclass
class SystemResult:
    system_id: int
    ledger: pd.DataFrame
    days: list[dict]
    summary: dict
    models: dict
    warnings: list[str]


def _bms_rows(engine: Engine, sid: int, d0: date, d1: date) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("""SELECT count(*) FROM battery_telemetry.system_telemetry WHERE system_id = :s
                                        AND ts >= CAST(:a AS date) AND ts < CAST(:b AS date) + 1"""),
                                {"s": sid, "a": d0, "b": d1}).scalar())


def statement(w: dict) -> Optional[str]:
    """The one-paragraph reading of a window's chain (where the round trip goes)."""
    if not w.get("has_cycle"):
        return None
    r, s = w["rte"], w["shares"]
    pts = {k: 100 * v for k, v in s.items()}
    order = sorted(pts.items(), key=lambda kv: -kv[1])
    parts = ", ".join(f"{STAGE_LABELS[k].lower()} {v:.2f}" for k, v in order if abs(v) >= 0.005)
    gap_dc_plant = 100 * (r["term"] - r["poi"])
    tail = (f" Between the battery terminals ({100 * r['term']:.1f} %) and the plant ({100 * r['poi']:.1f} %) the round trip "
            f"loses {gap_dc_plant:.1f} pts: PCS {pts.get('pcs', 0):.2f}, transformer {pts.get('xfmr', 0):.2f}, "
            f"auxiliaries {pts.get('aux', 0):.2f}, DC cabling {pts.get('dc', 0):.2f}.")
    pr = w.get("performance_ratio")
    pr_txt = f" Performance ratio {100 * pr:.1f} % of the benchmark." if pr else ""
    return (f"Plant round-trip efficiency {100 * r['poi']:.1f} % (POI excl. auxiliaries {100 * r['poi_x']:.1f} %, PCS AC "
            f"{100 * r['ac']:.1f} %). The {100 * (1 - r['poi']):.1f} pts lost split into: {parts} pts.{tail}{pr_txt}")


def run_system(engine: Engine, sid: int, cfg: RunConfig) -> SystemResult:
    m = D.master(engine, sid)
    warnings = [f"{m.system_name}: {n}" for n in m.notes]
    raw = D.series(engine, m, cfg.date_from, cfg.date_to)
    if raw.empty:
        raise D.LossDataError(f"{m.system_name} has no time-aligned BMS / PCS / EMS rows in {cfg.date_from} → {cfg.date_to}")
    n_bms = _bms_rows(engine, sid, cfg.date_from, cfg.date_to)
    if n_bms > len(raw):
        warnings.append(f"{m.system_name}: {n_bms - len(raw)} of {n_bms} BMS intervals have no PCS or EMS reading at the "
                        "same timestamp and are left out (time alignment)")
    ocv = D.ocv_table(engine, m.chemistry)
    led = build(raw, m, ocv, cfg.ledger)
    warnings += [f"{m.system_name}: {n}" for n in led.notes]
    models = fit_and_apply(led, cfg.ledger, cfg.bench, m.self_discharge_pct_day, m.rated_kva)
    df = led.df
    guarantee = (cfg.score.guarantee_rte_pct / 100 if cfg.score.guarantee_rte_pct is not None
                 else (m.rte_ac_param if m.rte_ac_param else 0.85))
    usable = m.usable_kwh or led.kwh_per_pct * 100
    days = daily(df, led.step_h, usable, led.stats["rated_kw"], led.kwh_per_pct, cfg.score, guarantee, models, m.rated_kva)
    w = window(df, led.step_h, usable, led.stats["rated_kw"], cfg.score, guarantee)

    # audits
    if not models["transformer"]["metered_residual"]:
        if cfg.ledger.transformer_mode == "metered":
            warnings.append(f"{m.system_name}: the POI meter reads PCS AC + auxiliaries to within "
                            f"{led.stats['xfmr_residual_abs_max_kw']:.2f} kW - no transformer loss is metered (the POI "
                            "meter sits on the LV side, or the data has none). Use the nameplate transformer model to "
                            "include a modelled loss; the closure then shows it against the meters.")
        else:
            warnings.append(f"{m.system_name}: the transformer loss is modelled from the nameplate (not metered); the "
                            f"identity's closure error ({w['closure_kwh']:,.0f} kWh) is that model against meters that "
                            "show no transformer loss.")
    if led.stats["dc_meter_abs_mean_kw"] < 0.01:
        warnings.append(f"{m.system_name}: the PCS DC meter and the BMS power are the same reading - DC cabling loss is "
                        "not measurable (0)")
    if w["has_cycle"] and w["rte"]["term"] > 1.0:
        warnings.append(f"{m.system_name}: the battery terminal round trip is above 100 % ({100 * w['rte']['term']:.2f} %) "
                        "- the terminal counters / SOC show no battery loss")
    bc = [d["battery_closure"]["diff_kwh"] for d in days if d["battery_closure"]["diff_kwh"] is not None]
    if not cfg.bench.baseline_days or len({d["day"] for d in days if d["is_baseline"]}) < 2:
        warnings.append(f"{m.system_name}: the baseline window has fewer than 2 days - control limits are rough")
    low = [d for d in days if not d["has_cycle"]]
    if low:
        warnings.append(f"{m.system_name}: {len(low)} day(s) have too little charge and discharge for a round trip "
                        f"(< {100 * cfg.score.min_cycle_frac:.0f} % of usable energy each way): no RTE, only losses")
    for stage, mdl in (("battery", models["battery"]["directions"]), ("PCS", models["pcs"]["directions"])):
        for d, x in mdl.items():
            r2 = (x.get("out_of_baseline") or {}).get("r2")
            if r2 is not None and r2 < 0.5:
                warnings.append(f"{m.system_name}: the {stage} benchmark ({d.lower()}) generalises weakly beyond the baseline "
                                f"(R² {r2:.2f}) - treat its excess and alarms as indicative")
    noisy = sorted({k for d in days for k, c in d.get("control", {}).items() if c.get("status") == "noisy"})
    if noisy:
        warnings.append(f"{m.system_name}: {', '.join(noisy)} scatter more day to day than their own size - charted, no "
                        "alarms (e.g. standby is below the SOC measurement noise)")
    alarms = {}
    for d in days:
        for k, c in d.get("control", {}).items():
            if c.get("status") not in (None, "ok", "noisy"):
                alarms.setdefault(k, []).append(d["day"].isoformat())

    summary = {
        "system_id": sid, "system_name": m.system_name, "site_name": m.site_name, "rated_kw": led.stats["rated_kw"],
        "rated_kva": m.rated_kva, "usable_kwh": usable, "kwh_per_pct": led.kwh_per_pct, "cells_series": led.cells_series,
        "guarantee_rte": guarantee, "guarantee_basis": cfg.score.guarantee_basis,
        "guarantee_source": "parameter" if cfg.score.guarantee_rte_pct is not None else
                            ("battery_opt_param.rte_ac" if m.rte_ac_param else "default 85 %"),
        "pcs_nameplate_eff_pct": m.pcs_nameplate_eff_pct, "window": w, "statement": statement(w),
        "audit": {**led.stats,
                  "battery_closure_abs_mean_kwh_day": float(np.mean(np.abs(bc))) if bc else None,
                  "counters": _counter_totals(days)},
        "loading_curve": loading_curve(df, led.stats["rated_kw"]),
        "direction": direction_split(df, led.step_h),
        "alarms": alarms,
        "days": len(days), "baseline_days": sum(1 for d in days if d["is_baseline"]),
    }
    return SystemResult(sid, df, days, summary, models, warnings)


def _counter_totals(days: list[dict]) -> dict:
    out: dict = {}
    for d in days:
        for k, v in d["counters"].items():
            t = out.setdefault(k, {"counter_kwh": 0.0, "integral_kwh": 0.0, "diff_kwh": 0.0, "days_missing": 0})
            if v["counter_kwh"] is None:
                t["days_missing"] += 1
                continue
            t["counter_kwh"] += v["counter_kwh"]
            t["integral_kwh"] += v["integral_kwh"]
            t["diff_kwh"] += v["diff_kwh"]
    for t in out.values():
        t["diff_pct"] = 100 * t["diff_kwh"] / t["integral_kwh"] if t["integral_kwh"] else None
    return out


def run(engine: Engine, cfg: RunConfig) -> dict:
    started = time.perf_counter()
    results, warnings = [], []
    for sid in cfg.system_ids:
        r = run_system(engine, sid, cfg)
        results.append(r)
        warnings += r.warnings
    fleet = []
    for r in results:
        w = r.summary["window"]
        fleet.append({"system_id": r.system_id, "system_name": r.summary["system_name"], "site_name": r.summary["site_name"],
                      "rte_plant": w["rte"].get("poi"), "rte_poi_excl_aux": w["rte"].get("poi_x"),
                      "rte_ac": w["rte"].get("ac"), "rte_term": w["rte"].get("term"),
                      "performance_ratio": w["performance_ratio"], "guarantee_gap_pts": w["guarantee_gap_pts"],
                      "shares": w["shares"], "aux_pct_of_throughput": w["aux_pct_of_throughput"],
                      "total_loss_kwh": w["total_loss_kwh"], "loss_usd": w["loss_usd"], "excess_usd": w["excess_usd"],
                      "excess_kwh": w["excess_kwh_total"], "utilization_pct": w["utilization_pct"],
                      "cycles": w["cycles"], "alarms": {k: len(v) for k, v in r.summary["alarms"].items()}})
    return {"results": results, "warnings": warnings, "fleet": fleet,
            "duration_ms": int((time.perf_counter() - started) * 1000)}
