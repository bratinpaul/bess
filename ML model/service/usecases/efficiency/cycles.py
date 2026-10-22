"""Charge-discharge cycles and their round-trip efficiencies, per PCS unit (and its battery system, EMS and HVAC).

A cycle runs from the start of a major charge phase to the start of the next one, so it holds the charge, the
rest, the discharge and the idle time after it - every auxiliary kWh of the day lands in one cycle. A charge
phase is major when its energy reaches `major_share` of the unit's typical (90th percentile) charge phase; the
short charge bursts of frequency regulation stay inside the cycle they happen in.

Per cycle (energies from the cumulative counters, else integrated power):
  DC RTE      E_dc_out / E_dc_in          system_telemetry cum_discharge_kwh / cum_charge_kwh (battery terminals)
  AC RTE      E_ac_out / E_ac_in          pcs_telemetry ac_energy_export_kwh / ac_energy_import_kwh (inverter AC)
  System RTE  E_poi_out / E_poi_in        ems_telemetry cum_export_kwh / cum_import_kwh (POI, net of auxiliaries)
A cycle that doesn't end at its starting SOC stores (or borrows) energy; the outputs are corrected by
ΔSOC × kWh-per-% (estimated per unit from its charge phases), and |ΔSOC| > the tolerance marks it open.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.metrics import regression_scores

_SERIES_SQL = """
SELECT p.pcs_id, p.ts, p.mode_code, p.grid_service, p.ac_active_power_kw, p.ac_reactive_power_kvar,
       p.ac_apparent_power_kva, p.power_factor, p.ac_frequency_hz,
       (p.ac_voltage_ab_v + p.ac_voltage_bc_v + p.ac_voltage_ca_v) / 3.0 AS ac_voltage_v,
       p.dc_voltage_v, p.dc_current_a, p.dc_power_kw, p.efficiency_pct,
       p.igbt_temp_c, p.heatsink_temp_c, p.inlet_coolant_temp_c, p.ambient_temp_c,
       p.ac_energy_import_kwh, p.ac_energy_export_kwh,
       s.soc_bms_pct AS soc_pct, s.soh_pct, s.power_kw AS dc_batt_kw, s.cum_charge_kwh, s.cum_discharge_kwh, s.cell_temp_avg_c,
       e.cum_import_kwh AS poi_import_kwh, e.cum_export_kwh AS poi_export_kwh, e.aux_load_kw,
       h.hvac_power_kw
FROM battery_telemetry.pcs_telemetry p
LEFT JOIN battery_telemetry.system_telemetry s ON s.system_id = :sid AND s.ts = p.ts
LEFT JOIN battery_telemetry.ems_telemetry e
       ON e.ems_id = (SELECT min(ems_id) FROM battery_master.ems_controller WHERE battery_system_id = :sid) AND e.ts = p.ts
LEFT JOIN battery_telemetry.hvac_telemetry h
       ON h.hvac_id = (SELECT min(hvac_id) FROM battery_master.hvac_unit WHERE battery_system_id = :sid) AND h.ts = p.ts
WHERE p.pcs_id = :pcs
  AND (CAST(:date_from AS date) IS NULL OR p.ts >= CAST(:date_from AS date))
  AND (CAST(:date_to AS date) IS NULL OR p.ts < CAST(:date_to AS date) + 1)
