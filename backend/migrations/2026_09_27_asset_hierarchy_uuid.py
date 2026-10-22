"""asset_hierarchy: asset_id becomes a generated UUID; the record's own id moves to source_id.

    python 2026_09_27_asset_hierarchy_uuid.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_27_asset_hierarchy_uuid.py --commit   # run for real

    asset_id         uuid PK, gen_random_uuid()
    asset_type       table name of the record (tenant / site / battery_system)
    source_id        the record's id (tenant_id / site_id / battery_system_id); unique per asset_type
    parent_asset_id  uuid -> asset_hierarchy.asset_id, ON DELETE SET NULL
    external_id      no longer filled (was the site code); left for manual use

parent_asset_type is dropped: the parent's type is read from the parent row. Every row is derived
from the tenant / site / battery_system tables, so the rows are rebuilt rather than converted.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
T = "battery_master.asset_hierarchy"

STEPS = [
    f"DELETE FROM {T}",
    f"ALTER TABLE {T} DROP CONSTRAINT asset_hierarchy_parent_fkey",
    f"ALTER TABLE {T} DROP CONSTRAINT asset_hierarchy_parent_pair",
    f"ALTER TABLE {T} DROP CONSTRAINT asset_hierarchy_pkey",
    "DROP INDEX battery_master.idx_asset_hierarchy_parent",
    f"ALTER TABLE {T} DROP COLUMN parent_asset_type",
    f"ALTER TABLE {T} ALTER COLUMN asset_id TYPE uuid USING gen_random_uuid()",
    f"ALTER TABLE {T} ALTER COLUMN asset_id SET DEFAULT gen_random_uuid()",
    f"ALTER TABLE {T} ALTER COLUMN parent_asset_id TYPE uuid USING NULL",
    f"ALTER TABLE {T} ADD COLUMN source_id bigint NOT NULL",
    f"ALTER TABLE {T} ADD CONSTRAINT asset_hierarchy_pkey PRIMARY KEY (asset_id)",
    f"ALTER TABLE {T} ADD CONSTRAINT asset_hierarchy_source_key UNIQUE (asset_type, source_id)",
    f"ALTER TABLE {T} ADD CONSTRAINT asset_hierarchy_parent_fkey FOREIGN KEY (parent_asset_id) "
    f"REFERENCES {T} (asset_id) ON DELETE SET NULL",
    f"CREATE INDEX idx_asset_hierarchy_parent ON {T} (parent_asset_id)",
    # ---- rebuild from the records, parents first
    f"INSERT INTO {T} (asset_type, source_id, asset_name) SELECT 'tenant', tenant_id, name FROM battery_master.tenant",
    f"""INSERT INTO {T} (asset_type, source_id, asset_name, parent_asset_id)
        SELECT 'site', s.site_id, s.site_name, p.asset_id
        FROM battery_master.site s
        LEFT JOIN battery_master.tenant_site ts ON ts.site_id = s.site_id AND ts.is_primary_owner
        LEFT JOIN {T} p ON p.asset_type = 'tenant' AND p.source_id = ts.tenant_id""",
    f"""INSERT INTO {T} (asset_type, source_id, asset_name, parent_asset_id)
        SELECT 'battery_system', b.battery_system_id, b.system_name, p.asset_id
        FROM battery_master.battery_system b
        LEFT JOIN {T} p ON p.asset_type = 'site' AND p.source_id = b.site_id""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute(
        f"""SELECT a.asset_type, a.source_id, a.asset_name, a.asset_id, p.asset_type, p.source_id, a.external_id
            FROM {T} a LEFT JOIN {T} p ON p.asset_id = a.parent_asset_id
            ORDER BY a.asset_type = 'tenant' DESC, a.asset_type = 'site' DESC, a.source_id"""
    )
    for row in cur.fetchall():
        print("  ", row)
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
