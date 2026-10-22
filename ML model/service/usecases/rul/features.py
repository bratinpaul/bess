"""RUL training data: the fleet's monthly aging snapshots (battery_master.v_rul_training) with the chemistry, BOL
resistance and EOL criteria of each unit, the RPT checkpoints (capacity_test) and the failure events (lifecycle_event).

Per snapshot row:
  health      soh_pct, internal_resistance_mohm and r_ratio = R / BOL R
  stress      age_days, equiv_full_cycles, cum_throughput_mwh, avg_dod_pct, avg_cell_temp_c, days_at_high_soc
  context     batch_lot, usage_cycles_per_day, climate_avg_temp_c, bol_capacity_kwh
  derived     cpd_recent (EFC per day over the last ~180 days), temp_mean (mean cell temperature to date)
  labels      rul_days / rul_cycles (only trusted for retired units), duration / event for survival:
                retired unit   duration = rul_days, event = 1
                censored unit  duration = days from the snapshot to the unit's last snapshot (known alive), event = 0
              With failures_as = 'censored', units that ended in a FAILURE event are treated as censored at the failure
              (a capacity-fade view of life); with 'event' (default) any end of life counts.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

STRESS = ["age_days", "equiv_full_cycles", "cum_throughput_mwh", "avg_dod_pct", "avg_cell_temp_c", "days_at_high_soc"]
HEALTH = ["soh_pct", "internal_resistance_mohm", "r_ratio"]
CONTEXT = ["usage_cycles_per_day", "climate_avg_temp_c", "bol_capacity_kwh"]
DERIVED = ["cpd_recent", "temp_mean"]
FEATURE_GROUPS = {
    "stress": {"label": "Accumulated stress (cycles, throughput, DoD, temperature, high-SOC days, age)", "columns": STRESS},
    "health": {"label": "Health state (SOH, internal resistance, R / BOL R)", "columns": HEALTH},
    "context": {"label": "Batch, duty and climate context", "columns": CONTEXT + ["batch_code"]},
    "derived": {"label": "Recent duty and temperature exposure", "columns": DERIVED},
}
DEFAULT_EOL = {"soh_eol_pct": 70.0, "resistance_eol_pct": 200.0}


@dataclass
class Fleet:
    rows: pd.DataFrame          # one row per unit and snapshot
    units: pd.DataFrame         # one row per unit
    rpt: pd.DataFrame           # RPT checkpoints
    eol: dict                   # chemistry -> {soh_eol_pct, resistance_eol_pct, description}
    batches: list


def systems(engine: Engine) -> list[dict]:
    """Battery systems with aging data: chemistry, batch, data coverage and status (for the builder)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.battery_system_id AS system_id, s.system_name AS system_code, p.chemistry, p.batch_lot, p.usage_cycles_per_day, p.climate_avg_temp_c,
                   count(a.snapshot_date) AS snapshots, min(a.snapshot_date) AS first_date, max(a.snapshot_date) AS last_date,
                   bool_or(a.eol_reached) AS retired,
                   (SELECT count(*) FROM battery_master.capacity_test t WHERE t.system_id = s.battery_system_id) AS rpt_tests,
                   (SELECT string_agg(DISTINCT e.event_type, ',') FROM battery_master.lifecycle_event e
                     WHERE e.system_id = s.battery_system_id AND e.event_type IN ('EOL_REACHED', 'FAILURE', 'DECOMMISSION')) AS end_events
            FROM battery_master.battery_system s
            LEFT JOIN battery_master.battery_provenance p ON p.system_id = s.battery_system_id
            LEFT JOIN battery_master.aging_snapshot a ON a.system_id = s.battery_system_id
            GROUP BY 1, 2, 3, 4, 5, 6
            HAVING count(a.snapshot_date) > 0          -- only battery systems with aging data
            ORDER BY s.system_name""")).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("usage_cycles_per_day", "climate_avg_temp_c"):
            d[k] = _f(d[k])
        for k in ("first_date", "last_date"):
            d[k] = d[k].isoformat() if d[k] else None
        d["retired"] = bool(d["retired"])
        out.append(d)
    return out


def eol_criteria(engine: Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT chemistry, soh_eol_pct, resistance_eol_pct, description FROM battery_master.eol_criteria")).all()
    return {r[0].upper(): {"soh_eol_pct": float(r[1]), "resistance_eol_pct": _f(r[2]), "description": r[3]} for r in rows}


def load(engine: Engine, system_ids: Optional[list[int]] = None, failures_as: str = "event") -> Fleet:
    with engine.connect() as conn:
        rows = pd.read_sql(text("""
            SELECT v.*, COALESCE(upper(p.chemistry), 'UNKNOWN') AS chemistry, p.bol_resistance_mohm
            FROM battery_master.v_rul_training v
            LEFT JOIN battery_master.battery_provenance p ON p.system_id = v.system_id
            WHERE (CAST(:ids AS bigint[]) IS NULL OR v.system_id = ANY(CAST(:ids AS bigint[])))
            ORDER BY v.system_code, v.snapshot_date"""), conn, params={"ids": system_ids})
        rpt = pd.read_sql(text("""
            SELECT t.system_id, t.test_date, t.age_days, t.equiv_full_cycles, t.soh_pct, t.internal_resistance_mohm
            FROM battery_master.capacity_test t
            WHERE (CAST(:ids AS bigint[]) IS NULL OR t.system_id = ANY(CAST(:ids AS bigint[])))
            ORDER BY t.system_id, t.test_date"""), conn, params={"ids": system_ids})
        events = pd.read_sql(text("""
            SELECT system_id, event_type, event_date, failure_mode FROM battery_master.lifecycle_event
            WHERE event_type IN ('EOL_REACHED', 'FAILURE', 'DECOMMISSION')"""), conn)
    eol = eol_criteria(engine)
    num = STRESS + ["soh_pct", "internal_resistance_mohm", "calendar_age_years", "usage_cycles_per_day",
                    "climate_avg_temp_c", "bol_capacity_kwh", "bol_resistance_mohm", "rul_days", "rul_cycles"]
    for c in num:
        rows[c] = pd.to_numeric(rows[c], errors="coerce").astype(float)
    for c in ("age_days", "equiv_full_cycles", "soh_pct", "internal_resistance_mohm"):
        rpt[c] = pd.to_numeric(rpt[c], errors="coerce").astype(float)
    rows["snapshot_date"] = pd.to_datetime(rows["snapshot_date"])
    rpt["test_date"] = pd.to_datetime(rpt["test_date"])
    rows = rows.dropna(subset=["soh_pct", "age_days", "equiv_full_cycles"]).reset_index(drop=True)
    rows["is_censored"] = rows["is_censored"].fillna(True).astype(bool)
    rows["eol_reached"] = rows["eol_reached"].fillna(False).astype(bool)

    # BOL resistance: provenance, else the first measured value of the unit
    first_r = rows.groupby("system_id")["internal_resistance_mohm"].transform("first")
    rows["bol_resistance_mohm"] = rows["bol_resistance_mohm"].fillna(first_r)
    rows["r_ratio"] = rows["internal_resistance_mohm"] / rows["bol_resistance_mohm"]
    rows["temp_mean"] = rows.groupby("system_id")["avg_cell_temp_c"].transform(lambda s: s.expanding().mean())
    rows["cpd_recent"] = rows.groupby("system_id", group_keys=False).apply(_cpd_recent)
    batches = sorted(rows["batch_lot"].fillna("UNKNOWN").unique())
    rows["batch_lot"] = rows["batch_lot"].fillna("UNKNOWN")
    rows["batch_code"] = rows["batch_lot"].map({b: i for i, b in enumerate(batches)}).astype(float)

    # units: status, end type, survival targets
    failed = set(events.loc[events["event_type"] == "FAILURE", "system_id"])
    last = rows.groupby("system_id").agg(system_code=("system_code", "first"), chemistry=("chemistry", "first"),
                                         batch_lot=("batch_lot", "first"), last_date=("snapshot_date", "max"),
                                         first_date=("snapshot_date", "min"), retired=("eol_reached", "max"),
                                         snapshots=("soh_pct", "size"), bol_r=("bol_resistance_mohm", "first"))
    last["failed"] = last.index.isin(failed)
    last["event_unit"] = last["retired"] & ~(last["failed"] & (failures_as == "censored"))
    rows = rows.merge(last[["last_date", "retired", "failed", "event_unit"]], left_on="system_id", right_index=True)
    alive = (rows["last_date"] - rows["snapshot_date"]).dt.days.astype(float)
    rows["known_alive_days"] = np.where(rows["retired"], np.nan, alive)
    rows["duration"] = np.where(rows["event_unit"], rows["rul_days"], np.where(rows["retired"], rows["rul_days"], alive))
    rows["event"] = rows["event_unit"].astype(int)
    rows["life_fraction"] = np.where(rows["retired"], rows["age_days"] / (rows["age_days"] + rows["rul_days"]).clip(lower=1), np.nan)
    units = last.reset_index()
    rpt = rpt[rpt["system_id"].isin(units["system_id"])].copy()
    rpt["r_ratio"] = rpt["internal_resistance_mohm"] / rpt["system_id"].map(last["bol_r"])
    return Fleet(rows=rows.reset_index(drop=True), units=units, rpt=rpt, eol=eol, batches=batches)


def eol_for(fleet_eol: dict, chemistry: str) -> dict:
    return fleet_eol.get((chemistry or "").upper(), DEFAULT_EOL)


def _cpd_recent(g: pd.DataFrame) -> pd.Series:
    """EFC per day over the last ~180 days (else since the start)."""
    age, efc = g["age_days"].to_numpy(), g["equiv_full_cycles"].to_numpy()
    out = np.empty(len(g))
    for i in range(len(g)):
        j = np.searchsorted(age, age[i] - 180)
        j = min(j, i - 1) if i > 0 else 0
        span = age[i] - age[j]
        out[i] = (efc[i] - efc[j]) / span if span > 0 else (efc[i] / age[i] if age[i] > 0 else np.nan)
    return pd.Series(out, index=g.index)


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
