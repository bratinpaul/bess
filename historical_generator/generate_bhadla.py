"""Generate historical telemetry for Bhadla BESS Site (Tata Power Renewable Energy Limited), 1 Aug - 30 Sep 2026.

Source: the seven sample files in input/historical (a 1 MW / 2 MWh system, 1-30 Aug, 5-minute data).
Output: input/historical/Bhadla BESS/ - the same file layouts, ready for the telemetry upload pages / bulk APIs:
  BMS, PCS, EMS, HVAC   one xlsx each (sheet "Data"), 61 days x 288 rows
  Module                one CSV per day for 1-30 Sep, all 96 modules (6 packs x 16)
  Alarms                xlsx (sheet "Data"), dispatch events xlsx (sheet "Dispatch Events")
  scenario_calendar.csv the day plan, README.md

How a day is made
  Every generated day copies one sample day (all feeds from the same sample day, so they stay consistent with
  each other) and applies Bhadla's ratings and the day's scenario:
  * sampling: sample days are tagged with the scenarios they contain (frequency regulation, VOLT_VAR, BMS comm
    warning, low insulation, compressor fault, each alarm code ...); each month first gets a set of days that
    covers every tag, the rest are drawn at random (seeded) without repeating until the pool is used up;
  * scaling: power x1.5 (1.5 MW vs 1 MW); capacity 3440.6 kWh (vs 2000), so SOC swings are x0.872; pack voltage
    = cell voltage x 1664 series cells; pack/DC current = P / V; PCS AC side at 33 kV (currents from kVA / V);
    cumulative counters, equivalent cycles and SOH are recomputed over the 61 days;
  * scenarios on top of the sample mix: desert heat (hot afternoons, derating, thermal alarms), monsoon /
    low-price days (cool and humid, compressed prices, shallow cycling), a planned maintenance day and a forced
    outage (PCS ground fault trip, restart in the evening).
Run:  .venv\\Scripts\\python historical_generator\\generate_bhadla.py   (deterministic: seed 2026)
"""
import math
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parent.parent
SAMPLES = PROJECT / "input" / "historical"
OUT = SAMPLES / "Bhadla BESS"
SEED = 2026
rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------- Bhadla master data (static data load)
SYSTEM = "EESL-BESS-S02"
PCS_CODE, EMS_CODE, HVAC_CODE = f"{SYSTEM}-PCS-01", f"{SYSTEM}-EMS-01", f"{SYSTEM}-HVAC-01"
CONTAINER = "CONT-S02-01"
PACKS, MODULES_PER_PACK = 6, 16
START, END = date(2026, 8, 1), date(2026, 9, 30)
MODULE_FROM = date(2026, 9, 1)

RATED_KW_OLD, RATED_KW_NEW = 1000.0, 1500.0
CAP_OLD, CAP_NEW = 2000.0, 3440.6
F_P = RATED_KW_NEW / RATED_KW_OLD  # power
F_SOC = F_P * CAP_OLD / CAP_NEW  # SOC change per interval (same power profile, bigger battery)
CELLS_NEW = 1664  # 104 cells x 16 modules in series
AC_V_OLD, AC_V_NEW = 405.0, 33000.0
BASE_AMBIENT = 3.0  # Bhadla (Thar desert) runs hotter than the sample site
SOH_START = 99.30  # the S02 modules average 99.24 %
STEP_H = 5 / 60

SEVERITY = {0: "Info", 1: "Warning", 2: "Alarm", 3: "Critical"}


# ---------------------------------------------------------------- scenario calendar


@dataclass
class DayPlan:
    day: date
    source: date = None
    scenario: str = "normal"  # normal | heat | monsoon | maintenance | outage
    k: float = 1.0  # dispatch intensity (power / energy scale)
    amp: float = 0.0  # afternoon ambient offset on top of BASE_AMBIENT
    window: tuple = None  # (start, end) datetimes the plant is offline
    notes: list = field(default_factory=list)


HEAT = {date(2026, 8, 27): 7.5, date(2026, 8, 28): 9.0, date(2026, 9, 9): 8.0, date(2026, 9, 10): 9.5,
        date(2026, 9, 11): 6.5, date(2026, 9, 18): 8.5, date(2026, 9, 24): 9.0, date(2026, 9, 25): 7.0}  # heat-wave peaks 42-46 degC
MONSOON = [date(2026, 8, 7), date(2026, 8, 8), date(2026, 8, 14), date(2026, 8, 22), date(2026, 8, 23), date(2026, 9, 4)]
LOW_INSULATION_DAY = date(2026, 8, 8)  # moisture: insulation dips below the limit
MAINTENANCE = (date(2026, 8, 19), time(7, 0), time(17, 0))
OUTAGE = (date(2026, 9, 15), time(16, 30))  # restart before the evening discharge; trip time from the source day


