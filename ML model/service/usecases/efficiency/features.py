"""PCS operating points: pcs_telemetry + the pcs master -> one row per 5-minute reading with the efficiency drivers.

Sign convention of the telemetry: ac_active_power_kw > 0 is charging (import), < 0 discharging (export).
efficiency_pct is the measured one-direction conversion efficiency (output / input):
    discharge  eta = P_ac / P_dc        charge  eta = P_dc / P_ac
Losses are expressed from the AC power and eta (so they agree with the label):
    discharge  P_loss = |P_ac| (1/eta - 1)        charge  P_loss = |P_ac| (1 - eta)
Everything that scales is per unit of the PCS rating, so units of different size share one model.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TARGET = "eta_pct"
REF_TEMP_C = 40.0  # grey-box temperature reference (IGBT)
ACTIVE_MODES = ("GRID_FOLLOWING", "GRID_FORMING")
GRID_SERVICES = ("NONE", "FREQ_WATT", "VOLT_VAR")

# the model inputs (estimator form, GAM terms, residual model features)
FEATURES: dict[str, dict] = {
    "load_frac": {"label": "Load fraction |P| / rated", "unit": "pu", "group": "load"},
    "is_charge": {"label": "Direction (1 = charge)", "unit": "", "group": "load"},
    "s_frac": {"label": "Apparent power |S| / rated", "unit": "pu", "group": "reactive"},
    "pf_abs": {"label": "Power factor |PF|", "unit": "", "group": "reactive"},
    "v_dc_pu": {"label": "DC bus voltage / nominal", "unit": "pu", "group": "dc"},
    "igbt_temp_c": {"label": "IGBT temperature", "unit": "°C", "group": "thermal"},
    "heatsink_temp_c": {"label": "Heatsink temperature", "unit": "°C", "group": "thermal"},
    "inlet_coolant_temp_c": {"label": "Inlet coolant temperature", "unit": "°C", "group": "thermal"},
    "ambient_temp_c": {"label": "Ambient temperature", "unit": "°C", "group": "thermal"},
    "v_ac_pu": {"label": "AC voltage / rated", "unit": "pu", "group": "grid"},
    "freq_dev_hz": {"label": "Frequency deviation", "unit": "Hz", "group": "grid"},
    "gs_freq_watt": {"label": "Grid service FREQ_WATT", "unit": "", "group": "mode"},
    "gs_volt_var": {"label": "Grid service VOLT_VAR", "unit": "", "group": "mode"},
    "age_years": {"label": "Asset age", "unit": "years", "group": "asset"},
}
FEATURE_GROUPS = {
    "load": "Load fraction & direction",
    "reactive": "Apparent power / power factor",
    "dc": "DC bus voltage",
    "thermal": "Temperatures (IGBT, heatsink, coolant, ambient)",
    "grid": "AC voltage & frequency",
    "mode": "Grid service / mode",
    "asset": "Asset identity & age",
}
REQUIRED_GROUPS = ("load",)

_POINTS_SQL = """
SELECT t.pcs_id, t.ts, t.mode_code, t.grid_service,
       t.ac_active_power_kw, t.ac_reactive_power_kvar, t.ac_apparent_power_kva, t.power_factor, t.ac_frequency_hz,
       (t.ac_voltage_ab_v + t.ac_voltage_bc_v + t.ac_voltage_ca_v) / 3.0 AS ac_voltage_v,
       t.dc_voltage_v, t.dc_current_a, t.dc_power_kw, t.efficiency_pct,
       t.igbt_temp_c, t.heatsink_temp_c, t.inlet_coolant_temp_c, t.ambient_temp_c,
       EXISTS (SELECT 1 FROM battery_raw.batchlog b WHERE b.snapshot_time = t.ts AND b.status <> 'FAILED') AS from_snapshot
FROM battery_telemetry.pcs_telemetry t
WHERE t.pcs_id = ANY(CAST(:pcs AS bigint[]))
  AND t.mode_code = ANY(CAST(:modes AS text[]))
  AND t.efficiency_pct IS NOT NULL AND t.efficiency_pct > 0
  AND (CAST(:date_from AS date) IS NULL OR t.ts >= CAST(:date_from AS date))
  AND (CAST(:date_to AS date) IS NULL OR t.ts < CAST(:date_to AS date) + 1)
ORDER BY t.pcs_id, t.ts
"""

_UNITS_SQL = """
SELECT p.pcs_id, p.pcs_code, p.system_id AS battery_system_id, bs.system_name, s.site_name,
       p.manufacturer, p.model, p.topology, p.rated_power_kw, COALESCE(p.rated_apparent_kva, p.rated_power_kw) AS rated_kva,
       p.rated_ac_voltage_v, p.ac_frequency_hz AS nominal_hz, p.dc_voltage_nom_v, p.efficiency_pct AS datasheet_eff_pct,
       p.commissioned_on, bs.rated_energy_mwh,
       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t.dc_voltage_v) FROM battery_telemetry.pcs_telemetry t
         WHERE t.pcs_id = p.pcs_id AND t.dc_voltage_v > 0) AS dc_voltage_median_v
