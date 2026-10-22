"""Snapshot simulator: write plant snapshot files (the bess_snapshot.json format) for every 5-minute interval
between a start and an end time, into the realtime inbox (input/realtime/<YYYY-MM-DD-HH-MM-SS>.json), where
the realtime batch loads them.

The values are sampled from the telemetry already stored:
  * every simulated day replays one historical source day that has all four feeds (BMS, PCS, EMS, HVAC)
    complete - so within a day the SOC curve, dispatch schedule and temperatures follow a real day, and all
    feeds of one file describe the same moment. The day is picked at random among the CLOSEST_DAYS days whose
    SOC at that time of day is nearest the previous interval's, so the state carries on across the join;
  * module telemetry comes from the same source day, or (it has fewer days) from a random module day, at the
    same time of day;
  * the dispatch and alarms active at the source moment are moved to the simulated day (their windows clipped
    to that day, so consecutive days don't overlap) and keep their source IDs - the batch gives them new ones;
  * cumulative BMS counters (charge / discharge kWh, equivalent full cycles) keep increasing from the last
    stored value by the source day's own increments, instead of jumping back;
  * the BMS current-sensing / SOC-estimation / rest signals (measured current, sensor offset, coulomb-counted and
    telemetry SOC, usable Ah, coulombic efficiency, rest state, rested OCV) are replayed when the source reading has
    them, else derived interval by interval (soc_signals.py) - continuing from the last stored values.

Used by the backend API (/api/batch/simulator, the frontend's Batch -> Simulator page) and by simulate.py
(command line). Needs only a SQLAlchemy session on the Battery database.
"""
import json
import os
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from snapshot_simulator.soc_signals import SocSignals, nominal_ah

PROJECT = Path(__file__).resolve().parents[1]  # the bess project root
INBOX = PROJECT / "input" / "realtime"
ARCHIVE = INBOX / "archieve"
PLANT_TZ = timezone(timedelta(hours=5, minutes=30))  # Asia/Kolkata, no DST
INTERVAL = timedelta(minutes=5)
SLOTS_PER_DAY = 288
MAX_FILES = 7 * SLOTS_PER_DAY  # one week per run
# each simulated day replays one of the source days closest in SOC to where the previous interval ended
CLOSEST_DAYS = 3


class SimulatorError(Exception):
    """Bad input or no data to sample from."""


