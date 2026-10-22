"""Columns for loading static master data (input/static/bess_static_data.json) through the bulk loaders.

    python 2026_09_29_static_master_columns.py            # rehearsal: run, verify, ROLLBACK
    python 2026_09_29_static_master_columns.py --commit   # run for real

source_uuid   the record's UUID in the source system (the JSON's tenant_id, site_id, unit_id, pcs_id ...).
              Unique per table: the bulk loaders upsert on it, so a re-run updates instead of duplicating.
              Records created in the app have none.
Plus the JSON attributes that had no column yet:
  site               grid_voltage_kv
  battery_container  container_type, ip_rating, fire_suppression
  battery_pack       module_count
  battery_module     cell_count, soh_pct
  pcs                efficiency_pct, grid_mode (grid-following / grid-forming)
  ems_controller     manufacturer, model, firmware_version, control_mode
  hvac_unit          manufacturer, model, hvac_type, cooling_capacity_kw, status
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

TABLES = ["tenant", "site", "battery_system", "battery_container", "battery_pack", "battery_module", "pcs",
          "ems_controller", "hvac_unit"]

STEPS = [
    *[f"ALTER TABLE battery_master.{t} ADD COLUMN source_uuid uuid" for t in TABLES],
    *[f"ALTER TABLE battery_master.{t} ADD CONSTRAINT {t}_source_uuid_key UNIQUE (source_uuid)" for t in TABLES],
    "ALTER TABLE battery_master.site ADD COLUMN grid_voltage_kv numeric(8,2)",
    """ALTER TABLE battery_master.battery_container ADD COLUMN container_type text, ADD COLUMN ip_rating text,
        ADD COLUMN fire_suppression text""",
    "ALTER TABLE battery_master.battery_pack ADD COLUMN module_count integer CHECK (module_count IS NULL OR module_count >= 0)",
    """ALTER TABLE battery_master.battery_module ADD COLUMN cell_count integer CHECK (cell_count IS NULL OR cell_count >= 0),
        ADD COLUMN soh_pct numeric(5,2) CHECK (soh_pct IS NULL OR soh_pct BETWEEN 0 AND 100)""",
    """ALTER TABLE battery_master.pcs ADD COLUMN efficiency_pct numeric(5,2)
        CHECK (efficiency_pct IS NULL OR efficiency_pct BETWEEN 0 AND 100), ADD COLUMN grid_mode text""",
    """ALTER TABLE battery_master.ems_controller ADD COLUMN manufacturer text, ADD COLUMN model text,
        ADD COLUMN firmware_version text, ADD COLUMN control_mode text""",
    """ALTER TABLE battery_master.hvac_unit ADD COLUMN manufacturer text, ADD COLUMN model text, ADD COLUMN hvac_type text,
        ADD COLUMN cooling_capacity_kw numeric(8,2) CHECK (cooling_capacity_kw IS NULL OR cooling_capacity_kw >= 0),
        ADD COLUMN status text""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT table_name, count(*) FROM information_schema.columns
                   WHERE table_schema = 'battery_master' AND column_name = 'source_uuid' GROUP BY 1 ORDER BY 1""")
    print("   source_uuid on:", [r[0] for r in cur.fetchall()])
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
