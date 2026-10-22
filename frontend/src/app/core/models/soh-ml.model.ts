export interface SohEstimateResponse {
  predicted_soh_pct: number;
  model_version: string;
  /** The run id the prediction came from. */
  model_key: string;
  run_id: number;
  /** Inputs outside the range seen in training. */
  out_of_range: { feature: string; value: number; min: number; max: number }[];
}

export interface FeatureRange {
  min: number | null;
  max: number | null;
  mean: number | null;
}

export interface SohModelInfo {
  model_version: string;
  trained_at: string;
  target: string;
  features: string[];
  feature_ranges: Record<string, FeatureRange>;
  feature_importances: Record<string, number>;
  metrics: Record<string, number>;
  caveat: string;
  /** The Model Training run the model comes from. */
  run_id: number;
  model_type?: string | null;
  grain?: string | null;
  feature_labels?: Record<string, string>;
  run_name?: string | null;
  /** Hyper-parameters the model was trained with. */
  params?: Record<string, number | boolean>;
  /** The data it was trained on (grain, dates, feature groups, split, rows, SOH range). */
  data_selection?: Record<string, unknown>;
  warnings?: string[];
  is_active?: boolean;
  /** Plant awareness: a base model, or a battery system (plant) model. */
  scope?: 'base' | 'system';
  site_name?: string | null;
  battery_system_id?: number | null;
  system_name?: string | null;
  training_mode?: 'scratch' | 'finetune';
  parent_run_id?: number | null;
  systems?: number[] | null;
  holdout_system_id?: number | null;
  metrics_by_system?: Record<string, { n: number; r2: number | null; rmse: number | null; mae: number | null }> | null;
  holdout_metrics?: { n: number; rmse: number | null; mae: number | null; system_name?: string } | null;
  /** Why "active" resolved to this run (system default, base default, latest base run). */
  chosen_as?: string | null;
}

/** A model the estimator can use (GET /models). */
export interface SohModelOption {
  key: string;
  run_id: number;
  label: string;
  run_name: string | null;
  model_type: string;
  grain: string;
  features: number;
  r2: number | null;
  rmse: number | null;
  mae: number | null;
  trained_at: string;
  /** Default of its scope (the base default, or its battery system's default). */
  is_active: boolean;
  scope: 'base' | 'system';
  battery_system_id: number | null;
  /** "base" or "Site · system". */
  scope_label: string;
  training_mode: 'scratch' | 'finetune';
  parent_run_id: number | null;
}

export interface SohModelList {
  /** The base default run (null = none set). */
  active_key: string | null;
  /** The chosen battery system's default run (null = none set). */
  system_active_key: string | null;
  /** What "active" resolves to: the system default, else the base default, else the latest base run. */
  default_key: string | null;
  default_reason: string | null;
  models: SohModelOption[];
}

export interface SohSampleReading {
  day: string;
  system_name: string | null;
  values: Record<string, number | null>;
  /** SOH recorded for that reading. */
  actual_soh_pct: number | null;
}

/** A battery system the estimator can read from (with its site and the span of its BMS telemetry). */
export interface SohSystemOption {
  site_id: number;
  site_name: string;
  battery_system_id: number;
  system_name: string;
  has_telemetry: boolean;
  first_ts: string | null;
  last_ts: string | null;
}

/** A battery system's mean of a model's features: over its rows in the training data, else its whole history. */
export interface SohSystemAverage {
  battery_system_id: number;
  system_name: string | null;
  values: Record<string, number | null>;
  rows: number;
  date_from: string | null;
  date_to: string | null;
  scope: 'training' | 'history';
  actual_soh_pct: number | null;
}

export interface SohFeatureField {
  key: string;
  label: string;
  unit: string;
  group: string;
  step: number | 'any';
}

/** Input group of a trained model's feature (Model Training feature groups). */
export function featureGroupOf(key: string): string {
  if (key.startsWith('mod_')) return 'Module envelope';
  if (key.startsWith('cell_v_')) return 'Cell voltage envelope';
  if (key.startsWith('cell_temp_')) return 'Cell temperature envelope';
  if (key.startsWith('imbalance_')) return 'Cell imbalance';
  if (key === 'equiv_full_cycles' || key === 'cycles_in_period') return 'Cycles';
  if (key.startsWith('cum_') || key.startsWith('throughput')) return 'Energy throughput';
  if (key === 'calendar_age_days') return 'Calendar age';
  return 'Other';
}
