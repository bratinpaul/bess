"""Grey-box auxiliary-load model, one per site:

    aux  = controls_base + HVAC
    HVAC = p0 + k_q Â· Q_batt / COP(T_amb) + k_e Â· max(T_amb - T_b, 0) / COP(T_amb) + k_s Â· solar / COP(T_amb)

    Q_batt   battery heat load = h0 + h1 Â· |P| (losses -> heat; fitted on battery_heat_load_kw, |P| averaged over the
             last 15 min since the cooling loop lags the load a little)
    COP      falls with ambient: c0 + c1 Â· T_amb (fitted on the readings while cooling, kept within 1.5..8)
    envelope heat entering the enclosure above the balance temperature T_b (grid-searched)
    solar    clear-sky daylight shape (solar gain on the enclosure; no GHI feed needed)
    p0       fans / pumps / standby of the HVAC

controls_base is the median of aux - HVAC (near-constant). Without HVAC telemetry the same structure is fitted to aux
directly (p0 then holds the controls). Fitted by least squares with k_q, k_e, k_s >= 0, so the parameters stay physical
and the model extrapolates sensibly to hotter days or heavier dispatch.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import lsq_linear

COP_DEFAULT = (5.6, -0.058)
COP_RANGE = (1.5, 8.0)


@dataclass
class AuxGreyBox:
    controls_base: float = 0.0
    decomposed: bool = True  # False: no HVAC telemetry, the HVAC terms model aux directly
    heat: tuple[float, float] = (0.0, 0.0)  # h0, h1
    cop: tuple[float, float] = COP_DEFAULT  # c0, c1
    t_balance: float = 25.0
    coef: dict[str, float] = field(default_factory=dict)  # p0, k_q, k_e, k_s
    r2: Optional[float] = None
    mae: Optional[float] = None

    def cop_at(self, amb) -> np.ndarray:
        return np.clip(self.cop[0] + self.cop[1] * np.asarray(amb, float), *COP_RANGE)

    def heat_at(self, abs_p) -> np.ndarray:
        return np.maximum(self.heat[0] + self.heat[1] * np.asarray(abs_p, float), 0.0)

    def design(self, abs_p, amb, solar, t_balance: Optional[float] = None) -> np.ndarray:
        cop = self.cop_at(amb)
        tb = self.t_balance if t_balance is None else t_balance
        amb = np.asarray(amb, float)
        return np.column_stack([np.ones(len(amb)), self.heat_at(abs_p) / cop, np.maximum(amb - tb, 0.0) / cop,
                                np.asarray(solar, float) / cop])

    def hvac(self, abs_p, amb, solar) -> np.ndarray:
        c = self.coef
        beta = np.array([c["p0"], c["k_q"], c["k_e"], c["k_s"]])
        return np.maximum(self.design(abs_p, amb, solar) @ beta, 0.0)

    def aux(self, abs_p, amb, solar) -> np.ndarray:
        return self.hvac(abs_p, amb, solar) + (self.controls_base if self.decomposed else 0.0)

    @classmethod
    def fit(cls, aux, hvac, abs_p, amb, solar, heat_load, cop, cooling) -> "AuxGreyBox":
        aux, hvac, abs_p, amb, solar = (np.asarray(x, float) for x in (aux, hvac, abs_p, amb, solar))
        heat_load, cop = np.asarray(heat_load, float), np.asarray(cop, float)
        m = cls()
        both = np.isfinite(aux) & np.isfinite(hvac)
        m.decomposed = bool(both.sum() >= 100)
        if m.decomposed:
            m.controls_base = float(np.median(aux[both] - hvac[both]))
            y = hvac
        else:
            y = aux
        # battery heat load vs |P|
        k = np.isfinite(heat_load) & np.isfinite(abs_p)
        if k.sum() >= 50:
            sol = lsq_linear(np.column_stack([np.ones(k.sum()), abs_p[k]]), heat_load[k], bounds=([0, 0], [np.inf, np.inf])).x
            m.heat = (float(sol[0]), float(sol[1]))
        else:
            m.heat = (0.0, 0.03)  # ~3 % of the throughput ends up as heat
        # COP(ambient) while cooling
        k = np.asarray(cooling, bool) & np.isfinite(cop) & np.isfinite(amb)
        if k.sum() >= 50 and np.ptp(amb[k]) > 2:
            c1, c0 = np.polyfit(amb[k], cop[k], 1)
            m.cop = (float(c0), float(min(c1, 0.0)))
        # the HVAC map; the balance temperature by grid search on the last quarter of the training readings
        ok = np.isfinite(y) & np.isfinite(abs_p) & np.isfinite(amb) & np.isfinite(solar)
        idx = np.flatnonzero(ok)
        if len(idx) < 50:
            raise ValueError("Too few readings to fit the grey-box aux model")
        cut = idx[int(len(idx) * 0.75)]
        fit_i, val_i = idx[idx < cut], idx[idx >= cut]
        lower, upper = [-np.inf, 0, 0, 0], [np.inf] * 4
        best = None
        for tb in np.arange(15.0, 35.01, 0.5):
            A = m.design(abs_p[fit_i], amb[fit_i], solar[fit_i], tb)
            beta = lsq_linear(A, y[fit_i], bounds=(lower, upper)).x
            err = np.mean(np.abs(y[val_i] - m.design(abs_p[val_i], amb[val_i], solar[val_i], tb) @ beta))
            if best is None or err < best[0]:
                best = (err, tb)
        m.t_balance = float(best[1])
        A = m.design(abs_p[idx], amb[idx], solar[idx])
        beta = lsq_linear(A, y[idx], bounds=(lower, upper)).x
        m.coef = dict(zip(("p0", "k_q", "k_e", "k_s"), (float(b) for b in beta)))
        pred = m.aux(abs_p[idx], amb[idx], solar[idx])
        a = aux[idx]
        a_ok = np.isfinite(a)
        if a_ok.sum() > 2:
            m.mae = float(np.mean(np.abs(a[a_ok] - pred[a_ok])))
            m.r2 = float(1 - np.var(a[a_ok] - pred[a_ok]) / max(np.var(a[a_ok]), 1e-9))
        return m

    def to_dict(self) -> dict:
        return {"controls_base_kw": self.controls_base, "decomposed": self.decomposed,
                "heat_h0_kw": self.heat[0], "heat_h1_kw_per_kw": self.heat[1], "cop_c0": self.cop[0],
                "cop_c1_per_c": self.cop[1], "t_balance_c": self.t_balance, **self.coef, "r2": self.r2,
                "mae_kw": self.mae}
