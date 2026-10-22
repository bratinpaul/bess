"""Grey-box PCS loss model: P_loss = a + b·I + c·I² (per unit of the PCS rating).

  a  constant losses (standby, gate drive, fans, control)
  b  conduction-type losses, proportional to the current (IGBT / diode forward drops, switching ∝ I)
  c  ohmic losses, proportional to I² (conductors, inductors, transformer copper)

The current-dependent coefficients b and c may vary linearly with the IGBT temperature (ΔT = (T - 40 °C) / 10)
and with the DC bus voltage (ΔV = (V_dc / V_nom - 1) × 10), separately per direction (charge / discharge); the
constant term a has a per-unit offset (asset identity). The model stays linear in its parameters, so it is
fitted by bounded weighted least squares: a, b, c at the reference point are kept ≥ 0 (losses can't be negative),
and the weight 1 / P² makes the fit minimise the efficiency error (η error ≈ loss error / P), not the kW error.

η follows from the loss and the AC power (the side that is measured on both directions):
  discharge  η = P / (P + P_loss)          charge  η = (P - P_loss) / P
The fitted a / b / c are the health signal: a unit whose losses grow drifts away from them.
"""
from typing import ClassVar, Optional

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear

REF_TEMP_C = 40.0
TEMP_SCALE = 10.0
VOLT_SCALE = 10.0

TERMS = ("a", "b", "c")


