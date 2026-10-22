"""Core -> Fault: view, add, edit, delete and bulk-load the fault-diagnosis tables (battery_master) - fault_catalog,
fault_signature, fault_episode, fault_alarm_link, maintenance_action, fault_prediction.

One spec per table drives everything: the columns (kind, required, allowed values, references), the row key used in
URLs, the natural key bulk loads upsert on, the filters, the date column and the summary statistics. Uploads take
.csv / .xlsx with the BESS DESIGN file headers; system_code is the battery system name (the pack's legacy BESS-01 maps
to EESL-BESS-S02, where the retired bess_system data went). Timestamps without a zone are plant time (Asia/Kolkata).
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import MetaData, Table, and_, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.services.demand_telemetry_import import _read_csv, _read_xlsx, _ts

PLANT_TZ = ZoneInfo("Asia/Kolkata")
SCHEMA = "battery_master"
MAX_ROWS = 100_000
LEGACY_SYSTEMS = {"BESS-01": "EESL-BESS-S02"}   # the retired bess_system code -> battery_system name

router = APIRouter(prefix="/api/fault", tags=["fault"])

SUBSYSTEMS = ("BMS", "PCS", "EMS", "HVAC", "PLANT")
SIGNAL_KINDS = ("ALARM", "TELEMETRY", "FEATURE")
OPERATORS = (">", "<", ">=", "<=", "==", "!=", "RISING", "FALLING", "PRESENT")
DETECTION_METHODS = ("ALARM", "MODEL", "INSPECTION", "MAINTENANCE", "OPERATOR")
ROLES = ("PRIMARY", "CONTRIBUTING", "CONSEQUENTIAL")
ACTION_TYPES = ("INSPECT", "REPAIR", "REPLACE", "RESET", "CALIBRATE", "CLEAN", "FIRMWARE", "NO_ACTION")
ASSET_TYPES = ("System", "Cell", "Module", "Pack", "Inverter", "HVAC Unit", "Site Controller")
SEVERITIES = (0, 1, 2, 3)


@dataclass(frozen=True)
class F:
    name: str
    kind: str = "text"                       # text | int | num | bool | ts | system
    required: bool = False
    choices: Optional[tuple] = None          # allowed values (enums are matched case-insensitively)
    ref: Optional[str] = None                # fault | episode - must exist
    headers: tuple = ()                      # extra accepted upload headers
    lo: Optional[float] = None
    hi: Optional[float] = None


@dataclass
class Spec:
    endpoint: str
    table: str
    title: str
    fields: list[F]
    key: list[str]                           # URL key (row identity)
    conflict: list[str]                      # bulk upsert key
    generated: Optional[str] = None          # identity column (not in uploads)
    date_col: Optional[str] = None
    filters: list[str] = field(default_factory=list)
    search: list[str] = field(default_factory=list)
    stats: list[tuple[str, str, str]] = field(default_factory=list)   # (label, SQL aggregate, format)
    check: Optional[Callable[[dict], tuple[list[str], list[str]]]] = None   # -> (errors, warnings)


def _episode_check(r: dict):
    errs, warns = [], []
    if r.get("resolved_ts") and r.get("detected_ts") and r["resolved_ts"] < r["detected_ts"]:
        errs.append("resolved_ts is before detected_ts")
    if r.get("onset_ts") and r.get("detected_ts") and r["detected_ts"] < r["onset_ts"]:
        warns.append(f"{r.get('episode_id')}: detected before onset")
    if r.get("is_ongoing") is True and r.get("resolved_ts"):
        warns.append(f"{r.get('episode_id')}: marked ongoing but has a resolved_ts")
    return errs, warns


def _signature_check(r: dict):
    if r.get("operator") in (">", "<", ">=", "<=", "==", "!=") and r.get("threshold") is None:
        return [f"operator {r['operator']} needs a threshold"], []
    return [], []


def _prediction_check(r: dict):
    warns = []
    if r.get("actual_fault_code") and r.get("is_correct") is not None:
        if (r["predicted_fault_code"] == r["actual_fault_code"]) != r["is_correct"]:
            warns.append(f"{r.get('asset_code')} {r.get('predicted_at')}: is_correct disagrees with predicted vs actual fault")
    return [], warns


SPECS: dict[str, Spec] = {s.endpoint: s for s in [
    Spec("fault-catalog", "fault_catalog", "Fault catalog", [
        F("fault_code", required=True), F("fault_name", required=True), F("subsystem", required=True, choices=SUBSYSTEMS),
        F("category", required=True), F("failure_mode"), F("default_severity", "int", choices=SEVERITIES),
        F("is_safety_critical", "bool"), F("typical_root_cause"), F("typical_symptoms"), F("recommended_action"),
        F("standard_ref")],
        key=["fault_code"], conflict=["fault_code"], filters=["subsystem", "category"],
        search=["fault_code", "fault_name", "failure_mode"],
        stats=[("Fault classes", "count(*)", "int"), ("Safety-critical", "count(*) FILTER (WHERE is_safety_critical)", "int"),
               ("Subsystems", "count(DISTINCT subsystem)", "int")]),
    Spec("fault-signatures", "fault_signature", "Fault signature", [
        F("fault_code", required=True, ref="fault"), F("signal", required=True), F("signal_kind", choices=SIGNAL_KINDS),
        F("operator", choices=OPERATORS), F("threshold", "num"), F("unit"), F("window_min", "int", lo=0, hi=32767),
        F("weight", "num", lo=0), F("note")],
        key=["signature_id"], conflict=["fault_code", "signal"], generated="signature_id",
        filters=["fault_code", "signal_kind"], search=["signal", "note"], check=_signature_check,
        stats=[("Signatures", "count(*)", "int"), ("Faults covered", "count(DISTINCT fault_code)", "int"),
               ("Alarm-based", "count(*) FILTER (WHERE signal_kind = 'ALARM')", "int"),
               ("Avg weight", "avg(weight)", "2")]),
    Spec("fault-episodes", "fault_episode", "Fault episode", [
        F("episode_id", required=True), F("system_id", "system", required=True), F("asset_type", choices=ASSET_TYPES),
        F("asset_code"), F("fault_code", required=True, ref="fault"), F("onset_ts", "ts"),
        F("detected_ts", "ts", required=True), F("resolved_ts", "ts"),
        F("detection_method", choices=DETECTION_METHODS), F("severity_level", "int", choices=SEVERITIES),
        F("confirmed_by"), F("label_confidence", "num", lo=0, hi=1), F("root_cause_confirmed"),
        F("operating_context"), F("downtime_min", "num", lo=0), F("energy_lost_kwh", "num", lo=0),
        F("is_ongoing", "bool"), F("note")],
        key=["episode_id"], conflict=["episode_id"], date_col="detected_ts",
        filters=["system_id", "fault_code", "asset_type", "severity_level"], search=["episode_id", "asset_code", "root_cause_confirmed"],
        check=_episode_check,
        stats=[("Episodes", "count(*)", "int"), ("Fault classes", "count(DISTINCT fault_code)", "int"),
               ("Ongoing", "count(*) FILTER (WHERE is_ongoing OR resolved_ts IS NULL)", "int"),
               ("Mean time to resolve", "avg(extract(epoch FROM resolved_ts - detected_ts) / 60)", "min"),
               ("Downtime", "sum(downtime_min)", "min"), ("Energy lost", "sum(energy_lost_kwh)", "kwh")]),
    Spec("fault-alarm-links", "fault_alarm_link", "Fault–alarm link", [
        F("episode_id", required=True, ref="episode"), F("alarm_id", required=True, ref="alarm"), F("role", choices=ROLES)],
        key=["episode_id", "alarm_id"], conflict=["episode_id", "alarm_id"], filters=["episode_id", "role"],
        search=["alarm_id"],
        stats=[("Links", "count(*)", "int"), ("Episodes linked", "count(DISTINCT episode_id)", "int"),
               ("Primary alarms", "count(*) FILTER (WHERE role = 'PRIMARY')", "int")]),
    Spec("maintenance-actions", "maintenance_action", "Maintenance action", [
        F("action_id", required=True), F("episode_id", ref="episode"), F("system_id", "system"),
        F("action_type", choices=ACTION_TYPES), F("component"), F("part_number"), F("part_replaced", "bool"),
        F("labor_hours", "num", lo=0), F("cost_usd", "num", lo=0), F("performed_by"), F("performed_at", "ts"),
        F("resolution"), F("fault_confirmed", "bool"), F("effective", "bool"), F("note")],
        key=["action_id"], conflict=["action_id"], date_col="performed_at",
        filters=["system_id", "action_type", "episode_id"], search=["action_id", "component", "performed_by"],
        stats=[("Work orders", "count(*)", "int"), ("Labour", "sum(labor_hours)", "h"), ("Cost", "sum(cost_usd)", "usd"),
               ("Avg cost", "avg(cost_usd)", "usd"), ("Parts replaced", "count(*) FILTER (WHERE part_replaced)", "int"),
               ("Effective", "100.0 * avg(CASE WHEN effective THEN 1 ELSE 0 END)", "pct")]),
    Spec("fault-predictions", "fault_prediction", "Fault prediction", [
        F("model_version", required=True), F("system_id", "system", required=True), F("asset_type", choices=ASSET_TYPES),
        F("asset_code"), F("predicted_at", "ts", required=True), F("predicted_fault_code", required=True, ref="fault"),
        F("probability", "num", lo=0, hi=1), F("top3"), F("episode_id", ref="episode"),
        F("actual_fault_code", ref="fault"), F("is_correct", "bool"), F("note")],
        key=["prediction_id"], conflict=["model_version", "system_id", "asset_code", "predicted_at"],
        generated="prediction_id", date_col="predicted_at",
        filters=["system_id", "model_version", "predicted_fault_code", "is_correct"], search=["asset_code", "top3"],
        check=_prediction_check,
        stats=[("Predictions", "count(*)", "int"),
               ("Accuracy", "100.0 * avg(CASE WHEN is_correct THEN 1 ELSE 0 END) FILTER (WHERE is_correct IS NOT NULL)", "pct"),
               ("Avg probability", "avg(probability)", "3"), ("Linked to an episode", "count(episode_id)", "int")]),
]}

_meta = MetaData(schema=SCHEMA)
_tables: dict[str, Table] = {}


def _t(name: str) -> Table:
    if name not in _tables:
        _tables[name] = Table(name, _meta, autoload_with=engine)
    return _tables[name]


def _spec(endpoint: str) -> Spec:
    s = SPECS.get(endpoint)
    if not s:
        raise HTTPException(status_code=404, detail=f"Unknown fault table '{endpoint}'")
    return s


# ---------------------------------------------------------------- lookups / references


def _systems(db: Session) -> dict[str, int]:
    return {n: i for i, n in db.execute(text("SELECT battery_system_id, system_name FROM battery_master.battery_system"))}


def _refs(db: Session) -> dict[str, set]:
    return {"fault": {r[0] for r in db.execute(text("SELECT fault_code FROM battery_master.fault_catalog"))},
            "episode": {r[0] for r in db.execute(text("SELECT episode_id FROM battery_master.fault_episode"))},
            "alarm": {r[0] for r in db.execute(text("SELECT alarm_id FROM battery_telemetry.alarm_event"))}}


@router.get("/lookups")
def lookups(db: Session = Depends(get_db)):
    """Systems, fault classes, episodes, model versions and the allowed values of every enum column."""
    return {
        "systems": [{"id": i, "code": n} for i, n in db.execute(text(
            "SELECT battery_system_id, system_name FROM battery_master.battery_system ORDER BY system_name"))],
        "faults": [{"code": c, "label": f"{c} · {n}", "subsystem": s} for c, n, s in db.execute(text(
            "SELECT fault_code, fault_name, subsystem FROM battery_master.fault_catalog ORDER BY fault_code"))],
        "episodes": [{"code": e, "label": f"{e} · {f}"} for e, f in db.execute(text(
            "SELECT episode_id, fault_code FROM battery_master.fault_episode ORDER BY episode_id"))],
        "model_versions": [r[0] for r in db.execute(text(
            "SELECT DISTINCT model_version FROM battery_master.fault_prediction ORDER BY 1"))],
        "categories": [r[0] for r in db.execute(text("SELECT DISTINCT category FROM battery_master.fault_catalog ORDER BY 1"))],
        "subsystems": list(SUBSYSTEMS), "signal_kinds": list(SIGNAL_KINDS), "operators": list(OPERATORS),
        "detection_methods": list(DETECTION_METHODS), "roles": list(ROLES), "action_types": list(ACTION_TYPES),
        "asset_types": list(ASSET_TYPES), "severities": list(SEVERITIES), "booleans": [True, False],
    }


# ---------------------------------------------------------------- values


def _convert(f: F, value: Any, systems: dict[str, int], warnings: list[str]) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if f.kind == "ts":
        return _ts(value)
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "t", "yes", "y", "1"):
            return True
        if s in ("false", "f", "no", "n", "0"):
            return False
        raise ValueError(f"'{value}' is not true / false")
    if f.kind == "system":
        if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
            sid = int(value)
            if sid not in systems.values():
                raise ValueError(f"system {sid} does not exist")
            return sid
        code = str(value).strip()
        if code not in systems and code in LEGACY_SYSTEMS:
            mapped = LEGACY_SYSTEMS[code]
            msg = f"system_code {code} (retired bess_system) mapped to {mapped}"
            if msg not in warnings:
                warnings.append(msg)
            code = mapped
        if code not in systems:
            raise ValueError(f"'{code}' is not a known battery system")
        return systems[code]
    if f.kind in ("int", "num"):
        try:
            num = float(str(value).strip())
        except ValueError:
            raise ValueError(f"'{value}' is not a number")
        if f.kind == "int":
            if num != int(num):
                raise ValueError(f"'{value}' is not a whole number")
            num = int(num)
        if f.lo is not None and num < f.lo:
            raise ValueError(f"{num} is below {f.lo}")
        if f.hi is not None and num > f.hi:
            raise ValueError(f"{num} is above {f.hi}")
        if f.choices and num not in f.choices:
            raise ValueError(f"{num} is not one of {', '.join(map(str, f.choices))}")
        return num
    s = str(value).strip()
    if f.choices:
        match = next((c for c in f.choices if str(c).lower() == s.lower()), None)
        if match is None:
            raise ValueError(f"'{s}' is not one of {', '.join(map(str, f.choices))}")
        return match
    return s


def _validate(spec: Spec, raw: dict, systems: dict[str, int], refs: dict[str, set], warnings: list[str],
              partial: bool = False) -> tuple[dict, list[str]]:
    """Convert and check one row; partial = an edit (only the given fields, keys excluded)."""
    rec, errs = {}, []
    for f in spec.fields:
        if partial and f.name not in raw:
            continue
        try:
            rec[f.name] = _convert(f, raw.get(f.name), systems, warnings)
        except ValueError as exc:
            errs.append(f"{f.name}: {exc}")
            continue
        if f.required and rec[f.name] is None:
            errs.append(f"{f.name}: missing")
        elif f.ref and rec[f.name] is not None and rec[f.name] not in refs[f.ref]:
            what = {"fault": "fault code (add it to the fault catalog first)", "episode": "episode (load the episodes first)",
                    "alarm": "alarm (Telemetry → Alarm events)"}[f.ref]
            errs.append(f"{f.name}: '{rec[f.name]}' is not a known {what}")
    if not errs and spec.check and not partial:
        e, w = spec.check(rec)
        errs += e
        warnings += [x for x in w if x not in warnings]
    return rec, errs


def _out(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, datetime):
            out[k] = v.astimezone(PLANT_TZ).isoformat()
        else:
            out[k] = v
    return out


def _fmt(v, kind: str) -> Optional[str]:
    if v is None:
        return None
    f = float(v)
    return {"int": f"{int(f):,}", "2": f"{f:,.2f}", "3": f"{f:,.3f}", "min": f"{f:,.0f} min", "kwh": f"{f:,.1f} kWh",
            "h": f"{f:,.1f} h", "usd": f"{f:,.2f} USD", "pct": f"{f:.1f} %"}.get(kind, f"{f:,.2f}")


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc.orig).splitlines()[0])


def _key_filter(spec: Spec, t: Table, key: str):
    parts = key.split("/")
    if len(parts) != len(spec.key):
        raise HTTPException(status_code=400, detail=f"The key of a {spec.title.lower()} is {' / '.join(spec.key)}")
    conds = []
    for name, value in zip(spec.key, parts):
        col = t.c[name]
        conds.append(col == (int(value) if name in ("signature_id", "prediction_id") else value))
    return and_(*conds)


# ---------------------------------------------------------------- CRUD


def _select(spec: Spec, t: Table):
    sel = select(t)
    joins = t
    if "system_id" in t.c:
        bs = _t("battery_system")
        joins = joins.outerjoin(bs, bs.c.battery_system_id == t.c.system_id)
        sel = select(t, bs.c.system_name.label("system_code"))
    fc_col = "fault_code" if "fault_code" in t.c and spec.table != "fault_catalog" else (
        "predicted_fault_code" if "predicted_fault_code" in t.c else None)
    if fc_col:
        fc = _t("fault_catalog").alias("fc")
        joins = joins.outerjoin(fc, fc.c.fault_code == t.c[fc_col])
        sel = sel.add_columns(fc.c.fault_name.label("fault_name"), fc.c.subsystem.label("fault_subsystem"))
    return sel.select_from(joins)


@router.get("/{endpoint}")
def list_rows(endpoint: str, start: Optional[date] = None, end: Optional[date] = None, q: Optional[str] = None,
              order: str = "asc", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=2000),
              system_id: Optional[int] = None, fault_code: Optional[str] = None, subsystem: Optional[str] = None,
              category: Optional[str] = None, signal_kind: Optional[str] = None, asset_type: Optional[str] = None,
              severity_level: Optional[int] = None, episode_id: Optional[str] = None, role: Optional[str] = None,
              action_type: Optional[str] = None, model_version: Optional[str] = None,
              predicted_fault_code: Optional[str] = None, is_correct: Optional[bool] = None, db: Session = Depends(get_db)):
    """Rows with the table's filters, a plant-time date range on its date column, a text search and the summary stats."""
    spec = _spec(endpoint)
    t = _t(spec.table)
    given = {"system_id": system_id, "fault_code": fault_code, "subsystem": subsystem, "category": category,
             "signal_kind": signal_kind, "asset_type": asset_type, "severity_level": severity_level,
             "episode_id": episode_id, "role": role, "action_type": action_type, "model_version": model_version,
             "predicted_fault_code": predicted_fault_code, "is_correct": is_correct}
    conds = [t.c[k] == v for k, v in given.items() if v is not None and k in spec.filters]
    if spec.date_col and start:
        conds.append(t.c[spec.date_col] >= datetime.combine(start, time(), PLANT_TZ))
    if spec.date_col and end:
        conds.append(t.c[spec.date_col] < datetime.combine(end + timedelta(days=1), time(), PLANT_TZ))
    if q and spec.search:
        like = f"%{q.strip()}%"
        conds.append(or_(*[t.c[c].ilike(like) for c in spec.search]))
    where = and_(*conds) if conds else None
    agg_q = select(*[literal_column(expr) for _, expr, _ in spec.stats]).select_from(t)
    if where is not None:
        agg_q = agg_q.where(where)
    agg = db.execute(agg_q).one()
    total_q = select(func.count()).select_from(t)
    if where is not None:
        total_q = total_q.where(where)
    total = db.execute(total_q).scalar()
    sel = _select(spec, t)
    if where is not None:
        sel = sel.where(where)
    order_cols = [t.c[spec.date_col]] if spec.date_col else []
    order_cols += [t.c[k] for k in spec.key]
    sel = sel.order_by(*[(c.desc() if order == "desc" else c.asc()) for c in order_cols])
    rows = db.execute(sel.offset((page - 1) * page_size).limit(page_size)).mappings().all()
    stats = [{"label": lbl, "value": _fmt(v, kind), "warn": False} for (lbl, _, kind), v in zip(spec.stats, agg)]
    return {"items": [_out(dict(r)) for r in rows], "total": total, "page": page, "page_size": page_size, "stats": stats}


