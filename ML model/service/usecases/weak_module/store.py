"""Weak module runs in battery_ml.anomaly_run / anomaly_module_result / anomaly_point and their model files."""
import json
from pathlib import Path
from typing import Optional

import joblib
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from usecases.weak_module.detector import DetectionResult

ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "anomaly"

RUN_COLUMNS = """run_id, use_case, run_kind, parent_run_id, run_name, status, battery_system_id, system_name, date_from,
    date_to, grain, feature_groups, features, params, n_rows, n_modules, n_packs, if_anomalies, db_noise, db_clusters,
    eps_used, silhouette, n_weak, n_suspect, warnings, error_message, started_at, finished_at, duration_ms"""


def _row(r) -> dict:
    out = dict(r._mapping)
    for k, v in out.items():
        if hasattr(v, "is_finite"):
            out[k] = float(v)
    return out


def start_run(engine: Engine, values: dict) -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO battery_ml.anomaly_run (run_kind, parent_run_id, run_name, status, battery_system_id, system_name,
                date_from, date_to, grain, feature_groups, features, params)
            VALUES (:run_kind, :parent_run_id, :run_name, 'RUNNING', :battery_system_id, :system_name, :date_from,
                :date_to, :grain, :feature_groups, :features, CAST(:params AS jsonb))
            RETURNING run_id"""), {**values, "params": json.dumps(values["params"])}).scalar_one()


def fail_run(engine: Engine, run_id: int, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""UPDATE battery_ml.anomaly_run SET status = 'FAILED', error_message = :m, finished_at = now(),
                             duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int WHERE run_id = :id"""),
                     {"id": run_id, "m": message})


def save_artifact(run_id: int, artifact: dict) -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"run_{run_id}.joblib"
    joblib.dump(artifact, path)
    return str(path)


def load_artifact(run: dict) -> dict:
    path = run.get("artifact_path")
    if not path or not Path(path).exists():
        raise FileNotFoundError(f"The model file of run #{run['run_id']} is missing")
    return joblib.load(path)


def complete_run(engine: Engine, run_id: int, result: DetectionResult, params: dict, artifact: Optional[str]) -> None:
    s = result.stats
    ts = lambda v: None if v is None or pd.isna(v) else pd.Timestamp(v).to_pydatetime()  # noqa: E731
    features = [c for c in result.points.columns if c not in ("module_id", "bucket", "if_score", "if_flag", "db_label")]
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE battery_ml.anomaly_run SET status = 'COMPLETED', params = CAST(:params AS jsonb), n_rows = :rows,
                n_modules = :modules, n_packs = :packs, if_anomalies = :if_anomalies, db_noise = :db_noise,
                db_clusters = :db_clusters, eps_used = :eps_used, silhouette = :silhouette, n_weak = :n_weak,
                n_suspect = :n_suspect, feature_stats = CAST(:feature_stats AS jsonb), warnings = CAST(:warnings AS jsonb),
                artifact_path = :artifact, finished_at = now(),
                duration_ms = (EXTRACT(EPOCH FROM now() - started_at) * 1000)::int
            WHERE run_id = :id"""), {
            "id": run_id, "params": json.dumps(params), **{k: s[k] for k in ("rows", "modules", "packs", "if_anomalies",
                                                                              "db_noise", "db_clusters", "eps_used",
                                                                              "silhouette", "n_weak", "n_suspect")},
            "feature_stats": json.dumps({**s["feature_stats"], "_agreement": s["agreement"],
                                         "_if_threshold": s["if_threshold"], "_min_samples_used": s["min_samples_used"]}),
            "warnings": json.dumps(result.warnings), "artifact": artifact,
        })
        m = result.modules
        conn.execute(text("""
            INSERT INTO battery_ml.anomaly_module_result (run_id, module_id, serial_number, pack_id, pack_number, position,
                verdict, combined_score, rank, n_points, if_score_mean, if_anomaly_share, db_noise_share, if_flag, db_flag,
                feature_means, reasons, first_anomaly)
            VALUES (:run_id, :module_id, :serial_number, :pack_id, :pack_number, :position, :verdict, :combined_score,
                :rank, :n_points, :if_score_mean, :if_anomaly_share, :db_noise_share, :if_flag, :db_flag,
                CAST(:feature_means AS jsonb), CAST(:reasons AS jsonb), :first_anomaly)"""), [
            {"run_id": run_id, "module_id": int(r.module_id), "serial_number": r.serial_number,
             "pack_id": int(r.pack_id) if pd.notna(r.pack_id) else None, "pack_number": r.pack_number,
             "position": int(r.position) if pd.notna(r.position) else None, "verdict": r.verdict,
             "combined_score": float(r.combined_score), "rank": int(r.rank), "n_points": int(r.n_points),
             "if_score_mean": float(r.if_score_mean), "if_anomaly_share": float(r.if_anomaly_share),
             "db_noise_share": float(r.db_noise_share), "if_flag": bool(r.if_flag), "db_flag": bool(r.db_flag),
             "feature_means": json.dumps(r.feature_means), "reasons": json.dumps(r.reasons),
             "first_anomaly": ts(r.first_anomaly)} for r in m.itertuples()])
        p = result.points
        conn.execute(text("""
            INSERT INTO battery_ml.anomaly_point (run_id, module_id, bucket, features, if_score, if_flag, db_label)
            VALUES (:run_id, :module_id, :bucket, CAST(:features AS jsonb), :if_score, :if_flag, :db_label)"""), [
            {"run_id": run_id, "module_id": int(r["module_id"]), "bucket": pd.Timestamp(r["bucket"]).to_pydatetime(),
             "features": json.dumps({f: round(float(r[f]), 4) for f in features}), "if_score": float(r["if_score"]),
             "if_flag": bool(r["if_flag"]), "db_label": int(r["db_label"])} for r in p.to_dict("records")])


def list_runs(engine: Engine, system_id: Optional[int] = None, limit: int = 100) -> list[dict]:
    where = "WHERE battery_system_id = :sid" if system_id else ""
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"SELECT {RUN_COLUMNS} FROM battery_ml.anomaly_run {where} ORDER BY run_id DESC LIMIT :limit"),
            {"sid": system_id, "limit": limit})]


def get_run(engine: Engine, run_id: int, with_modules: bool = True) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {RUN_COLUMNS}, feature_stats, artifact_path FROM battery_ml.anomaly_run "
                                "WHERE run_id = :id"), {"id": run_id}).first()
        if row is None:
            return None
        run = _row(row)
        if with_modules:
            run["modules"] = [_row(r) for r in conn.execute(text(
                "SELECT * FROM battery_ml.anomaly_module_result WHERE run_id = :id ORDER BY rank"), {"id": run_id})]
    return run


def points(engine: Engine, run_id: int, module_id: Optional[int] = None) -> list[dict]:
    where = "AND module_id = :mid" if module_id else ""
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(text(
            f"""SELECT module_id, bucket, features, if_score, if_flag, db_label FROM battery_ml.anomaly_point
                WHERE run_id = :id {where} ORDER BY bucket, module_id"""), {"id": run_id, "mid": module_id})]


def delete_run(engine: Engine, run_id: int) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("DELETE FROM battery_ml.anomaly_run WHERE run_id = :id RETURNING artifact_path"),
                           {"id": run_id}).first()
    if row is None:
        return False
    if row[0]:
        Path(row[0]).unlink(missing_ok=True)
    return True
