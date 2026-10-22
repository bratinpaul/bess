"""The per-interval loss ledger of one battery system: an energy balance along the loss chain.

    POI ──(transformer)── LV bus ──aux tap── PCS AC ──(PCS)── DC bus ──(DC cabling)── terminals ──(cells)── chemistry

Every node power is + toward the battery and - toward the grid, so each stage's loss is the same expression in both
directions - the power on its grid side minus the power on its battery side - and is positive when physical:

  loss_xfmr = (P_poi - aux) - P_ac     metered residual; or the nameplate model core + copper x (S / S_rated)^2
  loss_pcs  = P_ac - P_dc              (cross-checked against efficiency_pct)
  loss_dc   = P_dc - P_term            (PCS DC meter vs BMS; 0 when they are the same reading)
  loss_batt = P_term - P_chem          P_chem = OCV(SOC, T) x cells x I: the I²R + overpotential loss the terminal
                                       meter can't see
  aux       = aux_load_kw = HVAC (hvac_power_kw) + controls (the rest)
  standby   = self-discharge: SOC drift (regression slope) over rest periods, netted per day, x kWh per SOC %
              (recalibration jumps excluded; a day whose SOC rises at rest counts 0)

Identity at every interval: P_poi = P_chem + loss_batt + loss_dc + loss_pcs + loss_xfmr + aux + closure. With the
metered transformer residual the closure is 0 by construction; with the nameplate model it is the metered residual
minus the model (a metering-boundary check). Independent audits: the PCS efficiency_pct cross-check, the cumulative
counters vs the integrated power (per meter, per day), and the cells' stored energy vs SOC x kWh per %.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from usecases.loss.data import SystemMaster, ocv_lookup


@dataclass
class LedgerSettings:
    idle_frac: float = 0.01                  # |P_ac| <= idle_frac x rated kW -> IDLE
    transformer_mode: str = "metered"        # metered | model
    xfmr_kva: Optional[float] = None         # None -> site transformer rating -> PCS rated kVA
    xfmr_core_pct: float = 0.2               # no-load (core) loss, % of rating, whenever energized
    xfmr_cu_pct: float = 1.0                 # load (copper) loss at rated kVA, % of rating
    standby_min_rest_h: float = 1.0          # rest periods shorter than this are ignored for self-discharge
    standby_max_drop_pct_h: float = 0.5      # an SOC step larger than this (%) at rest is a recalibration


@dataclass
class Ledger:
    df: pd.DataFrame                         # one row per interval (see build())
    step_h: float
    cells_series: Optional[int]
    kwh_per_pct: float
    xfmr_kva: float
    xfmr_source: str
    notes: list[str]
    stats: dict


def xfmr_model_kw(s_kva: np.ndarray, rating_kva: float, core_pct: float, cu_pct: float) -> tuple[np.ndarray, np.ndarray]:
    """Nameplate transformer loss: (core, copper) kW at apparent power s_kva."""
    core = np.full(len(s_kva), core_pct / 100 * rating_kva)
    copper = cu_pct / 100 * rating_kva * (np.nan_to_num(s_kva) / rating_kva) ** 2
    return core, copper


def build(raw: pd.DataFrame, m: SystemMaster, ocv: Optional[pd.DataFrame], cfg: LedgerSettings) -> Ledger:
    df = raw.copy()
    notes: list[str] = []
    step_h = float(df["ts"].diff().dt.total_seconds().median() / 3600) if len(df) > 1 else 5 / 60
    rated = m.rated_kw or float(df["p_ac_kw"].abs().max())
    idle_kw = cfg.idle_frac * rated
    df["direction"] = np.where(df["p_ac_kw"] > idle_kw, "CHARGE", np.where(df["p_ac_kw"] < -idle_kw, "DISCHARGE", "IDLE"))
    df["load_frac"] = df["p_ac_kw"].abs() / rated
    df["s_kva"] = df["s_kva"].where(df["s_kva"].notna(), df["p_ac_kw"].abs())

    # --- chemistry node: OCV x cells x current
    ratio = (df["pack_voltage_v"] / df["cell_v_avg_v"]).replace([np.inf, -np.inf], np.nan)
    cells = int(round(float(ratio.median()))) if ratio.notna().any() else (m.series_cells_master or None)
    if cells and m.series_cells_master and cells != m.series_cells_master:
        notes.append(f"Pack ÷ cell voltage gives {cells} cells in series; the master data says {m.series_cells_master} "
                     f"(the telemetry ratio is used)")
    if ocv is not None and cells:
        df["ocv_cell_v"] = ocv_lookup(ocv, df["soc_pct"].to_numpy(), df["cell_temp_avg_c"].to_numpy())
        df["p_chem_kw"] = df["ocv_cell_v"] * cells * df["pack_current_a"] / 1000
        # at rest (no current) the chemistry and terminal powers are both 0
        df["p_chem_kw"] = df["p_chem_kw"].fillna(df["p_term_kw"])
    else:
        df["ocv_cell_v"] = np.nan
        df["p_chem_kw"] = df["p_term_kw"]
        notes.append("No OCV curve for this chemistry: the internal battery loss can't be separated (set to 0)")

    # --- stage losses (kW)
    df["aux_kw"] = df["aux_kw"].fillna(0.0)
    df["hvac_kw"] = df["hvac_kw"].clip(lower=0)
    if df["hvac_kw"].isna().all():
        notes.append("No HVAC telemetry: the auxiliary load is not split into HVAC and controls")
    df["aux_hvac_kw"] = np.minimum(df["hvac_kw"].fillna(0.0), df["aux_kw"])
    df["aux_ctrl_kw"] = df["aux_kw"] - df["aux_hvac_kw"]
    df["loss_batt_kw"] = df["p_term_kw"] - df["p_chem_kw"]
    df["loss_dc_kw"] = df["p_dc_kw"] - df["p_term_kw"]
    df["loss_pcs_kw"] = df["p_ac_kw"] - df["p_dc_kw"]
    df["xfmr_residual_kw"] = (df["p_poi_kw"] - df["aux_kw"]) - df["p_ac_kw"]

    if m.transformer_kva:
        xfmr_kva, xfmr_source = (cfg.xfmr_kva or m.transformer_kva), ("parameter" if cfg.xfmr_kva else
                                                                       f"site transformer {m.transformer_name}")
    else:
        xfmr_kva, xfmr_source = (cfg.xfmr_kva or m.rated_kva), ("parameter" if cfg.xfmr_kva else "PCS rated kVA")
    core, copper = xfmr_model_kw(df["s_kva"].to_numpy(), xfmr_kva, cfg.xfmr_core_pct, cfg.xfmr_cu_pct)
    df["xfmr_core_model_kw"], df["xfmr_cu_model_kw"] = core, copper
    if cfg.transformer_mode == "model":
        df["loss_xfmr_kw"] = core + copper
    else:
        df["loss_xfmr_kw"] = df["xfmr_residual_kw"]
    df["closure_kw"] = df["xfmr_residual_kw"] - df["loss_xfmr_kw"]

    # PCS cross-check: the loss efficiency_pct implies (charge: P_dc = eta x P_ac, discharge: P_ac = eta x P_dc)
    eta = (df["efficiency_pct"] / 100).where(df["efficiency_pct"] > 0)
    implied = np.where(df["direction"] == "CHARGE", df["p_ac_kw"] * (1 - eta),
                       np.where(df["direction"] == "DISCHARGE", -df["p_dc_kw"] * (1 - eta), np.nan))
    df["closure_pcs_kw"] = np.where(np.isfinite(implied), df["loss_pcs_kw"] - implied, np.nan)
    # stage efficiencies in the interval (one way, in the direction of flow)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["eta_pcs"] = np.where(df["direction"] == "CHARGE", df["p_dc_kw"] / df["p_ac_kw"],
                                 np.where(df["direction"] == "DISCHARGE", df["p_ac_kw"] / df["p_dc_kw"], np.nan))
        df["eta_batt"] = np.where(df["direction"] == "CHARGE", df["p_chem_kw"] / df["p_term_kw"],
                                  np.where(df["direction"] == "DISCHARGE", df["p_term_kw"] / df["p_chem_kw"], np.nan))
    df.loc[~np.isfinite(df["eta_pcs"]) | (df["eta_pcs"] <= 0) | (df["eta_pcs"] > 1.2), "eta_pcs"] = np.nan
    df.loc[~np.isfinite(df["eta_batt"]) | (df["eta_batt"] <= 0) | (df["eta_batt"] > 1.2), "eta_batt"] = np.nan

    # --- kWh per SOC % from the charge phases (chemistry energy over the SOC rise)
    kwh_per_pct, phases = _kwh_per_pct(df, step_h)
    if not np.isfinite(kwh_per_pct):
        kwh_per_pct = m.usable_kwh / 100 if m.usable_kwh else np.nan
        notes.append("No long charge phase to measure kWh per SOC %: the usable energy / 100 is used")

    # --- standby (self-discharge) over rest periods
    df["standby_kw"], standby_stats = _standby(df, step_h, kwh_per_pct, cfg)

    negative = int(((df["loss_batt_kw"] < -0.5) & (df["direction"] != "IDLE")).sum())
    if negative:
        notes.append(f"{negative} active intervals have a terminal voltage on the wrong side of the OCV (negative internal "
                     "loss) - an SOC or OCV-curve mismatch")
    stats = {"rows": int(len(df)), "step_min": round(step_h * 60, 2), "idle_kw": idle_kw, "rated_kw": rated,
             "charge_phases_used": phases, "negative_internal_intervals": negative,
             "xfmr_residual_abs_mean_kw": float(df["xfmr_residual_kw"].abs().mean()),
             "xfmr_residual_abs_max_kw": float(df["xfmr_residual_kw"].abs().max()),
             "pcs_eta_check_abs_mean_kw": float(np.nanmean(np.abs(df["closure_pcs_kw"]))) if df["closure_pcs_kw"].notna().any() else None,
             "dc_meter_abs_mean_kw": float(df["loss_dc_kw"].abs().mean()), **standby_stats}
    return Ledger(df=df, step_h=step_h, cells_series=cells, kwh_per_pct=float(kwh_per_pct), xfmr_kva=float(xfmr_kva),
                  xfmr_source=xfmr_source, notes=notes, stats=stats)


def _runs(mask: pd.Series) -> pd.Series:
    return (mask != mask.shift()).cumsum()


def _kwh_per_pct(df: pd.DataFrame, step_h: float) -> tuple[float, int]:
    charging = df["direction"] == "CHARGE"
    per = []
    for _, g in df[charging].groupby(_runs(charging)[charging]):
        rise = float(g["soc_pct"].iloc[-1] - g["soc_pct"].iloc[0])
        if rise > 10:
            per.append(float((g["p_chem_kw"] * step_h).sum()) / rise)
    return (float(np.median(per)) if per else float("nan")), len(per)


def _standby(df: pd.DataFrame, step_h: float, kwh_per_pct: float, cfg: LedgerSettings) -> tuple[np.ndarray, dict]:
    """Self-discharge from the SOC drift at rest. Per rest period (long enough, no recalibration jump) the drift is the
    regression slope of SOC over the period (endpoints alone are too noisy); the drifts are netted per plant day and a
    day's net drop (never a rise) is spread over its rest intervals."""
    rest = (df["direction"] == "IDLE") & (df["pack_current_a"].abs().fillna(0) < 1.0)
    out = np.zeros(len(df))
    used = recal = 0
    hours = 0.0
    by_day: dict = {}
    run_ids = _runs(rest)
    for _, g in df[rest].groupby(run_ids[rest]):
        h = len(g) * step_h
        soc = g["soc_pct"]
        if h < cfg.standby_min_rest_h or soc.notna().sum() < 3:
            continue
        step = soc.diff().abs().max()
        if step > cfg.standby_max_drop_pct_h:  # a recalibration jump, not self-discharge
            recal += 1
            continue
        t = (g["ts"] - g["ts"].iloc[0]).dt.total_seconds().to_numpy() / 3600
        ok = soc.notna().to_numpy()
        slope = float(np.polyfit(t[ok], soc.to_numpy()[ok], 1)[0])
        used += 1
        hours += h
        for d, gd in g.groupby(g["ts"].dt.date):
            e = by_day.setdefault(d, {"drop_pct": 0.0, "idx": []})
            e["drop_pct"] += -slope * len(gd) * step_h
            e["idx"].extend(gd.index.to_list())
    net = 0.0
    rise_days = 0
    for e in by_day.values():
        net += e["drop_pct"]
        if e["drop_pct"] <= 0:
            rise_days += 1
            continue
        out[np.array(e["idx"])] = e["drop_pct"] * kwh_per_pct / (len(e["idx"]) * step_h)
    return out, {"standby_rest_periods": used, "standby_rest_hours": round(hours, 1),
                 "standby_recalibrations_excluded": recal, "standby_days_with_soc_rise": rise_days,
                 "standby_net_drift_pct": round(net, 3)}
