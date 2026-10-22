"""Retire battery_master.bess_system: every system reference points at battery_master.battery_system.

    python 2026_10_15_drop_bess_system.py            # rehearsal: apply, verify, ROLLBACK
    python 2026_10_15_drop_bess_system.py --commit   # for real

bess_system (BESS-01 ... BESS-15, ids 16-30) was a second system registry: the RUL fleet and the arbitrage data pack
pointed at it instead of battery_system. Decisions (2026-10-15, user):
  * the RUL fleet data is deleted - aging_snapshot, capacity_test, lifecycle_event, battery_provenance (all rows
    belong to BESS-01..15) and the RUL model results battery_ml.rul_run / rul_score / rul_backtest / rul_forecast;
  * the BESS-01 arbitrage rows (optimization_run, dispatch_outcome, as_award, battery_opt_param, efficiency_curve,
    degradation_cost_curve, interconnection_limit) and current_sensor_cal move to EESL-BESS-S02 (battery_system 12).
Then every foreign key that referenced bess_system(system_id) is recreated against battery_system(battery_system_id)
(same name, column and ON DELETE action), v_rul_training is rebuilt on battery_system (system_name AS system_code),
and bess_system is dropped. Columns keep the name system_id.

Every table whose rows are deleted (and bess_system itself) is first copied to battery_raw.bak_20261015_<table>,
so the data can be restored. All in one transaction.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

TARGET_SYSTEM = "EESL-BESS-S02"          # battery_system 12, Bhadla BESS Site
MOVE_TABLES = ["optimization_run", "dispatch_outcome", "as_award", "battery_opt_param", "efficiency_curve",
               "degradation_cost_curve", "interconnection_limit", "current_sensor_cal"]
RUL_MASTER = ["aging_snapshot", "capacity_test", "lifecycle_event", "battery_provenance"]
RUL_ML = ["rul_score", "rul_backtest", "rul_forecast", "rul_run"]       # children first
BACKUP = "battery_raw.bak_20261015_"

FKS_SQL = """
SELECT c.conname, cn.nspname, cr.relname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class cr ON cr.oid = c.conrelid JOIN pg_namespace cn ON cn.oid = cr.relnamespace
WHERE c.contype = 'f' AND c.confrelid = 'battery_master.bess_system'::regclass
  AND cn.nspname <> '_timescaledb_internal'          -- chunk copies follow their hypertable
ORDER BY cr.relname
"""

V_RUL_TRAINING = """
CREATE VIEW battery_master.v_rul_training AS
SELECT a.system_id,
       s.system_name AS system_code,
       a.snapshot_date, a.age_days, a.calendar_age_years, a.cum_throughput_mwh, a.equiv_full_cycles, a.avg_dod_pct,
       a.avg_cell_temp_c, a.days_at_high_soc, a.soh_pct, a.internal_resistance_mohm,
       p.batch_lot, p.usage_cycles_per_day, p.climate_avg_temp_c, p.bol_capacity_kwh,
       a.rul_days, a.rul_cycles, a.is_censored, a.eol_reached
