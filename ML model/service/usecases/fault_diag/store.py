"""Fault-diagnosis runs in battery_ml.fault_diag_run / _example / _scan_point / _candidate, the model files (one joblib per
run), and the writes into battery_master.fault_prediction (published OOF results, scan candidates, confirmations)."""
import json
from datetime import date
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import ArtifactMissing

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "fault_diag"

RUN_COLUMNS = """run_id, run_name, status, is_default, date_from, date_to, params, summary, warnings, artifact_path,
    published_at, error_message, started_at, finished_at, duration_ms"""
_cache: dict = {}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _clean(v):
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return _num(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (pd.Timestamp, date)):
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


# -------------------------------------------------------------------------------------------------------- runs
def start_run(engine: Engine, name: Optional[str], d0, d1, params: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.fault_diag_run (run_name, status, date_from, date_to, params)
            VALUES (:n, 'RUNNING', :a, :b, CAST(:p AS jsonb)) RETURNING run_id"""),
            {"n": name, "a": d0, "b": d1, "p": _json(params)}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.fault_diag_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message[:2000]})


def complete_run(engine: Engine, run_id: int, result: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(result["artifact"], path)
    rows = []
    for e in result["examples"]:
        rows.append((run_id, e["key"], e["group"], e["kind"], e["episode_id"], e["system_id"],
                     e["start"].to_pydatetime(), e["end"].to_pydatetime(), e["label"], e["predicted"],
                     round(e["probability"], 4), bool(e["correct"]), e["fold"],
                     _json({"top3": e["top3"], "top3_ml": e["top3_ml"], "top3_engine": e["top3_engine"],
                            "contributions": e["contributions"], "evidence": e["evidence"]})))
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(cur, """INSERT INTO battery_ml.fault_diag_example (run_id, example_key, group_key, kind, episode_id,
                system_id, window_start, window_end, label, predicted, probability, correct, fold, detail) VALUES %s""",
                           rows, template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)", page_size=500)
        raw.commit()
    finally:
        raw.close()
    with engine.begin() as conn:
        first = conn.execute(text("SELECT NOT EXISTS (SELECT 1 FROM battery_ml.fault_diag_run WHERE is_default)")).scalar()
        conn.execute(text("""
            UPDATE battery_ml.fault_diag_run SET status = 'COMPLETED', summary = CAST(:s AS jsonb), metrics = CAST(:m AS jsonb),
                warnings = CAST(:w AS jsonb), artifact_path = :p, is_default = :d, finished_at = now(), duration_ms = :ms
            WHERE run_id = :id"""), {"id": run_id, "s": _json(result["summary"]), "m": _json(result["metrics"]),
                                     "w": _json(result["warnings"]), "p": str(path), "d": bool(first),
                                     "ms": result["duration_ms"]})


def list_runs(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(f"""
            SELECT {RUN_COLUMNS},
                   metrics -> 'oof' -> 'fused' -> 'macro_f1' AS macro_f1,
                   metrics -> 'oof' -> 'fused' -> 'top3_accuracy' AS top3_accuracy,
                   metrics -> 'oof' -> 'fused' -> 'accuracy' AS accuracy
            FROM battery_ml.fault_diag_run ORDER BY run_id DESC LIMIT :l"""), {"l": limit})]


def get_run(engine: Engine, run_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        r = conn.execute(text(f"SELECT {RUN_COLUMNS}, metrics FROM battery_ml.fault_diag_run WHERE run_id = :id"),
                         {"id": run_id}).first()
    return _row(r) if r else None


def default_run(engine: Engine) -> Optional[int]:
    with engine.connect() as conn:
        return conn.execute(text("""SELECT run_id FROM battery_ml.fault_diag_run WHERE status = 'COMPLETED'
                                    ORDER BY is_default DESC, run_id DESC LIMIT 1""")).scalar()


def set_default(engine: Engine, run_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE battery_ml.fault_diag_run SET is_default = (run_id = :id) WHERE status = 'COMPLETED'"),
                     {"id": run_id})


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM battery_master.fault_prediction WHERE model_version IN (:a, :b)"),
                     {"a": model_version(run_id), "b": model_version(run_id, scan=True)})
        ok = conn.execute(text("DELETE FROM battery_ml.fault_diag_run WHERE run_id = :id"), {"id": run_id}).rowcount > 0
    p = ARTIFACTS / f"run_{run_id}.joblib"
    if p.exists():
        p.unlink()
    _cache.pop(str(p), None)
    return ok


def artifact(run: dict) -> dict:
    path = run.get("artifact_path")
    if not path or not Path(path).exists():
        raise ArtifactMissing(f"The model file of run #{run['run_id']} is missing. Retrain the model.")
    if path not in _cache:
        _cache[path] = joblib.load(path)
    return _cache[path]


def examples(engine: Engine, run_id: int, kind: Optional[str] = None) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT x.example_key, x.group_key, x.kind, x.episode_id, x.system_id, x.window_start, x.window_end, x.label,
                   x.predicted, x.probability, x.correct, x.fold, x.detail -> 'top3' AS top3,
                   e.asset_code, e.detected_ts, e.onset_ts, e.severity_level, e.root_cause_confirmed
            FROM battery_ml.fault_diag_example x
            LEFT JOIN battery_master.fault_episode e ON e.episode_id = x.episode_id
            WHERE x.run_id = :r AND (CAST(:k AS text) IS NULL OR x.kind = :k)
            ORDER BY x.window_end"""), {"r": run_id, "k": kind})
        return [_row(r) for r in rows]


