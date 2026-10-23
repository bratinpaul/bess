"""SOC estimation inputs: the 5-min SOC-feature series per battery system, the ground-truth anchors and the OCV curve.

Series (battery_master.v_soc_features + the reported BMS fused estimate from system_telemetry), plant time. Only rows
with a coulomb estimate are used (the SOC-estimation columns are filled). ts is wall-clock local in the files and is
stored as timestamptz in the plant zone, so the anchor join (soc_reference, same zone) matches exactly.

Columns:
  soc_coulomb_pct          raw coulomb-counted SOC (drifts with the current-sensor error)
  soc_bms_pct              dense reference SOC. In the sample data it equals the file's soc_true_pct; on a real
                           plant it is the BMS's own value - hence optional as a training label only
  soc_reported_pct         system_telemetry.soc_battery_telemetry_pct - the BMS fused estimate (a baseline)
  measured_current_a, current_sensor_offset_a, pack_voltage_v, cell_v_avg_v, ocv_rested_v (NULL unless rested),
  cell_temp_avg_c, usable_capacity_ah, c_rate, coulombic_efficiency, at_rest, rest_duration_min
  soc_true_pct / reference_method   the anchor (label) where one exists

OCV curve (battery_master.ocv_curve): per-cell OCV vs SOC by direction (CHARGE / DISCHARGE / MEAN - hysteresis) and
temperature; linear in temperature between the measured ones (clamped at the ends), monotone in SOC.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.base import UseCaseError

TZ = "Asia/Kolkata"
STEP_MIN = 5
DIRECTIONS = ("CHARGE", "DISCHARGE", "MEAN")

_SERIES_SQL = """
SELECT v.ts, v.soc_coulomb_pct, v.soc_bms_pct, t.soc_battery_telemetry_pct AS soc_reported_pct,
       v.measured_current_a, v.current_sensor_offset_a, v.pack_voltage_v, v.cell_v_avg_v, v.ocv_rested_v,
       v.cell_temp_avg_c, v.usable_capacity_ah, v.c_rate, v.coulombic_efficiency, v.at_rest, v.rest_duration_min,
       v.soc_true_pct, v.reference_method
FROM battery_master.v_soc_features v
JOIN battery_telemetry.system_telemetry t ON t.system_id = v.system_id AND t.ts = v.ts
WHERE v.system_id = :s AND v.soc_coulomb_pct IS NOT NULL
  AND (CAST(:f AS timestamptz) IS NULL OR v.ts >= CAST(:f AS timestamptz))
  AND (CAST(:t AS timestamptz) IS NULL OR v.ts <= CAST(:t AS timestamptz))