ORDER BY p.ts
"""

NUMERIC = ["ac_active_power_kw", "dc_power_kw", "ac_energy_import_kwh", "ac_energy_export_kwh", "soc_pct", "soh_pct",
           "dc_batt_kw", "cum_charge_kwh", "cum_discharge_kwh", "cell_temp_avg_c", "poi_import_kwh", "poi_export_kwh",
           "aux_load_kw", "hvac_power_kw", "ambient_temp_c", "igbt_temp_c"]

# the DC round-trip regression inputs (cycle level)
CYCLE_FEATURES: dict[str, str] = {
    "charge_load_frac": "Charge load fraction (energy-weighted)",
    "discharge_load_frac": "Discharge load fraction (energy-weighted)",
    "depth_pct": "Depth (SOC max - min)",
    "soc_max_pct": "SOC max",
    "cell_temp_avg_c": "Avg cell temperature (active)",
    "rest_hours": "Rest / idle hours",
    "fr_share": "Share of active time in FREQ_WATT",
    "direction_changes": "Direction changes",
    "soh_pct": "SOH at cycle start",
}


@dataclass
class CycleOptions:
    major_share: float = 0.25
    soc_tolerance_pct: float = 5.0
    deadband_frac: float = 0.02


def series(engine: Engine, unit: dict, date_from=None, date_to=None) -> pd.DataFrame:
    sid = unit.get("battery_system_id")
    with engine.connect() as conn:
        df = pd.read_sql(text(_SERIES_SQL), conn, params={"pcs": unit["pcs_id"], "sid": sid or -1,
                                                         "date_from": date_from, "date_to": date_to})
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Kolkata")  # plant time
    return df


def _counter(window: pd.DataFrame, col: str) -> Optional[float]:
    """Energy counted in the window: the sum of the counter's positive steps (resets count as 0)."""
    v = window[col]
    if v.notna().sum() < 2:
        return None
    return float(v.ffill().diff().clip(lower=0).fillna(0).sum())


def extract(df: pd.DataFrame, unit: dict, opts: CycleOptions) -> pd.DataFrame:
    """One row per cycle of a unit's series (see the module docstring)."""
    if df.empty:
        return pd.DataFrame()
    rated = float(unit["rated_power_kw"])
    df = df.sort_values("ts").reset_index(drop=True)
    step_h = df["ts"].diff().dt.total_seconds().median() / 3600 if len(df) > 1 else 5 / 60
    p = df["ac_active_power_kw"].fillna(0.0)
    sign = np.where(p > opts.deadband_frac * rated, 1, np.where(p < -opts.deadband_frac * rated, -1, 0))
    df["dir"] = sign
    df["e_kwh"] = p.abs() * step_h

    # phases: runs of the same direction, ignoring the standby rows between them
    active = df[df["dir"] != 0]
    if active.empty:
        return pd.DataFrame()
    run_id = (active["dir"] != active["dir"].shift()).cumsum()
    phases = active.groupby(run_id).agg(dir=("dir", "first"), start=("ts", "first"), end=("ts", "last"),
                                        energy=("e_kwh", "sum")).reset_index(drop=True)
    charges = phases[phases["dir"] > 0]
    discharges = phases[phases["dir"] < 0]
    if charges.empty or discharges.empty:
        return pd.DataFrame()
    threshold = opts.major_share * float(charges["energy"].quantile(0.9))
    dis_threshold = opts.major_share * float(discharges["energy"].quantile(0.9))
    starts = list(charges.loc[charges["energy"] >= threshold, "start"])

    rows = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else None
        w = df[(df["ts"] >= start) & ((df["ts"] < end) if end is not None else True)]
        ph = phases[(phases["start"] >= start) & ((phases["start"] < end) if end is not None else True)]
        if ph[ph["dir"] < 0]["energy"].sum() < dis_threshold:
            continue  # no real discharge (e.g. the data ends after charging)
        boundary = df[df["ts"] == end] if end is not None else w.tail(1)
        rows.append(_cycle_row(w, boundary, ph, unit, step_h, end is not None))
    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # kWh per SOC % from the charge phases (battery terminals), then the SOC closure correction
    per_pct = (out["e_dc_in"] / out["soc_rise_pct"]).replace([np.inf, -np.inf], np.nan)
    kwh_per_pct = float(per_pct[(out["soc_rise_pct"] > 10)].median()) if (out["soc_rise_pct"] > 10).any() else np.nan
    out["kwh_per_pct"] = kwh_per_pct
    out["closed"] = out["delta_soc_pct"].abs() <= opts.soc_tolerance_pct
    stored = (out["delta_soc_pct"] * kwh_per_pct).fillna(0.0)  # DC kWh left in the battery at the end
    out["e_dc_out_adj"] = out["e_dc_out"] + stored
    eta_d = (out["e_ac_out"] / out["e_dc_out"]).replace([np.inf, -np.inf], np.nan)
    out["e_ac_out_adj"] = out["e_ac_out"] + stored * eta_d.fillna(1.0)
    poi_ratio = (out["e_poi_out"] / out["e_dc_out"]).replace([np.inf, -np.inf], np.nan)
    out["e_poi_out_adj"] = out["e_poi_out"] + stored * poi_ratio.fillna(1.0)
    out["rte_dc_pct"] = 100 * out["e_dc_out_adj"] / out["e_dc_in"]
    out["rte_ac_pct"] = 100 * out["e_ac_out_adj"] / out["e_ac_in"]
    out["rte_sys_pct"] = 100 * out["e_poi_out_adj"] / out["e_poi_in"]
    out["rte_dc_raw_pct"] = 100 * out["e_dc_out"] / out["e_dc_in"]
    out["rte_ac_raw_pct"] = 100 * out["e_ac_out"] / out["e_ac_in"]
    out["rte_sys_raw_pct"] = 100 * out["e_poi_out"] / out["e_poi_in"]
    out["eta_chg_meas_pct"] = 100 * out["e_dc_in"] / out["e_ac_in"]
    out["eta_dis_meas_pct"] = 100 * out["e_ac_out"] / out["e_dc_out"]
    return out.replace([np.inf, -np.inf], np.nan)


