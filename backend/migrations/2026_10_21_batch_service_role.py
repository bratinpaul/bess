"""Least-privilege role for the batch loaders (realtime snapshot, static data, historical) and move the service account to it.

    python 2026_10_21_batch_service_role.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_21_batch_service_role.py --commit   # run for real

BATCH_SERVICE (service accounts only, not in the RBAC workbook) gets exactly what the loaders call:
    master.tenant / master.asset / master.hierarchy : read, write   (static loader -> /api/master-bulk/<entity>)
    telemetry                                       : read, write   (bulk telemetry, alarm and dispatch events)
    batch                                           : read, execute
batch.service@bess.local moves from Data Engineer to BATCH_SERVICE; human Data Engineers keep the matrix grants.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()
GRANTS = [("master.tenant", "read"), ("master.tenant", "write"), ("master.asset", "read"), ("master.asset", "write"),
          ("master.hierarchy", "read"), ("master.hierarchy", "write"), ("telemetry", "read"), ("telemetry", "write"),
          ("batch", "read"), ("batch", "execute")]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO battery_users.role (role_code, role_name, is_tenant_scoped, description)
                           VALUES ('BATCH_SERVICE', 'Batch Service', false,
                                   'Service accounts of the batch loaders - bulk master data and telemetry only')
                           ON CONFLICT (role_code) DO UPDATE SET description = EXCLUDED.description""")
            cur.execute("DELETE FROM battery_users.role_privilege WHERE role_id = (SELECT role_id FROM battery_users.role "
                        "WHERE role_code = 'BATCH_SERVICE')")
            for resource, action in GRANTS:
                cur.execute("""INSERT INTO battery_users.privilege (resource, action, module_label) VALUES (%s, %s, 'Batch loaders')
                               ON CONFLICT (resource, action) DO NOTHING""", (resource, action))
                cur.execute("""INSERT INTO battery_users.role_privilege (role_id, privilege_id)
                               SELECT r.role_id, p.privilege_id FROM battery_users.role r, battery_users.privilege p
                               WHERE r.role_code = 'BATCH_SERVICE' AND p.resource = %s AND p.action = %s""", (resource, action))
            cur.execute("""UPDATE battery_users.app_user SET role_id = (SELECT role_id FROM battery_users.role
                           WHERE role_code = 'BATCH_SERVICE') WHERE email = 'batch.service@bess.local'""")
            cur.execute("""SELECT u.email, r.role_code, array_agg(p.code ORDER BY p.code)
                           FROM battery_users.app_user u JOIN battery_users.role r USING (role_id)
                           JOIN battery_users.role_privilege rp ON rp.role_id = r.role_id
                           JOIN battery_users.privilege p ON p.privilege_id = rp.privilege_id
                           WHERE u.email = 'batch.service@bess.local' GROUP BY 1, 2""")
            print(cur.fetchall())
        if commit:
            conn.commit()
            print("committed")
        else:
            conn.rollback()
            print("rehearsal - rolled back (use --commit)")
    finally:
        conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
