"""Studies in battery_ml.arb_study / arb_study_day / arb_backtest, and the daily runs they write into the decision chain
(battery_master.optimization_run with study_id -> decision_state -> dispatch_schedule). Deleting a study deletes all
of it (optimization_run.study_id ON DELETE CASCADE)."""
import json
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

STUDY_COLUMNS = """study_id, study_name, status, system_id, node_id, date_from, date_to, mode, params, metrics, checks,
    warnings, error_message, started_at, finished_at, duration_ms"""


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _json(v) -> str:
    return json.dumps(v, default=lambda o: _num(o) if isinstance(o, (np.floating, np.integer)) else
                      (bool(o) if isinstance(o, np.bool_) else str(o)))


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def start_study(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.arb_study (study_name, status, system_id, node_id, date_from, date_to, mode, params)
            VALUES (:name, 'RUNNING', :system_id, :node_id, :date_from, :date_to, :mode, CAST(:params AS jsonb))
            RETURNING study_id"""), {**values, "params": _json(values["params"])}).scalar_one()


def fail_study(engine: Engine, study_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.arb_study SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int
                             WHERE study_id = :id"""), {"id": study_id, "m": message[:2000]})


def _mode(p: float, c: float) -> tuple[str, str]:
    if p > 1:
        return "ENERGY_ARBITRAGE", "DAM"
    if p < -1:
        return "SCHEDULED_CHARGE", "DAM"
    if c > 0:
        return "FREQUENCY_REGULATION", "AS"
    return "STANDBY", "DAM"