def _cycle_row(w: pd.DataFrame, boundary: pd.DataFrame, ph: pd.DataFrame, unit: dict, step_h: float,
               complete: bool) -> dict:
    rated = float(unit["rated_power_kw"])
    chg, dis = w[w["dir"] > 0], w[w["dir"] < 0]
    act = w[w["dir"] != 0]

    def integ(rows: pd.DataFrame, col: str, sign: int = 0) -> float:
        v = rows[col].fillna(0.0)
        v = v.clip(lower=0) if sign > 0 else (-v).clip(lower=0) if sign < 0 else v
        return float(v.sum() * step_h)

    e_dc_in = _counter(w, "cum_charge_kwh") or integ(w, "dc_batt_kw", +1)
    e_dc_out = _counter(w, "cum_discharge_kwh") or integ(w, "dc_batt_kw", -1)
    e_ac_in = _counter(w, "ac_energy_import_kwh") or integ(w, "ac_active_power_kw", +1)
    e_ac_out = _counter(w, "ac_energy_export_kwh") or integ(w, "ac_active_power_kw", -1)
    e_poi_in, e_poi_out = _counter(w, "poi_import_kwh"), _counter(w, "poi_export_kwh")
    soc = w["soc_pct"]
    soc_start = float(soc.dropna().iloc[0]) if soc.notna().any() else np.nan
    end_soc = boundary["soc_pct"].dropna()
    soc_end = float(end_soc.iloc[0]) if len(end_soc) else (float(soc.dropna().iloc[-1]) if soc.notna().any() else np.nan)
    first_dis = dis["ts"].min() if len(dis) else w["ts"].max()
    soc_peak = float(w.loc[w["ts"] <= first_dis, "soc_pct"].max()) if soc.notna().any() else np.nan

    def wavg(rows: pd.DataFrame) -> float:
        e = rows["e_kwh"].sum()
        return float((rows["ac_active_power_kw"].abs() * rows["e_kwh"]).sum() / e / rated) if e > 0 else np.nan

    gs = act["grid_service"].fillna("NONE")
    period_h = (len(w)) * step_h
    return {
        "pcs_id": int(unit["pcs_id"]), "battery_system_id": unit.get("battery_system_id"),
        "start_ts": w["ts"].iloc[0], "end_ts": w["ts"].iloc[-1] + pd.Timedelta(hours=step_h), "complete": complete,
        "e_dc_in": e_dc_in, "e_dc_out": e_dc_out, "e_ac_in": e_ac_in, "e_ac_out": e_ac_out,
        "e_poi_in": e_poi_in if e_poi_in is not None else np.nan,
        "e_poi_out": e_poi_out if e_poi_out is not None else np.nan,
        "e_aux": integ(w, "aux_load_kw"), "e_hvac": integ(w, "hvac_power_kw"),
        "soc_start_pct": soc_start, "soc_end_pct": soc_end, "delta_soc_pct": soc_end - soc_start,
        "soc_rise_pct": soc_peak - soc_start,
        "soc_min_pct": float(soc.min()), "soc_max_pct": float(soc.max()),
        "depth_pct": float(soc.max() - soc.min()),
        "charge_load_frac": wavg(chg), "discharge_load_frac": wavg(dis),
        "charge_hours": len(chg) * step_h, "discharge_hours": len(dis) * step_h, "period_hours": period_h,
        "rest_hours": period_h - (len(chg) + len(dis)) * step_h,
        "cell_temp_avg_c": float(act["cell_temp_avg_c"].mean()), "ambient_temp_c": float(w["ambient_temp_c"].mean()),
        "fr_share": float((gs == "FREQ_WATT").mean()) if len(gs) else 0.0,
        "vv_share": float((gs == "VOLT_VAR").mean()) if len(gs) else 0.0,
        "direction_changes": int(max(0, len(ph) - 1)),
        "soh_pct": float(w["soh_pct"].dropna().iloc[0]) if w["soh_pct"].notna().any() else np.nan,
        "aux_kw_avg": float(w["aux_load_kw"].mean()), "hvac_kw_avg": float(w["hvac_power_kw"].mean()),
    }


