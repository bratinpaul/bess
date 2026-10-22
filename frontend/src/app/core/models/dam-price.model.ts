export interface DamPrice {
  node_id: number;
  node_code: string;
  /** ISO timestamp with offset (plant / market time). */
  delivery_start: string;
  block_minutes: number;
  price_mwh: number;
  cleared_mw: number | null;
}

/** Node and delivery start are the key; only these change on edit. */
export interface DamPriceInput {
  block_minutes: number;
  price_mwh: number;
  cleared_mw: number | null;
}

export interface DamPriceCreateInput extends DamPriceInput {
  node_id: number;
  /** Local plant time, e.g. 2026-08-01T05:00:00 (no zone). */
  delivery_start: string;
}

export interface DamPriceStats {
  blocks: number;
  first_start: string | null;
  last_start: string | null;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  total_cleared_mwh: number | null;
}

export interface DamPricePage {
  items: DamPrice[];
  total: number;
  page: number;
  page_size: number;
  stats: DamPriceStats;
}

export interface PriceNode {
  node_id: number;
  node_code: string;
  name: string | null;
  node_type: string | null;
  market_code: string;
  currency: string;
  timezone: string;
  site_id: number | null;
  site_code: string | null;
  blocks: number;
}

export interface BulkDamPriceResult {
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
