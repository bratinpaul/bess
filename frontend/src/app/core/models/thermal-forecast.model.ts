/** Temperature forecasting use case of the ML service (/thermal-forecast). */

export type ThermalTarget = 'cell_temp_max_c' | 'coolant_return_temp_c' | 'igbt_temp_c' | 'enclosure_temp_c';
export type ThermalMethod = 'persistence' | 'seasonal' | 'rc' | 'hybrid';

export interface ThermalParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
}

export interface ThermalTargetSpec {
  key: ThermalTarget;
  label: string;
  family: string;
  asset: string;
  asset_type: string;
  ref: string;
  drivers: string[];
  threshold: number;
  alarm_code: string | null;
}

export interface ThermalSystem {
  battery_system_id: number;
  system_name: string | null;
  site_name: string | null;
  pcs_id: number | null;
  hvac_id: number | null;
  ems_id: number | null;
  readings: number;
  date_from: string | null;
  date_to: string | null;
}

export interface ThermalOptions {
  systems: ThermalSystem[];
  targets: ThermalTargetSpec[];
  families: Record<string, string>;
  methods: Record<ThermalMethod, string>;
  catalog_thresholds: Record<string, number | null>;
  gbm_params: ThermalParamSpec[];
  defaults: { horizons_min: number[]; test_fraction: number; train_origin_step: number; plan_source: string };
}

export interface ThermalTrainRequest {
  system_ids: number[];
  date_from: string | null;
  date_to: string | null;
  targets: ThermalTarget[];
  horizons_min: number[];
  thresholds: Record<string, number>;
  plan_source: 'scheduled' | 'typical';
  test_fraction: number;
  train_origin_step: number;
  gbm_params: Record<string, number>;
  run_name: string | null;
  make_default: boolean;
}

export interface ThermalScores {
  n: number;
  mae?: number | null;
  rmse?: number | null;
  pinball?: number | null;
  coverage_pct?: number | null;
  threshold_c?: number;
  events?: number;
  recall_p50?: number | null;
  precision_p50?: number | null;
  recall_p90?: number | null;
  precision_p90?: number | null;
}

/** metrics[target][horizon][method] */
export type ThermalMetrics = Record<string, Record<string, Record<ThermalMethod, ThermalScores>>>;

export interface ThermalRc {
  drivers: string[];
  coef: Record<string, number>;
  alpha: number;
  tau_min: number;
  r2_steady: number | null;
}

export interface ThermalRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  system_ids: number[];
  date_from: string | null;
  date_to: string | null;
  targets: ThermalTarget[];
  horizons_min: number[];
  test_fraction: number;
  params: Record<string, any>;
  n_train_rows: number | null;
  n_test_rows: number | null;
  metrics: ThermalMetrics | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface ThermalRunDetail extends ThermalRun {
  results: {
    importance: Record<string, Record<string, number>>;
    thresholds: Record<string, number>;
    catalog_thresholds: Record<string, number | null>;
    rc: Record<string, Record<string, ThermalRc>>;
    split: Record<string, { test_from: string; to: string }>;
    summary: Record<string, { horizon_min: number; mae: Record<ThermalMethod, number | null>; events: number; recall_p90: number | null; recall_p50: number | null }>;
  } | null;
}

export interface ThermalModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  system_ids: number[];
  targets: ThermalTarget[];
  horizons_min: number[];
  metrics: ThermalMetrics | null;
  finished_at: string | null;
}

export interface ThermalForecastRow {
  target: ThermalTarget;
  asset_type: string;
  asset_id: number | null;
  horizon_min: number;
  pred_c: number | null;
  p10_c: number | null;
  p90_c: number | null;
  rc_c?: number | null;
  now_c?: number | null;
  threshold_c?: number | null;
  flag: string | null;
}

export interface ThermalPrediction {
  run_id: number;
  system_id: number;
  origin_ts: string;
  plan_source: string;
  data_age_min: number | null;
  forecasts: ThermalForecastRow[];
  flags: Record<string, { stale_min: number; stale: boolean; missing_inputs: string[] }>;
  history: Record<string, { ts: string; v: number | null }[]>;
  ambient: { ts: string; v: number | null }[];
  plan_kw: (number | null)[];
  plan_times: string[];
}

export interface ThermalSeriesPoint {
  method: ThermalMethod;
  target_ts: string;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  actual: number | null;
  now_c: number | null;
}
