import { StateSegment } from './system-telemetry.model';

export interface MeteringPoint {
  metering_point_id: number;
  mp_code: string;
  mp_type: string;
  site_id: number;
  site_name: string | null;
  voltage_kv: number | null;
  description: string | null;
  readings: number;
  first_ts: string | null;
  last_ts: string | null;
}

export interface DemandTelemetry {
  metering_point_id: number;
  ts: string;
  mp_code: string | null;
  gross_load_kw: number | string | null;
  behind_meter_gen_kw: number | string | null;
  net_load_kw: number | string | null;
  load_reactive_kvar: number | string | null;
  power_factor: number | null;
}

export interface DemandTelemetryInput {
  gross_load_kw: number | null;
  behind_meter_gen_kw: number | null;
  net_load_kw: number | null;
  load_reactive_kvar: number | null;
}

export interface DemandTelemetryCreateInput extends DemandTelemetryInput {
  metering_point_id: number;
  ts: string;
}

export interface DemandTelemetryPage {
  items: DemandTelemetry[];
  total: number;
  page: number;
  page_size: number;
}

export interface BulkDemandTelemetryRowError {
  row: number;
  errors: string[];
}

export interface BulkDemandTelemetryResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkDemandTelemetryRowError[];
  metering_points: string[];
}

export interface DemandTelemetrySeries {
  metering_point_id: number;
  mp_code: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  points: Record<string, number | string | null>[];
  timelines: Record<string, { states: string[]; segments: StateSegment[] }>;
  refs: Record<string, number | null>;
  tariff: {
    name: string;
    demand_charge_per_kw: number;
    peak_window_start: number | null;
    peak_window_end: number | null;
    ratchet_pct: number;
    measurement_minutes: number | null;
  } | null;
}