@router.post("/{endpoint}", status_code=201)
def add_row(endpoint: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    spec = _spec(endpoint)
    t = _t(spec.table)
    warnings: list[str] = []
    rec, errs = _validate(spec, payload, _systems(db), _refs(db), warnings)
    if errs:
        raise HTTPException(status_code=422, detail="; ".join(errs))
    res = db.execute(t.insert().values(**rec).returning(*[t.c[k] for k in spec.key])).one()
    _commit(db)
    key = "/".join(str(v) for v in res)
    return _get_one(spec, t, db, key)


def _get_one(spec: Spec, t: Table, db: Session, key: str) -> dict:
    row = db.execute(_select(spec, t).where(_key_filter(spec, t, key))).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{spec.title} {key} does not exist")
    return _out(dict(row))


@router.put("/{endpoint}/{key:path}")
def update_row(endpoint: str, key: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Edit the non-key fields of a row."""
    spec = _spec(endpoint)
    t = _t(spec.table)
    current = _get_one(spec, t, db, key)
    fixed = set(spec.key) | ({spec.generated} if spec.generated else set())
    merged = {f.name: payload.get(f.name, current.get(f.name)) for f in spec.fields}
    for k in spec.key:
        if k in merged:
            merged[k] = current.get(k)
    warnings: list[str] = []
    rec, errs = _validate(spec, merged, _systems(db), _refs(db), warnings)
    if errs:
        raise HTTPException(status_code=422, detail="; ".join(errs))
    values = {k: v for k, v in rec.items() if k not in fixed}
    db.execute(t.update().where(_key_filter(spec, t, key)).values(**values))
    _commit(db)
    return _get_one(spec, t, db, key)


@router.delete("/{endpoint}/{key:path}", status_code=204)
def delete_row(endpoint: str, key: str, db: Session = Depends(get_db)):
    spec = _spec(endpoint)
    t = _t(spec.table)
    n = db.execute(t.delete().where(_key_filter(spec, t, key))).rowcount
    if not n:
        raise HTTPException(status_code=404, detail=f"{spec.title} {key} does not exist")
    _commit(db)
    return None


@router.post("/{endpoint}/bulk")
async def bulk_load(endpoint: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load the table's .csv / .xlsx; a row whose natural key exists is updated, a new one inserted. Problem rows are
    reported with their file row number and skipped."""
    spec = _spec(endpoint)
    t = _t(spec.table)
    content = await file.read()
    name = (file.filename or "upload").lower()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        if name.endswith((".xlsx", ".xlsm")):
            headers, raw_rows = _read_xlsx(content)
        elif name.endswith(".csv"):
            headers, raw_rows = _read_csv(content)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Please upload a .csv or .xlsx file.")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    if len(raw_rows) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"File has {len(raw_rows)} rows, above the {MAX_ROWS} row limit.")
    norm = [h.strip().lower() for h in headers]
    idx = {h: i for i, h in enumerate(norm) if h}
    where: dict[str, Optional[int]] = {}
    for f in spec.fields:
        names = (f.name,) + f.headers + (("system_code", "system", "system_name") if f.kind == "system" else ())
        where[f.name] = next((idx[h] for h in names if h in idx), None)
    missing = [f.name if f.kind != "system" else "system_code" for f in spec.fields if f.required and where[f.name] is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required column(s): {', '.join(missing)}")
    used = {norm[i] for i in where.values() if i is not None}
    ignored = [h for h, n in zip(headers, norm) if n and n not in used and n != spec.generated]

    systems, refs = _systems(db), _refs(db)
    errors, warnings, valid = [], [], {}
    for i, raw in enumerate(raw_rows):
        row = {f.name: (raw[where[f.name]] if where[f.name] is not None and where[f.name] < len(raw) else None)
               for f in spec.fields}
        rec, errs = _validate(spec, row, systems, refs, warnings)
        if errs:
            errors.append({"row": i + 2, "errors": errs})
            continue
        valid[tuple(rec.get(c) for c in spec.conflict)] = rec
    rows = list(valid.values())
    inserted = updated = 0
    update_cols = [f.name for f in spec.fields if f.name not in spec.conflict]
    for s in range(0, len(rows), 1000):
        stmt = pg_insert(t).values(rows[s:s + 1000])
        stmt = (stmt.on_conflict_do_update(index_elements=spec.conflict,
                                           set_={c: getattr(stmt.excluded, c) for c in update_cols})
                if update_cols else stmt.on_conflict_do_nothing(index_elements=spec.conflict))
        for r in db.execute(stmt.returning(literal_column("(xmax = 0)").label("ins"))):
            if r.ins:
                inserted += 1
            else:
                updated += 1
    _commit(db)
    n_err = len(errors)
    if ignored:
        errors.insert(0, {"row": 1, "errors": [f"Ignored unknown column(s): {', '.join(ignored)}"]})
    ts = [r[spec.date_col] for r in rows if spec.date_col and r.get(spec.date_col)]
    return {"filename": file.filename, "total_rows": len(raw_rows), "valid_rows": len(rows), "inserted": inserted,
            "updated": updated, "error_count": n_err, "errors": errors[:200], "warnings": warnings[:20],
            "first_ts": min(ts).isoformat() if ts else None, "last_ts": max(ts).isoformat() if ts else None}
