"""KPI API of a domain (BMS, PCS): the definitions from its kpi_config YAML, the calculation, and the stored daily
values. make_router(domain, ...) builds the same endpoints for each domain; the entity id parameter is named after
the domain's entity (system_id for BMS, pcs_id for PCS). Responses carry entity_id / entity_name (and entity_ids /
entity_names on runs) so one frontend component serves every domain."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, create_model
from sqlalchemy import text
from sqlalchemy.orm import Session

from bess_common.errors import BusinessRuleViolation
from app.database import get_db
from app.services.bms_kpi.calculator import describe, load_system_params, run
from app.services.bms_kpi.config import ConfigError, load_config, range_summary
from app.services.bms_kpi.domain import KpiDomain


def make_router(domain: KpiDomain, prefix: str, entity_label: str) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[f"{domain.key}-kpi"])
    ent = domain.entity_col
    not_found = f"{entity_label} not found"

    # POST /calculate body: {<entity_col>: id | null, start_date, end_date, dry_run}
    CalculateRequest = create_model(  # noqa: N806
        f"{domain.label}KpiCalculateRequest",
        __base__=BaseModel,
        **{ent: (Optional[int], None)},  # None = every entity with telemetry
        start_date=(Optional[date], None),
        end_date=(Optional[date], None),
        dry_run=(bool, False),
    )

    def _config():
        try:
            return load_config(domain)
        except ConfigError as exc:  # the YAML's own validation messages (written for whoever edits the file)
            raise BusinessRuleViolation(f"KPI configuration error: {exc}", code="KPI_CONFIG_INVALID") from exc

    def _entity_name(db: Session, entity_id: int) -> str:
        name = db.execute(text(f"SELECT {domain.master_name} {domain.master_from} WHERE {domain.master_id} = :id"),
                          {"id": entity_id}).scalar()
        if name is None:
            raise HTTPException(status_code=404, detail=not_found)
        return name

    @router.get("/config")
    def get_config():
        cfg = _config()
        return {
            "domain": domain.key,
            "entity_param": ent,
            "file_path": cfg.file_path,
            "version": cfg.version,
            "config_hash": cfg.file_hash,
            "timezone": cfg.timezone,
            "interval": cfg.interval.model_dump(),
            "expected_samples_per_day": cfg.expected_samples_per_day,
            "groups": [g.model_dump() for g in cfg.groups],
            "params": cfg.global_params,
            "system_params": {name: p.model_dump() for name, p in cfg.system_params.items()},
            "system_overrides": {str(sid): o for sid, o in cfg.system_overrides.items()},
            "queries": {name: q.model_dump() for name, q in cfg.queries.items()},
            "kpis": [
                {**k.model_dump(exclude={"filter"}), "filter": [f.model_dump() for f in k.filter],
                 "formula_text": describe(k)}
                for k in cfg.kpis
            ],
            "charts": [c.model_dump() for c in cfg.charts],
            "tiles": cfg.tiles,
        }

    @router.get("/entities")
    def entities(db: Session = Depends(get_db)):
        """The entities KPIs are computed for (battery systems / PCS units), with their telemetry span."""
        rows = db.execute(text(f"""
            SELECT {domain.master_id} AS id, {domain.master_name} AS name,
                   (SELECT count(*) FROM {domain.telemetry_table} t WHERE t.{ent} = {domain.master_id}) AS samples
            {domain.master_from}
            ORDER BY {domain.master_name}""")).mappings().all()
        return [dict(r) for r in rows]

    @router.get("/system-params")
    def system_params(entity_id: int = Query(..., alias=ent), db: Session = Depends(get_db)):
        """The entity params (master data + overrides) the KPIs of one entity are computed with."""
        cfg = _config()
        return load_system_params(db, cfg, domain).get(entity_id, {})

    @router.get("/date-range")
    def date_range(entity_id: int = Query(..., alias=ent), db: Session = Depends(get_db)):
        """Telemetry days available for an entity (plant-local) and the days that already have stored KPIs."""
        cfg = _config()
        row = db.execute(text(f"""
            SELECT (SELECT CAST(min(ts) AT TIME ZONE :tz AS date) FROM {domain.telemetry_table} WHERE {ent} = :id),
                   (SELECT CAST(max(ts) AT TIME ZONE :tz AS date) FROM {domain.telemetry_table} WHERE {ent} = :id),
                   (SELECT min(kpi_date) FROM {domain.kpi_table} WHERE {ent} = :id),
                   (SELECT max(kpi_date) FROM {domain.kpi_table} WHERE {ent} = :id),
                   (SELECT count(DISTINCT kpi_date) FROM {domain.kpi_table} WHERE {ent} = :id)"""),
            {"tz": cfg.timezone, "id": entity_id}).one()
        return {"telemetry_start": row[0], "telemetry_end": row[1],
                "kpi_start": row[2], "kpi_end": row[3], "kpi_days": row[4]}

    @router.get("")
    def list_kpis(
        entity_id: int = Query(..., alias=ent),
        start: Optional[date] = None,
        end: Optional[date] = None,
        db: Session = Depends(get_db),
    ):
        """Stored daily KPIs of one entity, one entry per day with the values keyed by KPI code."""
        name = _entity_name(db, entity_id)
        if start and end and start > end:
            raise HTTPException(status_code=400, detail="start must be on or before end")
        cfg = _config()

        rows = db.execute(text(f"""
            SELECT kpi_date, kpi_code, kpi_name, unit, value, sample_count, config_version, config_hash, calculated_at
            FROM {domain.kpi_table}
            WHERE {ent} = :id
              AND (CAST(:start AS date) IS NULL OR kpi_date >= :start)
              AND (CAST(:end AS date) IS NULL OR kpi_date <= :end)
            ORDER BY kpi_date, kpi_code"""), {"id": entity_id, "start": start, "end": end}).mappings().all()

        order = {k.code: i for i, k in enumerate(cfg.kpis)}
        kpis: dict[str, dict] = {}
        days: dict[date, dict] = {}
        for r in rows:
            kpis.setdefault(r["kpi_code"], {"code": r["kpi_code"], "name": r["kpi_name"], "unit": r["unit"],
                                            "in_config": r["kpi_code"] in order})
            day = days.setdefault(r["kpi_date"], {
                "kpi_date": r["kpi_date"],
                "sample_count": r["sample_count"],
                "coverage_pct": round(100.0 * r["sample_count"] / cfg.expected_samples_per_day, 1),
                "calculated_at": r["calculated_at"],
                "stale": False,
                "values": {},
            })
            day["values"][r["kpi_code"]] = None if r["value"] is None else float(r["value"])
            day["stale"] = day["stale"] or r["config_hash"] != cfg.file_hash
            day["calculated_at"] = max(day["calculated_at"], r["calculated_at"])

        daily = {code: [d["values"].get(code) for d in days.values()] for code in kpis}
        return {
            ent: entity_id,
            "entity_id": entity_id,
            "entity_name": name,
            "config_hash": cfg.file_hash,
            "kpis": sorted(kpis.values(), key=lambda k: order.get(k["code"], len(order))),
            "days": list(days.values()),
            "summary": range_summary(cfg, daily, load_system_params(db, cfg, domain).get(entity_id, {})),
        }

    @router.post("/calculate")
    def calculate(payload: CalculateRequest, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        entity_id = getattr(payload, ent)
        if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
            raise HTTPException(status_code=400, detail="start_date must be on or before end_date")
        if entity_id is not None and not db.get(domain.entity_model, entity_id):
            raise HTTPException(status_code=404, detail=not_found)
        cfg = _config()
        # a failure is answered by the shared handlers (bess_common/errors.py): generic 500 + reference, trace logged
        return run(db, cfg, triggered_by="api", system_ids=[entity_id] if entity_id is not None else None,
                   start_date=payload.start_date, end_date=payload.end_date, dry_run=payload.dry_run, domain=domain)

    @router.get("/runs")
    def list_runs(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
        ids = domain.run_ids_col
        rows = db.execute(text(f"""
            SELECT r.run_id, r.status, r.triggered_by, r.{ids} AS entity_ids, r.start_date, r.end_date,
                   r.config_version, r.config_hash, r.kpi_codes, r.systems_done AS entities_done, r.days,
                   r.rows_deleted, r.rows_written, r.error_message, r.started_at, r.finished_at, r.duration_ms,
                   (SELECT array_agg({domain.master_name} ORDER BY {domain.master_name}) {domain.master_from}
                    WHERE {domain.master_id} = ANY(r.{ids})) AS entity_names
            FROM {domain.run_table} r
            ORDER BY r.run_id DESC
            LIMIT :limit"""), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    return router
