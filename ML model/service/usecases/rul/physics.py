"""Empirical fade model (the interpretable backbone), one per chemistry, pooled over the fleet:

    capacity loss    100 - SOH       = c0 + m_b m_u f_T(T) (a sqrt(age_days) + b EFC^z)
    resistance rise  R / R_BOL - 1   = g0 + n_b n_u f_T(T) (ar sqrt(age_days) + br EFC^zr)
    Arrhenius        f_T(T) = exp(Ea / R_gas (1 / T_ref - 1 / T)),   T = mean cell temperature to date (K), T_ref = 25 C

Calendar fade grows with the square root of time, cycle fade with a power of the equivalent full cycles, both faster
when hotter. The fleet-level curve is fitted by bounded least squares; m_b / n_b are per-batch factors (batch effects
dominate aging variance) and m_u / n_u per-unit factors estimated from the unit's own history - snapshots plus RPT
checkpoints (weighted, the calibrated ground truth) - shrunk towards 1 with prior strength kappa, so a unit with little
history follows its batch and one with a long history follows itself. The posterior spread of the unit factor gives the
P10 / P90 bands (the trainer widens them to the errors seen on the training units).

Knee: LFP fade is three-stage - fast early (SEI), linear, then a knee where it accelerates. A smooth sqrt / power curve
cannot bend upwards late, so a fleet-level acceleration factor per SOH band (g = observed / modelled increments of the
units' monthly snapshots in that band) multiplies the projected fade - for capacity and resistance alike, banded by SOH.

RUL: the fade is projected from the unit's current state (anchored at its measured SOH / resistance) at its recent
cycles per day and temperature until SOH reaches the EOL threshold or resistance the EOL multiple of BOL - whichever
comes first (the trigger).
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import least_squares

R_GAS = 8.314
T_REF = 298.15
Z90 = 1.2816
HORIZON_DAYS = 40 * 365
STEP_DAYS = 5


def f_temp(temp_c, ea: float) -> np.ndarray:
    t = np.asarray(temp_c, float) + 273.15
    return np.exp(ea / R_GAS * (1.0 / T_REF - 1.0 / t))


@dataclass
class FadeCurve:
    """offset + f_T (a sqrt(age) + b EFC^z) - for capacity loss (%-points) or resistance rise (fraction of BOL)."""
    offset: float = 0.0
    a: float = 0.0
    b: float = 0.0
    z: float = 1.0
    ea: float = 0.0
    r2: Optional[float] = None
    rmse: Optional[float] = None

    def core(self, age, efc, temp) -> np.ndarray:
        age = np.maximum(np.asarray(age, float), 0.0)
        efc = np.maximum(np.asarray(efc, float), 0.0)
        return f_temp(temp, self.ea) * (self.a * np.sqrt(age) + self.b * efc ** self.z)

    @classmethod
    def fit(cls, y, age, efc, temp, scale, weights, arrhenius: bool, z_bounds=(0.5, 3.0)) -> "FadeCurve":
        """y = offset + scale * core; scale = batch x unit factor (1 on the first pass)."""
        y, age, efc, temp, scale, w = (np.asarray(v, float) for v in (y, age, efc, temp, scale, weights))
        ok = np.isfinite(y) & np.isfinite(age) & np.isfinite(efc) & np.isfinite(temp)
        y, age, efc, temp, scale, w = y[ok], age[ok], efc[ok], temp[ok], scale[ok], np.sqrt(w[ok])
        ea_hi = 80000.0 if arrhenius else 1e-6

        def resid(p):
            c = cls(p[0], np.exp(p[1]), np.exp(p[2]), p[3], p[4])
            return w * (c.offset + scale * c.core(age, efc, temp) - y)

        y_span = max(np.nanmax(y) - np.nanmin(y), 1e-3)
        x0 = [float(np.nanmin(y)), np.log(y_span / max(np.sqrt(age.max()), 1) / 2 + 1e-9),
              np.log(y_span / max(efc.max(), 1) / 2 + 1e-9), 1.0, 20000.0 if arrhenius else 0.0]
        lo = [-np.inf, -30, -30, z_bounds[0], 0.0]
        hi = [np.inf, 10, 10, z_bounds[1], ea_hi]
        x0[3] = float(np.clip(x0[3], *z_bounds))
        x0[4] = float(np.clip(x0[4], 0, ea_hi))
        sol = least_squares(resid, x0, bounds=(lo, hi), loss="soft_l1", f_scale=max(0.05 * y_span, 1e-3)).x
        c = cls(float(sol[0]), float(np.exp(sol[1])), float(np.exp(sol[2])), float(sol[3]), float(sol[4]))
        pred = c.offset + scale * c.core(age, efc, temp)
        c.rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
        c.r2 = float(1 - np.var(y - pred) / max(np.var(y), 1e-12))
        return c

    def to_dict(self) -> dict:
        return {"offset": self.offset, "a": self.a, "b": self.b, "z": self.z, "ea_kj_mol": self.ea / 1000.0,
                "r2": self.r2, "rmse": self.rmse}


def unit_factor(y, offset, core_scaled, weights, kappa: float) -> tuple[float, float]:
    """Shrunk log factor of a unit (and its effective sample size): log m = n / (n + kappa) * log(ratio)."""
    y, core_scaled, w = (np.asarray(v, float) for v in (y, core_scaled, weights))
    ok = np.isfinite(y) & np.isfinite(core_scaled) & (core_scaled > 1e-9)
    if ok.sum() == 0:
        return 0.0, 0.0
    num = np.sum(w[ok] * (y[ok] - offset) * core_scaled[ok])
    den = np.sum(w[ok] * core_scaled[ok] ** 2)
    ratio = num / den if den > 0 else 1.0
    n = float(np.sum(w[ok]))
    return float(n / (n + kappa) * np.log(max(ratio, 0.05))), n


KNEE_EDGES = [95.0, 90.0, 85.0, 80.0, 75.0, 70.0, 65.0]  # SOH band boundaries (bands: >95, 95-90, ..., <65)


def band_labels() -> list[str]:
    e = KNEE_EDGES
    return [f">{e[0]:.0f}"] + [f"{e[i]:.0f}-{e[i + 1]:.0f}" for i in range(len(e) - 1)] + [f"<{e[-1]:.0f}"]


def band_of(soh) -> np.ndarray:
    """Band index of SOH values: band b covers (edge_b, edge_{b-1}]; a value on an edge falls in the lower band."""
    return np.searchsorted(-np.asarray(KNEE_EDGES), -np.asarray(soh, float), side="right")


def _fill_bands(num: np.ndarray, den: np.ndarray, cnt: np.ndarray, min_count: int = 5) -> list[float]:
    """g per band (observed / modelled increments); bands without enough data take the nearest fitted band."""
    g = np.full(len(num), np.nan)
    ok = (cnt >= min_count) & (den > 0)
    g[ok] = np.clip(num[ok] / den[ok], 0.3, 5.0)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return [1.0] * len(num)
    for i in range(len(g)):
        if not np.isfinite(g[i]):
            g[i] = g[idx[np.argmin(np.abs(idx - i))]]
    return [float(v) for v in g]


@dataclass
class ChemistryModel:
    chemistry: str
    soh_eol: float
    res_eol_ratio: Optional[float]
    cap: FadeCurve
    res: Optional[FadeCurve]
    batch_cap: dict = field(default_factory=dict)  # batch -> factor
    batch_res: dict = field(default_factory=dict)
    tau_cap: float = 0.1  # between-unit sd of log factor
    tau_res: float = 0.1
    kappa: float = 6.0
    rpt_weight: float = 3.0
    arrhenius: bool = True
    half_life_days: float = 0.0  # recency weighting of a unit's own history (0 = off)
    knee: bool = True
    knee_cap: list = field(default_factory=list)  # acceleration factor per SOH band (KNEE_EDGES)
    knee_res: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"chemistry": self.chemistry, "soh_eol_pct": self.soh_eol, "resistance_eol_ratio": self.res_eol_ratio,
                "capacity": self.cap.to_dict(), "resistance": self.res.to_dict() if self.res else None,
                "batch_capacity_factor": self.batch_cap, "batch_resistance_factor": self.batch_res,
                "unit_spread_capacity": self.tau_cap, "unit_spread_resistance": self.tau_res, "kappa": self.kappa,
                "rpt_weight": self.rpt_weight, "half_life_days": self.half_life_days,
                "knee_bands": band_labels() if self.knee else [], "knee_capacity": self.knee_cap if self.knee else [],
                "knee_resistance": self.knee_res if self.knee else []}


def _history(rows, rpt, rpt_weight: float):
    """Unit history points: snapshots (weight 1) + RPT checkpoints (weight rpt_weight)."""
    cols = ["age_days", "equiv_full_cycles", "temp_mean", "soh_pct", "r_ratio"]
    h = rows[cols].copy()
    h["w"] = 1.0
    if rpt is not None and len(rpt):
        r = rpt[["age_days", "equiv_full_cycles", "soh_pct", "r_ratio"]].copy()
        r["temp_mean"] = np.interp(r["age_days"], rows["age_days"], rows["temp_mean"]) if len(rows) else np.nan
        r["w"] = rpt_weight
        h = np.concatenate([h[cols + ["w"]].to_numpy(float), r[cols + ["w"]].to_numpy(float)])
        return {c: h[:, i] for i, c in enumerate(cols + ["w"])}
    return {c: h[c].to_numpy(float) for c in cols + ["w"]}


def fit_chemistry(chemistry: str, rows, rpt, eol: dict, arrhenius: bool = True, kappa: float = 6.0,
                  rpt_weight: float = 3.0, half_life_days: float = 0.0, knee: bool = True) -> ChemistryModel:
    """Fleet curve -> batch factors -> refit with batch factors -> unit spread (tau)."""
    soh_eol = float(eol["soh_eol_pct"])
    res_ratio = eol["resistance_eol_pct"] / 100.0 if eol.get("resistance_eol_pct") else None
    pts = {k: [] for k in ("age_days", "equiv_full_cycles", "temp_mean", "soh_pct", "r_ratio", "w", "batch", "unit")}
    for sid, g in rows.groupby("system_id"):
        h = _history(g, rpt[rpt["system_id"] == sid] if rpt is not None else None, rpt_weight)
        for k, v in h.items():
            pts[k].append(v)
        pts["batch"].append(np.full(len(h["w"]), g["batch_lot"].iloc[0], dtype=object))
        pts["unit"].append(np.full(len(h["w"]), sid))
    p = {k: np.concatenate(v) for k, v in pts.items()}
    loss = 100.0 - p["soh_pct"]
    rise = p["r_ratio"] - 1.0
    ones = np.ones(len(loss))
    m = ChemistryModel(chemistry, soh_eol, res_ratio, FadeCurve(), None, kappa=kappa, rpt_weight=rpt_weight,
                       arrhenius=arrhenius, half_life_days=half_life_days, knee=knee)
    for kind, y in (("cap", loss), ("res", rise)):
        if kind == "res" and (res_ratio is None or np.isfinite(y).sum() < 20):
            continue
        curve = FadeCurve.fit(y, p["age_days"], p["equiv_full_cycles"], p["temp_mean"], ones, p["w"], arrhenius)
        core = curve.core(p["age_days"], p["equiv_full_cycles"], p["temp_mean"])
        batch = {}
        for b in np.unique(p["batch"]):
            k = p["batch"] == b
            lf, _ = unit_factor(y[k], curve.offset, core[k], p["w"][k], kappa=0.0)
            batch[str(b)] = float(np.exp(lf))
        scale = np.array([batch[str(b)] for b in p["batch"]])
        curve = FadeCurve.fit(y, p["age_days"], p["equiv_full_cycles"], p["temp_mean"], scale, p["w"], arrhenius)
        core = curve.core(p["age_days"], p["equiv_full_cycles"], p["temp_mean"]) * scale
        logs = []
        for u in np.unique(p["unit"]):
            k = p["unit"] == u
            lf, n = unit_factor(y[k], curve.offset, core[k], p["w"][k], kappa=0.0)
            if n >= 6:
                logs.append(lf)
        tau = float(max(np.std(logs), 0.03)) if len(logs) >= 3 else 0.1
        if kind == "cap":
            m.cap, m.batch_cap, m.tau_cap = curve, batch, tau
        else:
            m.res, m.batch_res, m.tau_res = curve, batch, tau
    n_b = len(KNEE_EDGES) + 1
    m.knee_cap, m.knee_res = [1.0] * n_b, [1.0] * n_b
    if knee:
        m.knee_cap, m.knee_res = _fit_knee(m, rows)
    return m


def _fit_knee(m: ChemistryModel, rows) -> tuple[list, list]:
    """Observed / modelled monthly increments per SOH band, with each unit's own (unshrunk) level factor."""
    n_b = len(KNEE_EDGES) + 1
    acc = {k: (np.zeros(n_b), np.zeros(n_b), np.zeros(n_b)) for k in ("cap", "res")}
    for _, g in rows.groupby("system_id"):
        if len(g) < 3:
            continue
        age, efc, temp = g["age_days"].to_numpy(), g["equiv_full_cycles"].to_numpy(), g["temp_mean"].to_numpy()
        batch = str(g["batch_lot"].iloc[0])
        soh = g["soh_pct"].to_numpy()
        band = band_of((soh[:-1] + soh[1:]) / 2)
        for kind, curve, bmap, y in (("cap", m.cap, m.batch_cap, 100.0 - soh),
                                     ("res", m.res, m.batch_res, g["r_ratio"].to_numpy() - 1.0)):
            if curve is None:
                continue
            core = curve.core(age, efc, temp) * bmap.get(batch, 1.0)
            lf, _ = unit_factor(y, curve.offset, core, np.ones(len(y)), kappa=0.0)
            d_obs, d_mod = np.diff(y), np.exp(lf) * np.diff(core)
            ok = np.isfinite(d_obs) & np.isfinite(d_mod)
            num, den, cnt = acc[kind]
            np.add.at(num, band[ok], d_obs[ok])
            np.add.at(den, band[ok], d_mod[ok])
            np.add.at(cnt, band[ok], 1)
    return _fill_bands(*acc["cap"]), (_fill_bands(*acc["res"]) if m.res is not None else [1.0] * n_b)


