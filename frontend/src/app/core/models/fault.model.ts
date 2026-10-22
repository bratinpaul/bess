/** Fault-diagnosis tables (Core -> Fault): fault catalog, signatures, episodes, alarm links, maintenance actions and
 *  classifier predictions. Rows are plain records; each page is described by a FaultPageConfig. */

export type FaultRow = Record<string, unknown>;

export interface FaultStat {
  label: string;
  value: string | null;
  warn: boolean;
}

export interface FaultPage {
  items: FaultRow[];
  total: number;
  page: number;
  page_size: number;
  stats: FaultStat[];
}

export interface FaultBulkResult {
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

export interface FaultLookups {
  systems: { id: number; code: string }[];
  faults: { code: string; label: string; subsystem: string }[];
  episodes: { code: string; label: string }[];
  model_versions: string[];
  categories: string[];
  subsystems: string[];
  signal_kinds: string[];
  operators: string[];
  detection_methods: string[];
  roles: string[];
  action_types: string[];
  asset_types: string[];
  severities: number[];
  booleans: boolean[];
}

/** Pickers filled from the lookups endpoint. */
export type FaultLookupSource = 'systems' | 'faults' | 'episodes' | 'model_versions' | 'categories';
export type FaultEnumSource = 'subsystems' | 'signal_kinds' | 'operators' | 'detection_methods' | 'roles' | 'action_types'
  | 'asset_types' | 'severities' | 'booleans';
