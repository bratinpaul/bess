/** PCS conversion & round-trip efficiency use case of the ML service (/efficiency). */

export type EffModelKey = 'greybox' | 'gam' | 'hybrid';
export type EffBooster = 'lightgbm' | 'xgboost';
export type EffDirection = 'charge' | 'discharge';
export type GridService = 'NONE' | 'FREQ_WATT' | 'VOLT_VAR';

export interface EffParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float' | 'bool' | 'choice';
  default: number | boolean | string;
  min?: number;
  max?: number;
  step?: number;
  choices?: string[];
  help?: string;
}

export interface EffUnit {
  pcs_id: number;
  pcs_code: string;
  battery_system_id: number | null;
  system_name: string | null;
  site_name: string | null;
  manufacturer: string | null;
  model: string | null;
  topology: string | null;
  rated_power_kw: number | null;
  rated_kva: number | null;
  rated_ac_voltage_v: number | null;
  nominal_hz: number | null;
  v_dc_ref: number | null;
  dc_voltage_from: string;
  datasheet_eff_pct: number | null;
  commissioned_on: string | null;
  rated_energy_mwh: number | null;
}

export interface EffUnitCoverage extends EffUnit {
  readings: number;
  active: number;
  charging: number;
  discharging: number;
  date_from: string | null;
  date_to: string | null;
}

export interface EffFeatureSpec {
  key: string;
  label: string;
  unit: string;
  group: string;
}

export interface EffOptions {
  units: EffUnitCoverage[];
  feature_groups: { key: string; label: string; required: boolean; features: EffFeatureSpec[] }[];
  models: {
    greybox: { label: string; params: EffParamSpec[] };
    gam: { label: string; params: EffParamSpec[] };
    boosters: { key: EffBooster; label: string; params: EffParamSpec[] }[];
  };
  cycle_features: Record<string, string>;
  defaults: { min_load_frac: number; test_fraction: number; major_share: number; soc_tolerance_pct: number };
}

export interface EffSelection {
  pcs_ids: number[];
  date_from: string | null;
  date_to: string | null;
  min_load_frac: number;
  exclude_snapshots: boolean;
  feature_groups: string[];
}

export interface EffPreview {
  rows: number;
  charge?: number;
  discharge?: number;
  light_load?: number;
  eta_mean?: number;
  eta_std?: number;
  units: { pcs_id: number; rows: number; charge: number; discharge: number; from: string; to: string; eta_mean: number; eta_min: number }[];
}

export interface EffTrainRequest extends EffSelection {
  split_method: 'chronological' | 'random';
  test_fraction: number;
  random_state: number;
  greybox_params: Record<string, unknown>;
  gam_params: Record<string, unknown>;
  booster: EffBooster;
  booster_params: Record<string, unknown>;
  major_share: number;
  soc_tolerance_pct: number;
  run_name: string | null;
  make_default: boolean;
}

export interface EffScores {
  n: number;
  r2: number | null;
  mae: number | null;
  rmse: number | null;
  mape_pct: number | null;
  max_error: number | null;
  median_ae: number | null;
  loss_mae_kw?: number | null;
  bias_pp?: number | null;
  explained_variance?: number | null;
}

export type EffMetrics = Record<EffModelKey, { test: EffScores; train: EffScores }>;

export interface EffRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  pcs_ids: number[];
  date_from: string | null;
  date_to: string | null;
  split_method: string;
  test_fraction: number;
  min_load_frac: number;
  feature_groups: string[];
  features: string[] | null;
  booster: EffBooster;
  params: Record<string, any>;
  n_points: number | null;
  n_train: number | null;
  n_test: number | null;
  n_cycles: number | null;
  best_model: EffModelKey | null;
  metrics: EffMetrics | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface EffCurvePoint {
  load_frac: number;
  greybox: number;
  gam: number;
  hybrid: number;
}

export type EffCurves = Record<EffDirection, { observed: [number, number] | null; points: EffCurvePoint[] }>;

export interface EffTermCoef {
  value: number;
  per_10c: number | null;
  per_0p1_vdc: number | null;
}

export type EffDirectionCoefs = Record<string, { a: EffTermCoef; b: EffTermCoef; c: EffTermCoef }>;

export interface EffGreybox {
  reference: { igbt_temp_c: number; v_dc_pu: number; temp_step_c: number; volt_step_pu: number };
  current_basis: string;
  directions: EffDirectionCoefs;
  unit_offsets: Record<string, number>;
  reference_unit?: number;
  params: Record<string, unknown>;
}

export interface EffRte {
  n_cycles: number;
  n_closed?: number;
  rte_dc_pct?: EffStat;
  rte_ac_pct?: EffStat;
  rte_sys_pct?: EffStat;
  rte_ac_comp_pct?: EffStat;
  rte_sys_comp_pct?: EffStat;
  ac_composition_scores?: EffScores;
  sys_composition_scores?: EffScores;
  per_unit?: Record<string, EffUnitCycleStats>;
  dc_model?: EffDcModel;
}

export interface EffStat {
  mean: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
}

export interface EffUnitCycleStats {
  kwh_per_pct: number | null;
  aux_kw_avg: number | null;
  hvac_kw_avg: number | null;
  rte_dc_median: number | null;
  cycles: number;
}

export interface EffDcModel {
  features: string[];
  labels: Record<string, string>;
  medians: Record<string, number>;
  ranges: Record<string, { min: number; max: number }>;
  alpha: number;
  coef_std: Record<string, number>;
  coef_raw: Record<string, number>;
  intercept: number;
  scores_cv: EffScores;
  folds: number;
  n: number;
}

export interface EffPrediction {
  ts: string;
  pcs_id: number;
  load_frac: number;
  charge: boolean;
  actual: number;
  greybox: number;
  gam: number;
  hybrid: number;
  set: 'train' | 'test';
}

