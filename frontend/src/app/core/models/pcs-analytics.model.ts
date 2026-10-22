export interface PcsDailySummary {
  date: string;
  pcs_id: number;
  pcs_code: string;
  sample_count: number;
  peak_charge_power_ac: number | null;
  peak_discharge_power_ac: number | null;
  peak_apparent_power: number | null;
  min_power_factor: number | null;
  max_reactive_power: number | null;
  min_ac_frequency_closed: number | null;
  max_ac_frequency: number | null;
  avg_efficiency: number | null;
  max_igbt_temp: number | null;
  total_energy_imported: number | null;
  total_energy_exported: number | null;
  ac_ac_round_trip_eff_pct: number | null;
  alarm_samples: number;
  volt_var_intervals: number;
  freq_watt_intervals: number;
}

export interface PcsTelemetryDateRange {
  min_date: string | null;
  max_date: string | null;
}