def _knee_soh_path(soh_now: float, cum: np.ndarray, g: list) -> np.ndarray:
    """SOH along the projection: within a band SOH falls by g_band x the modelled loss; integrated band by band."""
    path = np.empty_like(cum)
    lowers = KNEE_EDGES + [-np.inf]
    i, cur = 0, soh_now
    for _ in range(len(lowers) + 2):
        b = int(band_of(cur))
        seg = cur - g[b] * (cum[i:] - cum[i])
        hit = np.flatnonzero(seg <= lowers[b]) if np.isfinite(lowers[b]) else np.array([], int)
        if not len(hit) or hit[0] == 0 and seg[0] > lowers[b]:
            path[i:] = seg
            return path
        k = hit[0]
        path[i:i + k] = seg[:k]
        if i + k >= len(cum):
            return path
        cur = min(float(seg[k]), lowers[b] - 1e-9)
        path[i + k] = cur
        i = i + k
    path[i:] = cur - g[int(band_of(cur))] * (cum[i:] - cum[i])
    return path


@dataclass
class UnitState:
    age_days: float
    efc: float
    temp: float          # mean cell temperature going forward
    cpd: float           # EFC per day going forward
    soh: float
    r_ratio: float
    batch: str
    log_m_cap: float = 0.0
    n_cap: float = 0.0
    log_m_res: float = 0.0
    n_res: float = 0.0


