/** Arbitrage decision tables (Core -> Dispatch): optimization runs, decision states, dispatch schedule / outcome,
 *  AS awards and price scenarios. Rows are plain records; each page is described by a DispatchPageConfig. */

export type ArbRow = Record<string, unknown>;

export interface ArbStat {
  label: string;
  value: string | null;
  warn: boolean;
}

export interface ArbPage {
  items: ArbRow[];
  total: number;
  page: number;
  page_size: number;
  stats: ArbStat[];
}

export interface ArbBulkResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  warnings: string[];
  first_ts: string | null;
  last_ts: string | null;
}

export interface ArbOption {
  id: number;
  code: string;
  label: string | null;
}

export interface ArbRunOption {
  run_id: number;
  system_id: number;
  system_code: string;
  issued_at: string;
  horizon_start: string;
  horizon_end: string;
  resolution_min: number;
}

export interface ArbLookups {
  systems: ArbOption[];
  nodes: ArbOption[];
  products: ArbOption[];
  runs: ArbRunOption[];
  scenario_vintages: string[];
  methods: string[];
  objectives: string[];
  solver_statuses: string[];
  modes: string[];
  markets: string[];
  resolutions: number[];
}

/** Pickers filled from the lookups endpoint. */
export type LookupSource = 'systems' | 'nodes' | 'products' | 'runs' | 'scenario_vintages';
export type EnumSource = 'methods' | 'objectives' | 'solver_statuses' | 'modes' | 'markets' | 'resolutions';
