"""Static master data: turn bess_static_data.json into one CSV per master table and load them through the
master-data bulk loaders (POST /api/master-bulk/<entity>).

JSON                                   CSV (entity)            key (source_uuid)   parent column
tenant                                 tenant.csv              tenant_id           -
sites[]                                site.csv                site_id             tenant_uuid (ownership)
sites[].battery_system                 battery_system.csv      unit_id             site_uuid
sites[].battery_system.container       battery_container.csv   container_id        battery_system_uuid
sites[].battery_system.packs[]         battery_pack.csv        pack_id             container_uuid
sites[].battery_system.packs[].modules module.csv              module_id           pack_uuid
sites[].battery_system.pcs             pcs.csv                 pcs_id              battery_system_uuid
sites[].battery_system.ems             ems.csv                 ems_id              battery_system_uuid
sites[].battery_system.hvac            hvac.csv                hvac_id             battery_system_uuid

Values the JSON doesn't have are derived (see MAPPING.md):
  site_code            from the site name, upper case with dashes ("Bhuj BESS Site" -> BHUJ-BESS-SITE)
  site rated MW / MWh  its battery system's rated kW / kWh / 1000
  series_cells         cells per module x modules per pack (104 x 16 = 1664); parallel_cells = number of packs
  nominal_dc_voltage   the packs' nominal voltage
  pcs rated AC voltage the site's grid voltage (kV x 1000)
  codes                <system serial>-PCS-01 / -EMS-01 / -HVAC-01; pack number <container number>-PACK-<nn>
  tenant phone / email from its primary contact
The CSVs are loaded parents first; the loaders insert new records and update known ones (by source_uuid),
so loading the same file again changes nothing.
"""
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

# the bulk APIs are deny-by-default: authenticate as the batch service account (see bess_service_auth.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bess_service_auth import auth_headers  # noqa: E402


DEFAULT_API = "http://127.0.0.1:8000"  # 127.0.0.1, not localhost: localhost costs ~2 s per call (IPv6 first)

SUCCESS, PARTIAL, FAILED, API_DOWN = "SUCCESS", "PARTIAL", "FAILED", "API_DOWN"


class StaticDataError(Exception):
    """The JSON can't be used."""


@dataclass(frozen=True)
class Feed:
    entity: str  # /api/master-bulk/<entity>
    csv_name: str
    label: str
    columns: tuple[str, ...]


FEEDS: tuple[Feed, ...] = (
    Feed("tenant", "tenant.csv", "Tenant", (
        "source_uuid", "name", "legal_name", "tenant_type", "address_line1", "address_line2", "city", "state_province",
        "postal_code", "country", "phone", "email", "status")),
    Feed("site", "site.csv", "Site", (
        "source_uuid", "tenant_uuid", "ownership_pct", "is_primary_owner", "site_code", "site_name", "latitude",
        "longitude", "address", "state", "rated_power_mw", "rated_energy_mwh", "commission_date", "timezone",
        "grid_voltage_kv")),
    Feed("battery_system", "battery_system.csv", "Battery system", (
        "source_uuid", "site_uuid", "system_name", "manufacturer", "model", "rated_power_mw", "rated_energy_mwh",
        "nominal_dc_voltage", "chemistry_code", "series_cells", "parallel_cells", "commissioned_on")),
    Feed("battery_container", "battery_container.csv", "Container", (
        "source_uuid", "battery_system_uuid", "container_number", "installation_date", "container_type", "ip_rating",
        "fire_suppression")),
    Feed("battery_pack", "battery_pack.csv", "Pack", (
        "source_uuid", "container_uuid", "pack_number", "nominal_voltage", "nominal_capacity_ah", "module_count")),
    Feed("battery_module", "module.csv", "Module", (
        "source_uuid", "pack_uuid", "serial_number", "chemistry", "nominal_voltage", "capacity_ah", "manufacture_date",
        "installation_date", "cell_count", "soh_pct")),
    Feed("pcs", "pcs.csv", "PCS", (
        "source_uuid", "battery_system_uuid", "pcs_code", "manufacturer", "model", "rated_power_kw",
        "rated_ac_voltage_v", "efficiency_pct", "grid_mode", "commissioned_on")),
    Feed("ems_controller", "ems.csv", "EMS", (
        "source_uuid", "battery_system_uuid", "ems_code", "manufacturer", "model", "firmware_version", "control_mode")),
    Feed("hvac_unit", "hvac.csv", "HVAC", (
        "source_uuid", "battery_system_uuid", "hvac_code", "manufacturer", "model", "hvac_type", "cooling_capacity_kw",
        "status")),
)


