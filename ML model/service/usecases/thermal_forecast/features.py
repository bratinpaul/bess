"""Thermal series per battery system from battery_telemetry.v_thermal_features, cleaned, plus the target definitions.

Targets (one row of TARGETS each): the column, the family (battery-thermal / power-electronics), the asset the value
belongs to (battery system, PCS or HVAC unit), the reference temperature the heat flows to, the heat drivers of the
grey-box model and the default evaluation threshold. The catalog alarm limits (alarm_catalog: HighCellTemp 44 °C,
IGBT_OVERTEMP 80 °C, HighCoolantTemp 38 °C) are never crossed in the sample data, so the default thresholds are
pre-alarm levels the data does reach; both are reported.

Input guards: implausible readings (outside -30..150 °C, or a jump of more than 25 °C in 5 min) become NULL; gaps of up
to 3 readings are interpolated; `stale_min` counts the minutes since the last real reading of each target.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TZ = "Asia/Kolkata"
STEP_MIN = 5
STEPS_PER_DAY = 24 * 60 // STEP_MIN

TARGETS: dict[str, dict] = {
    "cell_temp_max_c": {
        "label": "Cell temperature (max)", "family": "battery_thermal", "asset": "battery_system_id",
        "asset_type": "battery_system", "ref": "bms_coolant_temp_c", "drivers": ["c_rate_sq", "c_rate_abs"],
        "threshold": 40.0, "alarm_code": "HighCellTemp"},
    "coolant_return_temp_c": {
        "label": "Coolant return temperature", "family": "battery_thermal", "asset": "hvac_id", "asset_type": "hvac",
        "ref": "coolant_supply_temp_c", "drivers": ["load_sq", "load_abs"], "threshold": 34.0,
        "alarm_code": "HighCoolantTemp"},
    "igbt_temp_c": {
        "label": "IGBT temperature", "family": "power_electronics", "asset": "pcs_id", "asset_type": "pcs",
        "ref": "inlet_coolant_temp_c", "drivers": ["s_sq", "s_abs"], "threshold": 60.0, "alarm_code": "IGBT_OVERTEMP"},
    "enclosure_temp_c": {
        "label": "Enclosure temperature", "family": "battery_thermal", "asset": "hvac_id", "asset_type": "hvac",
        "ref": "coolant_supply_temp_c", "drivers": ["load_abs"], "threshold": 38.0, "alarm_code": None},
}
FAMILIES = {"battery_thermal": "Battery thermal (cell, coolant, enclosure)", "power_electronics": "Power electronics (IGBT)"}
NUMERIC = ["cell_temp_max_c", "cell_temp_avg_c", "power_kw", "c_rate", "soc_pct", "ambient_temp_c", "bms_coolant_temp_c",
           "igbt_temp_c", "heatsink_temp_c", "inlet_coolant_temp_c", "ac_active_power_kw", "ac_apparent_power_kva",
           "compressor_speed_pct", "coolant_flow_lpm", "coolant_setpoint_c", "coolant_supply_temp_c",
           "coolant_return_temp_c", "hvac_power_kw", "enclosure_temp_c", "p_setpoint_kw", "cell_max_1h_c",
           "power_abs_1h_kw", "igbt_max_1h_c", "apparent_1h_kva", "coolant_return_max_1h_c", "enclosure_max_1h_c",
           "hvac_power_1h_kw"]
TEMPS = ["cell_temp_max_c", "igbt_temp_c", "coolant_return_temp_c", "enclosure_temp_c", "ambient_temp_c",
         "bms_coolant_temp_c", "inlet_coolant_temp_c", "coolant_supply_temp_c", "heatsink_temp_c"]
ROLLING = {"cell_temp_max_c": "cell_max_1h_c", "igbt_temp_c": "igbt_max_1h_c",
           "coolant_return_temp_c": "coolant_return_max_1h_c", "enclosure_temp_c": "enclosure_max_1h_c"}
COOLING_MODES = ["IDLE", "FREE_COOLING", "COOLING", "HEATING"]


@dataclass
class Selection:
    system_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None


def systems(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT a.battery_system_id, bs.system_name, s.site_name, a.pcs_id, a.hvac_id, a.ems_id,
                   bs.rated_power_mw, bs.rated_energy_mwh, p.rated_power_kw AS pcs_rated_kw,
                   p.rated_apparent_kva AS pcs_rated_kva, x.readings, x.date_from, x.date_to
            FROM battery_master.v_thermal_assets a
            JOIN battery_master.battery_system bs ON bs.battery_system_id = a.battery_system_id
            LEFT JOIN battery_master.site s ON s.site_id = bs.site_id
            LEFT JOIN battery_master.pcs p ON p.pcs_id = a.pcs_id
            LEFT JOIN LATERAL (SELECT count(*) AS readings, min(ts)::date AS date_from, max(ts)::date AS date_to
                               FROM battery_telemetry.system_telemetry t WHERE t.system_id = a.battery_system_id) x ON true
            ORDER BY a.battery_system_id""")).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("rated_power_mw", "rated_energy_mwh", "pcs_rated_kw", "pcs_rated_kva"):
            d[k] = _f(d[k])
        d["date_from"] = d["date_from"].isoformat() if d["date_from"] else None
        d["date_to"] = d["date_to"].isoformat() if d["date_to"] else None
        out.append(d)
    return out


