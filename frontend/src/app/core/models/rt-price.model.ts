export interface RtPrice {
  node_id: number;
  node_code: string;
  /** ISO timestamp with offset (plant / market time). */
  interval_start: string;
  block_minutes: number;
  price_mwh: number;
  /** Day-ahead price of the hour the interval falls in. */
  dam_price_mwh: number | null;
  /** RT − DAM. */
  spread_mwh: number | null;
}

/** Node and interval start are the key; only these change on edit. */
export interface RtPriceInput {
  block_minutes: number;
  price_mwh: number;
}

export interface RtPriceCreateInput extends RtPriceInput {
  node_id: number;
  /** Local plant time, e.g. 2026-08-01T05:15:00 (no zone). */
  interval_start: string;
}

export interface RtPriceStats {
  intervals: number;
  first_start: string | null;
  last_start: string | null;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  stddev_price: number | null;
  avg_spread: number | null;
  matched_dam: number;
}

export interface RtPricePage {
  items: RtPrice[];
  total: number;
  page: number;
  page_size: number;
  stats: RtPriceStats;
}

export interface BulkRtPriceResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  nodes: string[];
  first_start: string | null;
  last_start: string | null;
}