class GreyBoxLossModel:
    key: ClassVar[str] = "greybox"
    label: ClassVar[str] = "Grey-box loss model"
    param_specs: ClassVar[list[dict]] = [
        {"name": "current_basis", "label": "Current proxy", "type": "choice", "default": "ac",
         "choices": ["ac", "dc"],
         "help": "ac: |S| / V_ac (AC current, follows reactive loading); dc: |P| / V_dc (DC current)."},
        {"name": "temp_dependence", "label": "Coefficients vary with IGBT temperature", "type": "bool", "default": True},
        {"name": "voltage_dependence", "label": "Coefficients vary with DC voltage", "type": "bool", "default": True},
        {"name": "separate_directions", "label": "Separate charge / discharge curves", "type": "bool", "default": True},
        {"name": "unit_offsets", "label": "Per-unit offset (asset identity)", "type": "bool", "default": True},
        {"name": "ridge", "label": "Ridge penalty", "type": "float", "default": 1e-6, "min": 0, "max": 1, "step": 1e-6,
         "help": "Small penalty that keeps the per-unit offsets and sensitivities stable."},
    ]

    def __init__(self, params: Optional[dict] = None):
        p = {s["name"]: s["default"] for s in self.param_specs}
        p.update(params or {})
        self.params = p
        self.columns: list[str] = []
        self.coef: Optional[np.ndarray] = None
        self.units: list[int] = []

    # ---------------------------------------------------------------- design

    def current(self, X: pd.DataFrame) -> np.ndarray:
        if self.params["current_basis"] == "dc":
            return (X["load_frac"] / X["v_dc_pu"].clip(lower=0.5)).to_numpy(float)
        return (X["s_frac"] / X["v_ac_pu"].clip(lower=0.5)).to_numpy(float)

    def _dirs(self) -> list[str]:
        return ["chg", "dis"] if self.params["separate_directions"] else ["all"]

    def _mods(self) -> list[str]:
        mods = [""]
        if self.params["temp_dependence"]:
            mods.append("dT")
        if self.params["voltage_dependence"]:
            mods.append("dV")
        return mods

    def _design(self, X: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
        i = self.current(X)
        dT = ((X["igbt_temp_c"] - REF_TEMP_C) / TEMP_SCALE).to_numpy(float)
        dV = ((X["v_dc_pu"] - 1.0) * VOLT_SCALE).to_numpy(float)
        chg = X["is_charge"].to_numpy(float)
        mod_val = {"": np.ones(len(X)), "dT": dT, "dV": dV}
        cols, names = [], []
        for d in self._dirs():
            mask = chg if d == "chg" else (1 - chg) if d == "dis" else np.ones(len(X))
            for term, base in (("a", np.ones(len(X))), ("b", i), ("c", i * i)):
                for m in self._mods():
                    if term == "a" and m:
                        continue  # standby losses: constant (plus the unit offset); light-load readings are too
                        # few and too cool to separate a temperature effect from it
                    cols.append(mask * base * mod_val[m])
                    names.append(f"{d}.{term}{('·' + m) if m else ''}")
        if self.params["unit_offsets"] and len(self.units) > 1:
            pcs = X["pcs_id"].to_numpy()
            for u in self.units[1:]:  # the first unit is the reference
                cols.append((pcs == u).astype(float))
                names.append(f"unit.{u}")
        return np.column_stack(cols), names

    # ---------------------------------------------------------------- fit / predict

    def fit(self, X: pd.DataFrame, loss_pu: np.ndarray) -> "GreyBoxLossModel":
        self.units = sorted(int(u) for u in X["pcs_id"].unique())
        A, self.columns = self._design(X)
        w = 1.0 / np.maximum(X["load_frac"].to_numpy(float), 0.05)
        Aw, yw = A * w[:, None], loss_pu * w
        lam = float(self.params["ridge"]) * len(X)
        if lam > 0:
            Aw = np.vstack([Aw, np.sqrt(lam) * np.eye(A.shape[1])])
            yw = np.concatenate([yw, np.zeros(A.shape[1])])
        # the base a / b / c of each direction are physical losses (≥ 0); sensitivities and unit offsets are free
        base = [("·" not in n and not n.startswith("unit.")) for n in self.columns]
        lower = np.where(base, 0.0, -np.inf)
        self.coef = lsq_linear(Aw, yw, bounds=(lower, np.full(len(lower), np.inf)), method="bvls").x
        return self

    def predict_loss_pu(self, X: pd.DataFrame) -> np.ndarray:
        A, _ = self._design(X)
        return np.clip(A @ self.coef, 0.0, None)

    def predict_eta_pct(self, X: pd.DataFrame) -> np.ndarray:
        return eta_from_loss(X["load_frac"].to_numpy(float), self.predict_loss_pu(X), X["is_charge"].to_numpy(float))

    def breakdown_pu(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Loss per term (constant / conduction / ohmic), in per unit, summing to the predicted loss (unclipped)."""
        A, names = self._design(X)
        parts = {"constant": np.zeros(len(X)), "conduction": np.zeros(len(X)), "ohmic": np.zeros(len(X))}
        for j, n in enumerate(names):
            key = "constant" if n.startswith("unit.") or n.split(".")[1].startswith("a") else (
                "conduction" if n.split(".")[1].startswith("b") else "ohmic")
            parts[key] += A[:, j] * self.coef[j]
        return parts

    # ---------------------------------------------------------------- report

    def coefficients(self) -> dict:
        """The fitted coefficients: a / b / c per direction at the reference point, their sensitivities, unit offsets."""
        c = dict(zip(self.columns, (float(v) for v in self.coef)))
        out = {"reference": {"igbt_temp_c": REF_TEMP_C, "v_dc_pu": 1.0, "temp_step_c": TEMP_SCALE,
                             "volt_step_pu": 1 / VOLT_SCALE},
               "current_basis": self.params["current_basis"], "directions": {}, "unit_offsets": {}}
        for d in self._dirs():
            out["directions"][d] = {t: {"value": c.get(f"{d}.{t}", 0.0),
                                        "per_10c": c.get(f"{d}.{t}·dT"),
                                        "per_0p1_vdc": c.get(f"{d}.{t}·dV")} for t in TERMS}
        for u in self.units[1:]:
            out["unit_offsets"][str(u)] = c.get(f"unit.{u}", 0.0)
        if self.units:
            out["unit_offsets"][str(self.units[0])] = 0.0
            out["reference_unit"] = self.units[0]
        return out

    def unit_terms(self, unit: int, direction: str) -> dict[str, float]:
        """a / b / c of one unit and direction at the reference temperature and voltage."""
        info = self.coefficients()
        d = direction if direction in info["directions"] else "all"
        terms = {t: info["directions"][d][t]["value"] for t in TERMS}
        terms["a"] += info["unit_offsets"].get(str(unit), 0.0)
        return terms


def eta_from_loss(load_frac: np.ndarray, loss_pu: np.ndarray, is_charge: np.ndarray) -> np.ndarray:
    p = np.maximum(load_frac, 1e-6)
    eta = np.where(is_charge > 0, (p - loss_pu) / p, p / (p + loss_pu))
    return np.clip(eta, 0.5, 1.0) * 100.0


def loss_from_eta(load_frac: np.ndarray, eta_pct: np.ndarray, is_charge: np.ndarray) -> np.ndarray:
    e = np.clip(eta_pct / 100.0, 0.5, 1.0)
    return np.where(is_charge > 0, load_frac * (1 - e), load_frac * (1 / e - 1))
