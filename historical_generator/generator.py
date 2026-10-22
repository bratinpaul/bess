"""Generate historical telemetry files for any battery system from the seven sample files in input/historical.

Used by the frontend (Batch -> Historical Generator, via /api/batch/history-generator) and by generate_bhadla.py.

Inputs: a battery system (its master data: ratings, series cells, PCS AC voltage, PCS / EMS / HVAC codes, packs and
modules) and a date range. Output: input/historical/<Site> BESS/ (e.g. "Bhuj BESS"), the sample layouts:
  BMS, PCS, EMS, HVAC   one xlsx each (sheet "Data"), 288 rows per day
  Module                one CSV per day, every module of the system (module/)
  Alarms                xlsx (sheet "Data"); dispatch events xlsx (sheet "Dispatch Events")
  scenario_calendar.csv, generation_report.json, README.md
Files generated earlier for the same site are replaced (a folder holds one generated range).

How a day is made (the same method as the Bhadla files)
  * sampling: every day copies one sample day (all feeds from that same day, so they agree with each other).
    Sample days are tagged with the scenarios they contain; each month of the range first gets days that cover
    every tag, the rest are drawn at random (seeded per system) without repeats until the pool is used;
  * scaling to the system's ratings: power x rated kW / 1000, capacity -> SOC swings, pack voltage = cell voltage x
    series cells, current = P / V, PCS AC side at its rated voltage (currents from kVA / V); counters, equivalent
    cycles and SOH are recomputed over the range (SOH starts at the modules' average SOH);
  * scenarios on top, from the site's climate (by state): heat waves (hot afternoons, 80 % derating, thermal alarms),
    monsoon / low-price days (cool, humid, compressed prices, shallow cycling; one DC insulation dip), a planned
    maintenance day and a forced outage (PCS ground fault; SOC held; restart before the evening discharge).
"""
import json
import math
import shutil
import sys
import threading
import time as clock
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

import numpy as np
import pandas as pd
import psycopg2

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:  # the shared signal model lives in <project>/snapshot_simulator
    sys.path.insert(0, str(_ROOT))
from snapshot_simulator.soc_signals import SocSignals  # noqa: E402

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parent.parent
# generated site folders live in input/historical/<site>; the sample files in input/historical/template (their
# current home), else input/historical (where they used to be)
HISTORICAL = PROJECT / "input" / "historical"
SAMPLES = next((d for d in (HISTORICAL / "template", HISTORICAL)
                if (d / "BESS_BMS_SampleData_30d_5min.xlsx").exists()), PROJECT / "input" / "historical" / "template")
PLANT_TZ = "Asia/Kolkata"

# the sample system
RATED_KW_OLD, CAP_OLD, AC_V_OLD = 1000.0, 2000.0, 405.0
STEP_H = 5 / 60
SEVERITY = {0: "Info", 1: "Warning", 2: "Alarm", 3: "Critical"}
MAX_DAYS = 92
_LOCK = threading.Lock()


class GenerationError(Exception):
    pass


# ---------------------------------------------------------------- site profile (master data + climate)


@dataclass(frozen=True)
class Climate:
    label: str
    base_ambient: float  # degC above the sample site, every day
    heat_share: float  # share of days in a heat wave
    heat_amp: tuple  # afternoon extra degC on heat days (min, max)
    monsoon_share: float  # share of monsoon / low-price days
    humidity: float  # enclosure humidity offset (coastal sites)


CLIMATES = {
    "Rajasthan": Climate("hot desert (Thar)", 3.0, 0.13, (6.5, 9.5), 0.05, 0.0),
    "Gujarat": Climate("hot arid (Kutch)", 2.5, 0.10, (5.5, 8.5), 0.07, 3.0),
    "Maharashtra": Climate("semi-arid plateau (Marathwada)", 1.0, 0.05, (4.0, 6.5), 0.20, 2.0),
    "Karnataka": Climate("semi-arid plateau", 0.5, 0.04, (4.0, 6.0), 0.17, 0.0),
    "Tamil Nadu": Climate("hot humid coast", 2.0, 0.08, (4.5, 7.0), 0.07, 8.0),
}
DEFAULT_CLIMATE = Climate("moderate", 1.0, 0.06, (4.0, 6.5), 0.10, 0.0)
CLIMATES_ALL = {**CLIMATES, "Other": DEFAULT_CLIMATE}  # the choices on the page ("Other" = moderate)


@dataclass
class SiteProfile:
    battery_system_id: int
    system_name: str
    site_id: int
    site_name: str
    site_code: str
    state: Optional[str]
    rated_kw: float
    capacity_kwh: float
    series_cells: int
    pcs_code: str
    ac_voltage: float
    ems_code: str
    hvac_code: str
    packs: list  # [pack_number] in order
    modules: list  # [(serial, pack index 1.., position 1.., soh)]
    prefix: str  # alarm / dispatch id prefix
    short: str  # "Bhuj"
    climate_key: Optional[str] = None  # a CLIMATES key chosen on the page; None = from the state
    soh_start: Optional[float] = None  # starting SOH chosen on the page; None = the modules' average + 0.05

    @property
    def climate(self) -> Climate:
        if self.climate_key:
            return CLIMATES_ALL.get(self.climate_key, DEFAULT_CLIMATE)
        return CLIMATES.get(self.state or "", DEFAULT_CLIMATE)

    @property
    def folder_name(self) -> str:
        return f"{self.short} BESS"


