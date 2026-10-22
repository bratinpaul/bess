"""Heat-load runs in battery_ml.heatload_run / heatload_ledger / heatload_forecast_point (+ the v_heatload_daily view)."""
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

LEDGER_COLUMNS = ["run_id", "system_id", "ts", "direction", "is_train", "q_batt_irr_kw", "q_batt_rev_kw", "q_pcs_kw",
                  "q_aux_kw", "q_solar_kw", "q_env_kw", "q_storage_kw", "q_total_kw", "q_model_kw", "measured_kw",
                  "heat_load_sensor_kw", "cooling_kw", "hvac_kw", "residual_kw", "t_amb_c", "t_enc_c", "t_cell_max_c",
                  "dt_cell_c", "ghi_wm2", "ghi_source"]
POINT_COLUMNS = ["run_id", "system_id", "issued_at", "horizon_min", "valid_at", "actual_kw", "persistence_kw", "physics_kw",
                 "p10_kw", "p50_kw", "p90_kw", "plan_kw"]


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
            INSERT INTO battery_ml.heatload_run (run_name, status, system_ids, date_from, date_to, params)
            VALUES (:name, 'RUNNING', :systems, :date_from, :date_to, CAST(:params AS jsonb)) RETURNING run_id"""),
            {**values, "params": _json(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.heatload_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message[:2000]})


def _copy(engine: Engine, table: str, columns: list[str], frame: pd.DataFrame) -> None:
    buf = io.StringIO()
    frame[columns].to_csv(buf, index=False, header=False, na_rep="", quoting=csv.QUOTE_MINIMAL)
    buf.seek(0)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv)", buf)
        raw.commit()
    finally:
        raw.close()


def _utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M:%S+00")


def complete_run(engine: Engine, run_id: int, result: dict) -> None:
    for r in result["results"]:
        df = r.ledger
        led = pd.DataFrame({c: df[c] for c in LEDGER_COLUMNS if c in df.columns})
        led["run_id"], led["system_id"], led["ts"] = run_id, r.system_id, _utc(df["ts"])
        num = [c for c in LEDGER_COLUMNS if c not in ("run_id", "system_id", "ts", "direction", "is_train", "ghi_source")]
        led[num] = led[num].astype(float).round(4)
        _copy(engine, "battery_ml.heatload_ledger", LEDGER_COLUMNS, led)
        p = r.points
        if len(p):
            pts = pd.DataFrame({"run_id": run_id, "system_id": r.system_id, "issued_at": _utc(p["issued_at"]),
                                "horizon_min": p["h_min"].astype(int), "valid_at": _utc(p["valid_at"]),
                                "actual_kw": p["actual"], "persistence_kw": p["persistence"], "physics_kw": p["physics"],
                                "p10_kw": p["p10"], "p50_kw": p["p50"], "p90_kw": p["p90"], "plan_kw": p["plan_kw"]})
            for c in POINT_COLUMNS[5:]:
                pts[c] = pts[c].astype(float).round(4)
            _copy(engine, "battery_ml.heatload_forecast_point", POINT_COLUMNS, pts)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.heatload_run SET status = 'COMPLETED', models = CAST(:models AS jsonb),
                summary = CAST(:summary AS jsonb), warnings = CAST(:w AS jsonb), finished_at = now(), duration_ms = :ms
            WHERE run_id = :id"""), {
            "id": run_id, "models": _json({str(r.system_id): r.models for r in result["results"]}),
            "summary": _json({"systems": {str(r.system_id): r.summary for r in result["results"]}, "fleet": result["fleet"]}),
            "w": _json(result["warnings"]), "ms": result["duration_ms"]})


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(f"""
            SELECT {RUN_COLUMNS}, summary -> 'fleet' AS fleet FROM battery_ml.heatload_run ORDER BY run_id DESC LIMIT :l"""),
            {"l": limit})]


def get_run(engine: Engine, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}, models, summary FROM battery_ml.heatload_run WHERE run_id = :id"),
                           {"id": run_id}).first()
    return _row(row) if row else None


def ledger(engine: Engine, run_id: int, system_id: int, day_from: date, day_to: date, limit: int = 4000) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT * FROM battery_ml.heatload_ledger WHERE run_id = :r AND system_id = :s
              AND ts >= CAST(:a AS date) AND ts < CAST(:b AS date) + 1 ORDER BY ts LIMIT :l"""),
            {"r": run_id, "s": system_id, "a": day_from, "b": day_to, "l": limit})]


def daily(engine: Engine, run_id: int, system_id: int) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT * FROM battery_ml.v_heatload_daily WHERE run_id = :r AND system_id = :s ORDER BY day"""),
            {"r": run_id, "s": system_id})]


def issues(engine: Engine, run_id: int, system_id: int) -> list[str]:
    with engine.connect() as conn:
        return [r[0].isoformat() for r in conn.execute(text("""
            SELECT DISTINCT issued_at FROM battery_ml.heatload_forecast_point WHERE run_id = :r AND system_id = :s
            ORDER BY 1"""), {"r": run_id, "s": system_id})]


def trajectory(engine: Engine, run_id: int, system_id: int, issued_at: str) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT * FROM battery_ml.heatload_forecast_point WHERE run_id = :r AND system_id = :s
              AND issued_at = CAST(:i AS timestamptz) ORDER BY horizon_min"""),
            {"r": run_id, "s": system_id, "i": issued_at})]


def horizon_series(engine: Engine, run_id: int, system_id: int, horizon: int, day_from: date, day_to: date) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT valid_at, issued_at, actual_kw, persistence_kw, physics_kw, p10_kw, p50_kw, p90_kw, plan_kw
            FROM battery_ml.heatload_forecast_point WHERE run_id = :r AND system_id = :s AND horizon_min = :h
              AND valid_at >= CAST(:a AS date) AND valid_at < CAST(:b AS date) + 1 ORDER BY valid_at"""),
            {"r": run_id, "s": system_id, "h": horizon, "a": day_from, "b": day_to})]


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM battery_ml.heatload_ledger WHERE run_id = :id"), {"id": run_id})
        conn.execute(text("DELETE FROM battery_ml.heatload_forecast_point WHERE run_id = :id"), {"id": run_id})
        return conn.execute(text("DELETE FROM battery_ml.heatload_run WHERE run_id = :id"), {"id": run_id}).rowcount > 0
