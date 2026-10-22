import { StateSegment } from './system-telemetry.model';

export interface WeatherStation {
  station_id: number;
  station_code: string;
  provider: string | null;
  site_id: number | null;
  site_name: string | null;
  latitude: number | null;
  longitude: number | null;
  readings: number;
  first_ts: string | null;
  last_ts: string | null;
}

export interface WeatherReading {
  station_id: number;
  ts: string;
  station_code: string | null;
  temp_c: number | string | null;
  ghi_wm2: number | string | null;
  humidity_pct: number | string | null;
  wind_ms: number | string | null;
  cloud_fraction: number | string | null;
  dew_point_c: number | null;
}

export interface WeatherInput {
  temp_c: number | null;
  ghi_wm2: number | null;
  humidity_pct: number | null;
  wind_ms: number | null;
  cloud_fraction: number | null;
}

export interface WeatherCreateInput extends WeatherInput {
  station_id: number;
  ts: string;
}

export interface WeatherPage {
  items: WeatherReading[];
  total: number;
  page: number;
  page_size: number;
}

export interface BulkWeatherRowError {
  row: number;
  errors: string[];
}

export interface BulkWeatherResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: BulkWeatherRowError[];
  stations: string[];
}

export interface WeatherSeries {
  station_id: number;
  station_code: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  points: Record<string, number | string | null>[];
  timelines: Record<string, { states: string[]; segments: StateSegment[] }>;
  refs: Record<string, number | null>;
}
