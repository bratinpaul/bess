"""Inference with a run's models: one operating point (η of each model, loss breakdown, SHAP attribution, the
efficiency curve at those conditions) and one charge-discharge cycle (DC / AC / system round-trip)."""
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from usecases.efficiency import cycles as C
from usecases.efficiency import features as F
from usecases.efficiency.models import EfficiencyError, eta_from_loss, loss_from_eta
from usecases.efficiency.schemas import CycleIn, PointIn
from usecases.efficiency.trainer import MODEL_KEYS, model_curves, predict_frame


def _unit(art: dict, pcs_id: int) -> dict:
    info = art["units"].get(pcs_id)
    if info is None:
        trained = ", ".join(str(u) for u in art["units"])
        raise EfficiencyError(f"PCS {pcs_id} is not part of this model (trained on PCS {trained})")
    return info


def profile_at(art: dict, pcs_id: int, direction: str, load_frac: float) -> dict:
    """The unit's typical inputs at a load (its operating profile), else its medians."""
    prof = art.get("profiles", {}).get(pcs_id, {}).get(direction)
    if not prof:
        return dict(art["medians"].get(pcs_id, {}))
    return {f: float(np.interp(load_frac, prof["load"], prof[f])) for f in art["features"]}


def point_frame(art: dict, p: PointIn) -> tuple[pd.DataFrame, dict]:
    """The model row of a point; missing inputs come from the unit's operating profile at that load."""
    info = _unit(art, p.pcs_id)
    rated = info["rated_power_kw"]
    load = p.p_kw / rated
    typical = profile_at(art, p.pcs_id, p.direction, load)
    v_dc_ref = info.get("v_dc_ref") or 1.0
    raw = {
        "pcs_id": p.pcs_id, "ts": datetime.now(timezone.utc), "grid_service": p.grid_service,
        "ac_active_power_kw": p.p_kw if p.direction == "charge" else -p.p_kw,
        "ac_apparent_power_kva": p.p_kw / p.power_factor, "power_factor": p.power_factor,
        "ac_reactive_power_kvar": p.p_kw * np.tan(np.arccos(p.power_factor)),
        "ac_frequency_hz": p.ac_frequency_hz or (info.get("nominal_hz") or 50.0) + typical.get("freq_dev_hz", 0.0),
        "ac_voltage_v": p.ac_voltage_v or (info.get("rated_ac_voltage_v") or 1.0) * typical.get("v_ac_pu", 1.0),
        "dc_voltage_v": p.dc_voltage_v or v_dc_ref * typical.get("v_dc_pu", 1.0),
    }
    used = {}
    for c in ("igbt_temp_c", "heatsink_temp_c", "inlet_coolant_temp_c", "ambient_temp_c"):
        v = getattr(p, c)
        raw[c] = v if v is not None else typical.get(c)
        used[c] = raw[c]
    used.update(dc_voltage_v=raw["dc_voltage_v"], ac_voltage_v=raw["ac_voltage_v"], ac_frequency_hz=raw["ac_frequency_hz"])
    units = pd.DataFrame([{"pcs_id": p.pcs_id, "rated_power_kw": rated, "rated_kva": info.get("rated_kva") or rated,
                           "rated_ac_voltage_v": info.get("rated_ac_voltage_v") or 1.0,
                           "nominal_hz": info.get("nominal_hz") or 50.0, "v_dc_ref": v_dc_ref,
                           "commissioned_on": info.get("commissioned_on")}])
    X = F.derive(pd.DataFrame([raw]), units)
    if p.age_years is not None:
        X["age_years"] = p.age_years
    for f in art["features"]:
        if X[f].isna().any():
            X[f] = typical.get(f, art["medians"].get(p.pcs_id, {}).get(f, 0.0))
    used["age_years"] = float(X["age_years"].iloc[0])
    return X, used


def range_warnings(art: dict, X: pd.DataFrame) -> list[str]:
    out = []
    load = float(X["load_frac"].iloc[0])
    if load < art["min_load_frac"]:
        out.append(f"Load {load * 100:.1f} % is below the {art['min_load_frac'] * 100:g} % light-load cut of the training "
                   "readings: the constant losses dominate here and the models extrapolate (the grey-box by physics).")
    for f, r in art["ranges"].items():
        v = float(X[f].iloc[0])
        if f in ("is_charge", "gs_freq_watt", "gs_volt_var"):
            continue
        span = r["max"] - r["min"]
        if v < r["min"] - 0.05 * span or v > r["max"] + 0.05 * span:
            out.append(f"{F.FEATURES[f]['label']} = {v:.3g} is outside the training range "
                       f"({r['min']:.3g} – {r['max']:.3g}): the grey-box extrapolates, the GAM and the trees hold flat")
    return out