def database_dsn() -> dict:
    url = None
    for line in (PROJECT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
    if not url:
        raise GenerationError("DATABASE_URL not found in backend/.env")
    u = urlparse(url.replace("postgresql+psycopg2://", "postgresql://"))
    return dict(host=u.hostname, port=u.port or 5432, dbname=u.path.lstrip("/"), user=unquote(u.username or ""),
                password=unquote(u.password or ""), options=f"-c timezone={PLANT_TZ}")


def short_name(site_name: str) -> str:
    name = site_name
    for suffix in (" BESS Site", " Site", " BESS"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip().split(" ")[0] if len(name.split()) > 2 else name.strip()


def _prefixes(cur) -> dict[int, str]:
    """A unique 3-letter id prefix per site (letters of the site code; a digit added on a clash)."""
    cur.execute("SELECT site_id, site_code FROM battery_master.site ORDER BY site_id")
    used, out = set(), {}
    for site_id, code in cur.fetchall():
        letters = "".join(ch for ch in (code or "SITE").upper() if ch.isalpha()) or "SIT"
        p, n = letters[:3], 1
        while p in used:
            n += 1
            p = f"{letters[:2]}{n}"
        used.add(p)
        out[site_id] = p
    return out


def eligible(dsn: Optional[dict] = None) -> list[dict]:
    """Battery systems with the master data a generation needs (PCS, EMS, HVAC, modules)."""
    with psycopg2.connect(**(dsn or database_dsn())) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT b.battery_system_id, b.system_name, s.site_id, s.site_name, s.state, b.rated_power_mw, b.rated_energy_mwh,
                   (SELECT count(*) FROM battery_master.pcs WHERE system_id = b.battery_system_id) AS pcs,
                   (SELECT count(*) FROM battery_master.ems_controller WHERE battery_system_id = b.battery_system_id) AS ems,
                   (SELECT count(*) FROM battery_master.hvac_unit WHERE battery_system_id = b.battery_system_id) AS hvac,
                   (SELECT count(*) FROM battery_master.battery_module m JOIN battery_master.battery_pack p USING (pack_id)
                     JOIN battery_master.battery_container c USING (container_id)
                     WHERE c.battery_system_id = b.battery_system_id) AS modules
            FROM battery_master.battery_system b JOIN battery_master.site s USING (site_id)
            ORDER BY s.site_name, b.system_name""")
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    conn.close()
    out = []
    for r in rows:
        missing = [k for k in ("pcs", "ems", "hvac", "modules") if not r[k]]
        r["rated_power_mw"] = float(r["rated_power_mw"] or 0)
        r["rated_energy_mwh"] = float(r["rated_energy_mwh"] or 0)
        r["ready"] = not missing
        r["missing"] = missing
        r["folder"] = f"{short_name(r['site_name'])} BESS"
        r["climate"] = CLIMATES.get(r["state"] or "", DEFAULT_CLIMATE).label
        out.append(r)
    return out


def load_profile(battery_system_id: int, dsn: Optional[dict] = None) -> SiteProfile:
    with psycopg2.connect(**(dsn or database_dsn())) as conn, conn.cursor() as cur:
        cur.execute("""SELECT b.system_name, b.rated_power_mw, b.rated_energy_mwh, b.series_cells, s.site_id, s.site_name,
                              s.site_code, s.state, s.rated_power_mw, s.rated_energy_mwh
                       FROM battery_master.battery_system b JOIN battery_master.site s USING (site_id)
                       WHERE b.battery_system_id = %s""", (battery_system_id,))
        row = cur.fetchone()
        if not row:
            raise GenerationError(f"Battery system {battery_system_id} not found")
        system_name, p_mw, e_mwh, series, site_id, site_name, site_code, state, sp_mw, se_mwh = row
        cur.execute("SELECT pcs_code, rated_ac_voltage_v FROM battery_master.pcs WHERE system_id = %s ORDER BY pcs_code",
                    (battery_system_id,))
        pcs = cur.fetchone()
        cur.execute("SELECT ems_code FROM battery_master.ems_controller WHERE battery_system_id = %s ORDER BY ems_code",
                    (battery_system_id,))
        ems = cur.fetchone()
        cur.execute("SELECT hvac_code FROM battery_master.hvac_unit WHERE battery_system_id = %s ORDER BY hvac_code",
                    (battery_system_id,))
        hvac = cur.fetchone()
        cur.execute("""SELECT p.pack_number, m.serial_number, m.soh_pct FROM battery_master.battery_module m
                       JOIN battery_master.battery_pack p USING (pack_id)
                       JOIN battery_master.battery_container c USING (container_id)
                       WHERE c.battery_system_id = %s ORDER BY p.pack_number, m.serial_number""", (battery_system_id,))
        mods = cur.fetchall()
        prefix = _prefixes(cur)[site_id]
    conn.close()
    missing = [n for n, v in (("PCS", pcs), ("EMS controller", ems), ("HVAC unit", hvac), ("modules", mods)) if not v]
    if missing:
        raise GenerationError(f"{system_name} has no {', '.join(missing)} in master data")
    packs = list(dict.fromkeys(m[0] for m in mods))
    modules, pos = [], {}
    for pack_number, serial, soh in mods:
        pi = packs.index(pack_number) + 1
        pos[pi] = pos.get(pi, 0) + 1
        modules.append((serial, pi, pos[pi], float(soh) if soh is not None else 99.2))
    # the pack module count (the sample is 16 modules of 384 cells in series); modules x cells when series is missing
    rated_kw = float(p_mw or sp_mw or 1.0) * 1000
    capacity = float(e_mwh or se_mwh or 2.0) * 1000
    return SiteProfile(battery_system_id, system_name, site_id, site_name, site_code, state, rated_kw, capacity,
                       int(series or 384), pcs[0], float(pcs[1] or AC_V_OLD), ems[0], hvac[0], packs, modules, prefix,
                       short_name(site_name))


def default_soh(profile: SiteProfile) -> float:
    return round(float(np.mean([m[3] for m in profile.modules])) + 0.05, 2)


def system_codes(battery_system_id: int, dsn: Optional[dict] = None) -> dict:
    """The PCS / EMS / HVAC codes of a battery system (the choices for the mapping)."""
    with psycopg2.connect(**(dsn or database_dsn())) as conn, conn.cursor() as cur:
        out = {}
        for key, sql in (("pcs", "SELECT pcs_code FROM battery_master.pcs WHERE system_id = %s"),
                         ("ems", "SELECT ems_code FROM battery_master.ems_controller WHERE battery_system_id = %s"),
                         ("hvac", "SELECT hvac_code FROM battery_master.hvac_unit WHERE battery_system_id = %s")):
            cur.execute(sql + " ORDER BY 1", (battery_system_id,))
            out[key] = [r[0] for r in cur.fetchall()]
    conn.close()
    return out


# the mapping fields the page may override for one run (master data is never changed): field -> (label, kind, min, max)
OVERRIDES = {
    "rated_kw": ("Rated power (kW)", float, 10.0, 1_000_000.0),
    "capacity_kwh": ("Usable energy (kWh)", float, 10.0, 4_000_000.0),
    "series_cells": ("Cells in series", int, 10, 20_000),
    "ac_voltage": ("PCS AC voltage (V)", float, 100.0, 765_000.0),
    "soh_start": ("Starting SOH (%)", float, 60.0, 100.0),
    "pcs_code": ("PCS code", str, None, None),
    "ems_code": ("EMS controller code", str, None, None),
    "hvac_code": ("HVAC unit code", str, None, None),
    "climate_key": ("Climate profile", str, None, None),
    "prefix": ("Alarm / dispatch id prefix", str, None, None),
}


def apply_overrides(profile: SiteProfile, overrides: Optional[dict], codes: Optional[dict] = None) -> tuple[SiteProfile, dict]:
    """A copy of the profile with the page's values; returns it and the fields that differ from master data."""
    if not overrides:
        return profile, {}
    base = {**asdict(profile), "soh_start": profile.soh_start if profile.soh_start is not None else default_soh(profile),
            "climate_key": profile.climate_key or (profile.state if profile.state in CLIMATES else "Other")}
    values, changed = dict(base), {}
    for name, raw in overrides.items():
        if name not in OVERRIDES:
            raise GenerationError(f"Unknown mapping field: {name}")
        if raw is None or raw == "":
            continue
        label, kind, lo, hi = OVERRIDES[name]
        try:
            v = kind(raw) if kind is not str else str(raw).strip()
        except (TypeError, ValueError):
            raise GenerationError(f"{label}: '{raw}' is not a valid {kind.__name__}")
        if lo is not None and not lo <= v <= hi:
            raise GenerationError(f"{label} must be between {lo:g} and {hi:g} ({v:g} given)")
        if name in ("pcs_code", "ems_code", "hvac_code"):
            codes = codes or system_codes(profile.battery_system_id)
            allowed = codes[name.split("_")[0]]
            if v not in allowed:
                raise GenerationError(f"{label} '{v}' is not one of {profile.system_name}'s units ({', '.join(allowed)})")
        if name == "climate_key" and v not in CLIMATES_ALL:
            raise GenerationError(f"Unknown climate profile '{v}'")
        if name == "prefix":
            v = v.upper()
            if not (2 <= len(v) <= 6 and v.isalnum()):
                raise GenerationError("The id prefix must be 2-6 letters or digits")
        values[name] = v
        if v != base[name]:
            changed[name] = {"master": base[name], "used": v}
    values["modules"], values["packs"] = profile.modules, profile.packs
    return SiteProfile(**values), changed


# ---------------------------------------------------------------- samples


@lru_cache(maxsize=1)
def _read_samples_cached(stamp: tuple) -> dict:
    s = {
        "bms": pd.read_excel(SAMPLES / "BESS_BMS_SampleData_30d_5min.xlsx"),
        "pcs": pd.read_excel(SAMPLES / "BESS_PCS_SampleData_30d_5min.xlsx"),
        "ems": pd.read_excel(SAMPLES / "BESS_EMS_SampleData_30d_5min.xlsx"),
        "hvac": pd.read_excel(SAMPLES / "BESS_HVAC_SampleData_30d_5min.xlsx"),
        "module": pd.read_excel(SAMPLES / "BESS_ModuleTelemetry_30d_5min.xlsx"),
        "alarm": pd.read_excel(SAMPLES / "BESS_Alarm_SampleData.xlsx"),
        "dispatch": pd.read_excel(SAMPLES / "BESS_DispatchEvents_SampleData.xlsx", sheet_name="Dispatch Events"),
    }
    s["bms"]["ts"] = s["bms"]["Timestamp"]
    for key in ("bms", "pcs", "ems", "hvac"):
        s[key]["sday"] = s[key]["ts"].dt.date
    s["cols"] = {k: list(s[k].columns) for k in ("bms", "pcs", "ems", "hvac", "alarm", "dispatch")}
    s["cols"]["bms"] = [c for c in s["cols"]["bms"] if c not in ("ts", "sday")]
    for k in ("pcs", "ems", "hvac"):
        s["cols"][k] = [c for c in s["cols"][k] if c != "sday"]
    return s


SAMPLE_FILES = ("BESS_BMS_SampleData_30d_5min.xlsx", "BESS_PCS_SampleData_30d_5min.xlsx", "BESS_EMS_SampleData_30d_5min.xlsx",
                "BESS_HVAC_SampleData_30d_5min.xlsx", "BESS_ModuleTelemetry_30d_5min.xlsx", "BESS_Alarm_SampleData.xlsx",
                "BESS_DispatchEvents_SampleData.xlsx")


def read_samples() -> dict:
    missing = [f for f in SAMPLE_FILES if not (SAMPLES / f).exists()]
    if missing:
        raise GenerationError(f"Sample file(s) missing in {SAMPLES}: {', '.join(missing)}")
    stamp = tuple((SAMPLES / f).stat().st_mtime for f in SAMPLE_FILES)  # re-read when a sample changes
    return _read_samples_cached(stamp)


# ---------------------------------------------------------------- scenario calendar


@dataclass
class DayPlan:
    day: date
    source: date = None
    scenario: str = "normal"  # normal | heat | monsoon | maintenance | outage
    k: float = 1.0  # dispatch intensity (power / energy scale)
    amp: float = 0.0  # afternoon ambient offset on top of the climate's base
    window: tuple = None  # (start, end) datetimes the plant is offline
    notes: list = field(default_factory=list)


@dataclass
class Calendar:
    """Fixed scenario days (generate_bhadla.py); None = derive them from the climate and the range."""
    heat: dict  # date -> amplitude
    monsoon: list
    low_insulation: Optional[date]
    maintenance: Optional[tuple]  # (date, start time, end time)
    outage: Optional[tuple]  # (date, restart time)


def calendar_to_dict(cal: Calendar) -> dict:
    return {
        "heat": {d.isoformat(): a for d, a in sorted(cal.heat.items())},
        "monsoon": sorted(d.isoformat() for d in cal.monsoon),
        "low_insulation": cal.low_insulation.isoformat() if cal.low_insulation else None,
        "maintenance": {"date": cal.maintenance[0].isoformat(), "start": f"{cal.maintenance[1]:%H:%M}",
                        "end": f"{cal.maintenance[2]:%H:%M}"} if cal.maintenance else None,
        "outage": {"date": cal.outage[0].isoformat(), "restart": f"{cal.outage[1]:%H:%M}"} if cal.outage else None,
    }


def _hhmm(value: str, what: str) -> time:
    try:
        t = datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        raise GenerationError(f"{what}: '{value}' is not a time (HH:MM)")
    if t.minute % 5:
        raise GenerationError(f"{what}: use a 5-minute time (the data is 5-minute), not {value}")
    return t


def calendar_from_dict(d: dict, start: date, end: date) -> Calendar:
    """The page's scenario calendar, checked: dates inside the range, at most one scenario per day."""
    def day(v, what):
        try:
            x = date.fromisoformat(str(v))
        except ValueError:
            raise GenerationError(f"{what}: '{v}' is not a date")
        if not start <= x <= end:
            raise GenerationError(f"{what} {x} is outside {start} - {end}")
        return x

    heat = {}
    for k, amp in (d.get("heat") or {}).items():
        a = float(amp)
        if not 0 <= a <= 15:
            raise GenerationError(f"Heat day {k}: the afternoon extra must be 0-15 degC ({a:g} given)")
        heat[day(k, "Heat day")] = round(a, 1)
    monsoon = sorted({day(v, "Monsoon day") for v in d.get("monsoon") or []})
    used: dict[date, str] = {x: "heat" for x in heat}
    for x in monsoon:
        if x in used:
            raise GenerationError(f"{x} is both a heat day and a monsoon day")
        used[x] = "monsoon"
    low = day(d["low_insulation"], "Insulation dip day") if d.get("low_insulation") else None
    if low and low not in monsoon:
        raise GenerationError(f"The insulation dip day {low} must be a monsoon day")
    maintenance = outage = None
    if d.get("maintenance"):
        m = d["maintenance"]
        md = day(m.get("date"), "Maintenance day")
        t0, t1 = _hhmm(m.get("start", "07:00"), "Maintenance start"), _hhmm(m.get("end", "17:00"), "Maintenance end")
        if t1 <= t0:
            raise GenerationError("Maintenance must end after it starts")
        if md in used:
            raise GenerationError(f"The maintenance day {md} is also a {used[md]} day")
        used[md] = "maintenance"
        maintenance = (md, t0, t1)
    if d.get("outage"):
        o = d["outage"]
        od = day(o.get("date"), "Forced outage day")
        restart = _hhmm(o.get("restart", "16:30"), "Outage restart")
        if not time(13, 30) <= restart <= time(17, 0):
            raise GenerationError("The outage restart must be between 13:30 and 17:00 (before the evening discharge)")
        if od in used:
            raise GenerationError(f"The forced outage day {od} is also a {used[od]} day")
        outage = (od, restart)
    return Calendar(heat, monsoon, low, maintenance, outage)


def day_tags(s: dict) -> dict[date, set]:
    tags: dict[date, set] = {}
    add = lambda d, t: tags.setdefault(d, set()).add(t)  # noqa: E731
    for d, g in s["ems"].groupby("sday"):
        tags.setdefault(d, set())
        if (g.dispatch_mode == "FREQUENCY_REGULATION").any():
            add(d, "freq_reg")
    for d, g in s["pcs"].groupby("sday"):
        for svc in ("VOLT_VAR", "FREQ_WATT"):
            if (g.grid_service == svc).any():
                add(d, svc.lower())
        if (g.alarm_level > 0).any():
            add(d, "pcs_alarm")
    for d, g in s["bms"].groupby("sday"):
        for flag in set(g.Alarm_Flags) - {"Normal"}:
            add(d, f"bms:{flag}")
    for d, g in s["hvac"].groupby("sday"):
        for flag in set(g.alarm_flags) - {"Normal"}:
            add(d, f"hvac:{flag}")
    for _, a in s["alarm"].iterrows():
        add(pd.Timestamp(a.start_time).date(), f"alarm:{a.alarm_code}")
    return tags


class Generator:
    def __init__(self, profile: SiteProfile, start: date, end: date, seed: Optional[int] = None,
                 calendar: Optional[Calendar] = None, module_from: Optional[date] = None):
        if end < start:
            raise GenerationError("The end date is before the start date")
        days = (end - start).days + 1
        if days > MAX_DAYS:
            raise GenerationError(f"At most {MAX_DAYS} days can be generated at once ({days} asked)")
        self.p = profile
        self.start, self.end = start, end
        self.days = [start + timedelta(days=i) for i in range(days)]
        self.module_from = module_from or start
        self.rng = np.random.default_rng(seed if seed is not None else 2026 + profile.battery_system_id)
        self.calendar = calendar
        self.F_P = profile.rated_kw / RATED_KW_OLD
        self.F_SOC = self.F_P * CAP_OLD / profile.capacity_kwh
        self.base_ambient = profile.climate.base_ambient
        self.soh_start = profile.soh_start if profile.soh_start is not None else default_soh(profile)
        self.warnings: list[str] = []

    # ---------------------------------------------------------------- plan

    def choose_sources(self, tags: dict[date, set]) -> dict[date, date]:
        first_sample = min(tags)
        pool_all = sorted(d for d in tags if d != first_sample)  # the first sample day starts at 55 % SOC
        all_tags = set().union(*(tags[d] for d in pool_all))
        out = {}
        if self.start == first_sample:
            out[self.start] = first_sample
        for month in sorted({(d.year, d.month) for d in self.days}):
            month_days = [d for d in self.days if (d.year, d.month) == month and d not in out]
            uncovered, cover = set(all_tags), []
            while uncovered:
                best = max(pool_all, key=lambda d: (len(tags[d] & uncovered), -pool_all.index(d)))
                if not tags[best] & uncovered:
                    break
                cover.append(best)
                uncovered -= tags[best]
            rest = [d for d in pool_all if d not in cover]
            self.rng.shuffle(rest)
            sequence = cover + rest
            while len(sequence) < len(month_days):
                extra = list(pool_all)
                self.rng.shuffle(extra)
                sequence += extra
            order = list(month_days)
            self.rng.shuffle(order)
            for d, src in zip(order, sequence):
                out[d] = src
        return out

    def auto_calendar(self) -> Calendar:
        """Scenario days from the site's climate: heat waves of 2-3 days, scattered monsoon days, one maintenance
        day (about a third into the range) and one forced outage (about two thirds), when the range is long enough."""
        c, n = self.p.climate, len(self.days)
        free = list(self.days[1:])  # keep the first day plain
        heat: dict = {}
        n_heat = int(round(n * c.heat_share))
        while n_heat > 0 and len(free) > 3:
            length = min(n_heat, int(self.rng.integers(2, 4)))
            i = int(self.rng.integers(0, max(1, len(free) - length)))
            run = free[i:i + length]
            if any((b - a).days != 1 for a, b in zip(run, run[1:])):
                n_heat -= 1
                continue
            for d in run:
                heat[d] = round(float(self.rng.uniform(*c.heat_amp)), 1)
                free.remove(d)
            n_heat -= length
        mons = sorted(self.rng.choice(free, size=min(len(free) // 2, int(round(n * c.monsoon_share))), replace=False)) \
            if free and c.monsoon_share > 0 else []
        mons = [d if isinstance(d, date) else pd.Timestamp(d).date() for d in mons]
        for d in mons:
            free.remove(d)
        maintenance = outage = None
        if n >= 10 and free:
            target = self.days[n // 3]
            d = min(free, key=lambda x: abs((x - target).days))
            maintenance = (d, time(7, 0), time(17, 0))
            free.remove(d)
        if n >= 14 and free:
            target = self.days[(2 * n) // 3]
            d = min(free, key=lambda x: abs((x - target).days))
            outage = (d, time(16, 30))
        return Calendar(heat, list(mons), mons[0] if mons else None, maintenance, outage)

    def build_plan(self, s: dict) -> list[DayPlan]:
        cal = self.calendar or self.auto_calendar()
        self.cal = cal
        sources = self.choose_sources(day_tags(s))
        plans = []
        for d in self.days:
            p = DayPlan(d, sources[d])
            if d in cal.heat:
                p.scenario, p.amp, p.k = "heat", cal.heat[d], 0.8
                p.notes.append(f"heat wave: afternoon ambient +{cal.heat[d] + self.base_ambient:.1f} degC over the sample "
                               "site, power derated to 80 %")
            elif d in cal.monsoon:
                p.scenario, p.amp, p.k = "monsoon", -5.0, 0.35
                p.notes.append("monsoon: cool, humid, compressed low prices, shallow cycling (35 %)")
                if d == cal.low_insulation:
                    p.notes.append("moisture: DC insulation below 2100 kOhm for ~45 min")
            elif cal.maintenance and d == cal.maintenance[0]:
                p.scenario, p.k = "maintenance", 0.0
                p.window = (datetime.combine(d, cal.maintenance[1]), datetime.combine(d, cal.maintenance[2]))
                p.notes.append(f"planned maintenance {cal.maintenance[1]:%H:%M}-{cal.maintenance[2]:%H:%M}: contactors and "
                               "PCS breaker open, plant unavailable")
            plans.append(p)
        if cal.outage:
            self._plan_outage(s, plans, cal.outage)
        return plans

    def _plan_outage(self, s: dict, plans: list[DayPlan], outage: tuple) -> None:
        """SOC is held while the plant is off, so trip and restart need the same SOC in the source day; use a source day
        that allows it (swapped with another plain day of the range if needed)."""
        out_plan = next((p for p in plans if p.day == outage[0]), None)
        if out_plan is None:
            return
        restart = outage[1]
        candidates = [out_plan] + [p for p in plans if p.scenario == "normal" and p is not out_plan]
        for other in candidates:
            bms = s["bms"][s["bms"].sday == other.source]
            at_restart = bms.loc[bms.ts.dt.time == restart, "SOC_%"]
            if at_restart.empty:
                continue
            cand = bms[(bms.ts.dt.time >= time(9, 0)) & (bms.ts.dt.time <= time(13, 0))
                       & ((bms["SOC_%"] - at_restart.iloc[0]).abs() < 1.5) & bms.Mode.isin(["Standby", "Idle"])]
            if len(cand):
                out_plan.source, other.source = other.source, out_plan.source
                trip = cand.ts.iloc[0].time()
                break
        else:
            self.warnings.append("No sample day allows a forced outage with matching SOC; outage left out")
            return
        out_plan.scenario = "outage"
        out_plan.window = (datetime.combine(out_plan.day, trip), datetime.combine(out_plan.day, restart))
        out_plan.notes.append(f"forced outage: PCS ground fault trips the breaker at {trip:%H:%M}, restart "
                              f"{restart:%H:%M}; SOC held while offline")

    # ---------------------------------------------------------------- assemble

    def assemble(self, sample: pd.DataFrame, plans: list[DayPlan]) -> pd.DataFrame:
        parts = []
        for i, p in enumerate(plans):
            g = sample[sample.sday == p.source].copy()
            shift = pd.Timestamp(p.day) - pd.Timestamp(p.source)
            g["ts"] = g["ts"] + shift
            g["day_idx"], g["scenario"] = i, p.scenario
            hour = g["ts"].dt.hour + g["ts"].dt.minute / 60
            if p.scenario == "monsoon":
                dT = -4.0 - 1.5 * np.exp(-((hour - 14) / 4) ** 2)
            else:
                dT = self.base_ambient + p.amp * np.exp(-((hour - 14.5) / 3.5) ** 2)
            g["dT"] = dT
            k = np.full(len(g), p.k)
            offline = np.zeros(len(g), bool)
            if p.window:
                offline = ((g["ts"] >= p.window[0]) & (g["ts"] < p.window[1])).to_numpy()
                if p.scenario == "outage":
                    k = np.where(offline, 0.0, 1.0)
            g["k"], g["offline"] = k, offline
            parts.append(g)
        return pd.concat(parts, ignore_index=True)

    # ---------------------------------------------------------------- BMS

    def make_bms(self, s: dict, plans: list[DayPlan]) -> pd.DataFrame:
        F_P, F_SOC, P = self.F_P, self.F_SOC, self.p
        b = self.assemble(s["bms"], plans)
        src = s["bms"]
        end_soc = src.groupby("sday")["SOC_%"].last()
        rest_v = src.groupby("sday")["Cell_V_Avg_V"].first()
        plan_src = pd.Series([p.source for p in plans])
        anchor = plan_src.map(end_soc).to_numpy()[b.day_idx]
        vrest = plan_src.map(rest_v).to_numpy()[b.day_idx]
        k = b.k.to_numpy()
        soc = np.clip(anchor + (b["SOC_%"] - anchor) * F_SOC * np.where(b.scenario == "outage", 1.0, k), 5, 100)
        off_idx = np.flatnonzero(b.offline.to_numpy() & (b.scenario == "outage").to_numpy())
        if len(off_idx):
            soc[off_idx] = soc[off_idx[0] - 1]
        b["SOC_%"] = soc.round(2)
        dv = (b.Cell_V_Avg_V - vrest) * (k - 1)
        for c in ("Cell_V_Avg_V", "Cell_V_Min_V", "Cell_V_Max_V"):
            b[c] = (b[c] + dv).round(4)
        b["Power_kW"] = (b.Power_kW * F_P * k).round(1)
        b["Pack_Voltage_V"] = (b.Cell_V_Avg_V * P.series_cells).round(1)
        b["Pack_Current_A"] = (b.Power_kW * 1000 / b.Pack_Voltage_V).round(1)
        b["C_Rate"] = (b.Power_kW / P.capacity_kwh).round(3)
        dT = b.dT.to_numpy()
        heat_rise = np.where(b.scenario == "heat", 0.15 * np.abs(b.Power_kW) / P.rated_kw * 10, 0)
        for c in ("Cell_Temp_Avg_C", "Cell_Temp_Min_C", "Cell_Temp_Max_C"):
            b[c] = (b[c] + np.where(b.scenario == "heat", 0.8, 0.5) * dT + heat_rise).round(2)
        b["Coolant_Temp_C"] = (b.Coolant_Temp_C + 0.4 * dT).round(2)
        b["Ambient_Temp_C"] = (b.Ambient_Temp_C + dT).round(2)
        derate = np.where(b.scenario == "heat", 0.8, 1.0)
        for c in ("Avail_Charge_kW", "Avail_Discharge_kW"):
            b[c] = (b[c] * F_P * derate).round(0)
        b["Charge_kWh_step"] = (b.Charge_kWh_step * F_P * k).round(3)
        b["Discharge_kWh_step"] = (b.Discharge_kWh_step * F_P * k).round(3)
        ins = b.Insulation_Res_kOhm.astype(float).to_numpy()
        b["Insulation_Res_kOhm"] = np.where(b.scenario == "monsoon", ins * 0.88, ins).round(0)
        off = b.offline.to_numpy()
        zero = k == 0
        b.loc[zero, "Mode"] = "Standby"
        b.loc[zero, "Contactor_Status"] = "Closed"
        b.loc[off, "Mode"] = "Idle"
        b.loc[off, "Contactor_Status"] = "Open"
        b.loc[off, ["Avail_Charge_kW", "Avail_Discharge_kW"]] = 0
        for c in ("Power_kW", "Pack_Current_A", "C_Rate"):
            b.loc[zero, c] = 0.0
        b.loc[off & (b.Alarm_Flags != "Normal"), ["Alarm_Level", "Alarm_Flags"]] = [0, "Normal"]
        b.loc[zero & (b.Alarm_Flags == "SOC_Limit"), ["Alarm_Level", "Alarm_Flags"]] = [0, "Normal"]
        b["Timestamp"] = b.ts
        return b

    def finish_bms(self, b: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        cap = self.p.capacity_kwh
        b["Cum_Charge_kWh"] = b.Charge_kWh_step.cumsum().round(1)
        b["Cum_Discharge_kWh"] = b.Discharge_kWh_step.cumsum().round(1)
        b["Equiv_Full_Cycles"] = ((b.Cum_Charge_kWh + b.Cum_Discharge_kWh) / 2 / cap).round(2)
        d_efc = ((b.Charge_kWh_step + b.Discharge_kWh_step) / 2 / cap) * np.where(b.scenario == "heat", 1.6, 1.0)
        days = (b.ts - b.ts.iloc[0]).dt.total_seconds() / 86400
        soh = self.soh_start - 0.0045 * d_efc.cumsum() - 0.0012 * days
        b["SOH_%"] = np.minimum.accumulate(soh.to_numpy()).round(2)
        b["Date"] = b.ts.dt.strftime("%Y-%m-%d")
        b.insert(0, "System_Name", self.p.system_name)
        extra = self.soc_signal_columns(b)
        return b[["System_Name"] + cols + [c for c in extra if c not in cols]]

    # system_telemetry columns since 2026-10 (current sensing, SOC estimation, rest) -> file headers
    SOC_SIGNAL_HEADERS = {
        "measured_current_a": "Measured_Current_A", "current_sensor_offset_a": "Current_Sensor_Offset_A",
        "soc_coulomb_pct": "SOC_Coulomb_%", "soc_battery_telemetry_pct": "SOC_Battery_Telemetry_%",
        "usable_capacity_ah": "Usable_Capacity_Ah", "coulombic_efficiency": "Coulombic_Efficiency",
        "at_rest": "At_Rest", "rest_duration_min": "Rest_Duration_min", "ocv_rested_v": "OCV_Rested_V",
    }
    LFP_CELL_NOMINAL_V = 3.2

    def soc_signal_columns(self, b: pd.DataFrame) -> list[str]:
        """Measured current / sensor offset / coulomb-counted and telemetry SOC / usable Ah / coulombic efficiency /
        rest state / rested OCV, derived reading by reading from the generated series (shared model:
        snapshot_simulator/soc_signals.py). Sample files that already carry them are kept as they are."""
        headers = list(self.SOC_SIGNAL_HEADERS.values())
        if all(h in b.columns and b[h].notna().any() for h in headers):
            return headers
        nominal_ah = self.p.capacity_kwh * 1000.0 / (self.p.series_cells * self.LFP_CELL_NOMINAL_V)
        signals = SocSignals(nominal_ah, seed=2026 + self.p.battery_system_id)
        cols = {k: [] for k in self.SOC_SIGNAL_HEADERS}
        for cur, soc, soh, temp, volt in zip(b["Pack_Current_A"], b["SOC_%"], b["SOH_%"], b["Cell_Temp_Avg_C"],
                                              b["Cell_V_Avg_V"]):
            out = signals.step({"pack_current_a": cur, "soc_bms_pct": soc, "soh_pct": soh, "cell_temp_avg_c": temp,
                                "cell_v_avg_v": volt})
            for k in cols:
                cols[k].append(out[k])
        for k, header in self.SOC_SIGNAL_HEADERS.items():
            b[header] = cols[k]
        return headers

    # ---------------------------------------------------------------- PCS

    def make_pcs(self, s: dict, plans: list[DayPlan], bms: pd.DataFrame) -> pd.DataFrame:
        F_P = self.F_P
        p = self.assemble(s["pcs"], plans)
        k, dT, off = p.k.to_numpy(), p.dT.to_numpy(), p.offline.to_numpy()
        derate = np.where(p.scenario == "heat", 0.8, 1.0)
        for c in ("ac_active_power_kw", "ac_reactive_power_kvar", "ac_apparent_power_kva", "dc_power_kw"):
            p[c] = (p[c] * F_P * k).round(2)
        for c in ("avail_charge_kw", "avail_discharge_kw"):
            p[c] = (p[c] * F_P * derate).round(0)
        for c in ("ac_voltage_ab_v", "ac_voltage_bc_v", "ac_voltage_ca_v"):
            p[c] = (p[c] * self.p.ac_voltage / AC_V_OLD).round(1)
        phases = p[["ac_current_a_a", "ac_current_b_a", "ac_current_c_a"]].astype(float)
        ratio = phases.div(phases.mean(axis=1).replace(0, np.nan), axis=0).fillna(1.0)
        v_ll = p[["ac_voltage_ab_v", "ac_voltage_bc_v", "ac_voltage_ca_v"]].mean(axis=1)
        i_mean = (p.ac_apparent_power_kva * 1000 / (math.sqrt(3) * v_ll.where(v_ll > 0))).fillna(0.0)
        for c in phases.columns:
            p[c] = (i_mean * ratio[c]).round(2)
        p["dc_voltage_v"] = bms["Pack_Voltage_V"].to_numpy()
        p["dc_current_a"] = (p.dc_power_kw * 1000 / p.dc_voltage_v).round(2)
        p["igbt_temp_c"] = (p.igbt_temp_c + 0.6 * dT).round(2)
        p["heatsink_temp_c"] = (p.heatsink_temp_c + 0.5 * dT).round(2)
        p["inlet_coolant_temp_c"] = (p.inlet_coolant_temp_c + 0.4 * dT).round(2)
        p["ambient_temp_c"] = bms["Ambient_Temp_C"].to_numpy()
        p["import_kwh_step"] = (p.import_kwh_step * F_P * k).round(3)
        p["export_kwh_step"] = (p.export_kwh_step * F_P * k).round(3)
        zero = k == 0
        p.loc[zero, ["mode_code", "grid_service"]] = ["STANDBY", "NONE"]
        p.loc[zero, ["power_factor", "efficiency_pct", "thd_current_pct"]] = np.nan
        p.loc[zero, ["igbt_temp_c", "heatsink_temp_c"]] = p.loc[zero, ["inlet_coolant_temp_c"]].to_numpy() + [[2.5, 1.5]]
        if off.any():
            outage = off & (p.scenario == "outage").to_numpy()
            maint = off & (p.scenario == "maintenance").to_numpy()
            p.loc[maint, ["mode_code", "breaker_state"]] = ["IDLE", "OPEN"]
            p.loc[outage, ["mode_code", "breaker_state"]] = ["FAULT", "TRIPPED"]
            p.loc[off, ["avail_charge_kw", "avail_discharge_kw"]] = 0
            p.loc[outage, "alarm_level"] = 3
            p.loc[maint, "alarm_level"] = 0
            p.loc[off, ["ac_current_a_a", "ac_current_b_a", "ac_current_c_a", "dc_current_a"]] = 0.0
        p["ac_energy_import_kwh"] = p.import_kwh_step.cumsum().round(2)
        p["ac_energy_export_kwh"] = p.export_kwh_step.cumsum().round(2)
        p["pcs_code"] = self.p.pcs_code
        p["Date"] = p.ts.dt.strftime("%Y-%m-%d")
        return p

    # ---------------------------------------------------------------- EMS

    def make_ems(self, s: dict, plans: list[DayPlan], bms: pd.DataFrame, hvac_extra_kw: np.ndarray) -> pd.DataFrame:
        F_P, F_SOC, P = self.F_P, self.F_SOC, self.p
        e = self.assemble(s["ems"], plans)
        k, off = e.k.to_numpy(), e.offline.to_numpy()
        derate = np.where(e.scenario == "heat", 0.8, 1.0)
        aux_new = (e.aux_load_kw * F_P + hvac_extra_kw).clip(lower=1.0)
        e["poi_active_power_kw"] = (k * F_P * (e.poi_active_power_kw - e.aux_load_kw) + aux_new).round(2)
        e["aux_load_kw"] = aux_new.round(2)
        e["aux_load_pct"] = (aux_new / P.rated_kw * 100).round(2)
        for c in ("p_setpoint_kw", "poi_reactive_power_kvar", "tracking_error_kw"):
            e[c] = (e[c] * F_P * k).round(2)
        for c in ("avail_charge_kw", "avail_discharge_kw"):
            e[c] = (e[c] * F_P * derate).round(0)
        soc = bms["SOC_%"].to_numpy()
        e["plant_soc_pct"] = soc
        src_end = s["bms"].groupby("sday")["SOC_%"].last()
        anchor = pd.Series([p.source for p in plans]).map(src_end).to_numpy()[e.day_idx]
        e["target_soc_pct"] = np.clip(anchor + (e.target_soc_pct - anchor) * F_SOC * np.where(k == 0, 0, 1), 5, 100).round(1)
        e["avail_charge_energy_kwh"] = np.clip((95 - soc) / 100 * P.capacity_kwh, 0, None).round(1)
        e["avail_discharge_energy_kwh"] = np.clip((soc - 10) / 100 * P.capacity_kwh, 0, None).round(1)
        day_mean = e.groupby("day_idx").market_price_mwh.transform("mean")
        mons = (e.scenario == "monsoon").to_numpy()
        e.loc[mons, "market_price_mwh"] = ((day_mean + (e.market_price_mwh - day_mean) * 0.3) * 0.7)[mons].round(2)
        zero = k == 0
        e.loc[zero, ["dispatch_mode", "grid_service"]] = ["STANDBY", "NONE"]
        e.loc[zero, "agc_signal"] = np.nan
        e.loc[off, "dispatch_mode"] = "IDLE"
        e.loc[off, ["units_online", "plant_available", "avail_charge_kw", "avail_discharge_kw"]] = 0
        e.loc[off & (e.scenario == "outage").to_numpy(), "alarm_level"] = 3
        e.loc[off & (e.scenario == "maintenance").to_numpy(), "alarm_level"] = 0
        poi = e.poi_active_power_kw
        e["import_kwh_step"] = (poi.clip(lower=0) * STEP_H).round(3)
        e["export_kwh_step"] = ((-poi).clip(lower=0) * STEP_H).round(3)
        e["revenue_step_usd"] = ((e.export_kwh_step - e.import_kwh_step) * e.market_price_mwh / 1000).round(4)
        e["cum_import_kwh"] = e.import_kwh_step.cumsum().round(1)
        e["cum_export_kwh"] = e.export_kwh_step.cumsum().round(1)
        e["revenue_cum_usd"] = e.revenue_step_usd.cumsum().round(2)
        e["Date"] = e.ts.dt.strftime("%Y-%m-%d")
        return e

    # ---------------------------------------------------------------- HVAC

    def make_hvac(self, s: dict, plans: list[DayPlan]) -> tuple[pd.DataFrame, np.ndarray]:
        F_P = self.F_P
        h = self.assemble(s["hvac"], plans)
        k, dT = h.k.to_numpy(), h.dT.to_numpy()
        load = F_P * (0.3 + 0.7 * k)
        h["ambient_temp_c"] = (h.ambient_temp_c + dT).round(2)
        for c in ("coolant_supply_temp_c", "coolant_return_temp_c"):
            h[c] = (h[c] + 0.4 * dT).round(2)
        h["coolant_delta_t_c"] = (h.coolant_return_temp_c - h.coolant_supply_temp_c).round(2)
        h["enclosure_temp_c"] = (h.enclosure_temp_c + 0.5 * dT).round(2)
        mons = (h.scenario == "monsoon").to_numpy()
        heat = (h.scenario == "heat").to_numpy()
        h["enclosure_humidity_pct"] = np.clip(h.enclosure_humidity_pct + self.p.climate.humidity, 5, 95).round(1)
        h.loc[mons, "enclosure_humidity_pct"] = np.clip(h.enclosure_humidity_pct[mons] + 22, 0, 92).round(1)
        h.loc[heat, "enclosure_humidity_pct"] = np.clip(h.enclosure_humidity_pct[heat] - 8, 8, 100).round(1)
        for c in ("battery_heat_load_kw", "cooling_capacity_kw", "heat_rejected_kw"):
            h[c] = (h[c] * load).round(2)
        hot = (h.cooling_mode == "FREE_COOLING") & (h.ambient_temp_c > 28)
        h.loc[hot, "cooling_mode"] = "COOLING"
        busy = (h.cooling_mode == "COOLING").to_numpy()
        h.loc[busy, "compressor_speed_pct"] = np.clip(
            np.maximum(h.compressor_speed_pct[busy], 35) + 2.5 * np.clip(dT[busy], 0, None), 0, 100).round(1)
        h.loc[busy, "condenser_fan_pct"] = np.clip(
            np.maximum(h.condenser_fan_pct[busy], 40) + 2.5 * np.clip(dT[busy], 0, None), 0, 100).round(1)
        h.loc[busy & (h.units_running == 0).to_numpy(), "units_running"] = 1
        before = h.hvac_power_kw.astype(float) * F_P
        after = (before * (1 + 0.03 * np.clip(dT, 0, None)) * np.where(busy & hot.to_numpy(), 1.35, 1.0)).clip(lower=1.0)
        h["hvac_power_kw"] = after.round(2)
        h["cop"] = np.where(h.cop.notna(), np.clip(h.cop - 0.04 * dT, 2.2, 6.0), np.nan).round(2)
        h["energy_kwh_step"] = (h.hvac_power_kw * STEP_H).round(4)
        h["cool_runtime_step"] = np.where(h.compressor_speed_pct > 0, round(STEP_H, 4), 0.0)
        h["cum_energy_kwh"] = (0.3 + h.energy_kwh_step.cumsum()).round(1)
        h["compressor_runtime_h"] = h.cool_runtime_step.cumsum().round(2)
        h["Date"] = h.ts.dt.strftime("%Y-%m-%d")
        return h, (after - before).to_numpy()

    # ---------------------------------------------------------------- modules

    def make_modules(self, bms: pd.DataFrame, s: dict) -> dict[date, pd.DataFrame]:
        rng = self.rng
        sample = s["module"].merge(s["bms"][["ts", "Cell_V_Avg_V", "Cell_Temp_Avg_C"]], on="ts")
        dv = (sample.cell_v_avg_v - sample.Cell_V_Avg_V) * 1000
        dt_ = sample.cell_temp_max_c - sample.Cell_Temp_Avg_C
        spread = sample.cell_temp_max_c - sample.cell_temp_min_c
        mods = self.p.modules
        n = len(mods)
        soh = np.array([m[3] for m in mods])
        pack = np.array([m[1] for m in mods])
        off_v = rng.normal(dv.mean(), dv.std(), n) / 1000
        off_t = rng.normal(dt_.mean(), dt_.std() * 0.8, n) + (pack - 1) * 0.25
        sprd = np.clip(rng.normal(spread.mean(), spread.std() * 0.5, n), 0.6, 2.0)
        base_imb = np.clip(rng.normal(sample.imbalance_mv.mean(), 0.5, n), 1.2, 6) * (1 + (99.99 - soh) * 0.5)
        sel = bms.Timestamp.dt.date >= self.module_from
        b = bms[sel].reset_index(drop=True)
        if b.empty:
            return {}
        delta = b.Cell_V_Delta_mV.astype(float).to_numpy()
        shape = delta / np.median(delta)
        T = len(b)
        imb = np.clip(base_imb[None, :] * shape[:, None] * rng.normal(1, 0.08, (T, n)), 0.5, None)
        avg = b.Cell_V_Avg_V.to_numpy()[:, None] + off_v[None, :] + rng.normal(0, 0.0004, (T, n))
        u = rng.uniform(0.35, 0.65, (T, n))
        vmin = avg - imb / 1000 * u
        vmax = vmin + imb / 1000
        tmax = b.Cell_Temp_Avg_C.to_numpy()[:, None] + off_t[None, :] + rng.normal(0, 0.15, (T, n))
        tmin = tmax - sprd[None, :] * rng.normal(1, 0.05, (T, n))
        mode = b.Mode.to_numpy()[:, None]
        balancing = ((mode == "Charging") & (imb > base_imb * 1.1)) | ((mode == "Standby") & (imb > base_imb * 1.35))
        idx = bms.index[sel]
        bms.loc[idx, "Cell_V_Min_V"] = vmin.min(axis=1).round(4)
        bms.loc[idx, "Cell_V_Max_V"] = vmax.max(axis=1).round(4)
        bms.loc[idx, "Cell_V_Delta_mV"] = ((vmax.max(axis=1) - vmin.min(axis=1)) * 1000).round(1)
        bms.loc[idx, "Cell_Temp_Max_C"] = tmax.max(axis=1).round(2)
        bms.loc[idx, "Cell_Temp_Min_C"] = tmin.min(axis=1).round(2)
        frame = pd.DataFrame({
            "module_code": np.tile([m[0] for m in mods], T),
            "ts": np.repeat(b.Timestamp.to_numpy(), n),
            "cell_v_avg_v": avg.ravel().round(4), "cell_v_min_v": vmin.ravel().round(4),
            "cell_v_max_v": vmax.ravel().round(4), "cell_temp_max_c": tmax.ravel().round(2),
            "cell_temp_min_c": tmin.ravel().round(2), "imbalance_mv": imb.ravel().round(1),
            "balancing_active": balancing.ravel(),
        })
        frame["imbalance_mv"] = ((frame.cell_v_max_v - frame.cell_v_min_v) * 1000).round(1)
        return {d: g for d, g in frame.groupby(frame.ts.dt.date)}

    # ---------------------------------------------------------------- alarms

    def module_at(self, pack_index: int, position: int) -> str:
        same = [m for m in self.p.modules if m[1] == pack_index]
        if not same:
            same = self.p.modules
        return next((m[0] for m in same if m[2] == position), same[(position - 1) % len(same)][0])

    def remap_asset(self, code: str) -> str:
        c, P = str(code).upper(), self.p
        n_packs = max(1, len(P.packs))
        if c.startswith("PACK"):
            return P.packs[int(self.rng.integers(0, n_packs))]
        if c.startswith("MOD"):
            position = int("".join(ch for ch in c if ch.isdigit()) or 1)
            return self.module_at(int(self.rng.integers(1, n_packs + 1)), position)
        if c.startswith("PCS"):
            return P.pcs_code
        if c.startswith("EMS"):
            return P.ems_code
        if c.startswith("HVAC"):
            return P.hvac_code
        return P.system_name

    @staticmethod
    def runs(mask: np.ndarray, ts: pd.Series, min_len: int = 2) -> list[tuple]:
        out, start = [], None
        for i, m in enumerate(mask):
            if m and start is None:
                start = i
            if (not m or i == len(mask) - 1) and start is not None:
                stop = i if not m else i + 1
                if stop - start >= min_len:
                    out.append((ts.iloc[start], ts.iloc[stop - 1] + timedelta(minutes=5), start, stop))
                start = None
        return out

    def make_alarms(self, s: dict, plans: list[DayPlan], bms, pcs, hvac, catalog: pd.DataFrame, cols: list) -> pd.DataFrame:
        P, rows = self.p, []
        sample = s["alarm"].copy()
        sample["sday"] = pd.to_datetime(sample.start_time).dt.date
        for p in plans:
            shift = pd.Timestamp(p.day) - pd.Timestamp(p.source)
            for _, a in sample[sample.sday == p.source].iterrows():
                start = pd.Timestamp(a.start_time) + shift
                if p.k == 0 and a.alarm_code in ("DISPATCH_REJECTED", "SETPOINT_DEVIATION", "SOC_Limit", "OVERLOAD"):
                    continue
                if p.window and p.window[0] <= start < p.window[1] and a.source_system in ("BMS", "PCS"):
                    continue
                r = a.to_dict()
                r.update(start_time=start, end_time=(pd.Timestamp(a.end_time) + shift) if pd.notna(a.end_time) else None,
                         acknowledged_at=(pd.Timestamp(a.acknowledged_at) + shift) if pd.notna(a.acknowledged_at) else None,
                         asset_code=self.remap_asset(a.asset_code))
                if str(a.unit) in ("kW", "kVA", "kvar"):
                    for c in ("trigger_value", "threshold_value"):
                        if pd.notna(r[c]):
                            r[c] = round(float(r[c]) * self.F_P * (1 if c == "threshold_value" else max(p.k, 0.35)), 3)
                rows.append(r)
        cat = {r.alarm_code: r for r in catalog.itertuples()}

        def add(code, asset_type, asset, start, end, trigger=None, threshold=None, unit=None, ack=None):
            if code not in cat:
                return
            c = cat[code]
            rows.append(dict(source_system=c.source, asset_type=asset_type, asset_code=asset, alarm_code=code,
                             alarm_type=c.alarm_type, severity=SEVERITY[c.severity_level], severity_level=c.severity_level,
                             description=c.description, probable_cause=c.probable_cause, start_time=start, end_time=end,
                             duration_min=None, trigger_value=trigger, threshold_value=threshold, unit=unit,
                             status="Cleared", acknowledged_by=ack,
                             acknowledged_at=(start + timedelta(minutes=12)) if ack else None))

        n_packs = max(1, len(P.packs))
        for day_idx in sorted(bms.day_idx[bms.scenario == "heat"].unique()):
            g = bms[bms.day_idx == day_idx]
            for st, en, i0, i1 in self.runs((g.Cell_Temp_Max_C > 40.0).to_numpy(), g.Timestamp):
                add("HighCellTemp", "Module", self.module_at(n_packs, int(self.rng.integers(1, 17))), st, en,
                    round(g.Cell_Temp_Max_C.iloc[i0:i1].max(), 2), 40.0, "degC", "control-room")
                bms.loc[g.index[i0:i1], ["Alarm_Level", "Alarm_Flags"]] = [2, "HighCellTemp"]
            gh = hvac[hvac.day_idx == day_idx]
            for st, en, i0, i1 in self.runs((gh.coolant_return_temp_c > 36.0).to_numpy(), gh.ts):
                add("HighCoolantTemp", "HVAC Unit", P.hvac_code, st, en,
                    round(gh.coolant_return_temp_c.iloc[i0:i1].max(), 2), 36.0, "degC", "j.mehta")
                hvac.loc[gh.index[i0:i1], ["alarm_level", "alarm_flags"]] = [2, "HighCoolantTemp"]
            gp = pcs[pcs.index.isin(g.index)]
            for st, en, i0, i1 in self.runs((gp.igbt_temp_c > 60.0).to_numpy(), g.Timestamp):
                add("IGBT_OVERTEMP", "Inverter", P.pcs_code, st, en, round(gp.igbt_temp_c.iloc[i0:i1].max(), 2), 60.0, "degC")
                pcs.loc[gp.index[i0:i1], "alarm_level"] = np.maximum(pcs.loc[gp.index[i0:i1], "alarm_level"], 2)
        for day_idx in sorted(set(hvac.day_idx[hvac.scenario == "monsoon"])):
            gh = hvac[hvac.day_idx == day_idx]
            for st, en, i0, i1 in self.runs((gh.enclosure_humidity_pct > 68).to_numpy(), gh.ts, 3)[:2]:
                add("HighHumidity", "HVAC Unit", P.hvac_code, st, en,
                    round(gh.enclosure_humidity_pct.iloc[i0:i1].max(), 1), 68.0, "%RH")
                hvac.loc[gh.index[i0:i1], ["alarm_level", "alarm_flags"]] = [1, "HighHumidity"]
        if self.cal.low_insulation:
            dip_day = [i for i, p in enumerate(plans) if p.day == self.cal.low_insulation]
            if dip_day:
                g = bms[bms.day_idx == dip_day[0]]
                at = g.index[(g.Timestamp.dt.hour == 5) & (g.Timestamp.dt.minute == 30)][0]
                dip = list(range(at, at + 9))
                values = np.round(np.linspace(2080, 1985, 5).tolist() + np.linspace(2000, 2090, 4).tolist(), 0)
                bms.loc[dip, "Insulation_Res_kOhm"] = values
                bms.loc[dip, ["Alarm_Level", "Alarm_Flags"]] = [3, "LowInsulation"]
                add("LowInsulation", "System", P.system_name, bms.Timestamp[dip[0]],
                    bms.Timestamp[dip[-1]] + timedelta(minutes=5), float(min(values)), 2100.0, "kOhm", "m.rao")
        outage = next((p for p in plans if p.scenario == "outage"), None)
        if outage:
            add("GROUND_FAULT", "Inverter", P.pcs_code, pd.Timestamp(outage.window[0]),
                pd.Timestamp(outage.window[1]) - timedelta(minutes=15), ack="s.iyer")
            add("DISPATCH_REJECTED", "Site Controller", P.ems_code, pd.Timestamp(outage.window[0]) + timedelta(minutes=5),
                pd.Timestamp(outage.window[0]) + timedelta(minutes=40), ack="control-room")
        out = pd.DataFrame(rows)
        if out.empty:
            return pd.DataFrame(columns=cols)
        out["start_time"] = pd.to_datetime(out.start_time)
        out["end_time"] = pd.to_datetime(out.end_time)
        out = out.sort_values(["start_time", "source_system", "alarm_code"]).reset_index(drop=True)
        out["alarm_id"] = [f"{P.prefix}-ALM-{i + 1:05d}" for i in range(len(out))]
        out["duration_min"] = ((out.end_time - out.start_time).dt.total_seconds() / 60).round(0)
        out["status"] = np.where(out.end_time.notna(), "Cleared", "Active")
        out["start_date"] = out.start_time.dt.strftime("%Y-%m-%d")
        return out[cols]

    # ---------------------------------------------------------------- dispatch events

    def make_dispatch(self, s: dict, plans: list[DayPlan], bms: pd.DataFrame, cols: list) -> pd.DataFrame:
        P, F_P, F_SOC = self.p, self.F_P, self.F_SOC
        num = lambda v: 0.0 if v is None or pd.isna(v) else float(v)  # noqa: E731
        src = s["dispatch"].copy()
        src["sday"] = pd.to_datetime(src.effective_from).dt.date
        end_soc = s["bms"].groupby("sday")["SOC_%"].last()
        rows = []

        def event(start, end, mode, note, source="Operator", soc=10.0):
            rows.append(dict(ems_code=P.ems_code, command_code="SET_MODE", dispatch_mode=mode, grid_service="NONE",
                             source=source, issued_at=start - timedelta(minutes=2), effective_from=start, effective_to=end,
                             p_setpoint_kw=0.0, target_soc_pct=None, soc_start_pct=soc, soc_end_pct=soc,
                             ramp_rate_kw_s=0.0, import_kwh=0.0, export_kwh=0.0, net_energy_kwh=0.0, avg_price_mwh=None,
                             revenue_usd=0.0, accepted=True, status="Completed", note=note))

        for p in plans:
            day0 = pd.Timestamp(p.day)
            midnight = day0 + timedelta(days=1)
            shift = day0 - pd.Timestamp(p.source)
            anchor = end_soc[p.source]
            day_soc = bms[bms.Timestamp.dt.date == p.day].set_index("Timestamp")["SOC_%"]
            if p.scenario == "maintenance":
                event(day0, pd.Timestamp(p.window[0]), "STANDBY", None, source="Scheduler", soc=day_soc.iloc[0])
                event(pd.Timestamp(p.window[0]), pd.Timestamp(p.window[1]), "IDLE",
                      "Planned maintenance - plant offline (contactors and PCS breaker open)", soc=day_soc.iloc[0])
                event(pd.Timestamp(p.window[1]), midnight, "STANDBY", "Returned to service after maintenance",
                      source="Scheduler", soc=day_soc.iloc[-1])
                continue
            for _, d in src[src.sday == p.source].iterrows():
                r = d.to_dict()
                start = pd.Timestamp(d.effective_from) + shift
                end = pd.Timestamp(d.effective_to) + shift if pd.notna(d.effective_to) else midnight
                end = min(end, midnight)
                k = p.k
                if p.scenario == "outage":
                    trip, restart = pd.Timestamp(p.window[0]), pd.Timestamp(p.window[1])
                    if trip <= start < restart:
                        continue
                    if start < trip < end:
                        k = (trip - start) / (end - start)
                        end = trip
                        r["note"] = "Interrupted: PCS ground fault trip"
                r.update(ems_code=P.ems_code, issued_at=pd.Timestamp(d.issued_at) + shift, effective_from=start,
                         effective_to=end)
                r["p_setpoint_kw"] = round(float(d.p_setpoint_kw) * F_P * p.k, 1)
                r["ramp_rate_kw_s"] = round(num(d.ramp_rate_kw_s) * F_P, 2)
                for c in ("import_kwh", "export_kwh", "net_energy_kwh", "revenue_usd"):
                    r[c] = round(num(d[c]) * F_P * k, 2)
                for c in ("soc_start_pct", "soc_end_pct", "target_soc_pct"):
                    if pd.notna(d[c]):
                        r[c] = round(float(np.clip(anchor + (float(d[c]) - anchor) * F_SOC * p.k, 5, 100)), 1)
                if p.scenario == "monsoon" and pd.notna(d.avg_price_mwh):
                    r["avg_price_mwh"] = round(float(d.avg_price_mwh) * 0.7, 2)
                r["status"] = "Completed"
                rows.append(r)
            if p.scenario == "outage":
                trip, restart = pd.Timestamp(p.window[0]), pd.Timestamp(p.window[1])
                soc = day_soc[day_soc.index >= trip].iloc[0]
                event(trip, restart, "IDLE", "Forced outage - PCS ground fault, breaker tripped", soc=soc)
                later = [r["effective_from"] for r in rows if restart <= r["effective_from"] < midnight]
                event(restart, min(later) if later else midnight, "STANDBY", "Restart after ground fault cleared",
                      source="Scheduler", soc=soc)
        out = pd.DataFrame(rows).sort_values(["effective_from", "issued_at"]).reset_index(drop=True)
        out["dispatch_id"] = [f"{P.prefix}-DSP-{i + 1:05d}" for i in range(len(out))]
        out["duration_min"] = ((pd.to_datetime(out.effective_to) - pd.to_datetime(out.effective_from))
                               .dt.total_seconds() / 60).round(0)
        out.loc[out.index[-1], ["status", "effective_to", "duration_min"]] = ["Active", None, None]
        out["issued_date"] = pd.to_datetime(out.issued_at).dt.strftime("%Y-%m-%d")
        return out[cols]

    # ---------------------------------------------------------------- run

    def generate(self, out_dir: Path, catalog: pd.DataFrame, log: Callable[[str], None] = lambda m: None,
                 extra: Optional[dict] = None) -> dict:
        started = clock.perf_counter()
        s = read_samples()
        cols = s["cols"]
        log("planning days")
        plans = self.build_plan(s)
        bms = self.make_bms(s, plans)
        hvac, hvac_extra = self.make_hvac(s, plans)
        pcs = self.make_pcs(s, plans, bms)
        ems = self.make_ems(s, plans, bms, hvac_extra)
        log("modules")
        modules = self.make_modules(bms, s)
        alarms = self.make_alarms(s, plans, bms, pcs, hvac, catalog, cols["alarm"])
        dispatch = self.make_dispatch(s, plans, bms, cols["dispatch"])
        bms_out = self.finish_bms(bms, cols["bms"])

        log("writing files")
        clear_generated(out_dir, self.p.short)
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = f"{self.p.short}_{self.start:%Y-%m-%d}_{self.end:%Y-%m-%d}"
        files = []

        def xlsx(name: str, frame: pd.DataFrame, sheet: str, feed: str):
            path = out_dir / name
            with pd.ExcelWriter(path) as w:
                frame.to_excel(w, sheet_name=sheet, index=False)
            files.append({"feed": feed, "file": name, "rows": len(frame)})

        xlsx(f"BESS_BMS_{tag}_5min.xlsx", bms_out, "Data", "BMS")
        xlsx(f"BESS_PCS_{tag}_5min.xlsx", pcs[cols["pcs"]], "Data", "PCS")
        xlsx(f"BESS_EMS_{tag}_5min__{self.p.ems_code}.xlsx", ems[cols["ems"]], "Data", "EMS")
        xlsx(f"BESS_HVAC_{tag}_5min__{self.p.hvac_code}.xlsx", hvac[cols["hvac"]], "Data", "HVAC")
        xlsx(f"BESS_Alarm_{tag}.xlsx", alarms, "Data", "Alarms")
        xlsx(f"BESS_DispatchEvents_{tag}.xlsx", dispatch, "Dispatch Events", "Dispatch events")
        (out_dir / "module").mkdir(exist_ok=True)
        for d, g in modules.items():
            name = f"module/BESS_ModuleTelemetry_{self.p.short}_{d:%Y-%m-%d}.csv"
            g.to_csv(out_dir / name, index=False, date_format="%Y-%m-%d %H:%M:%S")
            files.append({"feed": "Module", "file": name, "rows": len(g)})
        pd.DataFrame([{"date": p.day, "source_sample_day": p.source, "scenario": p.scenario, "dispatch_scale": p.k,
                       "offline_from": p.window[0] if p.window else None, "offline_to": p.window[1] if p.window else None,
                       "notes": "; ".join(p.notes)} for p in plans]).to_csv(out_dir / "scenario_calendar.csv", index=False)
        for f in files:
            f["size"] = (out_dir / f["file"]).stat().st_size
        report = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "site_name": self.p.site_name, "system_name": self.p.system_name,
            "battery_system_id": self.p.battery_system_id, "date_from": self.start.isoformat(),
            "date_to": self.end.isoformat(), "days": len(self.days), "folder": str(out_dir),
            "folder_relative": str(out_dir.relative_to(PROJECT / "input")),
            "climate": self.p.climate.label, "state": self.p.state, "id_prefix": self.p.prefix,
            "ratings": {"rated_kw": self.p.rated_kw, "capacity_kwh": self.p.capacity_kwh,
                        "series_cells": self.p.series_cells, "pcs_ac_voltage_v": self.p.ac_voltage,
                        "modules": len(self.p.modules), "packs": len(self.p.packs), "soh_start": self.soh_start},
            "scenarios": pd.Series([p.scenario for p in plans]).value_counts().to_dict(),
            "scenario_days": [{"date": p.day.isoformat(), "scenario": p.scenario, "notes": "; ".join(p.notes)}
                              for p in plans if p.scenario != "normal"],
            "files": files, "warnings": self.warnings,
            "duration_s": round(clock.perf_counter() - started, 1),
            **(extra or {}),
        }
        (out_dir / "generation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        write_readme(out_dir, report)
        return report


def clear_generated(out_dir: Path, short: str) -> None:
    """Remove the files an earlier generation wrote for this site (the folder holds one generated range)."""
    if not out_dir.exists():
        return
    for pattern in (f"BESS_*_{short}_*.xlsx", "scenario_calendar.csv", "generation_report.json", "README.md"):
        for f in out_dir.glob(pattern):
            f.unlink()
    module_dir = out_dir / "module"
    if module_dir.exists():
        for f in module_dir.glob(f"BESS_ModuleTelemetry_{short}_*.csv"):
            f.unlink()
        if not any(module_dir.iterdir()):
            shutil.rmtree(module_dir, ignore_errors=True)


def write_readme(out_dir: Path, r: dict) -> None:
    feeds: dict[str, list] = {}
    for f in r["files"]:
        feeds.setdefault(f["feed"], []).append(f)
    lines = [f"# {r['site_name']} — generated historical telemetry, {r['date_from']} – {r['date_to']}", "",
             f"Generated {r['generated_at']} by Batch → Historical Generator (`historical_generator/generator.py`) from the "
             "sample files in `input\\historical`. Battery system "
             f"`{r['system_name']}`; climate profile: {r['climate']}; alarm / dispatch ids `{r['id_prefix']}-ALM-` / "
             f"`{r['id_prefix']}-DSP-`.", "",
             "| Feed | Files | Rows |", "|---|---|---|"]
    for feed, items in feeds.items():
        lines.append(f"| {feed} | {len(items)} | {sum(i['rows'] for i in items):,} |")
    lines += ["", "Scenario days:", ""]
    lines += [f"- {d['date']} {d['scenario']}: {d['notes']}" for d in r["scenario_days"]] or ["- none"]
    lines += ["", f"Load them with Batch → Historical Load (folder `{r['folder_relative']}`, system `{r['system_name']}`)."]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_catalog(dsn: Optional[dict] = None) -> pd.DataFrame:
    with psycopg2.connect(**(dsn or database_dsn())) as conn:
        cat = pd.read_sql("SELECT alarm_code, source, alarm_type, severity_level, description, probable_cause "
                          "FROM battery_master.alarm_catalog", conn)
    conn.close()
    return cat


def output_dir(profile: SiteProfile) -> Path:
    return HISTORICAL / profile.folder_name


def default_module_from(start: date, end: date) -> date:
    """Module data covers the last 30 days of the range by default (as for Bhadla: it is ~27,600 rows a day)."""
    return max(start, end - timedelta(days=29))


def check_range(start: date, end: date, module_from: Optional[date] = None) -> date:
    if end < start:
        raise GenerationError("The end date is before the start date")
    if (end - start).days + 1 > MAX_DAYS:
        raise GenerationError(f"At most {MAX_DAYS} days can be generated at once ({(end - start).days + 1} asked)")
    module_from = module_from or default_module_from(start, end)
    if not start <= module_from <= end:
        raise GenerationError(f"Module data must start inside the range ({start} - {end})")
    return module_from


def preview(battery_system_id: int, start: date, end: date, overrides: Optional[dict] = None) -> dict:
    """What a generation would use: the mapping (master data, and the values after the page's overrides), the
    proposed scenario calendar from the climate, the default module range, and what the site's folder holds now."""
    module_from = check_range(start, end)
    master = load_profile(battery_system_id)
    codes = system_codes(battery_system_id)
    profile, changed = apply_overrides(master, overrides, codes)
    cal = Generator(profile, start, end).auto_calendar()
    folder = output_dir(profile)
    existing = [f for f in folder.rglob("*") if f.is_file()] if folder.exists() else []
    mapping = {
        "rated_kw": master.rated_kw, "capacity_kwh": master.capacity_kwh, "series_cells": master.series_cells,
        "ac_voltage": master.ac_voltage, "soh_start": default_soh(master), "pcs_code": master.pcs_code,
        "ems_code": master.ems_code, "hvac_code": master.hvac_code,
        "climate_key": master.state if master.state in CLIMATES else "Other", "prefix": master.prefix,
    }
    return {
        "battery_system_id": battery_system_id, "system_name": master.system_name, "site_name": master.site_name,
        "site_code": master.site_code, "state": master.state, "packs": len(master.packs), "modules": len(master.modules),
        "fields": [{"name": k, "label": v[0], "kind": v[1].__name__, "master": mapping[k]} for k, v in OVERRIDES.items()],
        "choices": {"pcs_code": codes["pcs"], "ems_code": codes["ems"], "hvac_code": codes["hvac"],
                    "climate_key": [{"key": k, "label": c.label, "heat_amp": list(c.heat_amp)}
                                    for k, c in CLIMATES_ALL.items()]},
        "changed": changed, "climate": profile.climate.label, "heat_amp": list(profile.climate.heat_amp),
        "calendar": calendar_to_dict(cal), "date_from": start.isoformat(), "date_to": end.isoformat(),
        "module_from": module_from.isoformat(), "folder": str(folder),
        "folder_relative": str(folder.relative_to(PROJECT / "input")), "existing_files": len(existing),
        "scaling": {"power": round(profile.rated_kw / RATED_KW_OLD, 3),
                    "soc_swing": round(profile.rated_kw / RATED_KW_OLD * CAP_OLD / profile.capacity_kwh, 3),
                    "ac_voltage": round(profile.ac_voltage / AC_V_OLD, 2)},
    }


def generate(battery_system_id: int, start: date, end: date, log: Callable[[str], None] = lambda m: None,
             overrides: Optional[dict] = None, calendar: Optional[dict] = None,
             module_from: Optional[date] = None) -> dict:
    """Generate the files for one battery system and date range (one generation at a time). overrides: mapping
    values for this run (OVERRIDES); calendar: the scenario days (calendar_to_dict format; None = from the climate)."""
    if not _LOCK.acquire(blocking=False):
        raise GenerationError("Another generation is running; try again when it has finished")
    try:
        module_from = check_range(start, end, module_from)
        profile, changed = apply_overrides(load_profile(battery_system_id), overrides)
        cal = calendar_from_dict(calendar, start, end) if calendar is not None else None
        extra = {"overrides": changed, "module_from": module_from.isoformat(),
                 "calendar_source": "page" if cal else "climate"}
        return Generator(profile, start, end, calendar=cal, module_from=module_from).generate(
            output_dir(profile), read_catalog(), log, extra=extra)
    finally:
        _LOCK.release()


def generated_files(battery_system_id: int) -> dict:
    """What the site's folder holds now (the last generation's report, if any, and the files)."""
    profile = load_profile(battery_system_id)
    folder = output_dir(profile)
    report = None
    if (folder / "generation_report.json").exists():
        report = json.loads((folder / "generation_report.json").read_text(encoding="utf-8"))
    files = []
    if folder.exists():
        rows = {f["file"]: f["rows"] for f in (report or {}).get("files", [])}
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not p.name.startswith("~$"):
                rel = p.relative_to(folder).as_posix()
                st = p.stat()
                files.append({"file": rel, "size": st.st_size, "rows": rows.get(rel),
                              "modified": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")})
    return {"folder": str(folder), "folder_relative": str(folder.relative_to(PROJECT / "input")),
            "exists": folder.exists(), "report": report, "files": files}


def profile_summary(profile: SiteProfile) -> dict:
    d = asdict(profile)
    d.pop("modules")
    d["modules"] = len(profile.modules)
    d["climate"] = profile.climate.label
    d["folder"] = profile.folder_name
    return d
