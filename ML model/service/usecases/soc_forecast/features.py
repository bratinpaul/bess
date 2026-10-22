"""SOC series, dispatch plans and the coulomb-counting physics.

Series (5 min, plant time): ems_telemetry plant SOC, setpoint, POI power, aux load, AGC, dispatch mode / grid service,
target SOC; system_telemetry DC power and C-rate; hvac_telemetry HVAC power. Gaps are not filled beyond two readings:
an origin is only used when its history and (for backtests) its horizon are gap-free.

Plans: the setpoint (kW, AC side, + charge / - discharge) for every future 5-min step:
  scheduled   dispatch_event commands whose [time, effective_to) covers the step; steps no command covers fall back
              to the typical day
  typical     the EMS's median setpoint per 5-min slot of the day over its training period (what it usually does)
  custom      blocks entered in the viewer (what-if)

Physics (per EMS, fitted on the training rows): SOC[k+1] = clip(SOC[k] + c * P * Δt, SOC min, SOC max) with
c = c_chg (%/kWh) when P > 0 and c_dis when P < 0. c_chg and c_dis differ: charging a percent takes more energy than
a discharged percent returns (battery and conversion losses), so their ratio is the effective round-trip.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TZ = "Asia/Kolkata"
STEP_MIN = 5
DT_H = STEP_MIN / 60
STEPS_PER_DAY = 24 * 60 // STEP_MIN
HISTORY_STEPS = 12  # an origin needs the last hour

MODES = ["STANDBY", "IDLE", "SCHEDULED_CHARGE", "ENERGY_ARBITRAGE", "FREQUENCY_REGULATION"]
SERVICES = ["NONE", "ARBITRAGE", "FREQ_REG"]

_SERIES_SQL = """
SELECT e.ts, e.plant_soc_pct AS soc, e.target_soc_pct AS target_soc, e.p_setpoint_kw AS sp,
       e.poi_active_power_kw AS poi_kw, e.aux_load_kw AS aux_kw, e.agc_signal AS agc,
       e.dispatch_mode AS mode, e.grid_service AS gs, s.power_kw AS dc_kw, s.c_rate,
       h.hvac_power_kw AS hvac_kw
FROM battery_telemetry.ems_telemetry e
JOIN battery_master.ems_controller c ON c.ems_id = e.ems_id
LEFT JOIN battery_telemetry.system_telemetry s ON s.system_id = c.battery_system_id AND s.ts = e.ts
LEFT JOIN battery_telemetry.hvac_telemetry h
       ON h.hvac_id = (SELECT min(hvac_id) FROM battery_master.hvac_unit WHERE battery_system_id = c.battery_system_id)
      AND h.ts = e.ts
WHERE e.ems_id = :ems AND e.plant_soc_pct IS NOT NULL
  AND (CAST(:f AS date) IS NULL OR e.ts >= CAST(:f AS date))
  AND (CAST(:t AS date) IS NULL OR e.ts < CAST(:t AS date) + 1)
ORDER BY e.ts
"""


@dataclass
class Selection:
    ems_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None


def ems_units(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT e.ems_id, e.ems_code, e.battery_system_id, bs.system_name, s.site_name, bs.rated_energy_mwh,
                   bs.rated_power_mw, count(t.ts) AS readings, min(t.ts)::date AS date_from, max(t.ts)::date AS date_to,
                   (SELECT count(*) FROM battery_telemetry.dispatch_event d WHERE d.ems_id = e.ems_id) AS commands
            FROM battery_master.ems_controller e
            LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = e.battery_system_id
            LEFT JOIN battery_master.site s ON s.site_id = bs.site_id
            LEFT JOIN battery_telemetry.ems_telemetry t ON t.ems_id = e.ems_id AND t.plant_soc_pct IS NOT NULL
            GROUP BY e.ems_id, e.ems_code, e.battery_system_id, bs.system_name, s.site_name, bs.rated_energy_mwh,
                     bs.rated_power_mw
            ORDER BY e.ems_id""")).mappings().all()
    return [{**dict(r), "rated_energy_mwh": _f(r["rated_energy_mwh"]), "rated_power_mw": _f(r["rated_power_mw"]),
             "date_from": r["date_from"].isoformat() if r["date_from"] else None,
             "date_to": r["date_to"].isoformat() if r["date_to"] else None} for r in rows]


def series(engine: Engine, ems_id: int, date_from=None, date_to=None) -> pd.DataFrame:
    """5-min readings on a continuous grid; `ok` marks real readings (short gaps of <= 2 steps are interpolated)."""
    with engine.connect() as conn:
        df = pd.read_sql(text(_SERIES_SQL), conn, params={"ems": ems_id, "f": date_from, "t": date_to})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.drop_duplicates("ts").set_index("ts")
    num = ["soc", "target_soc", "sp", "poi_kw", "aux_kw", "agc", "dc_kw", "c_rate", "hvac_kw"]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    grid = pd.date_range(df.index.min(), df.index.max(), freq=f"{STEP_MIN}min", tz=TZ)
    df = df.reindex(grid)
    df.index.name = "ts"
    df["ok"] = df["soc"].notna()
    df[num] = df[num].interpolate(limit=2, limit_area="inside")
    df[["mode", "gs"]] = df[["mode", "gs"]].ffill(limit=2)
    df["ok"] = df["soc"].notna()
    df["agc"] = df["agc"].fillna(0.0)
    df["hvac_kw"] = df["hvac_kw"].fillna(df["hvac_kw"].median() if df["hvac_kw"].notna().any() else 0.0)
    return df