export interface EffRunDetail extends EffRun {
  results: {
    residual_features: string[];
    split: { train_from: string; train_to: string; test_from: string; test_to: string; eta_min: number; eta_max: number; eta_std: number };
    metrics_detail: {
      by_unit: Record<string, Record<EffModelKey, EffScores>>;
      by_direction: Record<string, Record<EffModelKey, EffScores>>;
      by_load_band: Record<string, Record<EffModelKey, EffScores>>;
    };
    greybox: EffGreybox;
    gam: { params: Record<string, unknown>; partial_dependence: Record<string, { x: number; y: number }[]> };
    shap: { share: Record<string, number>; mean_abs_pp: Record<string, number>; gain_share: Record<string, number>; n: number };
    health: {
      per_unit: Record<string, EffDirectionCoefs>;
      loss_index: { pcs_id: number; week: string; index: number; n: number; eta_mean: number }[];
    };
    curves: Record<string, EffCurves>;
    rte: EffRte;
    boost_curve: { iteration: number; train_rmse: number; valid_rmse: number }[];
  } | null;
  predictions: EffPrediction[] | null;
}

export interface EffCycle {
  run_id: number;
  cycle_no: number;
  pcs_id: number;
  battery_system_id: number | null;
  start_ts: string;
  end_ts: string;
  data_set: string | null;
  closed: boolean;
  complete: boolean;
  e_dc_in_kwh: number | null;
  e_dc_out_kwh: number | null;
  e_ac_in_kwh: number | null;
  e_ac_out_kwh: number | null;
  e_poi_in_kwh: number | null;
  e_poi_out_kwh: number | null;
  e_aux_kwh: number | null;
  e_hvac_kwh: number | null;
  soc_start_pct: number | null;
  soc_end_pct: number | null;
  depth_pct: number | null;
  rte_dc_pct: number | null;
  rte_ac_pct: number | null;
  rte_sys_pct: number | null;
  rte_dc_pred_pct: number | null;
  rte_ac_comp_pct: number | null;
  rte_sys_comp_pct: number | null;
  eta_chg_meas_pct: number | null;
  eta_dis_meas_pct: number | null;
  eta_chg_pred_pct: number | null;
  eta_dis_pred_pct: number | null;
  detail: Record<string, number | null>;
}

export interface EffScoreRow extends EffScores {
  run_id: number;
  model: string;
  dataset: string;
}

// ---------------------------------------------------------------- estimator

export interface EffModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  pcs_ids: number[];
  date_from: string | null;
  date_to: string | null;
  booster: EffBooster;
  best_model: EffModelKey | null;
  metrics: EffMetrics | null;
  n_points: number | null;
  n_cycles: number | null;
  finished_at: string | null;
}

export interface EffModelInfo {
  run: EffRun;
  features: string[];
  labels: Record<string, EffFeatureSpec>;
  units: (EffUnit & {
    typical: Record<EffDirection, Record<string, number>>;
    medians: Record<string, number>;
    cycle: EffUnitCycleStats | null;
  })[];
  ranges: Record<string, { min: number; max: number }>;
  curves: Record<string, EffCurves> | null;
  points: { pcs_id: number; load_frac: number; charge: boolean; actual: number; set: string }[];
  dc_rte_model: EffDcModel | null;
  rte: EffRte;
  greybox: EffGreybox | null;
}

export interface EffPointIn {
  pcs_id: number;
  direction: EffDirection;
  p_kw: number;
  power_factor: number;
  dc_voltage_v: number | null;
  igbt_temp_c: number | null;
  heatsink_temp_c: number | null;
  inlet_coolant_temp_c: number | null;
  ambient_temp_c: number | null;
  ac_voltage_v: number | null;
  ac_frequency_hz: number | null;
  grid_service: GridService;
  age_years: number | null;
}

export interface EffSample extends Omit<EffPointIn, 'age_years'> {
  ts: string;
  measured_eta_pct: number | null;
}

export interface EffPointResult {
  run_id: number;
  pcs_id: number;
  direction: EffDirection;
  load_frac: number;
  s_frac: number;
  models: Record<EffModelKey, { eta_pct: number; loss_kw: number; p_in_kw: number; p_out_kw: number }>;
  breakdown_kw: { constant: number; conduction: number; ohmic: number; residual: number };
  shap: { feature: string; label: string; value: number; pp: number; kw: number }[];
  shap_base_pp: number;
  inputs_used: Record<string, number>;
  curves: EffCurves;
  warnings: string[];
}

export interface EffCycleIn {
  pcs_id: number;
  charge_kw: number;
  discharge_kw: number;
  soc_min_pct: number;
  soc_max_pct: number;
  period_hours: number;
  kwh_per_pct: number | null;
  cell_temp_avg_c: number | null;
  fr_share: number;
  direction_changes: number;
  soh_pct: number | null;
  aux_kw: number | null;
  dc_rte_pct: number | null;
  power_factor: number;
  grid_service: GridService;
}

export interface EffCycleResult {
  run_id: number;
  pcs_id: number;
  kwh_per_pct: number;
  aux_kw: number;
  dc_rte_source: string;
  eta_charge_pct: number;
  eta_discharge_pct: number;
  hours: { charge: number; discharge: number; rest: number; period: number };
  energy_kwh: { poi_in: number; ac_in: number; dc_in: number; dc_out: number; ac_out: number; poi_out: number; aux: number; aux_during_discharge: number };
  losses_kwh: { pcs_charge: number; battery: number; pcs_discharge: number; auxiliaries: number };
  rte_pct: { pcs_conversion: number; dc: number; ac: number; system: number | null };
  warnings: string[];
}
