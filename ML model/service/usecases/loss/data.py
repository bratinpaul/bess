"""Inputs of the loss decomposition: the time-aligned 5-min streams of one battery system and its master data.

One row per BMS timestamp that has PCS and EMS readings at the same ts (inner join = a common grid; HVAC is optional).
Telemetry sign: every power is + toward the battery (charge) and - toward the grid (discharge), at every node.

  p_poi_kw    EMS poi_active_power_kw               (POI meter; includes the auxiliary import)
  aux_kw      EMS aux_load_kw                        (HVAC + controls, tapped between the POI and the PCS AC side)
  p_ac_kw     PCS ac_active_power_kw (sum of units)  (inverter AC terminals)
  p_dc_kw     PCS dc_power_kw (sum of units)         (inverter DC bus)
  p_term_kw   BMS power_kw                           (battery terminals)
  ocv_v       cell OCV from battery_master.ocv_curve (MEAN branch) at the reported SOC and cell temperature,
              x the cells in series -> p_chem_kw = OCV_pack x pack current (power into / out of the chemistry)
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

TZ = "Asia/Kolkata"


class LossDataError(Exception):
    """Bad input for a loss run (the API answers 400)."""


_SERIES_SQL = """
WITH pcs AS (
    SELECT t.ts, sum(t.ac_active_power_kw) AS p_ac_kw, sum(t.dc_power_kw) AS p_dc_kw,
           sum(abs(t.ac_apparent_power_kva)) AS s_kva, sum(t.ac_reactive_power_kvar) AS q_kvar,
           avg(t.efficiency_pct) AS efficiency_pct, max(t.igbt_temp_c) AS igbt_temp_c,
           max(t.ambient_temp_c) AS pcs_ambient_c, sum(t.ac_energy_import_kwh) AS ac_import_kwh,
           sum(t.ac_energy_export_kwh) AS ac_export_kwh, min(t.mode_code) AS mode_code, min(t.grid_service) AS grid_service
    FROM battery_telemetry.pcs_telemetry t
    WHERE t.pcs_id = ANY(CAST(:pcs_ids AS bigint[]))
      AND t.ts >= CAST(:date_from AS date) AND t.ts < CAST(:date_to AS date) + 1
    GROUP BY t.ts
), hvac AS (
    SELECT h.ts, sum(h.hvac_power_kw) AS hvac_kw, avg(h.ambient_temp_c) AS ambient_c
    FROM battery_telemetry.hvac_telemetry h
    WHERE h.hvac_id = ANY(CAST(:hvac_ids AS bigint[]))
      AND h.ts >= CAST(:date_from AS date) AND h.ts < CAST(:date_to AS date) + 1
    GROUP BY h.ts
)
SELECT s.ts, s.power_kw AS p_term_kw, s.pack_voltage_v, s.pack_current_a, s.cell_v_avg_v, s.cell_temp_avg_c,
       s.soc_bms_pct AS soc_pct, s.soh_pct, s.cum_charge_kwh, s.cum_discharge_kwh,
       p.p_ac_kw, p.p_dc_kw, p.s_kva, p.q_kvar, p.efficiency_pct, p.igbt_temp_c, p.pcs_ambient_c, p.ac_import_kwh, p.ac_export_kwh, p.mode_code,
       p.grid_service,
       e.poi_active_power_kw AS p_poi_kw, e.aux_load_kw AS aux_kw, e.market_price_mwh AS price_mwh,
       e.cum_import_kwh AS poi_import_kwh, e.cum_export_kwh AS poi_export_kwh,
       h.hvac_kw, h.ambient_c
FROM battery_telemetry.system_telemetry s
JOIN pcs p ON p.ts = s.ts
JOIN battery_telemetry.ems_telemetry e ON e.ems_id = :ems_id AND e.ts = s.ts
LEFT JOIN hvac h ON h.ts = s.ts
WHERE s.system_id = :sid
  AND s.ts >= CAST(:date_from AS date) AND s.ts < CAST(:date_to AS date) + 1
