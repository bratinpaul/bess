/** Current-sensor calibrations (battery_master.current_sensor_cal) of the fleet systems. */

export interface CurrentSensorCalValues {
  offset_a: number | null;
  gain_error_pct: number | null;
  drift_a_per_day: number | null;
}

export interface CurrentSensorCal extends CurrentSensorCalValues {
  system_id: number;
  system_code: string | null;
  calibrated_on: string;
  /** Read-only: days to today (or to the system's next calibration) and the offset the drift projects to by then. */
  days_since: number | null;
  projected_offset_a: number | null;
  superseded_on: string | null;
}

export interface CalSystem {
  system_id: number;
  system_code: string;
  calibrations: number;
}
