/** Remaining Useful Life use case of the ML service (/rul). */

export type RulMethod = 'physics' | 'gbm' | 'hybrid' | 'cox' | 'rsf';

export interface RulParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
}

export interface RulSystem {
  system_id: number;
  system_code: string;
  chemistry: string | null;
  batch_lot: string | null;
  usage_cycles_per_day: number | null;
  climate_avg_temp_c: number | null;
  snapshots: number;
  first_date: string | null;
  last_date: string | null;
  retired: boolean;
  rpt_tests: number;
  end_events: string | null;
}

export interface RulEol {
  soh_eol_pct: number;
  resistance_eol_pct: number | null;
  description?: string | null;
}

export interface RulOptions {
  systems: RulSystem[];
  eol_criteria: Record<string, RulEol>;
  methods: Record<RulMethod, string>;
  feature_groups: Record<string, { label: string; columns: string[] }>;
  physics_params: RulParamSpec[];
  gbm_params: RulParamSpec[];
  survival_params: RulParamSpec[];
  life_buckets: string[];
  cox_features: string[];
}

export interface RulTrainRequest {
  system_ids: number[] | null;
  methods: RulMethod[];
  feature_groups: string[];
  failures_as: 'event' | 'censored';
  arrhenius: boolean;
  knee: boolean;
  calibrate_bands: boolean;
  physics: Record<string, number>;
  gbm: Record<string, number>;
  survival: Record<string, number>;
  run_name: string | null;
  make_default: boolean;
}

export interface RulScores {
  n: number;
  mae_days?: number | null;
  rmse_days?: number | null;
  bias_days?: number | null;
  mae_cycles?: number | null;
  coverage_pct?: number | null;
  pinball_days?: number | null;
  c_index?: number | null;
  censored_violation_pct?: number | null;
  oracle_mae_days?: number | null;
}

/** metrics[method][scope] - scope 'all', 'life:<bucket>', 'unit:<code>' */
export type RulMetrics = Record<string, Record<string, RulScores>>;

export interface RulCurve {
  offset: number;
  a: number;
  b: number;
  z: number;
  ea_kj_mol: number;
  r2: number | null;
  rmse: number | null;
}

export interface RulPhysicsParams {
  chemistry: string;
  soh_eol_pct: number;
  resistance_eol_ratio: number | null;
  capacity: RulCurve;
  resistance: RulCurve | null;
  batch_capacity_factor: Record<string, number>;
  batch_resistance_factor: Record<string, number>;
  unit_spread_capacity: number;
  unit_spread_resistance: number;
  kappa: number;
  rpt_weight: number;
  knee_bands: string[];
  knee_capacity: number[];
  knee_resistance: number[];
}

export interface RulChemParams {
  physics: RulPhysicsParams | null;
  band_log_q10_q90: [number, number];
  cox: Record<string, { coef: number; hazard_ratio_per_sd: number }> | null;
  rsf_importance: Record<string, number> | null;
  gbm_importance: Record<string, number> | null;
  hybrid_importance: Record<string, number> | null;
  eol: RulEol;
  units: number;
  retired_units: number;
  survival_cap_days: number;
}

export interface RulUnitInfo {
  system_id: number;
  system_code: string;
  chemistry: string;
  batch_lot: string;
  retired: boolean;
  failed: boolean;
  event_unit: boolean;
  snapshots: number;
  first_date: string;
  last_date: string;
}

export interface RulRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  system_ids: number[];
  methods: RulMethod[];
  params: Record<string, any>;
  n_units: number | null;
  n_rows: number | null;
  metrics: RulMetrics | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RulRunDetail extends RulRun {
  results: {
    params: Record<string, RulChemParams>;
    summary: Record<string, Record<RulMethod, number | null>>;
    features: string[];
    units: RulUnitInfo[];
  } | null;
}

export interface RulModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  methods: RulMethod[];
  n_units: number | null;
  metrics: RulMetrics | null;
  finished_at: string | null;
}

export interface RulForecastRow {
  run_id: number;
  system_id: number;
  system_code: string;
  method: RulMethod;
  as_of: string;
  soh_pct: number | null;
  resistance_ratio: number | null;
  p10_days: number | null;
  p50_days: number | null;
  p90_days: number | null;
  p10_cycles: number | null;
  p50_cycles: number | null;
  p90_cycles: number | null;
  eol_date_p50: string | null;
  trigger: string | null;
  beyond: boolean;
}

export interface RulBacktestPoint {
  system_id: number;
  snapshot_date: string;
  method: RulMethod;
  p10_days: number | null;
  p50_days: number | null;
  p90_days: number | null;
  p50_cycles: number | null;
  beyond: boolean;
  actual_days: number | null;
  actual_cycles: number | null;
  known_alive_days: number | null;
  censored: boolean;
}

export interface RulMethodResult {
  p10_days: number | null;
  p50_days: number | null;
  p90_days: number | null;
  p10_cycles: number | null;
  p50_cycles: number | null;
  p90_cycles: number | null;
  eol_date_p50: string;
  beyond: boolean;
  trigger: string;
  survival?: { days: number; s: number }[];
}

export interface RulPrediction {
  run_id: number;
  system_id: number;
  system_code: string;
  chemistry: string;
  batch_lot: string;
  retired: boolean;
  failed: boolean;
  as_of: string;
  state: {
    age_days: number | null;
    efc: number | null;
    soh_pct: number | null;
    r_ratio: number | null;
    cpd: number | null;
    temp: number | null;
    cpd_actual: number | null;
    temp_actual: number | null;
  };
  eol: RulEol;
  methods: Partial<Record<RulMethod, RulMethodResult>>;
  paths: {
    days: number[];
    soh_p10: number[];
    soh_p50: number[];
    soh_p90: number[];
    r_p10?: number[];
    r_p50?: number[];
    r_p90?: number[];
    factor_capacity: number;
    factor_resistance: number;
  } | null;
  history: { date: string; age_days: number | null; soh_pct: number | null; r_ratio: number | null; efc: number | null }[];
  rpt: { date: string; age_days: number | null; soh_pct: number | null; r_ratio: number | null }[];
}