FROM battery_master.pcs p
LEFT JOIN battery_master.battery_system bs ON bs.battery_system_id = p.system_id
LEFT JOIN battery_master.site s ON s.site_id = bs.site_id
ORDER BY p.pcs_id
"""


@dataclass
class Selection:
    pcs_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    min_load_frac: float = 0.02  # below this the readings are standby noise
    exclude_snapshots: bool = True
    feature_groups: list[str] = field(default_factory=lambda: list(FEATURE_GROUPS))

    @property
    def features(self) -> list[str]:
        groups = set(self.feature_groups) | set(REQUIRED_GROUPS)
        return [f for f, spec in FEATURES.items() if spec["group"] in groups]


def units(engine: Engine) -> pd.DataFrame:
    """The PCS units with their ratings; the nominal DC voltage falls back to the unit's median DC voltage."""
    with engine.connect() as conn:
        df = pd.read_sql(text(_UNITS_SQL), conn)
    for c in ("rated_power_kw", "rated_kva", "rated_ac_voltage_v", "nominal_hz", "dc_voltage_nom_v",
              "datasheet_eff_pct", "rated_energy_mwh", "dc_voltage_median_v"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["v_dc_ref"] = df["dc_voltage_nom_v"].fillna(df["dc_voltage_median_v"])
    df["nominal_hz"] = df["nominal_hz"].fillna(50.0)
    return df


def unit_info(row: pd.Series) -> dict:
    return {
        "pcs_id": int(row.pcs_id), "pcs_code": row.pcs_code,
        "battery_system_id": None if pd.isna(row.battery_system_id) else int(row.battery_system_id),
        "system_name": row.system_name, "site_name": row.site_name, "manufacturer": row.manufacturer,
        "model": row.model, "topology": row.topology, "rated_power_kw": to_float(row.rated_power_kw),
        "rated_kva": to_float(row.rated_kva), "rated_ac_voltage_v": to_float(row.rated_ac_voltage_v),
        "nominal_hz": to_float(row.nominal_hz), "v_dc_ref": to_float(row.v_dc_ref),
        "dc_voltage_from": "master" if pd.notna(row.dc_voltage_nom_v) else "median of telemetry",
        "datasheet_eff_pct": to_float(row.datasheet_eff_pct),
        "commissioned_on": row.commissioned_on.isoformat() if pd.notna(row.commissioned_on) else None,
        "rated_energy_mwh": to_float(row.rated_energy_mwh),
    }


def derive(raw: pd.DataFrame, u: pd.DataFrame) -> pd.DataFrame:
    """Raw readings (telemetry column names) -> model rows. Used for training and for the estimator's inputs."""
    df = raw.merge(u[["pcs_id", "rated_power_kw", "rated_kva", "rated_ac_voltage_v", "nominal_hz", "v_dc_ref",
                      "commissioned_on"]], on="pcs_id", how="left")
    p = pd.to_numeric(df["ac_active_power_kw"], errors="coerce").astype(float)
    rated = df["rated_power_kw"].astype(float)
    kva = df["rated_kva"].astype(float)
    s = pd.to_numeric(df["ac_apparent_power_kva"], errors="coerce").astype(float).abs()
    s = s.where(s > 0, p.abs())
    out = pd.DataFrame({"pcs_id": df["pcs_id"].astype(int),
                        "ts": pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Kolkata")})  # plant time
    out["load_frac"] = p.abs() / rated
    out["is_charge"] = (p > 0).astype(float)
    out["s_frac"] = s / kva
    pf = pd.to_numeric(df["power_factor"], errors="coerce").astype(float).abs()
    out["pf_abs"] = pf.fillna((p.abs() / s).clip(upper=1.0))
    out["v_dc_pu"] = pd.to_numeric(df["dc_voltage_v"], errors="coerce").astype(float) / df["v_dc_ref"].astype(float)
    for c in ("igbt_temp_c", "heatsink_temp_c", "inlet_coolant_temp_c", "ambient_temp_c"):
        out[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    out["v_ac_pu"] = pd.to_numeric(df["ac_voltage_v"], errors="coerce").astype(float) / df["rated_ac_voltage_v"].astype(float)
    out["freq_dev_hz"] = pd.to_numeric(df["ac_frequency_hz"], errors="coerce").astype(float) - df["nominal_hz"].astype(float)
    gs = df["grid_service"].fillna("NONE").astype(str).str.upper()
    out["gs_freq_watt"] = (gs == "FREQ_WATT").astype(float)
    out["gs_volt_var"] = (gs == "VOLT_VAR").astype(float)
    commissioned = pd.to_datetime(df["commissioned_on"], errors="coerce")
    ts_naive = out["ts"].dt.tz_localize(None) if out["ts"].dt.tz is not None else out["ts"]
    out["age_years"] = ((ts_naive - commissioned).dt.days / 365.25).fillna(0.0).clip(lower=0)
    out["p_ac_kw"] = p.abs()
    out["rated_kw"] = rated
    if "efficiency_pct" in df:
        eta = pd.to_numeric(df["efficiency_pct"], errors="coerce").astype(float)
        out[TARGET] = eta
        e = eta / 100.0
        loss = np.where(out["is_charge"] > 0, out["p_ac_kw"] * (1 - e), out["p_ac_kw"] * (1 / e - 1))
        out["loss_kw"] = loss
    if "from_snapshot" in df:
        out["from_snapshot"] = df["from_snapshot"].astype(bool)
    return out


def build(engine: Engine, sel: Selection) -> pd.DataFrame:
    """Training rows: active readings above the light-load cut with a measured efficiency."""
    if not sel.pcs_ids:
        return pd.DataFrame()
    with engine.connect() as conn:
        raw = pd.read_sql(text(_POINTS_SQL), conn, params={
            "pcs": sel.pcs_ids, "modes": list(ACTIVE_MODES), "date_from": sel.date_from, "date_to": sel.date_to})
    if raw.empty:
        return pd.DataFrame()
    df = derive(raw, units(engine))
    df = df[(df["load_frac"] >= sel.min_load_frac) & df[TARGET].between(50, 100)]
    if sel.exclude_snapshots and "from_snapshot" in df:
        df = df[~df["from_snapshot"]]
    # the light-load and missing-value cleanup: fill sensor gaps with the unit's median
    for f in FEATURES:
        if f in df and df[f].isna().any():
            df[f] = df[f].fillna(df.groupby("pcs_id")[f].transform("median")).fillna(df[f].median())
    return df.reset_index(drop=True)


def coverage(engine: Engine) -> list[dict]:
    """Per PCS unit: readings, active readings with an efficiency, and the date span."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pcs_id, count(*) AS readings,
                   count(*) FILTER (WHERE mode_code = ANY(CAST(:modes AS text[])) AND efficiency_pct > 0) AS active,
                   count(*) FILTER (WHERE mode_code = ANY(CAST(:modes AS text[])) AND ac_active_power_kw > 0) AS charging,
                   count(*) FILTER (WHERE mode_code = ANY(CAST(:modes AS text[])) AND ac_active_power_kw < 0) AS discharging,
                   min(ts)::date AS date_from, max(ts)::date AS date_to
            FROM battery_telemetry.pcs_telemetry GROUP BY pcs_id"""), {"modes": list(ACTIVE_MODES)}).mappings().all()
    stats = {r["pcs_id"]: dict(r) for r in rows}
    out = []
    for _, u in units(engine).iterrows():
        s = stats.get(int(u.pcs_id), {})
        out.append({**unit_info(u), "readings": int(s.get("readings", 0)), "active": int(s.get("active", 0)),
                    "charging": int(s.get("charging", 0)), "discharging": int(s.get("discharging", 0)),
                    "date_from": s["date_from"].isoformat() if s.get("date_from") else None,
                    "date_to": s["date_to"].isoformat() if s.get("date_to") else None})
    return out


def latest_point(engine: Engine, pcs_id: int, direction: Optional[str] = None, min_load_frac: float = 0.0) -> Optional[dict]:
    """The newest active reading of a unit (optionally of one direction) at or above a load fraction, as raw
    estimator inputs."""
    cond = {"charge": "AND ac_active_power_kw > 0", "discharge": "AND ac_active_power_kw < 0"}.get(direction or "", "")
    cond += """ AND abs(ac_active_power_kw) >= :min_load *
        (SELECT rated_power_kw FROM battery_master.pcs WHERE pcs_id = :id)"""
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT ts, grid_service, ac_active_power_kw, ac_reactive_power_kvar, ac_apparent_power_kva, power_factor,
                   ac_frequency_hz, (ac_voltage_ab_v + ac_voltage_bc_v + ac_voltage_ca_v) / 3.0 AS ac_voltage_v,
                   dc_voltage_v, igbt_temp_c, heatsink_temp_c, inlet_coolant_temp_c, ambient_temp_c, efficiency_pct
            FROM battery_telemetry.pcs_telemetry
            WHERE pcs_id = :id AND mode_code = ANY(CAST(:modes AS text[])) AND efficiency_pct > 0 {cond}
            ORDER BY ts DESC LIMIT 1"""), {"id": pcs_id, "modes": list(ACTIVE_MODES),
                                           "min_load": min_load_frac}).mappings().first()
    if not row:
        return None
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else to_float(v) if not isinstance(v, str) else v)
           for k, v in row.items()}
    out["direction"] = "charge" if (out["ac_active_power_kw"] or 0) > 0 else "discharge"
    return out


def to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
