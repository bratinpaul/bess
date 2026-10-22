/** Electricity-price forecasting use case of the ML service (/price-forecast). */

export type PfModelKey = 'seasonal_naive' | 'sarima' | 'lightgbm' | 'xgboost' | 'nbeats' | 'spike_hybrid';

export interface PfParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
  help?: string;
}

export interface PfModelSpec {
  key: PfModelKey;
  label: string;
  family: 'baseline' | 'primary' | 'deep' | 'spike';
  params: PfParamSpec[];
  always: boolean;
}

export interface PfUnit {
  ems_id: number;
  ems_code: string;
  battery_system_id: number | null;
  system_name: string | null;
  site_name: string | null;
  readings: number;
  priced: number;
  date_from: string | null;
  date_to: string | null;
  price_mean: number | null;
  price_max: number | null;
}

export interface PfBand {
  tariff_period_id: number;
  ems_id: number | null;
  band_code: string;
  band_name: string;
  price_level: string;
  start_hour: number;
  end_hour: number;
  day_type: string;
  season: string;
  reference_price_mwh: number | null;
}

export interface PfOptions {
  units: PfUnit[];
  feature_groups: { key: string; label: string; required: boolean; features: string[] }[];
  models: PfModelSpec[];
  tariff: PfBand[];
  external_drivers: string[];
  defaults: { horizon_hours: number; test_fraction: number; origin_step_h: number; train_origin_step_h: number; spike_threshold: number };
}

export interface PfSelection {
  ems_ids: number[];
  date_from: string | null;
  date_to: string | null;
  feature_groups: string[];
  spike_threshold: number;
}

export interface PfPreview {
  hours: number;
  spike_hours: number;
  units: { ems_id: number; hours: number; missing_hours?: number; from?: string; to?: string; spike_hours?: number; price_mean?: number; price_p95?: number }[];
}

export interface PfTrainRequest extends PfSelection {
  models: PfModelKey[];
  params: Record<string, Record<string, number>>;
  horizon_hours: number;
  test_fraction: number;
  origin_step_h: number;
  train_origin_step_h: number;
  random_state: number;
  run_name: string | null;
  make_default: boolean;
}

export interface PfScores {
  n: number;
  mae: number | null;
  rmse: number | null;
  smape_pct: number | null;
  bias: number | null;
  pinball: number | null;
  coverage_pct: number | null;
  width_mwh: number | null;
  skill_mae_pct: number | null;
  spike_hour_mae: number | null;
  spread_capture_pct: number | null;
  peak_mae?: number | null;
  mean_mae?: number | null;
  spike_brier?: number | null;
  spike_auc?: number | null;
  spike_recall?: number | null;
  spike_precision?: number | null;
}

export interface PfRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  ems_ids: number[];
  date_from: string | null;
  date_to: string | null;
  resolution: string;
  horizon_hours: number;
  test_fraction: number;
  origin_step_h: number;
  feature_groups: string[];
  models: PfModelKey[];
  params: Record<string, any>;
  n_hours: number | null;
  n_train_rows: number | null;
  n_test_origins: number | null;
  n_spikes: number | null;
  best_model: PfModelKey | null;
  metrics: Record<string, PfScores> | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface PfRunDetail extends PfRun {
  results: {
    features: string[];
    mae_by_horizon: Record<string, (number | null)[]>;
    mae_by_band: Record<string, Record<string, number | null>>;
    importance: Record<string, Record<string, number>>;
    timings_ms: Record<string, number>;
    bands: Record<string, PfBand[]>;
    codes: string[];
    split: Record<string, { train_to: string; test_from: string; test_to: string }>;
    nbeats_loss: number[] | null;
    train_spike_rows: number;
    test_spike_rows: number;
    spike_reference: { auc: number | null; brier: number | null; hour_rate: Record<string, number | null> } | null;
  } | null;
}

export interface PfModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  ems_ids: number[];
  models: PfModelKey[];
  best_model: PfModelKey | null;
  metrics: Record<string, PfScores> | null;
  horizon_hours: number;
  finished_at: string | null;
}

export interface PfForecastPoint {
  target_ts: string;
  horizon: number;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  mean: number | null;
  spike_prob: number | null;
}

export interface PfForecast {
  run_id: number;
  best_model: PfModelKey | null;
  ems_id: number;
  origin_ts: string;
  horizon: number;
  history: { ts: string; price: number | null; price_max5: number | null }[];
  history_5min: { ts: string; price: number }[];
  forecasts: Record<string, PfForecastPoint[]>;
  bands: PfBand[];
}

export interface PfBacktestPoint {
  model: PfModelKey;
  horizon_h: number;
  target_ts: string;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  mean: number | null;
  spike_prob: number | null;
  actual: number | null;
}

export interface PfBacktest {
  origin_ts: string;
  points: PfBacktestPoint[];
  history: { ts: string; price: number | null }[];
  history_5min: { ts: string; price: number }[];
}