def example_detail(engine: Engine, run_id: int, key: str) -> Optional[dict]:
    with engine.connect() as conn:
        r = conn.execute(text("""SELECT * FROM battery_ml.fault_diag_example WHERE run_id = :r AND example_key = :k"""),
                         {"r": run_id, "k": key}).first()
    return _row(r) if r else None


# ---------------------------------------------------------------------------------------- fault_prediction log
def model_version(run_id: int, scan: bool = False) -> str:
    return f"fault-diag-r{run_id}" + ("-scan" if scan else "")


def _top3_text(top3: list[dict]) -> str:
    return "|".join(f"{t['fault_code']}:{t['p']:.2f}" for t in top3)


def publish(engine: Engine, run_id: int) -> int:
    """Write the run's out-of-fold predictions (one per episode / healthy anchor) to fault_prediction, so
    v_fault_scoring compares this model with the logged ones. Window-level runs publish the last window of each group."""
    mv = model_version(run_id)
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (x.group_key) x.group_key, x.kind, x.episode_id, x.window_end, x.label, x.predicted,
                   x.probability, x.correct, x.detail -> 'top3' AS top3, x.detail -> 'evidence' AS evidence,
                   COALESCE(e.system_id, x.system_id) AS system_id, e.asset_type, e.asset_code, bs.system_name
            FROM battery_ml.fault_diag_example x
            LEFT JOIN battery_master.fault_episode e ON e.episode_id = x.episode_id
            LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = x.system_id
            WHERE x.run_id = :r ORDER BY x.group_key, x.window_end DESC"""), {"r": run_id}).mappings().all()
        conn.execute(text("DELETE FROM battery_master.fault_prediction WHERE model_version = :mv"), {"mv": mv})
        for r in rows:
            matched = [f"{e['signal']}" for e in (r["evidence"] or []) if e.get("match") is not None and e["match"] >= 0.5
                       and e["fault_code"] == r["predicted"]]
            conn.execute(text("""
                INSERT INTO battery_master.fault_prediction (model_version, system_id, asset_type, asset_code, predicted_at,
                    predicted_fault_code, probability, top3, episode_id, actual_fault_code, is_correct, note)
                VALUES (:mv, :sid, :at, :ac, :ts, :pred, :p, :top3, :ep, :act, :ok, :note)"""), {
                "mv": mv, "sid": int(r["system_id"]), "at": r["asset_type"] or "System",
                "ac": r["asset_code"] or r["system_name"] or r["group_key"], "ts": r["window_end"], "pred": r["predicted"],
                "p": round(float(r["probability"]), 4), "top3": _top3_text(r["top3"] or []), "ep": r["episode_id"],
                "act": r["label"], "ok": bool(r["correct"]),
                "note": ("out-of-fold; symptoms: " + ", ".join(matched)) if matched else "out-of-fold"})
        conn.execute(text("UPDATE battery_ml.fault_diag_run SET published_at = now() WHERE run_id = :r"), {"r": run_id})
    return len(rows)


def scoring(engine: Engine) -> list[dict]:
    """Model-level accuracy from v_fault_scoring (every model_version in the log)."""
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT model_version, sum(n) AS n, sum(n_correct) AS n_correct, sum(n_correct)::float / NULLIF(sum(n), 0) AS accuracy,
                   sum(n * avg_confidence) / NULLIF(sum(n), 0) AS avg_confidence
            FROM battery_master.v_fault_scoring GROUP BY model_version ORDER BY model_version"""))]


def logged_predictions(engine: Engine, mv: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text("""SELECT predicted_fault_code, actual_fault_code, probability, top3
                                   FROM battery_master.fault_prediction WHERE model_version = :mv
                                     AND actual_fault_code IS NOT NULL"""), conn, params={"mv": mv})


