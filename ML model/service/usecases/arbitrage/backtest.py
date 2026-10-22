"""A study = the optimizer run day by day over a date range (receding horizon), executed and scored.

Per day (the day-ahead vintage issued before it):
  plan      deterministic: one MILP on the P50 forecast (hourly). stochastic: rolling two-stage MILP over the price
            scenarios - re-solved every `resolve_every_h` hours with the next block as here-and-now decisions and
            the rest as scenario recourse; only the block is executed, then the state rolls forward.
  execute   the hourly schedule held over the day's 15-min intervals, settled at rt_price (perfect execution):
            gross = price × energy; degradation = degradation_cost_mwh × |energy| (scalar, comparable with the pack's
            dispatch_outcome); grid = wheeling × |e| + duty × import / export + tax × |price × e|; AS = capacity price
            × MW × Δt (reported apart from net, like the pack). SOC uses the planning efficiency model.
  oracle    the same MILP on the realized 15-min prices (perfect foresight) from the same starting SOC - the gap is
            what better forecasts are worth.
SOC chains from day to day; the first day starts from the pack's decision_state. Terminal SOC (default next_open):
the next day's planned opening SOC (the pack's decision_state of that day), else the day's start.
"""
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from usecases.arbitrage import data as D
from usecases.arbitrage.optimizer import Settings, solve


@dataclass
class StudyConfig:
    system_id: int
    date_from: date
    date_to: date
    mode: str = "deterministic"          # deterministic | stochastic
    settings: Settings = field(default_factory=Settings)
    resolve_every_h: int = 4
    name: Optional[str] = None


def settle(e_mwh: np.ndarray, price: np.ndarray, g: D.GridCharges, deg_mwh: float) -> dict:
    gross = price * e_mwh
    degr = deg_mwh * np.abs(e_mwh)
    grid = (g.wheeling_mwh * np.abs(e_mwh) + g.import_duty_mwh * np.maximum(-e_mwh, 0)
            + g.export_duty_mwh * np.maximum(e_mwh, 0) + g.tax_fraction * np.abs(price * e_mwh))
    return {"gross": gross, "degr": degr, "grid": grid, "net": gross - degr - grid}


def _execute(di: D.DayInputs, p_net_h: np.ndarray, drain_h: np.ndarray, c_h: np.ndarray, soc0: float,
             b: D.Battery, g: D.GridCharges) -> dict:
    """Hourly plan held over the 15-min intervals."""
    hpos = {h: i for i, h in enumerate(di.hours)}
    idx = np.array([hpos[q.floor("h")] for q in di.quarters], dtype=int)
    p = p_net_h[idx]
    e = p * 0.25 / 1000.0
    sd_q = b.self_discharge_pct_day * 0.25 / 24.0
    soc = soc0 + np.cumsum(drain_h[idx] / 4.0 - sd_q)
    out = settle(e, di.rt, g, b.degradation_cost_mwh)
    out.update(p=p, e=e, soc=soc, c=c_h[idx], as_usd=di.as_price_h[idx] * c_h[idx] * 0.25, fc=di.p50[idx])
    return out


def _quarter_as_price(di: D.DayInputs) -> np.ndarray:
    hpos = {h: i for i, h in enumerate(di.hours)}
    return np.array([di.as_price_h[hpos[q.floor("h")]] for q in di.quarters])


