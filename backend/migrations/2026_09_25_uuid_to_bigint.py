"""Convert every uuid key column in the Battery database to bigint.

    python 2026_09_25_uuid_to_bigint.py            # rehearsal: run everything, verify, ROLLBACK
    python 2026_09_25_uuid_to_bigint.py --commit   # run for real

All schema and data changes run in ONE transaction, so any failure rolls everything back.
New ids start at 1 in created_at order (natural codes for tables without created_at).
Old UUID values are dropped; no mapping is kept.

system_telemetry is a compressed hypertable segmented by system_id, so it is decompressed
and compression turned off for the change, then re-enabled. The system_telemetry_daily
continuous aggregate and the two v_soh_* views depend on system_id and are recreated from
their live definitions. Chunk recompression runs after the commit (TimescaleDB requirement).
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

# table -> (key column, ORDER BY for numbering)
KEYED = {
    "site": ("site_id", "created_at, site_code"),
    "battery_system": ("battery_system_id", "created_at, system_name"),
    "battery_container": ("container_id", "container_number"),
    "battery_pack": ("pack_id", "pack_number"),
    "battery_module": ("module_id", "serial_number"),
    "transformer": ("transformer_id", "transformer_name"),
    "asset": ("asset_id", "created_at, asset_name"),
}

# (table, column, referenced table) for every column that points at a keyed table
REFERENCES = [
    ("battery_system", "site_id", "site"),
    ("transformer", "site_id", "site"),
    ("battery_container", "battery_system_id", "battery_system"),
    ("pcs", "system_id", "battery_system"),
    ("system_telemetry", "system_id", "battery_system"),
    ("dispatch_event", "battery_system_id", "battery_system"),
    ("battery_pack", "container_id", "battery_container"),
    ("battery_module", "pack_id", "battery_pack"),
    ("asset", "parent_asset_id", "asset"),
    ("alarm_event", "asset_id", "asset"),
]

TABLES = sorted({t for t in KEYED} | {t for t, _, _ in REFERENCES})
VIEWS = ["v_soh_daily_features", "v_soh_features_5min"]
CAGG = "system_telemetry_daily"


def log(msg):
    print(msg, flush=True)


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    conn.autocommit = False
    cur = conn.cursor()

    def q(sql, *args):
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else None

    counts_before = {t: q(f"SELECT count(*) FROM {t}")[0][0] for t in TABLES}

    # ---- capture everything we drop, from the live database
    view_defs = {v: q("SELECT pg_get_viewdef(%s::regclass, true)", v)[0][0].strip().rstrip(";") for v in VIEWS}
    view_comments = {v: q("SELECT obj_description(%s::regclass)", v)[0][0] for v in VIEWS}
    cagg_def = q(
        "SELECT view_definition, materialized_only FROM timescaledb_information.continuous_aggregates "
        "WHERE view_name = %s", CAGG)[0]
    cagg_policy = q(
        "SELECT config->>'start_offset', config->>'end_offset', schedule_interval "
        "FROM timescaledb_information.jobs WHERE hypertable_name = %s "
        "AND proc_name = 'policy_refresh_continuous_aggregate'", CAGG)[0]
    compress_policy = q(
        "SELECT config->>'compress_after' FROM timescaledb_information.jobs "
        "WHERE hypertable_name = 'system_telemetry' AND proc_name = 'policy_compression'")[0][0]
    uuid_cols = q(
        """SELECT c.relname, a.attname, a.attnotnull FROM pg_attribute a
           JOIN pg_class c ON c.oid = a.attrelid
           WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
             AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped""")
    not_null = {(t, col) for t, col, nn in uuid_cols if nn}
    expected = {(t, k) for t, (k, _) in KEYED.items()} | {(t, col) for t, col, _ in REFERENCES}
    found = {(t, col) for t, col, _ in uuid_cols}
    assert found == expected, f"uuid columns changed since the survey: {found ^ expected}"

    # constraints (PK / UNIQUE / FK) and plain indexes on the uuid columns, to recreate verbatim
    constraints = q(
        """SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid) FROM pg_constraint
           WHERE connamespace = 'public'::regnamespace AND contype IN ('p', 'u', 'f')
             AND (EXISTS (SELECT 1 FROM unnest(conkey) k JOIN pg_attribute a
                          ON a.attrelid = conrelid AND a.attnum = k WHERE a.atttypid = 'uuid'::regtype)
                  OR (contype = 'f' AND EXISTS (SELECT 1 FROM unnest(confkey) k JOIN pg_attribute a
                          ON a.attrelid = confrelid AND a.attnum = k WHERE a.atttypid = 'uuid'::regtype)))""")
    indexes = q(
        """SELECT i.relname, pg_get_indexdef(x.indexrelid) FROM pg_index x
           JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid
           WHERE t.relnamespace = 'public'::regnamespace
             AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conindid = x.indexrelid)
             AND EXISTS (SELECT 1 FROM unnest(x.indkey) k JOIN pg_attribute a
                         ON a.attrelid = x.indrelid AND a.attnum = k WHERE a.atttypid = 'uuid'::regtype)""")
    log(f"captured {len(constraints)} constraints, {len(indexes)} indexes, {len(VIEWS)} views, 1 aggregate")

    # ---- 1. drop the aggregate and views that depend on system_id
    for v in VIEWS:
        q(f"DROP VIEW {v}")
    q(f"DROP MATERIALIZED VIEW {CAGG}")  # also removes its refresh policy
    log("dropped views and continuous aggregate")

    # ---- 2. decompress system_telemetry and switch compression off
    n = q("SELECT count(decompress_chunk(c, true)) FROM show_chunks('system_telemetry') c")[0][0]
    q("SELECT remove_compression_policy('system_telemetry')")
    q("ALTER TABLE system_telemetry SET (timescaledb.compress = false)")
    log(f"decompressed {n} chunks, compression off")

    # ---- 3. new bigint ids, numbered from 1
    for table, (key, order) in KEYED.items():
        q(f"ALTER TABLE {table} ADD COLUMN {key}__new bigint")
        q(f"""UPDATE {table} t SET {key}__new = s.rn
              FROM (SELECT {key}, row_number() OVER (ORDER BY {order}, {key}) AS rn FROM {table}) s
              WHERE t.{key} = s.{key}""")
    for table, col, ref in REFERENCES:
        ref_key = KEYED[ref][0]
        q(f"ALTER TABLE {table} ADD COLUMN {col}__new bigint")
        q(f"UPDATE {table} t SET {col}__new = r.{ref_key}__new FROM {ref} r WHERE t.{col} = r.{ref_key}")
        orphans = q(f"SELECT count(*) FROM {table} WHERE {col} IS NOT NULL AND {col}__new IS NULL")[0][0]
        assert orphans == 0, f"{table}.{col}: {orphans} values point at no {ref} row"
    log("assigned new ids and remapped references")

    # ---- 4. swap columns: drop FKs, drop old uuid columns (takes PKs/indexes with them), rename
    for table, name, kind, _ in constraints:
        if kind == "f":
            q(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
    for table, col in sorted(expected):
        q(f"ALTER TABLE {table} DROP COLUMN {col} CASCADE")
        q(f"ALTER TABLE {table} RENAME COLUMN {col}__new TO {col}")
        if (table, col) in not_null:
            q(f"ALTER TABLE {table} ALTER COLUMN {col} SET NOT NULL")
    log("swapped uuid columns for bigint")

    # ---- 5. identity keys continuing after the highest id
    for table, (key, _) in KEYED.items():
        q(f"ALTER TABLE {table} ALTER COLUMN {key} ADD GENERATED BY DEFAULT AS IDENTITY")
        q(f"SELECT setval(pg_get_serial_sequence('{table}', '{key}'), "
          f"COALESCE((SELECT max({key}) FROM {table}), 0) + 1, false)")

    # ---- 6. recreate constraints (keys before foreign keys) and indexes, same names and definitions
    for kind in ("p", "u", "f"):
        for table, name, k, definition in constraints:
            if k == kind:
                q(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" {definition}')
    for _, definition in indexes:
        q(definition)
    log("recreated keys, foreign keys and indexes")

    # ---- 7. compression back on, same settings and policy
    q("""ALTER TABLE system_telemetry SET (timescaledb.compress,
         timescaledb.compress_segmentby = 'system_id', timescaledb.compress_orderby = 'ts DESC')""")
    q("SELECT add_compression_policy('system_telemetry', %s::interval)", compress_policy)

    # ---- 8. recreate the aggregate (empty, as it was) and the views
    view_sql, materialized_only = cagg_def
    view_sql = view_sql.strip().rstrip(";")
    q(f"""CREATE MATERIALIZED VIEW {CAGG}
          WITH (timescaledb.continuous, timescaledb.materialized_only = {str(materialized_only).lower()})
          AS {view_sql} WITH NO DATA""")
    q(f"SELECT add_continuous_aggregate_policy('{CAGG}', start_offset => %s::interval, "
      f"end_offset => %s::interval, schedule_interval => %s)", *cagg_policy)
    for v in VIEWS:
        q(f"CREATE VIEW {v} AS {view_defs[v]}")
        if view_comments[v]:
            q(f"COMMENT ON VIEW {v} IS %s", view_comments[v])
    log("recreated compression, aggregate and views")

    # ---- 9. verify inside the transaction
    left = q("""SELECT c.relname || '.' || a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
                WHERE c.relnamespace = 'public'::regnamespace AND a.atttypid = 'uuid'::regtype
                  AND a.attnum > 0 AND NOT a.attisdropped""")
    assert not left, f"uuid columns remain: {left}"
    counts_after = {t: q(f"SELECT count(*) FROM {t}")[0][0] for t in TABLES}
    assert counts_after == counts_before, f"row counts changed: {counts_before} -> {counts_after}"
    for v in VIEWS:
        q(f"SELECT count(*) FROM {v}")
    log(f"verified: no uuid columns left, row counts unchanged {counts_after}")

    if not commit:
        conn.rollback()
        log("REHEARSAL: rolled back, database unchanged")
        return
    conn.commit()
    log("COMMITTED")

    # ---- 10. after commit: recompress chunks the policy would already have compressed
    conn.autocommit = True
    n = q("SELECT count(compress_chunk(c, true)) FROM show_chunks('system_telemetry', "
          "older_than => %s::interval) c", compress_policy)[0][0]
    log(f"recompressed {n} chunks")
    conn.close()


if __name__ == "__main__":
    main(commit="--commit" in sys.argv)
