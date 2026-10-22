"""The dispatch MILP (scipy.optimize.milp = HiGHS; no extra solver package).

One solve covers T intervals of Δt hours and S price scenarios with weights w_s (deterministic = one scenario, the
P50 forecast; the oracle = one scenario, the realized price). The first F intervals are here-and-now decisions shared
by every scenario (non-anticipativity); the rest is scenario-dependent recourse. Deterministic: F = T.

Variables per (scenario, t) - shared for t < F:
  pd_k, pc_k ≥ 0   discharge / charge power in efficiency segment k (kW); K = 1 (scalar √rte_ac) or the curve's
                   power-fraction segments - η falls with power, so cheap segments fill first without binaries
  u_d, u_c         binary mode (no simultaneous charge + discharge)
  c, y             AS capacity committed (MW) and its binary (minimum bid)        [AS stacking on]
  soc_t            % at the end of interval t
Per scenario: smax, smin, d_b (DoD layers)                                        [degradation curve on]
CVaR: eta, z_s                                                                    [risk weight λ > 0]

Profit of scenario s (maximized as (1 − λ)·E[profit] + λ·CVaR_α):
  Σ_t Δt/1000 · [ (π − tax·π − wheeling − duty_exp − deg)·Σpd − (π + tax·π + wheeling + duty_imp + deg)·Σpc ]
  + Σ_t as_price_t · c_t · Δt  −  Σ_b (m_b − m_1)·2·E_mwh·d_b/100
Constraints: SOC dynamics with split efficiency and self-discharge, SOC band, power ≤ available × mode, POI caps,
ramp on the net power, cycle cap, AS power + energy headroom (sustain minutes), capacity cap and standing award floors, terminal
SOC ≥ target, DoD layers = daily SOC range.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from usecases.arbitrage.data import AsInfo, Battery, GridCharges


class LP:
    """Tiny sparse model builder: variables with bounds / integrality, linear rows lo ≤ a·x ≤ hi, objective c·x."""

    def __init__(self):
        self.lb, self.ub, self.integ, self.c = [], [], [], []
        self.rows, self.cols, self.vals, self.lo, self.hi = [], [], [], [], []

    def var(self, lb=0.0, ub=np.inf, integer=False, cost=0.0) -> int:
        self.lb.append(lb)
        self.ub.append(ub)
        self.integ.append(1 if integer else 0)
        self.c.append(cost)
        return len(self.lb) - 1

    def add(self, terms: dict, lo=-np.inf, hi=np.inf) -> None:
        r = len(self.lo)
        for j, v in terms.items():
            if v != 0:
                self.rows.append(r)
                self.cols.append(j)
                self.vals.append(v)
        self.lo.append(lo)
        self.hi.append(hi)

    def obj(self, j: int, v: float) -> None:
        self.c[j] += v

    def solve(self, maximize=True, time_limit=30.0, gap=1e-4):
        n = len(self.lb)
        c = -np.array(self.c) if maximize else np.array(self.c)
        cons = []
        if self.lo:
            A = coo_matrix((self.vals, (self.rows, self.cols)), shape=(len(self.lo), n)).tocsr()
            cons = [LinearConstraint(A, np.array(self.lo), np.array(self.hi))]
        t0 = time.perf_counter()
        res = milp(c, constraints=cons, integrality=np.array(self.integ), bounds=Bounds(self.lb, self.ub),
                   options={"time_limit": time_limit, "mip_rel_gap": gap, "disp": False})
        return res, time.perf_counter() - t0


@dataclass
class Settings:
    efficiency: str = "scalar"          # scalar | curve
    degradation: str = "scalar"         # scalar | curve
    as_stacking: bool = True
    terminal: str = "next_open"         # next_open (planned next-day opening SOC) | start | value | free
    terminal_soc: float = 50.0
    cvar_lambda: float = 0.0
    cvar_alpha: float = 0.9
    deg_cost_override: Optional[float] = None   # e.g. 0 for the over-cycling check
    as_max_mw: Optional[float] = None           # AS capacity cap (MW); None = decision_state.reserved_mw_as
    time_limit: float = 30.0


@dataclass
class Plan:
    status: str
    objective: float                    # optimizer's objective value (expected profit incl. AS)
    solve_seconds: float
    pd: np.ndarray                      # first-stage / deterministic discharge kW per interval (scenario-weighted)
    pc: np.ndarray
    soc: np.ndarray                     # SOC at the end of each interval (scenario-weighted after F)
    c_as: np.ndarray                    # MW
    drain: np.ndarray                   # SOC % change per interval from power (− discharge drain + charge gain)
    expected_by_scenario: list = field(default_factory=list)


def efficiency_segments(b: Battery, s: Settings) -> tuple[list, list, list]:
    """(widths kW, η_charge, η_discharge) per segment."""
    eta = float(np.sqrt(b.rte_ac))
    if s.efficiency != "curve" or not b.eff_curve.get("CHARGE") or not b.eff_curve.get("DISCHARGE"):
        return [1.0], [eta], [eta]
    ch = sorted(b.eff_curve["CHARGE"])
    dis = sorted(b.eff_curve["DISCHARGE"])
    fr = [f for f, _ in ch]
    widths = [fr[0]] + [fr[i] - fr[i - 1] for i in range(1, len(fr))]
    return widths, [e for _, e in ch], [e for _, e in dis]


def solve(b: Battery, g: GridCharges, a: AsInfo, s: Settings, prices: np.ndarray, probs: np.ndarray,
          dt_h: float, soc0: float, prev_net_kw: float, cycles_left: Optional[float], as_price: np.ndarray,
          as_floor: np.ndarray, first_stage: Optional[int] = None, p_dis_avail: Optional[float] = None,
          p_chg_avail: Optional[float] = None, usable_mwh: Optional[float] = None,
          terminal_target: Optional[float] = None, as_cap_mw: Optional[float] = None) -> Plan:
    prices = np.atleast_2d(prices)
    S, T = prices.shape
    F = T if first_stage is None else max(1, min(first_stage, T))
    E_kwh = (usable_mwh or b.usable_mwh) * 1000.0
    Pd = min(p_dis_avail or b.p_discharge_max_kw, b.p_discharge_max_kw, b.poi_export_max_kw)
    Pc = min(p_chg_avail or b.p_charge_max_kw, b.p_charge_max_kw, b.poi_import_max_kw)
    widths, eta_c, eta_d = efficiency_segments(b, s)
    K = len(widths)
    deg_base = s.deg_cost_override if s.deg_cost_override is not None else (
        b.deg_curve[0][1] if s.degradation == "curve" and b.deg_curve else b.degradation_cost_mwh)
    use_layers = s.degradation == "curve" and len(b.deg_curve) > 1 and s.deg_cost_override is None
    sd = b.self_discharge_pct_day * dt_h / 24.0
    ramp = b.ramp_kw_per_min * dt_h * 60.0 if b.ramp_kw_per_min else None
    as_on = s.as_stacking and a.product_id is not None and np.any(as_price > 0)
    cmax = min(Pd, Pc) / 1000.0
    if as_cap_mw is not None:
        cmax = max(0.0, min(cmax, as_cap_mw))
    as_on = as_on and cmax >= a.min_bid_mw
    lam = max(0.0, min(1.0, s.cvar_lambda)) if S > 1 else 0.0

    lp = LP()
    pd_v = np.empty((S, T, K), dtype=int)
    pc_v = np.empty((S, T, K), dtype=int)
    ud_v = np.empty((S, T), dtype=int)
    uc_v = np.empty((S, T), dtype=int)
    soc_v = np.empty((S, T), dtype=int)
    c_v = np.full((S, T), -1, dtype=int)
    y_v = np.full((S, T), -1, dtype=int)
    for sc in range(S):
        for t in range(T):
            if t < F and sc > 0:  # shared here-and-now decisions
                pd_v[sc, t], pc_v[sc, t] = pd_v[0, t], pc_v[0, t]
                ud_v[sc, t], uc_v[sc, t], soc_v[sc, t] = ud_v[0, t], uc_v[0, t], soc_v[0, t]
                c_v[sc, t], y_v[sc, t] = c_v[0, t], y_v[0, t]
                continue
            for k in range(K):
                pd_v[sc, t, k] = lp.var(0, widths[k] * Pd)
                pc_v[sc, t, k] = lp.var(0, widths[k] * Pc)
            ud_v[sc, t] = lp.var(0, 1, True)
            uc_v[sc, t] = lp.var(0, 1, True)
            soc_v[sc, t] = lp.var(b.soc_min, b.soc_max)
            if as_on:
                c_v[sc, t] = lp.var(0, cmax)
                y_v[sc, t] = lp.var(0, 1, True)

    profit_terms = []  # per scenario: dict var -> coefficient (for CVaR)
    for sc in range(S):
        pt: dict = {}
        for t in range(T):
            pi = prices[sc, t]
            dis = dt_h / 1000.0 * (pi * (1 - g.tax_fraction) - g.wheeling_mwh - g.export_duty_mwh - deg_base)
            chg = -dt_h / 1000.0 * (pi * (1 + g.tax_fraction) + g.wheeling_mwh + g.import_duty_mwh + deg_base)
            for k in range(K):
                pt[pd_v[sc, t, k]] = pt.get(pd_v[sc, t, k], 0) + dis
                pt[pc_v[sc, t, k]] = pt.get(pc_v[sc, t, k], 0) + chg
            if as_on:
                pt[c_v[sc, t]] = pt.get(c_v[sc, t], 0) + as_price[t] * dt_h
        if use_layers:
            smax, smin = lp.var(b.soc_min, b.soc_max), lp.var(b.soc_min, b.soc_max)
            m1 = b.deg_curve[0][1]
            prev = 0
            layer = {smax: 1.0, smin: -1.0}
            for upper, cost in b.deg_curve:
                d = lp.var(0, upper - prev)
                layer[d] = -1.0
                pt[d] = pt.get(d, 0) - (cost - m1) * 2.0 * E_kwh / 1000.0 / 100.0
                prev = upper
            lp.add(layer, 0, 0)
            lp.add({smax: 1.0}, soc0, np.inf)
            lp.add({smin: 1.0}, -np.inf, soc0)
            for t in range(T):
                lp.add({smax: 1.0, soc_v[sc, t]: -1.0}, 0, np.inf)
                lp.add({smin: 1.0, soc_v[sc, t]: -1.0}, -np.inf, 0)
        profit_terms.append(pt)

    # objective: (1 − λ) Σ w_s profit_s + λ (eta − Σ w_s z_s / (1 − α))
    for sc in range(S):
        for j, v in profit_terms[sc].items():
            lp.obj(j, (1 - lam) * probs[sc] * v)
    if lam > 0:
        eta = lp.var(-np.inf, np.inf, cost=lam)
        for sc in range(S):
            z = lp.var(0, np.inf, cost=-lam * probs[sc] / (1 - s.cvar_alpha))
            row = {z: 1.0, eta: -1.0}
            for j, v in profit_terms[sc].items():
                row[j] = row.get(j, 0) + v
            lp.add(row, 0, np.inf)  # z ≥ eta − profit

    for sc in range(S):
        cyc = {}
        for t in range(T):
            shared = t < F and sc > 0
            if not shared:
                # mode
                lp.add({**{pd_v[sc, t, k]: 1.0 for k in range(K)}, ud_v[sc, t]: -Pd}, -np.inf, 0)
                lp.add({**{pc_v[sc, t, k]: 1.0 for k in range(K)}, uc_v[sc, t]: -Pc}, -np.inf, 0)
                lp.add({ud_v[sc, t]: 1.0, uc_v[sc, t]: 1.0}, -np.inf, 1)
                # SOC dynamics: soc_t − soc_{t−1} − 100Δt/E (Σ η_c pc − Σ pd/η_d) = −sd
                row = {soc_v[sc, t]: 1.0}
                for k in range(K):
                    row[pc_v[sc, t, k]] = -100.0 * dt_h / E_kwh * eta_c[k]
                    row[pd_v[sc, t, k]] = 100.0 * dt_h / E_kwh / eta_d[k]
                if t == 0:
                    lp.add(row, soc0 - sd, soc0 - sd)
                else:
                    row[soc_v[sc, t - 1]] = row.get(soc_v[sc, t - 1], 0) - 1.0
                    lp.add(row, -sd, -sd)
                # ramp on the net power
                if ramp is not None:
                    net = {**{pd_v[sc, t, k]: 1.0 for k in range(K)}, **{pc_v[sc, t, k]: -1.0 for k in range(K)}}
                    if t == 0:
                        lp.add(net, prev_net_kw - ramp, prev_net_kw + ramp)
                    else:
                        for k in range(K):
                            net[pd_v[sc, t - 1, k]] = net.get(pd_v[sc, t - 1, k], 0) - 1.0
                            net[pc_v[sc, t - 1, k]] = net.get(pc_v[sc, t - 1, k], 0) + 1.0
                        lp.add(net, -ramp, ramp)
                if as_on:
                    lp.add({**{pd_v[sc, t, k]: 1.0 for k in range(K)}, c_v[sc, t]: 1000.0}, -np.inf, Pd)
                    lp.add({**{pc_v[sc, t, k]: 1.0 for k in range(K)}, c_v[sc, t]: 1000.0}, -np.inf, Pc)
                    hold = 100.0 * 1000.0 * (a.sustain_min / 60.0) / E_kwh  # SOC % to sustain 1 MW
                    if t == 0:
                        lp.add({c_v[sc, t]: hold}, -np.inf, min(soc0 - b.soc_min, b.soc_max - soc0))
                    else:
                        lp.add({soc_v[sc, t - 1]: 1.0, c_v[sc, t]: -hold}, b.soc_min, np.inf)
                        lp.add({soc_v[sc, t - 1]: 1.0, c_v[sc, t]: hold}, -np.inf, b.soc_max)
                    lp.add({c_v[sc, t]: 1.0, y_v[sc, t]: -a.min_bid_mw}, 0, np.inf)
                    lp.add({c_v[sc, t]: 1.0, y_v[sc, t]: -cmax}, -np.inf, 0)
                    if as_floor[t] > 0:
                        lp.add({c_v[sc, t]: 1.0}, min(as_floor[t], cmax), np.inf)
            for k in range(K):
                cyc[pd_v[sc, t, k]] = cyc.get(pd_v[sc, t, k], 0) + dt_h / E_kwh
        if cycles_left is not None:
            lp.add(cyc, -np.inf, max(cycles_left, 0.0))
        if s.terminal != "free":
            # next_open / start: the caller passes the day's target (next-day opening SOC or the day's start SOC)
            target = s.terminal_soc if s.terminal == "value" else (terminal_target if terminal_target is not None else soc0)
            target = min(max(target, b.soc_min), b.soc_max)
            lp.add({soc_v[sc, T - 1]: 1.0}, target - 1e-6, np.inf)

    res, secs = lp.solve(time_limit=s.time_limit)
    status = {0: "OPTIMAL", 1: "TIME_LIMIT", 2: "INFEASIBLE", 3: "INFEASIBLE", 4: "ERROR"}.get(res.status, "ERROR")
    if res.x is None:
        raise RuntimeError(f"Optimizer {status.lower()}: {res.message}")
    if status == "TIME_LIMIT":
        status = "FEASIBLE"
    x = res.x
    pd_t = np.einsum("s,stk->t", probs, x[pd_v])
    pc_t = np.einsum("s,stk->t", probs, x[pc_v])
    soc_t = probs @ x[soc_v]
    c_t = probs @ x[c_v] if as_on else np.zeros(T)
    drain = np.array([sum(100.0 * dt_h / E_kwh * (eta_c[k] * np.dot(probs, x[pc_v[:, t, k]])
                                                  - np.dot(probs, x[pd_v[:, t, k]]) / eta_d[k]) for k in range(K))
                      for t in range(T)])
    by_s = [float(sum(v * x[j] for j, v in pt.items())) for pt in profit_terms]
    return Plan(status, float(-res.fun), secs, pd_t, pc_t, soc_t, c_t, drain, by_s)
