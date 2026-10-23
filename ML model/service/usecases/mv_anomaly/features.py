"""One wide feature row per (system, 5-min ts): BMS + PCS + HVAC + EMS telemetry time-aligned on the 5-min grid,
derived signals, the operating regime, and the rule checks (frozen / missing sensors) that never feed the models.

    load_frame()      raw joined telemetry for one system and window (TimescaleDB time_bucket on every hypertable)
    derive()          ΔV, ΔT, temperature / IGBT rise, PCS loss, HVAC setpoint error, dispatch error, I² load ...
    rule_flags()      frozen (stuck) and missing sensors - an anomaly by themselves, masked out of the model inputs
    Residuals         fitted on the training rows only (they are part of the model):
                        dv_resid_mv          ΔV − typical ΔV for the regime and SOC band
                        temp_rise_resid_c    (cell T − coolant T) − a + b·I²(30 min) + c·ambient
                        igbt_rise_resid_c    (IGBT − inlet coolant) − a + b·|S| + c·|S|²
    labels()          alarm_event intervals (evaluation only) and the training exclusions
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import UseCaseError

REGIMES = ["Charging", "Discharging", "Idle", "Standby"]
SOC_BANDS = [0, 20, 40, 60, 80, 101]
SOC_BAND_LABELS = ["0-20", "20-40", "40-60", "60-80", "80-100"]

# model input features: key -> (label shown to operators, group)
FEATURES: dict[str, tuple[str, str]] = {
    "pack_voltage_v": ("pack voltage", "bms"),
    "pack_current_a": ("pack current", "bms"),
    "power_kw": ("battery power", "bms"),
    "c_rate": ("C-rate", "bms"),
    "soc_pct": ("SOC", "bms"),
    "cell_v_avg_v": ("cell voltage avg", "bms"),
    "cell_v_min_v": ("cell voltage min", "bms"),
    "cell_v_max_v": ("cell voltage max", "bms"),
    "dv_mv": ("cell-voltage spread ΔV", "bms"),
    "cell_temp_avg_c": ("cell temperature avg", "bms"),
    "cell_temp_min_c": ("cell temperature min", "bms"),
    "cell_temp_max_c": ("cell temperature max", "bms"),
    "dt_c": ("cell-temperature spread ΔT", "bms"),
    "ac_active_power_kw": ("PCS AC power", "pcs"),
    "dc_power_kw": ("PCS DC power", "pcs"),
    "efficiency_pct": ("PCS efficiency", "pcs"),
    "pcs_loss_kw": ("PCS conversion loss", "pcs"),
    "igbt_temp_c": ("IGBT temperature", "pcs"),
    "ac_reactive_power_kvar": ("PCS reactive power", "pcs"),
    "hvac_power_kw": ("HVAC cooling power", "hvac"),
    "hvac_setpoint_err_c": ("coolant setpoint error", "hvac"),
    "coolant_return_temp_c": ("coolant return temperature", "hvac"),
    "dispatch_error_kw": ("dispatch tracking error (delivered − commanded)", "ems"),
    "dv_resid_mv": ("ΔV vs expected for SOC / regime", "residual"),
    "temp_rise_resid_c": ("cell temperature vs expected for I²R load", "residual"),
    "igbt_rise_resid_c": ("IGBT temperature vs expected for load", "residual"),
}
GROUPS = {
    "bms": "BMS - pack, cells",
    "pcs": "PCS - power, efficiency, IGBT",
    "hvac": "HVAC - cooling",
    "ems": "EMS - dispatch tracking",
    "residual": "Residuals (measured − expected)",
}
CONTEXT_LABELS = {"regime": "operating regime", "soc_band": "SOC band"}

# frozen-sensor rule: signal -> only check while current flows (a resting pack voltage / SOC legitimately stays put)
FROZEN_SIGNALS = {
    "pack_voltage_v": True, "soc_pct": True, "cell_v_avg_v": True, "cell_temp_avg_c": False,
    "cell_temp_max_c": False, "igbt_temp_c": False, "hvac_power_kw": False, "coolant_return_temp_c": False,
}
# missing-sensor rule: a NULL here is a fault (efficiency is NULL by design while the PCS is not converting)
REQUIRED_SIGNALS = ["pack_voltage_v", "pack_current_a", "soc_pct", "cell_v_max_v", "cell_v_min_v", "cell_temp_max_c",
                    "igbt_temp_c", "hvac_power_kw", "p_setpoint_kw", "poi_active_power_kw"]

SQL = """
WITH s AS (
    SELECT time_bucket('5 minutes', ts) AS ts, system_id, last(mode_code, ts) AS mode_code,
           avg(pack_voltage_v) AS pack_voltage_v, avg(pack_current_a) AS pack_current_a, avg(power_kw) AS power_kw,
           avg(c_rate) AS c_rate, avg(soc_bms_pct) AS soc_pct, avg(soh_pct) AS soh_pct,
           avg(cell_v_avg_v) AS cell_v_avg_v, avg(cell_v_min_v) AS cell_v_min_v, avg(cell_v_max_v) AS cell_v_max_v,
           avg(cell_temp_avg_c) AS cell_temp_avg_c, avg(cell_temp_min_c) AS cell_temp_min_c,
           avg(cell_temp_max_c) AS cell_temp_max_c, avg(ambient_temp_c) AS ambient_temp_c,
           max(alarm_level) AS bms_alarm
    FROM battery_telemetry.system_telemetry
    WHERE system_id = :sid AND ts >= :t0 AND ts < :t1
    GROUP BY 1, 2
), p AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, last(t.mode_code, t.ts) AS pcs_mode,
           avg(t.ac_active_power_kw) AS ac_active_power_kw, avg(t.dc_power_kw) AS dc_power_kw,
           avg(t.efficiency_pct) AS efficiency_pct, avg(t.igbt_temp_c) AS igbt_temp_c,
           avg(t.inlet_coolant_temp_c) AS inlet_coolant_temp_c, avg(t.ac_reactive_power_kvar) AS ac_reactive_power_kvar,
           avg(t.ac_apparent_power_kva) AS ac_apparent_power_kva, max(t.alarm_level) AS pcs_alarm
    FROM battery_telemetry.pcs_telemetry t JOIN battery_master.pcs m ON m.pcs_id = t.pcs_id
    WHERE m.system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
), h AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, avg(t.hvac_power_kw) AS hvac_power_kw,
           avg(t.coolant_setpoint_c) AS coolant_setpoint_c, avg(t.coolant_supply_temp_c) AS coolant_supply_temp_c,
           avg(t.coolant_return_temp_c) AS coolant_return_temp_c, max(t.alarm_level) AS hvac_alarm
    FROM battery_telemetry.hvac_telemetry t JOIN battery_master.hvac_unit m ON m.hvac_id = t.hvac_id
    WHERE m.battery_system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
), e AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, sum(t.p_setpoint_kw) AS p_setpoint_kw,
           sum(t.poi_active_power_kw) AS poi_active_power_kw, max(t.alarm_level) AS ems_alarm
    FROM battery_telemetry.ems_telemetry t JOIN battery_master.ems_controller m ON m.ems_id = t.ems_id
    WHERE m.battery_system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
)
SELECT s.*, p.pcs_mode, p.ac_active_power_kw, p.dc_power_kw, p.efficiency_pct, p.igbt_temp_c, p.inlet_coolant_temp_c,
       p.ac_reactive_power_kvar, p.ac_apparent_power_kva, p.pcs_alarm,
       h.hvac_power_kw, h.coolant_setpoint_c, h.coolant_supply_temp_c, h.coolant_return_temp_c, h.hvac_alarm,
       e.p_setpoint_kw, e.poi_active_power_kw, e.ems_alarm
