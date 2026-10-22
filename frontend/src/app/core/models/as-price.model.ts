export interface AsPrice {
  product_id: number;
  product_code: string;
  /** ISO timestamp with offset (plant / market time). */
  delivery_start: string;
  block_minutes: number;
  capacity_price_mw: number | null;
  performance_price: number | null;
}

/** Product and delivery start are the key; only these change on edit. At least one price is required. */
export interface AsPriceInput {
  block_minutes: number;
  capacity_price_mw: number | null;
  performance_price: number | null;
}

export interface AsPriceCreateInput extends AsPriceInput {
  product_id: number;
  /** Local plant time, e.g. 2026-08-01T05:00:00 (no zone). */
  delivery_start: string;
}

export interface AsPriceStats {
  blocks: number;
  first_start: string | null;
  last_start: string | null;
  avg_capacity: number | null;
  min_capacity: number | null;
  max_capacity: number | null;
  avg_performance: number | null;
  max_performance: number | null;
}

export interface AsPricePage {
  items: AsPrice[];
  total: number;
  page: number;
  page_size: number;
  stats: AsPriceStats;
}

export interface AsProduct {
  product_id: number;
  product_code: string;
  name: string;
  direction: string | null;
  min_bid_mw: number | null;
  sustain_minutes: number | null;
  response_seconds: number | null;
  settlement: string | null;
  description: string | null;
  market_code: string;
  currency: string;
  blocks: number;
}

export interface BulkAsPriceResult {
  filename: string;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  updated: number;
  error_count: number;
  errors: { row: number; errors: string[] }[];
  products: string[];
  first_start: string | null;
  last_start: string | null;
}
