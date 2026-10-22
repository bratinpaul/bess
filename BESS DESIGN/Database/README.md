# BESS database: ERD and DDL

Generated 2026-10-22 from database `Battery` (PostgreSQL 18.4, TimescaleDB 2.27.1).

| File | Contents |
|---|---|
| `BESS_ERD.pdf` | Overview of the 6 schemas and the foreign keys between them, one ERD page per schema, a table index and a view index |
| `DDL/00_create_all.sql` | Complete DDL for all 6 schemas in runnable order. **Run this one.** |
| `DDL/battery_<schema>.sql` | The same DDL split per schema, for reading. Cross-schema foreign keys need the other schemas to exist first. |

## Running the DDL

```
psql -h localhost -U postgres -d <new_db> -v ON_ERROR_STOP=1 -f DDL/00_create_all.sql
```

The script creates the extensions (timescaledb, pgcrypto), schemas, enums, tables, sequences, indexes, constraints and views. It then adds the TimescaleDB hypertables, compression settings, continuous aggregates (`WITH NO DATA`; refresh them or let the policies fill them), the views built on those aggregates, the compression, retention and refresh policies, and the database's default `search_path`, which the APIs rely on.

The script is verified by rebuilding into a scratch database: tables, views, indexes, sequences, constraints, hypertables, continuous aggregates and policies all match the source.

## Regenerating

```
python db_docs/generate_ddl.py --verify    # DDL, plus the scratch-database check
python db_docs/build_erd.py                # ERD PDF (needs Node and Chrome; runs npm install in db_docs once)
```