FROM s
LEFT JOIN p ON p.ts = s.ts
LEFT JOIN h ON h.ts = s.ts
LEFT JOIN e ON e.ts = s.ts
ORDER BY s.ts
"""


class FeatureError(UseCaseError):
    code = "MV_ANOMALY_FEATURES_REJECTED"


@dataclass
class Window:
    system_id: int
    date_from: Optional[date] = None
    date_to: Optional[date] = None


def systems(engine: Engine) -> list[dict]:
    """Battery systems with BMS telemetry, their window and which subsystems report."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT bs.battery_system_id, bs.system_name, si.site_name,
                   CAST(min(t.ts) AS date) AS date_from, CAST(max(t.ts) AS date) AS date_to, count(*) AS rows,
                   EXISTS (SELECT 1 FROM battery_master.pcs p JOIN battery_telemetry.pcs_telemetry pt ON pt.pcs_id = p.pcs_id
                           WHERE p.system_id = bs.battery_system_id LIMIT 1) AS has_pcs,
                   EXISTS (SELECT 1 FROM battery_master.hvac_unit u JOIN battery_telemetry.hvac_telemetry ht
                           ON ht.hvac_id = u.hvac_id WHERE u.battery_system_id = bs.battery_system_id LIMIT 1) AS has_hvac,
                   EXISTS (SELECT 1 FROM battery_master.ems_controller c JOIN battery_telemetry.ems_telemetry et
                           ON et.ems_id = c.ems_id WHERE c.battery_system_id = bs.battery_system_id LIMIT 1) AS has_ems,
                   (SELECT count(*) FROM battery_telemetry.alarm_event a WHERE a.battery_system_id = bs.battery_system_id)
                       AS alarms
            FROM battery_master.battery_system bs
            JOIN battery_telemetry.system_telemetry t ON t.system_id = bs.battery_system_id
            LEFT JOIN battery_master.site si ON si.site_id = bs.site_id
            GROUP BY bs.battery_system_id, bs.system_name, si.site_name
            ORDER BY bs.battery_system_id""")).mappings().all()
    return [dict(r) for r in rows]


def _bounds(w: Window) -> tuple:
    t0 = pd.Timestamp(w.date_from, tz="Asia/Kolkata") if w.date_from else pd.Timestamp("2000-01-01", tz="Asia/Kolkata")
    t1 = (pd.Timestamp(w.date_to, tz="Asia/Kolkata") + pd.Timedelta(days=1)) if w.date_to \
        else pd.Timestamp("2100-01-01", tz="Asia/Kolkata")
    return t0, t1


def load_frame(engine: Engine, w: Window, lookback_intervals: int = 0) -> pd.DataFrame:
    """Raw joined telemetry, one row per 5-min bucket; `lookback_intervals` extra rows before the window
    (temporal models need history) are marked in_window = False."""
    t0, t1 = _bounds(w)
    t_load = t0 - pd.Timedelta(minutes=5 * lookback_intervals)
    with engine.connect() as conn:
        df = pd.read_sql(text(SQL), conn, params={"sid": w.system_id, "t0": t_load.to_pydatetime(),
                                                  "t1": t1.to_pydatetime()})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Kolkata")
    num = [c for c in df.columns if c not in ("ts", "system_id", "mode_code", "pcs_mode")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    df["in_window"] = df["ts"] >= t0
    return df.reset_index(drop=True)


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Derived signals and the regime columns (no fitted parameters)."""
    out = df.copy()
    out["dv_mv"] = (out["cell_v_max_v"] - out["cell_v_min_v"]) * 1000
    out["dt_c"] = out["cell_temp_max_c"] - out["cell_temp_min_c"]
    coolant = out["coolant_supply_temp_c"].fillna(out["ambient_temp_c"])
    out["temp_rise_c"] = out["cell_temp_avg_c"] - coolant
    # thermal lag: the cells heat with the I² of the last ~30 min, not the instant one
    out["i2_load"] = (out["pack_current_a"] ** 2).rolling(6, min_periods=1).mean() / 1e4
    out["igbt_rise_c"] = out["igbt_temp_c"] - out["inlet_coolant_temp_c"].fillna(out["ambient_temp_c"])
    out["s_abs_kva"] = out["ac_apparent_power_kva"].abs()
    out["pcs_loss_kw"] = (out["dc_power_kw"].abs() - out["ac_active_power_kw"].abs()).abs()
    out["hvac_setpoint_err_c"] = out["coolant_supply_temp_c"] - out["coolant_setpoint_c"]
    out["dispatch_error_kw"] = out["poi_active_power_kw"] - out["p_setpoint_kw"]
    out["regime"] = out["mode_code"].where(out["mode_code"].isin(REGIMES), "Other")
    out["soc_band"] = pd.cut(out["soc_pct"], SOC_BANDS, labels=SOC_BAND_LABELS, right=False).astype(str)
    out["active"] = out["pack_current_a"].abs() > 1.0
    return out


