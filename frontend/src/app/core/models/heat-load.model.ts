/** Heat-load prediction / thermal design (ML service /heatload). Heat terms in kW thermal; pack current + on charge. */

export interface HeatSystemOption {
  system_id: number;
  system_name: string;
  site_name: string;
  intervals: number;
  first_day: string;
  last_day: string;
}

export interface HeatRunRequest {
  system_ids: number[];
  date_from: string;
  date_to: string;
  run_name: string | null;
  measured_reference: 'heat_load_sensor' | 'cooling_delivered';
  envelope_area_m2: number;
  u_value_w_m2k: number;
  sunlit_area_m2: number;
  absorptivity: number;
  pcs_inside: boolean;
  aux_inside: boolean;
  thermal_mass_kj_k_per_kwh: number;
  solar_source: 'auto' | 'clear_sky' | 'none';
  train_frac: number;
  horizons: number[];
  plan_source: 'scheduled' | 'typical' | 'oracle';
  issue_every_min: number;
  n_estimators: number;
  learning_rate: number;
  num_leaves: number;
  design_ambient_c: number | null;
  design_ghi_wm2: number;
  design_soc_pct: number;
  design_cell_temp_c: number;
  internal_setpoint_c: number;
  eol_resistance_pct: number | null;
  margin_pct: number;
  redundancy: number;
  unit_capacity_kw: number | null;
  capacity_derate_pct_per_c: number;
  coincidence: number;
  use_calibrated: boolean;
}

export interface HeatOptions {
  systems: HeatSystemOption[];
  defaults: HeatRunRequest;
  references: { key: string; label: string }[];
  plan_sources: { key: string; label: string }[];
}

export interface HeatScores {
  n: number;
  r2?: number | null;
  mae_kw?: number;
  rmse_kw?: number;
  bias_kw?: number;
}

export interface HeatCalibration {
  coef: Record<'const' | 'irr_chg' | 'irr_dis' | 'rev' | 'pcs' | 'solar' | 'env' | 'storage', number>;
  at_upper_bound: string[];
  fitted_alpha_a_m2: number;
  fitted_ua_kw_per_k: number;
  fitted_c_kwh_per_k: number;
  train: HeatScores;
  test: HeatScores;
  nameplate_train: HeatScores;
  nameplate_test: HeatScores;
  contribution_kw: Record<string, number>;
}

export interface HeatDesignCase {
  terms: Record<'battery_irreversible' | 'battery_entropic' | 'pcs' | 'aux' | 'solar' | 'envelope' | 'constant', number>;
  q_peak_kw: number;
  battery_irr_bol_kw: number;
  nameplate_terms: Record<string, number>;
}

export interface HeatDuty {
  hours: number;
  load_duration: { pct_time: number; q_kw: number; measured_kw: number }[];
  histogram: { from_kw: number; to_kw: number; hours: number; share: number }[];
  heat_kwh: number;
  chiller_kwh: number;
  mean_kw: number;
  annual_heat_mwh: number;
  annual_chiller_mwh: number;
  annualization_factor: number;
  cop_fit: { intercept: number; slope_per_c: number; n: number };
  part_load_vs_design: { band: string; share: number }[];
  hours_above_design: number;
}

export interface HeatDesign {
  condition: Record<string, number | string | boolean | null>;
  cases: Record<'CHARGE' | 'DISCHARGE', HeatDesignCase>;
  sizing_direction: 'CHARGE' | 'DISCHARGE';
  q_peak_kw: number;
  q_peak_bol_kw: number;
  margin_pct: number;
  required_capacity_kw: number;
  unit_capacity_kw: number | null;
  unit_capacity_at_design_kw: number | null;
  derate_factor: number;
  units_n?: number | null;
  units_installed_n_plus?: number | null;
  redundancy?: number;
  installed_capacity_kw?: number | null;
  observed: Record<string, number | string | null>;
  duty: HeatDuty;
  hot_spot: Record<string, number>;
}

