"""Load one BESS plant snapshot (bess_snapshot.json) through the telemetry bulk-load APIs.

    python load_snapshot.py <snapshot.json> [--api http://localhost:8000] [--out DIR] [--csv-only]

Steps:
  1. read and check the snapshot (structure, timestamp, consistency between feeds);
  2. write one CSV per feed - BMS, module, PCS, EMS, HVAC, alarms, dispatch events - in the column
     layout that feed's bulk-load API reads (the mapping is the FEEDS table below; see MAPPING.md);
  3. post each CSV to its bulk-load endpoint and report inserted / updated / skipped rows.

Re-running the same snapshot is safe: every bulk load updates a row that already exists (same asset and
timestamp / id) instead of adding a second one. Alarms and dispatch events that already exist are updated
only in the columns the snapshot has, so values the snapshot doesn't carry (e.g. a dispatch's revenue) stay.

Alarm and dispatch IDs: an ID that the database already uses for a different start time is treated as a new
record and gets the next free ID (the original ID goes in the dispatch's note and the load report). A record
this loader already stored for the same event (same EMS + start, or same alarm code + start) is reused, so a
re-run doesn't add it twice. A newer dispatch ends the EMS's running one (the dispatch API closes it).

Exit code: 0 all rows loaded, 1 snapshot or file problem (nothing loaded), 2 some rows skipped or a load failed.
"""
import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# the bulk APIs are deny-by-default: authenticate as the batch service account (see bess_service_auth.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bess_service_auth import auth_headers, open_authed  # noqa: E402
from bess_common.errors import EXIT_FAILED, EXIT_OK, EXIT_PARTIAL, FileFormatError, run_main  # noqa: E402


HERE = Path(__file__).resolve().parent
# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and each request waits ~2 s
DEFAULT_API = "http://127.0.0.1:8000"
MISSING = object()  # a path the snapshot doesn't have (as opposed to an explicit null)


# ---------------------------------------------------------------- mapping: snapshot JSON -> CSV -> API


def get(obj: Any, path: str) -> Any:
    """Value at a dotted path ('bms.system.cell_voltage.avg_v'), or MISSING."""
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return MISSING
        obj = obj[part]
    return obj


@dataclass
class Feed:
    name: str
    csv_name: str
    endpoint: str
    # rows of the feed: each is a context dict the column paths are read from
    rows: Callable[[dict], list[dict]]
    # CSV header -> path in the row context ('@ts' = the snapshot timestamp)
    columns: list[tuple[str, str]]
    # multipart form fields the endpoint needs besides the file (value = path in the snapshot)
    form: dict[str, str] = field(default_factory=dict)
    # columns the API accepts that the snapshot has no data for (left empty; reported)
    not_in_snapshot: list[str] = field(default_factory=list)
    # columns sent only when some row has a value (e.g. a note the loader adds)
    optional: list[tuple[str, str]] = field(default_factory=list)


def _system(s: dict) -> dict:
    return s["site"]["bess_system"]


