export type NfModelKey = 'seasonal_naive' | 'sarima' | 'lightgbm' | 'nbeats' | 'peak_classifier';
export type NfRegressorKey = Exclude<NfModelKey, 'peak_classifier'>;

export interface NfUnit {
  mp_id: number;
  mp_code: string;
  mp_type: string | null;
  voltage_kv: number | null;
  site_id: number | null;
  site_name: string | null;
  station_id: number | null;
  station_code: string | null;
  readings: number;
  date_from: string | null;
  date_to: string | null;
  net_mean: number | null;
  net_max: number | null;
  wx_fc_values: number;
  wx_fc_runs: number;
}

export interface NfTariff {
  tariff_id: number;
  name: string;
  demand_charge_per_kw: number | null;
  peak_window_start: number | null;
  peak_window_end: number | null;
  measurement_minutes: number | null;
  ratchet_pct: number | null;
  valid_from: string | null;
}

export interface NfParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
  help?: string;
}

export interface NfModelSpec {
  key: NfModelKey;
  label: string;
  family: 'baseline' | 'primary' | 'deep' | 'peak';
  params: NfParamSpec[];
  always: boolean;
}

export interface NfOptions {
  units: NfUnit[];
  tariffs: Record<string, NfTariff | null>;
  feature_groups: { key: string; label: string; required: boolean; features: string[] }[];
  models: NfModelSpec[];
  defaults: { horizon_hours: number; test_fraction: number; origin_step_h: number; train_origin_step_h: number; weather_source: string };
}

export interface NfSelection {
  mp_ids: number[];
  date_from: string | null;
  date_to: string | null;
  feature_groups: string[];
  weather_source: 'forecast' | 'actual';
  peak_threshold_kw: number | null;
}

export interface NfTrainRequest extends NfSelection {
  models: NfModelKey[];
  params: Record<string, Record<string, number>>;
  horizon_hours: number;
  test_fraction: number;
  origin_step_h: number;
  train_origin_step_h: number;
  random_state: number;
  run_name: string | null;
  make_default: boolean;
}

export interface NfDayPeak {
  date: string;
  peak: number | null;
  peak_ts: string;
  workday?: boolean;
}

export interface NfPreviewUnit {
  mp_id: number;
  readings: number;
  missing?: number;
  days?: number;
  from?: string;
  to?: string;
  workdays?: number;
  holidays?: number;
  calendar_missing?: number;
  weather_actual_share?: number | null;
  weather_runs?: number;
  window?: number[];
  peaks?: NfDayPeak[];
  peak_p75?: number | null;
}

export interface NfScores {
  n?: number;
  mae?: number | null;
  rmse?: number | null;
  mape_pct?: number | null;
  bias?: number | null;
  pinball?: number | null;
  coverage_pct?: number | null;
  width_kw?: number | null;
  skill_mae_pct?: number | null;
  window_mae?: number | null;
  peak_n?: number;
  peak_mae_kw?: number | null;
  peak_bias_kw?: number | null;
  peak_time_mae_min?: number | null;
  exceed_brier?: number | null;
  exceed_auc?: number | null;
  exceed_recall?: number | null;
  exceed_precision?: number | null;
}

export interface NfRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  mp_ids: number[];
  date_from: string | null;
  date_to: string | null;
  horizon_hours: number;
  test_fraction: number;
  origin_step_h: number;
  feature_groups: string[];
  weather_source: 'forecast' | 'actual';
  peak_threshold_kw: number | null;
  models: NfModelKey[];
  params: Record<string, any>;
  n_readings: number | null;
  n_train_rows: number | null;
  n_test_origins: number | null;
  n_test_days: number | null;
  best_model: NfRegressorKey | null;
  metrics: Partial<Record<NfModelKey, NfScores>> | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface NfPeakCal {
  n: number;
  days?: number;
  median?: number;
  q10?: number;
  q90?: number;
}

export interface NfResults {
  mae_by_lead: Partial<Record<NfModelKey, (number | null)[]>>;
  mae_by_hour: Partial<Record<NfModelKey, (number | null)[]>>;
  importance: Partial<Record<NfModelKey, Record<string, number>>>;
  timings_ms: Partial<Record<NfModelKey, number>>;
  threshold: { kw: number; auto_kw: number | null; given: boolean; test_days: number; test_days_above: number };
  window: number[];
  tariff: Record<string, NfTariff | null>;
  demand_charge_per_kw: number | null;
  pv_ratio: Record<string, number | null>;
  split: Record<string, { train_to: string; test_from: string; test_to: string }>;
  nbeats_loss: number[] | null;
  classifier: {
    reference: NfScores | null;
    coefficients: Record<string, number>;
    class_rate: Record<string, number | null>;
    train_days: number;
  } | null;
  peak_calibration: Partial<Record<NfModelKey, NfPeakCal>>;
  weather_share: number | null;
  features: string[];
}

export interface NfRunDetail extends NfRun {
  results: NfResults | null;
}

export interface NfModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  mp_ids: number[];
  models: NfModelKey[];
  best_model: NfRegressorKey | null;
  metrics: Partial<Record<NfModelKey, NfScores>> | null;
  horizon_hours: number;
  peak_threshold_kw: number | null;
  weather_source: string;
  finished_at: string | null;
}

export interface NfPathPoint {
  target_ts: string;
  step: number;
  p10: number | null;
  p50: number | null;
  p90: number | null;
}

export interface NfPeak {
  target_date: string;
  lead_h: number | null;
  p10?: number | null;
  p50?: number | null;
  p90?: number | null;
  p50_raw?: number | null;
  peak_ts?: string | null;
  prob_exceed: number | null;
  reference?: number | null;
  actual?: number | null;
  actual_ts?: string | null;
  model?: NfModelKey;
  origin_ts?: string;
}

export interface NfHistoryPoint {
  ts: string;
  net: number | null;
  gross: number | null;
  gen: number | null;
}

export interface NfForecast {
  run_id: number;
  best_model: NfRegressorKey | null;
  has_classifier: boolean;
  mp_id: number;
  mp_code: string;
  origin_ts: string;
  horizon_hours: number;
  threshold_kw: number;
  trained_threshold_kw: number;
  window: number[];
  tariff: NfTariff | null;
  history: NfHistoryPoint[];
  inputs: { ts: string; temp_fc: number | null; ghi_fc: number | null; from_forecast: boolean; workday: boolean }[];
  calendar_missing: string[];
  recent_peaks: NfDayPeak[];
  forecasts: Partial<Record<NfRegressorKey, NfPathPoint[]>>;
  peaks: Partial<Record<NfModelKey, NfPeak[]>>;
  data_age_hours: number | null;
}

export interface NfBacktest {
  origin_ts: string;
  points: (NfPathPoint & { model: NfRegressorKey; actual: number | null })[];
  peaks: (NfPeak & { model: NfModelKey; threshold_kw: number })[];
  history: NfHistoryPoint[];
}
