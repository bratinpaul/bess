"""Weak module features: module_telemetry turned into one row per module per time bucket (day or hour).

At every timestamp each module is compared with
  * all modules of its battery system  -> per-module deviation   (V in mV, T in degC)
  * the other modules of its pack      -> per-pack deviation     (mV / degC, and as a z-score within the pack)
and the bucket keeps the averages. Supporting signals: the module's cell imbalance (max - min cell V), its pack
deviation under load (discharging / charging, from the BMS mode at that timestamp) vs at rest, and its share of
time balancing. A weak module sags (lower V) and runs hotter than its peers, with more imbalance - especially
under load.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

GRAINS = ("day", "hour")

FEATURE_GROUPS: dict[str, dict] = {
    "module_deviation": {"label": "Per-module deviation (vs system)", "features": ["v_dev_sys_mv", "t_dev_sys_c"]},
    "pack_deviation": {"label": "Per-pack module deviation",
                       "features": ["v_dev_pack_mv", "t_dev_pack_c", "v_dev_pack_z", "t_dev_pack_z"]},
    "imbalance": {"label": "Cell imbalance", "features": ["imbalance_mv", "imbalance_p95_mv"]},
    "under_load": {"label": "Deviation under load",
                   "features": ["v_dev_pack_discharge_mv", "v_dev_pack_charge_mv", "v_dev_pack_rest_mv"]},
    "balancing": {"label": "Balancing activity", "features": ["balancing_share"]},
}

# label, unit, and how to say a positive / negative value in a reason
FEATURES: dict[str, dict] = {
    "v_dev_sys_mv": {"label": "Voltage vs system", "unit": "mV", "up": "above the system average", "down": "below the system average"},
    "t_dev_sys_c": {"label": "Temperature vs system", "unit": "°C", "up": "hotter than the system average", "down": "cooler than the system average"},
    "v_dev_pack_mv": {"label": "Voltage vs pack", "unit": "mV", "up": "above its pack", "down": "below its pack"},
    "t_dev_pack_c": {"label": "Temperature vs pack", "unit": "°C", "up": "hotter than its pack", "down": "cooler than its pack"},
    "v_dev_pack_z": {"label": "Voltage z-score in pack", "unit": "σ", "up": "high in its pack", "down": "low in its pack"},
    "t_dev_pack_z": {"label": "Temperature z-score in pack", "unit": "σ", "up": "hot in its pack", "down": "cool in its pack"},
    "imbalance_mv": {"label": "Cell imbalance", "unit": "mV", "up": "more cell imbalance than peers", "down": "less cell imbalance than peers"},
    "imbalance_p95_mv": {"label": "Cell imbalance (p95)", "unit": "mV", "up": "higher peak imbalance than peers", "down": "lower peak imbalance than peers"},
    "v_dev_pack_discharge_mv": {"label": "Voltage vs pack, discharging", "unit": "mV", "up": "above its pack while discharging", "down": "sags below its pack while discharging"},
    "v_dev_pack_charge_mv": {"label": "Voltage vs pack, charging", "unit": "mV", "up": "rises above its pack while charging", "down": "below its pack while charging"},
    "v_dev_pack_rest_mv": {"label": "Voltage vs pack, at rest", "unit": "mV", "up": "above its pack at rest", "down": "below its pack at rest"},
    "balancing_share": {"label": "Time balancing", "unit": "share", "up": "balances more often than peers", "down": "balances less often than peers"},
}

_SQL = """
WITH m AS (
    SELECT t.module_id, t.ts, bm.pack_id, t.cell_v_avg_v AS v, t.cell_temp_max_c AS temp,
           (t.cell_v_max_v - t.cell_v_min_v) * 1000 AS imb, CASE WHEN t.balancing_active THEN 1.0 ELSE 0.0 END AS bal
    FROM battery_telemetry.module_telemetry t
    JOIN battery_master.battery_module bm ON bm.module_id = t.module_id
    JOIN battery_master.battery_pack p ON p.pack_id = bm.pack_id
    JOIN battery_master.battery_container c ON c.container_id = p.container_id
    WHERE c.battery_system_id = :sid
      AND (CAST(:date_from AS date) IS NULL OR t.ts >= CAST(:date_from AS date))
      AND (CAST(:date_to AS date) IS NULL OR t.ts < CAST(:date_to AS date) + 1)
      AND (CAST(:pack_id AS bigint) IS NULL OR bm.pack_id = CAST(:pack_id AS bigint))
), d AS (
    SELECT m.*,
           (v - avg(v) OVER (PARTITION BY ts)) * 1000             AS dv_sys,
           temp - avg(temp) OVER (PARTITION BY ts)                AS dt_sys,
           (v - avg(v) OVER (PARTITION BY pack_id, ts)) * 1000    AS dv_pack,
           temp - avg(temp) OVER (PARTITION BY pack_id, ts)       AS dt_pack,
           stddev_pop(v) OVER (PARTITION BY pack_id, ts) * 1000   AS sv_pack,
           stddev_pop(temp) OVER (PARTITION BY pack_id, ts)       AS st_pack
    FROM m
)
SELECT d.module_id, d.pack_id, date_trunc(:grain, d.ts) AS bucket, count(*) AS readings,
       avg(dv_sys) AS v_dev_sys_mv, avg(dt_sys) AS t_dev_sys_c,
       avg(dv_pack) AS v_dev_pack_mv, avg(dt_pack) AS t_dev_pack_c,
       avg(dv_pack / NULLIF(sv_pack, 0)) AS v_dev_pack_z, avg(dt_pack / NULLIF(st_pack, 0)) AS t_dev_pack_z,
       avg(imb) AS imbalance_mv, percentile_cont(0.95) WITHIN GROUP (ORDER BY imb) AS imbalance_p95_mv,
       avg(dv_pack) FILTER (WHERE s.mode_code = 'Discharging') AS v_dev_pack_discharge_mv,
       avg(dv_pack) FILTER (WHERE s.mode_code = 'Charging') AS v_dev_pack_charge_mv,
       avg(dv_pack) FILTER (WHERE s.mode_code IN ('Standby', 'Idle') OR s.mode_code IS NULL) AS v_dev_pack_rest_mv,
       avg(bal) AS balancing_share
