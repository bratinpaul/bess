import { StateSegment } from './system-telemetry.model';

export interface PcsTelemetry {
  pcs_id: number;
  ts: string;
  pcs_code: string | null;
  mode_code: string | null;
  grid_service: string | null;
  ac_active_power_kw: number | null;
  ac_reactive_power_kvar: number | null;
  ac_apparent_power_kva: number | null;
  power_factor: number | null;
  ac_frequency_hz: number | null;
  ac_voltage_ab_v: number | null;
  ac_voltage_bc_v: number | null;
  ac_voltage_ca_v: number | null;
  ac_current_a_a: number | null;
  ac_current_b_a: number | null;
  ac_current_c_a: number | null;
  thd_voltage_pct: number | null;
  thd_current_pct: number | null;
  dc_voltage_v: number | null;
  dc_current_a: number | null;
  dc_power_kw: number | null;
  efficiency_pct: number | null;
  igbt_temp_c: number | null;
  heatsink_temp_c: number | null;
  inlet_coolant_temp_c: number | null;
  ambient_temp_c: number | null;
  avail_charge_kw: number | null;
  avail_discharge_kw: number | null;
  ac_energy_import_kwh: number | null;
  ac_energy_export_kwh: number | null;
  breaker_state: string | null;
  alarm_level: number | null;
}

export interface PcsTelemetryCreateInput {
  pcs_id: number;
  ts: string;
  mode_code?: string | null;
  grid_service?: string | null;
  ac_active_power_kw?: number | null;
  ac_reactive_power_kvar?: number | null;
  ac_apparent_power_kva?: number | null;
  power_factor?: number | null;
  ac_frequency_hz?: number | null;
  igbt_temp_c?: number | null;
  efficiency_pct?: number | null;
  breaker_state?: string | null;
  alarm_level?: number | null;
}

export interface PcsTelemetryPage {
  items: PcsTelemetry[];
  total: number;
  page: number;
  page_size: number;
}

export interface PcsTelemetryLookups {
  modes: string[];
  grid_services: string[];
  breaker_states: string[];
}

export interface BulkPcsTelemetryRowError {
  row: number;
  errors: string[];
}

export interface BulkPcsTelemetryResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkPcsTelemetryRowError[];
}

export interface PcsStateTimeline {
  states: string[];
  segments: StateSegment[];
}

export interface PcsTelemetrySeries {
  pcs_id: number;
  pcs_code: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  /** One entry per bucket: `ts` plus every PCS series column. */
  points: ({ ts: string } & Record<string, number | null>)[];
  timelines: Record<string, PcsStateTimeline>;
  min_power_factor: number | null;
  rated_apparent_kva: number | null;
}
