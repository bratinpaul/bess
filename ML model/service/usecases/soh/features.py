"""SOH training dataset: BMS (system_telemetry) and module (module_telemetry) readings turned into feature rows.

One row per battery system per time bucket (5 min, hour or day). Target: the mean SOH % in the bucket.

Feature groups (the training page picks which to use):
  cell_voltage      cell voltage envelope     min / max / avg cell V, and max - min in the bucket (mV)
  cell_temperature  cell temperature envelope min / max / avg cell temperature, spread
  imbalance         cell imbalance            mean and max cell voltage delta (mV)
  cycles            cycles                    equivalent full cycles (cumulative) and those added in the bucket
  throughput        energy throughput         cumulative charge / discharge kWh and kWh moved in the bucket
                                              (raw kWh depend on plant size: battery system models only)
  throughput_norm   throughput / rated kWh    the same divided by the battery system's rated kWh (full-equivalent
                                              cycles) - comparable across plants, for base models
  c_rate            C-rate                    mean and max |C-rate| in the bucket (power / rated energy)
  calendar_age      calendar age              days since the system was commissioned
  module            module envelope           across the modules: min/max cell V, spread of module averages,
                                              module imbalance (mean / max), min/max temperature, balancing share
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TARGET = "soh_pct"
GRAINS = {"5min": "5min", "hour": "h", "day": "D"}

FEATURE_GROUPS: dict[str, dict] = {
    "cell_voltage": {"label": "Cell voltage envelope",
                     "features": ["cell_v_min_v", "cell_v_max_v", "cell_v_avg_v", "cell_v_range_mv"]},
    "cell_temperature": {"label": "Cell temperature envelope",
                         "features": ["cell_temp_min_c", "cell_temp_max_c", "cell_temp_avg_c", "cell_temp_spread_c"]},
    "imbalance": {"label": "Cell imbalance", "features": ["imbalance_avg_mv", "imbalance_max_mv"]},
    "cycles": {"label": "Cycles", "features": ["equiv_full_cycles", "cycles_in_period"]},
    "throughput": {"label": "Energy throughput (kWh)", "features": ["cum_charge_kwh", "cum_discharge_kwh", "throughput_kwh"],
                   "scopes": ["system"]},
    "throughput_norm": {"label": "Energy throughput ÷ rated kWh",
                        "features": ["cum_charge_efc", "cum_discharge_efc", "throughput_efc"]},
    "c_rate": {"label": "C-rate (load)", "features": ["c_rate_abs_avg", "c_rate_abs_max"]},
    "calendar_age": {"label": "Calendar age", "features": ["calendar_age_days"]},
    "module": {"label": "Module envelope (module table)",
               "features": ["mod_cell_v_min_v", "mod_cell_v_max_v", "mod_avg_spread_mv", "mod_imbalance_avg_mv",
                            "mod_imbalance_max_mv", "mod_temp_min_c", "mod_temp_max_c", "mod_balancing_share"]},
}

FEATURE_LABELS = {
    "cell_v_min_v": "Min cell voltage (V)", "cell_v_max_v": "Max cell voltage (V)", "cell_v_avg_v": "Avg cell voltage (V)",
    "cell_v_range_mv": "Cell voltage range (mV)", "cell_temp_min_c": "Min cell temp (°C)",
    "cell_temp_max_c": "Max cell temp (°C)", "cell_temp_avg_c": "Avg cell temp (°C)",
    "cell_temp_spread_c": "Cell temp spread (°C)", "imbalance_avg_mv": "Avg cell imbalance (mV)",
    "imbalance_max_mv": "Max cell imbalance (mV)", "equiv_full_cycles": "Equivalent full cycles",
    "cycles_in_period": "Cycles in period", "cum_charge_kwh": "Cumulative charge (kWh)",
    "cum_discharge_kwh": "Cumulative discharge (kWh)", "throughput_kwh": "Throughput in period (kWh)",
    "calendar_age_days": "Calendar age (days)", "mod_cell_v_min_v": "Module min cell V (V)",
    "mod_cell_v_max_v": "Module max cell V (V)", "mod_avg_spread_mv": "Spread of module avg V (mV)",
    "mod_imbalance_avg_mv": "Avg module imbalance (mV)", "mod_imbalance_max_mv": "Max module imbalance (mV)",
    "mod_temp_min_c": "Module min temp (°C)", "mod_temp_max_c": "Module max temp (°C)",
    "mod_balancing_share": "Share of modules balancing",
    "cum_charge_efc": "Cumulative charge ÷ rated kWh", "cum_discharge_efc": "Cumulative discharge ÷ rated kWh",
    "throughput_efc": "Throughput in period ÷ rated kWh", "c_rate_abs_avg": "Avg |C-rate|", "c_rate_abs_max": "Max |C-rate|",
}

SCOPES = ("base", "system")


def groups_for(scope: str) -> list[str]:
    """Feature groups a scope may use (raw kWh only for battery system models: they depend on plant size)."""
    return [k for k, g in FEATURE_GROUPS.items() if scope in g.get("scopes", SCOPES)]

_READINGS_SQL = """
WITH module_ts AS (
    -- the module readings of one system at one timestamp, reduced to envelope figures
    SELECT c.battery_system_id AS system_id, m.ts,
           min(m.cell_v_min_v)                                  AS mod_cell_v_min_v,
           max(m.cell_v_max_v)                                  AS mod_cell_v_max_v,
           (max(m.cell_v_avg_v) - min(m.cell_v_avg_v)) * 1000   AS mod_avg_spread_mv,
           avg((m.cell_v_max_v - m.cell_v_min_v) * 1000)        AS mod_imbalance_avg_mv,
           max((m.cell_v_max_v - m.cell_v_min_v) * 1000)        AS mod_imbalance_max_mv,
           min(m.cell_temp_min_c)                               AS mod_temp_min_c,
           max(m.cell_temp_max_c)                               AS mod_temp_max_c,
           avg(CASE WHEN m.balancing_active THEN 1.0 ELSE 0.0 END) AS mod_balancing_share
    FROM battery_telemetry.module_telemetry m
    JOIN battery_master.battery_module bm ON bm.module_id = m.module_id
    JOIN battery_master.battery_pack p ON p.pack_id = bm.pack_id
    JOIN battery_master.battery_container c ON c.container_id = p.container_id
    WHERE (CAST(:date_from AS date) IS NULL OR m.ts >= CAST(:date_from AS date))
      AND (CAST(:date_to AS date) IS NULL OR m.ts < CAST(:date_to AS date) + 1)
      AND (CAST(:systems AS bigint[]) IS NULL OR c.battery_system_id = ANY(CAST(:systems AS bigint[])))
    GROUP BY c.battery_system_id, m.ts
)
SELECT s.system_id, s.ts, s.soh_pct,
       s.cell_v_min_v, s.cell_v_max_v, s.cell_v_avg_v, s.cell_v_delta_mv,
       s.cell_temp_min_c, s.cell_temp_max_c, s.cell_temp_avg_c,
       s.equiv_full_cycles, s.cum_charge_kwh, s.cum_discharge_kwh, s.c_rate,
       bs.commissioned_on, bs.rated_energy_mwh * 1000 AS rated_kwh,
       -- rows the realtime batch loaded from snapshot files (e.g. simulator output)
       EXISTS (SELECT 1 FROM battery_raw.batchlog b WHERE b.snapshot_time = s.ts AND b.status <> 'FAILED') AS from_snapshot,
       mt.mod_cell_v_min_v, mt.mod_cell_v_max_v, mt.mod_avg_spread_mv, mt.mod_imbalance_avg_mv,
       mt.mod_imbalance_max_mv, mt.mod_temp_min_c, mt.mod_temp_max_c, mt.mod_balancing_share
