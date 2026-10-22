/** Energy-arbitrage optimizer (ML service /arbitrage): studies (MILP backtests) and the Dispatch Viewer's day view.
 *  Power sign: + discharge / − charge. */

export interface ArbSystem {
  system_id: number;
  system_name: string;
  site_name: string;
  node_code: string | null;
  first_day: string | null;
  last_day: string | null;
}

export interface ArbStudyRequest {
  system_id: number;
  date_from: string;
  date_to: string;
  mode: 'deterministic' | 'stochastic';
  efficiency: 'scalar' | 'curve';
  degradation: 'scalar' | 'curve';
  as_stacking: boolean;
  as_max_mw: number | null;
  terminal: 'next_open' | 'start' | 'value' | 'free';
  terminal_soc: number;
  resolve_every_h: number;
  cvar_lambda: number;
  cvar_alpha: number;
  time_limit: number;
  study_name: string | null;
}

export interface ArbOptions {
  systems: ArbSystem[];
  modes: { key: string; label: string }[];
  defaults: ArbStudyRequest;
  solver: string;
}

export interface ArbStudyDay {
  kpi_date: string;
  run_id: number | null;
  solver_status: string;
  solve_seconds: number;
  expected_profit_usd: number | null;
  gross_usd: number;
  degradation_usd: number;
  grid_usd: number;
  net_usd: number;
  oracle_net_usd: number;
  pack_net_usd: number | null;
  discharge_mwh: number;
  charge_mwh: number;
  cycles: number;
  soc_start_pct: number;
  soc_end_pct: number;
  checks: Record<string, boolean | number | null>;
}

export interface ArbStudy {
  study_id: number;
  study_name: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  system_id: number;
  node_id: number;
  date_from: string;
  date_to: string;
  mode: string;
  params: ArbStudyRequest;
  metrics: Record<string, number | string | null> | null;
  checks: { checks: Record<string, boolean>; details: Record<string, unknown> } | null;
  warnings: string[] | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  days?: ArbStudyDay[];
}

export interface ArbDayItem {
  kpi_date: string;
  run_id: number;
  net_usd: number | null;
  total_usd?: number | null;
}

export interface ArbInterval {
  ts: string;
  rt: number | null;
  dam: number | null;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  p_sched: number | null;
  p_actual: number | null;
  soc: number | null;
  soc_plan: number | null;
  c_as: number | null;
  gross: number | null;
  degr: number | null;
  grid: number | null;
  as_usd: number | null;
  net: number | null;
}

export interface ArbDayView {
  warnings: string[];
  source: 'pack' | 'study';
  day: string;
  study_id: number | null;
  system_id: number;
  node_code: string;
  study: { study_name: string | null; mode: string; params: ArbStudyRequest } | null;
  run: {
    run_id: number;
    issued_at: string;
    horizon_start: string;
    horizon_end: string;
    method: string | null;
    objective: string | null;
    solver_status: string | null;
    expected_profit_usd: number | null;
    solve_seconds: number | null;
  };
  state: Record<string, number | null>;
  battery: { soc_min: number; soc_max: number; usable_mwh: number; rte_ac: number; max_cycles_per_day: number | null; p_max_kw: number };
  intervals: ArbInterval[];
  hourly: { ts: string; p_setpoint: number | null; soc_target: number | null; mode: string; market: string; forecast: number | null }[];
  oracle: {
    intervals?: { ts: string; p: number | null; soc: number | null; net: number | null }[];
    net_usd?: number | null;
    as_usd?: number | null;
    total_usd?: number | null;
    note?: string;
    error?: string;
  } | null;
  kpis: Record<string, number | null>;
}
