"""Roll the per-interval ledger up into the benchmark scorecard (per plant day and for the whole window).

Round trip with the storage correction. Over a window the cells end with stored = Σ P_chem·Δt - standby kWh more
(or less) than they started with. That energy would come back out through the discharge path, so at each node k
    RTE_k = (E_out_k + stored · E_out_k / E_out_chem) / E_in_k
Nodes: term (battery terminals), dc (PCS DC bus), ac (PCS AC), poi_x (POI net of the auxiliary tap), poi (plant);
the POI nodes are PCS AC + transformer loss (+ aux), i.e. the POI meter when the transformer is the metered residual.
The factor chain telescopes exactly:
    RTE_plant = η_batt · η_DC · η_PCS · η_xfmr · η_aux
    η_batt = RTE_term,  η_DC = RTE_dc / RTE_term,  η_PCS = RTE_ac / RTE_dc,  η_xfmr = RTE_poi_x / RTE_ac,
    η_aux  = RTE_plant / RTE_poi_x
and the gap 1 - RTE_plant is attributed to the stages in proportion to ln η_k (shares add up to the gap exactly;
the battery share is split into internal and standby by their kWh).

Expected chain: η_k,exp = η_k · (1 - L_k,exp / T_k) / (1 - L_k / T_k) with T_k the throughput at the stage's grid-side
node, RTE_exp = Π η_k,exp and the performance ratio PR = RTE / RTE_exp (normal ageing is in the benchmark through the
battery's resistance-growth term). Guarantee gap = guaranteed RTE - actual RTE on the contract basis.

Control charts per stage on the daily excess % ((actual - expected) / expected), standardized on the baseline days:
EWMA (λ, L·σ limits) and a tabular CUSUM (k, h); alarms are one-sided (excess loss above the
benchmark) and days without a round trip are left off the charts.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

STAGES = ["batt", "dc", "pcs", "xfmr", "aux", "standby"]
STAGE_LABELS = {"batt": "Battery internal", "dc": "DC cabling", "pcs": "PCS conversion", "xfmr": "Transformer",
                "aux": "Auxiliaries", "standby": "Standby / self-discharge"}
# stages benchmarked (with an expected model); standby is charted but advisory - measured from the SOC drift at rest it
# sits below the SOC measurement noise, so it never raises an alarm
BENCH = ["batt", "pcs", "xfmr", "aux", "standby"]
ADVISORY = {"standby"}
BASIS_NODE = {"dc": "term", "ac": "ac", "poi_excl_aux": "poi_x", "plant": "poi"}


@dataclass
class ScoreSettings:
    guarantee_rte_pct: Optional[float] = None    # None -> battery_opt_param.rte_ac, else 85
    guarantee_basis: str = "poi_excl_aux"         # dc | ac | poi_excl_aux | plant
    min_cycle_frac: float = 0.05                  # a day needs this x usable kWh in and out for an RTE
    ewma_lambda: float = 0.2
    ewma_l: float = 3.0
    cusum_k: float = 0.5
    cusum_h: float = 5.0
    sigma_floor_pct: float = 1.0                  # floor of the baseline σ of the daily excess %
    noisy_sigma_pct: float = 100.0                # baseline σ above this: the stage is charted but never alarms


def _sum_pos(x: pd.Series, step_h: float) -> float:
    return float(x.clip(lower=0).sum() * step_h)


def window(df: pd.DataFrame, step_h: float, usable_kwh: float, rated_kw: float, cfg: ScoreSettings,
           guarantee: float) -> dict:
    """Energy balance, RTE chain, loss shares, expected chain and value for a set of intervals."""
    h = step_h
    # POI nodes from the chain: PCS AC + transformer loss (+ aux). With the metered transformer residual this is the POI
    # meter exactly; with the nameplate model it is the HV-side equivalent (the meter's difference is the closure)
    poi_x = df["p_ac_kw"] + df["loss_xfmr_kw"]
    nodes = {"chem": df["p_chem_kw"], "term": df["p_term_kw"], "dc": df["p_dc_kw"], "ac": df["p_ac_kw"],
             "poi_x": poi_x, "poi": poi_x + df["aux_kw"]}
    e_in = {k: _sum_pos(v, h) for k, v in nodes.items()}
    e_out = {k: _sum_pos(-v, h) for k, v in nodes.items()}
    loss = {"batt": float(df["loss_batt_kw"].sum() * h), "dc": float(df["loss_dc_kw"].sum() * h),
            "pcs": float(df["loss_pcs_kw"].sum() * h), "xfmr": float(df["loss_xfmr_kw"].sum() * h),
            "aux": float(df["aux_kw"].sum() * h), "standby": float(df["standby_kw"].sum() * h)}
    aux_split = {"hvac": float(df["aux_hvac_kw"].sum() * h), "controls": float(df["aux_ctrl_kw"].sum() * h)}
    exp = {"batt": float(df["exp_batt_kw"].sum() * h), "dc": 0.0, "pcs": float(df["exp_pcs_kw"].sum() * h),
           "xfmr": float(df["exp_xfmr_kw"].sum() * h), "aux": float(df["exp_aux_kw"].sum() * h),
           "standby": float(df["exp_standby_kw"].sum() * h)}
    stored = float(df["p_chem_kw"].sum() * h) - loss["standby"]
    closure = float(df["closure_kw"].sum() * h)
    throughput_ac = e_in["ac"] + e_out["ac"]
    hours = len(df) * h
    out = {"intervals": int(len(df)), "hours": hours, "e_in": e_in, "e_out": e_out, "loss": loss, "aux_split": aux_split,
           "expected": exp, "stored_kwh": stored, "closure_kwh": closure,
           "closure_pct_of_throughput": 100 * closure / throughput_ac if throughput_ac else None,
           "throughput_kwh": throughput_ac,
           "utilization_pct": 100 * (throughput_ac / 2) / (rated_kw * hours) if rated_kw and hours else None,
           "total_loss_kwh": float(sum(loss.values())),
           "aux_pct_of_throughput": 100 * loss["aux"] / throughput_ac if throughput_ac else None,
           "fixed_kwh": float(df["fixed_kw"].sum() * h), "variable_kwh": float(df["variable_kw"].sum() * h),
           "closure_pcs_kwh": float(np.nansum(df["closure_pcs_kw"]) * h),
           "cycles": e_out["term"] / usable_kwh if usable_kwh else None}

    # value: every loss kWh and every excess kWh at the interval's price
    price = df["price_mwh"].fillna(df["price_mwh"].mean() if df["price_mwh"].notna().any() else 0.0)
    tot_kw = (df[["loss_batt_kw", "loss_dc_kw", "loss_pcs_kw", "loss_xfmr_kw"]].sum(axis=1) + df["aux_kw"] + df["standby_kw"])
    out["avg_price_mwh"] = float(price.mean()) if len(price) else None
    out["loss_usd"] = float((tot_kw * h * price / 1000).sum())
    excess_usd = {}
    for k, col, ecol in (("batt", "loss_batt_kw", "exp_batt_kw"), ("pcs", "loss_pcs_kw", "exp_pcs_kw"),
                         ("xfmr", "loss_xfmr_kw", "exp_xfmr_kw"), ("aux", "aux_kw", "exp_aux_kw"),
                         ("standby", "standby_kw", "exp_standby_kw")):
        excess_usd[k] = float(((df[col] - df[ecol]) * h * price / 1000).sum())
    out["excess_kwh"] = {k: loss[k] - exp[k] for k in BENCH}
    out["excess_usd_by_stage"] = excess_usd
    out["excess_usd"] = float(sum(max(v, 0.0) for v in excess_usd.values()))
    out["excess_kwh_total"] = float(sum(max(v, 0.0) for v in out["excess_kwh"].values()))

    # round trip at every node (storage-corrected) and the factor chain
    ok = usable_kwh and e_in["chem"] >= cfg.min_cycle_frac * usable_kwh and e_out["chem"] >= cfg.min_cycle_frac * usable_kwh
    rte = {}
    if ok:
        for k in ("term", "dc", "ac", "poi_x", "poi"):
            r = e_out[k] / e_out["chem"] if e_out["chem"] else 0.0
            rte[k] = (e_out[k] + stored * r) / e_in[k] if e_in[k] else None
    out["rte"] = rte
    out["has_cycle"] = bool(ok and all(v is not None and v > 0 for v in rte.values()))
    if not out["has_cycle"]:
        out.update(factors={}, shares={}, rte_expected=None, performance_ratio=None, guarantee_gap_pts=None,
                   factors_expected={})
        return out
    f = {"batt": rte["term"], "dc": rte["dc"] / rte["term"], "pcs": rte["ac"] / rte["dc"],
         "xfmr": rte["poi_x"] / rte["ac"], "aux": rte["poi"] / rte["poi_x"]}
    out["factors"] = f
    gap = 1 - rte["poi"]
    ln_total = float(np.log(rte["poi"])) if rte["poi"] > 0 else None
    shares = {}
    if ln_total and abs(ln_total) > 1e-12:
        for k, v in f.items():
            shares[k] = gap * float(np.log(v)) / ln_total
        b_tot = max(loss["batt"], 0) + max(loss["standby"], 0)
        b = shares.pop("batt")
        shares["batt"] = b * (max(loss["batt"], 0) / b_tot) if b_tot else b
        shares["standby"] = b * (max(loss["standby"], 0) / b_tot) if b_tot else 0.0
    out["shares"] = shares  # fractions of the input that each stage loses; sum = 1 - RTE_plant

    # expected chain
    t = {"batt": e_in["term"] + e_out["term"], "dc": e_in["dc"] + e_out["dc"], "pcs": throughput_ac,
         "xfmr": e_in["poi_x"] + e_out["poi_x"], "aux": e_in["poi_x"] + e_out["poi_x"]}
    l_act = {"batt": loss["batt"] + loss["standby"], "dc": loss["dc"], "pcs": loss["pcs"], "xfmr": loss["xfmr"],
             "aux": loss["aux"]}
    l_exp = {"batt": exp["batt"] + exp["standby"], "dc": loss["dc"], "pcs": exp["pcs"], "xfmr": exp["xfmr"],
             "aux": exp["aux"]}
    fe = {}
    for k in f:
        if t[k] > 0 and (1 - l_act[k] / t[k]) > 0:
            fe[k] = f[k] * (1 - l_exp[k] / t[k]) / (1 - l_act[k] / t[k])
        else:
            fe[k] = f[k]
    out["factors_expected"] = fe
    r_exp = float(np.prod(list(fe.values())))
    out["rte_expected"] = r_exp
    out["performance_ratio"] = rte["poi"] / r_exp if r_exp else None
    node = BASIS_NODE.get(cfg.guarantee_basis, "poi_x")
    actual_basis = rte.get(node)
    out["guarantee_basis_rte"] = actual_basis
    out["guarantee_gap_pts"] = 100 * (guarantee - actual_basis) if actual_basis is not None else None
    return out


def counter_closure(day: pd.DataFrame, h: float) -> dict:
    """Cumulative counters vs integrated power per meter (kWh, counter - integral)."""
    def delta(col):
        v = day[col]
        return float(v.ffill().diff().clip(lower=0).fillna(0).sum()) if v.notna().sum() >= 2 else None
    pairs = {"bms_charge": ("cum_charge_kwh", day["p_term_kw"]), "bms_discharge": ("cum_discharge_kwh", -day["p_term_kw"]),
             "pcs_import": ("ac_import_kwh", day["p_ac_kw"]), "pcs_export": ("ac_export_kwh", -day["p_ac_kw"]),
             "poi_import": ("poi_import_kwh", day["p_poi_kw"]), "poi_export": ("poi_export_kwh", -day["p_poi_kw"])}
    out = {}
    for k, (col, p) in pairs.items():
        c = delta(col)
        integ = float(p.clip(lower=0).sum() * h)
        out[k] = {"counter_kwh": c, "integral_kwh": integ, "diff_kwh": (c - integ) if c is not None else None}
    return out


def daily(df: pd.DataFrame, step_h: float, usable_kwh: float, rated_kw: float, kwh_per_pct: float, cfg: ScoreSettings,
          guarantee: float, models: dict, rated_kva: float) -> list[dict]:
    rows = []
    days = df["ts"].dt.date
    for d, g in df.groupby(days):
        w = window(g, step_h, usable_kwh, rated_kw, cfg, guarantee)
        soc0, soc1 = g["soc_pct"].dropna().iloc[[0, -1]] if g["soc_pct"].notna().sum() >= 2 else (np.nan, np.nan)
        soc_based = (soc1 - soc0) * kwh_per_pct if np.isfinite(soc0) and np.isfinite(soc1) else None
        w["day"] = d
        w["is_baseline"] = bool(g["is_baseline"].all())
        w["counters"] = counter_closure(g, step_h)
        w["battery_closure"] = {"stored_kwh": w["stored_kwh"], "soc_based_kwh": soc_based,
                                "diff_kwh": (w["stored_kwh"] - soc_based) if soc_based is not None else None}
        w["normalized"] = _normalized(w, models, rated_kva)
        rows.append(w)
    _control_charts(rows, cfg)
    return rows


def _normalized(w: dict, models: dict, rated_kva: float) -> dict:
    """Efficiency at the reference conditions, scaled by the day's actual / expected loss ratio (health, not duty)."""
    out = {}
    ref = models.get("reference", {})
    s = ref.get("load_frac", 0.5)
    pcs = models.get("pcs", {}).get("directions", {})
    if pcs and w["expected"]["pcs"] > 0:
        ratio = w["loss"]["pcs"] / w["expected"]["pcs"]
        etas = []
        for m in pcs.values():
            l_ref = m["a_kw"] + m["b_kw"] * s + m["c_kw"] * s ** 2
            if s * rated_kva > 0:
                etas.append(1 - ratio * l_ref / (s * rated_kva))
        out["pcs_eta_ref_pct"] = 100 * float(np.mean(etas)) if etas else None
        out["pcs_loss_ratio"] = ratio
    if w["expected"]["batt"] > 0:
        out["batt_loss_ratio"] = w["loss"]["batt"] / w["expected"]["batt"]
        r = [m["r_ohm_pack"] for m in models.get("battery", {}).get("directions", {}).values()]
        out["batt_r_ref_ohm"] = float(np.mean(r)) * out["batt_loss_ratio"] if r else None
    if w["expected"]["aux"] > 0:
        out["aux_ratio"] = w["loss"]["aux"] / w["expected"]["aux"]
        out["aux_ref_kw"] = models.get("aux", {}).get("ref_aux_kw", 0) * out["aux_ratio"]
    return out