def run_day(di: D.DayInputs, b: D.Battery, g: D.GridCharges, a: D.AsInfo, cfg: StudyConfig, soc0: float,
            prev_net: float, next_open: Optional[float] = None) -> dict:
    s = cfg.settings
    st = di.pack_state or {}
    usable = st.get("usable_energy_mwh") or b.usable_mwh
    pdis, pchg = st.get("p_discharge_avail_kw"), st.get("p_charge_avail_kw")
    used = st.get("cycles_used_today") or 0.0
    cycles_left = None if b.max_cycles_per_day is None else b.max_cycles_per_day - used
    soc0 = float(min(max(soc0, b.soc_min), b.soc_max))
    target = next_open if (s.terminal == "next_open" and next_open is not None) else soc0
    H = len(di.hours)
    as_cap = s.as_max_mw if s.as_max_mw is not None else st.get("reserved_mw_as")
    common = dict(dt_h=1.0, p_dis_avail=pdis, p_chg_avail=pchg, usable_mwh=usable, terminal_target=target,
                  as_cap_mw=as_cap)

    if cfg.mode == "stochastic":
        pd_h, pc_h, c_h, drain_h, soc_h = (np.zeros(H) for _ in range(5))
        soc, net, left, secs, expected, status = soc0, prev_net, cycles_left, 0.0, None, "OPTIMAL"
        block = max(1, int(cfg.resolve_every_h))
        for h0 in range(0, H, block):
            F = min(block, H - h0)
            plan = solve(b, g, a, s, di.scenarios[:, h0:], di.scenario_probs, soc0=soc, prev_net_kw=net,
                         cycles_left=left, as_price=di.as_price_h[h0:], as_floor=di.as_floor_h[h0:],
                         first_stage=F, **common)
            if expected is None:
                expected = plan.objective
            secs += plan.solve_seconds
            status = plan.status if plan.status != "OPTIMAL" else status
            sl = slice(h0, h0 + F)
            pd_h[sl], pc_h[sl], c_h[sl] = plan.pd[:F], plan.pc[:F], plan.c_as[:F]
            drain_h[sl], soc_h[sl] = plan.drain[:F], plan.soc[:F]
            soc = float(plan.soc[F - 1])
            net = float(plan.pd[F - 1] - plan.pc[F - 1])
            if left is not None:
                left -= float(plan.pd[:F].sum()) / (usable * 1000.0)
    else:
        plan = solve(b, g, a, s, di.p50[None, :], np.array([1.0]), soc0=soc0, prev_net_kw=prev_net,
                     cycles_left=cycles_left, as_price=di.as_price_h, as_floor=di.as_floor_h, **common)
        pd_h, pc_h, c_h, drain_h, soc_h = plan.pd, plan.pc, plan.c_as, plan.drain, plan.soc
        expected, secs, status = plan.objective, plan.solve_seconds, plan.status

    p_net_h = pd_h - pc_h
    policy = _execute(di, p_net_h, drain_h, c_h, soc0, b, g)

    # perfect-foresight oracle on the realized 15-min prices, same constraints and start
    o = solve(b, g, a, s, di.rt[None, :], np.array([1.0]), dt_h=0.25, soc0=soc0, prev_net_kw=prev_net,
              cycles_left=cycles_left, as_price=_quarter_as_price(di), as_floor=di.as_floor_q,
              p_dis_avail=pdis, p_chg_avail=pchg, usable_mwh=usable, terminal_target=target, as_cap_mw=as_cap)
    o_e = (o.pd - o.pc) * 0.25 / 1000.0
    oracle = settle(o_e, di.rt, g, b.degradation_cost_mwh)
    oracle.update(p=o.pd - o.pc, e=o_e, soc=o.soc, c=o.c_as, as_usd=_quarter_as_price(di) * o.c_as * 0.25,
                  fc=policy["fc"])

    dis = float(np.maximum(policy["e"], 0).sum())
    chg = float(np.maximum(-policy["e"], 0).sum())
    net_total = float(policy["net"].sum())
    o_net = float(oracle["net"].sum())
    soc_path = np.concatenate([[soc0], policy["soc"]])
    checks = {
        "soc_in_band": bool(soc_path.min() >= b.soc_min - 0.05 and soc_path.max() <= b.soc_max + 0.05),
        "no_simultaneous": bool(np.all(np.minimum(pd_h, pc_h) < 1e-3)),
        "cycle_cap": bool(cycles_left is None or dis / usable <= cycles_left + 1e-6),
        # the oracle optimizes the planning objective; with the DoD-layer degradation curve its realized (scalar)
        # net can fall a little below the policy's, so the check only holds strictly with scalar degradation
        "profit_le_oracle": bool(net_total + float(policy["as_usd"].sum())
                                 <= o_net + float(oracle["as_usd"].sum()) + 0.01) or s.degradation == "curve",
    }
    return {
        "day": di.day, "status": status, "as_cap_mw": as_cap, "terminal_target": target, "solve_seconds": secs + o.solve_seconds, "expected": expected,
        "soc_start": soc0, "soc_end": float(policy["soc"][-1]) if len(policy["soc"]) else soc0,
        "prev_net_end": float(p_net_h[-1]) if H else prev_net,
        "plan": {"p_net": p_net_h, "soc": soc_h, "c": c_h, "fc": di.p50},
        "policy": policy, "oracle": oracle,
        "discharge_mwh": dis, "charge_mwh": chg, "cycles": dis / usable, "usable_mwh": usable,
        "net": net_total, "gross": float(policy["gross"].sum()), "degr": float(policy["degr"].sum()),
        "grid": float(policy["grid"].sum()), "as_usd": float(policy["as_usd"].sum()), "oracle_net": o_net,
        "oracle_as": float(oracle["as_usd"].sum()), "checks": checks, "cycles_left": cycles_left,
    }


