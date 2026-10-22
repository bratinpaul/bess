"""Export the BESS schema metadata (tables, columns, keys, foreign keys, hypertables, views) to JSON for the ERD.

Usage: python db_docs/export_model.py <out.json>
"""
import json
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn

SCHEMAS = ["battery_master", "battery_users", "battery_raw", "battery_telemetry", "battery_ml", "battery_itops"]


def main(out: str) -> int:
    with psycopg2.connect(**psycopg2_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path = pg_catalog")
        cur.execute("""
            SELECT n.nspname, c.relname, c.relkind, obj_description(c.oid, 'pg_class'),
                   greatest(c.reltuples, 0)::bigint
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v', 'm')
            ORDER BY 1, 2""", (SCHEMAS,))
        rels = {(s, t): {"schema": s, "name": t, "kind": "view" if k in ("v", "m") else "table", "comment": cm,
                         "rows_est": rows, "columns": [], "hypertable": False, "cagg": False}
                for s, t, k, cm, rows in cur.fetchall()}

        cur.execute("""
            SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   col_description(c.oid, a.attnum)
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v', 'm') AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY 1, 2, a.attnum""", (SCHEMAS,))
        for s, t, col, typ, notnull, cm in cur.fetchall():
            rels[(s, t)]["columns"].append({"name": col, "type": typ, "not_null": notnull, "comment": cm,
                                            "pk": False, "fk": False, "unique": False})

        cur.execute("""
            SELECT n.nspname, c.relname, k.contype, array_agg(a.attname ORDER BY x.ord)
            FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN LATERAL unnest(k.conkey) WITH ORDINALITY x(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = x.attnum
            WHERE n.nspname = ANY(%s) AND k.contype IN ('p', 'u')
            GROUP BY n.nspname, c.relname, k.oid, k.contype""", (SCHEMAS,))
        for s, t, kind, cols in cur.fetchall():
            for col in rels[(s, t)]["columns"]:
                if col["name"] in cols:
                    col["pk" if kind == "p" else "unique"] = True

        cur.execute("""
            SELECT k.conname, n.nspname, c.relname, rn.nspname, r.relname,
                   (SELECT array_agg(a.attname ORDER BY x.ord) FROM unnest(k.conkey) WITH ORDINALITY x(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = x.attnum),
                   (SELECT array_agg(a.attname ORDER BY x.ord) FROM unnest(k.confkey) WITH ORDINALITY x(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = x.attnum)
            FROM pg_constraint k
            JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_class r ON r.oid = k.confrelid JOIN pg_namespace rn ON rn.oid = r.relnamespace
            WHERE k.contype = 'f' AND n.nspname = ANY(%s)
            ORDER BY 2, 3, 1""", (SCHEMAS,))
        fks = []
        for name, s, t, rs, rt, cols, rcols in cur.fetchall():
            fks.append({"name": name, "from": f"{s}.{t}", "to": f"{rs}.{rt}", "columns": cols, "ref_columns": rcols})
            for col in rels[(s, t)]["columns"]:
                if col["name"] in cols:
                    col["fk"] = True
                    col.setdefault("refs", []).append(f"{rs}.{rt}")

        cur.execute("""SELECT hypertable_schema, hypertable_name FROM timescaledb_information.hypertables
                       WHERE hypertable_schema = ANY(%s)""", (SCHEMAS,))
        for s, t in cur.fetchall():
            rels[(s, t)]["hypertable"] = True
        cur.execute("""SELECT view_schema, view_name FROM timescaledb_information.continuous_aggregates
                       WHERE view_schema = ANY(%s)""", (SCHEMAS,))
        for s, t in cur.fetchall():
            rels[(s, t)]["cagg"] = True

        # what each view reads from (direct dependencies)
        cur.execute("""
            SELECT DISTINCT vn.nspname, v.relname, tn.nspname, t.relname
            FROM pg_rewrite r JOIN pg_class v ON v.oid = r.ev_class JOIN pg_namespace vn ON vn.oid = v.relnamespace
            JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass
            JOIN pg_class t ON t.oid = d.refobjid JOIN pg_namespace tn ON tn.oid = t.relnamespace
            WHERE vn.nspname = ANY(%s) AND v.relkind IN ('v', 'm') AND t.oid <> v.oid AND t.relkind IN ('r','p','v','m')
            ORDER BY 1, 2, 3, 4""", (SCHEMAS,))
        for vs, vt, ts, tt in cur.fetchall():
            src = f"{ts}.{tt}"
            if ts.startswith("_timescaledb"):
                src = "(continuous aggregate storage)"
            rels[(vs, vt)].setdefault("sources", [])
            if src not in rels[(vs, vt)]["sources"]:
                rels[(vs, vt)]["sources"].append(src)

        cur.execute("SELECT current_database(), now()::date::text")
        db, today = cur.fetchone()

    model = {"database": db, "generated": today, "schemas": SCHEMAS,
             "relations": list(rels.values()), "foreign_keys": fks}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=1)
    tables = sum(1 for r in rels.values() if r["kind"] == "table")
    print(f"{tables} tables, {len(rels) - tables} views, {len(fks)} foreign keys -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