FROM d
LEFT JOIN battery_telemetry.system_telemetry s ON s.system_id = :sid AND s.ts = d.ts
GROUP BY d.module_id, d.pack_id, date_trunc(:grain, d.ts)
ORDER BY bucket, d.module_id
"""


@dataclass
class Selection:
    battery_system_id: int
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    grain: str = "day"
    feature_groups: list[str] = field(default_factory=lambda: list(FEATURE_GROUPS))

    @property
    def features(self) -> list[str]:
        return [f for g in self.feature_groups for f in FEATURE_GROUPS[g]["features"]]


def modules(engine: Engine, system_id: int) -> pd.DataFrame:
    """The system's modules with their pack and position (for the heatmap)."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT bm.module_id, bm.serial_number, p.pack_id, p.pack_number
            FROM battery_master.battery_module bm
            JOIN battery_master.battery_pack p ON p.pack_id = bm.pack_id
            JOIN battery_master.battery_container c ON c.container_id = p.container_id
            WHERE c.battery_system_id = :sid ORDER BY p.pack_number, bm.serial_number"""), conn, params={"sid": system_id})
    df["position"] = df.groupby("pack_id").cumcount() + 1
    return df


def build(engine: Engine, sel: Selection, pack_id: Optional[int] = None) -> pd.DataFrame:
    """Feature rows (module_id, pack_id, bucket, readings, all features); missing load-state values filled from the
    module's overall pack deviation of that bucket (no discharge that day = no sag seen). pack_id: one pack only."""
    if sel.grain not in GRAINS:
        raise ValueError(f"grain must be one of {', '.join(GRAINS)}")
    with engine.connect() as conn:
        df = pd.read_sql(text(_SQL), conn, params={"sid": sel.battery_system_id, "date_from": sel.date_from,
                                                   "date_to": sel.date_to, "grain": sel.grain, "pack_id": pack_id})
    if df.empty:
        return df
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    num = [c for c in df.columns if c not in ("module_id", "pack_id", "bucket")]
    df[num] = df[num].astype(float)
    for c in ("v_dev_pack_discharge_mv", "v_dev_pack_charge_mv", "v_dev_pack_rest_mv"):
        df[c] = df[c].fillna(df["v_dev_pack_mv"])
    df[["v_dev_pack_z", "t_dev_pack_z"]] = df[["v_dev_pack_z", "t_dev_pack_z"]].fillna(0.0)
    return df


def coverage(engine: Engine) -> list[dict]:
    """Battery systems with module telemetry: date range, modules, packs."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT b.battery_system_id, b.system_name, s.site_name, min(t.ts)::date AS date_from, max(t.ts)::date AS date_to,
                   count(DISTINCT t.ts::date) AS days, count(DISTINCT t.module_id) AS modules,
                   count(DISTINCT bm.pack_id) AS packs
            FROM battery_telemetry.module_telemetry t
            JOIN battery_master.battery_module bm ON bm.module_id = t.module_id
            JOIN battery_master.battery_pack p ON p.pack_id = bm.pack_id
            JOIN battery_master.battery_container c ON c.container_id = p.container_id
            JOIN battery_master.battery_system b ON b.battery_system_id = c.battery_system_id
            JOIN battery_master.site s ON s.site_id = b.site_id
            GROUP BY 1, 2, 3 ORDER BY 3, 2""")).mappings()
        return [{**r, "date_from": r["date_from"].isoformat(), "date_to": r["date_to"].isoformat()} for r in rows]


def count(engine: Engine, sel: Selection) -> dict:
    """What a window gives, without building the features (fast, for the page's preview)."""
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT count(DISTINCT t.module_id) AS modules, count(DISTINCT bm.pack_id) AS packs,
                   count(DISTINCT date_trunc(:grain, t.ts)) AS buckets,
                   count(DISTINCT date_trunc('day', t.ts)) AS days, min(t.ts) AS ts_from, max(t.ts) AS ts_to
            FROM battery_telemetry.module_telemetry t
            JOIN battery_master.battery_module bm ON bm.module_id = t.module_id
            JOIN battery_master.battery_pack p ON p.pack_id = bm.pack_id
            JOIN battery_master.battery_container c ON c.container_id = p.container_id
            WHERE c.battery_system_id = :sid
              AND (CAST(:date_from AS date) IS NULL OR t.ts >= CAST(:date_from AS date))
              AND (CAST(:date_to AS date) IS NULL OR t.ts < CAST(:date_to AS date) + 1)"""),
            {"sid": sel.battery_system_id, "date_from": sel.date_from, "date_to": sel.date_to, "grain": sel.grain}).mappings().one()
    if not r["modules"]:
        return {"rows": 0}
    # one row per module and bucket (modules report together, so modules x buckets)
    return {"rows": r["modules"] * r["buckets"], "modules": r["modules"], "packs": r["packs"], "days": r["days"],
            "from": r["ts_from"].isoformat(), "to": r["ts_to"].isoformat(), "rows_per_module": r["buckets"]}


def to_float(v) -> Optional[float]:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