def _control_charts(rows: list[dict], cfg: ScoreSettings) -> None:
    lam = cfg.ewma_lambda
    for k in BENCH:
        x = []
        for r in rows:
            e = r["expected"][k]
            # days without a round trip (idle / partial days) are off the chart: their excess % says nothing
            x.append(100 * (r["loss"][k] - e) / e if e > 1e-6 and r["has_cycle"] else None)
        base = [v for v, r in zip(x, rows) if v is not None and r["is_baseline"]]
        if len(base) < 2:
            base = [v for v in x if v is not None]
        mu = float(np.mean(base)) if base else 0.0
        sigma = float(np.std(base, ddof=1)) if len(base) > 1 else 0.0
        if sigma < cfg.sigma_floor_pct:  # a degenerate baseline (e.g. always 0): the scatter over all charted days
            every = [v for v in x if v is not None]
            sigma = float(np.std(every, ddof=1)) if len(every) > 1 else 0.0
        sigma = max(sigma, cfg.sigma_floor_pct)
        # a stage whose daily excess scatters by more than its own size (e.g. standby, below the SOC noise) is charted
        # but raises no alarm
        noisy = sigma > cfg.noisy_sigma_pct or k in ADVISORY
        z, cp, cn, t = mu, 0.0, 0.0, 0
        for v, r in zip(x, rows):
            cc = r.setdefault("control", {})
            if v is None:
                cc[k] = {"excess_pct": None}
                continue
            t += 1
            z = lam * v + (1 - lam) * z
            width = cfg.ewma_l * sigma * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * t)))
            u = (v - mu) / sigma
            cp = max(0.0, cp + u - cfg.cusum_k)
            cn = max(0.0, cn - u - cfg.cusum_k)
            # one-sided: only more loss than the benchmark is a fault signature (cusum_neg is kept for the chart)
            ewma_alarm = bool(z > mu + width) and not noisy
            cusum_alarm = bool(cp > cfg.cusum_h) and not noisy
            cc[k] = {"excess_pct": v, "ewma": z, "ucl": mu + width, "lcl": mu - width, "center": mu, "sigma": sigma,
                     "cusum_pos": cp, "cusum_neg": cn, "ewma_alarm": ewma_alarm, "cusum_alarm": cusum_alarm,
                     "status": "noisy" if noisy else ("both" if ewma_alarm and cusum_alarm else
                                                      ("ewma" if ewma_alarm else ("cusum" if cusum_alarm else "ok")))}