ORDER BY v.ts
"""
NUMERIC = ["soc_coulomb_pct", "soc_bms_pct", "soc_reported_pct", "measured_current_a", "current_sensor_offset_a",
           "pack_voltage_v", "cell_v_avg_v", "ocv_rested_v", "cell_temp_avg_c", "usable_capacity_ah", "c_rate",
           "coulombic_efficiency", "rest_duration_min", "soc_true_pct"]


@dataclass
class Selection:
    system_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None


def systems(engine: Engine) -> list[dict]:
    """Battery systems with their SOC-estimation readings, anchors and chemistry (for the builder / viewer)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT b.battery_system_id AS system_id, b.system_name, b.chemistry_code AS chemistry, s.site_name,
                   b.rated_energy_mwh, f.readings, f.date_from, f.date_to, a.anchors, a.full_charge, a.rest_ocv,
                   tl.last_ts AS telemetry_to
            FROM battery_master.battery_system b
            LEFT JOIN battery_master.site s ON s.site_id = b.site_id
            LEFT JOIN LATERAL (SELECT count(*) AS readings, min(ts)::date AS date_from, max(ts)::date AS date_to
                               FROM battery_telemetry.system_telemetry
                               WHERE system_id = b.battery_system_id AND soc_coulomb_pct IS NOT NULL) f ON true
            LEFT JOIN LATERAL (SELECT count(*) AS anchors, count(*) FILTER (WHERE method = 'FULL_CHARGE') AS full_charge,
                                      count(*) FILTER (WHERE method = 'REST_OCV') AS rest_ocv
                               FROM battery_master.soc_reference WHERE system_id = b.battery_system_id) a ON true
            LEFT JOIN LATERAL (SELECT max(ts) AS last_ts FROM battery_telemetry.system_telemetry
                               WHERE system_id = b.battery_system_id) tl ON true
            ORDER BY (f.readings > 0) DESC, b.battery_system_id"""))
        out = []
        for r in rows:
            d = dict(r._mapping)
            d["readings"] = int(d["readings"] or 0)
            d["rated_energy_mwh"] = float(d["rated_energy_mwh"]) if d["rated_energy_mwh"] is not None else None
            d["telemetry_to"] = d["telemetry_to"].isoformat() if d["telemetry_to"] else None
            out.append(d)
        return out


def chemistry(engine: Engine, system_id: int) -> str:
    with engine.connect() as conn:
        c = conn.execute(text("SELECT chemistry_code FROM battery_master.battery_system WHERE battery_system_id = :s"),
                         {"s": system_id}).scalar()
    return c or "LFP"


def series(engine: Engine, system_id: int, date_from=None, date_to=None) -> pd.DataFrame:
    """The SOC-feature series of one system (plant-time index). date_to is inclusive (a date or a timestamp)."""
    f, t = _bound(date_from, False), _bound(date_to, True)
    with engine.connect() as conn:
        df = pd.read_sql(text(_SERIES_SQL), conn, params={"s": system_id, "f": f, "t": t})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    df = df.drop_duplicates("ts").set_index("ts")
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["at_rest"] = df["at_rest"].astype("boolean").fillna(False).astype(bool)
    df["current_sensor_offset_a"] = df["current_sensor_offset_a"].fillna(0.0)
    df["coulombic_efficiency"] = df["coulombic_efficiency"].fillna(1.0)
    df["usable_capacity_ah"] = df["usable_capacity_ah"].ffill().bfill()
    # guards: implausible readings out, rested OCV only when actually at rest
    df.loc[(df["ocv_rested_v"] < 1.5) | (df["ocv_rested_v"] > 4.5) | ~df["at_rest"], "ocv_rested_v"] = np.nan
    df.loc[(df["cell_temp_avg_c"] < -40) | (df["cell_temp_avg_c"] > 90), "cell_temp_avg_c"] = np.nan
    df["cell_temp_avg_c"] = df["cell_temp_avg_c"].ffill().fillna(25.0)
    for c in ("soc_coulomb_pct", "soc_bms_pct", "soc_reported_pct", "soc_true_pct"):
        df.loc[(df[c] < -5) | (df[c] > 105), c] = np.nan
    df["gap_min"] = df.index.to_series().diff().dt.total_seconds().div(60).fillna(STEP_MIN).to_numpy()
    return df


def _bound(v, end: bool) -> Optional[pd.Timestamp]:
    """A date (whole day; the end inclusive) or a timestamp, in plant time."""
    if v is None:
        return None
    t = pd.Timestamp(v)
    if type(v) is date and end:
        t = t + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return t.tz_localize(TZ) if t.tzinfo is None else t.tz_convert(TZ)


def latest_telemetry_ts(engine: Engine, system_id: int) -> Optional[pd.Timestamp]:
    with engine.connect() as conn:
        v = conn.execute(text("SELECT max(ts) FROM battery_telemetry.system_telemetry WHERE system_id = :s"),
                         {"s": system_id}).scalar()
    return pd.Timestamp(v).tz_convert(TZ) if v is not None else None


# ---------------------------------------------------------------- OCV curve


class OcvCurve:
    """Per-cell OCV(SOC, direction, temperature) with its slope and inverse."""

    def __init__(self, table: pd.DataFrame):
        self.temps: dict[str, np.ndarray] = {}
        self.grids: dict[str, tuple[np.ndarray, np.ndarray]] = {}  # direction -> (soc grid, ocv[temp, soc])
        for d in DIRECTIONS:
            g = table[table["direction"] == d]
            if g.empty:
                continue
            temps = np.sort(g["temp_c"].unique())
            socs = np.sort(g["soc_pct"].unique())
            m = np.full((len(temps), len(socs)), np.nan)
            for i, t in enumerate(temps):
                gt = g[g["temp_c"] == t].set_index("soc_pct")["ocv_v"].reindex(socs).interpolate(limit_direction="both")
                # keep it strictly increasing so the inverse is unique
                v = np.maximum.accumulate(gt.to_numpy())
                m[i] = v + np.arange(len(v)) * 1e-7
            self.temps[d], self.grids[d] = temps, (socs, m)
        if not self.grids:
            raise UseCaseError("The OCV curve is empty")
        if "MEAN" not in self.grids:  # mean of the two branches
            c, dch = self.grids.get("CHARGE"), self.grids.get("DISCHARGE")
            base = c or dch
            self.temps["MEAN"], self.grids["MEAN"] = self.temps["CHARGE" if c else "DISCHARGE"], \
                (base[0], (c[1] + dch[1]) / 2 if c and dch else base[1])

    def _curve(self, direction: str, temp_c: float) -> tuple[np.ndarray, np.ndarray]:
        d = direction if direction in self.grids else "MEAN"
        socs, m = self.grids[d]
        temps = self.temps[d]
        if len(temps) == 1:
            return socs, m[0]
        t = float(np.clip(temp_c if temp_c == temp_c else 25.0, temps[0], temps[-1]))
        j = int(np.clip(np.searchsorted(temps, t) - 1, 0, len(temps) - 2))
        w = (t - temps[j]) / (temps[j + 1] - temps[j])
        return socs, m[j] * (1 - w) + m[j + 1] * w

    def ocv(self, soc: float, direction: str, temp_c: float) -> float:
        socs, v = self._curve(direction, temp_c)
        return float(np.interp(soc, socs, v))

    def slope(self, soc: float, direction: str, temp_c: float) -> float:
        """dOCV/dSOC in V per SOC point (the local segment, central near the knots)."""
        socs, v = self._curve(direction, temp_c)
        h = 0.5
        a, b = max(socs[0], soc - h), min(socs[-1], soc + h)
        return float((np.interp(b, socs, v) - np.interp(a, socs, v)) / max(b - a, 1e-6))

    def soc(self, ocv_v: float, direction: str, temp_c: float) -> float:
        socs, v = self._curve(direction, temp_c)
        return float(np.interp(ocv_v, v, socs))

    def to_dict(self) -> dict:
        return {d: {"temps": [float(t) for t in self.temps[d]], "soc": [float(s) for s in self.grids[d][0]],
                    "ocv": [[float(x) for x in row] for row in self.grids[d][1]]} for d in self.grids}


def ocv_curve(engine: Engine, chem: str) -> OcvCurve:
    with engine.connect() as conn:
        df = pd.read_sql(text("""SELECT direction, temp_c, soc_pct, ocv_v FROM battery_master.ocv_curve
                                 WHERE upper(chemistry) = upper(:c)"""), conn, params={"c": chem})
    if df.empty:
        raise UseCaseError(f"No OCV curve for chemistry {chem}")
    for c in ("temp_c", "soc_pct", "ocv_v"):
        df[c] = df[c].astype(float)
    return OcvCurve(df)
