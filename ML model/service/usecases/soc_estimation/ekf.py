"""Extended Kalman filter for SOC: coulomb-count propagation with a sensor-offset state, rested-OCV measurement update.

State x = [soc (%), bias (A), gain (-)]:
  soc    state of charge
  bias   residual current-sensor offset on top of the BMS-estimated one (current_sensor_offset_a) - the drift source
  gain   capacity scale: SOC moves gain x the coulomb-counted step (usable_capacity_ah may be off, gain errors)

Propagate (Δt = time since the previous row):
  I      = measured_current_a - current_sensor_offset_a - bias
  soc'   = soc + gain * k * I,   k = 100 * coulombic_efficiency * Δt_h / usable_capacity_ah
Measure (only when rested >= min_rest_min, at most every ocv_every_min, ocv_rested_v not NULL):
  z = ocv_rested_v,  h(soc) = OCV(soc, direction, temperature),  H = [dOCV/dSOC, 0, 0]
  The direction (hysteresis branch) is the sign of the last real current (|I| > 0.02 C); MEAN until one is seen.
  `hysteresis` blends the MEAN curve (0) towards that branch (1) - tunable, as some plants' rested OCV sits mid-way.
  In LFP's flat mid-SOC region dOCV/dSOC is ~1 mV/% so the Kalman gain shrinks there by itself - the filter
  trusts coulomb counting where the voltage says little and snaps to the OCV near the ends.
Hard recalibration: at a FULL_CHARGE anchor (soc_reference) the SOC is set to the anchor and its variance to ~0.
"""
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from usecases.soc_estimation.features import OcvCurve

Z90 = 1.2815515655446004  # P10 / P90 of a normal


@dataclass
class EkfParams:
    r_mv: float = 3.0            # rested-OCV measurement noise (mV, per cell)
    q_soc: float = 0.02          # SOC process noise per 5 min (%)
    q_rel: float = 0.05          # SOC process noise as a share of each coulomb step (integration / capacity error)
    q_bias: float = 0.02         # bias random walk per 5 min (A)
    q_gain: float = 1e-5         # gain random walk per 5 min
    init_sigma_soc: float = 5.0
    init_sigma_bias: float = 2.0
    init_sigma_gain: float = 0.05
    min_rest_min: float = 30.0   # rest needed before the OCV is trusted (relaxation)
    ocv_every_min: float = 60.0  # at most one OCV update per this many minutes (the readings are correlated)
    full_charge_reset: bool = True
    hysteresis: float = 1.0      # weight of the charge / discharge OCV branch vs the MEAN curve (0 = mean only)
    anchor_sigma: float = 0.1    # SOC sd right after a FULL_CHARGE recalibration (%)
    gap_inflate: float = 0.05    # extra SOC variance per missing 5-min step (%^2)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EkfState:
    soc: float
    bias: float = 0.0
    gain: float = 1.0
    P: list = field(default_factory=lambda: [[25.0, 0, 0], [0, 4.0, 0], [0, 0, 0.0025]])
    direction: str = "MEAN"
    ts: Optional[str] = None             # the last row the state includes
    last_recal_ts: Optional[str] = None  # last OCV update or FULL_CHARGE reset
    last_ocv_ts: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def initial(soc: float, p: EkfParams, bias: float = 0.0, gain: float = 1.0) -> "EkfState":
        return EkfState(float(np.clip(soc, 0, 100)), bias, gain,
                        [[p.init_sigma_soc ** 2, 0, 0], [0, p.init_sigma_bias ** 2, 0], [0, 0, p.init_sigma_gain ** 2]])