def read_samples() -> dict[str, pd.DataFrame]:
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
    return s


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


def choose_sources(days: list[date], tags: dict[date, set]) -> dict[date, date]:
    """Per month: a set of sample days covering every scenario tag, then random days without repeats."""
    pool_all = sorted(d for d in tags if d != date(2026, 8, 1))  # 1 Aug starts at 55 % SOC: only for 1 Aug
    all_tags = set().union(*(tags[d] for d in pool_all))
    out = {date(2026, 8, 1): date(2026, 8, 1)}
    for month in (8, 9):
        month_days = [d for d in days if d.month == month and d not in out]
        uncovered, cover = set(all_tags), []
        while uncovered:  # greedy set cover
            best = max(pool_all, key=lambda d: (len(tags[d] & uncovered), -pool_all.index(d)))
            if not tags[best] & uncovered:
                break
            cover.append(best)
            uncovered -= tags[best]
        rest = [d for d in pool_all if d not in cover]
        rng.shuffle(rest)
        sequence = cover + rest
        while len(sequence) < len(month_days):
            extra = list(pool_all)
            rng.shuffle(extra)
            sequence += extra
        order = list(month_days)
        rng.shuffle(order)  # spread the covering days over the month
        for d, src in zip(order, sequence):
            out[d] = src
    return out


def build_plan(s: dict) -> list[DayPlan]:
    days = [START + timedelta(days=i) for i in range((END - START).days + 1)]
    sources = choose_sources(days, day_tags(s))
    plans = []
    for d in days:
        p = DayPlan(d, sources[d])
        if d in HEAT:
            p.scenario, p.amp, p.k = "heat", HEAT[d], 0.8
            p.notes.append(f"desert heat: afternoon ambient +{HEAT[d] + BASE_AMBIENT:.1f} degC, power derated to 80 %")
        elif d in MONSOON:
            p.scenario, p.amp, p.k = "monsoon", -5.0, 0.35
            p.notes.append("monsoon: cool, humid, compressed low prices, shallow cycling (35 %)")
            if d == LOW_INSULATION_DAY:
                p.notes.append("moisture: DC insulation below 2100 kOhm for ~45 min")
        elif d == MAINTENANCE[0]:
            p.scenario, p.k = "maintenance", 0.0
            p.window = (datetime.combine(d, MAINTENANCE[1]), datetime.combine(d, MAINTENANCE[2]))
            p.notes.append("planned maintenance 07:00-17:00: contactors and PCS breaker open, plant unavailable")
        plans.append(p)

    # forced outage: SOC is frozen while the plant is off, so trip and restart need the same SOC in the source day
    # (the plant then resumes the day's schedule). Use a September source day that allows that; swap if needed.
    out_plan = next(p for p in plans if p.day == OUTAGE[0])
    restart = OUTAGE[1]
    candidates = [out_plan] + [p for p in plans if p.day.month == 9 and p.scenario == "normal" and p is not out_plan]
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
        raise SystemExit("no sample day allows a forced outage with matching SOC")
    out_plan.scenario = "outage"
    out_plan.window = (datetime.combine(out_plan.day, trip), datetime.combine(out_plan.day, restart))
    out_plan.notes.append(f"forced outage: PCS ground fault trips the breaker at {trip:%H:%M}, restart {restart:%H:%M}; "
                          "SOC held while offline")
    return plans


# ---------------------------------------------------------------- assemble the 61 days of one feed


def assemble(sample: pd.DataFrame, plans: list[DayPlan]) -> pd.DataFrame:
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
            dT = BASE_AMBIENT + p.amp * np.exp(-((hour - 14.5) / 3.5) ** 2)
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


def ramp_counter(steps: pd.Series, start: float = 0.0) -> pd.Series:
    return start + steps.cumsum()


# ---------------------------------------------------------------- BMS