def _naive(dt: datetime) -> datetime:
    """Stored timestamptz -> plant local clock time without a zone (how snapshots carry time)."""
    return dt.astimezone(PLANT_TZ).replace(tzinfo=None) if dt.tzinfo else dt


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _rows(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


@dataclass
class Plant:
    """Master data of the simulated battery system and its assets."""

    system_id: int
    system_name: str
    chemistry: Optional[str]
    rated_power_kw: Optional[float]
    rated_energy_kwh: Optional[float]
    nominal_voltage_v: Optional[float]
    series_cells: Optional[int]
    parallel_cells: Optional[int]
    site_code: str
    site_name: str
    site_timezone: str
    ems_id: int
    ems_code: str
    pcs_id: int
    pcs_code: str
    hvac_id: int
    hvac_code: str
    # pack number -> [(module_id, module serial)]
    packs: dict[str, list[tuple[int, str]]] = field(default_factory=dict)


def load_plant(db: Session) -> Plant:
    system = _rows(db, """
        SELECT bs.battery_system_id, bs.system_name, bs.chemistry_code, bs.rated_power_mw, bs.rated_energy_mwh,
               bs.nominal_dc_voltage, bs.series_cells, bs.parallel_cells, s.site_code, s.site_name, s.timezone
        FROM battery_master.battery_system bs JOIN battery_master.site s ON s.site_id = bs.site_id
        WHERE EXISTS (SELECT 1 FROM battery_telemetry.system_telemetry t WHERE t.system_id = bs.battery_system_id)
        ORDER BY bs.battery_system_id LIMIT 1""")
    if not system:
        raise SimulatorError("No battery system has BMS telemetry to sample from")
    s = system[0]
    sid = s["battery_system_id"]

    def asset(sql: str, label: str) -> dict:
        found = _rows(db, sql, sid=sid)
        if not found:
            raise SimulatorError(f"{s['system_name']} has no {label} in master data")
        return found[0]

    ems = asset("SELECT ems_id, ems_code FROM battery_master.ems_controller WHERE battery_system_id = :sid ORDER BY ems_id", "EMS controller")
    pcs = asset("SELECT pcs_id, pcs_code FROM battery_master.pcs WHERE system_id = :sid ORDER BY pcs_id", "PCS")
    hvac = asset("SELECT hvac_id, hvac_code FROM battery_master.hvac_unit WHERE battery_system_id = :sid ORDER BY hvac_id", "HVAC unit")
    packs: dict[str, list[tuple[int, str]]] = {}
    for r in _rows(db, """
            SELECT p.pack_number, m.module_id, m.serial_number
            FROM battery_master.battery_module m
            JOIN battery_master.battery_pack p ON p.pack_id = m.pack_id
            JOIN battery_master.battery_container c ON c.container_id = p.container_id
            WHERE c.battery_system_id = :sid ORDER BY p.pack_number, m.module_id""", sid=sid):
        packs.setdefault(r["pack_number"], []).append((r["module_id"], r["serial_number"]))
    # natural module order: MODULE-2 before MODULE-10
    for modules in packs.values():
        modules.sort(key=lambda m: (len(m[1]), m[1]))
    mw = lambda v: float(v) * 1000 if v is not None else None  # noqa: E731
    return Plant(
        system_id=sid, system_name=s["system_name"], chemistry=s["chemistry_code"],
        rated_power_kw=mw(s["rated_power_mw"]), rated_energy_kwh=mw(s["rated_energy_mwh"]),
        nominal_voltage_v=_num(s["nominal_dc_voltage"]), series_cells=s["series_cells"],
        parallel_cells=s["parallel_cells"], site_code=s["site_code"], site_name=s["site_name"],
        site_timezone=s["timezone"] or "Asia/Kolkata",
        ems_id=ems["ems_id"], ems_code=ems["ems_code"], pcs_id=pcs["pcs_id"], pcs_code=pcs["pcs_code"],
        hvac_id=hvac["hvac_id"], hvac_code=hvac["hvac_code"], packs=packs,
    )


@dataclass
class Source:
    """Stored telemetry, keyed by plant-local timestamp."""

    bms: dict[datetime, dict]
    pcs: dict[datetime, dict]
    ems: dict[datetime, dict]
    hvac: dict[datetime, dict]
    modules: dict[datetime, dict[int, dict]]
    dispatches: list[dict]
    alarms: list[dict]
    days: list[date]         # complete in BMS, PCS, EMS and HVAC
    module_days: list[date]  # with module telemetry


def load_source(db: Session, plant: Plant, source_from: Optional[date] = None, source_to: Optional[date] = None) -> Source:
    def by_ts(sql: str, **params) -> dict[datetime, dict]:
        return {_naive(r["ts"]): r for r in _rows(db, sql, **params)}

    bms = by_ts("SELECT * FROM battery_telemetry.system_telemetry WHERE system_id = :id", id=plant.system_id)
    pcs = by_ts("SELECT * FROM battery_telemetry.pcs_telemetry WHERE pcs_id = :id", id=plant.pcs_id)
    ems = by_ts("SELECT * FROM battery_telemetry.ems_telemetry WHERE ems_id = :id", id=plant.ems_id)
    hvac = by_ts("SELECT * FROM battery_telemetry.hvac_telemetry WHERE hvac_id = :id", id=plant.hvac_id)
    module_ids = [m for modules in plant.packs.values() for m, _ in modules]
    modules: dict[datetime, dict[int, dict]] = {}
    if module_ids:
        for r in _rows(db, "SELECT * FROM battery_telemetry.module_telemetry WHERE module_id = ANY(:ids)", ids=module_ids):
            modules.setdefault(_naive(r["ts"]), {})[r["module_id"]] = r

    # a source day needs every 5-minute slot in all four feeds
    counts: dict[date, int] = {}
    for ts in bms:
        if ts in pcs and ts in ems and ts in hvac:
            counts[ts.date()] = counts.get(ts.date(), 0) + 1
    days = sorted(d for d, n in counts.items() if n >= SLOTS_PER_DAY
                  and (source_from is None or d >= source_from) and (source_to is None or d <= source_to))
    # a module day likewise needs every slot for every module
    module_counts: dict[date, int] = {}
    for ts, per_module in modules.items():
        if len(per_module) == len(module_ids):
            module_counts[ts.date()] = module_counts.get(ts.date(), 0) + 1
    module_days = sorted(d for d, n in module_counts.items() if n >= SLOTS_PER_DAY)

    dispatches = _rows(db, """SELECT * FROM battery_telemetry.dispatch_event WHERE ems_id = :id ORDER BY time""", id=plant.ems_id)
    alarms = _rows(db, """
        SELECT e.*, c.source, c.alarm_code, c.alarm_type, c.description, c.probable_cause, s.severity_name
        FROM battery_telemetry.alarm_event e
        JOIN battery_master.alarm_catalog c ON c.alarm_catalog_id = e.alarm_catalog_id
        LEFT JOIN battery_master.alarm_severity s ON s.severity_level = e.severity_level
        ORDER BY e.time""")
    for d in dispatches:
        for k in ("time", "effective_to", "issued_at"):
            d[k] = _naive(d[k]) if d[k] else None
    for a in alarms:
        for k in ("time", "end_time"):
            a[k] = _naive(a[k]) if a[k] else None
    return Source(bms, pcs, ems, hvac, modules, dispatches, alarms, days, module_days)


# ---------------------------------------------------------------- one snapshot


def _clip(start: datetime, end: Optional[datetime], day_start: datetime) -> tuple[datetime, Optional[datetime]]:
    day_end = day_start + timedelta(days=1)
    return max(start, day_start), (min(end, day_end) if end else None)


def build_snapshot(plant: Plant, src: Source, target: datetime, src_ts: datetime, module_ts: Optional[datetime],
                   cumulative: dict[str, float], source_day: date, soc: Optional[dict] = None) -> dict:
    shift = target - src_ts
    day_start = datetime.combine(target.date(), time())
    b, p, e, h = src.bms[src_ts], src.pcs[src_ts], src.ems[src_ts], src.hvac[src_ts]
    n = _num
    soc = soc or {}

    # dispatch running at the source moment, moved to the simulated day
    active_dispatch = None
    running = next((d for d in src.dispatches if d["time"] <= src_ts and (d["effective_to"] is None or d["effective_to"] > src_ts)), None)
    # a dispatch already stored for the simulated moment wins (the EMS runs one at a time): send none
    stored_now = any(d["time"] <= target and (d["effective_to"] is None or d["effective_to"] > target) for d in src.dispatches)
    if running and not stored_now:
        start, end = _clip(running["time"] + shift, running["effective_to"] + shift if running["effective_to"] else None, day_start)
        # fit between the stored dispatches around the simulated moment
        start = max([start] + [d["effective_to"] for d in src.dispatches
                               if d["effective_to"] is not None and start < d["effective_to"] <= target])
        later = [d["time"] for d in src.dispatches if target < d["time"] and (end is None or d["time"] < end)]
        if later:
            end = min(later)
        issued = min(max(running["issued_at"] + shift, day_start), start)
        active_dispatch = {
            "dispatch_id": running["dispatch_id"], "command_code": running["command_code"],
            "dispatch_mode": running["dispatch_mode"], "grid_service": running["grid_service"],
            "source": running["source"], "issued_at": issued.isoformat(), "effective_from": start.isoformat(),
            "effective_to": end.isoformat() if end else None, "p_setpoint_kw": n(running["p_setpoint_kw"]),
            "target_soc_pct": n(running["target_soc_pct"]), "ramp_rate_kw_s": n(running["ramp_rate_kw_s"]),
            "status": running["status"] if end else "Active",
        }

    active_alarms = []
    for a in src.alarms:
        if a["time"] <= src_ts and (a["end_time"] is None or a["end_time"] > src_ts):
            start, end = _clip(a["time"] + shift, a["end_time"] + shift if a["end_time"] else None, day_start)
            active_alarms.append({
                "alarm_id": a["alarm_id"], "source_system": a["source"], "asset_type": a["asset_type"],
                "asset_code": a["asset_code"], "alarm_code": a["alarm_code"], "alarm_type": a["alarm_type"],
                "severity": a["severity_name"], "severity_level": a["severity_level"],
                "description": a["description"], "probable_cause": a["probable_cause"],
                "start_time": start.isoformat(), "end_time": end.isoformat() if end else None,
                "trigger_value": n(a["trigger_value"]), "threshold_value": n(a["threshold_value"]),
                "unit": a["unit"], "status": "Cleared" if end else "Active",
            })

    packs = []
    for pack_number, modules in plant.packs.items():
        rows = src.modules.get(module_ts, {}) if module_ts else {}
        entries = []
        for module_id, serial in modules:
            m = rows.get(module_id)
            if not m:
                continue
            vmin, vmax = n(m["cell_v_min_v"]), n(m["cell_v_max_v"])
            entries.append({
                "module_code": serial,
                "cell_voltage": {"avg_v": n(m["cell_v_avg_v"]), "min_v": vmin, "max_v": vmax,
                                 "imbalance_mv": round((vmax - vmin) * 1000, 1) if vmin is not None and vmax is not None else None},
                "cell_temperature": {"max_c": n(m["cell_temp_max_c"]), "min_c": n(m["cell_temp_min_c"])},
                "balancing_active": m["balancing_active"],
            })
        packs.append({"pack_code": pack_number, "module_count": len(entries), "modules": entries})
    module_total = sum(len(m) for m in plant.packs.values())
    topology = None
    if plant.series_cells and plant.parallel_cells and module_total:
        topology = (f"{plant.series_cells * module_total}S{plant.parallel_cells}P "
                    f"({module_total} modules x {plant.series_cells}S, {plant.parallel_cells}P)")

    return {
        "meta": {
            "description": "BESS plant telemetry snapshot — single 5-minute interval, hierarchical",
            "timestamp": target.isoformat(),
            "interval_minutes": 5,
            "sign_convention": "power/current > 0 = charging / grid import; < 0 = discharging / grid export",
            "generated": f"simulator: sampled from stored telemetry of {source_day.isoformat()} "
                         f"{src_ts:%H:%M} (modules: {module_ts:%Y-%m-%d %H:%M})" if module_ts else
                         f"simulator: sampled from stored telemetry of {source_day.isoformat()} {src_ts:%H:%M}",
        },
        "site": {
            "site_code": plant.site_code,
            "name": plant.site_name,
            "timezone": plant.site_timezone,
            "ems": {
                "ems_code": plant.ems_code, "asset_type": "Site Controller",
                "dispatch_mode": e["dispatch_mode"], "grid_service": e["grid_service"],
                "market_price_mwh": n(e["market_price_mwh"]),
                "poi": {"active_power_kw": n(e["poi_active_power_kw"]), "reactive_power_kvar": n(e["poi_reactive_power_kvar"]),
                        "voltage_kv": n(e["poi_voltage_kv"]), "frequency_hz": n(e["grid_frequency_hz"])},
                "setpoint": {"p_setpoint_kw": n(e["p_setpoint_kw"]), "tracking_error_kw": n(e["tracking_error_kw"]),
                             "agc_signal": n(e["agc_signal"])},
                "soc": {"plant_soc_pct": n(e["plant_soc_pct"]), "target_soc_pct": n(e["target_soc_pct"])},
                "availability": {"avail_charge_kw": n(e["avail_charge_kw"]), "avail_discharge_kw": n(e["avail_discharge_kw"]),
                                 "plant_available": e["plant_available"]},
                "aux_load_kw": n(e["aux_load_kw"]),
                "alarm_level": e["alarm_level"],
            },
            "bess_system": {
                "system_code": plant.system_name,
                "config": {"chemistry": plant.chemistry, "rated_power_kw": plant.rated_power_kw,
                           "usable_energy_kwh": plant.rated_energy_kwh, "topology": topology,
                           "nominal_voltage_v": plant.nominal_voltage_v},
                "bms": {
                    "system": {
                        "mode": b["mode_code"], "soc_pct": n(b["soc_bms_pct"]), "soh_pct": n(b["soh_pct"]),
                        "pack_voltage_v": n(b["pack_voltage_v"]), "pack_current_a": n(b["pack_current_a"]),
                        "power_kw": n(b["power_kw"]), "c_rate": n(b["c_rate"]),
                        "cell_voltage": {"avg_v": n(b["cell_v_avg_v"]), "min_v": n(b["cell_v_min_v"]),
                                         "max_v": n(b["cell_v_max_v"]), "delta_mv": n(b["cell_v_delta_mv"])},
                        "cell_temperature": {"avg_c": n(b["cell_temp_avg_c"]), "min_c": n(b["cell_temp_min_c"]),
                                             "max_c": n(b["cell_temp_max_c"])},
                        "coolant_temp_c": n(b["coolant_temp_c"]), "ambient_temp_c": n(b["ambient_temp_c"]),
                        "insulation_res_kohm": n(b["insulation_res_kohm"]),
                        "cumulative": {"charge_kwh": cumulative["charge_kwh"], "discharge_kwh": cumulative["discharge_kwh"],
                                       "equiv_full_cycles": cumulative["equiv_full_cycles"]},
                        "contactor_state": b["contactor_state"], "alarm_level": b["alarm_level"], "alarm_flags": None,
                        "current_sensing": {"measured_current_a": n(soc.get("measured_current_a")),
                                            "sensor_offset_a": n(soc.get("current_sensor_offset_a"))},
                        "soc_estimation": {"soc_coulomb_pct": n(soc.get("soc_coulomb_pct")),
                                           "soc_battery_telemetry_pct": n(soc.get("soc_battery_telemetry_pct")),
                                           "usable_capacity_ah": n(soc.get("usable_capacity_ah")),
                                           "coulombic_efficiency": n(soc.get("coulombic_efficiency"))},
                        "rest": {"at_rest": soc.get("at_rest"), "rest_duration_min": n(soc.get("rest_duration_min")),
                                 "ocv_rested_v": n(soc.get("ocv_rested_v"))},
                    },
                    "packs": packs,
                },
                "pcs": {
                    "pcs_code": plant.pcs_code, "asset_type": "Inverter", "mode": p["mode_code"],
                    "grid_service": p["grid_service"],
                    "ac": {
                        "active_power_kw": n(p["ac_active_power_kw"]), "reactive_power_kvar": n(p["ac_reactive_power_kvar"]),
                        "apparent_power_kva": n(p["ac_apparent_power_kva"]), "power_factor": n(p["power_factor"]),
                        "frequency_hz": n(p["ac_frequency_hz"]),
                        "voltage_ll_v": {"ab": n(p["ac_voltage_ab_v"]), "bc": n(p["ac_voltage_bc_v"]), "ca": n(p["ac_voltage_ca_v"])},
                        "current_a": {"a": n(p["ac_current_a_a"]), "b": n(p["ac_current_b_a"]), "c": n(p["ac_current_c_a"])},
                        "thd_pct": {"voltage": n(p["thd_voltage_pct"]), "current": n(p["thd_current_pct"])},
                    },
                    "dc": {"voltage_v": n(p["dc_voltage_v"]), "current_a": n(p["dc_current_a"]), "power_kw": n(p["dc_power_kw"])},
                    "efficiency_pct": n(p["efficiency_pct"]),
                    "thermal": {"igbt_c": n(p["igbt_temp_c"]), "heatsink_c": n(p["heatsink_temp_c"]),
                                "inlet_coolant_c": n(p["inlet_coolant_temp_c"])},
                    "breaker_state": p["breaker_state"], "alarm_level": p["alarm_level"],
                },
                "hvac": {
                    "hvac_code": plant.hvac_code, "asset_type": "HVAC Unit", "cooling_mode": h["cooling_mode"],
                    "coolant": {"setpoint_c": n(h["coolant_setpoint_c"]), "supply_c": n(h["coolant_supply_temp_c"]),
                                "return_c": n(h["coolant_return_temp_c"]), "delta_t_c": n(h["coolant_delta_t_c"]),
                                "flow_lpm": n(h["coolant_flow_lpm"])},
                    "mechanical": {"compressor_speed_pct": n(h["compressor_speed_pct"]), "condenser_fan_pct": n(h["condenser_fan_pct"]),
                                   "refrig_suction_bar": n(h["refrig_suction_bar"]), "refrig_discharge_bar": n(h["refrig_discharge_bar"])},
                    "thermal_balance": {"battery_heat_load_kw": n(h["battery_heat_load_kw"]),
                                        "cooling_capacity_kw": n(h["cooling_capacity_kw"]),
                                        "heat_rejected_kw": n(h["heat_rejected_kw"]), "cop": n(h["cop"])},
                    "hvac_power_kw": n(h["hvac_power_kw"]),
                    "enclosure": {"temp_c": n(h["enclosure_temp_c"]), "humidity_pct": n(h["enclosure_humidity_pct"])},
                    "alarm_level": h["alarm_level"],
                    "alarm_flags": None if h["alarm_flags"] in (None, "Normal") else h["alarm_flags"],
                },
            },
            "active_dispatch": active_dispatch,
            "active_alarms": active_alarms,
        },
    }


# ---------------------------------------------------------------- the run


@dataclass
class SimulationResult:
    start: datetime
    end: datetime
    intervals: int
    written: int = 0
    skipped_existing: int = 0
    already_loaded: int = 0
    first_file: Optional[str] = None
    last_file: Optional[str] = None
    # simulated day -> source day
    source_days: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    inbox: str = str(INBOX)


def align(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Start rounded up and end rounded down to the 5-minute grid."""
    def floor(t: datetime) -> datetime:
        return t.replace(second=0, microsecond=0) - timedelta(minutes=t.minute % 5)
    s = floor(start)
    if s < start.replace(microsecond=0):
        s += INTERVAL
    return s, floor(end)


def simulate(db: Session, start: datetime, end: datetime, seed: Optional[int] = None, overwrite: bool = False,
             source_from: Optional[date] = None, source_to: Optional[date] = None,
             inbox: Path = INBOX) -> SimulationResult:
    start, end = align(_naive(start), _naive(end))
    if end < start:
        raise SimulatorError("The end time must be at or after the start time (on the 5-minute grid)")
    intervals = int((end - start) / INTERVAL) + 1
    if intervals > MAX_FILES:
        raise SimulatorError(f"{intervals} files requested; the limit is {MAX_FILES} (7 days) per run")

    plant = load_plant(db)
    src = load_source(db, plant, source_from, source_to)
    if not src.days:
        raise SimulatorError("No complete day of BMS, PCS, EMS and HVAC telemetry to sample from"
                             + (" in the chosen source period" if source_from or source_to else ""))
    result = SimulationResult(start=start, end=end, intervals=intervals)
    if not src.module_days:
        result.warnings.append("No module telemetry to sample from; the snapshots have no modules")
    rng = random.Random(seed)

    # BMS counters continue from the last stored value before the start
    previous = [ts for ts in src.bms if ts < start]
    base = src.bms[max(previous)] if previous else None
    last_soc = float(base["soc_bms_pct"]) if base is not None and base["soc_bms_pct"] is not None else None
    cumulative = None if base is None else {
        "charge_kwh": float(base["cum_charge_kwh"] or 0), "discharge_kwh": float(base["cum_discharge_kwh"] or 0),
        "equiv_full_cycles": float(base["equiv_full_cycles"] or 0)}

    # SOC-estimation signals continue from the last stored reading's values (when it has them)
    signals = SocSignals(nominal_ah(plant.rated_energy_kwh, plant.nominal_voltage_v), seed, state=base)

    existing = sum(1 for ts in src.bms if start <= ts <= end)
    if existing:
        result.warnings.append(
            f"{existing} of these intervals already have telemetry; loading will update them (a dispatch already "
            "stored for a moment is kept, and simulated dispatches are fitted around stored ones)")

    inbox.mkdir(parents=True, exist_ok=True)
    day_map: dict[date, tuple[date, Optional[date]]] = {}
    target = start
    while target <= end:
        day = target.date()
        if day not in day_map:
            # keep the state continuous: pick among the few source days whose SOC at this time of day is closest
            # to the previous interval's (the last stored or simulated value); random when there's none
            if last_soc is None:
                source_day = rng.choice(src.days)
            else:
                def gap(d: date) -> float:
                    soc = src.bms[datetime.combine(d, target.time())]["soc_bms_pct"]
                    return abs(float(soc) - last_soc) if soc is not None else float("inf")
                source_day = rng.choice(sorted(src.days, key=gap)[:CLOSEST_DAYS])
            module_day = source_day if source_day in src.module_days else (rng.choice(src.module_days) if src.module_days else None)
            day_map[day] = (source_day, module_day)
            result.source_days[day.isoformat()] = source_day.isoformat()
        source_day, module_day = day_map[day]
        src_ts = datetime.combine(source_day, target.time())
        module_ts = datetime.combine(module_day, target.time()) if module_day else None

        # counters: previous total + the source day's own increment over this interval
        row, prev = src.bms[src_ts], src.bms.get(src_ts - INTERVAL)
        if cumulative is None:
            cumulative = {"charge_kwh": float(row["cum_charge_kwh"] or 0), "discharge_kwh": float(row["cum_discharge_kwh"] or 0),
                          "equiv_full_cycles": float(row["equiv_full_cycles"] or 0)}
        elif prev is not None:
            for key, col in (("charge_kwh", "cum_charge_kwh"), ("discharge_kwh", "cum_discharge_kwh"),
                             ("equiv_full_cycles", "equiv_full_cycles")):
                cumulative[key] += max(0.0, float(row[col] or 0) - float(prev[col] or 0))
        counters = {"charge_kwh": round(cumulative["charge_kwh"], 1), "discharge_kwh": round(cumulative["discharge_kwh"], 1),
                    "equiv_full_cycles": round(cumulative["equiv_full_cycles"], 3)}

        # stepped for every interval (also skipped files) so the counter state stays continuous
        soc_values = SocSignals.from_source(row) or signals.step(row)
        if row["soc_bms_pct"] is not None:
            last_soc = float(row["soc_bms_pct"])
        name = f"{target:%Y-%m-%d-%H-%M-%S}"
        path = inbox / f"{name}.json"
        if (inbox / ARCHIVE.name / name / f"{name}.json").exists():
            result.already_loaded += 1
        if path.exists() and not overwrite:
            result.skipped_existing += 1
        else:
            snapshot = build_snapshot(plant, src, target, src_ts, module_ts, counters, source_day, soc_values)
            # write under a name the batch ignores, then rename: the batch never sees a half-written file
            tmp = inbox / f".{name}.json.tmp"
            tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            result.written += 1
            result.first_file = result.first_file or path.name
            result.last_file = path.name
        target += INTERVAL
    if result.already_loaded:
        result.warnings.append(f"{result.already_loaded} of these files were loaded before (they are in the archive); "
                               "loading them again updates the same records")
    return result


def source_info(db: Session) -> dict:
    """What the simulator can sample from (for the page)."""
    plant = load_plant(db)
    src = load_source(db, plant)
    latest = max(src.bms) if src.bms else None
    return {
        "system_name": plant.system_name,
        "source_days": [d.isoformat() for d in src.days],
        "module_days": [d.isoformat() for d in src.module_days],
        "latest_telemetry": latest.isoformat() if latest else None,
        "inbox": str(INBOX),
        "max_files": MAX_FILES,
        "interval_minutes": 5,
    }
