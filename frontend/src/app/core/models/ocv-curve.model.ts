/** OCV curves (battery_master.ocv_curve): per-cell open-circuit voltage vs SOC. */

export type OcvDirection = 'CHARGE' | 'DISCHARGE' | 'MEAN';

export interface OcvPoint {
  chemistry: string;
  direction: OcvDirection;
  temp_c: number;
  soc_pct: number;
  ocv_v: number;
}

export interface OcvCurveSummary {
  chemistry: string;
  direction: OcvDirection;
  temp_c: number;
  points: number;
  soc_min: number | null;
  soc_max: number | null;
  ocv_min: number | null;
  ocv_max: number | null;
  monotonic: boolean;
  soc: number[];
  ocv: number[];
}

export interface OcvOptions {
  chemistries: string[];
  temperatures: number[];
  directions: OcvDirection[];
}
