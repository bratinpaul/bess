"""Loss runs in battery_ml.loss_run / loss_daily / loss_ledger (deleting a run deletes its days and ledger)."""
import csv
import io
import json
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

RUN_COLUMNS = """run_id, run_name, status, system_ids, date_from, date_to, params, warnings, error_message, started_at,
    finished_at, duration_ms"""

LEDGER_COLUMNS = ["run_id", "system_id", "ts", "direction", "p_poi_kw", "p_ac_kw", "p_dc_kw", "p_term_kw", "p_chem_kw",
                  "load_frac", "loss_batt_kwh", "loss_dc_kwh", "loss_pcs_kwh", "loss_xfmr_kwh", "aux_hvac_kwh",
                  "aux_ctrl_kwh", "standby_kwh", "exp_batt_kwh", "exp_pcs_kwh", "exp_xfmr_kwh", "exp_aux_kwh", "eta_pcs",
                  "eta_batt", "closure_kwh", "price_mwh"]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _default(o):
    if isinstance(o, (np.floating, np.integer)):
        return _num(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (date, pd.Timestamp)):
        return o.isoformat()
    return str(o)


def _clean(v):
    """JSON-safe: NaN / inf -> None, numpy -> python."""
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return _num(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _json(v) -> str:
    return json.dumps(_clean(v), default=_default)


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.loss_run (run_name, status, system_ids, date_from, date_to, params)
            VALUES (:name, 'RUNNING', :systems, :date_from, :date_to, CAST(:params AS jsonb)) RETURNING run_id"""),
            {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.loss_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message[:2000]})


def _day_row(run_id: int, sid: int, d: dict) -> dict:
    loss, exp, rte = d["loss"], d["expected"], d.get("rte") or {}
    return {
        "run_id": run_id, "system_id": sid, "day": d["day"], "intervals": d["intervals"], "is_baseline": d["is_baseline"],
        "e_in_poi_kwh": d["e_in"]["poi"], "e_out_poi_kwh": d["e_out"]["poi"], "e_in_ac_kwh": d["e_in"]["ac"],
        "e_out_ac_kwh": d["e_out"]["ac"], "e_in_term_kwh": d["e_in"]["term"], "e_out_term_kwh": d["e_out"]["term"],
        "stored_kwh": d["stored_kwh"], "throughput_kwh": d["throughput_kwh"], "utilization_pct": d["utilization_pct"],
        "loss_batt_kwh": loss["batt"], "loss_dc_kwh": loss["dc"], "loss_pcs_kwh": loss["pcs"], "loss_xfmr_kwh": loss["xfmr"],
        "aux_hvac_kwh": d["aux_split"]["hvac"], "aux_ctrl_kwh": d["aux_split"]["controls"], "standby_kwh": loss["standby"],
        "exp_batt_kwh": exp["batt"], "exp_pcs_kwh": exp["pcs"], "exp_xfmr_kwh": exp["xfmr"], "exp_aux_kwh": exp["aux"],
        "exp_standby_kwh": exp["standby"], "fixed_kwh": d["fixed_kwh"], "variable_kwh": d["variable_kwh"],
        "rte_term": rte.get("term"), "rte_dc": rte.get("dc"), "rte_ac": rte.get("ac"), "rte_poi_excl_aux": rte.get("poi_x"),
        "rte_plant": rte.get("poi"), "rte_expected": d.get("rte_expected"), "performance_ratio": d.get("performance_ratio"),
        "guarantee_gap_pts": d.get("guarantee_gap_pts"), "closure_kwh": d["closure_kwh"],
        "closure_pcs_kwh": d["closure_pcs_kwh"], "avg_price_mwh": d["avg_price_mwh"], "loss_usd": d["loss_usd"],
        "excess_usd": d["excess_usd"],
        "extra": _json({"factors": d.get("factors"), "factors_expected": d.get("factors_expected"),
                        "shares": d.get("shares"), "excess_kwh": d["excess_kwh"],
                        "excess_usd_by_stage": d["excess_usd_by_stage"], "normalized": d["normalized"],
                        "counters": d["counters"], "battery_closure": d["battery_closure"], "control": d.get("control"),
                        "has_cycle": d["has_cycle"], "cycles": d["cycles"],
                        "aux_pct_of_throughput": d["aux_pct_of_throughput"], "total_loss_kwh": d["total_loss_kwh"],
                        "e_in": d["e_in"], "e_out": d["e_out"]}),
    }


def _copy_ledger(engine: Engine, run_id: int, sid: int, df: pd.DataFrame, step_h: float) -> None:
    h = step_h
    out = pd.DataFrame({
        "run_id": run_id, "system_id": sid, "ts": df["ts"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M:%S+00"),
        "direction": df["direction"], "p_poi_kw": df["p_poi_kw"], "p_ac_kw": df["p_ac_kw"], "p_dc_kw": df["p_dc_kw"],
        "p_term_kw": df["p_term_kw"], "p_chem_kw": df["p_chem_kw"], "load_frac": df["load_frac"],
        "loss_batt_kwh": df["loss_batt_kw"] * h, "loss_dc_kwh": df["loss_dc_kw"] * h, "loss_pcs_kwh": df["loss_pcs_kw"] * h,
        "loss_xfmr_kwh": df["loss_xfmr_kw"] * h, "aux_hvac_kwh": df["aux_hvac_kw"] * h, "aux_ctrl_kwh": df["aux_ctrl_kw"] * h,
        "standby_kwh": df["standby_kw"] * h, "exp_batt_kwh": df["exp_batt_kw"] * h, "exp_pcs_kwh": df["exp_pcs_kw"] * h,
        "exp_xfmr_kwh": df["exp_xfmr_kw"] * h, "exp_aux_kwh": df["exp_aux_kw"] * h, "eta_pcs": df["eta_pcs"],
        "eta_batt": df["eta_batt"], "closure_kwh": df["closure_kw"] * h, "price_mwh": df["price_mwh"],
    })[LEDGER_COLUMNS]
    num = [c for c in LEDGER_COLUMNS if c not in ("run_id", "system_id", "ts", "direction")]
    out[num] = out[num].astype(float).round(5)
    buf = io.StringIO()
    out.to_csv(buf, index=False, header=False, na_rep="", quoting=csv.QUOTE_MINIMAL)
    buf.seek(0)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(f"COPY battery_ml.loss_ledger ({', '.join(LEDGER_COLUMNS)}) FROM STDIN WITH (FORMAT csv)", buf)
        raw.commit()
    finally:
        raw.close()


def complete_run(engine: Engine, run_id: int, result: dict, step_h_by_system: dict[int, float]) -> None:
    for r in result["results"]:
        _copy_ledger(engine, run_id, r.system_id, r.ledger, step_h_by_system[r.system_id])
    with engine.begin() as conn:
        rows = [_day_row(run_id, r.system_id, d) for r in result["results"] for d in r.days]
        cols = list(rows[0].keys()) if rows else []
        if rows:
            conn.execute(text(f"""INSERT INTO battery_ml.loss_daily ({', '.join(cols)})
                                  VALUES ({', '.join(':' + c if c != 'extra' else 'CAST(:extra AS jsonb)' for c in cols)})"""),
                         [{k: (_num(v) if isinstance(v, (float, np.floating)) else v) for k, v in row.items()} for row in rows])
        summary = {str(r.system_id): r.summary for r in result["results"]}
        models = {str(r.system_id): r.models for r in result["results"]}
        conn.execute(text("""
            UPDATE battery_ml.loss_run SET status = 'COMPLETED', models = CAST(:models AS jsonb),
                summary = CAST(:summary AS jsonb), warnings = CAST(:w AS jsonb), finished_at = now(), duration_ms = :ms
            WHERE run_id = :id"""), {"id": run_id, "models": _json(models),
                                     "summary": _json({"systems": summary, "fleet": result["fleet"]}),
                                     "w": _json(result["warnings"]), "ms": result["duration_ms"]})


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        rows = [_row(r) for r in conn.execute(text(f"""
            SELECT {RUN_COLUMNS}, summary -> 'fleet' AS fleet FROM battery_ml.loss_run ORDER BY run_id DESC LIMIT :l"""),
            {"l": limit})]
    return rows


def get_run(engine: Engine, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}, models, summary FROM battery_ml.loss_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def days(engine: Engine, run_id: int, system_id: int) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT * FROM battery_ml.loss_daily WHERE run_id = :r AND system_id = :s ORDER BY day"""),
            {"r": run_id, "s": system_id})]


def ledger(engine: Engine, run_id: int, system_id: int, day_from: date, day_to: date, limit: int = 3000) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT * FROM battery_ml.loss_ledger WHERE run_id = :r AND system_id = :s
              AND ts >= CAST(:a AS date) AND ts < CAST(:b AS date) + 1 ORDER BY ts LIMIT :l"""),
            {"r": run_id, "s": system_id, "a": day_from, "b": day_to, "l": limit})]


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM battery_ml.loss_ledger WHERE run_id = :id"), {"id": run_id})
        return conn.execute(text("DELETE FROM battery_ml.loss_run WHERE run_id = :id"), {"id": run_id}).rowcount > 0