FROM battery_telemetry.system_telemetry s
JOIN battery_master.battery_system bs ON bs.battery_system_id = s.system_id
LEFT JOIN module_ts mt ON mt.system_id = s.system_id AND mt.ts = s.ts
WHERE s.soh_pct IS NOT NULL
  AND (CAST(:date_from AS date) IS NULL OR s.ts >= CAST(:date_from AS date))
  AND (CAST(:date_to AS date) IS NULL OR s.ts < CAST(:date_to AS date) + 1)
  AND (CAST(:systems AS bigint[]) IS NULL OR s.system_id = ANY(CAST(:systems AS bigint[])))
ORDER BY s.system_id, s.ts
"""


@dataclass
class DataSelection:
    grain: str = "hour"
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    feature_groups: list[str] = field(default_factory=lambda: list(FEATURE_GROUPS))
    module_rows_only: bool = True
    include_snapshots: bool = False
    # one battery system only (battery system models, the SOH Estimator); None = see systems
    system_id: Optional[int] = None
    # these battery systems only (base models trained on a subset); None = every system
    systems: Optional[list[int]] = None

    @property
    def system_filter(self) -> Optional[list[int]]:
        return [self.system_id] if self.system_id is not None else (list(self.systems) if self.systems else None)

    @property
    def features(self) -> list[str]:
        return [f for g in self.feature_groups for f in FEATURE_GROUPS[g]["features"]]


def _readings(engine: Engine, sel: DataSelection) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text(_READINGS_SQL), conn, params={"date_from": sel.date_from, "date_to": sel.date_to,
                                                         "systems": sel.system_filter})
    if df.empty:
        return df
    # plant local clock time (the database session answers in Asia/Kolkata)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    num = [c for c in df.columns if c not in ("system_id", "ts", "commissioned_on", "from_snapshot")]
    df[num] = df[num].astype(float)
    if not sel.include_snapshots:
        df = df[~df["from_snapshot"]]
    # per-reading increments (for "in period" features), within each system
    df = df.sort_values(["system_id", "ts"])
    g = df.groupby("system_id")
    df["c_rate_abs"] = df["c_rate"].abs()
    df["d_cycles"] = g["equiv_full_cycles"].diff().clip(lower=0)
    df["d_throughput"] = (g["cum_charge_kwh"].diff().clip(lower=0) + g["cum_discharge_kwh"].diff().clip(lower=0))
    return df


def build_dataset(engine: Engine, sel: DataSelection) -> pd.DataFrame:
    """Feature rows (columns: system_id, ts, soh_pct, all features, has_module) for the selection."""
    if sel.grain not in GRAINS:
        raise ValueError(f"grain must be one of {', '.join(GRAINS)}")
    df = _readings(engine, sel)
    if df.empty:
        return pd.DataFrame(columns=["system_id", "ts", TARGET, "has_module"] + sel.features)

    df["bucket"] = df["ts"].dt.floor(GRAINS[sel.grain])
    agg = df.groupby(["system_id", "bucket"]).agg(
        soh_pct=("soh_pct", "mean"),
        cell_v_min_v=("cell_v_min_v", "min"), cell_v_max_v=("cell_v_max_v", "max"),
        cell_v_avg_v=("cell_v_avg_v", "mean"),
        cell_temp_min_c=("cell_temp_min_c", "min"), cell_temp_max_c=("cell_temp_max_c", "max"),
        cell_temp_avg_c=("cell_temp_avg_c", "mean"),
        imbalance_avg_mv=("cell_v_delta_mv", "mean"), imbalance_max_mv=("cell_v_delta_mv", "max"),
        equiv_full_cycles=("equiv_full_cycles", "last"), cycles_in_period=("d_cycles", "sum"),
        cum_charge_kwh=("cum_charge_kwh", "last"), cum_discharge_kwh=("cum_discharge_kwh", "last"),
        throughput_kwh=("d_throughput", "sum"),
        c_rate_abs_avg=("c_rate_abs", "mean"), c_rate_abs_max=("c_rate_abs", "max"),
        rated_kwh=("rated_kwh", "first"),
        commissioned_on=("commissioned_on", "first"), last_ts=("ts", "max"),
        mod_cell_v_min_v=("mod_cell_v_min_v", "min"), mod_cell_v_max_v=("mod_cell_v_max_v", "max"),
        mod_avg_spread_mv=("mod_avg_spread_mv", "mean"), mod_imbalance_avg_mv=("mod_imbalance_avg_mv", "mean"),
        mod_imbalance_max_mv=("mod_imbalance_max_mv", "max"), mod_temp_min_c=("mod_temp_min_c", "min"),
        mod_temp_max_c=("mod_temp_max_c", "max"), mod_balancing_share=("mod_balancing_share", "mean"),
        module_readings=("mod_cell_v_min_v", "count"),
    ).reset_index().rename(columns={"bucket": "ts"})

    agg["cell_v_range_mv"] = (agg["cell_v_max_v"] - agg["cell_v_min_v"]) * 1000
    agg["cell_temp_spread_c"] = agg["cell_temp_max_c"] - agg["cell_temp_min_c"]
    # energy as multiples of the battery system's rated energy (plant-size independent)
    rated = agg["rated_kwh"].where(agg["rated_kwh"] > 0)
    agg["cum_charge_efc"] = agg["cum_charge_kwh"] / rated
    agg["cum_discharge_efc"] = agg["cum_discharge_kwh"] / rated
    agg["throughput_efc"] = agg["throughput_kwh"] / rated
    commissioned = pd.to_datetime(agg["commissioned_on"])
    agg["calendar_age_days"] = (agg["last_ts"] - commissioned).dt.total_seconds() / 86400
    agg["has_module"] = agg["module_readings"] > 0
    if sel.module_rows_only:
        agg = agg[agg["has_module"]]
    cols = ["system_id", "ts", TARGET, "has_module"] + sel.features
    return agg[cols].sort_values(["ts", "system_id"]).reset_index(drop=True)


def system_coverage(engine: Engine) -> list[dict]:
    """Per battery system: its BMS span (systems()) plus its BMS / module days and SOH range (plant local dates).
    Module days come from one module per system (all modules of a system report together)."""
    with engine.connect() as conn:
        module_days = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(text("""
            WITH rep AS (
                SELECT c.battery_system_id, min(bm.module_id) AS module_id
                FROM battery_master.battery_module bm
                JOIN battery_master.battery_pack p ON p.pack_id = bm.pack_id
                JOIN battery_master.battery_container c ON c.container_id = p.container_id
                GROUP BY 1)
            SELECT r.battery_system_id, min(d.day), max(d.day), count(*)
            FROM rep r JOIN LATERAL (
                SELECT DISTINCT (m.ts AT TIME ZONE 'Asia/Kolkata')::date AS day
                FROM battery_telemetry.module_telemetry m WHERE m.module_id = r.module_id) d ON true
            GROUP BY 1"""))}
        bms = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(text("""
            SELECT system_id, count(DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date), min(soh_pct), max(soh_pct)
            FROM battery_telemetry.system_telemetry WHERE soh_pct IS NOT NULL GROUP BY 1"""))}
    out = []
    for s in systems(engine):
        sid = s["battery_system_id"]
        m, b = module_days.get(sid), bms.get(sid)
        out.append({**s, "bms_days": b[0] if b else 0,
                    "soh_min": float(b[1]) if b and b[1] is not None else None,
                    "soh_max": float(b[2]) if b and b[2] is not None else None,
                    "module_from": m[0].isoformat() if m else None, "module_to": m[1].isoformat() if m else None,
                    "module_days": int(m[2]) if m else 0})
    return out


def coverage(engine: Engine) -> dict:
    """Date ranges available for training (for the page)."""
    with engine.connect() as conn:
        bms = conn.execute(text("""SELECT min(ts)::date, max(ts)::date, count(DISTINCT ts::date) FROM
                                   battery_telemetry.system_telemetry WHERE soh_pct IS NOT NULL""")).one()
        module_days = [r[0].isoformat() for r in conn.execute(text(
            "SELECT DISTINCT ts::date FROM battery_telemetry.module_telemetry ORDER BY 1"))]
        snapshot_days = [r[0].isoformat() for r in conn.execute(text(
            "SELECT DISTINCT snapshot_time::date FROM battery_raw.batchlog WHERE status <> 'FAILED' AND snapshot_time IS NOT NULL ORDER BY 1"))]
    return {"bms_from": bms[0], "bms_to": bms[1], "bms_days": bms[2], "module_days": module_days,
            "snapshot_days": snapshot_days}


def summarize(df: pd.DataFrame) -> dict:
    """Row count, span and target spread of a dataset (for the preview and the warnings)."""
    if df.empty:
        return {"rows": 0}
    y = df[TARGET]
    return {
        "rows": int(len(df)),
        "systems": int(df["system_id"].nunique()),
        "from": df["ts"].min().isoformat(), "to": df["ts"].max().isoformat(),
        "days": int(df["ts"].dt.date.nunique()),
        "target_min": float(y.min()), "target_max": float(y.max()),
        "target_std": float(y.std()) if len(y) > 1 else 0.0,
        "module_rows": int(df["has_module"].sum()),
        "missing_values": int(df.drop(columns=["system_id", "ts", TARGET, "has_module"]).isna().sum().sum()),
        "by_system": [{"system_id": int(sid), "rows": int(len(g)), "from": g["ts"].min().isoformat(),
                       "to": g["ts"].max().isoformat(), "target_min": float(g[TARGET].min()),
                       "target_max": float(g[TARGET].max()), "module_rows": int(g["has_module"].sum())}
                      for sid, g in df.groupby("system_id")],
    }


def latest_row(engine: Engine, sel: DataSelection) -> Optional[pd.Series]:
    """The newest feature row for a selection (to prefill the SOH Estimator). With a system, only its last two days
    are read first (the whole history only when they hold no usable row, e.g. no module data)."""
    if sel.system_id is not None and sel.date_from is None:
        with engine.connect() as conn:
            last = conn.execute(text("SELECT max(ts) FROM battery_telemetry.system_telemetry "
                                     "WHERE system_id = :sid AND soh_pct IS NOT NULL"), {"sid": sel.system_id}).scalar()
        if last is None:
            return None
        start = (_local(last) - pd.Timedelta(days=1)).date()
        df = build_dataset(engine, DataSelection(**{**sel.__dict__, "date_from": start}))
        if not df.empty:
            return df.iloc[-1]
    df = build_dataset(engine, sel)
    return None if df.empty else df.iloc[-1]


def _local(ts) -> pd.Timestamp:
    """A database timestamp as plant local clock time (naive)."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert("Asia/Kolkata").tz_localize(None)


