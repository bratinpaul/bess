/** Auxiliary / HVAC energy forecasting use case of the ML service (/aux-forecast). */

export type AuxMethod = 'persistence' | 'seasonal' | 'greybox' | 'hybrid';
export type AuxPlanSource = 'scheduled' | 'typical';
export type AuxAmbientSource = 'forecast' | 'profile' | 'actual';

export interface AuxParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
}

export interface AuxSite {
  ems_id: number;
  ems_code: string | null;
  battery_system_id: number;
  system_name: string | null;
  site_id: number | null;
  site_name: string | null;
  rated_power_mw: number | null;
  rated_energy_mwh: number | null;
  pcs_rated_kw: number | null;
  station_id: number | null;
  wx_forecast_rows: number;
  readings: number;
  date_from: string | null;
  date_to: string | null;
}

export interface AuxOptions {
  sites: AuxSite[];
  methods: Record<AuxMethod, string>;
  buckets: string[];
  report_horizons: number[];
  gbm_params: AuxParamSpec[];
  defaults: {
    horizon_hours: number;
    test_fraction: number;
    train_origin_step: number;
    steps_per_origin: number;
    plan_source: AuxPlanSource;
    ambient_source: AuxAmbientSource;
  };
}

export interface AuxTrainRequest {
  ems_ids: number[];
  date_from: string | null;
  date_to: string | null;
  horizon_hours: number;
  plan_source: AuxPlanSource;
  ambient_source: AuxAmbientSource;
  test_fraction: number;
  train_origin_step: number;
  steps_per_origin: number;
  gbm_params: Record<string, number>;
  run_name: string | null;
  make_default: boolean;
}

export interface AuxScores {
  n: number;
  mae?: number | null;
  rmse?: number | null;
  bias?: number | null;
  pinball?: number | null;
  coverage_pct?: number | null;
}

/** metrics[ems_id | 'all'][bucket | 'all'][method] */
export type AuxMetrics = Record<string, Record<string, Record<AuxMethod, AuxScores>>>;

export interface AuxDailyScore {
  days: number;
  mae_kwh: number | null;
  mape_pct: number | null;
  bias_kwh: number | null;
  actual_kwh_avg: number | null;
  coverage_pct: number | null;
}

export interface AuxGreybox {
  controls_base_kw: number;
  decomposed: boolean;
  heat_h0_kw: number;
  heat_h1_kw_per_kw: number;
  cop_c0: number;
  cop_c1_per_c: number;
  t_balance_c: number;
  p0: number;
  k_q: number;
  k_e: number;
  k_s: number;
  r2: number | null;
  mae_kw: number | null;
}

export interface AuxRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  ems_ids: number[];
  date_from: string | null;
  date_to: string | null;
  horizon_hours: number;
  test_fraction: number;
  params: Record<string, any>;
  n_train_rows: number | null;
  n_test_rows: number | null;
  metrics: AuxMetrics | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface AuxRunDetail extends AuxRun {
  results: {
    importance: Record<string, number>;
    greybox: Record<string, AuxGreybox>;
    split: Record<string, { site_name: string; train_from: string; test_from: string; to: string }>;
    /** daily[ems_id | 'all'][method] (or { note } without a 24 h horizon) */
    daily: Record<string, Record<AuxMethod, AuxDailyScore>> & { note?: string };
    summary: {
      mae: Record<AuxMethod, number | null>;
      pinball: Record<AuxMethod, number | null>;
      coverage_pct: Record<AuxMethod, number | null>;
      skill_vs_seasonal_pct: Record<AuxMethod, number | null>;
      daily_mae_kwh?: Record<AuxMethod, number | null>;
      daily_mape_pct?: Record<AuxMethod, number | null>;
    };
  } | null;
}

export interface AuxModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  ems_ids: number[];
  horizon_hours: number;
  metrics: AuxMetrics | null;
  finished_at: string | null;
}

export interface AuxForecastRow {
  ts_target: string;
  horizon_min: number;
  aux_kw_p50: number | null;
  aux_kw_p10: number | null;
  aux_kw_p90: number | null;
  hvac_kw_p50?: number | null;
  controls_kw?: number | null;
  aux_energy_kwh: number | null;
  greybox_kw?: number | null;
  seasonal_kw?: number | null;
  ambient_fc_c?: number | null;
  ambient_from_forecast?: boolean;
  plan_kw?: number | null;
  actual_kw?: number | null;
}

export interface AuxDay {
  day: string;
  intervals: number;
  hours: number;
  aux_energy_kwh_p50: number;
  aux_energy_kwh_p10: number;
  aux_energy_kwh_p90: number;
  actual_kwh: number | null;
  actual_intervals: number;
}

export interface AuxPoint {
  ts: string;
  v: number | null;
}

export interface AuxPrediction {
  run_id: number;
  ems_id: number;
  site_name: string | null;
  origin_ts: string;
  horizon_hours: number;
  plan_source: AuxPlanSource;
  ambient_source: AuxAmbientSource;
  data_age_min: number | null;
  flags: { stale: boolean; stale_min: number; too_old: boolean; missing_inputs: string[] };
  greybox: AuxGreybox;
  forecasts: AuxForecastRow[];
  daily: AuxDay[];
  history: { aux_load_kw: AuxPoint[]; hvac_power_kw: AuxPoint[]; ambient_temp_c: AuxPoint[] };
}

export interface AuxBacktestPoint {
  method: AuxMethod;
  target_ts: string;
  horizon_min?: number;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  actual: number | null;
}

export interface AuxDailyRow {
  ems_id: number;
  day: string;
  method: AuxMethod;
  actual_kwh: number | null;
  p10_kwh: number | null;
  p50_kwh: number | null;
  p90_kwh: number | null;
}