def unit_state(model: ChemistryModel, hist_rows, hist_rpt, cpd: Optional[float] = None,
               temp: Optional[float] = None) -> UnitState:
    """The unit's state at its last history point and its shrunk factors from all history up to there."""
    last = hist_rows.iloc[-1]
    batch = str(last["batch_lot"])
    h = _history(hist_rows, hist_rpt, model.rpt_weight)
    if model.half_life_days > 0:  # recent history counts more: a late-life knee lifts the factor
        h["w"] = h["w"] * 0.5 ** ((float(last["age_days"]) - h["age_days"]).clip(min=0) / model.half_life_days)
    s = UnitState(float(last["age_days"]), float(last["equiv_full_cycles"]),
                  float(temp if temp is not None else last["temp_mean"]),
                  float(cpd if cpd is not None else (last["cpd_recent"] if np.isfinite(last["cpd_recent"]) else
                                                     last["usage_cycles_per_day"])),
                  float(last["soh_pct"]), float(last["r_ratio"]), batch)
    core = model.cap.core(h["age_days"], h["equiv_full_cycles"], h["temp_mean"]) * model.batch_cap.get(batch, 1.0)
    s.log_m_cap, s.n_cap = unit_factor(100.0 - h["soh_pct"], model.cap.offset, core, h["w"], model.kappa)
    if model.res is not None:
        core = model.res.core(h["age_days"], h["equiv_full_cycles"], h["temp_mean"]) * model.batch_res.get(batch, 1.0)
        s.log_m_res, s.n_res = unit_factor(h["r_ratio"] - 1.0, model.res.offset, core, h["w"], model.kappa)
    return s