def complete_study(engine: Engine, study_id: int, system_id: int, mode: str, as_on: bool, result: dict) -> None:
    method = "STOCHASTIC_MILP" if mode == "stochastic" else "MILP"
    objective = "ARBITRAGE+AS" if as_on else "ARBITRAGE"
    pack_daily = result.get("pack_daily", {})
    with engine.begin() as conn:
        for r in result["results"]:
            di, b = r["inputs"], r["battery"]
            st = di.pack_state or {}
            hours = di.hours
            run_id = conn.execute(text("""
                INSERT INTO battery_master.optimization_run (system_id, issued_at, horizon_start, horizon_end,
                    resolution_min, method, objective, solver_status, expected_profit_usd, solve_seconds, study_id)
                VALUES (:s, :issued, :hs, :he, 60, :method, :objective, :status, :exp, :secs, :study)
                RETURNING run_id"""), {
                "s": system_id, "issued": (di.issued_at or hours[0]).to_pydatetime(),
                "hs": hours[0].to_pydatetime(), "he": (hours[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
                "method": method, "objective": objective, "status": r["status"], "exp": _num(r["expected"]),
                "secs": round(float(r["solve_seconds"]), 3), "study": study_id}).scalar_one()
            plan = r["plan"]
            conn.execute(text("""
                INSERT INTO battery_master.decision_state (run_id, soc_start_pct, soh_pct, usable_energy_mwh,
                    avg_cell_temp_c, p_charge_avail_kw, p_discharge_avail_kw, cycles_used_today, aux_load_forecast_kw,
                    reserved_mw_as)
                VALUES (:r, :soc, :soh, :usable, :temp, :pch, :pdis, :cyc, :aux, :resv)"""), {
                "r": run_id, "soc": round(r["soc_start"], 2), "soh": st.get("soh_pct"),
                "usable": round(r["usable_mwh"], 3), "temp": st.get("avg_cell_temp_c"),
                "pch": st.get("p_charge_avail_kw") or b.p_charge_max_kw,
                "pdis": st.get("p_discharge_avail_kw") or b.p_discharge_max_kw,
                "cyc": st.get("cycles_used_today") or 0.0, "aux": b.aux_load_kw,
                "resv": round(float(np.max(plan["c"])) if len(plan["c"]) else 0.0, 3)})
            sched = []
            for i, h in enumerate(hours):
                p, c = float(plan["p_net"][i]), float(plan["c"][i])
                m, mk = _mode(p, c)
                sched.append({"r": run_id, "ts": h.to_pydatetime(), "p": round(p, 2),
                              "soc": round(float(plan["soc"][i]), 2), "mode": m, "market": mk,
                              "fc": _num(round(float(plan["fc"][i]), 2))})
            conn.execute(text("""
                INSERT INTO battery_master.dispatch_schedule (run_id, interval_start, p_setpoint_kw, soc_target_pct,
                    mode, market, forecast_price_mwh)
                VALUES (:r, :ts, :p, :soc, :mode, :market, :fc)"""), sched)
            conn.execute(text("""
                INSERT INTO battery_ml.arb_study_day (study_id, kpi_date, run_id, solver_status, solve_seconds,
                    expected_profit_usd, gross_usd, degradation_usd, grid_usd, net_usd, oracle_net_usd, pack_net_usd,
                    discharge_mwh, charge_mwh, cycles, soc_start_pct, soc_end_pct, checks)
                VALUES (:study, :d, :r, :status, :secs, :exp, :gross, :degr, :grid, :net, :onet, :pack, :dis, :chg,
                    :cyc, :s0, :s1, CAST(:checks AS jsonb))"""), {
                "study": study_id, "d": r["day"], "r": run_id, "status": r["status"],
                "secs": round(float(r["solve_seconds"]), 3), "exp": _num(r["expected"]), "gross": r["gross"],
                "degr": r["degr"], "grid": r["grid"], "net": r["net"],
                "onet": r["oracle_net"] + r["oracle_as"], "pack": _num(pack_daily.get(r["day"])),
                "dis": r["discharge_mwh"], "chg": r["charge_mwh"], "cyc": r["cycles"], "s0": round(r["soc_start"], 2),
                "s1": round(r["soc_end"], 2), "checks": _json({**r["checks"], "as_usd": r["as_usd"],
                                                                "oracle_energy_net_usd": r["oracle_net"],
                                                                "oracle_as_usd": r["oracle_as"],
                                                                "terminal_target": r.get("terminal_target")})})
            rows = []
            for kind, sim in (("policy", r["policy"]), ("oracle", r["oracle"])):
                for i, q in enumerate(di.quarters):
                    rows.append({
                        "study": study_id, "kind": kind, "ts": q.to_pydatetime(),
                        "r": run_id if kind == "policy" else None, "p": round(float(sim["p"][i]), 2),
                        "c": round(float(sim["c"][i]), 3), "soc": round(float(sim["soc"][i]), 2),
                        "rt": float(di.rt[i]), "fc": _num(sim["fc"][i]), "e": float(sim["e"][i]),
                        "gross": float(sim["gross"][i]), "degr": float(sim["degr"][i]), "grid": float(sim["grid"][i]),
                        "as": float(sim["as_usd"][i]), "net": float(sim["net"][i])})
            conn.execute(text("""
                INSERT INTO battery_ml.arb_backtest (study_id, kind, interval_start, run_id, p_kw, c_as_mw, soc_pct,
                    rt_price_mwh, fc_price_mwh, energy_mwh, gross_usd, degradation_usd, grid_usd, as_usd, net_usd)
                VALUES (:study, :kind, :ts, :r, :p, :c, :soc, :rt, :fc, :e, :gross, :degr, :grid, :as, :net)"""), rows)
        conn.execute(text("""
            UPDATE battery_ml.arb_study SET status = 'COMPLETED', metrics = CAST(:m AS jsonb),
                checks = CAST(:c AS jsonb), warnings = CAST(:w AS jsonb), finished_at = now(), duration_ms = :ms
            WHERE study_id = :id"""), {
            "id": study_id, "m": _json(result["metrics"]),
            "c": _json({"checks": result["checks"], "details": result["check_details"]}),
            "w": _json(result["warnings"]), "ms": result["metrics"]["duration_ms"]})


def list_studies(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {STUDY_COLUMNS} FROM battery_ml.arb_study ORDER BY study_id DESC LIMIT :l"), {"l": limit})]


def get_study(engine: Engine, study_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {STUDY_COLUMNS} FROM battery_ml.arb_study WHERE study_id = :id"),
                           {"id": study_id}).first()
        if not row:
            return None
        out = _row(row)
        out["days"] = [_row(r) for r in conn.execute(text("""
            SELECT kpi_date, run_id, solver_status, solve_seconds, expected_profit_usd, gross_usd, degradation_usd,
                   grid_usd, net_usd, oracle_net_usd, pack_net_usd, discharge_mwh, charge_mwh, cycles, soc_start_pct,
                   soc_end_pct, checks
            FROM battery_ml.arb_study_day WHERE study_id = :id ORDER BY kpi_date"""), {"id": study_id})]
    return out


def delete_study(engine: Engine, study_id: int) -> bool:
    with engine.begin() as conn:
        return conn.execute(text("DELETE FROM battery_ml.arb_study WHERE study_id = :id"),
                            {"id": study_id}).rowcount > 0