def make_bms(s: dict, plans: list[DayPlan]) -> pd.DataFrame:
    b = assemble(s["bms"], plans)
    src = s["bms"]
    end_soc = src.groupby("sday")["SOC_%"].last()
    rest_v = src.groupby("sday")["Cell_V_Avg_V"].first()
    plan_src = pd.Series([p.source for p in plans])
    anchor = plan_src.map(end_soc).to_numpy()[b.day_idx]
    vrest = plan_src.map(rest_v).to_numpy()[b.day_idx]
    k = b.k.to_numpy()

    soc = np.clip(anchor + (b["SOC_%"] - anchor) * F_SOC * np.where(b.scenario == "outage", 1.0, k), 5, 100)
    # forced outage: SOC frozen at its value when the breaker tripped
    off_idx = np.flatnonzero(b.offline.to_numpy() & (b.scenario == "outage").to_numpy())
    if len(off_idx):
        soc[off_idx] = soc[off_idx[0] - 1]
    b["SOC_%"] = soc.round(2)
    dv = (b.Cell_V_Avg_V - vrest) * (k - 1)
    for c in ("Cell_V_Avg_V", "Cell_V_Min_V", "Cell_V_Max_V"):
        b[c] = (b[c] + dv).round(4)
    b["Power_kW"] = (b.Power_kW * F_P * k).round(1)
    b["Pack_Voltage_V"] = (b.Cell_V_Avg_V * CELLS_NEW).round(1)
    b["Pack_Current_A"] = (b.Power_kW * 1000 / b.Pack_Voltage_V).round(1)
    b["C_Rate"] = (b.Power_kW / CAP_NEW).round(3)
    dT = b.dT.to_numpy()
    heat_rise = np.where(b.scenario == "heat", 0.15 * np.abs(b.Power_kW) / RATED_KW_NEW * 10, 0)
    for c in ("Cell_Temp_Avg_C", "Cell_Temp_Min_C", "Cell_Temp_Max_C"):
        b[c] = (b[c] + np.where(b.scenario == "heat", 0.8, 0.5) * dT + heat_rise).round(2)
    b["Coolant_Temp_C"] = (b.Coolant_Temp_C + 0.4 * dT).round(2)
    b["Ambient_Temp_C"] = (b.Ambient_Temp_C + dT).round(2)
    derate = np.where(b.scenario == "heat", 0.8, 1.0)
    for c in ("Avail_Charge_kW", "Avail_Discharge_kW"):
        b[c] = (b[c] * F_P * derate).round(0)
    b["Charge_kWh_step"] = (b.Charge_kWh_step * F_P * k).round(3)
    b["Discharge_kWh_step"] = (b.Discharge_kWh_step * F_P * k).round(3)

    # monsoon moisture: lower insulation; one dip below the limit
    ins = b.Insulation_Res_kOhm.astype(float).to_numpy()
    ins = np.where(b.scenario == "monsoon", ins * 0.88, ins)
    b["Insulation_Res_kOhm"] = ins.round(0)

    # offline windows (maintenance / forced outage)
    off = b.offline.to_numpy()
    zero_day = (k == 0)
    b.loc[zero_day, "Mode"] = "Standby"
    b.loc[zero_day, "Contactor_Status"] = "Closed"
    b.loc[off, "Mode"] = "Idle"
    b.loc[off, "Contactor_Status"] = "Open"
    b.loc[off, ["Avail_Charge_kW", "Avail_Discharge_kW"]] = 0
    for c in ("Power_kW", "Pack_Current_A", "C_Rate"):
        b.loc[zero_day, c] = 0.0
    b.loc[off & (b.Alarm_Flags != "Normal"), ["Alarm_Level", "Alarm_Flags"]] = [0, "Normal"]
    b.loc[zero_day & (b.Alarm_Flags == "SOC_Limit"), ["Alarm_Level", "Alarm_Flags"]] = [0, "Normal"]
    return b


def finish_bms(b: pd.DataFrame, plans: list[DayPlan]) -> pd.DataFrame:
    b["Cum_Charge_kWh"] = ramp_counter(b.Charge_kWh_step).round(1)
    b["Cum_Discharge_kWh"] = ramp_counter(b.Discharge_kWh_step).round(1)
    b["Equiv_Full_Cycles"] = ((b.Cum_Charge_kWh + b.Cum_Discharge_kWh) / 2 / CAP_NEW).round(2)
    # SOH: cycle ageing (heat days age 1.6x faster) plus calendar ageing, never rising
    d_efc = ((b.Charge_kWh_step + b.Discharge_kWh_step) / 2 / CAP_NEW) * np.where(b.scenario == "heat", 1.6, 1.0)
    days = (b.ts - b.ts.iloc[0]).dt.total_seconds() / 86400
    soh = SOH_START - 0.0045 * d_efc.cumsum() - 0.0012 * days
    b["SOH_%"] = np.minimum.accumulate(soh.to_numpy()).round(2)
    b["Timestamp"] = b.ts
    b["Date"] = b.ts.dt.strftime("%Y-%m-%d")
    b.insert(0, "System_Name", SYSTEM)
    cols = ["System_Name"] + [c for c in s_cols["bms"]]
    return b[cols]


# ---------------------------------------------------------------- PCS