def loading_curve(df: pd.DataFrame, rated_kw: float) -> list[dict]:
    """Mean stage loss (kW, actual and expected) and loss % of power per loading bin (active intervals)."""
    a = df[df["direction"] != "IDLE"]
    edges = [0, 0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.2]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = a[(a["load_frac"] > lo) & (a["load_frac"] <= hi)]
        if len(g) < 3:
            continue
        p = g["p_ac_kw"].abs().mean()
        row = {"from_pct": lo * 100, "to_pct": hi * 100, "mid_pct": 100 * float(g["load_frac"].mean()), "n": int(len(g)),
               "p_kw": float(p)}
        for k, col, ecol in (("batt", "loss_batt_kw", "exp_batt_kw"), ("pcs", "loss_pcs_kw", "exp_pcs_kw"),
                             ("xfmr", "loss_xfmr_kw", "exp_xfmr_kw"), ("aux", "aux_kw", "exp_aux_kw")):
            row[k] = float(g[col].mean())
            row[f"exp_{k}"] = float(g[ecol].mean())
        row["fixed_kw"] = float(g["fixed_kw"].mean())
        row["variable_kw"] = float(g["variable_kw"].mean())
        row["loss_pct_of_power"] = 100 * float((row["batt"] + row["pcs"] + row["xfmr"] + row["aux"]) / p) if p else None
        out.append(row)
    return out


def direction_split(df: pd.DataFrame, h: float) -> dict:
    """Loss kWh and % of the stage's throughput by direction (charge / discharge asymmetry)."""
    out = {}
    for d, g in df.groupby("direction"):
        thr = float(g["p_ac_kw"].abs().sum() * h)
        row = {"intervals": int(len(g)), "throughput_kwh": thr}
        for k, col in (("batt", "loss_batt_kw"), ("dc", "loss_dc_kw"), ("pcs", "loss_pcs_kw"), ("xfmr", "loss_xfmr_kw"),
                       ("aux", "aux_kw"), ("standby", "standby_kw")):
            e = float(g[col].sum() * h)
            row[k] = {"kwh": e, "pct_of_throughput": 100 * e / thr if thr else None}
        if d != "IDLE":
            row["eta_pcs_pct"] = 100 * float(np.nanmean(g["eta_pcs"])) if g["eta_pcs"].notna().any() else None
            row["eta_batt_pct"] = 100 * float(np.nanmean(g["eta_batt"])) if g["eta_batt"].notna().any() else None
        out[d] = row
    return out