# ---------------------------------------------------------------- JSON -> rows


def _need(obj: Any, key: str, where: str) -> Any:
    if not isinstance(obj, dict) or obj.get(key) in (None, ""):
        raise StaticDataError(f"{where}: '{key}' is missing")
    return obj[key]


def _mw(kw: Any) -> Optional[float]:
    return None if kw is None else round(float(kw) / 1000, 4)


def site_code(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")


def build_rows(data: dict) -> tuple[dict[str, list[dict]], list[str]]:
    """Rows per entity, and warnings about the data (e.g. counts that don't add up)."""
    rows: dict[str, list[dict]] = {f.entity: [] for f in FEEDS}
    warnings: list[str] = []
    tenant = _need(data, "tenant", "file")
    sites = _need(data, "sites", "file")
    if not isinstance(sites, list) or not sites:
        raise StaticDataError("file: 'sites' must be a non-empty list")

    contacts = tenant.get("contacts") or []
    primary = next((c for c in contacts if c.get("is_primary")), contacts[0] if contacts else {})
    rows["tenant"].append({
        "source_uuid": _need(tenant, "tenant_id", "tenant"), "name": _need(tenant, "name", "tenant"),
        **{k: tenant.get(k) for k in ("legal_name", "tenant_type", "address_line1", "address_line2", "city",
                                      "state_province", "postal_code", "country", "status")},
        "phone": primary.get("phone"), "email": primary.get("email"),
    })

    codes: dict[str, str] = {}
    for i, site in enumerate(sites, start=1):
        where = f"sites[{i}] ({site.get('name', '?')})"
        name = _need(site, "name", where)
        bs = _need(site, "battery_system", where)
        packs = bs.get("packs") or []
        owner = site.get("ownership") or {}
        code = site_code(name)
        if code in codes:
            raise StaticDataError(f"{where}: site code {code} is the same as for {codes[code]}")
        codes[code] = name
        if owner.get("tenant_id") and owner["tenant_id"] != tenant.get("tenant_id"):
            warnings.append(f"{name}: owner {owner['tenant_id']} is not the tenant in this file")
        rows["site"].append({
            "source_uuid": _need(site, "site_id", where), "tenant_uuid": owner.get("tenant_id"),
            "ownership_pct": owner.get("ownership_pct"), "is_primary_owner": owner.get("is_primary_owner"),
            "site_code": code, "site_name": name, "latitude": site.get("latitude"), "longitude": site.get("longitude"),
            "address": ", ".join(str(site[k]) for k in ("city", "state_province", "country") if site.get(k)),
            "state": site.get("state_province"), "rated_power_mw": _mw(bs.get("rated_power_kw")),
            "rated_energy_mwh": _mw(bs.get("rated_energy_kwh")), "commission_date": site.get("commissioning_date"),
            "timezone": site.get("timezone"), "grid_voltage_kv": site.get("grid_voltage_kv"),
        })

        bwhere = f"{where}.battery_system"
        unit, serial = _need(bs, "unit_id", bwhere), _need(bs, "serial_number", bwhere)
        modules_per_pack = {len(p.get("modules") or []) for p in packs}
        cells = {m.get("cell_count") for p in packs for m in p.get("modules") or []}
        pack_volts = {p.get("nominal_voltage_v") for p in packs}
        if not packs:
            warnings.append(f"{name}: the battery system has no packs; series/parallel cells can't be derived")
        if len(modules_per_pack) > 1 or len(cells) > 1 or len(pack_volts) > 1:
            warnings.append(f"{name}: packs differ (modules per pack {sorted(modules_per_pack)}, cells per module "
                            f"{sorted(c for c in cells if c)}, pack V {sorted(v for v in pack_volts if v)}); "
                            "series cells use the first pack")
        first = packs[0] if packs else {}
        first_modules = first.get("modules") or []
        series = (first_modules[0].get("cell_count") or 0) * len(first_modules) if first_modules else None
        rows["battery_system"].append({
            "source_uuid": unit, "site_uuid": site["site_id"], "system_name": serial,
            "manufacturer": bs.get("manufacturer"), "model": bs.get("model"),
            "rated_power_mw": _mw(bs.get("rated_power_kw")), "rated_energy_mwh": _mw(bs.get("rated_energy_kwh")),
            "nominal_dc_voltage": first.get("nominal_voltage_v"), "chemistry_code": _need(bs, "chemistry", bwhere),
            "series_cells": series or None, "parallel_cells": len(packs) or None, "commissioned_on": bs.get("install_date"),
        })

        container = _need(bs, "container", bwhere)
        rows["battery_container"].append({
            "source_uuid": _need(container, "container_id", f"{bwhere}.container"), "battery_system_uuid": unit,
            "container_number": container.get("container_number"), "installation_date": bs.get("install_date"),
            "container_type": container.get("type"), "ip_rating": container.get("ip_rating"),
            "fire_suppression": container.get("fire_suppression"),
        })
        for p in packs:
            pwhere = f"{bwhere}.packs[{p.get('pack_number', '?')}]"
            modules = p.get("modules") or []
            if p.get("module_count") is not None and p["module_count"] != len(modules):
                warnings.append(f"{name} pack {p.get('pack_number')}: module_count {p['module_count']} but "
                                f"{len(modules)} modules listed")
            number = p.get("pack_number")
            rows["battery_pack"].append({
                "source_uuid": _need(p, "pack_id", pwhere), "container_uuid": container["container_id"],
                "pack_number": f"{container.get('container_number') or serial}-PACK-{int(number):02d}"
                if isinstance(number, (int, float)) or str(number).isdigit() else number,
                "nominal_voltage": p.get("nominal_voltage_v"),
                "nominal_capacity_ah": modules[0].get("capacity_ah") if modules else None,
                "module_count": p.get("module_count", len(modules)),
            })
            for m in modules:
                rows["battery_module"].append({
                    "source_uuid": _need(m, "module_id", f"{pwhere}.modules[{m.get('module_number', '?')}]"),
                    "pack_uuid": p["pack_id"], "serial_number": m.get("serial_number"), "chemistry": bs.get("chemistry"),
                    "nominal_voltage": m.get("nominal_voltage_v"), "capacity_ah": m.get("capacity_ah"),
                    "manufacture_date": m.get("manufacture_date"), "installation_date": bs.get("install_date"),
                    "cell_count": m.get("cell_count"), "soh_pct": m.get("soh_pct"),
                })

        pcs = _need(bs, "pcs", bwhere)
        kv = site.get("grid_voltage_kv")
        if kv is None:
            warnings.append(f"{name}: no grid_voltage_kv, so the PCS rated AC voltage is empty (the row will fail)")
        rows["pcs"].append({
            "source_uuid": _need(pcs, "pcs_id", f"{bwhere}.pcs"), "battery_system_uuid": unit,
            "pcs_code": f"{serial}-PCS-01", "manufacturer": pcs.get("manufacturer"), "model": pcs.get("model"),
            "rated_power_kw": pcs.get("rated_power_kw"), "rated_ac_voltage_v": None if kv is None else float(kv) * 1000,
            "efficiency_pct": pcs.get("efficiency_pct"), "grid_mode": pcs.get("mode"), "commissioned_on": bs.get("install_date"),
        })
        ems = _need(bs, "ems", bwhere)
        rows["ems_controller"].append({
            "source_uuid": _need(ems, "ems_id", f"{bwhere}.ems"), "battery_system_uuid": unit, "ems_code": f"{serial}-EMS-01",
            **{k: ems.get(k) for k in ("manufacturer", "model", "firmware_version", "control_mode")},
        })
        hvac = _need(bs, "hvac", bwhere)
        rows["hvac_unit"].append({
            "source_uuid": _need(hvac, "hvac_id", f"{bwhere}.hvac"), "battery_system_uuid": unit,
            "hvac_code": f"{serial}-HVAC-01", "manufacturer": hvac.get("manufacturer"), "model": hvac.get("model"),
            "hvac_type": hvac.get("type"), "cooling_capacity_kw": hvac.get("cooling_capacity_kw"),
            "status": hvac.get("status"),
        })
    return rows, warnings


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_csvs(rows: dict[str, list[dict]], out_dir: Path) -> dict[str, Path]:
    import csv
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for feed in FEEDS:
        path = out_dir / feed.csv_name
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(feed.columns)
            for row in rows[feed.entity]:
                writer.writerow([csv_value(row.get(c)) for c in feed.columns])
        paths[feed.entity] = path
    return paths


# ---------------------------------------------------------------- API


def post_file(api: str, endpoint: str, path: Path) -> tuple[int, dict]:
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: text/csv\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(api + endpoint, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **auth_headers(api)})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {"detail": exc.reason}


