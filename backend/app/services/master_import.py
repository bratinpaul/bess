"""Bulk load of master data (CSV / Excel) - tenants, sites, battery systems, containers, packs, modules, PCS,
EMS controllers and HVAC units.

Every file has one row per record, a `source_uuid` column (the record's UUID in the source system) and, except
for tenants, the parent's source UUID (e.g. `site_uuid` on a battery system). A row whose source_uuid is known
updates that record; any other row inserts one. So loading a file twice changes nothing the second time, and
a record created in the app (no source_uuid) is never touched.

An update changes only the columns the file has (a blank cell clears an optional value); required values
must be filled on every row. Parents are looked up by their source UUID, so load parents first:
tenant -> site -> battery_system -> battery_container -> battery_pack -> battery_module, and pcs /
ems_controller / hvac_unit after battery_system. Rows that don't validate are reported and skipped; every
valid row is loaded in its own savepoint (a unique-key clash rejects that row only) and gets its asset
hierarchy node.

Sites can also carry their owner: tenant_uuid, ownership_pct and is_primary_owner set that tenant's row in
tenant_site (other owners of the site are left as they are).
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.hierarchy import sync_node
from app.services.telemetry_import import (
    TelemetryImportError,
    _parse_decimal,
    _parse_int,
    _parse_text,
    _read_csv,
    _read_xlsx,
)

MAX_ROWS = 50_000


class MasterImportError(Exception):
    """File-level problem: unknown entity, bad format, missing columns."""


# ---------------------------------------------------------------- value parsers


def _uuid(value) -> Optional[UUID]:
    text = _parse_text(value)
    if text is None:
        return None
    try:
        return UUID(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a valid UUID")


def _date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _parse_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise ValueError(f"'{text}' is not a date (YYYY-MM-DD)")


def _bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = _parse_text(value)
    if text is None:
        return None
    low = text.lower()
    if low in ("true", "t", "yes", "y", "1"):
        return True
    if low in ("false", "f", "no", "n", "0"):
        return False
    raise ValueError(f"'{text}' is not true/false")


PARSERS: dict[str, Callable[[Any], Any]] = {
    "text": _parse_text, "decimal": _parse_decimal, "int": _parse_int, "date": _date, "bool": _bool, "uuid": _uuid,
}


@dataclass(frozen=True)
class Col:
    name: str  # CSV header = model attribute
    kind: str = "text"
    required: bool = False  # must have a value on every row
    default: Any = None  # used on insert when the file has no value (and not required)
    min: Optional[Decimal] = None
    max: Optional[Decimal] = None
    choices: Optional[tuple] = None


@dataclass(frozen=True)
class Parent:
    column: str  # CSV column with the parent's source UUID
    model: type
    id_attr: str  # the parent's id column
    attr: str  # column on this record holding the parent id
    label: str
    required: bool = True


@dataclass(frozen=True)
class Entity:
    key: str  # URL segment and asset type
    label: str
    model: type
    id_attr: str
    columns: tuple[Col, ...]
    parent: Optional[Parent] = None
    # checks across columns of one row: returns error messages
    check: Optional[Callable[[dict], list[str]]] = None
    extra_columns: tuple[Col, ...] = field(default_factory=tuple)  # parsed but not model attributes


def _between(v, lo, hi):
    return v is None or (lo is None or v >= lo) and (hi is None or v <= hi)


def _pcs_check(v: dict) -> list[str]:
    lo, hi = v.get("dc_voltage_min_v"), v.get("dc_voltage_max_v")
    return ["dc_voltage_min_v must not exceed dc_voltage_max_v"] if lo is not None and hi is not None and lo > hi else []


D = Decimal
PCT = dict(min=D(0), max=D(100))

ENTITIES: dict[str, Entity] = {e.key: e for e in (
    Entity("tenant", "Tenant", models.Tenant, "tenant_id", (
        Col("name", required=True), Col("legal_name"),
        Col("tenant_type", choices=("Utility", "IPP", "C&I", "Developer", "Aggregator / VPP", "Government", "Other")),
        Col("address_line1"), Col("address_line2"), Col("city"), Col("state_province"), Col("postal_code"),
        Col("country"), Col("phone"), Col("email"), Col("status", default="active", choices=models.tenant.TENANT_STATUSES),
    )),
    Entity("site", "Site", models.Site, "site_id", (
        Col("site_code", required=True), Col("site_name", required=True),
        Col("latitude", "decimal", min=D(-90), max=D(90)), Col("longitude", "decimal", min=D(-180), max=D(180)),
        Col("address"), Col("rated_power_mw", "decimal", min=D(0)), Col("rated_energy_mwh", "decimal", min=D(0)),
        Col("commission_date", "date"), Col("timezone", default="UTC"), Col("grid_operator"), Col("state"),
        Col("grid_voltage_kv", "decimal", min=D(0)),
    ), extra_columns=(Col("tenant_uuid", "uuid"), Col("ownership_pct", "decimal", min=D(0), max=D(100)),
                      Col("is_primary_owner", "bool"))),
    Entity("battery_system", "Battery system", models.BatterySystem, "battery_system_id", (
        Col("system_name", required=True), Col("manufacturer"), Col("model"),
        Col("rated_power_mw", "decimal", min=D(0)), Col("rated_energy_mwh", "decimal", min=D(0)),
        Col("nominal_dc_voltage", "decimal", min=D(0)), Col("status"), Col("chemistry_code", required=True),
        Col("series_cells", "int", required=True, min=D(1)), Col("parallel_cells", "int", required=True, min=D(1)),
        Col("commissioned_on", "date"), Col("bms_firmware"),
    ), Parent("site_uuid", models.Site, "site_id", "site_id", "site")),
    Entity("battery_container", "Container", models.BatteryContainer, "container_id", (
        Col("container_number"), Col("manufacturer"), Col("installation_date", "date"), Col("status"),
        Col("container_type"), Col("ip_rating"), Col("fire_suppression"),
    ), Parent("battery_system_uuid", models.BatterySystem, "battery_system_id", "battery_system_id", "battery system")),
    Entity("battery_pack", "Pack", models.BatteryPack, "pack_id", (
        Col("pack_number"), Col("nominal_voltage", "decimal", min=D(0)), Col("nominal_capacity_ah", "decimal", min=D(0)),
        Col("status"), Col("module_count", "int", min=D(0)),
    ), Parent("container_uuid", models.BatteryContainer, "container_id", "container_id", "container")),
    Entity("battery_module", "Module", models.BatteryModule, "module_id", (
        Col("serial_number"), Col("chemistry"), Col("nominal_voltage", "decimal", min=D(0)),
        Col("capacity_ah", "decimal", min=D(0)), Col("manufacture_date", "date"), Col("installation_date", "date"),
        Col("status"), Col("cell_count", "int", min=D(0)), Col("soh_pct", "decimal", **PCT),
    ), Parent("pack_uuid", models.BatteryPack, "pack_id", "pack_id", "pack")),
    Entity("pcs", "PCS", models.Pcs, "pcs_id", (
        Col("pcs_code", required=True), Col("manufacturer"), Col("model"), Col("serial_number"), Col("topology"),
        Col("cooling"), Col("rated_power_kw", "decimal", required=True, min=D("0.01")),
        Col("rated_apparent_kva", "decimal", min=D(0)), Col("max_charge_kw", "decimal", min=D(0)),
        Col("max_discharge_kw", "decimal", min=D(0)), Col("rated_ac_voltage_v", "decimal", required=True, min=D(0)),
        Col("ac_frequency_hz", "decimal", default=D("50.0"), min=D(1)), Col("phases", "int", default=3, choices=(1, 3)),
        Col("dc_voltage_min_v", "decimal", min=D(0)), Col("dc_voltage_max_v", "decimal", min=D(0)),
        Col("dc_voltage_nom_v", "decimal", min=D(0)), Col("min_power_factor", "decimal", min=D(0), max=D(1)),
        Col("grid_code"), Col("firmware"), Col("commissioned_on", "date"), Col("efficiency_pct", "decimal", **PCT),
        Col("grid_mode"),
    ), Parent("battery_system_uuid", models.BatterySystem, "battery_system_id", "system_id", "battery system"),
        check=_pcs_check),
    Entity("ems_controller", "EMS controller", models.EmsController, "ems_id", (
        Col("ems_code", required=True), Col("manufacturer"), Col("model"), Col("firmware_version"), Col("control_mode"),
    ), Parent("battery_system_uuid", models.BatterySystem, "battery_system_id", "battery_system_id", "battery system")),
    Entity("hvac_unit", "HVAC unit", models.HvacUnit, "hvac_id", (
        Col("hvac_code", required=True), Col("manufacturer"), Col("model"), Col("hvac_type"),
        Col("cooling_capacity_kw", "decimal", min=D(0)), Col("status"),
    ), Parent("battery_system_uuid", models.BatterySystem, "battery_system_id", "battery_system_id", "battery system")),
)}
LOAD_ORDER = tuple(ENTITIES)


def describe(entity: Entity) -> dict:
    """Columns of an entity's file (for the API's help and the loaders)."""
    cols = [{"name": "source_uuid", "type": "uuid", "required": True}]
    if entity.parent:
        cols.append({"name": entity.parent.column, "type": "uuid", "required": entity.parent.required,
                     "help": f"source_uuid of the {entity.parent.label}"})
    for c in entity.columns + entity.extra_columns:
        cols.append({"name": c.name, "type": c.kind, "required": c.required,
                     **({"choices": list(c.choices)} if c.choices else {}),
                     **({"default": str(c.default)} if c.default is not None else {})})
    return {"key": entity.key, "label": entity.label, "parent": entity.parent.label if entity.parent else None,
            "columns": cols}


# ---------------------------------------------------------------- import


@dataclass
class ImportResult:
    total_rows: int = 0
    valid_rows: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[dict] = field(default_factory=list)  # {row, errors: [...]}


def _read(filename: str, content: bytes) -> tuple[list[str], list[list]]:
    try:
        if filename.lower().endswith((".xlsx", ".xlsm")):
            return _read_xlsx(content)
        if filename.lower().endswith(".csv"):
            return _read_csv(content)
    except TelemetryImportError as exc:
        raise MasterImportError(str(exc)) from exc
    raise MasterImportError("Upload a .csv or .xlsx file")


def import_file(db: Session, entity_key: str, filename: str, content: bytes) -> ImportResult:
    if entity_key not in ENTITIES:
        raise MasterImportError(f"Unknown master data '{entity_key}' (one of: {', '.join(LOAD_ORDER)})")
    entity = ENTITIES[entity_key]
    headers, rows = _read(filename, content)
    names = [h.strip().lower() for h in headers]
    if len(rows) > MAX_ROWS:
        raise MasterImportError(f"The file has {len(rows)} rows; at most {MAX_ROWS} can be loaded at once")
    known = {"source_uuid"} | {c.name for c in entity.columns + entity.extra_columns}
    if entity.parent:
        known.add(entity.parent.column)
    required = {"source_uuid"} | {c.name for c in entity.columns if c.required}
    if entity.parent and entity.parent.required:
        required.add(entity.parent.column)
    missing = sorted(required - set(names))
    if missing:
        raise MasterImportError(f"Missing column(s): {', '.join(missing)}")
    unknown = sorted(set(n for n in names if n) - known)
    if unknown:
        raise MasterImportError(f"Unknown column(s) for {entity.label}: {', '.join(unknown)}")
    if len(set(n for n in names if n)) != len([n for n in names if n]):
        raise MasterImportError("A column appears more than once")

    index = {n: i for i, n in enumerate(names) if n}
    present = [c for c in entity.columns if c.name in index]
    extras = [c for c in entity.extra_columns if c.name in index]
    result = ImportResult(total_rows=len(rows))

    # parse and validate every row first
    parsed: list[tuple[int, UUID, Optional[UUID], dict, dict]] = []
    seen: dict[UUID, int] = {}
    for n, raw in enumerate(rows, start=2):  # row 1 is the header
        cell = lambda name: raw[index[name]] if index[name] < len(raw) else None  # noqa: E731
        errors: list[str] = []
        values, extra = {}, {}
        try:
            source = _uuid(cell("source_uuid"))
            if source is None:
                errors.append("source_uuid is required")
        except ValueError as exc:
            errors.append(f"source_uuid: {exc}")
            source = None
        parent_uuid = None
        if entity.parent and entity.parent.column in index:
            try:
                parent_uuid = _uuid(cell(entity.parent.column))
            except ValueError as exc:
                errors.append(f"{entity.parent.column}: {exc}")
            if parent_uuid is None and entity.parent.required and not errors:
                errors.append(f"{entity.parent.column} is required")
        for col, target in [(c, values) for c in present] + [(c, extra) for c in extras]:
            try:
                v = PARSERS[col.kind](cell(col.name))
            except ValueError as exc:
                errors.append(f"{col.name}: {exc}")
                continue
            if v is None and col.required:
                errors.append(f"{col.name} is required")
            elif v is not None and col.kind in ("decimal", "int") and not _between(v, col.min, col.max):
                errors.append(f"{col.name} must be between {col.min if col.min is not None else '-∞'} and "
                              f"{col.max if col.max is not None else '∞'}")
            elif v is not None and col.choices and v not in col.choices:
                errors.append(f"{col.name} must be one of: {', '.join(map(str, col.choices))}")
            target[col.name] = v
        if entity.check and not errors:
            errors += entity.check(values)
        if source is not None and source in seen:
            errors.append(f"source_uuid {source} is also on row {seen[source]}")
        if errors:
            result.errors.append({"row": n, "errors": errors})
            continue
        seen[source] = n
        parsed.append((n, source, parent_uuid, values, extra))
    result.valid_rows = len(parsed)
    if not parsed:
        return result

    # look-ups: existing records by source UUID, parents by source UUID, chemistry codes
    model = entity.model
    existing = {r.source_uuid: r for r in db.query(model).filter(model.source_uuid.in_([p[1] for p in parsed]))}
    parents: dict[UUID, int] = {}
    if entity.parent:
        wanted = {p[2] for p in parsed if p[2] is not None}
        pm = entity.parent.model
        parents = {u: i for u, i in db.query(pm.source_uuid, getattr(pm, entity.parent.id_attr))
                   .filter(pm.source_uuid.in_(wanted))} if wanted else {}
    tenants: dict[UUID, int] = {}
    if entity.key == "site":
        wanted = {p[4].get("tenant_uuid") for p in parsed if p[4].get("tenant_uuid")}
        tenants = {u: i for u, i in db.query(models.Tenant.source_uuid, models.Tenant.tenant_id)
                   .filter(models.Tenant.source_uuid.in_(wanted))} if wanted else {}
    chemistries = {c for (c,) in db.query(models.BatteryChemistry.chemistry_code)} if entity.key == "battery_system" else set()

    for n, source, parent_uuid, values, extra in parsed:
        errors = []
        if entity.parent and parent_uuid is not None and parent_uuid not in parents:
            errors.append(f"{entity.parent.column}: no {entity.parent.label} with source_uuid {parent_uuid} "
                          f"(load the {entity.parent.label} file first)")
        if entity.key == "battery_system" and values.get("chemistry_code") not in chemistries:
            errors.append(f"chemistry_code '{values.get('chemistry_code')}' is not in battery_chemistry "
                          f"({', '.join(sorted(chemistries))})")
        if entity.key == "site" and extra.get("tenant_uuid") and extra["tenant_uuid"] not in tenants:
            errors.append(f"tenant_uuid: no tenant with source_uuid {extra['tenant_uuid']} (load the tenant file first)")
        if errors:
            result.errors.append({"row": n, "errors": errors})
            continue

        record = existing.get(source)
        savepoint = db.begin_nested()
        try:
            if record is None:
                data = {c.name: c.default for c in entity.columns if c.default is not None}
                data.update({k: v for k, v in values.items() if v is not None or k not in data})
                record = model(source_uuid=source, **data)
                db.add(record)
                created = True
            else:
                for k, v in values.items():
                    col = next(c for c in entity.columns if c.name == k)
                    if v is None and col.default is not None:
                        continue  # a blank defaulted value keeps what is stored
                    setattr(record, k, v)
                created = False
            if entity.parent and parent_uuid is not None:
                setattr(record, entity.parent.attr, parents[parent_uuid])
            db.flush()
            record_id = getattr(record, entity.id_attr)
            if entity.key == "site" and extra.get("tenant_uuid"):
                _set_owner(db, record_id, tenants[extra["tenant_uuid"]], extra)
            sync_node(db, entity.key, record_id)
            savepoint.commit()
        except IntegrityError as exc:
            savepoint.rollback()
            existing.pop(source, None)
            result.errors.append({"row": n, "errors": [_integrity_message(exc)]})
            continue
        existing[source] = record
        if created:
            result.inserted += 1
        else:
            result.updated += 1
    return result


def _set_owner(db: Session, site_id: int, tenant_id: int, extra: dict) -> None:
    """Insert or update this tenant's ownership of the site (other owners stay)."""
    link = db.get(models.TenantSite, (tenant_id, site_id))
    primary = bool(extra.get("is_primary_owner")) if "is_primary_owner" in extra else (link.is_primary_owner if link else True)
    if primary:  # a site has one primary owner
        db.query(models.TenantSite).filter(models.TenantSite.site_id == site_id,
                                           models.TenantSite.tenant_id != tenant_id).update(
            {models.TenantSite.is_primary_owner: False}, synchronize_session=False)
    if link is None:
        link = models.TenantSite(tenant_id=tenant_id, site_id=site_id)
        db.add(link)
    if "ownership_pct" in extra:
        link.ownership_pct = extra["ownership_pct"]
    link.is_primary_owner = primary
    db.flush()


def _integrity_message(exc: IntegrityError) -> str:
    detail = str(getattr(exc.orig, "diag", None) and exc.orig.diag.message_detail or exc.orig).strip()
    return f"Conflicts with an existing record: {detail}" if detail else "Conflicts with an existing record"