def systems(engine: Engine) -> list[dict]:
    """Sites and their battery systems, with the span of BMS telemetry each has (for the pickers)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.site_id, s.site_name, b.battery_system_id, b.system_name, t.first_ts, t.last_ts,
                   b.rated_energy_mwh
            FROM battery_master.battery_system b
            JOIN battery_master.site s ON s.site_id = b.site_id
            LEFT JOIN LATERAL (
                SELECT min(ts) AS first_ts, max(ts) AS last_ts FROM battery_telemetry.system_telemetry
                WHERE system_id = b.battery_system_id AND soh_pct IS NOT NULL) t ON true
            ORDER BY s.site_name, b.system_name""")).mappings().all()
    return [{"site_id": r["site_id"], "site_name": r["site_name"], "battery_system_id": r["battery_system_id"],
             "system_name": r["system_name"], "has_telemetry": r["last_ts"] is not None,
             "rated_kwh": float(r["rated_energy_mwh"]) * 1000 if r["rated_energy_mwh"] is not None else None,
             "first_ts": fmt_ts(_local(r["first_ts"])) if r["first_ts"] else None,
             "last_ts": fmt_ts(_local(r["last_ts"])) if r["last_ts"] else None}
            for r in rows]


def to_float(v) -> Optional[float]:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def fmt_ts(ts) -> Optional[str]:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).isoformat()


def as_date(value) -> Optional[date]:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else datetime.fromisoformat(str(value)).date()
