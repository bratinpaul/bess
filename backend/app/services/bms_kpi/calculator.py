"""Compute the configured KPIs of a domain (BMS per battery system, PCS per PCS unit - see domain.py) per entity per
day and store them in the domain's KPI table (battery_ml.bms_kpi / battery_ml.pcs_kpi).

    1. system params   one row per entity from master data (`system_params`, with `system_overrides`)
    2. row KPIs        integrate / aggregate / counter_delta - one SQL pass over the telemetry table: each KPI's row
                       expression + filter is computed per sample, then aggregated per (entity, plant-local day)
    3. query KPIs      each named query in `queries` runs once, read-only, and feeds every KPI that points at it
    4. derived KPIs    evaluated in Python over the KPI values and params of the system-day

A run replaces the stored rows of its scope (systems x days), so KPIs removed from the config disappear there too.
Only days with telemetry get KPI rows. Internally the entity id is carried as "system_id" in result dicts.
"""
import logging
import re
import time
from datetime import date
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from bess_common.observability import operation

from app.services.bms_kpi import expr
from app.services.bms_kpi.config import KpiConfig, KpiDefinition, derived_order, param_names
from app.services.bms_kpi.domain import BMS, KpiDomain

log = logging.getLogger(__name__)

QUERY_TIMEOUT = "120s"


def describe(kpi: KpiDefinition) -> str:
    """Human-readable formula for the UI."""
    where = " and ".join(
        f"{f.column} {f.op} {f.value if not isinstance(f.value, list) else '(' + ', '.join(map(str, f.value)) + ')'}"
        for f in kpi.filter)
    where = f" where {where}" if where else ""
    if kpi.method == "integrate":
        scale = "" if kpi.scale == 1 else f" × {kpi.scale:g}"
        return f"Σ ({kpi.column}) × Δt_h{scale}{where}"
    if kpi.method == "aggregate":
        return f"{kpi.func.upper()}({kpi.column}){where}"
    if kpi.method == "counter_delta":
        return f"MAX({kpi.column}) − MIN({kpi.column}) in the day{where}"
    if kpi.method == "query":
        return f"query {kpi.query} → {kpi.output_field}"
    return kpi.formula.replace("*", "×").replace("/", "÷")


# --- system params --------------------------------------------------------------------------------------------------

def system_params_sql(cfg: KpiConfig, binds: dict, domain: KpiDomain = BMS) -> str:
    """SELECT of one row per entity: its id (named like the telemetry entity column) + every system param
    (overrides applied)."""
    cols = [f"{domain.master_id} AS {domain.entity_col}"]
    for name, p in cfg.system_params.items():
        whens = []
        for sid, overrides in cfg.system_overrides.items():
            if name in overrides:
                key = f"ov_{name}_{sid}"
                binds[key] = overrides[name]
                whens.append(f"WHEN {int(sid)} THEN CAST(:{key} AS numeric)")
        value = f"CAST(({p.sql}) AS numeric)"
        if whens:
            value = f"CASE {domain.master_id} {' '.join(whens)} ELSE {value} END"
        cols.append(f'{value} AS "{name}"')
    return f"SELECT {', '.join(cols)} {domain.master_from}"


def load_system_params(db: Session, cfg: KpiConfig, domain: KpiDomain = BMS) -> dict[int, dict[str, Optional[float]]]:
    binds: dict = {}
    ent = domain.entity_col
    rows = db.execute(text(system_params_sql(cfg, binds, domain)), binds).mappings().all()
    return {r[ent]: {k: (None if v is None else float(v)) for k, v in r.items() if k != ent} for r in rows}


# --- row KPIs -------------------------------------------------------------------------------------------------------

def _resolver(cfg: KpiConfig, binds: dict):
    def resolve(name: str) -> str:
        if name in cfg.system_params:
            return f'sp."{name}"'
        if name in cfg.global_params:
            binds[f"gp_{name}"] = cfg.global_params[name]
            return f"CAST(:gp_{name} AS numeric)"
        return f't."{name}"'  # a telemetry column (validated at load)
    return resolve


def _condition(kpi: KpiDefinition, resolve, binds: dict, idx: int, ent: str) -> str:
    parts = []
    for j, f in enumerate(kpi.filter):
        left = expr.to_sql(f.column, resolve, ent)
        if f.op in ("in", "not in"):
            keys = []
            for n, v in enumerate(f.value):
                keys.append(f":f_{idx}_{j}_{n}")
                binds[keys[-1][1:]] = v
            parts.append(f"{left} {f.op.upper()} ({', '.join(keys)})")
        elif isinstance(f.value, str) and f.value.startswith("$"):
            parts.append(f"{left} {f.op} {resolve(f.value[1:])}")
        else:
            binds[f"f_{idx}_{j}"] = f.value
            parts.append(f"{left} {f.op} :f_{idx}_{j}")
    return " AND ".join(parts) if parts else "TRUE"


