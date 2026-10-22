import { BulkTelemetryRowError } from './system-telemetry.model';

export interface ModuleTelemetry {
  module_id: number;
  ts: string;
  serial_number: string | null;
  cell_v_avg_v: number | null;
  cell_v_min_v: number | null;
  cell_v_max_v: number | null;
  cell_temp_max_c: number | null;
  cell_temp_min_c: number | null;
  /** (cell_v_max_v − cell_v_min_v) × 1000, computed by the API. */
  imbalance_mv: number | null;
  balancing_active: boolean | null;
}

export interface ModuleTelemetryCreateInput {
  module_id: number;
  ts: string;
  cell_v_avg_v?: number | null;
  cell_v_min_v?: number | null;
  cell_v_max_v?: number | null;
  cell_temp_max_c?: number | null;
  cell_temp_min_c?: number | null;
  balancing_active?: boolean | null;
}

export interface ModuleTelemetryPage {
  items: ModuleTelemetry[];
  total: number;
  page: number;
  page_size: number;
}

export interface ModuleOption {
  module_id: number;
  serial_number: string | null;
  pack_number: string | null;
}

export interface BulkModuleTelemetryResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkTelemetryRowError[];
}

export interface ModuleTelemetrySeries {
  module_id: number;
  serial_number: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  /** One entry per bucket: `ts` plus every module series column. */
  points: ({ ts: string } & Record<string, number | null>)[];
}

export interface ModuleSummaryKpis {
  modules: number;
  samples_per_module: number | null;
  cell_v_min: number | null;
  cell_v_max: number | null;
  mean_imbalance_mv: number | null;
  max_imbalance_mv: number | null;
  max_temp_c: number | null;
  balancing_duty_pct: number | null;
  balancing_module_hours: number | null;
  highest_imbalance_module: string | null;
  highest_imbalance_mv: number | null;
}

export interface ModuleSummaryByModule {
  module_id: number;
  serial_number: string | null;
  /** Short label such as MOD-07. */
  label: string;
  avg_cell_v: number | null;
  min_cell_v: number | null;
  max_cell_v: number | null;
  mean_imbalance_mv: number | null;
  max_imbalance_mv: number | null;
  max_temp_c: number | null;
  balancing_hours: number;
  samples: number;
}

export interface ModuleSummaryDaily {
  day: string;
  max_imbalance_mv: number | null;
  avg_imbalance_mv: number | null;
  max_temp_c: number | null;
  balancing_module_hours: number;
  samples: number;
}

export interface ModuleTelemetrySummary {
  start_date: string;
  end_date: string;
  sample_interval_minutes: number;
  kpis: ModuleSummaryKpis;
  by_module: ModuleSummaryByModule[];
  daily: ModuleSummaryDaily[];
}

export interface ModuleTelemetryDateRange {
  first_date: string | null;
  last_date: string | null;
}
