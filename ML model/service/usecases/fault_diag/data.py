"""Reads behind fault classification: the labelled layer in battery_master (fault_catalog, fault_signature, fault_episode,
fault_alarm_link, maintenance_action, fault_prediction), the alarm stream, and one 5-min telemetry frame per system
(BMS + PCS + HVAC + EMS + per-module temperatures on the TimescaleDB time_bucket grid) with the derived signals the
fault_signature library names.

Telemetry system of an episode: the system its linked alarms were raised on. The pack's BESS-01 episodes are filed under
EESL-BESS-S02 (12), but their alarms - and the telemetry the alarm trigger values come from - belong to 01-BATTERY-01 (1).
Episodes without linked alarms fall back to their own system_id.
"""
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import UseCaseError

TZ = "Asia/Kolkata"

TELEMETRY_SQL = """
WITH s AS (
    SELECT time_bucket('5 minutes', ts) AS ts, last(mode_code, ts) AS mode_code,
           avg(soc_bms_pct) AS soc_pct, avg(pack_voltage_v) AS pack_voltage_v, avg(pack_current_a) AS pack_current_a,
           avg(power_kw) AS power_kw, avg(c_rate) AS c_rate, avg(cell_v_avg_v) AS cell_v_avg_v,
           avg(cell_v_min_v) AS cell_v_min_v, avg(cell_v_max_v) AS cell_v_max_v, avg(cell_v_delta_mv) AS cell_v_delta_mv,
           avg(cell_temp_avg_c) AS cell_temp_avg_c, avg(cell_temp_min_c) AS cell_temp_min_c,
           avg(cell_temp_max_c) AS cell_temp_max_c, avg(coolant_temp_c) AS bms_coolant_temp_c,
           avg(ambient_temp_c) AS ambient_temp_c, avg(insulation_res_kohm) AS insulation_res_kohm
    FROM battery_telemetry.system_telemetry
    WHERE system_id = :sid AND ts >= :t0 AND ts < :t1
    GROUP BY 1
), p AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, avg(t.ac_active_power_kw) AS ac_active_power_kw,
           avg(t.ac_reactive_power_kvar) AS ac_reactive_power_kvar, avg(t.ac_apparent_power_kva) AS ac_apparent_power_kva,
           avg(t.ac_frequency_hz) AS ac_frequency_hz, avg(t.dc_voltage_v) AS dc_voltage_v, avg(t.dc_power_kw) AS dc_power_kw,
           avg(t.efficiency_pct) AS efficiency_pct, avg(t.igbt_temp_c) AS igbt_temp_c,
           avg(t.heatsink_temp_c) AS heatsink_temp_c, avg(t.inlet_coolant_temp_c) AS inlet_coolant_temp_c,
           max(m.rated_apparent_kva) AS rated_apparent_kva
    FROM battery_telemetry.pcs_telemetry t JOIN battery_master.pcs m ON m.pcs_id = t.pcs_id
    WHERE m.system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
), h AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, avg(t.coolant_supply_temp_c) AS coolant_supply_temp_c,
           avg(t.coolant_return_temp_c) AS coolant_return_temp_c, avg(t.coolant_flow_lpm) AS coolant_flow_lpm,
           avg(t.compressor_speed_pct) AS compressor_speed_pct, avg(t.refrig_suction_bar) AS refrig_suction_bar,
           avg(t.refrig_discharge_bar) AS refrig_discharge_bar, avg(t.cop) AS cop, avg(t.hvac_power_kw) AS hvac_power_kw,
           avg(t.enclosure_temp_c) AS enclosure_temp_c, avg(t.enclosure_humidity_pct) AS enclosure_humidity_pct,
           avg(t.filter_dp_pa) AS filter_dp_pa, avg(t.battery_heat_load_kw) AS battery_heat_load_kw,
           avg(t.ambient_temp_c) AS hvac_ambient_c
    FROM battery_telemetry.hvac_telemetry t JOIN battery_master.hvac_unit m ON m.hvac_id = t.hvac_id
    WHERE m.battery_system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
), e AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, sum(t.p_setpoint_kw) AS p_setpoint_kw,
           sum(t.poi_active_power_kw) AS poi_active_power_kw, avg(t.tracking_error_kw) AS tracking_error_kw,
           avg(t.grid_frequency_hz) AS grid_frequency_hz, avg(t.plant_soc_pct) AS plant_soc_pct,
           avg(t.avail_discharge_energy_kwh) AS avail_discharge_energy_kwh, avg(t.market_price_mwh) AS market_price_mwh,
           avg(t.aux_load_kw) AS aux_load_kw, count(*) AS ems_rows
    FROM battery_telemetry.ems_telemetry t JOIN battery_master.ems_controller m ON m.ems_id = t.ems_id
    WHERE m.battery_system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
), mt AS (
    SELECT time_bucket('5 minutes', t.ts) AS ts, max(t.cell_temp_max_c) - min(t.cell_temp_max_c) AS module_dt_c,
           max(t.cell_v_max_v - t.cell_v_min_v) * 1000 AS module_dv_max_mv
    FROM battery_telemetry.module_telemetry t
    JOIN battery_master.battery_module bm ON bm.module_id = t.module_id
    JOIN battery_master.battery_pack bp ON bp.pack_id = bm.pack_id
    JOIN battery_master.battery_container bc ON bc.container_id = bp.container_id
    WHERE bc.battery_system_id = :sid AND t.ts >= :t0 AND t.ts < :t1
    GROUP BY 1
)
SELECT s.*, p.ac_active_power_kw, p.ac_reactive_power_kvar, p.ac_apparent_power_kva, p.ac_frequency_hz, p.dc_voltage_v,
       p.dc_power_kw, p.efficiency_pct, p.igbt_temp_c, p.heatsink_temp_c, p.inlet_coolant_temp_c, p.rated_apparent_kva,
       h.coolant_supply_temp_c, h.coolant_return_temp_c, h.coolant_flow_lpm, h.compressor_speed_pct, h.refrig_suction_bar,
       h.refrig_discharge_bar, h.cop, h.hvac_power_kw, h.enclosure_temp_c, h.enclosure_humidity_pct, h.filter_dp_pa,
       h.battery_heat_load_kw, h.hvac_ambient_c,
       e.p_setpoint_kw, e.poi_active_power_kw, e.tracking_error_kw, e.grid_frequency_hz, e.plant_soc_pct,
       e.avail_discharge_energy_kwh, e.market_price_mwh, e.aux_load_kw, e.ems_rows,
       mt.module_dt_c, mt.module_dv_max_mv
FROM s
LEFT JOIN p ON p.ts = s.ts
LEFT JOIN h ON h.ts = s.ts
LEFT JOIN e ON e.ts = s.ts
LEFT JOIN mt ON mt.ts = s.ts
ORDER BY s.ts
"""

