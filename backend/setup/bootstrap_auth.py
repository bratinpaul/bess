"""Bootstrap login for a new BESS database: JWT signing keys, starter users and the batch service account.

Run once after "BESS DESIGN/Database/DDL/00_create_all.sql" and "01_seed_reference.sql" (roles and privileges).
Safe to re-run: existing keys, users and passwords are kept.

    python backend/setup/bootstrap_auth.py            # rehearsal: shows what it would do, changes nothing
    python backend/setup/bootstrap_auth.py --commit   # do it

Creates
  keys/jwt_private.pem, keys/jwt_public.pem   RS256 key pair for access tokens (only if missing)
  starter users                               password "Password", must change it at first sign-in
  batch.service@bess.local                    role BATCH_SERVICE, random password -> keys/service_account.json

The database comes from DATABASE_URL (environment, else backend/.env). --keys-dir writes the key files elsewhere.
"""
import argparse
import json
import secrets
import sys
import uuid
from pathlib import Path

import psycopg2
from pwdlib import PasswordHash

from bess_common.db_settings import psycopg2_dsn

ROOT = Path(__file__).resolve().parents[2]
STARTER_USERS = [  # email, full name, role code, tenant name (tenant-scoped roles only)
    ("admin@bess.local", "Platform Admin", "ADMIN", None),
    ("asset.engineer@bess.local", "Asset Engineer", "ASSET_ENGINEER", None),
    ("operator@bess.local", "Plant Operator", "OPERATOR", None),
    ("data.scientist@bess.local", "Data Scientist", "DATA_SCIENTIST", None),
    ("tenant.viewer@bess.local", "Tenant Viewer (Tata Power)", "TENANT_VIEWER", "Tata Power Renewable Energy Limited"),
]
STARTER_PASSWORD = "Password"
SERVICE = ("batch.service@bess.local", "Batch service account", "BATCH_SERVICE")


def write_keys(keys: Path, commit: bool) -> None:
    priv, pub = keys / "jwt_private.pem", keys / "jwt_public.pem"
    if priv.exists() and pub.exists():
        print(f"JWT keys: present in {keys} - kept")
        return
    if not commit:
        print(f"JWT keys: would create an RS256 key pair in {keys}")
        return
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    keys.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"JWT keys: RS256 key pair written to {keys}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", action="store_true", help="make the changes (default: rehearsal)")
    ap.add_argument("--keys-dir", type=Path, default=ROOT / "keys")
    args = ap.parse_args()

    hasher = PasswordHash.recommended()  # argon2id, the same as the backend's fastapi-users helper
    service_password = None
    conn = psycopg2.connect(**psycopg2_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role_code, role_id FROM battery_users.role")
            roles = dict(cur.fetchall())
            missing = {code for _, _, code, _ in STARTER_USERS} | {SERVICE[2]}
            missing -= set(roles)
            if missing:
                print(f"roles missing: {', '.join(sorted(missing))} - run 01_seed_reference.sql first")
                return 1
            starter_hash = hasher.hash(STARTER_PASSWORD)
            for email, name, role, tenant in STARTER_USERS:
                cur.execute("SELECT 1 FROM battery_users.app_user WHERE email = %s", (email,))
                if cur.fetchone():
                    print(f"user {email}: exists - kept")
                    continue
                tenant_id = None
                if tenant:
                    cur.execute("SELECT tenant_id FROM battery_master.tenant WHERE name = %s", (tenant,))
                    row = cur.fetchone()
                    if row is None:
                        print(f"user {email}: skipped - tenant '{tenant}' not loaded yet (re-run after the master data)")
                        continue
                    tenant_id = row[0]
                cur.execute("""INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id,
                                   tenant_id, is_superuser, must_change_password)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, true)""",
                            (str(uuid.uuid4()), email, starter_hash, name, roles[role], tenant_id, role == "ADMIN"))
                print(f"user {email}: created ({role}, must change password)")
            cur.execute("SELECT 1 FROM battery_users.app_user WHERE email = %s", (SERVICE[0],))
            if cur.fetchone():
                print(f"user {SERVICE[0]}: exists - kept")
            else:
                service_password = secrets.token_urlsafe(32)
                cur.execute("""INSERT INTO battery_users.app_user (id, email, hashed_password, full_name, role_id,
                                   is_service_account, must_change_password)
                               VALUES (%s, %s, %s, %s, %s, true, false)""",
                            (str(uuid.uuid4()), SERVICE[0], hasher.hash(service_password), SERVICE[1], roles[SERVICE[2]]))
                print(f"user {SERVICE[0]}: created ({SERVICE[2]})")
        if not args.commit:
            conn.rollback()
            write_keys(args.keys_dir, False)
            print("rehearsal - nothing changed (use --commit)")
            return 0
        conn.commit()
    finally:
        conn.close()
    write_keys(args.keys_dir, True)
    if service_password:
        args.keys_dir.mkdir(parents=True, exist_ok=True)
        (args.keys_dir / "service_account.json").write_text(
            json.dumps({"email": SERVICE[0], "password": service_password}, indent=2), encoding="utf-8")
        print(f"service account credentials written to {args.keys_dir / 'service_account.json'}")
    print("committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