def composed(cycles: pd.DataFrame, eta_chg_pred: pd.Series, eta_dis_pred: pd.Series) -> pd.DataFrame:
    """Predicted AC / system RTE of each cycle from its measured DC RTE and the PCS model's energy-weighted
    conversion efficiencies over the cycle's own readings (eta series indexed like `cycles`)."""
    out = cycles.copy()
    out["eta_chg_pred_pct"] = eta_chg_pred
    out["eta_dis_pred_pct"] = eta_dis_pred
    ac_in = out["e_dc_in"] / (out["eta_chg_pred_pct"] / 100)
    ac_out = out["e_dc_out_adj"] * (out["eta_dis_pred_pct"] / 100)
    out["rte_ac_comp_pct"] = 100 * ac_out / ac_in
    # POI: the measured auxiliaries are added to the import and taken from the export
    aux_dis = out["aux_kw_avg"] * out["discharge_hours"]
    out["rte_sys_comp_pct"] = 100 * (ac_out - aux_dis) / (ac_in + out["e_aux"] - aux_dis)
    return out


# ---------------------------------------------------------------- DC round-trip regression


def fit_dc_rte(cycles: pd.DataFrame, alphas=(0.1, 1.0, 10.0, 100.0), seed: int = 42) -> tuple[Optional[dict], list[str]]:
    """Ridge regression of the cycle DC RTE on the cycle features (closed, complete cycles), scored by k-fold
    cross-validation (the cycles are few). Returns the model artifact and warnings."""
    warnings: list[str] = []
    data = cycles[cycles["closed"] & cycles["complete"]].dropna(subset=["rte_dc_pct"])
    feats = [f for f in CYCLE_FEATURES if f in data and data[f].notna().sum() >= max(5, len(data) // 2)
             and data[f].std() > 0]
    if len(data) < 8 or not feats:
        warnings.append(f"Only {len(data)} closed cycles: the DC round-trip model was not fitted")
        return None, warnings
    X = data[feats].fillna(data[feats].median())
    y = data["rte_dc_pct"].to_numpy()
    model = make_pipeline(StandardScaler(), RidgeCV(alphas=alphas))
    k = min(5, len(data))
    pred_cv = cross_val_predict(model, X, y, cv=KFold(k, shuffle=True, random_state=seed))
    model.fit(X, y)
    scaler, ridge = model.steps[0][1], model.steps[1][1]
    coef_std = dict(zip(feats, (float(c) for c in ridge.coef_)))
    return {
        "model": model, "features": feats, "medians": X.median().to_dict(),
        "ranges": {f: {"min": float(X[f].min()), "max": float(X[f].max())} for f in feats},
        "alpha": float(ridge.alpha_), "coef_std": coef_std,
        "coef_raw": {f: float(c / s) for f, c, s in zip(feats, ridge.coef_, scaler.scale_)},
        "intercept": float(ridge.intercept_ - np.sum(ridge.coef_ * scaler.mean_ / scaler.scale_)),
        "scores_cv": regression_scores(y, pred_cv), "folds": k, "n": int(len(data)),
        "cv_pred": dict(zip(data.index, (float(v) for v in pred_cv))),
    }, warnings


def predict_dc_rte(art: dict, values: dict) -> float:
    row = pd.DataFrame([{f: values.get(f, art["medians"][f]) for f in art["features"]}])
    row = row.fillna(pd.Series(art["medians"]))
    return float(art["model"].predict(row[art["features"]])[0])
