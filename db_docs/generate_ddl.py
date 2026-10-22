"""Generate DDL scripts for the BESS schemas into "BESS DESIGN/Database/DDL".

pg_dump writes TimescaleDB objects incompletely: hypertables come out as plain tables (no create_hypertable),
continuous aggregates come out as views over internal _timescaledb tables, and policies are missing. So:

  1. pg_dump --schema-only of the schemas, minus the continuous aggregates and the views built on them
  2. a TimescaleDB section: create_hypertable / add_dimension, compression settings
  3. the continuous aggregates (CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)), then the dependent views
  4. policies: compression, retention, continuous-aggregate refresh

Outputs
  00_create_all.sql      everything, in a runnable order (run this one)
  battery_<schema>.sql   one schema each, for reading / review (cross-schema FKs need the other schemas first)

Usage:  python db_docs/generate_ddl.py [--verify]
        --verify runs 00_create_all.sql into a scratch database (battery_ddl_verify), compares object counts
        with the source, and drops it again.
"""
import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import psycopg2

from bess_common.db_settings import psycopg2_dsn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "BESS DESIGN" / "Database" / "DDL"
PG_BIN = Path(os.getenv("PG_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
SCHEMAS = ["battery_master", "battery_users", "battery_raw", "battery_telemetry", "battery_ml", "battery_itops"]
VERIFY_DB = "battery_ddl_verify"


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def lit(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def pg_interval(v) -> str:
    """A timedelta (psycopg2 returns intervals as timedelta) as Postgres interval text, e.g. '1 day', '12 hours'."""
    if not hasattr(v, "total_seconds"):
        return str(v)
    secs = int(v.total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs and secs % size == 0:
            n = secs // size
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return f"{secs} seconds"


# ---------------------------------------------------------------- catalog reads


def caggs(cur) -> list[dict]:
    cur.execute("""SELECT view_schema, view_name, materialized_only, view_definition,
                          materialization_hypertable_schema, materialization_hypertable_name, compression_enabled
                   FROM timescaledb_information.continuous_aggregates
                   WHERE view_schema = ANY(%s) ORDER BY view_schema, view_name""", (SCHEMAS,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def dependent_views(cur, roots: list[tuple[str, str]]) -> list[tuple[str, str, int]]:
    """Views (in our schemas) that depend on the continuous aggregates, transitively; (schema, view, depth)."""
    if not roots:
        return []
    cur.execute("""
        WITH RECURSIVE dep(oid, depth) AS (
            SELECT c.oid, 0 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE (n.nspname, c.relname) IN (SELECT * FROM unnest(%s::text[], %s::text[]))
          UNION
            SELECT r.ev_class, dep.depth + 1
            FROM dep JOIN pg_depend d ON d.refobjid = dep.oid AND d.classid = 'pg_rewrite'::regclass
                     JOIN pg_rewrite r ON r.oid = d.objid
            WHERE r.ev_class <> dep.oid
        )
        SELECT n.nspname, c.relname, max(dep.depth)
        FROM dep JOIN pg_class c ON c.oid = dep.oid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE dep.depth > 0 AND n.nspname = ANY(%s) AND c.relkind = 'v'
        GROUP BY 1, 2 ORDER BY 3, 1, 2""",
                ([s for s, _ in roots], [v for _, v in roots], SCHEMAS))
    found = cur.fetchall()
    cagg_set = set(roots)
    return [r for r in found if (r[0], r[1]) not in cagg_set]


def hypertable_ddl(cur, schema_filter: list[str]) -> list[str]:
    out = []
    cur.execute("""SELECT d.hypertable_schema, d.hypertable_name, d.dimension_number, d.column_name, d.dimension_type,
                          d.time_interval, d.integer_interval, d.num_partitions
                   FROM timescaledb_information.dimensions d
                   JOIN timescaledb_information.hypertables h
                     ON h.hypertable_schema = d.hypertable_schema AND h.hypertable_name = d.hypertable_name
                   WHERE d.hypertable_schema = ANY(%s)
                   ORDER BY 1, 2, 3""", (schema_filter,))
    for schema, table, num, col, kind, t_int, i_int, parts in cur.fetchall():
        rel = lit(f"{q(schema)}.{q(table)}")
        if num == 1:
            interval = f"INTERVAL {lit(pg_interval(t_int))}" if t_int is not None else str(i_int)
            out.append(f"SELECT create_hypertable({rel}, by_range({lit(col)}, {interval}), if_not_exists => TRUE);")
        elif kind == "Space" or parts:
            out.append(f"SELECT add_dimension({rel}, by_hash({lit(col)}, {parts}), if_not_exists => TRUE);")
        else:
            interval = f"INTERVAL {lit(pg_interval(t_int))}" if t_int is not None else str(i_int)
            out.append(f"SELECT add_dimension({rel}, by_range({lit(col)}, {interval}), if_not_exists => TRUE);")
    return out


def compression_ddl(cur, rel_map: dict[tuple[str, str], tuple[str, str]], schema_filter: list[str]) -> list[str]:
    """ALTER ... SET (timescaledb.compress ...) for hypertables and continuous aggregates (rel_map maps a cagg's
    materialization hypertable to the cagg)."""
    cur.execute("""SELECT hypertable_schema, hypertable_name, attname, segmentby_column_index, orderby_column_index,
                          orderby_asc, orderby_nullsfirst
                   FROM timescaledb_information.compression_settings ORDER BY 1, 2""")
    per: dict[tuple[str, str], dict] = {}
    for schema, table, att, seg, ordr, asc, nullsfirst in cur.fetchall():
        target = rel_map.get((schema, table), (schema, table))
        if target[0] not in schema_filter:
            continue
        e = per.setdefault(target, {"seg": [], "ord": [], "cagg": (schema, table) in rel_map})
        if seg is not None:
            e["seg"].append((seg, q(att)))
        if ordr is not None:
            e["ord"].append((ordr, f"{q(att)} {'ASC' if asc else 'DESC'}{' NULLS FIRST' if nullsfirst and not asc else ''}"))
    out = []
    for (schema, table), e in per.items():
        opts = ["timescaledb.compress"]
        if e["seg"]:
            opts.append(f"timescaledb.compress_segmentby = {lit(', '.join(a for _, a in sorted(e['seg'])))}")
        if e["ord"]:
            opts.append(f"timescaledb.compress_orderby = {lit(', '.join(a for _, a in sorted(e['ord'])))}")
        kind = "MATERIALIZED VIEW" if e["cagg"] else "TABLE"
        out.append(f"ALTER {kind} {q(schema)}.{q(table)} SET ({', '.join(opts)});")
    return out


def policy_ddl(cur, rel_map, schema_filter: list[str]) -> list[str]:
    cur.execute("""SELECT proc_name, hypertable_schema, hypertable_name, schedule_interval, config
                   FROM timescaledb_information.jobs
                   WHERE proc_name IN ('policy_compression', 'policy_retention', 'policy_refresh_continuous_aggregate')
                   ORDER BY proc_name, hypertable_schema, hypertable_name""")
    out = []
    for proc, schema, table, every, cfg in cur.fetchall():
        schema, table = rel_map.get((schema, table), (schema, table))
        if schema not in schema_filter:
            continue
        rel = lit(f"{q(schema)}.{q(table)}")
        sched = f", schedule_interval => INTERVAL {lit(pg_interval(every))}" if every else ""
        if proc == "policy_compression":
            after = cfg.get("compress_after")
            out.append(f"SELECT add_compression_policy({rel}, compress_after => INTERVAL {lit(after)}"
                       f"{sched}, if_not_exists => TRUE);")
        elif proc == "policy_retention":
            out.append(f"SELECT add_retention_policy({rel}, drop_after => INTERVAL {lit(cfg.get('drop_after'))}"
                       f"{sched}, if_not_exists => TRUE);")
        else:
            def iv(v):
                return "NULL" if v is None else f"INTERVAL {lit(v)}"
            out.append(f"SELECT add_continuous_aggregate_policy({rel}, start_offset => {iv(cfg.get('start_offset'))}, "
                       f"end_offset => {iv(cfg.get('end_offset'))}{sched}, if_not_exists => TRUE);")
    return out


# ---------------------------------------------------------------- assembly


def pg_dump(dsn: dict, schemas: list[str], exclude: list[str]) -> str:
    args = [str(PG_BIN / "pg_dump.exe" if os.name == "nt" else PG_BIN / "pg_dump"), "-h", dsn["host"],
            "-p", str(dsn["port"]), "-U", dsn["user"], "-d", dsn["dbname"], "--schema-only", "--no-owner",
            "--no-privileges"]
    for s in schemas:
        args += ["-n", s]
    for x in exclude:
        args += ["-T", x]
    r = subprocess.run(args, env={**os.environ, "PGPASSWORD": dsn["password"]}, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout


def build(cur, dsn: dict, schemas: list[str], all_caggs, deps) -> str:
    my_caggs = [c for c in all_caggs if c["view_schema"] in schemas]
    my_deps = [d for d in deps if d[0] in schemas]
    exclude = [f"{c['view_schema']}.{c['view_name']}" for c in all_caggs] + [f"{s}.{v}" for s, v, _ in deps]
    rel_map = {(c["materialization_hypertable_schema"], c["materialization_hypertable_name"]):
               (c["view_schema"], c["view_name"]) for c in all_caggs}
    parts = [
        f"-- BESS database DDL: {', '.join(schemas)}",
        f"-- Generated {date.today().isoformat()} by db_docs/generate_ddl.py from database {dsn['dbname']}",
        "-- Sections: extensions, pg_dump schema DDL, TimescaleDB hypertables + compression, continuous aggregates,",
        "--           views on continuous aggregates, TimescaleDB policies",
        "",
        "CREATE EXTENSION IF NOT EXISTS timescaledb;",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
        "",
        "-- ============================================================ schema DDL (pg_dump)",
        pg_dump(dsn, schemas, exclude),
        "",
        "-- ============================================================ TimescaleDB hypertables",
        "SET search_path = public;",
        *hypertable_ddl(cur, schemas),
    ]
    if my_caggs:
        parts += ["", "-- ============================================================ continuous aggregates"]
        for c in my_caggs:
            opts = "timescaledb.continuous" + (", timescaledb.materialized_only = true" if c["materialized_only"]
                                               else ", timescaledb.materialized_only = false")
            body = c["view_definition"].strip().rstrip(";")
            # the stored definition names tables relative to the cagg's own schema
            parts += [f"SET search_path = {q(c['view_schema'])}, public;",
                      f"CREATE MATERIALIZED VIEW {q(c['view_schema'])}.{q(c['view_name'])}",
                      f"WITH ({opts}) AS", body, "WITH NO DATA;", ""]
        parts += ["SET search_path = public;", ""]
    if my_deps:
        parts += ["-- ============================================================ views on continuous aggregates"]
        for schema, view, _ in my_deps:
            cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (f"{q(schema)}.{q(view)}",))
            parts += [f"CREATE OR REPLACE VIEW {q(schema)}.{q(view)} AS", cur.fetchone()[0].strip().rstrip(";") + ";", ""]
    comp = compression_ddl(cur, rel_map, schemas)
    pol = policy_ddl(cur, rel_map, schemas)
    if comp or pol:
        parts += ["-- ============================================================ compression settings and policies",
                  *comp, *pol]
    if len(schemas) > 1:
        cur.execute("""SELECT unnest(setconfig) FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase
                       WHERE d.datname = current_database() AND s.setrole = 0""")
        settings = [r[0] for r in cur.fetchall()]
        if settings:
            parts += ["", "-- ============================================================ database settings",
                      "-- the APIs rely on the default search_path; applied to whichever database runs this script",
                      "DO $$", "BEGIN"]
            for kv in settings:
                k, v = kv.split("=", 1)
                parts.append(f"    EXECUTE format('ALTER DATABASE %I SET {k} = {v.replace(chr(39), chr(39) * 2)}', "
                             "current_database());")
            parts += ["END $$;"]
    return "\n".join(parts) + "\n"


def counts(cur) -> dict:
    cur.execute("""SELECT n.nspname, c.relkind, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m','S','i') GROUP BY 1, 2""", (SCHEMAS,))
    out = {f"{s}.{k}": n for s, k, n in cur.fetchall()}
    cur.execute("""SELECT n.nspname, count(*) FROM pg_constraint k JOIN pg_namespace n ON n.oid = k.connamespace
                   WHERE n.nspname = ANY(%s) GROUP BY 1""", (SCHEMAS,))
    out.update({f"{s}.constraints": n for s, n in cur.fetchall()})
    cur.execute("SELECT hypertable_schema, count(*) FROM timescaledb_information.hypertables "
                "WHERE hypertable_schema = ANY(%s) GROUP BY 1", (SCHEMAS,))
    out.update({f"{s}.hypertables": n for s, n in cur.fetchall()})
    cur.execute("SELECT view_schema, count(*) FROM timescaledb_information.continuous_aggregates "
                "WHERE view_schema = ANY(%s) GROUP BY 1", (SCHEMAS,))
    out.update({f"{s}.caggs": n for s, n in cur.fetchall()})
    cur.execute("SELECT count(*) FROM timescaledb_information.jobs WHERE proc_name IN "
                "('policy_compression','policy_retention','policy_refresh_continuous_aggregate')")
    out["policies"] = cur.fetchone()[0]
    return out


def verify(dsn: dict, script: Path, source: dict) -> bool:
    admin = psycopg2.connect(**{**dsn, "dbname": "postgres"})
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {VERIFY_DB}")
        cur.execute(f"CREATE DATABASE {VERIFY_DB}")
    try:
        r = subprocess.run([str(PG_BIN / ("psql.exe" if os.name == "nt" else "psql")), "-h", dsn["host"],
                            "-p", str(dsn["port"]), "-U", dsn["user"], "-d", VERIFY_DB, "-v", "ON_ERROR_STOP=1",
                            "-q", "-f", str(script)],
                           env={**os.environ, "PGPASSWORD": dsn["password"], "PGCLIENTENCODING": "UTF8"},
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            print("verify: script failed\n" + r.stderr[-3000:])
            return False
        with psycopg2.connect(**{**dsn, "dbname": VERIFY_DB}) as c, c.cursor() as cur:
            target = counts(cur)
        diff = {k: (source.get(k), target.get(k)) for k in sorted(set(source) | set(target))
                if source.get(k) != target.get(k)}
        # indexes / sequences on TimescaleDB internals can differ slightly; report everything, fail on structure
        if diff:
            print("verify: differences (source, rebuilt):")
            for k, v in diff.items():
                print(f"  {k}: {v}")
        else:
            print("verify: rebuilt database matches the source object counts")
        return not any(not k.endswith(".i") for k in diff)
    finally:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {VERIFY_DB} WITH (FORCE)")
        admin.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    dsn = psycopg2_dsn()
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg2.connect(**dsn) as conn, conn.cursor() as cur:
        # the database's default search_path includes the battery schemas; with only pg_catalog visible,
        # view definitions come back fully schema-qualified
        cur.execute("SET search_path = pg_catalog")
        all_caggs = caggs(cur)
        deps = dependent_views(cur, [(c["view_schema"], c["view_name"]) for c in all_caggs])
        (OUT / "00_create_all.sql").write_text(build(cur, dsn, SCHEMAS, all_caggs, deps), encoding="utf-8")
        for s in SCHEMAS:
            (OUT / f"{s}.sql").write_text(build(cur, dsn, [s], all_caggs, deps), encoding="utf-8")
        source = counts(cur)
    for f in sorted(OUT.glob("*.sql")):
        print(f"{f.name}: {sum(1 for _ in f.open(encoding='utf-8'))} lines")
    if args.verify:
        return 0 if verify(dsn, OUT / "00_create_all.sql", source) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