def _aggregate_sql(kpi: KpiDefinition, binds: dict, i: int) -> str:
    e, c = f"e_{i}", f"c_{i}"
    if kpi.method == "integrate":
        binds[f"scale_{i}"] = kpi.scale
        # 0 (not NULL) when the expression has values but none pass the filter - e.g. a day with no charging
        return (f"CASE WHEN COUNT({e}) = 0 THEN NULL ELSE "
                f"COALESCE(SUM(CASE WHEN {c} THEN {e} * dt_h END), 0) * :scale_{i} END")
    if kpi.method == "counter_delta":
        return f"MAX(CASE WHEN {c} THEN {e} END) - MIN(CASE WHEN {c} THEN {e} END)"
    if kpi.func == "count":
        return f"COUNT(CASE WHEN {c} THEN {e} END)"
    if kpi.func in ("first", "last"):
        order = "ASC" if kpi.func == "first" else "DESC"
        return f"(ARRAY_AGG({e} ORDER BY ts {order}) FILTER (WHERE {c} AND {e} IS NOT NULL))[1]"
    return f"{kpi.func.upper()}(CASE WHEN {c} THEN {e} END)"


def build_row_query(cfg: KpiConfig, kpis: list[KpiDefinition], system_ids: Optional[list[int]],
                    start_date: Optional[date], end_date: Optional[date], domain: KpiDomain = BMS):
    binds: dict = {"tz": cfg.timezone, "dt_fixed": cfg.interval.minutes / 60.0,
                   "dt_cap": cfg.interval.max_gap_minutes / 60.0}
    resolve = _resolver(cfg, binds)
    ent = domain.entity_col
    if cfg.interval.mode == "fixed":
        dt = "CAST(:dt_fixed AS numeric)"
    else:
        dt = (f"CAST(LEAST(COALESCE(EXTRACT(EPOCH FROM LEAD(t.ts) OVER (PARTITION BY t.{ent} ORDER BY t.ts) - t.ts)"
              " / 3600.0, :dt_fixed), :dt_cap) AS numeric)")

    where = []
    if system_ids:
        binds["system_ids"] = system_ids
        where.append(f"t.{ent} IN :system_ids")
    if start_date:
        binds["start_date"] = start_date
        where.append("t.ts >= (CAST(:start_date AS timestamp) AT TIME ZONE :tz)")
    if end_date:
        binds["end_date"] = end_date
        where.append("t.ts < ((CAST(:end_date AS timestamp) + interval '1 day') AT TIME ZONE :tz)")

    row_cols = "".join(
        f",\n           {expr.to_sql(k.column, resolve, ent)} AS e_{i}, ({_condition(k, resolve, binds, i, ent)}) AS c_{i}"
        for i, k in enumerate(kpis))
    aggs = "".join(f",\n       {_aggregate_sql(k, binds, i)} AS k_{i}" for i, k in enumerate(kpis))
    sql = f"""
WITH sp AS ({system_params_sql(cfg, binds, domain)}),
r AS (
    SELECT t.{ent} AS system_id, t.ts, CAST(t.ts AT TIME ZONE :tz AS date) AS kpi_date, {dt} AS dt_h{row_cols}
    FROM {domain.telemetry_table} t
    LEFT JOIN sp ON sp.{ent} = t.{ent}
    WHERE {' AND '.join(where) or 'TRUE'}
)
SELECT system_id, kpi_date, COUNT(*) AS sample_count{aggs}
FROM r
GROUP BY system_id, kpi_date
ORDER BY system_id, kpi_date"""
    stmt = text(sql)
    if system_ids:
        stmt = stmt.bindparams(bindparam("system_ids", expanding=True))
    return stmt, binds


# --- query KPIs -----------------------------------------------------------------------------------------------------

def _with_sp(cfg: KpiConfig, sql: str, binds: dict, domain: KpiDomain) -> str:
    """Make the system params available to a named query as CTE `sp` (keyed by the entity column)."""
    sp = f"sp AS ({system_params_sql(cfg, binds, domain)})"
    m = re.match(r"\s*with\s+(recursive\s+)?", sql, flags=re.IGNORECASE)
    if m:
        return f"WITH {m.group(1) or ''}{sp},\n{sql[m.end():]}"
    return f"WITH {sp}\n{sql}"