def schedule(engine: Engine, ems_id: int) -> pd.DataFrame:
    """dispatch_event commands of an EMS: [start, end) and the setpoint."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT time AS start, effective_to AS "end", p_setpoint_kw AS sp, dispatch_mode AS mode,
                   grid_service AS gs, command_code, source, status, dispatch_id
            FROM battery_telemetry.dispatch_event
            WHERE ems_id = :ems AND COALESCE(accepted, true) AND effective_to > time
            ORDER BY time"""), conn, params={"ems": ems_id})
    if df.empty:
        return df
    for c in ("start", "end"):
        df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(TZ)
    df["sp"] = pd.to_numeric(df["sp"], errors="coerce").astype(float).fillna(0.0)
    return df


def schedule_grid(sched: pd.DataFrame, index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Scheduled setpoint at every timestamp of `index` (NaN where no command covers it) and the command's mode."""
    sp = np.full(len(index), np.nan)
    mode = np.full(len(index), None, dtype=object)
    if sched.empty or not len(index):
        return sp, mode
    t = index.asi8
    for r in sched.itertuples():
        m = (t >= r.start.value) & (t < r.end.value)
        sp[m] = r.sp
        mode[m] = r.mode
    return sp, mode


def typical_profile(df: pd.DataFrame) -> np.ndarray:
    """Median setpoint per 5-min slot of the day (STEPS_PER_DAY values)."""
    slot = (df.index.hour * 60 + df.index.minute) // STEP_MIN
    prof = df["sp"].groupby(slot).median().reindex(range(STEPS_PER_DAY))
    return prof.interpolate(limit_direction="both").fillna(0.0).to_numpy()


def slot_of(ts: pd.DatetimeIndex) -> np.ndarray:
    return ((ts.hour * 60 + ts.minute) // STEP_MIN).to_numpy()


# ---------------------------------------------------------------- physics


@dataclass
class Physics:
    c_chg: float  # SOC % per kWh of positive setpoint
    c_dis: float  # SOC % per kWh of negative setpoint (discharged)
    soc_min: float
    soc_max: float
    drift: float = 0.0  # SOC % per step at zero setpoint

    @property
    def cap_chg_kwh(self) -> float:
        return 100.0 / self.c_chg

    @property
    def cap_dis_kwh(self) -> float:
        return 100.0 / self.c_dis

    @property
    def round_trip(self) -> float:
        return self.c_dis and self.c_chg / self.c_dis

    def roll(self, soc0: np.ndarray, plan: np.ndarray) -> np.ndarray:
        """Trajectories for many origins at once: soc0 (n,), plan (n, H) kW -> SOC (n, H) after each step."""
        out = np.empty_like(plan, dtype=float)
        soc = soc0.astype(float).copy()
        for k in range(plan.shape[1]):
            p = plan[:, k]
            d = np.where(p > 0, self.c_chg * p, np.where(p < 0, self.c_dis * p, 0.0)) * DT_H + self.drift
            soc = np.clip(soc + d, self.soc_min, self.soc_max)
            out[:, k] = soc
        return out

    def to_dict(self) -> dict:
        return {"c_chg": self.c_chg, "c_dis": self.c_dis, "soc_min": self.soc_min, "soc_max": self.soc_max,
                "drift": self.drift, "cap_chg_kwh": self.cap_chg_kwh, "cap_dis_kwh": self.cap_dis_kwh,
                "round_trip": self.round_trip}


def fit_physics(df: pd.DataFrame, soc_limits: Optional[tuple[float, float]] = None) -> Physics:
    """Robust (median) %/kWh per direction from consecutive real readings; limits from the 0.5 / 99.5 percentiles."""
    d = df[df["ok"] & df["ok"].shift(-1, fill_value=False)]
    dsoc = (df["soc"].shift(-1) - df["soc"]).loc[d.index]
    sp = d["sp"]
    chg = sp > 10
    dis = sp < -10
    # only steps that didn't sit on a limit (the battery stops moving there)
    lo, hi = np.nanpercentile(df["soc"], [0.5, 99.5])
    free = (d["soc"] > lo + 1) & (d["soc"] < hi - 1)
    c_chg = float((dsoc[chg & free] / (sp[chg & free] * DT_H)).median()) if (chg & free).sum() > 10 else 100 / 3500
    c_dis = float((dsoc[dis & free] / (sp[dis & free] * DT_H)).median()) if (dis & free).sum() > 10 else 100 / 3500
    idle = sp.abs() <= 10
    drift = float(dsoc[idle].clip(-1, 1).mean()) if idle.sum() > 10 else 0.0
    soc_min, soc_max = soc_limits if soc_limits else (float(round(lo, 1)), float(round(hi, 1)))
    return Physics(c_chg=max(c_chg, 1e-6), c_dis=max(c_dis, 1e-6), soc_min=soc_min, soc_max=soc_max, drift=drift)


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
