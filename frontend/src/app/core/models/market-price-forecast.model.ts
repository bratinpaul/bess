export interface PriceForecast {
  node_id: number;
  node_code: string;
  /** ISO timestamps with offset (plant / market time). */
  issued_at: string;
  target_ts: string;
  horizon_h: number | null;
  p10_mwh: number | null;
  p50_mwh: number;
  p90_mwh: number | null;
  model: string | null;
  /** Realized DAM price of the target hour, P50 − actual, and whether the actual fell inside P10–P90. */
  actual_mwh: number | null;
  error_mwh: number | null;
  in_band: boolean | null;
}

/** Node, vintage and target are the key (and fix the horizon); only these change on edit. */
export interface PriceForecastInput {
  p10_mwh: number | null;
  p50_mwh: number;
  p90_mwh: number | null;
  model: string | null;
}

export interface PriceForecastCreateInput extends PriceForecastInput {
  node_id: number;
  /** Local plant time without zone, e.g. 2026-08-01T10:00:00. */
  issued_at: string;
  target_ts: string;
}

export interface PriceForecastStats {
  rows: number;
  vintages: number;
  first_target: string | null;
  last_target: string | null;
  avg_p50: number | null;
  avg_band: number | null;
  matched_actual: number;
  mae: number | null;
  bias: number | null;
  coverage_pct: number | null;
}

export interface PriceForecastPage {
  items: PriceForecast[];
  total: number;
  page: number;
  page_size: number;
  stats: PriceForecastStats;
}

export interface ForecastVintage {
  node_id: number;
  node_code: string;
  issued_at: string;
  rows: number;
  first_target: string;
  last_target: string;
  models: string[];
}

export interface BulkPriceForecastResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  nodes: string[];
  vintages: number;
  first_target: string | null;
  last_target: string | null;
}