def run_queries(db: Session, cfg: KpiConfig, kpis: list[KpiDefinition], system_ids: list[int],
                start_date: date, end_date: date, domain: KpiDomain = BMS) -> dict[tuple, dict[str, Optional[float]]]:
    """{(entity id, kpi_date): {kpi_code: value}} from the named queries, run in a read-only transaction.
    Queries bind the entity ids as :<domain.entity_ids_bind> and return the entity column (system_id / pcs_id)."""
    needed: dict[str, list[KpiDefinition]] = {}
    for k in kpis:
        needed.setdefault(k.query, []).append(k)
    out: dict[tuple, dict[str, Optional[float]]] = {}
    if not needed:
        return out

    with db.get_bind().connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT}'"))
        bounds = conn.execute(text("""
            SELECT CAST(:sd AS timestamp) AT TIME ZONE :tz, (CAST(:ed AS timestamp) + interval '1 day') AT TIME ZONE :tz"""),
            {"sd": start_date, "ed": end_date, "tz": cfg.timezone}).one()
        for name, users in needed.items():
            binds = {**cfg.global_params, domain.entity_ids_bind: system_ids, "start_date": start_date,
                     "end_date": end_date, "start_ts": bounds[0], "end_ts": bounds[1], "tz": cfg.timezone}
            sql = _with_sp(cfg, cfg.queries[name].sql, binds, domain)
            try:
                rows = conn.execute(text(sql), binds).mappings().all()
            except Exception as exc:
                raise RuntimeError(f"query '{name}' failed: {str(exc).splitlines()[0]}") from exc
            for r in rows:
                if domain.entity_col not in r:
                    raise RuntimeError(f"query '{name}' returns no column '{domain.entity_col}'")
                cell = out.setdefault((r[domain.entity_col], r["kpi_date"]), {})
                for k in users:
                    if k.output_field not in r:
                        raise RuntimeError(f"query '{name}' returns no column '{k.output_field}' (KPI '{k.code}')")
                    v = r[k.output_field]
                    cell[k.code] = None if v is None else float(v)
        conn.rollback()
    return out


# --- compute / run --------------------------------------------------------------------------------------------------

def compute(db: Session, cfg: KpiConfig, system_ids: Optional[list[int]] = None,
            start_date: Optional[date] = None, end_date: Optional[date] = None,
            domain: KpiDomain = BMS) -> list[dict]:
    """KPI rows (not stored): one dict per entity / day / KPI (entity id under "system_id")."""
    enabled = cfg.enabled_kpis
    row_kpis = [k for k in enabled if k.method in ("integrate", "aggregate", "counter_delta")]
    query_kpis = [k for k in enabled if k.method == "query"]
    derived = derived_order(enabled, param_names(cfg))
    sys_params = load_system_params(db, cfg, domain)

    stmt, binds = build_row_query(cfg, row_kpis, system_ids, start_date, end_date, domain)
    base = db.execute(stmt, binds).mappings().all()
    if not base:
        return []

    days = [r["kpi_date"] for r in base]
    queried = run_queries(db, cfg, query_kpis, sorted({r["system_id"] for r in base}),
                          start_date or min(days), end_date or max(days), domain)

    out = []
    for row in base:
        sid, day = row["system_id"], row["kpi_date"]
        values: dict[str, Optional[float]] = {
            k.code: (None if row[f"k_{i}"] is None else float(row[f"k_{i}"])) for i, k in enumerate(row_kpis)
        }
        q = queried.get((sid, day), {})
        for k in query_kpis:
            values[k.code] = q[k.code] if k.code in q else k.default
        scope = {**cfg.global_params, **sys_params.get(sid, {})}
        for k in derived:
            values[k.code] = expr.evaluate(k.formula, {**scope, **values})
        for k in enabled:
            v = values[k.code]
            out.append({
                "system_id": sid,
                "kpi_date": day,
                "kpi_code": k.code,
                "kpi_name": k.name,
                "unit": k.unit,
                "value": None if v is None else round(v, k.decimals),
                "sample_count": row["sample_count"],
            })
    return out