# window-statistic signals: key -> (label, subsystem)
SIGNALS: dict[str, tuple[str, str]] = {
    "soc_pct": ("SOC", "BMS"),
    "pack_voltage_v": ("pack voltage", "BMS"),
    "pack_current_a": ("pack current", "BMS"),
    "power_kw": ("battery power", "BMS"),
    "c_rate": ("C-rate", "BMS"),
    "cell_v_max_v": ("cell voltage max", "BMS"),
    "cell_v_min_v": ("cell voltage min", "BMS"),
    "cell_v_delta_mv": ("cell-voltage spread", "BMS"),
    "cell_temp_max_c": ("cell temperature max", "BMS"),
    "cell_temp_avg_c": ("cell temperature avg", "BMS"),
    "cell_dt_c": ("cell-temperature spread", "BMS"),
    "module_dt_c": ("module temperature spread", "BMS"),
    "module_dv_max_mv": ("worst module voltage spread", "BMS"),
    "insulation_mohm": ("insulation resistance", "BMS"),
    "sensor_residual": ("pack/cell voltage sense residual", "BMS"),
    "ac_active_power_kw": ("PCS AC power", "PCS"),
    "ac_reactive_power_kvar": ("PCS reactive power", "PCS"),
    "apparent_loading": ("PCS apparent loading", "PCS"),
    "ac_frequency_hz": ("PCS AC frequency", "PCS"),
    "dc_voltage_v": ("DC bus voltage", "PCS"),
    "igbt_temp_c": ("IGBT temperature", "PCS"),
    "heatsink_minus_coolant_c": ("heatsink − inlet coolant", "PCS"),
    "pcs_loss_kw": ("PCS conversion loss", "PCS"),
    "coolant_supply_temp_c": ("coolant supply temperature", "HVAC"),
    "coolant_return_temp_c": ("coolant return temperature", "HVAC"),
    "coolant_dt_c": ("coolant ΔT", "HVAC"),
    "coolant_flow_lpm": ("coolant flow", "HVAC"),
    "compressor_speed_pct": ("compressor speed", "HVAC"),
    "refrig_lift_bar": ("refrigerant lift", "HVAC"),
    "cop": ("COP", "HVAC"),
    "cop_residual": ("COP vs expected for ambient", "HVAC"),
    "hvac_power_kw": ("HVAC power", "HVAC"),
    "enclosure_temp_c": ("enclosure temperature", "HVAC"),
    "enclosure_humidity_pct": ("enclosure humidity", "HVAC"),
    "filter_dp_pa": ("filter ΔP", "HVAC"),
    "tracking_error_kw": ("dispatch tracking error", "EMS"),
    "dispatch_error_kw": ("delivered − commanded power", "EMS"),
    "grid_frequency_hz": ("grid frequency", "EMS"),
    "grid_freq_dev_hz": ("grid frequency deviation", "EMS"),
    "avail_discharge_energy_kwh": ("available discharge energy", "EMS"),
    "aux_load_kw": ("auxiliary load", "EMS"),
    "ambient_temp_c": ("ambient temperature", "Context"),
}
# window-level signals (computed over the window, not per interval)
WINDOW_SIGNALS = {"telemetry_staleness_s": ("telemetry staleness", "EMS"),
                  "self_discharge_pct_day": ("SOC drift at rest", "BMS")}