def make_pcs(s: dict, plans: list[DayPlan], bms: pd.DataFrame) -> pd.DataFrame:
    p = assemble(s["pcs"], plans)
    k, dT, off = p.k.to_numpy(), p.dT.to_numpy(), p.offline.to_numpy()
    derate = np.where(p.scenario == "heat", 0.8, 1.0)
    for c in ("ac_active_power_kw", "ac_reactive_power_kvar", "ac_apparent_power_kva", "dc_power_kw"):
        p[c] = (p[c] * F_P * k).round(2)
    for c in ("avail_charge_kw", "avail_discharge_kw"):
        p[c] = (p[c] * F_P * derate).round(0)
    for c in ("ac_voltage_ab_v", "ac_voltage_bc_v", "ac_voltage_ca_v"):
        p[c] = (p[c] * AC_V_NEW / AC_V_OLD).round(1)
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
        p.loc[off & (p.scenario == "maintenance").to_numpy(), "alarm_level"] = 0
        p.loc[off, ["ac_current_a_a", "ac_current_b_a", "ac_current_c_a", "dc_current_a"]] = 0.0
    p["ac_energy_import_kwh"] = ramp_counter(p.import_kwh_step).round(2)
    p["ac_energy_export_kwh"] = ramp_counter(p.export_kwh_step).round(2)
    p["pcs_code"] = PCS_CODE
    p["Date"] = p.ts.dt.strftime("%Y-%m-%d")
    return p[s_cols["pcs"]]


# ---------------------------------------------------------------- EMS


def make_ems(s: dict, plans: list[DayPlan], bms: pd.DataFrame, hvac_extra_kw: np.ndarray) -> pd.DataFrame:
    e = assemble(s["ems"], plans)
    k, dT, off = e.k.to_numpy(), e.dT.to_numpy(), e.offline.to_numpy()
    derate = np.where(e.scenario == "heat", 0.8, 1.0)
    aux_new = (e.aux_load_kw * F_P + hvac_extra_kw).clip(lower=1.0)
    e["poi_active_power_kw"] = (k * F_P * (e.poi_active_power_kw - e.aux_load_kw) + aux_new).round(2)
    e["aux_load_kw"] = aux_new.round(2)
    e["aux_load_pct"] = (aux_new / RATED_KW_NEW * 100).round(2)
    for c in ("p_setpoint_kw", "poi_reactive_power_kvar", "tracking_error_kw"):
        e[c] = (e[c] * F_P * k).round(2)
    for c in ("avail_charge_kw", "avail_discharge_kw"):
        e[c] = (e[c] * F_P * derate).round(0)
    soc = bms["SOC_%"].to_numpy()
    e["plant_soc_pct"] = soc
    src_end = s["bms"].groupby("sday")["SOC_%"].last()
    anchor = pd.Series([p.source for p in plans]).map(src_end).to_numpy()[e.day_idx]
    e["target_soc_pct"] = np.clip(anchor + (e.target_soc_pct - anchor) * F_SOC * np.where(k == 0, 0, 1), 5, 100).round(1)
    e["avail_charge_energy_kwh"] = np.clip((95 - soc) / 100 * CAP_NEW, 0, None).round(1)
    e["avail_discharge_energy_kwh"] = np.clip((soc - 10) / 100 * CAP_NEW, 0, None).round(1)

    # monsoon: compressed, lower prices
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
    e["cum_import_kwh"] = ramp_counter(e.import_kwh_step).round(1)
    e["cum_export_kwh"] = ramp_counter(e.export_kwh_step).round(1)
    e["revenue_cum_usd"] = ramp_counter(e.revenue_step_usd).round(2)
    e["Date"] = e.ts.dt.strftime("%Y-%m-%d")
    return e[s_cols["ems"]]


# ---------------------------------------------------------------- HVAC


def make_hvac(s: dict, plans: list[DayPlan]) -> tuple[pd.DataFrame, np.ndarray]:
    h = assemble(s["hvac"], plans)
    k, dT = h.k.to_numpy(), h.dT.to_numpy()
    load = 1.5 * (0.3 + 0.7 * k)
    h["ambient_temp_c"] = (h.ambient_temp_c + dT).round(2)
    for c in ("coolant_supply_temp_c", "coolant_return_temp_c"):
        h[c] = (h[c] + 0.4 * dT).round(2)
    h["coolant_delta_t_c"] = (h.coolant_return_temp_c - h.coolant_supply_temp_c).round(2)
    h["enclosure_temp_c"] = (h.enclosure_temp_c + 0.5 * dT).round(2)
    mons = (h.scenario == "monsoon").to_numpy()
    heat = (h.scenario == "heat").to_numpy()
    h.loc[mons, "enclosure_humidity_pct"] = np.clip(h.enclosure_humidity_pct[mons] + 22, 0, 92).round(1)
    h.loc[heat, "enclosure_humidity_pct"] = np.clip(h.enclosure_humidity_pct[heat] - 8, 8, 100).round(1)
    for c in ("battery_heat_load_kw", "cooling_capacity_kw", "heat_rejected_kw"):
        h[c] = (h[c] * load).round(2)
    # no free cooling when it is hot outside: the compressor runs
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
    h["cum_energy_kwh"] = ramp_counter(h.energy_kwh_step, 0.3).round(1)
    h["compressor_runtime_h"] = ramp_counter(h.cool_runtime_step).round(2)
    h["Date"] = h.ts.dt.strftime("%Y-%m-%d")
    extra = (after - before).to_numpy()  # extra HVAC power seen as aux load at the POI
    return h, extra


