import { StateSegment } from './system-telemetry.model';
import { WeatherStation } from './weather.model';

export interface ForecastRun {
  station_id: number;
  issued_at: string;
  points: number;
  first_valid: string;
  last_valid: string;
}

export interface WeatherForecastLookups {
  stations: WeatherStation[];
  runs: ForecastRun[];
}

export interface WeatherForecastValue {
  station_id: number;
  issued_at: string;
  valid_at: string;
  station_code: string | null;
  lead_h: number | null;
  temp_c: number | string | null;
  ghi_wm2: number | string | null;
  actual_temp_c: number | null;
  actual_ghi_wm2: number | null;
  temp_error_c: number | null;
  ghi_error_wm2: number | null;
}

export interface WeatherForecastInput {
  temp_c: number | null;
  ghi_wm2: number | null;
}

export interface WeatherForecastCreateInput extends WeatherForecastInput {
  station_id: number;
  issued_at: string;
  valid_at: string;
}

export interface WeatherForecastPage {
  items: WeatherForecastValue[];
  total: number;
  page: number;
  page_size: number;
}

export interface BulkWeatherForecastResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  stations: string[];
  runs: number;
}

export interface WeatherForecastSeries {
  station_id: number;
  station_code: string | null;
  issued_at: string | null;
  start: string | null;
  end: string | null;
  bucket_seconds: number;
  raw_interval_seconds: number | null;
  points: Record<string, number | string | null>[];
  timelines: Record<string, { states: string[]; segments: StateSegment[] }>;
  refs: Record<string, number | null>;
}

export interface LeadSkill {
  lead_h: number;
  n: number;
  temp_mae: number | null;
  temp_bias: number | null;
  ghi_mae: number | null;
  ghi_bias: number | null;
  ghi_n: number;
}

export interface WeatherForecastSkill {
  station_id: number;
  runs: number;
  matched: number;
  forecasts: number;
  temp_mae: number | null;
  temp_bias: number | null;
  temp_rmse: number | null;
  ghi_mae: number | null;
  ghi_bias: number | null;
  ghi_rmse: number | null;
  by_lead: LeadSkill[];
}