# signature signals that no telemetry here can produce
UNAVAILABLE = {"can_error_rate": "no CAN error counters are logged",
               "dc_bus_ripple_v": "no DC-bus ripple measurement is logged"}


class FaultDataError(UseCaseError):
    code = "FAULT_DATA_REJECTED"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def catalog(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text("SELECT * FROM battery_master.fault_catalog ORDER BY subsystem, fault_code"), conn)


def signatures(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text("""SELECT signature_id, fault_code, signal, signal_kind, operator, threshold, unit, window_min,
                                        weight, note FROM battery_master.fault_signature ORDER BY fault_code, weight DESC"""),
                         conn)
    df["threshold"] = pd.to_numeric(df["threshold"], errors="coerce")
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1.0)
    df["window_min"] = pd.to_numeric(df["window_min"], errors="coerce").fillna(15)
    return df


def episodes(engine: Engine) -> pd.DataFrame:
    """Confirmed episodes with their telemetry system, linked alarms (PRIMARY codes = the defining alarms) and repair
    confirmation."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT e.*, fc.subsystem, fc.category, fc.is_safety_critical, fc.default_severity,
                   tel.telemetry_system_id, tel.primary_alarms, tel.all_alarms, tel.alarm_ids, tel.alarm_asset,
                   ma.fault_confirmed, ma.effective, ma.cost_usd, ma.labor_hours, ma.component, ma.action_type
            FROM battery_master.fault_episode e
            JOIN battery_master.fault_catalog fc ON fc.fault_code = e.fault_code
            LEFT JOIN LATERAL (
                SELECT mode() WITHIN GROUP (ORDER BY a.battery_system_id) AS telemetry_system_id,
                       array_agg(DISTINCT c.alarm_code) FILTER (WHERE l.role = 'PRIMARY') AS primary_alarms,
                       array_agg(DISTINCT c.alarm_code) AS all_alarms,
                       array_agg(DISTINCT l.alarm_id) AS alarm_ids,
                       min(a.asset_code) AS alarm_asset
                FROM battery_master.fault_alarm_link l
                JOIN battery_telemetry.alarm_event a ON a.alarm_id = l.alarm_id
                LEFT JOIN battery_master.alarm_catalog c ON c.alarm_catalog_id = a.alarm_catalog_id
                WHERE l.episode_id = e.episode_id) tel ON true
            LEFT JOIN LATERAL (
                SELECT bool_or(fault_confirmed) AS fault_confirmed, bool_or(effective) AS effective, sum(cost_usd) AS cost_usd,
                       sum(labor_hours) AS labor_hours, string_agg(DISTINCT component, ', ') AS component,
                       string_agg(DISTINCT action_type, ', ') AS action_type
                FROM battery_master.maintenance_action m WHERE m.episode_id = e.episode_id) ma ON true
            ORDER BY e.detected_ts"""), conn)
    for c in ("onset_ts", "detected_ts", "resolved_ts"):
        df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(TZ)
    df["telemetry_system_id"] = df["telemetry_system_id"].fillna(df["system_id"]).astype(int)
    df["onset_ts"] = df["onset_ts"].fillna(df["detected_ts"])
    for c in ("label_confidence", "downtime_min", "energy_lost_kwh", "cost_usd", "labor_hours"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("primary_alarms", "all_alarms", "alarm_ids"):
        df[c] = df[c].apply(lambda v: list(v) if isinstance(v, (list, tuple, np.ndarray)) else [])
    return df


def healthy_anchors(engine: Engine, model_version: Optional[str] = None) -> pd.DataFrame:
    """The healthy windows already in the scoring log (actual F-NONE, no episode) - reused as F-NONE examples. Rows this
    use case published itself are left out, so a retrain never feeds on its own sampled windows."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""SELECT system_id, predicted_at FROM battery_master.fault_prediction
                                 WHERE actual_fault_code = 'F-NONE' AND episode_id IS NULL
                                   AND model_version NOT LIKE 'fault-diag-%'
                                   AND (CAST(:mv AS text) IS NULL OR model_version = :mv)"""), conn,
                         params={"mv": model_version})
    df["predicted_at"] = pd.to_datetime(df["predicted_at"], utc=True).dt.tz_convert(TZ)
    return df


