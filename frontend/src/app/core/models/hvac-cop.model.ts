/** HVAC COP & cooling-performance modeling (ML service /hvac-cop). */

export interface CopUnitOption {
  hvac_id: number;
  hvac_code: string;
  system_id: number | null;
  system_name: string | null;
  site_name: string | null;
  rated_kw: number | null;
  model: string | null;
  intervals: number;
  cooling_intervals: number;
  first_day: string;
  last_day: string;
}

export interface CopRunRequest {
  hvac_ids: number[];
  date_from: string;
  date_to: string;
  run_name: string | null;
  cop_definition: 'logged' | 'ratio' | 'loop';
  capacity_definition: 'logged' | 'loop';
  lift_source: 'temperature' | 'pressure';
  evap_approach_k: number;
  cond_approach_k: number;
  fluid_density_kg_l: number;
  fluid_cp_kj_kgk: number;
  min_speed_pct: number;
  min_power_kw: number;
  max_dt_step_k: number;
  train_frac: number;
  expected_model: 'map' | 'grey' | 'hybrid';
  n_estimators: number;
  learning_rate: number;
  num_leaves: number;
  ref_ambient_c: number;
  ref_supply_c: number;
  ref_plr: number;
  rated_capacity_kw: number | null;
  ewma_lambda: number;
  ewma_l: number;
  cusum_k: number;
  cusum_h: number;
}

export interface CopOptions {
  units: CopUnitOption[];
  defaults: CopRunRequest;
  cop_definitions: { key: string; label: string }[];
  capacity_definitions: { key: string; label: string }[];
}

export interface CopScore {
  n: number;
  r2?: number | null;
  mae?: number;
  rmse?: number;
  mape_pct?: number;
  bias?: number;
}

export interface CopDay {
  day: string;
  is_train: boolean;
  cooling_h: number;
  steady_n: number;
  weighted_cop: number | null;
  kw_per_ton: number | null;
  cop_mean: number | null;
  cop_expected_mean: number | null;
  residual_mean: number | null;
  eta_2nd_law: number | null;
  cop_normalized: number | null;
  capacity_ratio: number | null;
  ambient_max_c: number;
  ambient_mean_c: number;
  filter_dp_pa: number;
  discharge_excess_bar: number | null;
  fan_saturated_share: number | null;
  hvac_kwh: number;
  cooling_kwh: number;
  control: { ewma: number; lcl: number; ucl: number; center: number; sigma: number; cusum_neg: number; ewma_alarm: boolean;
    cusum_alarm: boolean; status: string } | null;
}

export interface CopUnitSummary {
  hvac_id: number;
  hvac_code: string;
  system_id: number | null;
  system_name: string | null;
  site_name: string | null;
  model: string | null;
  rated_capacity_kw: number | null;
  cop_definition: string;
  capacity_definition: string;
  scores: Record<'map' | 'grey' | 'hybrid' | 'constant' | 'capacity_map' | 'power', { train?: CopScore; test: CopScore }>;
  closure: Record<string, number | null>;
  scorecard: {
    seasonal_cop_cooling: number | null;
    seasonal_cop_all_modes: number | null;
    cooling_mwh: number;
    hvac_mwh: number;
    hvac_cooling_mwh: number;
    cum_energy_counter_mwh: number;
    logged_cop_mean: number | null;
    kw_per_ton: number | null;
    iplv_style: number;
    rating_cop: Record<string, number>;
    rating_condition: { ambient_c: number; supply_c: number };
    observed_part_load_index: number;
    part_load_bins: { bin: string; share: number; cop: number | null }[];
    capacity_ratio: number | null;
    rated_capacity_kw: number | null;
    eta_2nd_law_mean: number | null;
    eta_2nd_law_p10_p90: number[] | null;
    latent_share_of_cooling: number;
    humid_share: number;
  };
  cycling: { starts: number; starts_per_day: number; mean_run_min: number | null; short_cycles: number; runtime_h_per_day: number;
    cooling_hours_per_day: number; modes: Record<string, number> };
  sensitivities: {
    at: { ambient_c: number; supply_c: number; plr: number };
    cop_at_median: number;
    per_setpoint_plus_1c: number;
    per_setpoint_plus_1c_pct: number;
    per_ambient_minus_1c: number;
    per_ambient_minus_1c_pct: number;
    per_plr_minus_10pct: number;
    grey_cop_at_median: number;
    grey_per_setpoint_plus_1c_pct: number;
    grey_per_ambient_minus_1c_pct: number;
    hourly: { hour: number; ambient_c: number; cop_expected_at_median_load: number; cop_actual_mean: number | null; steady_n: number }[];
    best_hours: number[];
  };
  map_grid: { ambient_c: number[]; supply_c: number; cop: Record<string, number[]>; cap: Record<string, number[]>;
    plr_curve: { plr: number[]; f: number[] } };
  shape: { night_cop: number | null; afternoon_cop: number | null; full_load_cop: number | null; part_load_cop: number | null };
  daily: CopDay[];
  alarm_days: string[];
  train_to: string;
  test_from: string;
  steady_n: number;
  cooling_n: number;
  scatter: { amb: number; cop: number; plr: number; exp: number | null }[];
}

export interface CopFleetRow {
  hvac_id: number;
  hvac_code: string;
  system_name: string | null;
  site_name: string | null;
  seasonal_cop: number | null;
  seasonal_cop_all: number | null;
  logged_cop_mean: number | null;
  kw_per_ton: number | null;
  iplv_style: number;
  eta_2nd_law: number | null;
  capacity_ratio: number | null;
  map_test_mae: number | null;
  map_test_r2: number | null;
  hybrid_test_mae: number | null;
  loop_ratio: number | null;
  starts_per_day: number;
  alarm_days: number;
}

export interface CopRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  hvac_ids: number[];
  date_from: string;
  date_to: string;
  params: CopRunRequest;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  fleet?: CopFleetRow[] | null;
  models?: Record<string, { cop_map: { biquad: number[]; plr: number[] }; cap_map: { biquad: number[]; plr: number[] };
    grey: { coef: number[] }; expected_model: string; gbm_importance: Record<string, number>; train_rows: number; test_rows: number;
    ranges: Record<string, number[]> }> | null;
  summary?: { units: Record<string, CopUnitSummary>; fleet: CopFleetRow[] } | null;
}

export interface CopPoint {
  ts: string;
  mode: string | null;
  steady: boolean;
  is_train: boolean;
  cop_actual: number | null;
  cop_logged: number | null;
  cop_ratio: number | null;
  cop_loop: number | null;
  cop_map: number | null;
  cop_grey: number | null;
  cop_hybrid: number | null;
  cop_expected: number | null;
  cop_residual: number | null;
  eta_2nd_law: number | null;
  cop_carnot: number | null;
  lift_k: number | null;
  plr: number | null;
  cap_actual_kw: number | null;
  cap_expected_kw: number | null;
  q_dt_kw: number | null;
  power_kw: number | null;
  power_expected_kw: number | null;
  rej_closure_kw: number | null;
  t_amb_c: number | null;
  t_supply_c: number | null;
}

export interface CopPrediction {
  plr: number;
  plr_needed: number;
  cycling: boolean;
  min_plr: number;
  cop_map: number;
  cop_grey: number | null;
  cop_carnot: number | null;
  eta_2nd_law: number | null;
  lift_k: number;
  capacity_kw: number;
  capacity_full_kw: number;
  cooling_kw: number;
  hvac_kw: number | null;
  kw_per_ton: number | null;
  heat_load_exceeds_capacity: boolean;
  out_of_range: boolean;
}