def run(df: pd.DataFrame, curve: OcvCurve, p: EkfParams, state: Optional[EkfState] = None) -> tuple[pd.DataFrame, EkfState]:
    """Filters the rows of df in order (from `state`, or from the first coulomb SOC). Returns per row: ekf_soc,
    ekf_sigma, ekf_bias, ekf_gain, recalibrated (an OCV update or FULL_CHARGE reset at this row), recal_kind, direction,
    min_since_recal, innovation_mv - and the state after the last row."""
    n = len(df)
    out_soc, out_sig, out_b, out_g = np.empty(n), np.empty(n), np.empty(n), np.empty(n)
    out_recal = np.zeros(n, bool)
    out_kind = np.empty(n, object)
    out_dir = np.empty(n, object)
    out_since = np.full(n, np.nan)
    out_innov = np.full(n, np.nan)
    if n == 0:
        return pd.DataFrame(index=df.index), state

    st = state or EkfState.initial(float(df["soc_coulomb_pct"].iloc[0]), p)
    s, b, g = st.soc, st.bias, st.gain
    P = [row[:] for row in st.P]
    direction = st.direction
    last_recal = pd.Timestamp(st.last_recal_ts) if st.last_recal_ts else None
    last_ocv = pd.Timestamp(st.last_ocv_ts) if st.last_ocv_ts else None
    prev_ts = pd.Timestamp(st.ts) if st.ts else None
    r = (p.r_mv / 1000.0) ** 2

    ts_arr = df.index
    I_meas = df["measured_current_a"].to_numpy(float)
    off = df["current_sensor_offset_a"].to_numpy(float)
    cap = df["usable_capacity_ah"].to_numpy(float)
    ce = df["coulombic_efficiency"].to_numpy(float)
    ocv = df["ocv_rested_v"].to_numpy(float)
    rest = df["rest_duration_min"].to_numpy(float)
    temp = df["cell_temp_avg_c"].to_numpy(float)
    anchor = df["soc_true_pct"].to_numpy(float) if "soc_true_pct" in df else np.full(n, np.nan)
    method = df["reference_method"].to_numpy(object) if "reference_method" in df else np.full(n, None, object)

    for i in range(n):
        ts = ts_arr[i]
        dt_min = 5.0 if prev_ts is None else max(0.0, (ts - prev_ts).total_seconds() / 60.0)
        prev_ts = ts
        steps = dt_min / 5.0
        # ---- propagate
        Ii = I_meas[i] if I_meas[i] == I_meas[i] else 0.0
        Ic = Ii - (off[i] if off[i] == off[i] else 0.0) - b
        ci = cap[i] if cap[i] == cap[i] and cap[i] > 0 else 1.0
        k = 100.0 * (ce[i] if ce[i] == ce[i] else 1.0) * (dt_min / 60.0) / ci
        if abs(Ic) > 0.02 * ci:
            direction = "CHARGE" if Ic > 0 else "DISCHARGE"
        s = s + g * k * Ic
        # P = F P F' + Q with F = [[1, -g k, k Ic], [0, 1, 0], [0, 0, 1]]
        f01, f02 = -g * k, k * Ic
        p00, p01, p02 = P[0]
        _, p11, p12 = P[1]
        p22 = P[2][2]
        n00 = p00 + 2 * f01 * p01 + 2 * f02 * p02 + f01 * f01 * p11 + 2 * f01 * f02 * p12 + f02 * f02 * p22
        n01 = p01 + f01 * p11 + f02 * p12
        n02 = p02 + f01 * p12 + f02 * p22
        q_s = p.q_soc ** 2 * steps + (p.q_rel * g * k * Ic) ** 2 + (p.gap_inflate * max(0.0, steps - 1.0) if dt_min > 7.5 else 0.0)
        P = [[n00 + q_s, n01, n02],
             [n01, p11 + p.q_bias ** 2 * steps, p12],
             [n02, p12, p22 + p.q_gain ** 2 * steps]]
        kind = None
        # ---- hard recalibration at a full-charge anchor
        if p.full_charge_reset and method[i] == "FULL_CHARGE" and anchor[i] == anchor[i]:
            s = float(anchor[i])
            P[0] = [p.anchor_sigma ** 2, 0.0, 0.0]
            P[1][0] = P[2][0] = 0.0
            kind = "FULL_CHARGE"
        # ---- rested-OCV measurement update
        elif ocv[i] == ocv[i] and rest[i] == rest[i] and rest[i] >= p.min_rest_min and \
                (last_ocv is None or (ts - last_ocv).total_seconds() / 60.0 >= p.ocv_every_min - 1e-6):
            sc = min(100.0, max(0.0, s))
            h, H = ocv_model(curve, sc, direction, temp[i], p.hysteresis)
            S = H * H * P[0][0] + r
            innov = ocv[i] - h
            K0, K1, K2 = P[0][0] * H / S, P[1][0] * H / S, P[2][0] * H / S
            s += K0 * innov
            b += K1 * innov
            g += K2 * innov
            row0 = P[0][:]
            P = [[P[a][c] - Kx * H * row0[c] for c in range(3)] for a, Kx in enumerate((K0, K1, K2))]
            # keep it symmetric
            P[0][1] = P[1][0] = (P[0][1] + P[1][0]) / 2
            P[0][2] = P[2][0] = (P[0][2] + P[2][0]) / 2
            P[1][2] = P[2][1] = (P[1][2] + P[2][1]) / 2
            out_innov[i] = innov * 1000.0
            last_ocv = ts
            kind = "REST_OCV"
        if kind:
            last_recal = ts
            out_recal[i] = True
        s = min(100.0, max(0.0, s))
        b = min(50.0, max(-50.0, b))
        g = min(1.25, max(0.8, g))
        P[0][0] = max(P[0][0], 1e-6)
        out_soc[i], out_sig[i], out_b[i], out_g[i] = s, math.sqrt(P[0][0]), b, g
        out_kind[i], out_dir[i] = kind, direction
        out_since[i] = (ts - last_recal).total_seconds() / 60.0 if last_recal is not None else np.nan

    res = pd.DataFrame({"ekf_soc": out_soc, "ekf_sigma": out_sig, "ekf_bias": out_b, "ekf_gain": out_g,
                        "recalibrated": out_recal, "recal_kind": out_kind, "direction": out_dir,
                        "min_since_recal": out_since, "innovation_mv": out_innov}, index=df.index)
    end = EkfState(s, b, g, P, direction, ts_arr[-1].isoformat(),
                   last_recal.isoformat() if last_recal is not None else None,
                   last_ocv.isoformat() if last_ocv is not None else None)
    return res, end


