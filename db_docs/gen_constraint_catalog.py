"""Generate bess_common/bess_common/constraint_catalog.py: one safe, user-facing message per database constraint.

When a write violates a constraint, the API answers with the catalog entry (code, HTTP status, message, field), never
with the Postgres text (constraint / table names, key values). Covered: primary keys, unique constraints, unique
indexes (incl. partial ones such as "one default run"), foreign keys (both directions: a missing parent on insert, a
parent still in use on delete) and check constraints, in the six battery_* schemas. NOT NULL violations are answered
from the column name (bess_common/errors_db.py).

Messages are derived from the table / column names and the constraint definition. Wording fixes go into
errors_db.OVERRIDES (merged over this file), so the generator can be re-run any time.

Usage:  python db_docs/gen_constraint_catalog.py            (re-run after every schema change; a test fails otherwise)
"""
import pprint
import re
import sys
from datetime import date
from pathlib import Path

import psycopg2

from bess_common.db_settings import psycopg2_dsn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bess_common" / "bess_common" / "constraint_catalog.py"
SCHEMAS = ["battery_master", "battery_users", "battery_raw", "battery_telemetry", "battery_ml", "battery_itops"]

ACRONYMS = {"pcs", "ems", "hvac", "bms", "soc", "soh", "rul", "ocv", "as", "dam", "rt", "cop", "ml", "mv", "ac", "dc",
            "poi", "rte", "kpi", "uuid", "igbt", "rbac", "eol", "rpt", "agc", "tou", "id", "fr", "btm", "ghi"}
UNITS = {"pct": "%", "kw": "kW", "kwh": "kWh", "mwh": "MWh", "kva": "kVA", "kvar": "kVAr", "hz": "Hz", "mv": "mV",
         "usd": "USD", "lpm": "l/min"}

CONSTRAINTS_SQL = """
SELECT n.nspname, cl.relname, con.conname, con.contype, pg_get_constraintdef(con.oid),
       ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum ORDER BY k.ord),
       rn.nspname, rcl.relname
  FROM pg_constraint con
  JOIN pg_class cl ON cl.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = cl.relnamespace
  LEFT JOIN pg_class rcl ON rcl.oid = con.confrelid
  LEFT JOIN pg_namespace rn ON rn.oid = rcl.relnamespace
 WHERE n.nspname = ANY(%s) AND con.contype IN ('p', 'u', 'f', 'c', 'x')
 ORDER BY 1, 2, 3"""

UNIQUE_INDEX_SQL = """
SELECT n.nspname, cl.relname, ic.relname, pg_get_indexdef(i.indexrelid),
       ARRAY(SELECT a.attname FROM unnest(i.indkey) k(attnum)
             JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum),
       pg_get_expr(i.indpred, i.indrelid)
  FROM pg_index i
  JOIN pg_class ic ON ic.oid = i.indexrelid
  JOIN pg_class cl ON cl.oid = i.indrelid
  JOIN pg_namespace n ON n.oid = cl.relnamespace
 WHERE n.nspname = ANY(%s) AND i.indisunique
   AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
 ORDER BY 1, 2, 3"""


# ------------------------------------------------------------------ labels
def words(name: str) -> list[str]:
    out = []
    for w in name.split("_"):
        if not w:
            continue
        out.append(UNITS.get(w) or (w.upper() if w in ACRONYMS else w))
    return out


def entity(table: str) -> str:
    """battery_system -> 'battery system', pcs_telemetry -> 'PCS telemetry'."""
    return " ".join(words(table))


