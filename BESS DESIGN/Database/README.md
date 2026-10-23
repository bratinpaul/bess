# BESS database: ERD, DDL and new-database setup

Generated 2026-10-22 from database `Battery` (PostgreSQL 18.4, TimescaleDB 2.27.1).

| File | Contents |
|---|---|
| `BESS_ERD.pdf` | Overview of the 6 schemas and the foreign keys between them, one ERD page per schema, a table index and a view index |
| `DDL/00_create_all.sql` | Complete structure for all 6 schemas in runnable order |
| `DDL/01_seed_reference.sql` | Reference data every install needs: lookup codes (alarm severity, chemistry, modes, states, grid services, market) and the RBAC roles, privileges and role grants |
| `DDL/battery_<schema>.sql` | The structure split per schema, for reading. Cross-schema foreign keys need the other schemas first. |

## Setting up a new database

```
psql -h localhost -U postgres -d <new_db> -v ON_ERROR_STOP=1 -f DDL/00_create_all.sql
psql -h localhost -U postgres -d <new_db> -v ON_ERROR_STOP=1 -f DDL/01_seed_reference.sql
python backend/setup/bootstrap_auth.py --commit      # DATABASE_URL must point at <new_db>
```

1. **Structure.** The first script creates the extensions (timescaledb, pgcrypto), schemas, enums, tables, sequences, indexes, constraints and views. It then adds the TimescaleDB hypertables, compression settings, continuous aggregates (`WITH NO DATA`), the views built on them, the policies, and the database's default `search_path`, which the APIs rely on.
2. **Reference data.** The second script is re-runnable (`ON CONFLICT DO NOTHING`).
3. **Login bootstrap.** The script creates:
   - the JWT signing keys in `keys/`, if they're missing;
   - the starter users `admin@`, `asset.engineer@`, `operator@` and `data.scientist@bess.local`, with password `Password`, which must be changed at first sign-in;
   - `tenant.viewer@bess.local`, once its tenant has been loaded;
   - the batch service account, with its password in `keys/service_account.json`.

   Run it without `--commit` first for a rehearsal that changes nothing.

Site, asset and telemetry data then come in through the loaders (static data loader, historical loader, realtime batch). The `battery_*.backup` files in `BESS DESIGN` hold a full copy of the current data (`pg_restore`).

This setup was verified on a scratch database:
- object counts and seeded row counts matched the source;
- the role grants were identical;
- signing in through the API worked for the admin and the service account.

## Regenerating

```
python db_docs/generate_ddl.py --verify    # DDL + seed, with the scratch-database check
python db_docs/build_erd.py                # ERD PDF (needs Node and Chrome)
```