FEEDS: list[Feed] = [
    Feed(
        name="BMS", csv_name="bms_telemetry.csv", endpoint="/api/system-telemetry/bulk",
        rows=lambda s: [{**_system(s)["bms"]["system"], "system_code": _system(s).get("system_code")}],
        columns=[
            ("system_name", "system_code"), ("timestamp", "@ts"), ("mode", "mode"),
            ("soc_%", "soc_pct"), ("soh_%", "soh_pct"),
            ("pack_voltage_v", "pack_voltage_v"), ("pack_current_a", "pack_current_a"),
            ("power_kw", "power_kw"), ("c_rate", "c_rate"),
            ("cell_v_avg_v", "cell_voltage.avg_v"), ("cell_v_min_v", "cell_voltage.min_v"),
            ("cell_v_max_v", "cell_voltage.max_v"), ("cell_v_delta_mv", "cell_voltage.delta_mv"),
            ("cell_temp_avg_c", "cell_temperature.avg_c"), ("cell_temp_min_c", "cell_temperature.min_c"),
            ("cell_temp_max_c", "cell_temperature.max_c"),
            ("coolant_temp_c", "coolant_temp_c"), ("ambient_temp_c", "ambient_temp_c"),
            ("insulation_res_kohm", "insulation_res_kohm"),
            ("cum_charge_kwh", "cumulative.charge_kwh"), ("cum_discharge_kwh", "cumulative.discharge_kwh"),
            ("equiv_full_cycles", "cumulative.equiv_full_cycles"),
            ("contactor_status", "contactor_state"), ("alarm_level", "alarm_level"),
        ],
        not_in_snapshot=["avail_charge_kw", "avail_discharge_kw"],
        # current sensing / SOC estimation / rest (system_telemetry since 2026-10): sent when the snapshot carries
        # them, so older snapshot files load as before
        optional=[
            ("measured_current_a", "current_sensing.measured_current_a"),
            ("current_sensor_offset_a", "current_sensing.sensor_offset_a"),
            ("soc_coulomb_%", "soc_estimation.soc_coulomb_pct"),
            ("soc_battery_telemetry_%", "soc_estimation.soc_battery_telemetry_pct"),
            ("usable_capacity_ah", "soc_estimation.usable_capacity_ah"),
            ("coulombic_efficiency", "soc_estimation.coulombic_efficiency"),
            ("at_rest", "rest.at_rest"),
            ("rest_duration_min", "rest.rest_duration_min"),
            ("ocv_rested_v", "rest.ocv_rested_v"),
        ],
    ),
    Feed(
        name="Module", csv_name="module_telemetry.csv", endpoint="/api/module-telemetry/bulk",
        rows=lambda s: [m for pack in _system(s)["bms"].get("packs", []) for m in pack.get("modules", [])],
        columns=[
            ("module_code", "module_code"), ("ts", "@ts"),
            ("cell_v_avg_v", "cell_voltage.avg_v"), ("cell_v_min_v", "cell_voltage.min_v"),
            ("cell_v_max_v", "cell_voltage.max_v"),
            ("cell_temp_max_c", "cell_temperature.max_c"), ("cell_temp_min_c", "cell_temperature.min_c"),
            ("imbalance_mv", "cell_voltage.imbalance_mv"), ("balancing_active", "balancing_active"),
        ],
    ),
    Feed(
        name="PCS", csv_name="pcs_telemetry.csv", endpoint="/api/pcs-telemetry/bulk",
        rows=lambda s: [_system(s)["pcs"]],
        columns=[
            ("pcs_code", "pcs_code"), ("ts", "@ts"), ("mode_code", "mode"), ("grid_service", "grid_service"),
            ("ac_active_power_kw", "ac.active_power_kw"), ("ac_reactive_power_kvar", "ac.reactive_power_kvar"),
            ("ac_apparent_power_kva", "ac.apparent_power_kva"), ("power_factor", "ac.power_factor"),
            ("ac_frequency_hz", "ac.frequency_hz"),
            ("ac_voltage_ab_v", "ac.voltage_ll_v.ab"), ("ac_voltage_bc_v", "ac.voltage_ll_v.bc"),
            ("ac_voltage_ca_v", "ac.voltage_ll_v.ca"),
            ("ac_current_a_a", "ac.current_a.a"), ("ac_current_b_a", "ac.current_a.b"), ("ac_current_c_a", "ac.current_a.c"),
            ("thd_voltage_pct", "ac.thd_pct.voltage"), ("thd_current_pct", "ac.thd_pct.current"),
            ("dc_voltage_v", "dc.voltage_v"), ("dc_current_a", "dc.current_a"), ("dc_power_kw", "dc.power_kw"),
            ("efficiency_pct", "efficiency_pct"),
            ("igbt_temp_c", "thermal.igbt_c"), ("heatsink_temp_c", "thermal.heatsink_c"),
            ("inlet_coolant_temp_c", "thermal.inlet_coolant_c"),
            ("breaker_state", "breaker_state"), ("alarm_level", "alarm_level"),
        ],
        not_in_snapshot=["ambient_temp_c", "avail_charge_kw", "avail_discharge_kw",
                         "ac_energy_import_kwh", "ac_energy_export_kwh"],
    ),
    Feed(
        name="EMS", csv_name="ems_telemetry.csv", endpoint="/api/ems-telemetry/bulk",
        rows=lambda s: [s["site"]["ems"]],
        form={"ems_code": "site.ems.ems_code"},
        columns=[
            ("ts", "@ts"), ("dispatch_mode", "dispatch_mode"), ("grid_service", "grid_service"),
            ("market_price_mwh", "market_price_mwh"), ("p_setpoint_kw", "setpoint.p_setpoint_kw"),
            ("poi_active_power_kw", "poi.active_power_kw"), ("poi_reactive_power_kvar", "poi.reactive_power_kvar"),
            ("tracking_error_kw", "setpoint.tracking_error_kw"), ("grid_frequency_hz", "poi.frequency_hz"),
            ("poi_voltage_kv", "poi.voltage_kv"), ("agc_signal", "setpoint.agc_signal"),
            ("plant_soc_pct", "soc.plant_soc_pct"), ("target_soc_pct", "soc.target_soc_pct"),
            ("avail_charge_kw", "availability.avail_charge_kw"), ("avail_discharge_kw", "availability.avail_discharge_kw"),
            ("aux_load_kw", "aux_load_kw"), ("plant_available", "availability.plant_available"),
            ("alarm_level", "alarm_level"),
        ],
        not_in_snapshot=["avail_charge_energy_kwh", "avail_discharge_energy_kwh", "aux_load_pct",
                         "cum_import_kwh", "cum_export_kwh", "revenue_cum_usd", "units_online"],
    ),
    Feed(
        name="HVAC", csv_name="hvac_telemetry.csv", endpoint="/api/hvac-telemetry/bulk",
        rows=lambda s: [_system(s)["hvac"]],
        form={"hvac_code": "site.bess_system.hvac.hvac_code"},
        columns=[
            ("ts", "@ts"), ("cooling_mode", "cooling_mode"),
            ("coolant_setpoint_c", "coolant.setpoint_c"), ("coolant_supply_temp_c", "coolant.supply_c"),
            ("coolant_return_temp_c", "coolant.return_c"), ("coolant_delta_t_c", "coolant.delta_t_c"),
            ("coolant_flow_lpm", "coolant.flow_lpm"),
            ("compressor_speed_pct", "mechanical.compressor_speed_pct"), ("condenser_fan_pct", "mechanical.condenser_fan_pct"),
            ("refrig_suction_bar", "mechanical.refrig_suction_bar"), ("refrig_discharge_bar", "mechanical.refrig_discharge_bar"),
            ("battery_heat_load_kw", "thermal_balance.battery_heat_load_kw"),
            ("cooling_capacity_kw", "thermal_balance.cooling_capacity_kw"),
            ("heat_rejected_kw", "thermal_balance.heat_rejected_kw"), ("cop", "thermal_balance.cop"),
            ("hvac_power_kw", "hvac_power_kw"),
            ("enclosure_temp_c", "enclosure.temp_c"), ("enclosure_humidity_pct", "enclosure.humidity_pct"),
            ("alarm_level", "alarm_level"), ("alarm_flags", "alarm_flags"),
        ],
        not_in_snapshot=["ambient_temp_c", "filter_dp_pa", "cum_energy_kwh", "compressor_runtime_h", "units_running"],
    ),
    Feed(
        name="Dispatch events", csv_name="dispatch_events.csv", endpoint="/api/dispatch-events/bulk",
        rows=lambda s: [{**d, "ems_code": s["site"]["ems"].get("ems_code")}] if (d := s["site"].get("active_dispatch")) else [],
        columns=[
            ("dispatch_id", "dispatch_id"), ("ems_code", "ems_code"), ("command_code", "command_code"),
            ("dispatch_mode", "dispatch_mode"), ("grid_service", "grid_service"), ("source", "source"),
            ("issued_at", "issued_at"), ("effective_from", "effective_from"), ("effective_to", "effective_to"),
            ("p_setpoint_kw", "p_setpoint_kw"), ("target_soc_pct", "target_soc_pct"),
            ("ramp_rate_kw_s", "ramp_rate_kw_s"), ("status", "status"),
        ],
        # set by the loader when the snapshot's dispatch_id was already used for another dispatch
        optional=[("note", "note")],
        # kept as stored when the dispatch already exists; empty (0 for energy) for a new one
        not_in_snapshot=["soc_start_pct", "soc_end_pct", "import_kwh", "export_kwh", "avg_price_mwh",
                         "revenue_usd", "accepted"],
    ),
    Feed(
        name="Alarms", csv_name="alarm_events.csv", endpoint="/api/alarm-events/bulk",
        rows=lambda s: list(s["site"].get("active_alarms") or []),
        columns=[
            ("alarm_id", "alarm_id"), ("source_system", "source_system"), ("asset_type", "asset_type"),
            ("asset_code", "asset_code"), ("alarm_code", "alarm_code"),
            ("severity", "severity"), ("severity_level", "severity_level"),
            ("start_time", "start_time"), ("end_time", "end_time"),
            ("trigger_value", "trigger_value"), ("threshold_value", "threshold_value"), ("unit", "unit"),
            ("status", "status"),
        ],
        # alarm_type, description and probable_cause come from the alarm catalog, so they aren't sent
        not_in_snapshot=["acknowledged_by", "acknowledged_at"],
    ),
]


