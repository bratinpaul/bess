"""Current-sensing, SOC-estimation and rest signals of a BMS reading stream - the system_telemetry columns added in
2026-10 (measured_current_a ... ocv_rested_v), derived where the source data does not carry them.

Shared by the snapshot simulator (one interval at a time) and the historical generator (a whole series). The model,
per 5-minute reading (positive current = charging):

  measured_current_a        the current sensor's reading: true pack current + a slowly drifting offset + gain noise
  current_sensor_offset_a   that offset: a bounded random walk (~0.2 A/day, within +/-1.5 A)
  soc_coulomb_pct           raw coulomb counting of the *measured* current over the usable capacity (charge scaled by
                            the coulombic efficiency) - it drifts with the sensor error and is recalibrated to the BMS
                            SOC after RECAL_REST_MIN minutes at rest (the OCV point), as the column comment describes
  soc_battery_telemetry_pct the SOC the plant telemetry (SCADA) reports: the BMS SOC one interval late, in 0.5 % steps
  usable_capacity_ah        nominal Ah (rated kWh / nominal DC voltage) x SOH
  coulombic_efficiency      fraction (~0.998), lower when hot and as the cells age
  at_rest                   |current| below REST_C_RATE of 1C
  rest_duration_min         minutes at rest so far (0 while active)
  ocv_rested_v              the measured average cell voltage once rested OCV_REST_MIN minutes (else empty)
"""
import math
import random
from typing import Optional

STEP_MIN = 5.0
REST_C_RATE = 0.02          # |I| below 2 % of 1C counts as rest
OCV_REST_MIN = 30.0         # rested long enough for the cell voltage to be an OCV reading
RECAL_REST_MIN = 120.0      # coulomb counter recalibrated to the BMS SOC after this much rest
OFFSET_LIMIT_A = 1.5
OFFSET_DRIFT_A_PER_DAY = 0.2
GAIN_NOISE = 0.002          # relative noise of the current reading
FIELDS = ["measured_current_a", "current_sensor_offset_a", "soc_coulomb_pct", "soc_battery_telemetry_pct",
          "usable_capacity_ah", "coulombic_efficiency", "at_rest", "rest_duration_min", "ocv_rested_v"]


def nominal_ah(rated_energy_kwh: Optional[float], nominal_voltage_v: Optional[float]) -> Optional[float]:
    if not rated_energy_kwh or not nominal_voltage_v:
        return None
    return float(rated_energy_kwh) * 1000.0 / float(nominal_voltage_v)


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class SocSignals:
    """Stateful per-unit generator: call step() with each reading in time order."""

    def __init__(self, nominal_capacity_ah: Optional[float], seed: Optional[int] = None, state: Optional[dict] = None):
        self.nominal_ah = nominal_capacity_ah
        self.rng = random.Random(seed)
        state = state or {}
        self.offset = _f(state.get("current_sensor_offset_a"))
        if self.offset is None:
            self.offset = self.rng.uniform(-0.5, 0.5)
        self.soc_coulomb = _f(state.get("soc_coulomb_pct"))
        self.rest_min = _f(state.get("rest_duration_min")) or 0.0
        self.prev_bms_soc = _f(state.get("soc_bms_pct"))

    @staticmethod
    def from_source(row: dict) -> Optional[dict]:
        """The source reading's own values when it already carries them (measured data is replayed, not invented)."""
        if row.get("soc_coulomb_pct") is None and row.get("measured_current_a") is None:
            return None
        return {k: row.get(k) for k in FIELDS}

    def step(self, row: dict, step_min: float = STEP_MIN) -> dict:
        """The nine signals for one reading. `row` keys: pack_current_a, soc_bms_pct, soh_pct, cell_temp_avg_c,
        cell_v_avg_v (missing values are tolerated)."""
        current = _f(row.get("pack_current_a")) or 0.0
        soc_bms = _f(row.get("soc_bms_pct"))
        soh = _f(row.get("soh_pct")) or 100.0
        temp = _f(row.get("cell_temp_avg_c"))
        cell_v = _f(row.get("cell_v_avg_v"))
        hours = step_min / 60.0

        cap = self.nominal_ah * soh / 100.0 if self.nominal_ah else None
        c1 = self.nominal_ah or 0.0
        eff = 0.9985 - (0.0004 * max((temp or 25.0) - 35.0, 0.0) / 5.0) - 0.002 * (100.0 - soh) / 30.0
        eff = min(max(eff + self.rng.gauss(0, 0.0002), 0.98), 1.0)

        # sensor: offset random walk (bounded) + gain noise on the true current
        self.offset += self.rng.gauss(0, OFFSET_DRIFT_A_PER_DAY * math.sqrt(step_min / 1440.0))
        self.offset = max(-OFFSET_LIMIT_A, min(OFFSET_LIMIT_A, self.offset))
        measured = current * (1 + self.rng.gauss(0, GAIN_NOISE)) + self.offset

        at_rest = abs(current) < REST_C_RATE * c1 if c1 else abs(current) < 1.0
        self.rest_min = self.rest_min + step_min if at_rest else 0.0

        # coulomb counting on the measured current; recalibrated to the BMS SOC after a long rest
        if self.soc_coulomb is None or (at_rest and self.rest_min >= RECAL_REST_MIN and soc_bms is not None):
            self.soc_coulomb = soc_bms
        elif cap:
            charge = measured * hours * (eff if measured > 0 else 1.0)
            self.soc_coulomb = min(100.0, max(0.0, self.soc_coulomb + 100.0 * charge / cap))

        telemetry_soc = self.prev_bms_soc if self.prev_bms_soc is not None else soc_bms
        self.prev_bms_soc = soc_bms
        return {
            "measured_current_a": round(measured, 2),
            "current_sensor_offset_a": round(self.offset, 3),
            "soc_coulomb_pct": round(self.soc_coulomb, 2) if self.soc_coulomb is not None else None,
            "soc_battery_telemetry_pct": round(telemetry_soc * 2) / 2 if telemetry_soc is not None else None,
            "usable_capacity_ah": round(cap, 1) if cap else None,
            "coulombic_efficiency": round(eff, 4),
            "at_rest": at_rest,
            "rest_duration_min": round(self.rest_min, 1),
            "ocv_rested_v": round(cell_v, 4) if at_rest and self.rest_min >= OCV_REST_MIN and cell_v is not None else None,
        }

    def state(self) -> dict:
        return {"current_sensor_offset_a": self.offset, "soc_coulomb_pct": self.soc_coulomb,
                "rest_duration_min": self.rest_min, "soc_bms_pct": self.prev_bms_soc}
