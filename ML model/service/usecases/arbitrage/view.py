"""Read model of the Dispatch Viewer: one day of one source, ready for the panels.

source = pack    the data pack's own run of the day (optimization_run without study) - plan from dispatch_schedule,
                 realized power and P&L from dispatch_outcome; realized SOC is rebuilt from the outcome energy and the
                 run's decision_state (planning efficiency √rte_ac); the oracle is solved on demand (cached).
source = study   a study's run of the day - plan from dispatch_schedule, executed power / SOC / P&L and the oracle from
                 battery_ml.arb_backtest.
Prices: rt_price (15-min), dam_price and the run's forecast vintage (P10 / P50 / P90, hourly) for every interval.
Power sign: + discharge / − charge.
"""
from datetime import date, datetime
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from usecases.arbitrage import data as D
from usecases.arbitrage.backtest import StudyConfig, run_day
from usecases.arbitrage.optimizer import Settings


class ViewError(Exception):
    pass


def _n(v, nd=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if np.isfinite(f) else None


def days(engine: Engine, source: str, system_id: int, study_id: Optional[int]) -> list[dict]:
    with engine.connect() as conn:
        if source == "study":
            rows = conn.execute(text("""
                SELECT kpi_date, run_id, net_usd + COALESCE((checks->>'as_usd')::numeric, 0) AS total_usd, net_usd
                FROM battery_ml.arb_study_day WHERE study_id = :id ORDER BY kpi_date"""), {"id": study_id}).mappings().all()
        else:
            rows = conn.execute(text("""
                SELECT CAST(r.horizon_start AS date) AS kpi_date, r.run_id,
                       (SELECT SUM(o.net_pnl_usd) FROM battery_master.dispatch_outcome o
                        WHERE o.run_id = r.run_id) AS net_usd
                FROM battery_master.optimization_run r
                WHERE r.system_id = :s AND r.study_id IS NULL ORDER BY r.horizon_start"""), {"s": system_id}).mappings().all()
    return [{k: (_n(v, 2) if k in ("net_usd", "total_usd") else v) for k, v in r.items()} for r in rows]


def _run(conn, system_id: int, start: pd.Timestamp, study_id: Optional[int]):
    q = """SELECT r.run_id, r.issued_at, r.horizon_start, r.horizon_end, r.method, r.objective, r.solver_status,
                  r.expected_profit_usd, r.solve_seconds, d.soc_start_pct, d.soh_pct, d.usable_energy_mwh,
                  d.avg_cell_temp_c, d.p_charge_avail_kw, d.p_discharge_avail_kw, d.cycles_used_today,
                  d.aux_load_forecast_kw, d.reserved_mw_as
           FROM battery_master.optimization_run r LEFT JOIN battery_master.decision_state d ON d.run_id = r.run_id
           WHERE r.system_id = :s AND r.horizon_start = :t AND """
    q += "r.study_id = :study" if study_id else "r.study_id IS NULL"
    return conn.execute(text(q + " ORDER BY r.run_id DESC LIMIT 1"),
                        {"s": system_id, "t": start, "study": study_id}).mappings().first()


@lru_cache(maxsize=64)
def _pack_oracle(system_id: int, day: date, soc0: float, version: int):
    """Perfect-foresight oracle for a pack day (energy only, scalar costs), from the pack's starting SOC."""
    from core.db import engine
    node_id, _ = D.node_of(engine, system_id)
    a = D.as_info(engine)
    b = D.battery(engine, system_id, day)
    g = D.grid_charges(engine, b.site_id, day)
    di = D.day_inputs(engine, system_id, node_id, day, a.product_id)
    r = run_day(di, b, g, a, StudyConfig(system_id, day, day, "deterministic", Settings(as_stacking=False)), soc0, 0.0,
                D.planned_open_soc(engine, system_id, D.add_days(day, 1)))
    o = r["oracle"]
    return [q.isoformat() for q in di.quarters], o["p"], o["soc"], o["net"], float(o["net"].sum())


def day_view(engine: Engine, source: str, day: date, system_id: int, study_id: Optional[int] = None) -> dict:
    start = pd.Timestamp(datetime.combine(day, datetime.min.time())).tz_localize(D.PLANT_TZ)
    end = start + pd.Timedelta(days=1)
    node_id, node_code = D.node_of(engine, system_id)
    b = D.battery(engine, system_id, day)
    with engine.connect() as conn:
        run = _run(conn, system_id, start, study_id if source == "study" else None)
        if not run:
            raise ViewError(f"No {'study ' + str(study_id) if source == 'study' else 'pack'} run for {day}")
        sched = pd.read_sql(text("""
            SELECT interval_start, p_setpoint_kw, soc_target_pct, mode, market, forecast_price_mwh
            FROM battery_master.dispatch_schedule WHERE run_id = :r ORDER BY interval_start"""), conn,
            params={"r": run["run_id"]})
        fc = pd.read_sql(text("""
            SELECT target_ts, p10_mwh, p50_mwh, p90_mwh FROM battery_master.price_forecast
            WHERE node_id = :n AND issued_at = :i AND target_ts >= :a AND target_ts < :b"""), conn,
            params={"n": node_id, "i": run["issued_at"], "a": start, "b": end})
        rt = pd.read_sql(text("""SELECT interval_start, price_mwh FROM battery_master.rt_price
                                 WHERE node_id = :n AND interval_start >= :a AND interval_start < :b"""), conn,
                         params={"n": node_id, "a": start, "b": end})
        dam = pd.read_sql(text("""SELECT delivery_start, price_mwh FROM battery_master.dam_price
                                  WHERE node_id = :n AND delivery_start >= :a AND delivery_start < :b"""), conn,
                          params={"n": node_id, "a": start, "b": end})
        if source == "study":
            bt = pd.read_sql(text("""SELECT * FROM battery_ml.arb_backtest
                                     WHERE study_id = :s AND interval_start >= :a AND interval_start < :b
                                     ORDER BY kind, interval_start"""), conn,
                             params={"s": study_id, "a": start, "b": end})
            sday = conn.execute(text("SELECT * FROM battery_ml.arb_study_day WHERE study_id = :s AND kpi_date = :d"),
                                {"s": study_id, "d": day}).mappings().first()
            study = conn.execute(text("SELECT study_name, mode, params FROM battery_ml.arb_study WHERE study_id = :s"),
                                 {"s": study_id}).mappings().first()
    for df, col in ((sched, "interval_start"), (fc, "target_ts"), (rt, "interval_start"), (dam, "delivery_start")):
        if not df.empty:
            df[col] = pd.to_datetime(df[col]).dt.tz_convert(D.PLANT_TZ)
    fc_h = fc.set_index("target_ts") if not fc.empty else pd.DataFrame()
    dam_h = dam.set_index("delivery_start")["price_mwh"] if not dam.empty else pd.Series(dtype=float)
    sched_h = sched.set_index("interval_start") if not sched.empty else pd.DataFrame()

    usable = float(run["usable_energy_mwh"] or b.usable_mwh)
    soc0 = float(run["soc_start_pct"] or 50.0)
    eta = float(np.sqrt(b.rte_ac))
    oracle = None
    if source == "pack":
        out = D.pack_outcomes(engine, system_id, start, end)
        if out.empty:
            raise ViewError(f"No dispatch_outcome for {day}")
        q = out["interval_start"]
        e = out["energy_mwh"].values
        soc = soc0 + np.cumsum(np.where(e < 0, -e * eta, -e / eta)) / usable * 100.0
        series = pd.DataFrame({"ts": q, "p_sched": out["p_scheduled_kw"].values, "p_actual": out["p_actual_kw"].values,
                               "soc": soc, "gross": out["gross_revenue_usd"].values,
                               "degr": out["degradation_cost_usd"].values, "grid": out["grid_cost_usd"].values,
                               "as_usd": 0.0, "net": out["net_pnl_usd"].values, "e": e, "c": 0.0})
        try:
            ts, op, osoc, onet, o_total = _pack_oracle(system_id, day, soc0, 1)
            oracle = {"intervals": [{"ts": t, "p": _n(p, 2), "soc": _n(s, 2), "net": _n(n)}
                                    for t, p, s, n in zip(ts, op, osoc, onet)], "net_usd": _n(o_total, 2),
                      "as_usd": 0.0, "total_usd": _n(o_total, 2), "note": "solved on demand, energy only"}
        except Exception as exc:  # noqa: BLE001 - the viewer still works without the oracle
            oracle = {"error": str(exc)}
    else:
        pol, ora = bt[bt["kind"] == "policy"], bt[bt["kind"] == "oracle"]
        if pol.empty:
            raise ViewError(f"No backtest rows for study {study_id} on {day}")
        q = pd.to_datetime(pol["interval_start"]).dt.tz_convert(D.PLANT_TZ)
        series = pd.DataFrame({"ts": q.values, "p_sched": pol["p_kw"].astype(float).values,
                               "p_actual": pol["p_kw"].astype(float).values, "soc": pol["soc_pct"].astype(float).values,
                               "gross": pol["gross_usd"].astype(float).values,
                               "degr": pol["degradation_usd"].astype(float).values,
                               "grid": pol["grid_usd"].astype(float).values, "as_usd": pol["as_usd"].astype(float).values,
                               "net": pol["net_usd"].astype(float).values, "e": pol["energy_mwh"].astype(float).values,
                               "c": pol["c_as_mw"].astype(float).values})
        series["ts"] = pd.to_datetime(series["ts"]).dt.tz_localize("UTC").dt.tz_convert(D.PLANT_TZ) \
            if series["ts"].dt.tz is None else series["ts"]
        o_ts = pd.to_datetime(ora["interval_start"]).dt.tz_convert(D.PLANT_TZ)
        o_net, o_as = float(ora["net_usd"].astype(float).sum()), float(ora["as_usd"].astype(float).sum())
        oracle = {"intervals": [{"ts": t.isoformat(), "p": _n(p, 2), "soc": _n(s, 2), "net": _n(n)}
                                for t, p, s, n in zip(o_ts, ora["p_kw"], ora["soc_pct"], ora["net_usd"])],
                  "net_usd": _n(o_net, 2), "as_usd": _n(o_as, 2), "total_usd": _n(o_net + o_as, 2)}

    rt_q = rt.set_index("interval_start")["price_mwh"] if not rt.empty else pd.Series(dtype=float)
    intervals = []
    for r in series.itertuples():
        ts = pd.Timestamp(r.ts)
        h = ts.floor("h")
        f = fc_h.loc[h] if not fc_h.empty and h in fc_h.index else None
        sh = sched_h.loc[h] if not sched_h.empty and h in sched_h.index else None
        intervals.append({
            "ts": ts.isoformat(), "rt": _n(rt_q.get(ts), 2), "dam": _n(dam_h.get(h), 2),
            "p10": _n(f["p10_mwh"], 2) if f is not None else None, "p50": _n(f["p50_mwh"], 2) if f is not None else None,
            "p90": _n(f["p90_mwh"], 2) if f is not None else None, "p_sched": _n(r.p_sched, 2),
            "p_actual": _n(r.p_actual, 2), "soc": _n(r.soc, 2),
            "soc_plan": _n(sh["soc_target_pct"], 2) if sh is not None else None, "c_as": _n(r.c, 3),
            "gross": _n(r.gross), "degr": _n(r.degr), "grid": _n(r.grid), "as_usd": _n(r.as_usd), "net": _n(r.net)})

    e = series["e"].values.astype(float)
    dis, chg = float(np.maximum(e, 0).sum()), float(np.maximum(-e, 0).sum())
    tot = {k: float(series[k].astype(float).sum()) for k in ("gross", "degr", "grid", "as_usd", "net")}
    total = tot["net"] + tot["as_usd"]
    o_total = oracle.get("total_usd") if oracle and "error" not in oracle else None
    expected = _n(run["expected_profit_usd"], 2)
    kpis = {
        "net_usd": _n(tot["net"], 2), "gross_usd": _n(tot["gross"], 2), "degradation_usd": _n(tot["degr"], 2),
        "grid_usd": _n(tot["grid"], 2), "as_usd": _n(tot["as_usd"], 2), "total_usd": _n(total, 2),
        "discharge_mwh": _n(dis, 3), "charge_mwh": _n(chg, 3),
        "usd_per_mwh_discharged": _n(tot["net"] / dis, 2) if dis else None,
        "cycles": _n(dis / usable, 3), "cycle_cap": b.max_cycles_per_day,
        "rte_pct": _n(100 * dis / chg, 1) if chg else None,
        "schedule_mae_kw": _n(np.mean(np.abs(series["p_sched"].astype(float) - series["p_actual"].astype(float))), 1),
        "oracle_total_usd": o_total,
        "forecast_value_usd": _n(o_total - total, 2) if o_total is not None else None,
        "capture_pct": _n(100 * total / o_total, 1) if o_total else None,
        "expected_usd": expected, "optimism_gap_usd": _n(expected - total, 2) if expected is not None else None,
    }
    warnings = []
    soc_vals = series["soc"].astype(float)
    if len(soc_vals) and (soc_vals.max() > b.soc_max + 1 or soc_vals.min() < b.soc_min - 1):
        warnings.append(f"Realized SOC leaves the {b.soc_min:g}–{b.soc_max:g} % band (min {soc_vals.min():.1f} %, "
                        f"max {soc_vals.max():.1f} %): the outcome energy does not fit the {usable:.3f} MWh battery"
                        + (" - the pack's realized power and energy exceed the stated limits" if source == "pack" else ""))
    return {
        "warnings": warnings,
        "source": source, "day": day.isoformat(), "study_id": study_id, "system_id": system_id, "node_code": node_code,
        "study": dict(study) if source == "study" and study else None,
        "run": {k: (_n(v, 3) if k in ("expected_profit_usd", "solve_seconds") else
                    (v.isoformat() if hasattr(v, "isoformat") else v))
                for k, v in run.items() if k in ("run_id", "issued_at", "horizon_start", "horizon_end", "method",
                                                 "objective", "solver_status", "expected_profit_usd", "solve_seconds")},
        "state": {k: _n(v, 3) for k, v in run.items() if k in ("soc_start_pct", "soh_pct", "usable_energy_mwh",
                                                               "avg_cell_temp_c", "p_charge_avail_kw",
                                                               "p_discharge_avail_kw", "cycles_used_today",
                                                               "aux_load_forecast_kw", "reserved_mw_as")},
        "battery": {"soc_min": b.soc_min, "soc_max": b.soc_max, "usable_mwh": usable, "rte_ac": b.rte_ac,
                    "max_cycles_per_day": b.max_cycles_per_day, "p_max_kw": b.p_discharge_max_kw},
        "intervals": intervals,
        "hourly": [{"ts": pd.Timestamp(t).isoformat(), "p_setpoint": _n(r["p_setpoint_kw"], 2),
                    "soc_target": _n(r["soc_target_pct"], 2), "mode": r["mode"], "market": r["market"],
                    "forecast": _n(r["forecast_price_mwh"], 2)} for t, r in sched_h.iterrows()] if not sched_h.empty else [],
        "oracle": oracle,
        "kpis": kpis,
        "day_row": {k: (_n(v, 4) if isinstance(v, (int, float)) or hasattr(v, "is_finite") else v)
                    for k, v in dict(sday).items() if k not in ("study_id",)} if source == "study" and sday else None,
    }
