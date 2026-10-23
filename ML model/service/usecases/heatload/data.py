"""Inputs of the heat-load model: the time-aligned 5-min BMS / PCS / EMS / HVAC streams of a battery system, the site's
weather (measured GHI where a station exists, else clear-sky), and the master data for the heat balance and sizing.

Telemetry sign: pack current and powers are + on charge, - on discharge.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import UseCaseError
from usecases.loss import data as LD

TZ = "Asia/Kolkata"
STEP_MIN = 5


class HeatLoadError(UseCaseError):
    """Bad input for a heat-load run (the API answers 400)."""
    code = "HEATLOAD_INPUT_REJECTED"


_SERIES_SQL = """
WITH pcs AS (
    SELECT t.ts, sum(t.ac_active_power_kw) AS p_ac_kw, sum(t.dc_power_kw) AS p_dc_kw,
           sum(abs(t.ac_apparent_power_kva)) AS s_kva, max(t.igbt_temp_c) AS igbt_temp_c
    FROM battery_telemetry.pcs_telemetry t
    WHERE t.pcs_id = ANY(CAST(:pcs_ids AS bigint[]))
      AND t.ts >= CAST(:date_from AS date) AND t.ts < CAST(:date_to AS date) + 1
    GROUP BY t.ts
), hvac AS (
    SELECT h.ts, sum(h.battery_heat_load_kw) AS heat_load_sensor_kw, sum(h.cooling_capacity_kw) AS cooling_kw,
           sum(h.heat_rejected_kw) AS heat_rejected_kw, sum(h.hvac_power_kw) AS hvac_kw, avg(h.cop) AS cop,
           avg(h.enclosure_temp_c) AS t_enc_c, avg(h.ambient_temp_c) AS t_amb_c, max(h.cooling_mode) AS cooling_mode,
           sum(h.units_running) AS units_running, avg(h.enclosure_humidity_pct) AS humidity_pct,
           avg(h.coolant_return_temp_c) AS coolant_return_c
    FROM battery_telemetry.hvac_telemetry h
    WHERE h.hvac_id = ANY(CAST(:hvac_ids AS bigint[]))
      AND h.ts >= CAST(:date_from AS date) AND h.ts < CAST(:date_to AS date) + 1
    GROUP BY h.ts
)
SELECT s.ts, s.pack_current_a, s.pack_voltage_v, s.power_kw AS p_term_kw, s.cell_v_avg_v, s.cell_temp_avg_c,
       s.cell_temp_max_c, s.cell_temp_min_c, s.soc_bms_pct AS soc_pct, s.soh_pct, s.c_rate,
       p.p_ac_kw, p.p_dc_kw, p.s_kva, p.igbt_temp_c,
       e.aux_load_kw, e.p_setpoint_kw,
       h.heat_load_sensor_kw, h.cooling_kw, h.heat_rejected_kw, h.hvac_kw, h.cop, h.t_enc_c, h.t_amb_c, h.cooling_mode,
       h.units_running, h.humidity_pct, h.coolant_return_c,
       w.ghi_wm2, w.temp_c AS wx_temp_c, w.cloud_fraction
FROM battery_telemetry.system_telemetry s
JOIN pcs p ON p.ts = s.ts
JOIN battery_telemetry.ems_telemetry e ON e.ems_id = :ems_id AND e.ts = s.ts
JOIN hvac h ON h.ts = s.ts
LEFT JOIN battery_telemetry.weather_actual w ON w.station_id = :station_id AND w.ts = s.ts
WHERE s.system_id = :sid
  AND s.ts >= CAST(:date_from AS date) AND s.ts < CAST(:date_to AS date) + 1
