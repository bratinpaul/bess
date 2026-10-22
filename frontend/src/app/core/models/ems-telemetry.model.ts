import { StateSegment } from './system-telemetry.model';

export interface EmsController {
  ems_id: number;
  ems_code: string;
}

export interface EmsTelemetry {
  ems_id: number;
  ts: string;
  ems_code: string | null;
  dispatch_mode: string | null;
  grid_service: string | null;
  market_price_mwh: number | null;
  p_setpoint_kw: number | null;
  poi_active_power_kw: number | null;
  poi_reactive_power_kvar: number | null;
  tracking_error_kw: number | null;
  grid_frequency_hz: number | null;
  poi_voltage_kv: number | null;
  agc_signal: number | null;
  plant_soc_pct: number | null;
  target_soc_pct: number | null;
  avail_charge_kw: number | null;
  avail_discharge_kw: number | null;
  avail_charge_energy_kwh: number | null;
  avail_discharge_energy_kwh: number | null;
  aux_load_kw: number | null;
  aux_load_pct: number | null;
  cum_import_kwh: number | null;
  cum_export_kwh: number | null;
  revenue_cum_usd: number | null;
  units_online: number | null;
  plant_available: number | null;
  alarm_level: number | null;
}

export interface EmsTelemetryCreateInput {
  ems_id: number;
  ts: string;
  dispatch_mode?: string | null;
  grid_service?: string | null;
  market_price_mwh?: number | null;
  poi_active_power_kw?: number | null;
  poi_reactive_power_kvar?: number | null;
  grid_frequency_hz?: number | null;
  plant_soc_pct?: number | null;
  target_soc_pct?: number | null;
  units_online?: number | null;
  plant_available?: number | null;
  alarm_level?: number | null;
}

export interface EmsTelemetryPage {
  items: EmsTelemetry[];
  total: number;
  page: number;
  page_size: number;
}

export interface EmsTelemetryLookups {
  controllers: EmsController[];
  dispatch_modes: string[];
  grid_services: string[];
}

export interface BulkEmsTelemetryRowError {
  row: number;
  errors: string[];
}

export interface BulkEmsTelemetryResult {
  filename: string;
  ems_code: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkEmsTelemetryRowError[];
}

export interface EmsTelemetrySeries {
  ems_id: number;
  ems_code: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  /** One entry per bucket: `ts` plus every EMS series column. */
  points: ({ ts: string } & Record<string, number | null>)[];
  timelines: Record<string, { states: string[]; segments: StateSegment[] }>;
}