def run(db: Session, cfg: KpiConfig, *, triggered_by: str, system_ids: Optional[list[int]] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None, dry_run: bool = False,
        domain: KpiDomain = BMS) -> dict:
    """Compute, replace the stored rows of the scope, and log the run in the domain's run table.

    dry_run computes and counts everything inside the transaction, then rolls back (nothing stored, no run row).
    """
    started = time.perf_counter()
    codes = [k.code for k in cfg.enabled_kpis]
    ent = domain.entity_col
    run_id = db.execute(text(f"""
        INSERT INTO {domain.run_table} (status, triggered_by, {domain.run_ids_col}, start_date, end_date,
                                        config_file, config_version, config_hash, kpi_codes)
        VALUES ('running', :by, :ids, :sd, :ed, :file, :ver, :hash, :codes) RETURNING run_id"""),
        {"by": triggered_by, "ids": system_ids, "sd": start_date, "ed": end_date, "file": cfg.file_path,
         "ver": cfg.version, "hash": cfg.file_hash, "codes": codes}).scalar_one()
    if not dry_run:
        db.commit()  # the run row survives a failed calculation

    with operation("kpi", f"{domain.key}_kpi", logger=log, run_id=None if dry_run else run_id, triggered_by=triggered_by,
                   entities=len(system_ids) if system_ids else "all", start_date=start_date, end_date=end_date,
                   dry_run=dry_run, config_version=cfg.version) as op:
        result = _run_body(db, cfg, run_id, codes, ent, started, system_ids, start_date, end_date, dry_run, domain)
        op.set(rows_total=result["rows_written"], rows_inserted=result["rows_written"], rows_updated=result["rows_deleted"],
               systems_done=result["systems_done"], days=result["days"])
    return result


def _run_body(db: Session, cfg: KpiConfig, run_id: int, codes: list[str], ent: str, started: float,
              system_ids: Optional[list[int]], start_date: Optional[date], end_date: Optional[date], dry_run: bool,
              domain: KpiDomain) -> dict:
    """Compute, replace and record one KPI run (the body of run(), timed and logged there)."""
    try:
        rows = compute(db, cfg, system_ids, start_date, end_date, domain)
        scope = sorted({(r["system_id"], r["kpi_date"]) for r in rows})
        deleted = 0
        if scope:
            # replace every stored KPI of the (system, day) pairs this run computed
            deleted = db.execute(text(f"""
                DELETE FROM {domain.kpi_table} k
                USING unnest(CAST(:sids AS bigint[]), CAST(:days AS date[])) AS s(entity_id, kpi_date)
                WHERE k.{ent} = s.entity_id AND k.kpi_date = s.kpi_date"""),
                {"sids": [s for s, _ in scope], "days": [d for _, d in scope]}).rowcount
            # one statement over arrays - executemany would be a round trip per value
            db.execute(text(f"""
                INSERT INTO {domain.kpi_table} ({ent}, kpi_date, kpi_code, kpi_name, unit, value, sample_count,
                                                config_version, config_hash, run_id)
                SELECT u.system_id, u.kpi_date, u.kpi_code, u.kpi_name, u.unit, u.value, u.sample_count,
                       :ver, :hash, :run_id
                FROM unnest(CAST(:sids AS bigint[]), CAST(:days AS date[]), CAST(:codes AS text[]),
                            CAST(:names AS text[]), CAST(:units AS text[]), CAST(:vals AS numeric[]),
                            CAST(:counts AS integer[]))
                     AS u(system_id, kpi_date, kpi_code, kpi_name, unit, value, sample_count)"""),
                {"sids": [r["system_id"] for r in rows], "days": [r["kpi_date"] for r in rows],
                 "codes": [r["kpi_code"] for r in rows], "names": [r["kpi_name"] for r in rows],
                 "units": [r["unit"] for r in rows], "vals": [r["value"] for r in rows],
                 "counts": [r["sample_count"] for r in rows],
                 "ver": cfg.version, "hash": cfg.file_hash, "run_id": run_id})

        result = {
            "run_id": None if dry_run else run_id,
            "status": "success",
            "dry_run": dry_run,
            "systems_done": len({s for s, _ in scope}),
            "days": len(scope),
            "rows_deleted": deleted,
            "rows_written": len(rows),
            "kpi_codes": codes,
            "config_version": cfg.version,
            "config_hash": cfg.file_hash,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        if dry_run:
            db.rollback()
            return result
        db.execute(text(f"""
            UPDATE {domain.run_table}
            SET status = 'success', systems_done = :systems_done, days = :days, rows_deleted = :rows_deleted,
                rows_written = :rows_written, finished_at = now(), duration_ms = :duration_ms
            WHERE run_id = :run_id"""), result)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        if not dry_run:
            db.execute(text(f"""
                UPDATE {domain.run_table}
                SET status = 'failed', error_message = :err, finished_at = now(), duration_ms = :ms
                WHERE run_id = :run_id"""),
                {"err": str(exc)[:2000], "ms": int((time.perf_counter() - started) * 1000), "run_id": run_id})
            db.commit()
        raise