def predict_point(art: dict, p: PointIn) -> dict:
    X, used = point_frame(art, p)
    info = art["units"][p.pcs_id]
    rated = info["rated_power_kw"]
    preds = predict_frame(art, X)
    load, chg = X["load_frac"].to_numpy(), X["is_charge"].to_numpy()
    models = {}
    for k in MODEL_KEYS:
        eta = float(preds[k][0])
        loss_kw = float(loss_from_eta(load, np.array([eta]), chg)[0] * rated)
        p_in = p.p_kw if p.direction == "charge" else p.p_kw + loss_kw
        models[k] = {"eta_pct": eta, "loss_kw": loss_kw, "p_in_kw": p_in, "p_out_kw": p_in - loss_kw}

    # loss breakdown: grey-box terms + the residual's share (hybrid - grey-box), kW
    parts = {k: float(v[0] * rated) for k, v in art["greybox"].breakdown_pu(X).items()}
    gb_loss = models["greybox"]["loss_kw"]
    breakdown = {**parts, "residual": models["hybrid"]["loss_kw"] - gb_loss}
    if sum(parts.values()) < 0:  # the grey-box clips negative totals to 0
        breakdown = {"constant": 0.0, "conduction": 0.0, "ohmic": 0.0, "residual": models["hybrid"]["loss_kw"]}

    # SHAP on the residual: percentage points of η, and ≈ kW of loss (d loss ≈ -dη · P)
    sv, base = art["booster"].shap(X)
    shap = sorted(({"feature": f, "label": F.FEATURES[f]["label"] if f in F.FEATURES else "PCS unit",
                    "value": float(X[f].iloc[0]), "pp": float(sv[0, j]), "kw": float(-sv[0, j] / 100 * p.p_kw)}
                   for j, f in enumerate(art["booster"].features)), key=lambda r: -abs(r["pp"]))
    conditions = {f: float(X[f].iloc[0]) for f in art["features"] if f not in ("load_frac", "is_charge")}
    return {
        "pcs_id": p.pcs_id, "direction": p.direction, "load_frac": float(load[0]), "s_frac": float(X["s_frac"].iloc[0]),
        "models": models, "breakdown_kw": breakdown, "shap": shap, "shap_base_pp": float(base[0]),
        "inputs_used": used, "curves": model_curves(art, p.pcs_id, conditions),
        "warnings": range_warnings(art, X),
    }


# ---------------------------------------------------------------- cycle


def _eta_at(art: dict, pcs_id: int, direction: str, p_kw: float, pf: float, gs: str) -> float:
    X, _ = point_frame(art, PointIn(pcs_id=pcs_id, direction=direction, p_kw=p_kw, power_factor=pf, grid_service=gs))
    return float(predict_frame(art, X)["hybrid"][0])