ORDER BY s.ts
"""

NUMERIC = ["p_term_kw", "pack_voltage_v", "pack_current_a", "cell_v_avg_v", "cell_temp_avg_c", "soc_pct", "soh_pct",
           "cum_charge_kwh", "cum_discharge_kwh", "p_ac_kw", "p_dc_kw", "s_kva", "q_kvar", "efficiency_pct",
           "igbt_temp_c", "pcs_ambient_c", "ac_import_kwh", "ac_export_kwh", "p_poi_kw", "aux_kw", "price_mwh", "poi_import_kwh", "poi_export_kwh",
           "hvac_kw", "ambient_c"]


@dataclass
class SystemMaster:
    system_id: int
    system_name: str
    site_id: int
    site_name: str
    chemistry: Optional[str]
    rated_kw: float                 # least(battery rated power, sum of PCS rated kW)
    rated_kva: float                # sum of PCS rated kVA (rated kW when not given)
    usable_kwh: float               # battery_opt_param.usable_energy_mwh, else rated energy
    series_cells_master: Optional[int]
    pcs_ids: list[int]
    pcs_nameplate_eff_pct: Optional[float]
    ems_id: int
    hvac_ids: list[int]
    transformer_kva: Optional[float]   # battery_master.transformer.rating_mva of the site (none in the sample)
    transformer_name: Optional[str]
    self_discharge_pct_day: Optional[float]
    rte_ac_param: Optional[float]      # battery_opt_param.rte_ac (the optimizer's assumed AC round trip)
    first_ts: Optional[pd.Timestamp] = None
    last_ts: Optional[pd.Timestamp] = None
    notes: list[str] = field(default_factory=list)


def systems(engine: Engine) -> list[dict]:
    """Battery systems with BMS, PCS and EMS telemetry (the ones a loss run can cover), with their span."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT b.battery_system_id, b.system_name, s.site_id, s.site_name,
                   (SELECT min(ems_id) FROM battery_master.ems_controller WHERE battery_system_id = b.battery_system_id) AS ems_id,
                   (SELECT array_agg(pcs_id ORDER BY pcs_id) FROM battery_master.pcs WHERE system_id = b.battery_system_id) AS pcs_ids,
                   t.first_ts, t.last_ts, t.n
            FROM battery_master.battery_system b
            JOIN battery_master.site s ON s.site_id = b.site_id
            LEFT JOIN LATERAL (SELECT min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS n
                               FROM battery_telemetry.system_telemetry WHERE system_id = b.battery_system_id) t ON true
            ORDER BY s.site_name, b.system_name""")).mappings().all()
        out = []
        for r in rows:
            if not r["ems_id"] or not r["pcs_ids"] or not r["n"]:
                continue
            has = conn.execute(text("""
                SELECT EXISTS (SELECT 1 FROM battery_telemetry.pcs_telemetry WHERE pcs_id = ANY(:p))
                   AND EXISTS (SELECT 1 FROM battery_telemetry.ems_telemetry WHERE ems_id = :e)"""),
                {"p": list(r["pcs_ids"]), "e": r["ems_id"]}).scalar()
            if not has:
                continue
            out.append({"system_id": r["battery_system_id"], "system_name": r["system_name"], "site_id": r["site_id"],
                        "site_name": r["site_name"], "intervals": int(r["n"]),
                        "first_day": _local(r["first_ts"]).date().isoformat(),
                        "last_day": _local(r["last_ts"]).date().isoformat()})
    return out


def master(engine: Engine, system_id: int) -> SystemMaster:
    with engine.connect() as conn:
        b = conn.execute(text("""
            SELECT b.battery_system_id, b.system_name, b.site_id, s.site_name, b.chemistry_code, b.series_cells,
                   b.rated_power_mw, b.rated_energy_mwh
            FROM battery_master.battery_system b JOIN battery_master.site s ON s.site_id = b.site_id
            WHERE b.battery_system_id = :id"""), {"id": system_id}).mappings().first()
        if not b:
            raise LossDataError(f"Battery system {system_id} not found")
        pcs = conn.execute(text("""SELECT pcs_id, rated_power_kw, rated_apparent_kva, efficiency_pct
                                   FROM battery_master.pcs WHERE system_id = :id ORDER BY pcs_id"""),
                           {"id": system_id}).mappings().all()
        ems = conn.execute(text("SELECT min(ems_id) FROM battery_master.ems_controller WHERE battery_system_id = :id"),
                           {"id": system_id}).scalar()
        hvac = [r[0] for r in conn.execute(text(
            "SELECT hvac_id FROM battery_master.hvac_unit WHERE battery_system_id = :id ORDER BY hvac_id"), {"id": system_id})]
        xf = conn.execute(text("""SELECT transformer_name, rating_mva FROM battery_master.transformer
                                  WHERE site_id = :s ORDER BY transformer_id LIMIT 1"""), {"s": b["site_id"]}).mappings().first()
        opt = conn.execute(text("""SELECT usable_energy_mwh, self_discharge_pct_day, rte_ac FROM battery_master.battery_opt_param
                                   WHERE system_id = :id ORDER BY valid_from DESC LIMIT 1"""), {"id": system_id}).mappings().first()
    if not pcs:
        raise LossDataError(f"{b['system_name']} has no PCS in the master data")
    if ems is None:
        raise LossDataError(f"{b['system_name']} has no EMS controller in the master data")
    pcs_kw = sum(float(p["rated_power_kw"] or 0) for p in pcs)
    pcs_kva = sum(float(p["rated_apparent_kva"] or p["rated_power_kw"] or 0) for p in pcs)
    batt_kw = float(b["rated_power_mw"]) * 1000 if b["rated_power_mw"] else None
    notes = []
    rated_kw = min(x for x in (batt_kw, pcs_kw) if x) if (batt_kw or pcs_kw) else 0.0
    if batt_kw and pcs_kw and abs(batt_kw - pcs_kw) > 0.05 * max(batt_kw, pcs_kw):
        notes.append(f"Battery rated {batt_kw:,.0f} kW vs PCS rated {pcs_kw:,.0f} kW: loading uses {rated_kw:,.0f} kW")
    usable = float(opt["usable_energy_mwh"]) * 1000 if opt and opt["usable_energy_mwh"] else float(b["rated_energy_mwh"] or 0) * 1000
    effs = [float(p["efficiency_pct"]) for p in pcs if p["efficiency_pct"] is not None]
    return SystemMaster(
        system_id=system_id, system_name=b["system_name"], site_id=b["site_id"], site_name=b["site_name"],
        chemistry=b["chemistry_code"], rated_kw=rated_kw, rated_kva=pcs_kva or rated_kw, usable_kwh=usable,
        series_cells_master=b["series_cells"], pcs_ids=[int(p["pcs_id"]) for p in pcs],
        pcs_nameplate_eff_pct=float(np.mean(effs)) if effs else None, ems_id=int(ems), hvac_ids=hvac,
        transformer_kva=float(xf["rating_mva"]) * 1000 if xf and xf["rating_mva"] else None,
        transformer_name=xf["transformer_name"] if xf else None,
        self_discharge_pct_day=float(opt["self_discharge_pct_day"]) if opt and opt["self_discharge_pct_day"] is not None else None,
        rte_ac_param=float(opt["rte_ac"]) if opt and opt["rte_ac"] is not None else None, notes=notes)


def series(engine: Engine, m: SystemMaster, date_from: date, date_to: date) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text(_SERIES_SQL), conn, params={
            "sid": m.system_id, "pcs_ids": m.pcs_ids, "hvac_ids": m.hvac_ids or [-1], "ems_id": m.ems_id,
            "date_from": date_from, "date_to": date_to})
    if df.empty:
        return df
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)  # plant local time
    return df.sort_values("ts").reset_index(drop=True)


def ocv_table(engine: Engine, chemistry: Optional[str]) -> Optional[pd.DataFrame]:
    """The MEAN (hysteresis-free) OCV curve of a chemistry: rows soc_pct, columns temp_c, values ocv_v (per cell)."""
    if not chemistry:
        return None
    with engine.connect() as conn:
        df = pd.read_sql(text("""SELECT temp_c, soc_pct, ocv_v FROM battery_master.ocv_curve
                                 WHERE chemistry = :c AND direction = 'MEAN' ORDER BY temp_c, soc_pct"""),
                         conn, params={"c": chemistry})
    if df.empty:
        return None
    df = df.astype(float)
    return df.pivot(index="soc_pct", columns="temp_c", values="ocv_v").sort_index()


def ocv_lookup(table: pd.DataFrame, soc: np.ndarray, temp: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of the OCV table in SOC and temperature (clipped to the table's range)."""
    socs = table.index.to_numpy(dtype=float)
    temps = table.columns.to_numpy(dtype=float)
    soc = np.clip(np.nan_to_num(soc, nan=50.0), socs[0], socs[-1])
    temp = np.clip(np.nan_to_num(temp, nan=25.0), temps[0], temps[-1])
    per_temp = np.stack([np.interp(soc, socs, table[t].to_numpy(dtype=float)) for t in temps], axis=1)
    if len(temps) == 1:
        return per_temp[:, 0]
    idx = np.clip(np.searchsorted(temps, temp, side="right") - 1, 0, len(temps) - 2)
    t0, t1 = temps[idx], temps[idx + 1]
    w = (temp - t0) / (t1 - t0)
    rows = np.arange(len(soc))
    return per_temp[rows, idx] * (1 - w) + per_temp[rows, idx + 1] * w


def _local(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert(TZ)
