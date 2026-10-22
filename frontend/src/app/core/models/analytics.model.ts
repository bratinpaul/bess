export interface DailySummary {
  date: string;
  system_id: number;
  system_name: string;
  sample_count: number;
  min_soc: number | null;
  max_soc: number | null;
  avg_soc: number | null;
  min_pack_voltage: number | null;
  max_pack_voltage: number | null;
  peak_charge_power: number | null;
  peak_discharge_power: number | null;
  max_cell_temp: number | null;
  max_cell_imbalance: number | null;
  total_energy_charged: number | null;
  total_energy_discharged: number | null;
  round_trip_efficiency_pct: number | null;
  equiv_full_cycles: number | null;
  alarm_samples: number;
  ending_soh: number | null;
  avg_ambient_temp: number | null;
}

export interface TelemetryDateRange {
  min_date: string | null;
  max_date: string | null;
}
