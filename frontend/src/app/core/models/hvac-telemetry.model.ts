import { StateSegment } from './system-telemetry.model';

export interface HvacUnit {
  hvac_id: number;
  hvac_code: string;
}

export interface HvacTelemetry {
  hvac_id: number;
  ts: string;
  hvac_code: string | null;
  cooling_mode: string | null;
  ambient_temp_c: number | null;
  coolant_setpoint_c: number | null;
  coolant_supply_temp_c: number | null;
  coolant_return_temp_c: number | null;
  coolant_delta_t_c: number | null;
  coolant_flow_lpm: number | null;
  compressor_speed_pct: number | null;
  condenser_fan_pct: number | null;
  refrig_suction_bar: number | null;
  refrig_discharge_bar: number | null;
  battery_heat_load_kw: number | null;
  cooling_capacity_kw: number | null;
  heat_rejected_kw: number | null;
  hvac_power_kw: number | null;
  cop: number | null;
  enclosure_temp_c: number | null;
  enclosure_humidity_pct: number | null;
  filter_dp_pa: number | null;
  cum_energy_kwh: number | null;
  compressor_runtime_h: number | null;
  units_running: number | null;
  alarm_level: number | null;
  alarm_flags: string | null;
}

export interface HvacTelemetryCreateInput {
  hvac_id: number;
  ts: string;
  cooling_mode?: string | null;
  ambient_temp_c?: number | null;
  coolant_setpoint_c?: number | null;
  coolant_supply_temp_c?: number | null;
  coolant_return_temp_c?: number | null;
  battery_heat_load_kw?: number | null;
  hvac_power_kw?: number | null;
  cop?: number | null;
  enclosure_temp_c?: number | null;
  enclosure_humidity_pct?: number | null;
  units_running?: number | null;
  alarm_level?: number | null;
}

export interface HvacTelemetryPage {
  items: HvacTelemetry[];
  total: number;
  page: number;
  page_size: number;
}

export interface HvacTelemetryLookups {
  units: HvacUnit[];
  cooling_modes: string[];
}

export interface BulkHvacTelemetryRowError {
  row: number;
  errors: string[];
}

export interface BulkHvacTelemetryResult {
  filename: string;
  hvac_code: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkHvacTelemetryRowError[];
}

export interface HvacTelemetrySeries {
  hvac_id: number;
  hvac_code: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  /** One entry per bucket: `ts` plus every HVAC series column. */
  points: ({ ts: string } & Record<string, number | null>)[];
  timelines: Record<string, { states: string[]; segments: StateSegment[] }>;
  coolant_setpoint_c: number | null;
}