def alarms(engine: Engine, system_id: int, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT a.alarm_id, a.time, a.end_time, a.severity_level, a.asset_type, a.asset_code, c.alarm_code, c.source
            FROM battery_telemetry.alarm_event a
            LEFT JOIN battery_master.alarm_catalog c ON c.alarm_catalog_id = a.alarm_catalog_id
            WHERE a.battery_system_id = :sid AND a.time >= :t0 AND a.time < :t1 ORDER BY a.time"""), conn,
            params={"sid": system_id, "t0": t0.to_pydatetime(), "t1": t1.to_pydatetime()})
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(TZ)
    df["severity_level"] = pd.to_numeric(df["severity_level"], errors="coerce").fillna(0)
    return df


def alarm_codes(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text(
            "SELECT DISTINCT alarm_code FROM battery_master.alarm_catalog WHERE alarm_code IS NOT NULL ORDER BY 1"))]


def systems(engine: Engine) -> list[dict]:
    """Systems with BMS telemetry: window, alarm count and labelled episodes whose telemetry lives there."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH t AS (SELECT system_id, min(ts) AS t0, max(ts) AS t1 FROM battery_telemetry.system_telemetry GROUP BY 1)
            SELECT bs.battery_system_id AS system_id, bs.system_name, si.site_name,
                   CAST(t.t0 AT TIME ZONE 'Asia/Kolkata' AS date) AS date_from,
                   CAST(t.t1 AT TIME ZONE 'Asia/Kolkata' AS date) AS date_to,
                   (SELECT count(*) FROM battery_telemetry.alarm_event a WHERE a.battery_system_id = bs.battery_system_id)
                       AS alarms,
                   (SELECT count(DISTINCT l.episode_id) FROM battery_master.fault_alarm_link l
                      JOIN battery_telemetry.alarm_event a ON a.alarm_id = l.alarm_id
                     WHERE a.battery_system_id = bs.battery_system_id) AS episodes
            FROM t JOIN battery_master.battery_system bs ON bs.battery_system_id = t.system_id
            LEFT JOIN battery_master.site si ON si.site_id = bs.site_id
            ORDER BY bs.battery_system_id""")).mappings().all()
    return [dict(r) for r in rows]


def system_name(engine: Engine, system_id: int) -> str:
    with engine.connect() as conn:
        v = conn.execute(text("SELECT system_name FROM battery_master.battery_system WHERE battery_system_id = :id"),
                         {"id": system_id}).scalar()
    return v or f"system {system_id}"


def load_telemetry(engine: Engine, system_id: int, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    """5-min frame [t0, t1) on a complete grid (missing buckets stay as NaN rows so staleness is visible)."""
    with engine.connect() as conn:
        df = pd.read_sql(text(TELEMETRY_SQL), conn, params={"sid": system_id, "t0": t0.to_pydatetime(),
                                                            "t1": t1.to_pydatetime()})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    num = [c for c in df.columns if c not in ("ts", "mode_code")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    grid = pd.date_range(df["ts"].min(), df["ts"].max(), freq="5min", tz=TZ)
    df = df.set_index("ts").reindex(grid).rename_axis("ts").reset_index()
    return derive(df)


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Signals the signature library names that are not logged directly."""
    out = df
    if out["cell_v_delta_mv"].isna().all():
        out["cell_v_delta_mv"] = (out["cell_v_max_v"] - out["cell_v_min_v"]) * 1000
    out["cell_dt_c"] = out["cell_temp_max_c"] - out["cell_temp_min_c"]
    out["insulation_mohm"] = out["insulation_res_kohm"] / 1000.0
    rated = out["rated_apparent_kva"].where(out["rated_apparent_kva"] > 0)
    out["apparent_loading"] = out["ac_apparent_power_kva"].abs() / rated
    out["heatsink_minus_coolant_c"] = out["heatsink_temp_c"] - out["inlet_coolant_temp_c"]
    out["pcs_loss_kw"] = (out["dc_power_kw"].abs() - out["ac_active_power_kw"].abs()).abs()
    out["coolant_dt_c"] = out["coolant_return_temp_c"] - out["coolant_supply_temp_c"]
    out["refrig_lift_bar"] = out["refrig_discharge_bar"] - out["refrig_suction_bar"]
    out["dispatch_error_kw"] = out["poi_active_power_kw"] - out["p_setpoint_kw"]
    out["grid_freq_dev_hz"] = (out["grid_frequency_hz"] - 50.0).abs()
    amb = out["hvac_ambient_c"].fillna(out["ambient_temp_c"])
    # COP vs expected for the ambient (straight-line fit over the frame's cooling intervals)
    ok = out["cop"].notna() & amb.notna() & (out["hvac_power_kw"] > 1)
    out["cop_residual"] = np.nan
    if ok.sum() > 30:
        b, a = np.polyfit(amb[ok], out.loc[ok, "cop"], 1)
        out.loc[ok, "cop_residual"] = out.loc[ok, "cop"] - (a + b * amb[ok])
    # voltage-sense plausibility: pack voltage / mean cell voltage should be the (constant) series count
    ratio = out["pack_voltage_v"] / out["cell_v_avg_v"].where(out["cell_v_avg_v"] > 0)
    med = ratio.median()
    mad = (ratio - med).abs().median() * 1.4826
    out["sensor_residual"] = (ratio - med).abs() / mad if mad and np.isfinite(mad) and mad > 0 else 0.0
    out["idle"] = out["pack_current_a"].abs() < 1.0
    return out


def frame_bounds(times: list[pd.Timestamp], pad_min: float) -> tuple[pd.Timestamp, pd.Timestamp]:
    lo, hi = min(times), max(times)
    pad = pd.Timedelta(minutes=pad_min)
    return (lo - pad).floor("1D"), (hi + pad).ceil("1D") + pd.Timedelta(days=1)


def day_bounds(d0: date, d1: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(d0, tz=TZ), pd.Timestamp(d1, tz=TZ) + pd.Timedelta(days=1)