def rule_flags(df: pd.DataFrame, frozen_intervals: int) -> pd.Series:
    """Per row: list of 'frozen:<signal>' / 'missing:<signal>' rule hits."""
    flags = [[] for _ in range(len(df))]
    for col, only_active in FROZEN_SIGNALS.items():
        if col not in df:
            continue
        v = df[col]
        same = v.diff().eq(0) & v.notna()
        if only_active:
            same &= df["active"]
        run_id = (~same).cumsum()
        run_len = same.groupby(run_id).cumsum()  # consecutive repeats ending here
        for i in np.flatnonzero(run_len.to_numpy() >= frozen_intervals - 1):
            flags[i].append(f"frozen:{col}")
    for col in REQUIRED_SIGNALS:
        if col in df:
            for i in np.flatnonzero(df[col].isna().to_numpy()):
                flags[i].append(f"missing:{col}")
    return pd.Series(flags, index=df.index)


# --- fitted residuals -----------------------------------------------------------------------------------------------

def fit_residuals(train: pd.DataFrame) -> dict:
    """Expected-value models fitted on clean training rows (stored with the run)."""
    res: dict = {}
    dv = train.dropna(subset=["dv_mv"])
    res["dv_table"] = dv.groupby(["regime", "soc_band"])["dv_mv"].median().to_dict()
    res["dv_global"] = float(dv["dv_mv"].median()) if len(dv) else 0.0

    def lstsq(frame: pd.DataFrame, y: str, xs: list[str]) -> list[float]:
        f = frame.dropna(subset=[y, *xs])
        if len(f) < 20:
            return [float(f[y].mean()) if len(f) else 0.0] + [0.0] * len(xs)
        a = np.column_stack([np.ones(len(f)), *[f[x].to_numpy(float) for x in xs]])
        coef, *_ = np.linalg.lstsq(a, f[y].to_numpy(float), rcond=None)
        return [float(c) for c in coef]

    res["temp_coef"] = lstsq(train, "temp_rise_c", ["i2_load", "ambient_temp_c"])
    tr = train.assign(s2=train["s_abs_kva"] ** 2 / 1e3)
    res["igbt_coef"] = lstsq(tr, "igbt_rise_c", ["s_abs_kva", "s2"])
    return res