def model_versions(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text(
            "SELECT DISTINCT model_version FROM battery_master.fault_prediction ORDER BY 1"))]


# ------------------------------------------------------------------------------------------------------- scans
def save_scan(engine: Engine, run_id: int, system_id: int, scores: pd.DataFrame, events: list[dict],
              episodes: pd.DataFrame, system_name: str) -> dict:
    t0, t1 = scores["end"].min(), scores["end"].max()
    mv = model_version(run_id, scan=True)
    pts = [(run_id, system_id, r.end.to_pydatetime(), r.predicted, round(r.probability, 4), round(r.p_none, 4),
            _json(r.top3), list(r.alarms)) for r in scores.itertuples(index=False)]
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("DELETE FROM battery_ml.fault_diag_scan_point WHERE run_id = %s AND system_id = %s AND ts BETWEEN %s AND %s",
                        (run_id, system_id, t0.to_pydatetime(), t1.to_pydatetime()))
            execute_values(cur, """INSERT INTO battery_ml.fault_diag_scan_point (run_id, system_id, ts, predicted, probability,
                                   p_none, top3, alarms) VALUES %s""", pts,
                           template="(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)", page_size=1000)
        raw.commit()
    finally:
        raw.close()
    eps = episodes[episodes["telemetry_system_id"] == system_id]
    written = 0
    with engine.begin() as conn:
        # reviewed candidates keep their prediction row (and the operator's label)
        conn.execute(text("""DELETE FROM battery_master.fault_prediction WHERE model_version = :mv AND system_id = :s
                             AND predicted_at BETWEEN :a AND :b AND prediction_id NOT IN (
                                 SELECT prediction_id FROM battery_ml.fault_diag_candidate
                                 WHERE status <> 'NEW' AND prediction_id IS NOT NULL)"""),
                     {"mv": mv, "s": system_id, "a": t0.to_pydatetime(), "b": t1.to_pydatetime()})
        conn.execute(text("""DELETE FROM battery_ml.fault_diag_candidate WHERE run_id = :r AND system_id = :s
                             AND peak_ts BETWEEN :a AND :b AND status = 'NEW'"""),
                     {"r": run_id, "s": system_id, "a": t0.to_pydatetime(), "b": t1.to_pydatetime()})
        for ev in events:
            ep = None
            for r in eps.itertuples():
                end = r.resolved_ts if pd.notna(r.resolved_ts) else r.detected_ts + pd.Timedelta(hours=2)
                if ev["first"] <= end + pd.Timedelta(minutes=30) and ev["last"] >= r.onset_ts - pd.Timedelta(minutes=30):
                    ep = r
                    break
            actual = ep.fault_code if ep is not None else None
            symptoms = ", ".join(sorted({e["signal"] for e in ev["evidence"] if e["fault_code"] == ev["fault_code"]}))
            pid = conn.execute(text("""
                INSERT INTO battery_master.fault_prediction (model_version, system_id, asset_type, asset_code, predicted_at,
                    predicted_fault_code, probability, top3, episode_id, actual_fault_code, is_correct, note)
                VALUES (:mv, :s, NULL, :ac, :ts, :f, :p, :t3, :ep, :act, :ok, :note)
                ON CONFLICT (model_version, system_id, asset_code, predicted_at) DO UPDATE SET
                    predicted_fault_code = EXCLUDED.predicted_fault_code, probability = EXCLUDED.probability,
                    top3 = EXCLUDED.top3, episode_id = EXCLUDED.episode_id, note = EXCLUDED.note,
                    actual_fault_code = COALESCE(fault_prediction.actual_fault_code, EXCLUDED.actual_fault_code),
                    is_correct = CASE WHEN fault_prediction.actual_fault_code IS NULL THEN EXCLUDED.is_correct
                                      ELSE fault_prediction.actual_fault_code = EXCLUDED.predicted_fault_code END
                RETURNING prediction_id"""), {
                "mv": mv, "s": system_id, "ac": ev["asset_code"] or system_name, "ts": ev["peak"].to_pydatetime(),
                "f": ev["fault_code"], "p": round(ev["probability"], 4), "t3": _top3_text(ev["top3"]),
                "ep": ep.episode_id if ep is not None else None, "act": actual,
                "ok": (actual == ev["fault_code"]) if actual else None,
                "note": f"scan {ev['n_windows']} window(s)" + (f"; symptoms: {symptoms}" if symptoms else "")}).scalar_one()
            conn.execute(text("""
                INSERT INTO battery_ml.fault_diag_candidate (run_id, system_id, first_ts, peak_ts, last_ts, fault_code,
                    probability, n_windows, top3, contributions, evidence, alarms, asset_code, episode_id, actual_fault_code,
                    prediction_id)
                VALUES (:r, :s, :a, :pk, :b, :f, :p, :n, CAST(:t3 AS jsonb), CAST(:c AS jsonb), CAST(:e AS jsonb), :al, :ac,
                        :ep, :act, :pid)
                ON CONFLICT (run_id, system_id, peak_ts, fault_code) DO UPDATE SET probability = EXCLUDED.probability,
                    first_ts = EXCLUDED.first_ts, last_ts = EXCLUDED.last_ts, n_windows = EXCLUDED.n_windows,
                    top3 = EXCLUDED.top3, contributions = EXCLUDED.contributions, evidence = EXCLUDED.evidence,
                    prediction_id = EXCLUDED.prediction_id"""), {
                "r": run_id, "s": system_id, "a": ev["first"].to_pydatetime(), "pk": ev["peak"].to_pydatetime(),
                "b": ev["last"].to_pydatetime(), "f": ev["fault_code"], "p": round(ev["probability"], 4),
                "n": ev["n_windows"], "t3": _json(ev["top3"]), "c": _json(ev["contributions"]), "e": _json(ev["evidence"]),
                "al": list(ev["alarms"]), "ac": ev["asset_code"], "ep": ep.episode_id if ep is not None else None,
                "act": actual, "pid": pid})
            written += 1
    return {"windows": len(pts), "candidates": written, "from": t0.isoformat(), "to": t1.isoformat()}


