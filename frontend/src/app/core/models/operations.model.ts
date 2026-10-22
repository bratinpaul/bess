export interface LatestReading {
  ts: string | null;
  soc_pct: number | null;
  soh_pct: number | null;
  power_kw: number | null;
  mode_code: string | null;
  bms_mode_code: string | null;
  contactor_state: string | null;
  breaker_state: string | null;
  bms_alarm_level: number | null;
  pcs_alarm_level: number | null;
}

export interface PeriodPerformance {
  start_date: string;
  end_date: string;
  days: number;
  avg_soc: number | null;
  min_soc: number | null;
  max_soc: number | null;
  soh_at_start: number | null;
  energy_discharged_mwh: number | null;
  energy_charged_mwh: number | null;
  energy_throughput_mwh: number | null;
  dc_round_trip_eff_pct: number | null;
  ac_round_trip_eff_pct: number | null;
  equiv_full_cycles: number | null;
  cycles_per_day: number | null;
  peak_charge_power_ac_kw: number | null;
  peak_discharge_power_ac_kw: number | null;
  avg_conversion_eff_pct: number | null;
  min_power_factor: number | null;
  max_cell_temp_c: number | null;
  max_igbt_temp_c: number | null;
  availability_pct: number | null;
  bms_alarm_samples: number;
  pcs_alarm_samples: number;
  bms_sample_count: number;
  pcs_sample_count: number;
}

export interface OperationsOverview {
  system_id: number;
  system_name: string;
  site_name: string | null;
  chemistry_code: string | null;
  rated_power_mw: number | null;
  rated_energy_mwh: number | null;
  pcs_codes: string[];
  latest: LatestReading;
  period: PeriodPerformance;
}