export interface HeatHorizonScore {
  n: number;
  persistence_mae: number;
  persistence_rmse: number;
  physics_mae: number;
  physics_rmse: number;
  p50_mae: number;
  p50_rmse: number;
  pinball: number;
  coverage_p10_p90: number;
  skill_vs_persistence: number | null;
  high_load_events: number;
  high_load_recall_p90: number | null;
}

export interface HeatDirectionRow {
  intervals: number;
  q_batt_irr_kw: number;
  q_batt_rev_kw: number;
  q_pcs_kw: number;
  q_aux_kw: number;
  q_solar_kw: number;
  q_env_kw: number;
  q_storage_kw: number;
  q_total_kw: number;
  q_model_kw: number;
  measured_kw: number;
  residual_kw: number;
  q_total_no_entropic_kw: number;
  c_rate_abs_mean: number | null;
}

export interface HeatSystemSummary {
  system_id: number;
  system_name: string;
  site_name: string;
  rated_kw: number;
  usable_kwh: number;
  cells_series: number;
  measured_reference: string;
  nameplate: { alpha_a_m2: number; ua_kw_per_k: number; c_kwh_per_k: number };
  calibration: HeatCalibration;
  closure: { mean_residual_kw: number; mean_abs_residual_kw: number; residual_pct_of_measured: number | null;
    by_direction: Record<string, number>; cooling_over_heat_sensor: number };
  direction: Record<string, HeatDirectionRow>;
  design: HeatDesign;
  forecast: { tau_min: number; tau_grid_mae: number; train_rows: number; importance: Record<string, number>;
    by_horizon?: Record<string, HeatHorizonScore>; high_load_threshold_kw?: number; issues?: number };
  daily: Record<string, number | string>[];
  train_to: string;
  test_from: string;
  ghi_measured_share: number;
}

export interface HeatFleetRow {
  system_id: number;
  system_name: string;
  site_name: string;
  calibrated_r2: number | null;
  calibrated_mae_kw: number | null;
  nameplate_mae_kw: number | null;
  closure_pct: number | null;
  q_peak_kw: number;
  required_kw: number;
  units: number | null;
  measured_peak_kw: number;
  installed_kw: number | null;
  annual_chiller_mwh: number;
  fc60_mae_kw: number | null;
  fc60_persistence_mae_kw: number | null;
  fc60_coverage: number | null;
  tau_min: number | null;
}

export interface HeatRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  system_ids: number[];
  date_from: string;
  date_to: string;
  params: HeatRunRequest;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  fleet?: HeatFleetRow[] | null;
  models?: Record<string, { battery_heat: Record<string, { r_ohm_by_soc_band: Record<string, number>; observed_bands: number[];
    r_ohm_median: number; fit: HeatScores }>; pcs_loss: { a: number; b: number; c: number; rated_kva: number; fit: HeatScores };
    calibration: Record<string, number>; tau_min: number }> | null;
  summary?: { systems: Record<string, HeatSystemSummary>; fleet: HeatFleetRow[] } | null;
}

export interface HeatLedgerRow {
  ts: string;
  direction: 'CHARGE' | 'DISCHARGE' | 'IDLE';
  is_train: boolean;
  q_batt_irr_kw: number | null;
  q_batt_rev_kw: number | null;
  q_pcs_kw: number | null;
  q_aux_kw: number | null;
  q_solar_kw: number | null;
  q_env_kw: number | null;
  q_storage_kw: number | null;
  q_total_kw: number | null;
  q_model_kw: number | null;
  measured_kw: number | null;
  heat_load_sensor_kw: number | null;
  cooling_kw: number | null;
  hvac_kw: number | null;
  residual_kw: number | null;
  t_amb_c: number | null;
  t_enc_c: number | null;
  t_cell_max_c: number | null;
  dt_cell_c: number | null;
  ghi_wm2: number | null;
  ghi_source: string | null;
}

export interface HeatPoint {
  issued_at: string;
  horizon_min: number;
  valid_at: string;
  actual_kw: number | null;
  persistence_kw: number | null;
  physics_kw: number | null;
  p10_kw: number | null;
  p50_kw: number | null;
  p90_kw: number | null;
  plan_kw: number | null;
}
