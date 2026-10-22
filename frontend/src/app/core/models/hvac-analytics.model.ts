export interface HvacDailySummary {
  date: string;
  hvac_id: number;
  hvac_code: string;
  sample_count: number;
  energy_kwh: number | null;
  peak_power_kw: number | null;
  max_heat_load_kw: number | null;
  avg_cop: number | null;
  max_return_temp_c: number | null;
  max_enclosure_temp_c: number | null;
  max_humidity_pct: number | null;
  avg_ambient_c: number | null;
  cooling_hours: number | null;
  free_cooling_hours: number | null;
  compressor_duty_cycle_pct: number | null;
  cooling_time_hours: number | null;
}

export interface HvacTelemetryDateRange {
  min_date: string | null;
  max_date: string | null;
}

export interface HvacLatestReading {
  hvac_id: number;
  hvac_code: string;
  ts: string;
  cooling_mode: string | null;
  coolant_supply_temp_c: number | null;
  coolant_return_temp_c: number | null;
  battery_heat_load_kw: number | null;
  hvac_power_kw: number | null;
  cop: number | null;
  enclosure_temp_c: number | null;
  alarm_level: number | null;
  alarm_flags: string | null;
}
