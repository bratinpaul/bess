"""Self-service sign-up: access requests waiting for an Admin.

    python 2026_10_21_access_request.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_21_access_request.py --commit   # run for real

access_request  one row per sign-up: name, e-mail, organisation, why access is needed, the argon2 hash of the password the
                requester chose, status PENDING / APPROVED / REJECTED, and the review (who, when, role, tenant, note).
                On approval the backend creates the battery_users.app_user (user_id) and the requester can sign in.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
CREATE TABLE IF NOT EXISTS battery_users.access_request (
    request_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name       text         NOT NULL,
    email           varchar(320) NOT NULL,
    organisation    text,
    reason          text         NOT NULL,
    hashed_password varchar(1024) NOT NULL,
    status          text         NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    requested_at    timestamptz  NOT NULL DEFAULT now(),
    request_ip      text,
    reviewed_at     timestamptz,
    reviewed_by     text,
    role_id         smallint REFERENCES battery_users.role (role_id),
    tenant_id       bigint REFERENCES battery_master.tenant (tenant_id) ON DELETE SET NULL,
    decision_note   text,
    user_id         uuid REFERENCES battery_users.app_user (id) ON DELETE SET NULL
);
-- one open request per e-mail
CREATE UNIQUE INDEX IF NOT EXISTS ux_access_request_pending ON battery_users.access_request (lower(email))
    WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS ix_access_request_status ON battery_users.access_request (status, requested_at DESC);
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            cur.execute("SELECT count(*) FROM battery_users.access_request")
            print("access_request rows:", cur.fetchone()[0])
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
