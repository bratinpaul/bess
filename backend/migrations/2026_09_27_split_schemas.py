"""Move the Battery database out of `public` into three schemas.

    python 2026_09_27_split_schemas.py            # rehearsal: run everything, verify, ROLLBACK
    python 2026_09_27_split_schemas.py --commit   # run for real

battery_master     master / reference tables and their enum types
battery_telemetry  hypertables (telemetry + events), their continuous aggregates and the views on them
battery_raw        created empty, for raw landing data

ALTER ... SET SCHEMA keeps OIDs, so data, indexes, constraints, identity sequences, foreign keys,
views, TimescaleDB chunks, compression and refresh/retention jobs all carry over unchanged.
Extensions (timescaledb, pgcrypto) stay in public: time_bucket() etc. are resolved from there.

The database default search_path is set to battery_master, battery_telemetry, battery_raw, public
so unqualified names keep working in psql/pgAdmin; the backend and ML service also set it per connection.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
SEARCH_PATH = "battery_master, battery_telemetry, battery_raw, public"

TELEMETRY_TABLES = [
    "system_telemetry", "pcs_telemetry", "ems_telemetry", "hvac_telemetry", "module_telemetry",
    "alarm_event", "dispatch_event",
]
CONTINUOUS_AGGREGATES = [
    "system_telemetry_daily", "pcs_telemetry_daily", "ems_telemetry_daily",
    "hvac_telemetry_daily", "module_telemetry_daily",
]
TELEMETRY_VIEWS = ["v_ems_latest", "v_hvac_latest", "v_module_latest", "v_soh_daily_features", "v_soh_features_5min"]

MASTER_TABLES = [
    # hierarchy + assets
    "tenant", "tenant_contact", "tenant_site", "site", "asset_hierarchy", "battery_system", "bess_system",
    "battery_container", "battery_pack", "battery_module", "pcs", "transformer", "ems_controller", "hvac_unit",
    # lookups
    "alarm_severity", "battery_chemistry", "contactor_state", "ems_dispatch_mode", "ems_grid_service",
    "hvac_cooling_mode", "operating_mode", "pcs_alarm_type", "pcs_breaker_state", "pcs_command_type",
    "pcs_grid_service", "pcs_mode", "pcs_ride_through_type",
]
MASTER_TYPES = ["tenant_status", "tenant_type"]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()

    def q(sql, *args):
        cur.execute(sql, args)
        return cur.fetchall()

    def count_rows():
        return {
            t: q(f"SELECT count(*) FROM {t}")[0][0] for t in TELEMETRY_TABLES + MASTER_TABLES
        }

    cur.execute("SET search_path = public")
    before = count_rows()
    jobs_before = q("SELECT count(*) FROM timescaledb_information.jobs WHERE job_id >= 1000")[0][0]

    # everything in public must be accounted for, so nothing is silently left behind
    in_public = {
        r[0] for r in q(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')"
        )
    }
    planned = set(TELEMETRY_TABLES + CONTINUOUS_AGGREGATES + TELEMETRY_VIEWS + MASTER_TABLES)
    assert in_public == planned, f"unplanned: {sorted(in_public - planned)}, missing: {sorted(planned - in_public)}"

    for schema in ("battery_master", "battery_telemetry", "battery_raw"):
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    for t in MASTER_TYPES:
        cur.execute(f"ALTER TYPE public.{t} SET SCHEMA battery_master")
    for t in MASTER_TABLES:
        cur.execute(f"ALTER TABLE public.{t} SET SCHEMA battery_master")
    for t in TELEMETRY_TABLES:
        cur.execute(f"ALTER TABLE public.{t} SET SCHEMA battery_telemetry")
    for v in CONTINUOUS_AGGREGATES:
        cur.execute(f"ALTER MATERIALIZED VIEW public.{v} SET SCHEMA battery_telemetry")
    for v in TELEMETRY_VIEWS:
        cur.execute(f"ALTER VIEW public.{v} SET SCHEMA battery_telemetry")

    cur.execute('ALTER DATABASE "Battery" SET search_path = ' + SEARCH_PATH)
    cur.execute("SET search_path = " + SEARCH_PATH)

    # ---- verify
    left = q(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')"
    )
    assert not left, f"still in public: {left}"
    assert count_rows() == before, "row counts changed"
    hypers = {r[0] for r in q("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema = 'battery_telemetry'")}
    assert hypers == set(TELEMETRY_TABLES), hypers
    caggs = {r[0] for r in q("SELECT view_name FROM timescaledb_information.continuous_aggregates WHERE view_schema = 'battery_telemetry'")}
    assert caggs == set(CONTINUOUS_AGGREGATES), caggs
    jobs = q("SELECT hypertable_schema, count(*) FROM timescaledb_information.jobs WHERE job_id >= 1000 GROUP BY 1")
    assert sum(n for _, n in jobs) == jobs_before, jobs
    for v in CONTINUOUS_AGGREGATES + TELEMETRY_VIEWS:
        q(f"SELECT * FROM {v} LIMIT 1")  # views still resolve
    types = q("SELECT n.nspname, t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE t.typname = ANY(%s)", MASTER_TYPES)
    assert {s for s, _ in types} == {"battery_master"}, types

    print("master tables  :", len(MASTER_TABLES), "+ types", MASTER_TYPES)
    print("telemetry      :", len(TELEMETRY_TABLES), "hypertables,", len(caggs), "continuous aggregates,", len(TELEMETRY_VIEWS), "views")
    print("jobs by schema :", jobs)
    print("rows unchanged :", sum(before.values()))

    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