def pack_reference(engine: Engine, cfg: StudyConfig, g: D.GridCharges, deg: float) -> dict:
    """The pack's realized outcomes in the study range, and the same energy settled with this model's costs."""
    start = pd.Timestamp(cfg.date_from).tz_localize(D.PLANT_TZ)
    end = pd.Timestamp(D.add_days(cfg.date_to, 1)).tz_localize(D.PLANT_TZ)
    df = D.pack_outcomes(engine, cfg.system_id, start, end)
    if df.empty:
        return {"rows": 0}
    s = settle(df["energy_mwh"].values, df["price_mwh"].values, g, deg)
    logged = {k: float(df[c].sum()) for k, c in (("gross", "gross_revenue_usd"), ("degr", "degradation_cost_usd"),
                                                 ("grid", "grid_cost_usd"), ("net", "net_pnl_usd"))}
    model = {k: float(v.sum()) for k, v in s.items()}
    daily = df.groupby(df["interval_start"].dt.date)["net_pnl_usd"].sum().to_dict()
    return {"rows": len(df), "logged": logged, "model": model, "daily_net": daily,
            "max_diff": max(abs(logged[k] - model[k]) for k in logged)}


def run_study(engine: Engine, cfg: StudyConfig) -> dict:
    t0 = time.perf_counter()
    if cfg.date_from > cfg.date_to:
        raise D.ArbitrageDataError("date_from must be on or before date_to")
    node_id, node_code = D.node_of(engine, cfg.system_id)
    a = D.as_info(engine)
    days = D.days_with_forecast(engine, node_id, cfg.date_from, cfg.date_to)
    if not days:
        raise D.ArbitrageDataError("No day-ahead price forecasts in the selected range")

    results, warnings = [], []
    soc, prev_net = None, 0.0
    b0 = D.battery(engine, cfg.system_id, days[0])
    g0 = D.grid_charges(engine, b0.site_id, days[0])
    if not any((g0.wheeling_mwh, g0.import_duty_mwh, g0.tax_fraction)):
        warnings.append("No grid charges for the site - grid cost is 0")
    for day in days:
        b = D.battery(engine, cfg.system_id, day)
        g = D.grid_charges(engine, b.site_id, day)
        di = D.day_inputs(engine, cfg.system_id, node_id, day, a.product_id)
        if len(di.quarters) == 0:
            warnings.append(f"{day}: no real-time prices - skipped")
            continue
        start_soc = soc if soc is not None else ((di.pack_state or {}).get("soc_start_pct") or 50.0)
        r = run_day(di, b, g, a, cfg, start_soc, prev_net, D.planned_open_soc(engine, cfg.system_id, D.add_days(day, 1)))
        r["inputs"] = di
        r["battery"] = b
        if len(di.hours) < 24:
            warnings.append(f"{day}: forecast covers {len(di.hours)} h only")
        results.append(r)
        soc, prev_net = r["soc_end"], r["prev_net_end"]
    if not results:
        raise D.ArbitrageDataError("No day had both a forecast and real-time prices")

    # study-level checks
    ref = pack_reference(engine, cfg, g0, b0.degradation_cost_mwh)
    first = results[0]
    di0, b_first = first["inputs"], first["battery"]
    st0 = di0.pack_state or {}
    common = dict(dt_h=1.0, soc0=first["soc_start"], prev_net_kw=0.0, as_price=di0.as_price_h,
                  as_floor=di0.as_floor_h, usable_mwh=st0.get("usable_energy_mwh"),
                  as_cap_mw=cfg.settings.as_max_mw if cfg.settings.as_max_mw is not None else st0.get("reserved_mw_as"))
    base = solve(b_first, g0, a, Settings(**{**cfg.settings.__dict__, "deg_cost_override": None}), di0.p50[None, :],
                 np.array([1.0]), cycles_left=None, **common)
    free = solve(b_first, g0, a, Settings(**{**cfg.settings.__dict__, "deg_cost_override": 0.0}), di0.p50[None, :],
                 np.array([1.0]), cycles_left=None, **common)
    thr_base, thr_free = float(base.pd.sum() + base.pc.sum()), float(free.pd.sum() + free.pc.sum())
    dis_tot = sum(r["discharge_mwh"] for r in results)
    chg_tot = sum(r["charge_mwh"] for r in results)
    e_start = (results[0]["soc_start"] - results[-1]["soc_end"]) / 100.0 * results[0]["usable_mwh"]
    checks = {
        "soc_in_band": all(r["checks"]["soc_in_band"] for r in results),
        "no_simultaneous": all(r["checks"]["no_simultaneous"] for r in results),
        "cycle_cap": all(r["checks"]["cycle_cap"] for r in results),
        "profit_le_oracle": all(r["checks"]["profit_le_oracle"] for r in results),
        "losses_present": bool(chg_tot > 0 and dis_tot < chg_tot + max(e_start, 0) + 1e-6),
        "deg_cost_bites": bool(thr_free >= thr_base - 1e-6),
        "pack_settlement_reproduced": bool(ref.get("rows") and ref["max_diff"] < 0.05),
    }
    details = {
        "deg_zero_throughput_kwh": thr_free, "deg_base_throughput_kwh": thr_base,
        "implied_rte_pct": 100.0 * dis_tot / (chg_tot + max(e_start, 0)) if chg_tot else None,
        "pack_reference": {k: v for k, v in ref.items() if k != "daily_net"},
    }
    tot = {k: float(sum(r[k] for r in results)) for k in ("net", "gross", "degr", "grid", "as_usd", "oracle_net",
                                                         "oracle_as", "discharge_mwh", "charge_mwh", "cycles",
                                                         "solve_seconds")}
    tot["expected"] = float(sum(r["expected"] or 0 for r in results))
    pack_daily = ref.get("daily_net", {})
    pack_days = [d for d in (r["day"] for r in results) if d in pack_daily]
    metrics = {
        **{f"{k}_usd" if k in ("net", "gross", "degr", "grid", "expected", "oracle_net", "oracle_as") else k: v
           for k, v in tot.items()},
        "days": len(results),
        "total_usd": tot["net"] + tot["as_usd"],
        "oracle_total_usd": tot["oracle_net"] + tot["oracle_as"],
        "forecast_value_usd": (tot["oracle_net"] + tot["oracle_as"]) - (tot["net"] + tot["as_usd"]),
        "capture_pct": 100.0 * (tot["net"] + tot["as_usd"]) / (tot["oracle_net"] + tot["oracle_as"])
        if tot["oracle_net"] + tot["oracle_as"] else None,
        "optimism_gap_usd": tot["expected"] - (tot["net"] + tot["as_usd"]),
        "usd_per_mwh_discharged": tot["net"] / tot["discharge_mwh"] if tot["discharge_mwh"] else None,
        # round trip corrected for the SOC carried in / out of the range (discharge ÷ (charge + energy drawn down))
        "rte_pct": details["implied_rte_pct"],
        "pack_net_usd": float(sum(pack_daily[d] for d in pack_days)) if pack_days else None,
        "pack_days": len(pack_days),
        "policy_net_on_pack_days_usd": float(sum(r["net"] for r in results if r["day"] in pack_daily)),
        "node_code": node_code,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }
    return {"results": results, "metrics": metrics, "checks": checks, "check_details": details,
            "warnings": warnings, "node_id": node_id, "pack_daily": pack_daily, "as_product_id": a.product_id}
