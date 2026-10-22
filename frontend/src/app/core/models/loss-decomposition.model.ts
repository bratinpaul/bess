/** Loss decomposition / performance benchmarking (ML service /loss): runs, the daily scorecard and the interval ledger.
 *  Node powers are + toward the battery (charge) / - toward the grid (discharge); losses are always positive. */

export type LossStage = 'batt' | 'dc' | 'pcs' | 'xfmr' | 'aux' | 'standby';
export type LossNode = 'chem' | 'term' | 'dc' | 'ac' | 'poi_x' | 'poi';

export interface LossSystemOption {
  system_id: number;
  system_name: string;
  site_id: number;
  site_name: string;
  intervals: number;
  first_day: string;
  last_day: string;
}

export interface LossRunRequest {
  system_ids: number[];
  date_from: string;
  date_to: string;
  run_name: string | null;
  idle_frac: number;
  transformer_mode: 'metered' | 'model';
  xfmr_kva: number | null;
  xfmr_core_pct: number;
  xfmr_cu_pct: number;
  standby_min_rest_h: number;
  standby_max_drop_pct_h: number;
  baseline_days: number;
  resistance_growth_pct_per_soh: number;
  self_discharge_pct_day: number | null;
  ref_load_frac: number;
  ref_temp_c: number;
  ref_ambient_c: number;
  guarantee_rte_pct: number | null;
  guarantee_basis: 'dc' | 'ac' | 'poi_excl_aux' | 'plant';
  min_cycle_frac: number;
  ewma_lambda: number;
  ewma_l: number;
  cusum_k: number;
  cusum_h: number;
}

export interface LossOptions {
  systems: LossSystemOption[];
  defaults: LossRunRequest;
  stages: { key: LossStage; label: string }[];
  guarantee_bases: { key: string; label: string }[];
}

export interface LossFleetRow {
  system_id: number;
  system_name: string;
  site_name: string;
  rte_plant: number | null;
  rte_poi_excl_aux: number | null;
  rte_ac: number | null;
  rte_term: number | null;
  performance_ratio: number | null;
  guarantee_gap_pts: number | null;
  shares: Partial<Record<LossStage, number>>;
  aux_pct_of_throughput: number | null;
  total_loss_kwh: number;
  loss_usd: number;
  excess_usd: number;
  excess_kwh: number;
  utilization_pct: number | null;
  cycles: number | null;
  alarms: Partial<Record<LossStage, number>>;
}

/** Energy balance of a window (the run or a set of days). */
export interface LossWindow {
  intervals: number;
  hours: number;
  e_in: Record<LossNode, number>;
  e_out: Record<LossNode, number>;
  loss: Record<LossStage, number>;
  aux_split: { hvac: number; controls: number };
  expected: Record<LossStage, number>;
  stored_kwh: number;
  closure_kwh: number;
  closure_pct_of_throughput: number | null;
  throughput_kwh: number;
  utilization_pct: number | null;
  total_loss_kwh: number;
  aux_pct_of_throughput: number | null;
  fixed_kwh: number;
  variable_kwh: number;
  closure_pcs_kwh: number;
  cycles: number | null;
  avg_price_mwh: number | null;
  loss_usd: number;
  excess_kwh: Partial<Record<LossStage, number>>;
  excess_usd_by_stage: Partial<Record<LossStage, number>>;
  excess_usd: number;
  excess_kwh_total: number;
  rte: Partial<Record<'term' | 'dc' | 'ac' | 'poi_x' | 'poi', number>>;
  has_cycle: boolean;
  factors: Partial<Record<'batt' | 'dc' | 'pcs' | 'xfmr' | 'aux', number>>;
  factors_expected: Partial<Record<'batt' | 'dc' | 'pcs' | 'xfmr' | 'aux', number>>;
  shares: Partial<Record<LossStage, number>>;
  rte_expected: number | null;
  performance_ratio: number | null;
  guarantee_basis_rte?: number | null;
  guarantee_gap_pts: number | null;
}

export interface LossLoadingBin {
  from_pct: number;
  to_pct: number;
  mid_pct: number;
  n: number;
  p_kw: number;
  batt: number;
  pcs: number;
  xfmr: number;
  aux: number;
  exp_batt: number;
  exp_pcs: number;
  exp_xfmr: number;
  exp_aux: number;
  fixed_kw: number;
  variable_kw: number;
  loss_pct_of_power: number | null;
}

export interface LossDirectionRow {
  intervals: number;
  throughput_kwh: number;
  eta_pcs_pct?: number | null;
  eta_batt_pct?: number | null;
  [stage: string]: unknown;
}

export interface LossCounterTotal {
  counter_kwh: number;
  integral_kwh: number;
  diff_kwh: number;
  diff_pct: number | null;
  days_missing: number;
}

export interface LossSystemSummary {
  system_id: number;
  system_name: string;
  site_name: string;
  rated_kw: number;
  rated_kva: number;
  usable_kwh: number;
  kwh_per_pct: number;
  cells_series: number | null;
  guarantee_rte: number;
  guarantee_basis: string;
  guarantee_source: string;
  pcs_nameplate_eff_pct: number | null;
  window: LossWindow;
  statement: string | null;
  audit: Record<string, unknown> & { counters: Record<string, LossCounterTotal> };
  loading_curve: LossLoadingBin[];
  direction: Record<string, LossDirectionRow>;
  alarms: Partial<Record<LossStage, string[]>>;
  days: number;
  baseline_days: number;
}

export interface LossFitScore {
  n: number;
  r2?: number | null;
  mae_kw?: number;
  bias_kw?: number;
}