def api_is_up(api: str) -> bool:
    try:
        with urllib.request.urlopen(api + "/api/health", timeout=10) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def run(source: Path, api: str = DEFAULT_API, out_dir: Optional[Path] = None, csv_only: bool = False,
        log: Callable[[str], None] = print) -> tuple[str, dict]:
    """Write the CSVs for one JSON file into out_dir and (unless csv_only) load them. Returns (outcome, report)."""
    out_dir = out_dir or source.with_suffix("")
    report: dict[str, Any] = {"source": source.name, "api": api, "feeds": [], "warnings": [], "error": None}
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        rows, report["warnings"] = build_rows(data)
    except (ValueError, StaticDataError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}" if isinstance(exc, ValueError) else str(exc)
        return FAILED, report
    report["counts"] = {f.entity: len(rows[f.entity]) for f in FEEDS}
    if not csv_only and not api_is_up(api):
        report["error"] = f"The backend at {api} isn't answering"
        return API_DOWN, report
    paths = write_csvs(rows, out_dir)
    log(f"CSVs written to {out_dir}")
    if csv_only:
        report["feeds"] = [{"entity": f.entity, "label": f.label, "csv": f.csv_name, "rows": len(rows[f.entity])}
                           for f in FEEDS]
        return SUCCESS, report

    for feed in FEEDS:
        entry: dict[str, Any] = {"feed": feed.label, "entity": feed.entity, "label": feed.label, "csv": feed.csv_name,
                                 "endpoint": f"/api/master-bulk/{feed.entity}", "rows": len(rows[feed.entity])}
        status, body = post_file(api, entry["endpoint"], paths[feed.entity])
        entry["http"] = status
        if status == 200:
            entry.update(inserted=body.get("inserted", 0), updated=body.get("updated", 0),
                         skipped=body.get("total_rows", 0) - body.get("inserted", 0) - body.get("updated", 0),
                         errors=[f"row {e['row']}: {'; '.join(e['errors'])}" for e in body.get("errors", [])][:50])
        else:
            detail = body.get("detail") if isinstance(body, dict) else body
            entry.update(skipped=entry["rows"], errors=[str(detail)])
        log(f"{feed.label:15} {entry['rows']:4} rows -> HTTP {status}"
            + (f": {entry.get('inserted', 0)} inserted, {entry.get('updated', 0)} updated, {entry.get('skipped', 0)} skipped"
               if status == 200 else f": {entry['errors'][0]}"))
        report["feeds"].append(entry)

    loaded = [f for f in report["feeds"] if f["http"] == 200]
    clean = all(f["http"] == 200 and not f.get("skipped") for f in report["feeds"])
    outcome = SUCCESS if clean else PARTIAL if loaded and any(f.get("inserted") or f.get("updated") for f in loaded) else FAILED
    if outcome != SUCCESS and not report["error"]:
        bad = [f"{f['label']} ({f.get('skipped', f['rows'])} skipped)" for f in report["feeds"]
               if f["http"] != 200 or f.get("skipped")]
        report["error"] = "Not everything loaded: " + ", ".join(bad)
    return outcome, report
