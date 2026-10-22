/** SOC estimation / correction use case of the ML service (/soc-estimation). */

export type SocEstMethod = 'coulomb' | 'ocv_lookup' | 'bms' | 'ekf' | 'gbm' | 'hybrid';
export type SocEstScope = 'anchors' | 'anchors_rest' | 'anchors_full' | 'dense' | 'dense_flat' | 'dense_active';
export type LabelSource = 'anchors' | 'dense';

export interface SocEstSystem {
  system_id: number;
  system_name: string;
  chemistry: string | null;
  site_name: string | null;
  rated_energy_mwh: number | null;
  readings: number;
  date_from: string | null;
  date_to: string | null;
  anchors: number;
  full_charge: number;
  rest_ocv: number;
  telemetry_to: string | null;
}

export interface SocEstParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
  help?: string;
}

export interface SocEstOptions {
  systems: SocEstSystem[];
  gbm_params: SocEstParamSpec[];
  ekf_params: SocEstParamSpec[];
  tune_grid: Record<string, number[]>;
  methods: Record<SocEstMethod, string>;
  scopes: Record<SocEstScope, string>;
  defaults: { test_fraction: number; label_source: LabelSource; tune_ekf: boolean; full_charge_reset: boolean };
}

export interface SocEstTrainRequest {
  system_ids: number[];
  date_from: string | null;
  date_to: string | null;
  test_fraction: number;
  label_source: LabelSource;
  tune_ekf: boolean;
  full_charge_reset: boolean;
  ekf_params: Record<string, number>;
  gbm_params: Record<string, number>;
  run_name: string | null;
  make_default: boolean;
}

export interface SocEstScore {
  n: number;
  rmse?: number | null;
  mae?: number | null;
  bias?: number | null;
  max_error?: number | null;
  p95_abs?: number | null;
  coverage_pct?: number | null;
  width?: number | null;
  skill_pct?: number | null;
}

export type SocEstMetrics = Record<SocEstMethod, Record<SocEstScope, SocEstScore>>;

export interface SocEstRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  system_ids: number[];
  date_from: string | null;
  date_to: string | null;
  test_fraction: number;
  label_source: LabelSource;
  params: any;
  n_train_rows: number | null;
  n_test_rows: number | null;
  n_test_anchors: number | null;
  best_method: SocEstMethod | null;
  primary_scope: SocEstScope | null;
  metrics: SocEstMetrics | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface SocEstSystemResult {
  name: string;
  params: Record<string, number | boolean>;
  tuning: { r_mv: number; q_bias: number; hysteresis: number; rmse: number | null }[];
  band_scale: number | null;
  end_bias_a: number | null;
  end_gain: number | null;
  train_end_bias_a: number | null;
  train_end_gain: number | null;
  ocv_updates: number;
  full_charge_resets: number;
  split: { train_from: string; test_from: string; to: string };
  dense_truth_rows: number;
}

export interface SocEstRunDetail extends SocEstRun {
  results: {
    ekf: Record<string, SocEstSystemResult>;
    importance: { gbm: Record<string, number>; hybrid: Record<string, number> };
    rmse_by_band: Partial<Record<SocEstMethod, (number | null)[]>>;
    band_edges: number[];
    max_error_by_day: Partial<Record<SocEstMethod, Record<string, number | null>>>;
    gbm_params_used: Record<string, number>;
  } | null;
}

export interface SocEstModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  system_ids: number[];
  label_source: LabelSource;
  best_method: SocEstMethod | null;
  primary_scope: SocEstScope | null;
  metrics: SocEstMetrics | null;
  finished_at: string | null;
}

export interface SocEstPoint {
  ts: string;
  is_test?: boolean;
  truth?: number | null;
  anchor: number | null;
  anchor_method: string | null;
  coulomb: number | null;
  ocv_lookup?: number | null;
  ocv_soc?: number | null;
  bms: number | null;
  ekf: number | null;
  ekf_p10: number | null;
  ekf_p90: number | null;
  gbm: number | null;
  gbm_p10?: number | null;
  gbm_p90?: number | null;
  hybrid: number | null;
  hybrid_p10: number | null;
  hybrid_p90: number | null;
  ekf_bias: number | null;
  ekf_gain: number | null;
  recal_kind: string | null;
  at_rest: boolean | null;
  min_since_recal?: number | null;
}

export interface SocEstFlags {
  stale: boolean;
  stale_minutes: number | null;
  behind_telemetry: boolean;
  telemetry_to: string | null;
  no_anchor: boolean;
  hours_since_recal: number | null;
  anchors_total: number;
}

export interface SocEstState {
  soc: number;
  bias: number;
  gain: number;
  P: number[][];
  direction: string;
  ts: string | null;
  last_recal_ts: string | null;
  last_ocv_ts: string | null;
}

/** The I/O contract record. */
export interface SocEstOutput {
  run_id: number;
  system_id: number;
  ts: string;
  soc_corrected_pct: number | null;
  p10: number | null;
  p90: number | null;
  drift_correction_pct: number | null;
  recalibrated: boolean;
  recal_kind: string | null;
  soc_coulomb_pct: number | null;
  soc_bms_pct: number | null;
  ekf: { soc: number | null; p10: number | null; p90: number | null; bias_a: number | null; gain: number | null; direction: string; innovation_mv: number | null };
  ocv_soc: number | null;
  min_since_recal: number | null;
  last_recal_ts: string | null;
  state: SocEstState;
  messages: string[];
}

export interface SocEstimate extends SocEstOutput {
  mode: 'live' | 'replay';
  flags: SocEstFlags;
  inputs: Record<string, number | boolean | null>;
  params: Record<string, number | boolean>;
  band_scale: number;
  trajectory: SocEstPoint[];
}

export interface SocStepRequest {
  system_id: number;
  ts: string | null;
  dt_min: number;
  state: { soc: number; bias: number; gain: number; sigma_soc: number; direction: string; last_recal_ts: string | null };
  features: Record<string, number | boolean | null>;
  anchor_soc_pct: number | null;
  anchor_method: 'FULL_CHARGE' | 'REST_OCV' | null;
}

export interface SocStepResult extends SocEstOutput {
  sigma_soc: number | null;
}