def _spread(tau: float, n: float, kappa: float) -> float:
    return tau * np.sqrt(kappa / (n + kappa)) if n + kappa > 0 else tau


def project(model: ChemistryModel, s: UnitState, horizon_days: int = HORIZON_DAYS, step: int = STEP_DAYS) -> dict:
    """SOH and resistance-ratio paths (P10 / P50 / P90 of the unit factor) and the RUL quantiles in days / cycles."""
    d = np.arange(0, horizon_days + step, step, dtype=float)
    age, efc = s.age_days + d, s.efc + s.cpd * d
    out = {"days": d, "trigger": {}}
    rul = {}
    sd_c = _spread(model.tau_cap, s.n_cap, model.kappa)
    sd_r = _spread(model.tau_res, s.n_res, model.kappa) if model.res else 0.0
    # q = RUL quantile: P10 RUL comes from the fast-fade end (+z)
    for q, z in (("p10", Z90), ("p50", 0.0), ("p90", -Z90)):
        mc = np.exp(s.log_m_cap + z * sd_c) * model.batch_cap.get(s.batch, 1.0)
        cum = mc * (model.cap.core(age, efc, s.temp) - model.cap.core(s.age_days, s.efc, s.temp))
        soh = _knee_soh_path(s.soh, cum, model.knee_cap if model.knee else [1.0] * (len(KNEE_EDGES) + 1))
        out[f"soh_{q}"] = soh
        hit_c = np.flatnonzero(soh <= model.soh_eol)
        t_c = d[hit_c[0]] if len(hit_c) else np.inf
        t_r = np.inf
        if model.res is not None and model.res_eol_ratio:
            mr = np.exp(s.log_m_res + z * sd_r) * model.batch_res.get(s.batch, 1.0)
            dres = mr * np.diff(model.res.core(age, efc, s.temp))
            if model.knee:  # resistance accelerates with the same SOH bands
                dres = dres * np.asarray(model.knee_res)[band_of(soh[:-1])]
            rr = s.r_ratio + np.concatenate([[0.0], np.cumsum(dres)])
            out[f"r_{q}"] = rr
            hit_r = np.flatnonzero(rr >= model.res_eol_ratio)
            t_r = d[hit_r[0]] if len(hit_r) else np.inf
        t = min(t_c, t_r)
        if s.soh <= model.soh_eol or (model.res_eol_ratio and s.r_ratio >= model.res_eol_ratio):
            t = 0.0
        rul[q] = t
        out["trigger"][q] = "capacity" if t_c <= t_r else "resistance"
    beyond = not np.isfinite(rul["p50"])
    days = {q: (float(v) if np.isfinite(v) else float(horizon_days)) for q, v in rul.items()}
    out.update({"rul_days": days, "rul_cycles": {q: v * s.cpd for q, v in days.items()}, "beyond": beyond,
                "factor_capacity": float(np.exp(s.log_m_cap)), "factor_resistance": float(np.exp(s.log_m_res))})
    return out
