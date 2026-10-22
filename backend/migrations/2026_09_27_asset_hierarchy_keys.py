"""Rework battery_master.asset_hierarchy so a node is identified by (asset_type, asset_id).

    python 2026_09_27_asset_hierarchy_keys.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_27_asset_hierarchy_keys.py --commit   # run for real

asset_id is now the id of the record the node stands for (tenant.tenant_id, site.site_id,
battery_system.battery_system_id) and asset_type is that record's table name, so the same id
can appear once per type. The parent is (parent_asset_type, parent_asset_id):

    tenant  <-  site (primary owner in tenant_site)  <-  battery_system (battery_system.site_id)

Deleting a node empties the parent of its children (ON DELETE SET NULL). The 5 old June sample
rows (BATTERY_SYSTEM / CONTAINER / RACK / MODULE / PCS, not tied to real records) are deleted,
then nodes are built for the existing tenants, sites and battery systems.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    "DELETE FROM battery_master.asset_hierarchy",
    "ALTER TABLE battery_master.asset_hierarchy ALTER COLUMN asset_id DROP IDENTITY IF EXISTS",
    "ALTER TABLE battery_master.asset_hierarchy DROP CONSTRAINT asset_pkey",
    "ALTER TABLE battery_master.asset_hierarchy ADD COLUMN parent_asset_type varchar(50)",
    "ALTER TABLE battery_master.asset_hierarchy "
    "ADD CONSTRAINT asset_hierarchy_pkey PRIMARY KEY (asset_type, asset_id)",
    "ALTER TABLE battery_master.asset_hierarchy "
    "ADD CONSTRAINT asset_hierarchy_parent_fkey FOREIGN KEY (parent_asset_type, parent_asset_id) "
    "REFERENCES battery_master.asset_hierarchy (asset_type, asset_id) ON DELETE SET NULL",
    # parent is either fully set or fully empty
    "ALTER TABLE battery_master.asset_hierarchy ADD CONSTRAINT asset_hierarchy_parent_pair "
    "CHECK ((parent_asset_type IS NULL) = (parent_asset_id IS NULL))",
    "CREATE INDEX idx_asset_hierarchy_parent ON battery_master.asset_hierarchy (parent_asset_type, parent_asset_id)",
    # ---- existing records, parents first
    """INSERT INTO battery_master.asset_hierarchy (asset_type, asset_id, asset_name)
       SELECT 'tenant', tenant_id, name FROM battery_master.tenant""",
    """INSERT INTO battery_master.asset_hierarchy (asset_type, asset_id, asset_name, external_id, parent_asset_type, parent_asset_id)
       SELECT 'site', s.site_id, s.site_name, s.site_code,
              CASE WHEN ts.tenant_id IS NOT NULL THEN 'tenant' END, ts.tenant_id
       FROM battery_master.site s
       LEFT JOIN battery_master.tenant_site ts ON ts.site_id = s.site_id AND ts.is_primary_owner""",
    """INSERT INTO battery_master.asset_hierarchy (asset_type, asset_id, asset_name, parent_asset_type, parent_asset_id)
       SELECT 'battery_system', battery_system_id, system_name, 'site', site_id FROM battery_master.battery_system""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    cur.execute("SELECT asset_type, asset_name FROM battery_master.asset_hierarchy ORDER BY asset_id")
    print("deleting old rows:", cur.fetchall())
    for sql in STEPS:
        cur.execute(sql)
    cur.execute(
        "SELECT asset_type, asset_id, asset_name, external_id, parent_asset_type, parent_asset_id "
        "FROM battery_master.asset_hierarchy ORDER BY asset_type = 'tenant' DESC, asset_type = 'site' DESC, asset_id"
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
