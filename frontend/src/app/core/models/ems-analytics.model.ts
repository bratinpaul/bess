export interface EmsDailySummary {
  date: string;
  ems_id: number;
  ems_code: string;
  sample_count: number;
  peak_grid_import_kw: number | null;
  peak_grid_export_kw: number | null;
  energy_imported_kwh: number | null;
  energy_exported_kwh: number | null;
  net_market_revenue_usd: number | null;
  avg_market_price: number | null;
  max_market_price: number | null;
  avg_realized_export_price: number | null;
  rms_tracking_error_kw: number | null;
  aux_energy_kwh: number | null;
  availability_pct: number | null;
  avg_plant_soc: number | null;
}

export interface EmsTelemetryDateRange {
  min_date: string | null;
  max_date: string | null;
}
