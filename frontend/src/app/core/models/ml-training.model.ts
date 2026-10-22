export type MlModelType = 'xgboost' | 'lightgbm';
export type MlGrain = '5min' | 'hour' | 'day';
export type MlSplit = 'chronological' | 'random';
/** base = plant-agnostic (several battery systems); system = one plant (site -> battery system). */
export type MlScope = 'base' | 'system';
export type MlTrainingMode = 'scratch' | 'finetune';

/** A battery system with the data it has (training page coverage). */
export interface MlSystemCoverage {
  site_id: number;
  site_name: string;
  battery_system_id: number;
  system_name: string;
  has_telemetry: boolean;
  rated_kwh: number | null;
  first_ts: string | null;
  last_ts: string | null;
  bms_days: number;
  soh_min: number | null;
  soh_max: number | null;
  module_from: string | null;
  module_to: string | null;
  module_days: number;
}

/** Test scores of a run on one battery system's rows (per plant, or the held-out plant). */
export interface MlSystemScores {
  n: number;
  r2: number | null;
  rmse: number | null;
  mae: number | null;
  mape_pct?: number | null;
  max_error?: number | null;
  actual_mean?: number;
  predicted_mean?: number;
  system_id?: number;
  system_name?: string;
  site_name?: string;
  from?: string;
  to?: string;
}

export interface MlParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float' | 'bool';
  default: number | boolean;
  min?: number;
  max?: number;
  step?: number;
  help?: string;
}

export interface MlTrainOptions {
  models: { key: MlModelType; label: string; params: MlParamSpec[] }[];
  feature_groups: { key: string; label: string; scopes: MlScope[]; features: { key: string; label: string }[] }[];
  grains: { key: MlGrain; label: string }[];
  coverage: { bms_from: string; bms_to: string; bms_days: number; module_days: string[]; snapshot_days: string[] };
  systems: MlSystemCoverage[];
  metrics: { key: MlMetricKey; label: string; better: 'higher' | 'lower' }[];
  feature_selection: {
    default_min_importance_pct: number;
    methods: { key: MlImportanceMethod; label: string; help: string }[];
  };
}

export type MlImportanceMethod = 'auto' | 'gain' | 'permutation';

export type MlMetricKey = 'r2' | 'rmse' | 'mae' | 'mape_pct' | 'max_error' | 'median_ae' | 'explained_variance';

export interface MlDataSelection {
  grain: MlGrain;
  date_from: string | null;
  date_to: string | null;
  feature_groups: string[];
  module_rows_only: boolean;
  include_snapshots: boolean;
  scope: MlScope;
  /** The plant of a battery system model. */
  battery_system_id: number | null;
  /** Base models: train on these battery systems (null = every system with data). */
  systems: number[] | null;
  /** Base models: leave this battery system out of training and score the model on it. */
  holdout_system_id: number | null;
}

export interface MlTrainRequest extends MlDataSelection {
  model_type: MlModelType;
  params: Record<string, number | boolean>;
  run_name: string | null;
  split_method: MlSplit;
  test_fraction: number;
  random_state: number;
  /** Keep only features with at least this share of the importance (0 = keep all). */
  min_importance_pct: number;
  importance_method: MlImportanceMethod;
  training_mode: MlTrainingMode;
  /** The base run a fine-tuned battery system model starts from. */
  parent_run_id: number | null;
}

export interface MlPreview {
  rows: number;
  systems?: number;
  from?: string;
  to?: string;
  days?: number;
  target_min?: number;
  target_max?: number;
  target_std?: number;
  module_rows?: number;
  missing_values?: number;
  by_system?: { system_id: number; rows: number; from: string; to: string; target_min: number; target_max: number; module_rows: number }[];
}

/** One row of battery_ml.model_run. */
export interface MlRun {
  run_id: number;
  run_name: string | null;
  model_type: MlModelType;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  params: Record<string, number | boolean>;
  grain: MlGrain;
  date_from: string | null;
  date_to: string | null;
  feature_groups: string[];
  features: string[];
  module_rows_only: boolean;
  include_snapshots: boolean;
  split_method: MlSplit;
  test_fraction: number;
  random_state: number;
  n_rows: number | null;
  n_train: number | null;
  n_test: number | null;
  train_from: string | null;
  train_to: string | null;
  test_from: string | null;
  test_to: string | null;
  target_min: number | null;
  target_max: number | null;
  target_std: number | null;
  r2: number | null;
  mae: number | null;
  rmse: number | null;
  mape_pct: number | null;
  max_error: number | null;
  median_ae: number | null;
  explained_variance: number | null;
  train_r2: number | null;
  train_mae: number | null;
  train_rmse: number | null;
  iterations: number | null;
  best_iteration: number | null;
  warnings: string[];
  error_message: string | null;
  is_active: boolean;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  /** `features` are the ones the model uses; these were offered by the chosen groups. */
  candidate_features: string[] | null;
  min_importance_pct: number;
  importance_method: 'gain' | 'permutation' | null;
  scope: MlScope;
  site_id: number | null;
  battery_system_id: number | null;
  training_mode: MlTrainingMode;
  parent_run_id: number | null;
  /** Battery systems the run trained on (null = every system: runs from before plant awareness). */
  systems: number[] | null;
  holdout_system_id: number | null;
  /** Test scores per battery system id. */
  metrics_by_system: Record<string, MlSystemScores> | null;
  holdout_metrics: MlSystemScores | null;
}

export interface MlRunDetail extends MlRun {
  feature_importance: Record<string, number> | null;
  feature_ranges: Record<string, { min: number | null; max: number | null; mean: number | null }> | null;
  predictions: { ts: string; actual: number; predicted: number; set: 'train' | 'test' }[] | null;
  /** Screening importance share of every candidate feature. */
  selection_importance: Record<string, number> | null;
  curve: { iteration: number; train_rmse: number; valid_rmse: number; train_mae: number; valid_mae: number }[];
}