FROM battery_master.aging_snapshot a
JOIN battery_master.battery_system s ON s.battery_system_id = a.system_id
LEFT JOIN battery_master.battery_provenance p ON p.system_id = a.system_id
"""


def count(cur, table: str, where: str = "") -> int:
    cur.execute(f"SELECT count(*) FROM {table} {where}")
    return cur.fetchone()[0]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT battery_system_id FROM battery_master.battery_system WHERE system_name = %s",
                        (TARGET_SYSTEM,))
            target = cur.fetchone()[0]
            cur.execute("SELECT array_agg(system_id ORDER BY system_id) FROM battery_master.bess_system")
            bess_ids = cur.fetchone()[0]
            print(f"bess_system ids {bess_ids[0]}..{bess_ids[-1]} ({len(bess_ids)}) -> target {TARGET_SYSTEM} = {target}")

            cur.execute(FKS_SQL)
            fks = cur.fetchall()
            print(f"\nforeign keys to recreate ({len(fks)}):")
            for name, schema, table, definition in fks:
                print(f"  {schema}.{table:<24} {name:<40} {definition}")

            # 1. backups of everything that will be deleted
            print("\nbackups:")
            for t in ["battery_master.bess_system"] + [f"battery_master.{t}" for t in RUL_MASTER] + \
                     [f"battery_ml.{t}" for t in RUL_ML]:
                bak = BACKUP + t.split(".")[1]
                cur.execute(f"DROP TABLE IF EXISTS {bak}")
                cur.execute(f"CREATE TABLE {bak} AS TABLE {t}")
                print(f"  {t:<34} -> {bak} ({count(cur, bak)} rows)")

            # 2. the view that depends on bess_system
            cur.execute("DROP VIEW battery_master.v_rul_training")

            # 3. delete the RUL fleet data and its model results
            print("\ndeleted:")
            for t in RUL_ML:
                cur.execute(f"DELETE FROM battery_ml.{t}")
                print(f"  battery_ml.{t:<22} {cur.rowcount}")
            for t in RUL_MASTER:
                cur.execute(f"DELETE FROM battery_master.{t} WHERE system_id = ANY(%s)", (bess_ids,))
                print(f"  battery_master.{t:<18} {cur.rowcount}")

            # 4. drop the old foreign keys
            for name, schema, table, _ in fks:
                cur.execute(f'ALTER TABLE {schema}.{table} DROP CONSTRAINT "{name}"')

            # 5. move the BESS-01 rows to the target battery system
            print(f"\nmoved to {TARGET_SYSTEM}:")
            for t in MOVE_TABLES:
                cur.execute(f"UPDATE battery_master.{t} SET system_id = %s WHERE system_id = ANY(%s)",
                            (target, bess_ids))
                print(f"  battery_master.{t:<24} {cur.rowcount}")

            # 6. nothing may still point at a non-existent battery system
            for _, schema, table, _ in fks:
                orphans = count(cur, f"{schema}.{table}", "WHERE system_id IS NOT NULL AND system_id NOT IN "
                                                          "(SELECT battery_system_id FROM battery_master.battery_system)")
                if orphans:
                    raise RuntimeError(f"{schema}.{table} still has {orphans} rows without a battery_system")

            # 7. recreate the foreign keys against battery_system
            for name, schema, table, definition in fks:
                new_def = definition.replace("REFERENCES bess_system(system_id)",
                                             "REFERENCES battery_master.battery_system(battery_system_id)")
                assert new_def != definition, definition
                cur.execute(f'ALTER TABLE {schema}.{table} ADD CONSTRAINT "{name}" {new_def}')

            # 8. rebuild the view, drop the old registry
            cur.execute(V_RUL_TRAINING)
            cur.execute("DROP TABLE battery_master.bess_system")

            # verify
            cur.execute("SELECT to_regclass('battery_master.bess_system')")
            assert cur.fetchone()[0] is None
            cur.execute("""SELECT cr.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c
                           JOIN pg_class cr ON cr.oid = c.conrelid JOIN pg_namespace cn ON cn.oid = cr.relnamespace
                           WHERE c.contype = 'f' AND c.confrelid = 'battery_master.battery_system'::regclass
                             AND cn.nspname <> '_timescaledb_internal' AND c.conname = ANY(%s) ORDER BY 1""",
                        ([f[0] for f in fks],))
            recreated = cur.fetchall()
            print(f"\nforeign keys now on battery_system: {len(recreated)} of {len(fks)}")
            for table, name, definition in recreated:
                print(f"  {table:<24} {definition}")
            assert len(recreated) == len(fks)
            print(f"v_rul_training rows: {count(cur, 'battery_master.v_rul_training')}")
            print("bess_system dropped")

        if commit:
            conn.commit()
            print("\ncommitted")
        else:
            conn.rollback()
            print("\nrolled back (rehearsal) - pass --commit to apply")
    finally:
        conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
