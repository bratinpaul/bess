/** One EMS dispatch instruction. Times are plant local time ("YYYY-MM-DDTHH:mm:ss+05:30"). */
export interface DispatchEvent {
  dispatch_id: string;
  effective_from: string;
  /** Null while the dispatch is active. */
  effective_to: string | null;
  issued_at: string;
  /** Derived. */
  duration_min: number | null;
  net_energy_kwh: string;
  issued_date: string;
  ems_id: number;
  ems_code: string | null;
  battery_system_id: number | null;
  system_name: string | null;
  command_code: string;
  dispatch_mode: string;
  dispatch_mode_description: string | null;
  grid_service: string;
  grid_service_description: string | null;
  source: string | null;
  /** > 0 charge / import, < 0 discharge / export. */
  p_setpoint_kw: string;
  target_soc_pct: string | null;
  soc_start_pct: string | null;
  soc_end_pct: string | null;
  ramp_rate_kw_s: string | null;
  import_kwh: string;
  export_kwh: string;
  avg_price_mwh: string | null;
  revenue_usd: string | null;
  accepted: boolean;
  status: DispatchStatus;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export type DispatchStatus = 'Active' | 'Completed' | 'Aborted';

export interface DispatchEventInput {
  dispatch_id?: string | null;
  effective_from: string;
  effective_to: string | null;
  issued_at: string | null;
  ems_id: number;
  command_code: string;
  dispatch_mode: string;
  grid_service: string;
  source: string | null;
  p_setpoint_kw: number;
  target_soc_pct: number | null;
  soc_start_pct: number | null;
  soc_end_pct: number | null;
  ramp_rate_kw_s: number | null;
  import_kwh: number;
  export_kwh: number;
  avg_price_mwh: number | null;
  revenue_usd: number | null;
  accepted: boolean;
  status: DispatchStatus | null;
  note: string | null;
}

/** The workbook's Summary 'Overview', over the filtered set. */
export interface DispatchEventStats {
  total: number;
  active: number;
  aborted: number;
  avg_duration_min: number | null;
  import_mwh: number;
  export_mwh: number;
  revenue_usd: number;
  by_mode: Record<string, number>;
  by_service: Record<string, number>;
}

export interface DispatchEventPage {
  items: DispatchEvent[];
  total: number;
  page: number;
  page_size: number;
  stats: DispatchEventStats;
}

export interface DispatchEventFilters {
  dispatch_mode?: string;
  grid_service?: string;
  command_code?: string;
  source?: string;
  status?: DispatchStatus | '';
  accepted?: boolean | null;
  ems_id?: number | null;
  battery_system_id?: number | null;
  start?: string;
  end?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface DispatchCodeOption {
  code: string;
  description: string | null;
}

export interface DispatchEventLookups {
  ems: { ems_id: number; ems_code: string; battery_system_id: number | null; system_name: string | null }[];
  modes: DispatchCodeOption[];
  services: DispatchCodeOption[];
  command_codes: string[];
  statuses: DispatchStatus[];
  sources: string[];
}

export interface BulkDispatchEventResult {
  filename: string;
  sheet: string | null;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; dispatch_id: string | null; errors: string[] }[];
  ignored_columns: string[];
  /** Running dispatches a newer one in the file ended, e.g. "DSP-00357 ended at 2026-09-28 18:20". */
  closed_dispatches: string[];
}

/** Short labels for the dispatch modes (codes stay visible in the form and detail page). */
export const DISPATCH_MODE_LABELS: Record<string, string> = {
  STANDBY: 'Standby',
  IDLE: 'Idle',
  SCHEDULED_CHARGE: 'Scheduled charge',
  ENERGY_ARBITRAGE: 'Energy arbitrage',
  FREQUENCY_REGULATION: 'Frequency regulation'
};

/** Usual command and grid service for each mode, used as form defaults. */
export const MODE_DEFAULTS: Record<string, { command_code: string; grid_service: string }> = {
  STANDBY: { command_code: 'SET_MODE', grid_service: 'NONE' },
  IDLE: { command_code: 'SET_MODE', grid_service: 'NONE' },
  SCHEDULED_CHARGE: { command_code: 'SET_POWER', grid_service: 'ARBITRAGE' },
  ENERGY_ARBITRAGE: { command_code: 'SET_POWER', grid_service: 'ARBITRAGE' },
  FREQUENCY_REGULATION: { command_code: 'SET_SERVICE', grid_service: 'FREQ_REG' }
};

export function modeLabel(code: string | null | undefined): string {
  return code ? DISPATCH_MODE_LABELS[code] ?? code.replace(/_/g, ' ').toLowerCase() : '';
}

/** Plant local time as shown in the tables: "2026-08-01 15:50". */
export function plantTime(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '';
}

/**
 * Mode colours for charts, chips and swatches, in the fixed order modes are stacked
 * (checked with the dataviz palette validator; neighbours in this order stay distinguishable).
 */
export const MODE_ORDER = ['FREQUENCY_REGULATION', 'ENERGY_ARBITRAGE', 'SCHEDULED_CHARGE', 'STANDBY', 'IDLE'];
export const MODE_COLORS: Record<string, string> = {
  FREQUENCY_REGULATION: '#2a78d6',
  ENERGY_ARBITRAGE: '#eb6834',
  SCHEDULED_CHARGE: '#1baf7a',
  STANDBY: '#eda100',
  IDLE: '#4a3aa7'
};

// ---------------------------------------------------------------- analytics (graphical tab)

export interface DispatchDay {
  date: string;
  /** By issued date, like the workbook's Summary 'Daily' table. */
  events: number;
  events_by_mode: Record<string, number>;
  revenue_usd: number;
  import_kwh: number;
  export_kwh: number;
  /** Minutes spent in each mode on this calendar day. */
  minutes_by_mode: Record<string, number>;
}

export interface DispatchModeSummary {
  mode: string;
  description: string | null;
  events: number;
  minutes: number;
  import_kwh: number;
  export_kwh: number;
  revenue_usd: number;
  mean_duration_min: number | null;
  max_duration_min: number | null;
}

export interface DispatchHour {
  hour: number;
  import_kwh: number;
  export_kwh: number;
  avg_price_mwh: number | null;
}

export interface DispatchPoint {
  dispatch_id: string;
  effective_from: string;
  effective_to: string | null;
  dispatch_mode: string;
  p_setpoint_kw: number;
  soc_start_pct: number | null;
  soc_end_pct: number | null;
  target_soc_pct: number | null;
  avg_price_mwh: number | null;
  revenue_usd: number | null;
  duration_min: number | null;
}

export interface DispatchEventAnalytics {
  total: number;
  /** Running dispatches have no end yet and are left out of the time-based charts. */
  open_dispatches: number;
  modes: DispatchModeSummary[];
  days: DispatchDay[];
  hours: DispatchHour[];
  sources: { key: string; count: number }[];
  dispatches: DispatchPoint[];
}