# ---------------------------------------------------------------- snapshot checks


class SnapshotError(FileFormatError):
    code = "SNAPSHOT_INVALID"


def check_snapshot(snap: dict) -> tuple[datetime, list[str]]:
    """Structural problems raise SnapshotError; returns (timestamp, warnings)."""
    for path in ("meta.timestamp", "site.ems.ems_code", "site.bess_system.system_code", "site.bess_system.bms.system",
                 "site.bess_system.pcs.pcs_code", "site.bess_system.hvac.hvac_code"):
        if get(snap, path) in (MISSING, None, ""):
            raise SnapshotError(f"'{path}' is missing")
    try:
        ts = datetime.fromisoformat(str(snap["meta"]["timestamp"]))
    except ValueError:
        raise SnapshotError(f"meta.timestamp '{snap['meta']['timestamp']}' is not an ISO date/time")
    if ts.tzinfo is not None:
        raise SnapshotError("meta.timestamp has a time zone; the loaders take plant local time without one")

    warnings = []
    interval = get(snap, "meta.interval_minutes")
    if interval not in (MISSING, None) and (ts.minute % int(interval) or ts.second):
        warnings.append(f"timestamp {ts:%H:%M:%S} is not on a {interval}-minute boundary")
    for pack in _system(snap)["bms"].get("packs", []):
        count, found = pack.get("module_count"), len(pack.get("modules", []))
        if count is not None and count != found:
            warnings.append(f"{pack.get('pack_code')}: module_count {count} but {found} modules listed")
    # the same measurement reported by two systems should agree
    for a, b, tol in (("site.bess_system.bms.system.power_kw", "site.bess_system.pcs.dc.power_kw", 5.0),
                      ("site.bess_system.bms.system.soc_pct", "site.ems.soc.plant_soc_pct", 1.0),
                      ("site.bess_system.bms.system.pack_voltage_v", "site.bess_system.pcs.dc.voltage_v", 5.0)):
        va, vb = get(snap, a), get(snap, b)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and abs(va - vb) > tol:
            warnings.append(f"{a} = {va} but {b} = {vb}")
    # dispatch / alarms are events: they may start earlier, but a date far from the snapshot is suspicious
    events = [("active_dispatch", get(snap, "site.active_dispatch.effective_from"))]
    events += [(f"alarm {a.get('alarm_id')}", a.get("start_time")) for a in get(snap, "site.active_alarms") or []]
    for label, when in events:
        if when in (MISSING, None):
            continue
        try:
            gap = abs((datetime.fromisoformat(str(when)) - ts).total_seconds()) / 86400
        except ValueError:
            continue  # the API reports the bad value
        if gap > 1:
            warnings.append(f"{label} starts {when}, {gap:.0f} days from the snapshot time {ts:%Y-%m-%d %H:%M}")
    return ts, warnings


