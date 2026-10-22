"""Grey-box first-order thermal (RC) model, one per target and asset.

    C dT/dt = Q_loss - k (T - T_ref) - k_a (T - T_amb)

With the drivers held over a step, its exact solution is an exponential approach to the steady state:
    T_ss = (k T_ref + k_a T_amb + Q_loss) / (k + k_a)  =  w_ref T_ref + w_amb T_amb + Σ b_i q_i + c
    T(t + h) = T_ss(t + h) + α^(h / 5 min) (T(t) - T_ss(t)),     α = exp(-5 min / τ),  τ = C / (k + k_a)
Q_loss is linear in the heat drivers q_i (|I| and I², per unit of rating: conduction and ohmic losses).
Fitted in two least-squares steps: the steady-state map on all readings, then α from the one-step decay of the
deviation from it. A small τ (as in the sample data, where temperatures settle within a step) gives α ≈ 0: the forecast
is the steady state of the planned load. The parameters stay physical: b_i ≥ 0 (losses heat), α in [0, 0.995].
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import lsq_linear

STEP_MIN = 5


@dataclass
class RCModel:
    drivers: list[str]
    coef: dict[str, float] = field(default_factory=dict)  # w_ref, w_amb, b_<driver>, c
    alpha: float = 0.0

    @property
    def tau_min(self) -> float:
        return float(-STEP_MIN / np.log(self.alpha)) if 0 < self.alpha < 1 else 0.0

    def steady(self, t_ref, t_amb, q: dict) -> np.ndarray:
        out = self.coef["c"] + self.coef["w_ref"] * np.asarray(t_ref, float) + self.coef["w_amb"] * np.asarray(t_amb, float)
        for d in self.drivers:
            out = out + self.coef[f"b_{d}"] * np.asarray(q[d], float)
        return out

    @classmethod
    def fit(cls, T: np.ndarray, t_ref: np.ndarray, t_amb: np.ndarray, q: dict, drivers: list[str]) -> "RCModel":
        m = np.isfinite(T) & np.isfinite(t_ref) & np.isfinite(t_amb)
        for d in drivers:
            m &= np.isfinite(q[d])
        cols = [t_ref[m], t_amb[m]] + [q[d][m] for d in drivers] + [np.ones(m.sum())]
        A = np.column_stack(cols)
        lower = np.array([-np.inf, -np.inf] + [0.0] * len(drivers) + [-np.inf])
        sol = lsq_linear(A, T[m], bounds=(lower, np.full(A.shape[1], np.inf))).x
        model = cls(drivers, {"w_ref": float(sol[0]), "w_amb": float(sol[1]),
                              **{f"b_{d}": float(v) for d, v in zip(drivers, sol[2:-1])}, "c": float(sol[-1])})
        dev = np.full(len(T), np.nan)
        dev[m] = T[m] - A @ sol
        x, y = dev[:-1], dev[1:]
        k = np.isfinite(x) & np.isfinite(y)
        model.alpha = float(np.clip((x[k] @ y[k]) / max(x[k] @ x[k], 1e-9), 0.0, 0.995)) if k.sum() > 20 else 0.0
        model.r2 = float(1 - np.nanvar(dev) / np.nanvar(T[m])) if m.sum() > 2 else None
        return model

    def predict(self, T0: np.ndarray, ss0: np.ndarray, ss_h: np.ndarray, steps: np.ndarray) -> np.ndarray:
        """T at h = steps x 5 min ahead from T0, the steady state now (ss0) and at the target time (ss_h)."""
        return ss_h + (self.alpha ** steps) * (T0 - ss0)

    def to_dict(self) -> dict:
        return {"drivers": self.drivers, "coef": self.coef, "alpha": self.alpha, "tau_min": self.tau_min,
                "r2_steady": getattr(self, "r2", None)}