export interface LossModels {
  baseline: { days: number; from: string; to: string; rows: number; soh_pct: number | null };
  battery: {
    cells_series: number;
    soh_growth_pct_per_pt: number;
    directions: Record<string, { r0_v: number; r_ohm_pack: number; r_mohm_cell_equiv: number; kt_per_c: number; soc_lin_v: number;
      soc_quad_v: number; temperature_term: boolean; fit: LossFitScore; out_of_baseline: LossFitScore }>;
  };
  pcs: {
    rated_kva: number;
    idle_kw: number;
    directions: Record<string, { a_kw: number; b_kw: number; c_kw: number; d_kw_per_c: number; temperature_term: boolean;
      eta_ref_pct: number | null; fit: LossFitScore; out_of_baseline: LossFitScore }>;
  };
  transformer: { mode: string; rating_kva: number; rating_source: string; nameplate_core_kw: number; nameplate_cu_at_rated_kw: number;
    metered_residual: boolean; fitted_core_kw: number | null; fitted_cu_at_rated_kw: number | null; residual_abs_mean_kw: number };
  aux: { c0_kw: number; c1_kw_per_kw: number; c2_kw_per_c: number; c3_kw_per_c_above_25: number; controls_base_kw: number | null;
    ref_aux_kw: number; fit: LossFitScore; out_of_baseline: LossFitScore };
  standby: { self_discharge_pct_day: number; source: string; kwh_per_pct: number; expected_kw_at_rest: number };
  reference: { load_frac: number; temp_c: number; ambient_c: number };
}

export interface LossRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  system_ids: number[];
  date_from: string;
  date_to: string;
  params: LossRunRequest;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  fleet?: LossFleetRow[] | null;
  models?: Record<string, LossModels> | null;
  summary?: { systems: Record<string, LossSystemSummary>; fleet: LossFleetRow[] } | null;
}

export interface LossControlPoint {
  excess_pct: number | null;
  ewma?: number;
  ucl?: number;
  lcl?: number;
  center?: number;
  sigma?: number;
  cusum_pos?: number;
  cusum_neg?: number;
  ewma_alarm?: boolean;
  cusum_alarm?: boolean;
  status?: 'ok' | 'ewma' | 'cusum' | 'both' | 'noisy';
}

export interface LossDay {
  run_id: number;
  system_id: number;
  day: string;
  intervals: number;
  is_baseline: boolean;
  e_in_poi_kwh: number;
  e_out_poi_kwh: number;
  e_in_ac_kwh: number;
  e_out_ac_kwh: number;
  e_in_term_kwh: number;
  e_out_term_kwh: number;
  stored_kwh: number;
  throughput_kwh: number;
  utilization_pct: number | null;
  loss_batt_kwh: number;
  loss_dc_kwh: number;
  loss_pcs_kwh: number;
  loss_xfmr_kwh: number;
  aux_hvac_kwh: number;
  aux_ctrl_kwh: number;
  standby_kwh: number;
  exp_batt_kwh: number;
  exp_pcs_kwh: number;
  exp_xfmr_kwh: number;
  exp_aux_kwh: number;
  exp_standby_kwh: number;
  fixed_kwh: number;
  variable_kwh: number;
  rte_term: number | null;
  rte_dc: number | null;
  rte_ac: number | null;
  rte_poi_excl_aux: number | null;
  rte_plant: number | null;
  rte_expected: number | null;
  performance_ratio: number | null;
  guarantee_gap_pts: number | null;
  closure_kwh: number;
  closure_pcs_kwh: number;
  avg_price_mwh: number | null;
  loss_usd: number;
  excess_usd: number;
  extra: {
    factors: LossWindow['factors'];
    factors_expected: LossWindow['factors_expected'];
    shares: LossWindow['shares'];
    excess_kwh: Partial<Record<LossStage, number>>;
    excess_usd_by_stage: Partial<Record<LossStage, number>>;
    normalized: { pcs_eta_ref_pct?: number | null; pcs_loss_ratio?: number; batt_loss_ratio?: number; batt_r_ref_ohm?: number | null;
      aux_ratio?: number; aux_ref_kw?: number };
    counters: Record<string, { counter_kwh: number | null; integral_kwh: number; diff_kwh: number | null }>;
    battery_closure: { stored_kwh: number; soc_based_kwh: number | null; diff_kwh: number | null };
    control: Partial<Record<LossStage, LossControlPoint>>;
    has_cycle: boolean;
    cycles: number | null;
    aux_pct_of_throughput: number | null;
    total_loss_kwh: number;
    e_in: Record<LossNode, number>;
    e_out: Record<LossNode, number>;
  };
}

export interface LossLedgerRow {
  ts: string;
  direction: 'CHARGE' | 'DISCHARGE' | 'IDLE';
  p_poi_kw: number | null;
  p_ac_kw: number | null;
  p_dc_kw: number | null;
  p_term_kw: number | null;
  p_chem_kw: number | null;
  load_frac: number | null;
  loss_batt_kwh: number | null;
  loss_dc_kwh: number | null;
  loss_pcs_kwh: number | null;
  loss_xfmr_kwh: number | null;
  aux_hvac_kwh: number | null;
  aux_ctrl_kwh: number | null;
  standby_kwh: number | null;
  exp_batt_kwh: number | null;
  exp_pcs_kwh: number | null;
  exp_xfmr_kwh: number | null;
  exp_aux_kwh: number | null;
  eta_pcs: number | null;
  eta_batt: number | null;
  closure_kwh: number | null;
  price_mwh: number | null;
}
