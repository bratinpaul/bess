/** SOC trajectory forecasting use case of the ML service (/soc-forecast). */

export type SocMethod = 'hold' | 'physics_typical' | 'physics_scheduled' | 'hybrid_typical' | 'hybrid_scheduled';
export type PlanSource = 'scheduled' | 'typical' | 'custom';

export interface SocParamSpec {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min: number;
  max: number;
  step: number;
}

export interface SocUnit {
  ems_id: number;
  ems_code: string;
  battery_system_id: number | null;
  system_name: string | null;
  site_name: string | null;
  rated_energy_mwh: number | null;
  rated_power_mw: number | null;
  readings: number;
  date_from: string | null;
  date_to: string | null;
  commands: number;
}

export interface SocOptions {
  units: SocUnit[];
  gbm_params: SocParamSpec[];
  methods: Record<SocMethod, string>;
  defaults: { horizon_h: number; test_fraction: number; origin_step_min: number; train_origin_step_min: number; train_horizon_step: number };
}

export interface SocTrainRequest {
  ems_ids: number[];
  date_from: string | null;
  date_to: string | null;
  horizon_h: number;
  test_fraction: number;
  origin_step_min: number;
  train_origin_step_min: number;
  train_horizon_step: number;
  soc_min: number | null;
  soc_max: number | null;
  gbm_params: Record<string, number>;
  run_name: string | null;
  make_default: boolean;
}

export interface SocScores {
  n: number;
  mae: number | null;
  rmse: number | null;
  mae_1h: number | null;
  mae_4h: number | null;
  mae_end: number | null;
  max_error: number | null;
  coverage_pct: number | null;
  width: number | null;
  skill_pct: number | null;
  drawdown_mae: number | null;
  breach_pct: number | null;
}

export interface SocPhysics {
  c_chg: number;
  c_dis: number;
  soc_min: number;
  soc_max: number;
  drift: number;
  cap_chg_kwh: number;
  cap_dis_kwh: number;
  round_trip: number;
}

export interface SocRun {
  run_id: number;
  run_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  is_default: boolean;
  ems_ids: number[];
  date_from: string | null;
  date_to: string | null;
  horizon_h: number;
  test_fraction: number;
  origin_step_min: number;
  params: Record<string, any>;
  n_train_rows: number | null;
  n_test_origins: number | null;
  best_method: SocMethod | null;
  metrics: Record<SocMethod, SocScores> | null;
  warnings: string[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface SocRunDetail extends SocRun {
  results: {
    mae_by_step: Record<SocMethod, (number | null)[]>;
    step_every_min: number;
    importance: Record<string, Record<string, number>>;
    physics: Record<string, SocPhysics>;
    typical: Record<string, (number | null)[]>;
    split: Record<string, { test_from: string; to: string }>;
    schedule_coverage: Record<string, number | null>;
  } | null;
}

export interface SocModelOption {
  run_id: number;
  run_name: string | null;
  is_default: boolean;
  ems_ids: number[];
  horizon_h: number;
  best_method: SocMethod | null;
  metrics: Record<SocMethod, SocScores> | null;
  finished_at: string | null;
}

export interface SocTrajectory {
  p10: (number | null)[];
  p50: (number | null)[];
  p90: (number | null)[];
}

export interface PlanBlock {
  start: string;
  end: string;
  kw: number;
}

export interface SocForecast {
  run_id: number;
  ems_id: number;
  origin_ts: string;
  soc_now: number | null;
  source: PlanSource;
  schedule_coverage: number | null;
  physics: SocPhysics;
  times: string[];
  plan_kw: (number | null)[];
  plan_from_schedule: boolean[];
  trajectories: { hold: SocTrajectory; physics: SocTrajectory; hybrid: SocTrajectory };
  history: { ts: string; soc: number | null; sp: number | null; mode: string | null }[];
  commands: { start: string; end: string; kw: number | null; mode: string; source: string }[];
  derived: {
    discharge_kwh_p50: (number | null)[];
    discharge_kwh_p10: (number | null)[];
    charge_headroom_kwh_p50: (number | null)[];
    time_to_min_p50: string | null;
    time_to_min_p10: string | null;
    time_to_max_p50: string | null;
    time_to_max_p90: string | null;
    min_soc_p10: number | null;
    min_soc_p50: number | null;
    max_soc_p90: number | null;
  };
}

export interface SocBacktestPoint {
  method: SocMethod;
  step: number;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  actual: number | null;
  plan_kw: number | null;
}

export interface SocBacktest {
  origin_ts: string;
  points: SocBacktestPoint[];
  history: { ts: string; soc: number | null; sp: number | null }[];
}