def ocv_model(curve: OcvCurve, soc: float, direction: str, temp_c: float, hysteresis: float) -> tuple[float, float]:
    """OCV and dOCV/dSOC on the MEAN curve moved `hysteresis` of the way to the direction's branch."""
    h, H = curve.ocv(soc, "MEAN", temp_c), curve.slope(soc, "MEAN", temp_c)
    if hysteresis and direction in ("CHARGE", "DISCHARGE"):
        h += hysteresis * (curve.ocv(soc, direction, temp_c) - h)
        H += hysteresis * (curve.slope(soc, direction, temp_c) - H)
    return h, H


def ocv_soc(curve: OcvCurve, ocv_v: float, direction: str, temp_c: float, hysteresis: float) -> float:
    """SOC implied by a rested OCV (the inverse of ocv_model; both branches share the MEAN curve's SOC grid)."""
    if ocv_v != ocv_v:
        return float("nan")
    socs, v = curve._curve("MEAN", temp_c)
    if hysteresis and direction in ("CHARGE", "DISCHARGE") and direction in curve.grids:
        sd, vd = curve._curve(direction, temp_c)
        v = v + hysteresis * (np.interp(socs, sd, vd) - v)
    return float(np.interp(ocv_v, np.maximum.accumulate(v), socs))


def band(soc: np.ndarray, sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.clip(soc - Z90 * sigma, 0, 100), np.clip(soc + Z90 * sigma, 0, 100)