# ---------------------------------------------------------------- CSV


def csv_value(value: Any) -> str:
    if value is MISSING or value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_csv(feed: Feed, snap: dict, out_dir: Path) -> tuple[Optional[Path], int, list[str]]:
    """Write the feed's CSV. Returns (path or None when there are no rows, row count, paths the snapshot lacks)."""
    rows = feed.rows(snap)
    if not rows:
        return None, 0, []
    ts = snap["meta"]["timestamp"]
    columns = feed.columns + [(h, p) for h, p in feed.optional if any(get(r, p) not in (MISSING, None) for r in rows)]
    absent = sorted({p for r in rows for _, p in feed.columns if p != "@ts" and get(r, p) is MISSING})
    path = out_dir / feed.csv_name
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([header for header, _ in columns])
        for r in rows:
            writer.writerow([csv_value(ts if p == "@ts" else get(r, p)) for _, p in columns])
    return path, len(rows), absent


# ---------------------------------------------------------------- API


def post_file(api: str, endpoint: str, path: Path, form: dict[str, str]) -> tuple[int, dict]:
    """multipart/form-data POST of one CSV (plus form fields); returns (HTTP status, JSON body)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in form.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: text/csv\r\n\r\n".encode() + path.read_bytes() + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        api + endpoint, data=b"".join(parts), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **auth_headers(api)},
    )
    try:
        with open_authed(api, request, 120) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {"detail": exc.reason}


def get_json(api: str, path: str) -> tuple[int, Any]:
    try:
        with open_authed(api, urllib.request.Request(api + path), 30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None


def same_minute(a: Optional[str], b: Optional[str]) -> bool:
    """Compare plant-local times to the minute ('2026-09-28T18:20:00+05:30' vs '2026-09-28T18:20:00')."""
    return bool(a and b) and str(a)[:16] == str(b)[:16]


class IdAllocator:
    """Next free IDs (DSP-00358, DSP-00359, ...) - asks the API once, then counts on locally."""

    def __init__(self, api: str, endpoint: str, key: str):
        self.api, self.endpoint, self.key, self.next = api, endpoint, key, None

    def take(self) -> str:
        if self.next is None:
            status, body = get_json(self.api, self.endpoint + "/next-id")
            if status != 200:
                raise RuntimeError(f"{self.endpoint}/next-id answered HTTP {status}")
            self.next = body[self.key]
        current = self.next
        prefix, number = current.rsplit("-", 1)
        self.next = f"{prefix}-{int(number) + 1:0{len(number)}d}"
        return current


def resolve_ids(snap: dict, api: str) -> list[str]:
    """Give snapshot dispatches/alarms whose ID is already used for another start time a free ID."""
    changes = []
    base = "/api/dispatch-events"
    dispatch = get(snap, "site.active_dispatch")
    if isinstance(dispatch, dict) and dispatch.get("dispatch_id"):
        orig, start = dispatch["dispatch_id"], dispatch.get("effective_from")
        status, stored = get_json(api, f"{base}/{urllib.parse.quote(orig)}")
        if status == 200 and not same_minute(stored.get("effective_from"), start):
            # loaded before from this snapshot? one EMS runs one dispatch at a time, so EMS + start identifies it
            day = str(start)[:10]
            ems = get(snap, "site.ems.ems_code")
            _, page = get_json(api, f"{base}?start={day}&end={day}&page_size=500")
            match = next((d for d in (page or {}).get("items", [])
                          if same_minute(d.get("effective_from"), start) and d.get("ems_code") == ems), None)
            new = match["dispatch_id"] if match else IdAllocator(api, base, "dispatch_id").take()
            dispatch["dispatch_id"] = new
            dispatch["note"] = (f"Source dispatch ID {orig} (already used for the dispatch from "
                                f"{str(stored['effective_from'])[:16].replace('T', ' ')}); loaded as {new}")
            changes.append(f"dispatch {orig} -> {new}" + (" (loaded before)" if match else " (new ID)"))

    base = "/api/alarm-events"
    allocator = IdAllocator(api, base, "alarm_id")
    for alarm in get(snap, "site.active_alarms") or []:
        orig, start = alarm.get("alarm_id"), alarm.get("start_time")
        if not orig:
            continue
        status, stored = get_json(api, f"{base}/{urllib.parse.quote(orig)}")
        if status != 200 or same_minute(stored.get("start_time"), start):
            continue
        # loaded before from this snapshot? same alarm code, source and start
        day = str(start)[:10]
        _, page = get_json(api, f"{base}?start={day}&end={day}&q={urllib.parse.quote(str(alarm.get('alarm_code')))}&page_size=500")
        match = next((a for a in (page or {}).get("items", [])
                      if same_minute(a.get("start_time"), start) and a.get("alarm_code") == alarm.get("alarm_code")
                      and a.get("source") == str(alarm.get("source_system", "")).upper()), None)
        new = match["alarm_id"] if match else allocator.take()
        alarm["alarm_id"] = new
        changes.append(f"alarm {orig} -> {new}" + (" (loaded before)" if match else " (new ID)")
                       + f"; {orig} is already the alarm from {str(stored['start_time'])[:16].replace('T', ' ')}")
    return changes


def api_is_up(api: str) -> bool:
    try:
        with urllib.request.urlopen(api + "/api/health", timeout=10) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def row_errors(body: dict) -> list[str]:
    out = []
    for e in body.get("errors") or []:
        if isinstance(e, dict):
            ident = e.get("dispatch_id") or e.get("alarm_id") or e.get("row")
            out.append(f"row {e.get('row')} ({ident}): {'; '.join(e.get('errors') or [])}")
        else:
            out.append(str(e))
    return out


# ---------------------------------------------------------------- main


# run() outcomes
SUCCESS, FAILED, PARTIAL, API_DOWN = "SUCCESS", "FAILED", "PARTIAL", "API_DOWN"


def run(snapshot: Path, api: str = DEFAULT_API, out_dir: Optional[Path] = None, csv_only: bool = False,
        log: Callable[[str], None] = print) -> tuple[str, dict]:
    """Check the snapshot, write the CSVs and (unless csv_only) load them.

    Returns (outcome, report). Outcome: SUCCESS; PARTIAL (some rows skipped or a feed failed); FAILED (the
    snapshot can't be used - nothing loaded); API_DOWN (backend not answering - nothing loaded, try again).
    The report is also written to <out_dir>/load_report.json once the CSV folder exists.
    """
    api = api.rstrip("/")
    report: dict = {"snapshot": str(snapshot), "api": api, "interval": None, "warnings": [], "id_changes": [],
                    "feeds": [], "csv_dir": None, "error": None}

    def finish(outcome: str, error: Optional[str] = None, code: Optional[str] = None) -> tuple[str, dict]:
        report["status"] = outcome
        if code:
            report["error_code"] = code  # battery_raw.batchlog.error_code
        if error:
            report["error"] = error
            log(f"ERROR: {error}")
        if report["csv_dir"]:
            (Path(report["csv_dir"]) / "load_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            log(f"\nReport -> {Path(report['csv_dir']) / 'load_report.json'}")
        return outcome, report

    # 1. read and check
    try:
        snap = json.loads(snapshot.read_text(encoding="utf-8"))
        ts, warnings = check_snapshot(snap)
    except FileNotFoundError:
        return finish(FAILED, f"{snapshot.name} not found", "FILE_NOT_FOUND")
    except (json.JSONDecodeError, UnicodeDecodeError, SnapshotError, KeyError, TypeError) as exc:
        return finish(FAILED, f"{snapshot.name} can't be used: {exc}", "SNAPSHOT_INVALID")
    report["interval"], report["warnings"] = ts.isoformat(), warnings
    log(f"Snapshot {snapshot.name} | interval {ts:%Y-%m-%d %H:%M} | site {get(snap, 'site.site_code')}")
    for w in warnings:
        log(f"  WARNING: {w}")

    # IDs the database already uses for another event get a free ID (needs the API)
    if api_is_up(api):
        try:
            report["id_changes"] = resolve_ids(snap, api)
        except (RuntimeError, urllib.error.URLError, KeyError, TypeError) as exc:
            return finish(FAILED, f"couldn't check alarm/dispatch IDs: {exc}", "ID_CHECK_FAILED")
        for change in report["id_changes"]:
            log(f"  ID: {change}")
    elif not csv_only:
        return finish(API_DOWN, f"the backend at {api} isn't answering (/api/health)", "API_UNAVAILABLE")
    else:
        log(f"  NOTE: {api} not reachable - alarm/dispatch IDs not checked against the database")

    # 2. CSVs
    out_dir = out_dir or HERE / "output" / ts.strftime("%Y%m%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    report["csv_dir"] = str(out_dir)
    built = []
    log(f"\nCSV files -> {out_dir}")
    for feed in FEEDS:
        try:
            path, count, absent = build_csv(feed, snap, out_dir)
        except (KeyError, TypeError) as exc:
            return finish(FAILED, f"{feed.name}: snapshot section missing ({exc})", "SNAPSHOT_INVALID")
        log(f"  {feed.name:16} {count:3} row(s)  {path.name if path else '(nothing to load)'}")
        if absent:
            log(f"  {'':16} missing in snapshot, left empty: {', '.join(absent)}")
        built.append((feed, path, count))
    if csv_only:
        log("\n--csv-only: nothing loaded.")
        return finish(SUCCESS)

    # 3. load
    log(f"\nLoading through {api}")
    outcome = SUCCESS
    for feed, path, count in built:
        if path is None:
            report["feeds"].append({"feed": feed.name, "rows": 0, "result": "nothing to load"})
            continue
        form = {k: str(get(snap, p)) for k, p in feed.form.items()}
        try:
            http, body = post_file(api, feed.endpoint, path, form)
        except (urllib.error.URLError, OSError) as exc:
            http, body = 0, {"detail": f"request failed: {exc}"}
        entry = {"feed": feed.name, "csv": path.name, "endpoint": feed.endpoint, "rows": count, "http": http,
                 "not_in_snapshot": feed.not_in_snapshot}
        if http != 200:
            outcome = PARTIAL
            entry["error"] = body.get("detail") if isinstance(body, dict) else str(body)
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                entry["error_code"] = body["error"].get("code")
            log(f"  {feed.name:16} FAILED  HTTP {http}: {entry['error']}")
        else:
            inserted, updated = body.get("inserted", 0), body.get("updated", 0)
            skipped = body.get("error_count", body.get("skipped", 0)) or 0
            entry.update(inserted=inserted, updated=updated, skipped=skipped, errors=row_errors(body))
            log(f"  {feed.name:16} {'OK     ' if not skipped else 'PARTIAL'} {inserted} inserted, {updated} updated, {skipped} skipped")
            for line in entry["errors"]:
                log(f"  {'':16}   {line}")
            for line in body.get("closed_dispatches") or []:
                entry.setdefault("closed_dispatches", []).append(line)
                log(f"  {'':16}   running dispatch {line}")
            if skipped:
                outcome = PARTIAL
        report["feeds"].append(entry)
    return finish(outcome)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Load a BESS snapshot JSON through the telemetry bulk-load APIs.")
    parser.add_argument("snapshot", type=Path, help="path to the snapshot JSON (e.g. bess_snapshot.json)")
    parser.add_argument("--api", default=DEFAULT_API, help=f"backend base URL (default {DEFAULT_API})")
    parser.add_argument("--out", type=Path, help="folder for the CSVs (default output/<snapshot time>)")
    parser.add_argument("--csv-only", action="store_true", help="write the CSVs but don't load them")
    args = parser.parse_args(argv)
    outcome, _ = run(args.snapshot, args.api, args.out, args.csv_only)
    if outcome in (SUCCESS, PARTIAL):
        print("Done." if outcome == SUCCESS else "Finished with problems (see above).")
    return {SUCCESS: EXIT_OK, PARTIAL: EXIT_PARTIAL}.get(outcome, EXIT_FAILED)


if __name__ == "__main__":
    sys.exit(run_main("snapshot_load", main))