def column(col: str) -> str:
    """site_code -> 'site code', tenant_id -> 'tenant', soc_bms_pct -> 'SOC BMS %'."""
    if col.endswith("_id") and col != "id":
        col = col[:-3]
    if col == "time" or col == "ts":
        return "time"
    return " ".join(words(col))


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def code_part(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def article(noun: str) -> str:
    first = noun.split(" ", 1)[0]
    if first.isupper() and len(first) > 1:  # acronyms by letter sound: an HVAC unit, an SOC estimate, a PCS
        vowel = first[0] in "AEFHILMNORSX"
    else:
        vowel = first[:1].lower() in "aeiou" and not first.lower().startswith(("uuid", "user", "use"))
    return ("an " if vowel else "a ") + noun


def join_and(items: list[str]) -> str:
    if not items:
        return "values"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# ------------------------------------------------------------------ entries
def unique_entry(table: str, cols: list[str], primary: bool, predicate: str | None = None) -> dict:
    ent = entity(table)
    meaningful = [c for c in cols if c not in ("id", f"{table}_id")]
    field = cols[0] if len(cols) == 1 else None
    if predicate:
        flag = re.search(r"\b(is_\w+)\b", predicate)
        state = column(flag.group(1)[3:]) if flag else None
        scope = [column(c) for c in meaningful if c not in ("use_case",)]
        per = f" per {join_and(scope)}" if scope else ""
        if not state:  # a plain unique rule on part of the rows (e.g. e-mail when given)
            return unique_entry(table, cols, primary=False)
        return {"kind": "unique", "code": f"{code_part(table)}_{code_part(state)}_CONFLICT",
                "status": 409, "message": f"Only one {ent} can be {state}{per}.", "field": field}
    if primary and (not meaningful or (len(cols) == 1 and cols[0].endswith("_id"))):
        return {"kind": "unique", "code": f"{code_part(table)}_DUPLICATE", "status": 409,
                "message": f"{cap(article(ent))} with this id already exists.", "field": None}
    labels = [column(c.removeprefix(table + "_") if c.startswith(table + "_") and c != f"{table}_id" else c)
              for c in meaningful] or ["id"]
    has_time = any(c in ("time", "ts") or c.endswith(("_ts", "_at", "_start", "_date")) for c in meaningful)
    if has_time and len(meaningful) > 1:
        message = f"{cap(article(ent))} already exists for this {join_and(labels)}."
    else:
        message = f"{cap(article(ent))} with this {join_and(labels)} already exists."
    suffix = "" if primary else "_" + code_part("_".join(c.removeprefix(table + "_") for c in meaningful))[:40]
    return {"kind": "unique", "code": f"{code_part(table)}{suffix}_DUPLICATE", "status": 409, "message": message,
            "field": field if field and field in meaningful else None}


def fk_entry(table: str, cols: list[str], ref_table: str) -> dict:
    ent, ref = entity(table), entity(ref_table)
    field = cols[0] if len(cols) == 1 else None
    label = column(cols[0]) if len(cols) == 1 else ref
    return {"kind": "fk", "code": f"{code_part(ref_table)}_NOT_FOUND", "status": 422,
            "message": f"The selected {label} does not exist.", "field": field,
            "in_use_code": f"{code_part(ref_table)}_IN_USE", "in_use_status": 409,
            "in_use_message": f"This {ref} can't be deleted or changed: {ent} records still refer to it."}


def _clean(definition: str) -> str:
    d = re.sub(r"\('(-?[\d.]+)'::\w+\)::\w+", r"\1", definition)    # ('-1'::integer)::numeric -> -1
    d = re.sub(r"\((-?[\d.]+)\)::\w+", r"\1", d)                      # (0)::numeric -> 0
    d = re.sub(r"'?(-?[\d.]+)'?::\w+", r"\1", d)
    d = re.sub(r"'([^']*)'::\w+", r"'\1'", d)
    return d.replace('"', "")


def check_message(table: str, name: str, cols: list[str], definition: str) -> str:
    d = _clean(definition)
    if len(cols) == 1:
        c = cols[0]
        label = cap(column(c))
        values = re.findall(r"'([^']*)'", d) if "ANY (ARRAY[" in d else []
        if not values and "ANY (ARRAY[" in d:
            values = re.findall(r"ARRAY\[([^\]]*)\]", d)[0].replace(" ", "").split(",")
        if values:
            return f"{label} must be one of {', '.join(values)}."
        lo = re.search(rf"\b{c} >= (-?[\d.]+)", d)
        hi = re.search(rf"\b{c} <= (-?[\d.]+)", d)
        gt = re.search(rf"\b{c} > (-?[\d.]+)", d)
        if lo and hi:
            return f"{label} must be between {lo.group(1)} and {hi.group(1)}."
        if lo:
            return f"{label} must be at least {lo.group(1)}."
        if gt:
            return f"{label} must be greater than {gt.group(1)}."
        if "btrim" in d and "<> ''" in d:
            return f"{cap(' '.join(words(c)))} must not be blank."
    # a <op> b between two columns, optionally guarded by "a IS NULL OR b IS NULL OR ..."
    order = re.fullmatch(r"CHECK \(+(?:\(\w+ IS NULL\) OR )*\(?([a-z_]\w*) (<=|>=|<|>) ([a-z_]\w*)\)+", d)
    if order:
        a, op, b = order.groups()
        timeish = any(x in ("time", "ts") or x.endswith(("_at", "_start", "_end", "_ts", "_date")) for x in (a, b))
        words_for = ({"<": "before", "<=": "not after", ">": "after", ">=": "not before"} if timeish else
                     {"<": "less than", "<=": "at most", ">": "greater than", ">=": "at least"})[op]
        verb = "must " + words_for if words_for.startswith("not") else "must be " + words_for
        verb = verb.replace("must not", "must not be") if words_for.startswith("not") else verb
        return f"{cap(column(a))} {verb} {column(b)}."
    pair = re.fullmatch(r"CHECK \(\(\((\w+) IS NULL\) = \((\w+) IS NULL\)\)\)", d)
    if pair:
        return f"{cap(column(pair.group(1)))} and {column(pair.group(2))} must be given together."
    bounds = [(re.search(rf"\b{c} >= (-?[\d.]+)", d), re.search(rf"\b{c} <= (-?[\d.]+)", d)) for c in cols]
    if len(cols) > 1 and all(lo and hi for lo, hi in bounds) and \
            len({(lo.group(1), hi.group(1)) for lo, hi in bounds}) == 1:
        lo, hi = bounds[0]
        return f"{cap(join_and([column(c) for c in cols]))} must be between {lo.group(1)} and {hi.group(1)}."
    if len(cols) > 1 and all(re.search(rf"\b{c} >= 0\b", d) for c in cols):
        return f"{cap(join_and([column(c) for c in cols]))} must not be negative."
    rule = " ".join(words(re.sub(r"_check$", "", re.sub(rf"^(chk_|ck_)?({table}_)?", "", name))))
    return f"The {entity(table)} values are not consistent ({rule})."


def check_entry(table: str, name: str, cols: list[str], definition: str) -> dict:
    rule = re.sub(r"_check$", "", re.sub(rf"^(chk_|ck_)?({table}_)?", "", name))
    return {"kind": "check", "code": f"{code_part(table)}_{code_part(rule)}_INVALID"[:64], "status": 422,
            "message": check_message(table, name, cols, definition), "field": cols[0] if len(cols) == 1 else None}


def build(conn) -> dict:
    catalog: dict[str, dict] = {}
    with conn.cursor() as cur:
        cur.execute(CONSTRAINTS_SQL, (SCHEMAS,))
        for schema, table, name, kind, definition, cols, _ref_schema, ref_table in cur.fetchall():
            if kind in ("p", "u"):
                entry = unique_entry(table, list(cols), primary=kind == "p")
            elif kind == "f":
                entry = fk_entry(table, list(cols), ref_table)
            elif kind == "c":
                entry = check_entry(table, name, list(cols), definition)
            else:  # exclusion
                entry = {"kind": "unique", "code": f"{code_part(table)}_OVERLAP", "status": 409,
                         "message": f"This {entity(table)} overlaps an existing one.", "field": None}
            catalog[f"{schema}.{name}"] = entry
        cur.execute(UNIQUE_INDEX_SQL, (SCHEMAS,))
        for schema, table, name, _definition, cols, predicate in cur.fetchall():
            catalog[f"{schema}.{name}"] = unique_entry(table, [c for c in cols if c], primary=False,
                                                       predicate=predicate)
    return catalog


def render(catalog: dict) -> str:
    body = pprint.pformat(catalog, width=118, sort_dicts=True)
    return f'''"""GENERATED by db_docs/gen_constraint_catalog.py on {date.today().isoformat()} - do not edit by hand.

Constraint ("schema.name") -> safe error: kind (unique | fk | check), code, HTTP status, message, field; fk entries
also carry in_use_code / in_use_status / in_use_message for deletes of a parent that is still referenced.
Wording fixes go into bess_common/errors_db.py OVERRIDES; re-run the generator after schema changes.
"""

CATALOG = {body}
'''


def main() -> int:
    with psycopg2.connect(**psycopg2_dsn()) as conn:
        catalog = build(conn)
    OUT.write_text(render(catalog), encoding="utf-8")
    print(f"{len(catalog)} constraints -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