def predict_cycle(art: dict, c: CycleIn) -> dict:
    """DC / AC / system round-trip of a cycle: DC RTE from the cycle regression (or as entered), the PCS
    conversion at the charge and discharge power from the hybrid model, the auxiliaries over the period."""
    info = _unit(art, c.pcs_id)
    rated = info["rated_power_kw"]
    if c.soc_max_pct <= c.soc_min_pct:
        raise EfficiencyError("SOC max must be above SOC min")
    unit_rte = art.get("rte_units", {}).get(str(c.pcs_id), {})
    kwh_per_pct = c.kwh_per_pct or unit_rte.get("kwh_per_pct")
    if not kwh_per_pct:
        rated_mwh = info.get("rated_energy_mwh")
        if not rated_mwh:
            raise EfficiencyError("Enter the kWh per SOC % (the unit has no cycles and no rated energy)")
        kwh_per_pct = rated_mwh * 10.0
    aux_kw = c.aux_kw if c.aux_kw is not None else (unit_rte.get("aux_kw_avg") or 0.0)
    depth = c.soc_max_pct - c.soc_min_pct
    e_dc_in = depth * kwh_per_pct

    eta_c = _eta_at(art, c.pcs_id, "charge", c.charge_kw, c.power_factor, c.grid_service)
    eta_d = _eta_at(art, c.pcs_id, "discharge", c.discharge_kw, c.power_factor, c.grid_service)
    e_ac_in = e_dc_in / (eta_c / 100)
    t_c = e_ac_in / c.charge_kw

    warnings: list[str] = []
    dc_source = "entered"
    dc_rte = c.dc_rte_pct
    dc_model = art.get("dc_rte")
    if dc_rte is None:
        if dc_model:
            dc_source = "regression"
            # the discharge time depends on the DC RTE: two passes are plenty
            t_d = e_dc_in / c.discharge_kw
            for _ in range(2):
                values = {"charge_load_frac": c.charge_kw / rated, "discharge_load_frac": c.discharge_kw / rated,
                          "depth_pct": depth, "soc_max_pct": c.soc_max_pct, "cell_temp_avg_c": c.cell_temp_avg_c,
                          "rest_hours": max(0.0, c.period_hours - t_c - t_d), "fr_share": c.fr_share,
                          "direction_changes": c.direction_changes, "soh_pct": c.soh_pct}
                dc_rte = C.predict_dc_rte(dc_model, {k: v for k, v in values.items() if v is not None})
                t_d = dc_rte / 100 * e_dc_in * (eta_d / 100) / c.discharge_kw
            for f, r in dc_model["ranges"].items():
                v = values.get(f)
                if v is not None and not (r["min"] - 1e-9 <= v <= r["max"] + 1e-9):
                    warnings.append(f"{C.CYCLE_FEATURES[f]} = {v:.3g} is outside the cycles seen ({r['min']:.3g} – "
                                    f"{r['max']:.3g}): the DC round-trip regression extrapolates linearly")
        else:
            dc_source = "unit median"
            dc_rte = unit_rte.get("rte_dc_median")
            if dc_rte is None:
                raise EfficiencyError("This model has no DC round-trip regression: enter the DC RTE")
    if dc_rte > 100:
        warnings.append(f"The DC round-trip is {dc_rte:.2f} % (> 100 %): the training cycles' BMS counters carry no "
                        "battery losses. Enter a DC RTE (e.g. from the cell datasheet) for a realistic figure.")

    e_dc_out = dc_rte / 100 * e_dc_in
    e_ac_out = e_dc_out * eta_d / 100
    t_d = e_ac_out / c.discharge_kw
    if t_c + t_d > c.period_hours:
        warnings.append(f"Charging ({t_c:.1f} h) and discharging ({t_d:.1f} h) don't fit in the {c.period_hours:g} h period")
    e_aux = aux_kw * c.period_hours
    aux_dis = aux_kw * t_d
    e_poi_in = e_ac_in + e_aux - aux_dis
    e_poi_out = e_ac_out - aux_dis
    return {
        "pcs_id": c.pcs_id, "kwh_per_pct": kwh_per_pct, "aux_kw": aux_kw, "dc_rte_source": dc_source,
        "eta_charge_pct": eta_c, "eta_discharge_pct": eta_d,
        "hours": {"charge": t_c, "discharge": t_d, "rest": max(0.0, c.period_hours - t_c - t_d), "period": c.period_hours},
        "energy_kwh": {"poi_in": e_poi_in, "ac_in": e_ac_in, "dc_in": e_dc_in, "dc_out": e_dc_out, "ac_out": e_ac_out,
                       "poi_out": e_poi_out, "aux": e_aux, "aux_during_discharge": aux_dis},
        "losses_kwh": {"pcs_charge": e_ac_in - e_dc_in, "battery": e_dc_in - e_dc_out, "pcs_discharge": e_dc_out - e_ac_out,
                       "auxiliaries": e_aux},
        "rte_pct": {"pcs_conversion": eta_c * eta_d / 100, "dc": dc_rte, "ac": 100 * e_ac_out / e_ac_in,
                    "system": 100 * e_poi_out / e_poi_in if e_poi_in > 0 else None},
        "warnings": warnings,
    }


def sample_point(art: dict, latest: Optional[dict], pcs_id: int) -> dict:
    """A reading as the estimator form (measured efficiency included for comparison)."""
    if not latest:
        raise EfficiencyError(f"No active reading of PCS {pcs_id}")
    pf = abs(latest.get("power_factor") or 1.0) or 1.0
    return {"pcs_id": pcs_id, "ts": latest["ts"], "direction": latest["direction"],
            "p_kw": abs(latest["ac_active_power_kw"]), "power_factor": round(min(1.0, pf), 4),
            "dc_voltage_v": latest["dc_voltage_v"], "igbt_temp_c": latest["igbt_temp_c"],
            "heatsink_temp_c": latest["heatsink_temp_c"], "inlet_coolant_temp_c": latest["inlet_coolant_temp_c"],
            "ambient_temp_c": latest["ambient_temp_c"], "ac_voltage_v": latest["ac_voltage_v"],
            "ac_frequency_hz": latest["ac_frequency_hz"], "grid_service": latest.get("grid_service") or "NONE",
            "measured_eta_pct": latest["efficiency_pct"]}


__all__ = ["eta_from_loss", "predict_cycle", "predict_point", "profile_at", "sample_point"]
