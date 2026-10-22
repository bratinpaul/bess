/** RUL aging snapshots (battery_master.aging_snapshot) per battery system (battery_master.battery_system). */

export interface AgingSnapshotValues {
  age_days: number | null;
  calendar_age_years: number | null;
  cum_throughput_mwh: number | null;
  equiv_full_cycles: number | null;
  avg_dod_pct: number | null;
  avg_cell_temp_c: number | null;
  days_at_high_soc: number | null;
  soh_pct: number | null;
  internal_resistance_mohm: number | null;
  rul_cycles: number | null;
  rul_days: number | null;
  is_censored: boolean | null;
  eol_reached: boolean | null;
}

export interface AgingSnapshot extends AgingSnapshotValues {
  system_id: number;
  system_code: string | null;
  snapshot_date: string;
}

export interface AgingSnapshotPage {
  items: AgingSnapshot[];
  total: number;
  page: number;
  page_size: number;
}

export interface AgingSystemSummary {
  system_id: number;
  system_code: string;
  snapshots: number;
  first_date: string | null;
  last_date: string | null;
  latest_soh_pct: number | null;
  latest_rul_days: number | null;
  eol_reached: boolean | null;
}