def thresholds(engine: Engine) -> dict[str, Optional[float]]:
    """Catalog alarm limits per target (alarm_catalog.threshold)."""
    codes = {t: s["alarm_code"] for t, s in TARGETS.items() if s["alarm_code"]}
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT alarm_code, threshold FROM battery_master.alarm_catalog "
                                      "WHERE alarm_code = ANY(:c)"), {"c": list(codes.values())}).all())
    return {t: _f(rows.get(c)) for t, c in codes.items()}


def series(engine: Engine, system_id: int, date_from=None, date_to=None) -> pd.DataFrame:
    """Cleaned 5-min features of one battery system on a continuous grid; `ok_<target>` marks real readings."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT * FROM battery_telemetry.v_thermal_features
            WHERE battery_system_id = :s
              AND (CAST(:f AS date) IS NULL OR ts >= CAST(:f AS date))
              AND (CAST(:t AS date) IS NULL OR ts < CAST(:t AS date) + 1)
            ORDER BY ts"""), conn, params={"s": system_id, "f": date_from, "t": date_to})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.drop_duplicates("ts").set_index("ts")
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    grid = pd.date_range(df.index.min(), df.index.max(), freq=f"{STEP_MIN}min", tz=TZ)
    df = df.reindex(grid)
    df.index.name = "ts"
    # guards: implausible values and single-step jumps become NULL
    for c in TEMPS:
        v = df[c].where(df[c].between(-30, 150))
        jump = v.diff().abs() > 25
        df[c] = v.mask(jump & (v.shift(-1).diff().abs() > 25))
    for t in TARGETS:
        df[f"ok_{t}"] = df[t].notna()
        last = df.index.to_series().where(df[t].notna()).ffill()
        df[f"stale_min_{t}"] = ((df.index.to_series() - last).dt.total_seconds() / 60).fillna(1e4)
    df[NUMERIC] = df[NUMERIC].interpolate(limit=3, limit_area="inside")
    for c in ("cooling_mode", "dispatch_mode", "grid_service", "pcs_mode"):
        df[c] = df[c].ffill(limit=3)
    for c in ("battery_system_id", "pcs_id", "hvac_id", "ems_id"):
        df[c] = df[c].ffill().bfill()
    return df


def derived(df: pd.DataFrame, rated_kw: float, rated_kva: float, kwh_per_c: float) -> pd.DataFrame:
    """Heat-driver columns (per unit of rating; losses go with the square of the current)."""
    p = df["power_kw"].abs()
    s = df["ac_apparent_power_kva"].abs().fillna(df["ac_active_power_kw"].abs()).fillna(p)
    out = pd.DataFrame(index=df.index)
    out["c_rate_abs"] = df["c_rate"].abs().fillna(p / kwh_per_c)
    out["c_rate_sq"] = out["c_rate_abs"] ** 2
    out["load_abs"] = p / rated_kw
    out["load_sq"] = out["load_abs"] ** 2
    out["s_abs"] = s / rated_kva
    out["s_sq"] = out["s_abs"] ** 2
    return out


def plan_drivers(plan_kw: np.ndarray, rated_kw: float, rated_kva: float, kwh_per_c: float) -> dict[str, np.ndarray]:
    """The same drivers for planned setpoints (|P| ≈ |S| at unity power factor)."""
    p = np.abs(plan_kw)
    return {"c_rate_abs": p / kwh_per_c, "c_rate_sq": (p / kwh_per_c) ** 2, "load_abs": p / rated_kw,
            "load_sq": (p / rated_kw) ** 2, "s_abs": p / rated_kva, "s_sq": (p / rated_kva) ** 2}


def slot_of(ts: pd.DatetimeIndex) -> np.ndarray:
    return ((ts.hour * 60 + ts.minute) // STEP_MIN).to_numpy()


def daily_profile(values: pd.Series) -> np.ndarray:
    """Median per 5-min slot of the day (for the ambient forecast and the typical plan)."""
    prof = values.groupby(slot_of(values.index)).median().reindex(range(STEPS_PER_DAY))
    return prof.interpolate(limit_direction="both").fillna(values.median() if values.notna().any() else 0.0).to_numpy()


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
