"""Auxiliary-load series per site (EMS) from battery_telemetry.v_aux_features, cleaned, plus the ambient forecast as
known at a forecast origin.

Target: aux_load_kw (EMS) = HVAC + controls, always a positive consumption (the sign convention of the efficiency and
net-load models, which subtract it). The HVAC part (hvac_power_kw) is the variable one; controls are near-constant.

Input guards: implausible readings (aux / HVAC below 0 or above 10x their 99th percentile, ambient outside -30..60 Â°C)
become NULL; gaps of up to 3 readings are interpolated; `stale_min` counts the minutes since the last real aux reading.
COP and compressor are NULL when the HVAC is not cooling: compressor is 0 then, COP is imputed from the site's COP(ambient)
curve (see physics.py) - the trainer does that, as it needs the fitted curve.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from usecases.netload_forecast.features import weather_runs  # forecast runs of a weather station

TZ = "Asia/Kolkata"
STEP_MIN = 5
STEPS_PER_DAY = 24 * 60 // STEP_MIN

NUMERIC = ["aux_load_kw", "aux_load_pct", "p_setpoint_kw", "hvac_power_kw", "cop", "coolant_setpoint_c",
           "compressor_speed_pct", "condenser_fan_pct", "coolant_return_temp_c", "enclosure_temp_c",
           "enclosure_humidity_pct", "battery_heat_load_kw", "cooling_capacity_kw", "ambient_temp_c", "power_kw",
           "c_rate", "cell_temp_max_c", "ac_apparent_power_kva", "aux_1h_kw", "aux_max_1h_kw", "aux_3h_kw", "hvac_1h_kw"]
COOLING_MODES = ["IDLE", "FREE_COOLING", "COOLING", "HEATING"]


@dataclass
class Selection:
    ems_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None


def sites(engine: Engine) -> list[dict]:
    """The EMS units (one per site) with their site, ratings, weather station and data coverage."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ec.ems_id, ec.ems_code, ec.battery_system_id, bs.system_name, bs.site_id, s.site_name,
                   bs.rated_power_mw, bs.rated_energy_mwh, p.rated_power_kw AS pcs_rated_kw,
                   (SELECT min(w.station_id) FROM battery_master.weather_station w WHERE w.site_id = bs.site_id) AS station_id,
                   (SELECT count(*) FROM battery_telemetry.weather_forecast f JOIN battery_master.weather_station w
                      ON w.station_id = f.station_id WHERE w.site_id = bs.site_id) AS wx_forecast_rows,
                   x.readings, x.date_from, x.date_to
            FROM battery_master.ems_controller ec
            JOIN battery_master.battery_system bs ON bs.battery_system_id = ec.battery_system_id
            LEFT JOIN battery_master.site s ON s.site_id = bs.site_id
            LEFT JOIN battery_master.v_thermal_assets a ON a.battery_system_id = ec.battery_system_id
            LEFT JOIN battery_master.pcs p ON p.pcs_id = a.pcs_id
            LEFT JOIN LATERAL (SELECT count(aux_load_kw) AS readings, min(ts)::date AS date_from, max(ts)::date AS date_to
                               FROM battery_telemetry.ems_telemetry t WHERE t.ems_id = ec.ems_id) x ON true
            ORDER BY ec.ems_id""")).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("rated_power_mw", "rated_energy_mwh", "pcs_rated_kw"):
            d[k] = _f(d[k])
        d["date_from"] = d["date_from"].isoformat() if d["date_from"] else None
        d["date_to"] = d["date_to"].isoformat() if d["date_to"] else None
        out.append(d)
    return out


def series(engine: Engine, ems_id: int, date_from=None, date_to=None) -> pd.DataFrame:
    """Cleaned 5-min features of one EMS on a continuous grid; `ok` marks real aux readings."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT * FROM battery_telemetry.v_aux_features
            WHERE ems_id = :e
              AND (CAST(:f AS date) IS NULL OR ts >= CAST(:f AS date))
              AND (CAST(:t AS date) IS NULL OR ts < CAST(:t AS date) + 1)
            ORDER BY ts"""), conn, params={"e": ems_id, "f": date_from, "t": date_to})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.drop_duplicates("ts").set_index("ts")
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    grid = pd.date_range(df.index.min(), df.index.max(), freq=f"{STEP_MIN}min", tz=TZ)
    df = df.reindex(grid)
    df.index.name = "ts"
    # guards: implausible values become NULL (aux is a consumption: never negative)
    for c in ("aux_load_kw", "hvac_power_kw"):
        v = df[c]
        hi = 10 * max(float(v.quantile(0.99)), 1.0) if v.notna().any() else np.inf
        df[c] = v.where(v.between(0, hi))
    df["ambient_temp_c"] = df["ambient_temp_c"].where(df["ambient_temp_c"].between(-30, 60))
    df["ok"] = df["aux_load_kw"].notna()
    last = df.index.to_series().where(df["ok"]).ffill()
    df["stale_min"] = ((df.index.to_series() - last).dt.total_seconds() / 60).fillna(1e4)
    df[NUMERIC] = df[NUMERIC].interpolate(limit=3, limit_area="inside")
    for c in ("cooling_mode", "dispatch_mode", "grid_service"):
        df[c] = df[c].ffill(limit=3)
    for c in ("ems_id", "site_id", "battery_system_id", "pcs_id", "hvac_id", "station_id"):
        df[c] = df[c].ffill().bfill()
    # branch on cooling mode: no compressor when not cooling
    df.loc[df["cooling_mode"].notna() & df["cooling_mode"].ne("COOLING"), "compressor_speed_pct"] = 0.0
    return df


def slot_of(ts: pd.DatetimeIndex) -> np.ndarray:
    return ((ts.hour * 60 + ts.minute) // STEP_MIN).to_numpy()


def daily_profile(values: pd.Series) -> np.ndarray:
    """Median per 5-min slot of the day."""
    prof = values.groupby(slot_of(values.index)).median().reindex(range(STEPS_PER_DAY))
    return prof.interpolate(limit_direction="both").fillna(values.median() if values.notna().any() else 0.0).to_numpy()


def solar_shape(ts: pd.DatetimeIndex) -> np.ndarray:
    """Clear-sky daylight shape (0 at night, 1 at solar noon): the solar gain on the enclosure without a GHI feed."""
    h = ts.hour.to_numpy() + ts.minute.to_numpy() / 60.0
    return np.clip(np.sin(np.pi * (h - 6.0) / 12.0), 0.0, None)


class Ambient:
    """Ambient temperature at future times as known at an origin.

    forecast  the newest weather_forecast run of the site's station issued at or before the origin, shifted by the
              site's offset (ambient now - the run's value now: the station is not the HVAC sensor); where no run covers
              a target time, the profile rule below
    profile   ambient now + the typical daily swing between now and the target (median per 5-min slot)
    actual    the measured ambient at the target (oracle - an upper bound of the skill a perfect forecast would give)
    """

    def __init__(self, runs: list, profile: np.ndarray):
        self.runs, self.profile = runs, profile
        self._issued = np.array([r[0].value for r in runs], dtype=np.int64)

    def run_at(self, origin_ts: pd.Timestamp):
        if not len(self.runs):
            return None
        i = int(np.searchsorted(self._issued, origin_ts.value, side="right")) - 1
        return self.runs[i] if i >= 0 else None

    def at(self, origin_ts: pd.Timestamp, amb_now: float, targets: pd.DatetimeIndex, source: str,
           actual: Optional[np.ndarray] = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(ambient, GHI or NaN, 1 where it came from a forecast run) at each target."""
        n = len(targets)
        prof = amb_now + self.profile[slot_of(targets)] - self.profile[slot_of(pd.DatetimeIndex([origin_ts]))[0]]
        if source == "actual" and actual is not None:
            amb = np.where(np.isfinite(actual), actual, prof)
            return amb, np.full(n, np.nan), np.isfinite(actual).astype(float)
        if source == "profile":
            return prof, np.full(n, np.nan), np.zeros(n)
        run = self.run_at(origin_ts)
        if run is None or not len(run[1]):
            return prof, np.full(n, np.nan), np.zeros(n)
        sec = (targets.asi8 // 10**9).astype(float)
        cover = (sec >= run[1][0] - 3600) & (sec <= run[1][-1])
        offset = amb_now - float(np.interp(origin_ts.value // 10**9, run[1], run[2]))
        amb = np.where(cover, np.interp(sec, run[1], run[2]) + offset, prof)
        ghi = np.where(cover, np.interp(sec, run[1], run[3]), np.nan)
        return amb, ghi, cover.astype(float)


def ambient_for(engine: Engine, station_id, train_ambient: pd.Series) -> Ambient:
    sid = int(station_id) if station_id is not None and np.isfinite(station_id) else None
    return Ambient(weather_runs(engine, sid), daily_profile(train_ambient))


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