def apply_residuals(df: pd.DataFrame, res: dict) -> pd.DataFrame:
    out = df.copy()
    keys = list(zip(out["regime"], out["soc_band"]))
    expected_dv = np.array([res["dv_table"].get(k, res["dv_global"]) for k in keys], dtype=float)
    out["dv_resid_mv"] = out["dv_mv"] - expected_dv
    c = res["temp_coef"]
    out["temp_rise_resid_c"] = out["temp_rise_c"] - (c[0] + c[1] * out["i2_load"] + c[2] * out["ambient_temp_c"])
    c = res["igbt_coef"]
    out["igbt_rise_resid_c"] = out["igbt_rise_c"] - (c[0] + c[1] * out["s_abs_kva"] + c[2] * out["s_abs_kva"] ** 2 / 1e3)
    return out


# --- labels & exclusions --------------------------------------------------------------------------------------------

def alarms(engine: Engine, w: Window) -> pd.DataFrame:
    """alarm_event rows of the system overlapping the window (start, end, code, source, severity)."""
    t0, t1 = _bounds(w)
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT e.alarm_id, e.time AS start_ts, COALESCE(e.end_time, e.time + interval '30 minutes') AS end_ts,
                   e.severity_level, c.alarm_code, c.source
            FROM battery_telemetry.alarm_event e
            LEFT JOIN battery_master.alarm_catalog c ON c.alarm_catalog_id = e.alarm_catalog_id
            WHERE e.battery_system_id = :sid AND e.time < :t1 AND COALESCE(e.end_time, e.time) >= :t0
            ORDER BY e.time"""), conn, params={"sid": w.system_id, "t0": t0.to_pydatetime(), "t1": t1.to_pydatetime()})
    for c in ("start_ts", "end_ts"):
        df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert("Asia/Kolkata")
    return df


def alarm_mask(ts: pd.Series, al: pd.DataFrame, pad_min: float = 0.0) -> np.ndarray:
    """True where an alarm is active at ts (start − pad ≤ ts < end + pad)."""
    mask = np.zeros(len(ts), dtype=bool)
    if al.empty or not len(ts):
        return mask
    t = pd.DatetimeIndex(ts).asi8
    pad = int(pad_min * 60 * 1e9)
    for s, e in zip(pd.DatetimeIndex(al["start_ts"]).asi8, pd.DatetimeIndex(al["end_ts"]).asi8):
        mask |= (t >= s - pad) & (t < e + pad)
    return mask


def commissioning(engine: Engine, system_id: int) -> Optional[date]:
    with engine.connect() as conn:
        return conn.execute(text("SELECT commissioned_on FROM battery_master.battery_system "
                                 "WHERE battery_system_id = :s"), {"s": system_id}).scalar()


def exclusions(df: pd.DataFrame, al: pd.DataFrame, alarm_pad_min: float, commissioned: Optional[date],
               commissioning_days: int) -> dict[str, np.ndarray]:
    """Reasons a row may not be used to learn 'normal' (evaluation still scores every row)."""
    reasons = {
        "alarm_event": alarm_mask(df["ts"], al, alarm_pad_min),
        "alarm_level": (df[["bms_alarm", "pcs_alarm", "hvac_alarm", "ems_alarm"]].fillna(0) > 0).any(axis=1).to_numpy(),
        "pcs_fault": (df["pcs_mode"] == "FAULT").to_numpy(),
        "sensor_rule": df["rule_flags"].map(bool).to_numpy(),
    }
    if commissioned and commissioning_days > 0:
        end = pd.Timestamp(commissioned + timedelta(days=commissioning_days), tz="Asia/Kolkata")
        reasons["commissioning"] = (df["ts"] < end).to_numpy()
    return reasons