# ---------------------------------------------------------------- modules (September)


def module_serials() -> list[tuple[str, int, float]]:
    """(serial, pack number, SOH) of the 96 Bhadla modules - from the archived static data (or synthesised)."""
    import json
    for path in sorted((PROJECT / "input" / "static" / "archieve").glob("*/bess_static_data.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for site in data["sites"]:
            if site["battery_system"]["serial_number"] == SYSTEM:
                return [(m["serial_number"], p["pack_number"], float(m.get("soh_pct") or 99.2))
                        for p in site["battery_system"]["packs"] for m in p["modules"]]
    return [(f"EESL-S02-P{p:02d}-M{m:02d}", p, 99.2) for p in range(1, PACKS + 1) for m in range(1, MODULES_PER_PACK + 1)]


def make_modules(bms: pd.DataFrame, s: dict) -> dict[date, pd.DataFrame]:
    sample = s["module"].merge(s["bms"][["ts", "Cell_V_Avg_V", "Cell_Temp_Avg_C"]], on="ts")
    dv = (sample.cell_v_avg_v - sample.Cell_V_Avg_V) * 1000
    dt_ = sample.cell_temp_max_c - sample.Cell_Temp_Avg_C
    spread = sample.cell_temp_max_c - sample.cell_temp_min_c
    mods = module_serials()
    n = len(mods)
    soh = np.array([m[2] for m in mods])
    pack = np.array([m[1] for m in mods])
    off_v = rng.normal(dv.mean(), dv.std(), n) / 1000
    off_t = rng.normal(dt_.mean(), dt_.std() * 0.8, n) + (pack - 1) * 0.25
    sprd = np.clip(rng.normal(spread.mean(), spread.std() * 0.5, n), 0.6, 2.0)
    base_imb = np.clip(rng.normal(sample.imbalance_mv.mean(), 0.5, n), 1.2, 6) * (1 + (99.99 - soh) * 0.5)

    b = bms[bms.Timestamp.dt.date >= MODULE_FROM].reset_index(drop=True)
    delta = b.Cell_V_Delta_mV.astype(float).to_numpy()
    shape = delta / np.median(delta)
    T = len(b)
    imb = base_imb[None, :] * shape[:, None] * rng.normal(1, 0.08, (T, n))
    imb = np.clip(imb, 0.5, None)
    avg = b.Cell_V_Avg_V.to_numpy()[:, None] + off_v[None, :] + rng.normal(0, 0.0004, (T, n))
    u = rng.uniform(0.35, 0.65, (T, n))
    vmin = avg - imb / 1000 * u
    vmax = vmin + imb / 1000
    tmax = b.Cell_Temp_Avg_C.to_numpy()[:, None] + off_t[None, :] + rng.normal(0, 0.15, (T, n))
    tmin = tmax - sprd[None, :] * rng.normal(1, 0.05, (T, n))
    mode = b.Mode.to_numpy()[:, None]
    balancing = ((mode == "Charging") & (imb > base_imb * 1.1)) | ((mode == "Standby") & (imb > base_imb * 1.35))

    # the pack envelope reported by the BMS is the envelope of its modules
    idx = bms.index[bms.Timestamp.dt.date >= MODULE_FROM]
    bms.loc[idx, "Cell_V_Min_V"] = vmin.min(axis=1).round(4)
    bms.loc[idx, "Cell_V_Max_V"] = vmax.max(axis=1).round(4)
    bms.loc[idx, "Cell_V_Delta_mV"] = ((vmax.max(axis=1) - vmin.min(axis=1)) * 1000).round(1)
    bms.loc[idx, "Cell_Temp_Max_C"] = tmax.max(axis=1).round(2)
    bms.loc[idx, "Cell_Temp_Min_C"] = tmin.min(axis=1).round(2)

    ts = b.Timestamp.to_numpy()
    frame = pd.DataFrame({
        "module_code": np.tile([m[0] for m in mods], T),
        "ts": np.repeat(ts, n),
        "cell_v_avg_v": avg.ravel().round(4), "cell_v_min_v": vmin.ravel().round(4), "cell_v_max_v": vmax.ravel().round(4),
        "cell_temp_max_c": tmax.ravel().round(2), "cell_temp_min_c": tmin.ravel().round(2),
        "imbalance_mv": imb.ravel().round(1), "balancing_active": balancing.ravel(),
    })
    frame["imbalance_mv"] = ((frame.cell_v_max_v - frame.cell_v_min_v) * 1000).round(1)
    return {d: g for d, g in frame.groupby(frame.ts.dt.date)}


# ---------------------------------------------------------------- alarms


def remap_asset(code: str, asset_type: str) -> str:
    c = str(code).upper()
    if c.startswith("PACK"):
        return f"{CONTAINER}-PACK-{rng.integers(1, PACKS + 1):02d}"
    if c.startswith("MOD"):
        return f"EESL-S02-P{rng.integers(1, PACKS + 1):02d}-M{int(''.join(ch for ch in c if ch.isdigit()) or 1):02d}"
    if c.startswith("PCS"):
        return PCS_CODE
    if c.startswith("EMS"):
        return EMS_CODE
    if c.startswith("HVAC"):
        return HVAC_CODE
    return SYSTEM


def runs(mask: np.ndarray, ts: pd.Series, min_len: int = 2) -> list[tuple]:
    """(start, end) of runs of True at least min_len intervals long."""
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


def make_alarms(s: dict, plans: list[DayPlan], bms, pcs, ems, hvac, catalog: pd.DataFrame) -> pd.DataFrame:
    rows = []
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
                     asset_code=remap_asset(a.asset_code, a.asset_type))
            if str(a.unit) in ("kW", "kVA", "kvar"):
                for c in ("trigger_value", "threshold_value"):
                    if pd.notna(r[c]):
                        r[c] = round(float(r[c]) * F_P * (1 if c == "threshold_value" else max(p.k, 0.35)), 3)
            rows.append(r)

    cat = {r.alarm_code: r for r in catalog.itertuples()}

    def add(code, asset_type, asset, start, end, trigger=None, threshold=None, unit=None, ack=None):
        c = cat[code]
        rows.append(dict(source_system=c.source, asset_type=asset_type, asset_code=asset, alarm_code=code,
                         alarm_type=c.alarm_type, severity=SEVERITY[c.severity_level], severity_level=c.severity_level,
                         description=c.description, probable_cause=c.probable_cause, start_time=start, end_time=end,
                         duration_min=None, trigger_value=trigger, threshold_value=threshold, unit=unit, status="Cleared",
                         acknowledged_by=ack, acknowledged_at=(start + timedelta(minutes=12)) if ack else None))

    # desert heat: thermal alarms where the generated data cross the limits
    for day_idx in sorted(bms.day_idx[bms.scenario == "heat"].unique()):
        g = bms[bms.day_idx == day_idx]
        for st, en, i0, i1 in runs((g.Cell_Temp_Max_C > 40.0).to_numpy(), g.Timestamp):
            peak = g.Cell_Temp_Max_C.iloc[i0:i1].max()
            add("HighCellTemp", "Module", f"EESL-S02-P{PACKS:02d}-M{rng.integers(1, MODULES_PER_PACK + 1):02d}", st, en,
                round(peak, 2), 40.0, "degC", "control-room")
            bms.loc[g.index[i0:i1], ["Alarm_Level", "Alarm_Flags"]] = [2, "HighCellTemp"]
        gh = hvac[hvac.day_idx == day_idx]
        for st, en, i0, i1 in runs((gh.coolant_return_temp_c > 36.0).to_numpy(), gh.ts):
            add("HighCoolantTemp", "HVAC Unit", HVAC_CODE, st, en, round(gh.coolant_return_temp_c.iloc[i0:i1].max(), 2),
                36.0, "degC", "j.mehta")
            hvac.loc[gh.index[i0:i1], ["alarm_level", "alarm_flags"]] = [2, "HighCoolantTemp"]
        gp = pcs[pcs.index.isin(g.index)]
        for st, en, i0, i1 in runs((gp.igbt_temp_c > 60.0).to_numpy(), g.Timestamp):
            add("IGBT_OVERTEMP", "Inverter", PCS_CODE, st, en, round(gp.igbt_temp_c.iloc[i0:i1].max(), 2), 60.0, "degC")
            pcs.loc[gp.index[i0:i1], "alarm_level"] = np.maximum(pcs.loc[gp.index[i0:i1], "alarm_level"], 2)

    # monsoon: humidity, and the insulation dip
    for day_idx in sorted(set(hvac.day_idx[hvac.scenario == "monsoon"])):
        gh = hvac[hvac.day_idx == day_idx]
        for st, en, i0, i1 in runs((gh.enclosure_humidity_pct > 68).to_numpy(), gh.ts, 3)[:2]:
            add("HighHumidity", "HVAC Unit", HVAC_CODE, st, en, round(gh.enclosure_humidity_pct.iloc[i0:i1].max(), 1),
                68.0, "%RH")
            hvac.loc[gh.index[i0:i1], ["alarm_level", "alarm_flags"]] = [1, "HighHumidity"]
    dip_day = [i for i, p in enumerate(plans) if p.day == LOW_INSULATION_DAY][0]
    g = bms[bms.day_idx == dip_day]
    at = g.index[(g.Timestamp.dt.hour == 5) & (g.Timestamp.dt.minute == 30)][0]
    dip = list(range(at, at + 9))
    values = np.round(np.linspace(2080, 1985, 5).tolist() + np.linspace(2000, 2090, 4).tolist(), 0)
    bms.loc[dip, "Insulation_Res_kOhm"] = values
    bms.loc[dip, ["Alarm_Level", "Alarm_Flags"]] = [3, "LowInsulation"]
    add("LowInsulation", "System", SYSTEM, bms.Timestamp[dip[0]], bms.Timestamp[dip[-1]] + timedelta(minutes=5),
        float(min(values)), 2100.0, "kOhm", "m.rao")

    # forced outage: ground fault trips the PCS; the EMS can't deliver the running dispatch
    p = next(p for p in plans if p.scenario == "outage")
    add("GROUND_FAULT", "Inverter", PCS_CODE, pd.Timestamp(p.window[0]), pd.Timestamp(p.window[1]) - timedelta(minutes=15),
        ack="s.iyer")
    add("DISPATCH_REJECTED", "Site Controller", EMS_CODE, pd.Timestamp(p.window[0]) + timedelta(minutes=5),
        pd.Timestamp(p.window[0]) + timedelta(minutes=40), ack="control-room")

    out = pd.DataFrame(rows)
    out["start_time"] = pd.to_datetime(out.start_time)
    out["end_time"] = pd.to_datetime(out.end_time)
    out = out.sort_values(["start_time", "source_system", "alarm_code"]).reset_index(drop=True)
    out["alarm_id"] = [f"BHD-ALM-{i + 1:05d}" for i in range(len(out))]
    out["duration_min"] = ((out.end_time - out.start_time).dt.total_seconds() / 60).round(0)
    out["status"] = np.where(out.end_time.notna(), "Cleared", "Active")
    out["start_date"] = out.start_time.dt.strftime("%Y-%m-%d")
    return out[s_cols["alarm"]]


# ---------------------------------------------------------------- dispatch events


def num(v) -> float:
    return 0.0 if v is None or pd.isna(v) else float(v)


def make_dispatch(s: dict, plans: list[DayPlan], bms: pd.DataFrame) -> pd.DataFrame:
    src = s["dispatch"].copy()
    src["sday"] = pd.to_datetime(src.effective_from).dt.date
    end_soc = s["bms"].groupby("sday")["SOC_%"].last()
    rows = []

    def event(start, end, mode, note, command="SET_MODE", source="Operator", soc=10.0):
        rows.append(dict(ems_code=EMS_CODE, command_code=command, dispatch_mode=mode, grid_service="NONE", source=source,
                         issued_at=start - timedelta(minutes=2), effective_from=start, effective_to=end, p_setpoint_kw=0.0,
                         target_soc_pct=None, soc_start_pct=soc, soc_end_pct=soc, ramp_rate_kw_s=0.0, import_kwh=0.0,
                         export_kwh=0.0, net_energy_kwh=0.0, avg_price_mwh=None, revenue_usd=0.0, accepted=True,
                         status="Completed", note=note))

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
            end = min(end, midnight)  # the next day comes from another sample day
            k = p.k
            if p.scenario == "outage":
                trip, restart = pd.Timestamp(p.window[0]), pd.Timestamp(p.window[1])
                if trip <= start < restart:
                    continue  # never issued: the plant was down
                if start < trip < end:
                    share = (trip - start) / (end - start)
                    end, k = trip, share
                    r["note"] = "Interrupted: PCS ground fault trip"
            r.update(ems_code=EMS_CODE, issued_at=pd.Timestamp(d.issued_at) + shift, effective_from=start, effective_to=end)
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
            later = [r["effective_from"] for r in rows if r["effective_from"] >= restart and r["effective_from"] < midnight]
            event(restart, min(later) if later else midnight, "STANDBY", "Restart after ground fault cleared",
                  source="Scheduler", soc=soc)
    out = pd.DataFrame(rows).sort_values(["effective_from", "issued_at"]).reset_index(drop=True)
    out["dispatch_id"] = [f"BHD-DSP-{i + 1:05d}" for i in range(len(out))]
    out["duration_min"] = ((pd.to_datetime(out.effective_to) - pd.to_datetime(out.effective_from))
                           .dt.total_seconds() / 60).round(0)
    out.loc[out.index[-1], ["status", "effective_to", "duration_min"]] = ["Active", None, None]  # still running
    out["issued_date"] = pd.to_datetime(out.issued_at).dt.strftime("%Y-%m-%d")
    return out[s_cols["dispatch"]]


# ---------------------------------------------------------------- main


s_cols: dict[str, list[str]] = {}


def main() -> None:
    import psycopg2
    s = read_samples()
    s_cols.update({
        "bms": [c for c in pd.read_excel(SAMPLES / "BESS_BMS_SampleData_30d_5min.xlsx", nrows=0).columns],
        "pcs": list(pd.read_excel(SAMPLES / "BESS_PCS_SampleData_30d_5min.xlsx", nrows=0).columns),
        "ems": list(pd.read_excel(SAMPLES / "BESS_EMS_SampleData_30d_5min.xlsx", nrows=0).columns),
        "hvac": list(pd.read_excel(SAMPLES / "BESS_HVAC_SampleData_30d_5min.xlsx", nrows=0).columns),
        "alarm": list(s["alarm"].columns),
        "dispatch": list(s["dispatch"].columns),
    })
    from bess_common.db_settings import psycopg2_dsn  # DATABASE_URL from env / backend/.env
    with psycopg2.connect(**psycopg2_dsn()) as conn:
        catalog = pd.read_sql("SELECT alarm_code, source, alarm_type, severity_level, description, probable_cause "
                              "FROM battery_master.alarm_catalog", conn)
    plans = build_plan(s)

    bms = make_bms(s, plans)
    hvac, hvac_extra = make_hvac(s, plans)
    pcs = make_pcs(s, plans, bms)
    pcs_full = pcs.copy()
    ems = make_ems(s, plans, bms, hvac_extra)
    bms_full = bms.copy()
    bms_full["Timestamp"] = bms_full.ts
    modules = make_modules(bms_full, s)
    pcs_full["day_idx"], pcs_full["scenario"] = bms.day_idx.to_numpy(), bms.scenario.to_numpy()
    alarms = make_alarms(s, plans, bms_full, pcs_full, ems, hvac, catalog)
    dispatch = make_dispatch(s, plans, bms_full)
    bms_out = finish_bms(bms_full, plans)
    pcs_out = pcs_full[s_cols["pcs"]]
    hvac_out = hvac[s_cols["hvac"]]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "module").mkdir(exist_ok=True)
    tag = "Bhadla_2026-08-01_2026-09-30_5min"
    with pd.ExcelWriter(OUT / f"BESS_BMS_{tag}.xlsx") as w:
        bms_out.to_excel(w, sheet_name="Data", index=False)
    with pd.ExcelWriter(OUT / f"BESS_PCS_{tag}.xlsx") as w:
        pcs_out.to_excel(w, sheet_name="Data", index=False)
    with pd.ExcelWriter(OUT / f"BESS_EMS_{tag}__{EMS_CODE}.xlsx") as w:
        ems.to_excel(w, sheet_name="Data", index=False)
    with pd.ExcelWriter(OUT / f"BESS_HVAC_{tag}__{HVAC_CODE}.xlsx") as w:
        hvac_out.to_excel(w, sheet_name="Data", index=False)
    with pd.ExcelWriter(OUT / "BESS_Alarm_Bhadla_2026-08-01_2026-09-30.xlsx") as w:
        alarms.to_excel(w, sheet_name="Data", index=False)
    with pd.ExcelWriter(OUT / "BESS_DispatchEvents_Bhadla_2026-08-01_2026-09-30.xlsx") as w:
        dispatch.to_excel(w, sheet_name="Dispatch Events", index=False)
    for d, g in modules.items():
        g.to_csv(OUT / "module" / f"BESS_ModuleTelemetry_Bhadla_{d:%Y-%m-%d}.csv", index=False,
                 date_format="%Y-%m-%d %H:%M:%S")
    pd.DataFrame([{"date": p.day, "source_sample_day": p.source, "scenario": p.scenario, "dispatch_scale": p.k,
                   "offline_from": p.window[0] if p.window else None, "offline_to": p.window[1] if p.window else None,
                   "notes": "; ".join(p.notes)} for p in plans]).to_csv(OUT / "scenario_calendar.csv", index=False)
    print(f"BMS {len(bms_out)} | PCS {len(pcs_out)} | EMS {len(ems)} | HVAC {len(hvac_out)} | alarms {len(alarms)} | "
          f"dispatch {len(dispatch)} | module files {len(modules)} x {len(next(iter(modules.values())))} rows")
    print(pd.Series([p.scenario for p in plans]).value_counts().to_dict())


if __name__ == "__main__":
    main()