def scan_points(engine: Engine, run_id: int, system_id: int, d0: date, d1: date) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT ts, predicted, probability, p_none, top3, alarms FROM battery_ml.fault_diag_scan_point
            WHERE run_id = :r AND system_id = :s AND ts >= CAST(:a AS date) AND ts < CAST(:b AS date) + 1 ORDER BY ts"""),
            {"r": run_id, "s": system_id, "a": d0, "b": d1})]


def list_candidates(engine: Engine, run_id: int, system_id: Optional[int] = None) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT c.*, fc.fault_name, fc.subsystem, fc.is_safety_critical, fc.default_severity, fc.recommended_action,
                   bs.system_name
            FROM battery_ml.fault_diag_candidate c
            JOIN battery_master.fault_catalog fc ON fc.fault_code = c.fault_code
            LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = c.system_id
            WHERE c.run_id = :r AND (CAST(:s AS bigint) IS NULL OR c.system_id = :s) ORDER BY c.peak_ts DESC"""),
            {"r": run_id, "s": system_id})]


def scanned_systems(engine: Engine, run_id: int) -> list[dict]:
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("""
            SELECT p.system_id, bs.system_name, CAST(min(p.ts) AS date) AS date_from, CAST(max(p.ts) AS date) AS date_to,
                   count(*) AS windows
            FROM battery_ml.fault_diag_scan_point p
            LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = p.system_id
            WHERE p.run_id = :r GROUP BY p.system_id, bs.system_name ORDER BY p.system_id"""), {"r": run_id})]


def review_candidate(engine: Engine, candidate_id: int, actual: Optional[str], status: str) -> Optional[dict]:
    """Operator review: the confirmed (or corrected) class goes to the candidate and its fault_prediction row - the label
    the next retrain learns from."""
    with engine.begin() as conn:
        if status == "NEW":
            # undo: back to the label of the overlapping confirmed episode (if any)
            actual = conn.execute(text("""SELECT e.fault_code FROM battery_ml.fault_diag_candidate c
                                          JOIN battery_master.fault_episode e ON e.episode_id = c.episode_id
                                          WHERE c.candidate_id = :id"""), {"id": candidate_id}).scalar()
        r = conn.execute(text("""UPDATE battery_ml.fault_diag_candidate SET status = :st, actual_fault_code = :a
                                 WHERE candidate_id = :id RETURNING prediction_id, fault_code"""),
                         {"id": candidate_id, "st": status, "a": actual}).first()
        if not r:
            return None
        if r.prediction_id:
            conn.execute(text("""UPDATE battery_master.fault_prediction SET actual_fault_code = :a,
                                 is_correct = CASE WHEN CAST(:a AS text) IS NULL THEN NULL ELSE predicted_fault_code = :a END
                                 WHERE prediction_id = :p"""), {"a": actual, "p": r.prediction_id})
    return {"candidate_id": candidate_id, "status": status, "actual_fault_code": actual}
