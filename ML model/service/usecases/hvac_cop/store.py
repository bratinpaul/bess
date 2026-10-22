"""COP runs in battery_ml.hvac_cop_run / hvac_cop_point (+ v_hvac_cop_daily)."""
import csv
import io
import json
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

RUN_COLUMNS = """run_id, run_name, status, hvac_ids, date_from, date_to, params, warnings, error_message, started_at,
    finished_at, duration_ms"""
POINT_COLUMNS = ["run_id", "hvac_id", "ts", "mode", "steady", "is_train", "cop_actual", "cop_logged", "cop_ratio", "cop_loop",
                 "cop_map", "cop_grey", "cop_hybrid", "cop_expected", "cop_residual", "eta_2nd_law", "cop_carnot", "lift_k",
                 "plr", "cap_actual_kw", "cap_expected_kw", "q_dt_kw", "power_kw", "power_expected_kw", "rej_closure_kw",
                 "t_amb_c", "t_supply_c"]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _clean(v):
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return _num(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (date, pd.Timestamp)):
        return v.isoformat()
    return v


def _json(v) -> str:
    return json.dumps(_clean(v), default=str)


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.hvac_cop_run (run_name, status, hvac_ids, date_from, date_to, params)
            VALUES (:name, 'RUNNING', :ids, :date_from, :date_to, CAST(:params AS jsonb)) RETURNING run_id"""),
            {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.hvac_cop_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message[:2000]})


def _copy(engine: Engine, frame: pd.DataFrame) -> None:
    buf = io.StringIO()
    frame[POINT_COLUMNS].to_csv(buf, index=False, header=False, na_rep="", quoting=csv.QUOTE_MINIMAL)
    buf.seek(0)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(f"COPY battery_ml.hvac_cop_point ({', '.join(POINT_COLUMNS)}) FROM STDIN WITH (FORMAT csv)", buf)
        raw.commit()
    finally:
        raw.close()


def complete_run(engine: Engine, run_id: int, result: dict) -> None:
    for r in result["results"]:
        df = r.points
        pts = pd.DataFrame({
            "run_id": run_id, "hvac_id": r.hvac_id, "ts": df["ts"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M:%S+00"),
            "mode": df["cooling_mode"], "steady": df["steady"], "is_train": df["is_train"], "cop_actual": df["cop_actual"],
            "cop_logged": df["cop_logged"], "cop_ratio": df["cop_ratio"], "cop_loop": df["cop_loop"], "cop_map": df["cop_map"],
            "cop_grey": df["cop_grey"], "cop_hybrid": df["cop_hybrid"], "cop_expected": df["cop_expected"],
            "cop_residual": df["cop_residual"], "eta_2nd_law": df["eta_2nd_law"], "cop_carnot": df["cop_carnot"],
            "lift_k": df["lift_k"], "plr": df["plr"], "cap_actual_kw": df["cap_actual_kw"], "cap_expected_kw": df["cap_expected_kw"],
            "q_dt_kw": df["q_loop_kw"], "power_kw": df["hvac_power_kw"], "power_expected_kw": df["power_expected_kw"],
            "rej_closure_kw": df["rej_closure_kw"], "t_amb_c": df["ambient_temp_c"], "t_supply_c": df["coolant_supply_temp_c"]})
        num = POINT_COLUMNS[6:]
        pts[num] = pts[num].astype(float).replace([np.inf, -np.inf], np.nan).round(4)
        # COP blows up when the input power is ~0 (idle): keep the ratios inside the column's range
        for c in ("cop_actual", "cop_logged", "cop_ratio", "cop_loop", "cop_map", "cop_grey", "cop_hybrid", "cop_expected", "cop_residual"):
            pts[c] = pts[c].where(pts[c].abs() < 9999)
        _copy(engine, pts)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.hvac_cop_run SET status = 'COMPLETED', models = CAST(:models AS jsonb),
                summary = CAST(:summary AS jsonb), warnings = CAST(:w AS jsonb), finished_at = now(), duration_ms = :ms
            WHERE run_id = :id"""), {
            "id": run_id, "models": _json({str(r.hvac_id): r.models for r in result["results"]}),
            "summary": _json({"units": {str(r.hvac_id): r.summary for r in result["results"]}, "fleet": result["fleet"]}),
            "w": _json(result["warnings"]), "ms": result["duration_ms"]})


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(f"""
            SELECT {RUN_COLUMNS}, summary -> 'fleet' AS fleet FROM battery_ml.hvac_cop_run ORDER BY run_id DESC LIMIT :l"""),
            {"l": limit})]


def get_run(engine: Engine, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}, models, summary FROM battery_ml.hvac_cop_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def points(engine: Engine, run_id: int, hvac_id: int, day_from: date, day_to: date, limit: int = 6000) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT * FROM battery_ml.hvac_cop_point WHERE run_id = :r AND hvac_id = :h
              AND ts >= CAST(:a AS date) AND ts < CAST(:b AS date) + 1 ORDER BY ts LIMIT :l"""),
            {"r": run_id, "h": hvac_id, "a": day_from, "b": day_to, "l": limit})]


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM battery_ml.hvac_cop_point WHERE run_id = :id"), {"id": run_id})
        return conn.execute(text("DELETE FROM battery_ml.hvac_cop_run WHERE run_id = :id"), {"id": run_id}).rowcount > 0