ORDER BY s.ts
"""

NUMERIC = ["pack_current_a", "pack_voltage_v", "p_term_kw", "cell_v_avg_v", "cell_temp_avg_c", "cell_temp_max_c",
           "cell_temp_min_c", "soc_pct", "soh_pct", "c_rate", "p_ac_kw", "p_dc_kw", "s_kva", "igbt_temp_c", "aux_load_kw",
           "p_setpoint_kw", "heat_load_sensor_kw", "cooling_kw", "heat_rejected_kw", "hvac_kw", "cop", "t_enc_c", "t_amb_c",
           "units_running", "humidity_pct", "coolant_return_c", "ghi_wm2", "wx_temp_c", "cloud_fraction"]


@dataclass
class HeatMaster:
    base: LD.SystemMaster
    latitude: Optional[float]
    longitude: Optional[float]
    station_id: Optional[int]
    container_type: Optional[str]
    containers: int
    hvac_units: int
    unit_capacity_kw: Optional[float]   # hvac_unit.cooling_capacity_kw (per unit)
    hvac_model: Optional[str]
    eol_resistance_pct: Optional[float]  # eol_criteria.resistance_eol_pct of the chemistry
    nominal_dc_v: Optional[float]


def systems(engine: Engine) -> list[dict]:
    """Battery systems with BMS, PCS, EMS and HVAC telemetry."""
    out = []
    with engine.connect() as conn:
        for s in LD.systems(engine):
            has_hvac = conn.execute(text("""
                SELECT EXISTS (SELECT 1 FROM battery_telemetry.hvac_telemetry h
                               JOIN battery_master.hvac_unit u ON u.hvac_id = h.hvac_id
                               WHERE u.battery_system_id = :s)"""), {"s": s["system_id"]}).scalar()
            if has_hvac:
                out.append(s)
    return out


def master(engine: Engine, system_id: int) -> HeatMaster:
    base = LD.master(engine, system_id)
    with engine.connect() as conn:
        site = conn.execute(text("SELECT latitude, longitude FROM battery_master.site WHERE site_id = :s"),
                            {"s": base.site_id}).mappings().first()
        station = conn.execute(text("SELECT min(station_id) FROM battery_master.weather_station WHERE site_id = :s"),
                               {"s": base.site_id}).scalar()
        cont = conn.execute(text("""SELECT count(*) AS n, max(container_type) AS t FROM battery_master.battery_container
                                    WHERE battery_system_id = :s"""), {"s": system_id}).mappings().first()
        hv = conn.execute(text("""SELECT count(*) AS n, max(cooling_capacity_kw) AS cap, max(model) AS model
                                  FROM battery_master.hvac_unit WHERE battery_system_id = :s"""), {"s": system_id}).mappings().first()
        bs = conn.execute(text("SELECT chemistry_code, nominal_dc_voltage FROM battery_master.battery_system WHERE battery_system_id = :s"),
                          {"s": system_id}).mappings().first()
        eol = conn.execute(text("SELECT resistance_eol_pct FROM battery_master.eol_criteria WHERE chemistry = :c"),
                           {"c": bs["chemistry_code"]}).scalar() if bs and bs["chemistry_code"] else None
    if not base.hvac_ids:
        raise HeatLoadError(f"{base.system_name} has no HVAC unit in the master data")
    return HeatMaster(
        base=base, latitude=float(site["latitude"]) if site and site["latitude"] is not None else None,
        longitude=float(site["longitude"]) if site and site["longitude"] is not None else None,
        station_id=int(station) if station is not None else None, container_type=cont["t"] if cont else None,
        containers=int(cont["n"] or 0) if cont else 0, hvac_units=int(hv["n"] or 0) if hv else 0,
        unit_capacity_kw=float(hv["cap"]) if hv and hv["cap"] is not None else None,
        hvac_model=hv["model"] if hv else None, eol_resistance_pct=float(eol) if eol is not None else None,
        nominal_dc_v=float(bs["nominal_dc_voltage"]) if bs and bs["nominal_dc_voltage"] else None)


def series(engine: Engine, m: HeatMaster, date_from: date, date_to: date) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text(_SERIES_SQL), conn, params={
            "sid": m.base.system_id, "pcs_ids": m.base.pcs_ids, "hvac_ids": m.base.hvac_ids, "ems_id": m.base.ems_id,
            "station_id": m.station_id or -1, "date_from": date_from, "date_to": date_to})
    if df.empty:
        return df
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    return df.sort_values("ts").reset_index(drop=True)


def weather_forecast(engine: Engine, station_id: Optional[int]) -> pd.DataFrame:
    """All forecast runs of a station: issued_at, valid_at, temp_c, ghi_wm2 (plant time)."""
    if station_id is None:
        return pd.DataFrame(columns=["issued_at", "valid_at", "temp_c", "ghi_wm2"])
    with engine.connect() as conn:
        df = pd.read_sql(text("""SELECT issued_at, valid_at, temp_c, ghi_wm2 FROM battery_telemetry.weather_forecast
                                 WHERE station_id = :s ORDER BY issued_at, valid_at"""), conn, params={"s": station_id})
    for c in ("issued_at", "valid_at"):
        df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(TZ)
    for c in ("temp_c", "ghi_wm2"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def clear_sky_ghi(ts: pd.Series, lat: Optional[float], lon: Optional[float]) -> np.ndarray:
    """A simple clear-sky GHI (W/m²): 1000 · sin(solar elevation)^1.15 · 0.9 (Haurwitz-like), from the solar position at
    the site. Local time is plant time (IST, UTC+5:30)."""
    if lat is None or lon is None:
        lat, lon = 23.0, 78.0  # centre of India
    t = pd.DatetimeIndex(ts).tz_convert("UTC")
    doy = t.dayofyear.to_numpy()
    hours = t.hour.to_numpy() + t.minute.to_numpy() / 60
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    b = 2 * np.pi * (doy - 81) / 364
    eot = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)  # minutes
    solar_time = hours + (4 * lon + eot) / 60
    ha = np.radians(15 * (solar_time - 12))
    phi = np.radians(lat)
    sin_el = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(ha)
    return np.where(sin_el > 0, 1000 * 0.9 * np.power(np.clip(sin_el, 0, 1), 1.15), 0.0)
